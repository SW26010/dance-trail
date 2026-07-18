import json
import socket
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from dancing_log.overlay_server import (
    MountedOverlayAdapter,
    OverlayEventStreams,
    OverlayServer,
    OverlayState,
    send_overlay_events,
    _OVERLAY_HTML,
)
import dancing_log.overlay_server as overlay_server_module


class OverlayServerTest(unittest.TestCase):
    def test_stop_closes_partial_ordinary_request_before_it_can_run(self):
        accepted = threading.Event()
        original_process_request = overlay_server_module._OverlayHTTPServer.process_request

        def observe_accept(http_server, request, client_address):
            accepted.set()
            return original_process_request(http_server, request, client_address)

        server = OverlayServer(port=0)
        client: socket.socket | None = None
        with patch.object(
            overlay_server_module._OverlayHTTPServer,
            "process_request",
            observe_accept,
        ):
            server.start()
            http_server = server._server
            try:
                client = socket.create_connection(
                    (server.host, server.port), timeout=1.0
                )
                client.sendall(b"GET /api/overlay/state HTTP/1.1\r\n")
                self.assertTrue(accepted.wait(timeout=1.0))

                server.stop()

                try:
                    client.sendall(
                        f"Host: {server.host}:{server.port}\r\n\r\n".encode("ascii")
                    )
                except OSError:
                    pass
                try:
                    response = client.recv(4096)
                except OSError:
                    response = b""
                self.assertNotIn(b"200 OK", response)
                self.assertEqual(http_server.active_request_count, 0)
            finally:
                if client is not None:
                    client.close()
                if server._server is not None:
                    server.stop()

    def test_start_failure_closes_bound_listener_without_shutdown(self):
        server = OverlayServer(port=0)
        try:
            with (
                patch(
                    "dancing_log.http_request_lifecycle.threading.Thread.start",
                    side_effect=RuntimeError("thread start failed"),
                ),
                self.assertRaisesRegex(RuntimeError, "thread start failed"),
            ):
                server.start()

            self.assertIsNone(server._server)
            probe = socket.socket()
            try:
                probe.bind((server.host, server.port))
            finally:
                probe.close()
        finally:
            if server._server is not None:
                server._server.server_close()
                server._server = None

    def test_concurrent_publishers_cannot_overwrite_newer_mailbox_state(self):
        state = OverlayState()
        subscriber = state.subscribe()
        older_blocked = threading.Event()
        release_older = threading.Event()
        newer_finished = threading.Event()
        put_latest = overlay_server_module._put_latest

        def controlled_put(queue, item):
            if item.get("status", {}).get("message") == "older":
                older_blocked.set()
                release_older.wait(timeout=2.0)
            put_latest(queue, item)

        def publish_newer() -> None:
            state.publish_status({"event_type": "test-update", "message": "newer"})
            newer_finished.set()

        try:
            with patch.object(overlay_server_module, "_put_latest", controlled_put):
                older = threading.Thread(
                    target=state.publish_status,
                    args=({"event_type": "test-update", "message": "older"},),
                )
                older.start()
                self.assertTrue(older_blocked.wait(timeout=1.0))
                newer = threading.Thread(target=publish_newer)
                newer.start()
                newer_finished.wait(timeout=0.2)
                release_older.set()
                older.join(timeout=1.0)
                newer.join(timeout=1.0)

            self.assertFalse(older.is_alive())
            self.assertFalse(newer.is_alive())
            queued = subscriber.get_nowait()
            self.assertEqual(queued["status"]["message"], "newer")
            self.assertEqual(queued["sequence"], state.snapshot()["sequence"])
        finally:
            release_older.set()
            state.unsubscribe(subscriber)

    def test_overlay_state_slow_subscriber_keeps_latest_snapshot(self):
        state = OverlayState()
        subscriber = state.subscribe()

        try:
            for value in range(12):
                state.publish_status(
                    {
                        "event_type": "test-update",
                        "message": str(value),
                    }
                )

            self.assertEqual(subscriber.qsize(), 1)
            queued = subscriber.get_nowait()
            self.assertEqual(queued["status"]["message"], "11")
            self.assertEqual(
                queued["status"]["message"],
                state.snapshot()["status"]["message"],
            )
        finally:
            state.unsubscribe(subscriber)

    def test_event_stream_stop_closes_connection_blocked_in_write(self):
        state = OverlayState()
        streams = OverlayEventStreams(state)
        write_started = threading.Event()

        class BlockingConnection:
            def __init__(self) -> None:
                self.closed = threading.Event()

            def shutdown(self, _how) -> None:
                self.closed.set()

            def close(self) -> None:
                self.closed.set()

        connection = BlockingConnection()

        class BlockingWriter:
            def write(self, payload: bytes) -> int:
                write_started.set()
                if connection.closed.wait(timeout=2.0):
                    raise OSError("connection closed")
                return len(payload)

            def flush(self) -> None:
                return

        class Handler:
            wfile = BlockingWriter()
            close_connection = False

            def __init__(self) -> None:
                self.connection = connection

            def send_response(self, _status: int) -> None:
                return

            def send_header(self, _name: str, _value: str) -> None:
                return

            def end_headers(self) -> None:
                return

        worker = threading.Thread(
            target=send_overlay_events,
            args=(Handler(), streams),
            daemon=True,
        )
        worker.start()
        self.assertTrue(write_started.wait(timeout=1.0))
        self.assertEqual(state.subscriber_count, 1)

        try:
            streams.stop()
            self.assertTrue(connection.closed.wait(timeout=0.5))
            worker.join(timeout=0.5)
            self.assertFalse(worker.is_alive())
            self.assertTrue(streams.wait_until_drained(timeout=0.1))
            self.assertEqual(state.subscriber_count, 0)
        finally:
            connection.close()
            worker.join(timeout=2.0)

    def test_overlay_state_distinguishes_inactive_from_enabled_waiting(self):
        state = OverlayState(enabled=False)

        inactive = state.snapshot()
        self.assertFalse(inactive["overlay_enabled"])
        self.assertIsNone(inactive["current"])

        waiting = state.publish_status(
            {
                "event_type": "overlay-started",
                "message": "Waiting for playback",
                "overlay_enabled": True,
                "clear_current": True,
            }
        )
        self.assertTrue(waiting["overlay_enabled"])
        self.assertIsNone(waiting["current"])
        self.assertEqual(waiting["status"]["message"], "Waiting for playback")

    def test_mounted_overlay_adapter_clears_without_destroying_shared_state(self):
        state = OverlayState()
        adapter = MountedOverlayAdapter(
            state,
            url="http://127.0.0.1:8787/overlay",
        )
        adapter.publish(
            {
                "event_key": "wannadance:3114#1",
                "dance_system_key": "wannadance",
                "dance_external_id": "3114",
                "actual_play_at": "2026.05.17 15:30:10",
            }
        )

        adapter.close()

        snapshot = state.snapshot()
        self.assertFalse(snapshot["overlay_enabled"])
        self.assertIsNone(snapshot["current"])
        self.assertEqual(snapshot["status"]["event_type"], "overlay-stopped")
        self.assertEqual(adapter.url, "http://127.0.0.1:8787/overlay")

    def test_mounted_overlay_restore_uses_event_time_not_callback_order(self):
        state = OverlayState(enabled=False)
        adapter = MountedOverlayAdapter(
            state,
            url="http://127.0.0.1:8787/overlay",
        )
        adapter.publish(
            {
                "event_key": "pypydance:newer#1",
                "dance_external_id": "newer",
                "actual_play_at": "2026.07.18 12:00:00",
            }
        )
        adapter.publish(
            {
                "event_key": "pypydance:older#1",
                "dance_external_id": "older",
                "actual_play_at": "2026.07.18 11:00:00",
            }
        )

        snapshot = adapter.enable()

        self.assertEqual(snapshot["current"]["dance_external_id"], "newer")

    def test_borrowed_mounted_overlay_publisher_does_not_close_owner(self):
        state = OverlayState()
        adapter = MountedOverlayAdapter(
            state,
            url="http://127.0.0.1:8787/overlay",
        )
        publisher = adapter.borrow()
        publisher.publish(
            {
                "event_key": "wannadance:3114#1",
                "dance_system_key": "wannadance",
                "dance_external_id": "3114",
                "actual_play_at": "2026.05.17 15:30:10",
            }
        )

        publisher.close()

        snapshot = state.snapshot()
        self.assertTrue(snapshot["overlay_enabled"])
        self.assertEqual(snapshot["current"]["dance_external_id"], "3114")

    def test_overlay_status_can_clear_current_without_dropping_history(self):
        state = OverlayState()
        state.publish(
            {
                "event_key": "wannadance:3114#1",
                "dance_system_key": "wannadance",
                "dance_external_id": "3114",
                "actual_play_at": "2026.05.17 15:30:10",
            }
        )

        snapshot = state.publish_status(
            {
                "event_type": "room-left",
                "message": "Room left",
                "clear_current": True,
            }
        )

        self.assertIsNone(snapshot["current"])
        self.assertEqual(snapshot["events"][0]["dance_external_id"], "3114")
        self.assertEqual(snapshot["status"]["message"], "Room left")

        resumed = state.publish(
            {
                "event_key": "pypydance:4661#1",
                "dance_system_key": "pypydance",
                "dance_external_id": "4661",
                "actual_play_at": "2026.05.17 15:31:00",
            }
        )
        self.assertEqual(resumed["current"]["dance_external_id"], "4661")

    def test_overlay_keeps_completed_event_current_until_cleared(self):
        state = OverlayState()
        state.publish(
            {
                "event_key": "pypydance:1845#1",
                "dance_system_key": "pypydance",
                "dance_external_id": "1845",
                "actual_play_at": "2026.05.18 15:57:11.690075",
                "duration_seconds": 245,
            }
        )

        completed = state.publish(
            {
                "event_key": "pypydance:1845#1",
                "dance_system_key": "pypydance",
                "dance_external_id": "1845",
                "actual_play_at": "2026.05.18 15:57:11.690075",
                "duration_seconds": 245,
                "completion_status": "completed",
                "completion_reason": "observed_completion_threshold",
            }
        )
        self.assertEqual(completed["current"]["dance_external_id"], "1845")

        cleared = state.publish_status(
            {
                "event_type": "application-quit",
                "message": "VRChat ended",
                "clear_current": True,
            }
        )
        self.assertIsNone(cleared["current"])

    def test_overlay_state_and_static_page_are_local(self):
        server = OverlayServer(port=0)
        server.start()
        try:
            self.assertEqual(server.host, "127.0.0.1")
            server.publish(
                {
                    "event_key": "wannadance:3114#1",
                    "live_event_key": "live-key",
                    "dance_system_key": "wannadance",
                    "dance_external_id": "3114",
                    "actual_play_at": "2026.05.17 15:30:10",
                    "duration_seconds": 180,
                    "video_name": "Example Song",
                    "source_type": "player",
                    "source_display_name": "Alice",
                    "actual_play_method": "usharp_delayed_video_ready",
                }
            )

            with urlopen(
                f"http://127.0.0.1:{server.port}/api/overlay/state",
                timeout=2,
            ) as response:
                state = json.loads(response.read().decode("utf-8"))
            self.assertTrue(state["overlay_enabled"])
            self.assertEqual(state["current"]["dance_external_id"], "3114")
            self.assertEqual(state["current_view"]["source_label"], "source player: Alice")
            self.assertEqual(state["current_view"]["timer"]["mode"], "elapsed_total")

            with urlopen(f"http://127.0.0.1:{server.port}/overlay", timeout=2) as response:
                html = response.read().decode("utf-8")
            self.assertIn("/api/overlay/events", html)
            self.assertIn("/api/overlay/state", html)
            self.assertNotIn("https://", html)
            self.assertNotIn("http://", html)
        finally:
            server.stop()

    def test_standalone_overlay_rejects_non_local_host(self):
        server = OverlayServer(port=0)
        server.start()
        try:
            request = Request(
                f"http://127.0.0.1:{server.port}/api/overlay/state",
                headers={"Host": f"evil.example:{server.port}"},
            )
            with self.assertRaises(HTTPError) as context:
                urlopen(request, timeout=2)
            context.exception.close()
            self.assertEqual(context.exception.code, 403)
        finally:
            server.stop()

    def test_standalone_overlay_stop_reports_sse_drain_timeout(self):
        server = OverlayServer(port=0)
        server.start()
        event_streams = server._server.event_streams
        with (
            patch.object(
                event_streams,
                "wait_until_drained",
                return_value=False,
            ),
            self.assertRaisesRegex(TimeoutError, "event stream"),
        ):
            server.stop()

        self.assertIsNone(server._server)

    def test_overlay_events_stream_sends_snapshot(self):
        server = OverlayServer(port=0)
        server.start()
        try:
            server.publish(
                {
                    "event_key": "pypydance:4661#1",
                    "dance_system_key": "pypydance",
                    "dance_external_id": "4661",
                    "actual_play_at": "2026.05.17 17:17:26.723128",
                    "video_name": "PyPy Song",
                    "source_type": "random",
                }
            )
            with urlopen(
                f"http://127.0.0.1:{server.port}/api/overlay/events",
                timeout=2,
            ) as response:
                lines = []
                for _ in range(4):
                    line = response.readline().decode("utf-8").strip()
                    if line:
                        lines.append(line)
                    if line.startswith("data: "):
                        break

            data_line = next(line for line in lines if line.startswith("data: "))
            snapshot = json.loads(data_line.removeprefix("data: "))
            self.assertEqual(snapshot["current"]["dance_system_key"], "pypydance")
            self.assertEqual(snapshot["current"]["source_type"], "random")
            self.assertEqual(snapshot["current_view"]["source_label"], "source random")
        finally:
            server.stop()

    def test_overlay_html_consumes_view_model_contract(self):
        self.assertIn("Loading overlay state", _OVERLAY_HTML)
        self.assertIn("Overlay inactive", _OVERLAY_HTML)
        self.assertIn("enable Live Overlay in WebUI", _OVERLAY_HTML)
        self.assertIn("watcher active", _OVERLAY_HTML)
        self.assertIn("snapshot.overlay_enabled !== true", _OVERLAY_HTML)
        self.assertIn("state.currentView = snapshot.current_view || null;", _OVERLAY_HTML)
        self.assertIn("if (sequence < state.sequence) return;", _OVERLAY_HTML)
        self.assertIn("state.sequence = sequence;", _OVERLAY_HTML)
        self.assertIn(
            'nodes.sourcePlayer.textContent = view.source_label || "source unknown";',
            _OVERLAY_HTML,
        )
        self.assertIn("formatTimer(view.timer, elapsed)", _OVERLAY_HTML)
        self.assertNotIn("function sourceLabel", _OVERLAY_HTML)
        self.assertNotIn("function primaryTitle", _OVERLAY_HTML)
        self.assertNotIn("function systemLabel", _OVERLAY_HTML)
        self.assertNotIn("event.source_type", _OVERLAY_HTML)
        self.assertNotIn("event.source_display_name", _OVERLAY_HTML)
        self.assertNotIn("event.duration_seconds", _OVERLAY_HTML)
        self.assertNotIn("remaining ", _OVERLAY_HTML)
        self.assertNotIn(
            'source player: ${event.source_display_name || "unknown"}',
            _OVERLAY_HTML,
        )


if __name__ == "__main__":
    unittest.main()
