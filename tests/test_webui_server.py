import json
from io import BytesIO
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from dancing_log.app_paths import DEFAULT_CONFIG, save_app_config
from dancing_log.data_operations import DataOperationResult, operation_catalog_snapshot
from dancing_log.live_app_session import LiveAppSessionRuntime
from dancing_log.playback_projection import (
    EFFECTIVE_PLAYBACK_ACCEPTED,
    EFFECTIVE_PLAYBACK_EXCLUDED,
    EFFECTIVE_PLAYBACK_NEEDS_ATTENTION,
    set_manual_playback_decision,
)
from dancing_log.webui_endpoints import (
    control_live_overlay_from_payload,
    load_catalog_snapshot,
    load_insights_snapshot,
    load_operations_snapshot,
    load_summary_snapshot,
    load_timeline_snapshot,
    update_playback_review_from_payload,
)
from dancing_log.storage import (
    WANNA_SYSTEM_KEY,
    connect_db,
    ensure_dance_track,
    upsert_live_playback_event,
)
from dancing_log.webui_server import (
    RequestRejected,
    WebUiRuntime,
    WebUiServer,
    _WebUiHandler,
    _WebUiHTTPServer,
)
from dancing_log.webui_routes import WebUiRouteResponse, handle_get_request
from dancing_log.webui_settings import load_config_snapshot
from dancing_log.windows_picker import (
    FOS_FILEMUSTEXIST,
    FOS_FORCEFILESYSTEM,
    FOS_PATHMUSTEXIST,
    FOS_PICKFOLDERS,
    _file_dialog_options,
    _run_windows_picker,
)
from tests.playback_record_helpers import insert_playback_record


def wait_for_call_count(calls: list[dict], count: int) -> None:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if len(calls) >= count:
            return
        time.sleep(0.01)
    raise AssertionError(f"expected {count} watcher calls, got {len(calls)}")


class WebUiServerTest(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Windows listener semantics")
    def test_second_server_cannot_share_the_same_local_address(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = WebUiServer(port=0, app_root=tmp)
            first.start()
            second = WebUiServer(port=first.port, app_root=tmp)
            try:
                with self.assertRaises(OSError):
                    second.start()
            finally:
                second.stop()
                first.stop()

    def test_mount_failure_closes_bound_listener(self):
        class RejectingSession:
            def mount_overlay(self, _overlay) -> None:
                raise RuntimeError("mount failed")

        with tempfile.TemporaryDirectory() as tmp:
            server = WebUiServer(
                port=0,
                app_root=tmp,
                session_runtime=RejectingSession(),
            )
            closed: list[tuple[str, int]] = []
            original_server_close = _WebUiHTTPServer.server_close

            def record_server_close(http_server) -> None:
                closed.append(http_server.server_address)
                original_server_close(http_server)

            with (
                patch.object(
                    _WebUiHTTPServer,
                    "server_close",
                    record_server_close,
                ),
                self.assertRaisesRegex(RuntimeError, "mount failed"),
            ):
                server.start()

            self.assertEqual(closed, [(server.host, server.port)])

            probe = socket.socket()
            try:
                probe.bind((server.host, server.port))
            finally:
                probe.close()

    def test_start_failure_closes_bound_listener_without_shutdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = WebUiServer(port=0, app_root=tmp)
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

    def test_startup_maintenance_skips_database_owned_by_live_watcher(self):
        watcher_started = threading.Event()

        def blocking_watch_vrc_logs(**kwargs):
            watcher_started.set()
            kwargs["stop_event"].wait(timeout=2.0)
            return {"finished": True}

        with tempfile.TemporaryDirectory() as tmp:
            runtime = LiveAppSessionRuntime(
                app_root=tmp,
                watch_vrc_logs_func=blocking_watch_vrc_logs,
            )
            runtime.start_watcher()
            self.assertTrue(watcher_started.wait(timeout=1.0))
            try:
                with patch(
                    "dancing_log.storage.repair_stale_watcher_pending_records"
                ) as repair:
                    server = WebUiServer(port=0, app_root=tmp)
                repair.assert_not_called()
                server.stop()
            finally:
                runtime.close()

    def test_startup_maintenance_failure_is_visible_in_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "dancing_log.storage.repair_stale_watcher_pending_records",
                side_effect=RuntimeError("repair exploded"),
            ):
                server = WebUiServer(port=0, app_root=tmp)
            try:
                summary = load_summary_snapshot(server.runtime)

                self.assertTrue(
                    any(
                        "startup maintenance failed" in warning.lower()
                        and "repair exploded" in warning
                        for warning in summary["config_warnings"]
                    ),
                    summary["config_warnings"],
                )
                self.assertEqual(len(summary["startup_warnings"]), 1)
                self.assertIn("repair exploded", summary["startup_warnings"][0])
            finally:
                server.stop()

    def test_partial_valid_post_body_cannot_block_shutdown_forever(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = WebUiServer(port=0, app_root=tmp)
            server.start()
            token = self._csrf_token(server)
            client: socket.socket | None = None
            stop_thread = threading.Thread(target=server.stop)
            try:
                with patch.object(
                    server._server,
                    "request_read_deadline_seconds",
                    10.0,
                ):
                    client = socket.create_connection(
                        (server.host, server.port), timeout=1.0
                    )
                    client.sendall(
                        (
                            "POST /api/config HTTP/1.1\r\n"
                            f"Host: {server.host}:{server.port}\r\n"
                            "Content-Type: application/json\r\n"
                            f"Origin: {server.url.rstrip('/')}\r\n"
                            f"X-Dancing-Log-CSRF: {token}\r\n"
                            "Content-Length: 100\r\n"
                            "Connection: keep-alive\r\n"
                            "\r\n"
                            "{"
                        ).encode("ascii")
                    )
                    deadline = time.monotonic() + 1.0
                    while (
                        server._server.active_request_count == 0
                        and time.monotonic() < deadline
                    ):
                        time.sleep(0.01)
                    self.assertEqual(server._server.active_request_count, 1)

                    stop_thread.start()
                    stop_thread.join(timeout=0.8)

                self.assertFalse(stop_thread.is_alive())
            finally:
                if client is not None:
                    client.close()
                stop_thread.join(timeout=2.0)
                if server._server is not None:
                    server.stop()

    def test_partial_header_remains_open_until_absolute_read_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = WebUiServer(port=0, app_root=tmp)
            server.start()
            client: socket.socket | None = None
            try:
                with patch.object(
                    server._server,
                    "request_read_deadline_seconds",
                    0.6,
                ):
                    client = socket.create_connection(
                        (server.host, server.port), timeout=1.0
                    )
                    client.sendall(b"GET /api/summary HTTP/1.1\r\n")
                    registration_deadline = time.monotonic() + 1.0
                    while (
                        server._server.active_request_count == 0
                        and time.monotonic() < registration_deadline
                    ):
                        time.sleep(0.01)
                    self.assertEqual(server._server.active_request_count, 1)

                    time.sleep(0.35)
                    self.assertEqual(server._server.active_request_count, 1)

                    expiry_deadline = time.monotonic() + 0.6
                    while (
                        server._server.active_request_count != 0
                        and time.monotonic() < expiry_deadline
                    ):
                        time.sleep(0.01)
                    self.assertEqual(server._server.active_request_count, 0)
            finally:
                if client is not None:
                    client.close()
                if server._server is not None:
                    server.stop()

    def test_slow_header_cannot_extend_request_read_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = WebUiServer(port=0, app_root=tmp)
            server.start()
            self._assert_slow_request_expires(
                initial=b"POST /api/config HTTP/1.1",
                trickle=b" ",
                server=server,
            )

    def test_slow_body_cannot_extend_request_read_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = WebUiServer(port=0, app_root=tmp)
            server.start()
            token = self._csrf_token(server)
            initial = (
                "POST /api/config HTTP/1.1\r\n"
                f"Host: {server.host}:{server.port}\r\n"
                "Content-Type: application/json\r\n"
                f"Origin: {server.url.rstrip('/')}\r\n"
                f"X-Dancing-Log-CSRF: {token}\r\n"
                "Content-Length: 10000\r\n"
                "Connection: keep-alive\r\n"
                "\r\n"
                "{"
            ).encode("ascii")
            self._assert_slow_request_expires(
                initial=initial,
                trickle=b" ",
                server=server,
            )

    def test_webui_stop_closes_session_after_http_lifecycle_failure(self):
        events: list[str] = []

        def stop_http() -> None:
            events.append("http.stop")
            raise RuntimeError("HTTP lifecycle failed")

        fake_http_server = SimpleNamespace(stop_http=stop_http)
        session = SimpleNamespace(close=lambda: events.append("session.close"))
        server = WebUiServer.__new__(WebUiServer)
        server._server = fake_http_server
        server._mounted_overlay = None
        server._owns_session = True
        server.runtime = SimpleNamespace(session=session)

        with self.assertRaisesRegex(RuntimeError, "HTTP lifecycle failed"):
            server.stop()

        self.assertEqual(events, ["http.stop", "session.close"])
        self.assertIsNone(server._server)

    def test_webui_stop_waits_for_in_flight_post_handler(self):
        entered = threading.Event()
        release = threading.Event()
        request_errors: list[Exception] = []

        def blocking_post(_runtime, _target, _payload):
            entered.set()
            release.wait(timeout=2.0)
            return WebUiRouteResponse(
                200,
                "application/json; charset=utf-8",
                b"{}",
            )

        with tempfile.TemporaryDirectory() as tmp:
            server = WebUiServer(port=0, app_root=tmp)
            server.start()
            token = self._csrf_token(server)
            request = self._json_request(
                server,
                "api/config",
                {},
                token=token,
                origin=server.url.rstrip("/"),
            )

            def send_request() -> None:
                try:
                    with urlopen(request, timeout=2) as response:
                        response.read()
                except Exception as exc:
                    request_errors.append(exc)

            request_thread = threading.Thread(target=send_request)
            stop_thread = threading.Thread(target=server.stop)
            try:
                with patch(
                    "dancing_log.webui_server.handle_post_request",
                    side_effect=blocking_post,
                ):
                    request_thread.start()
                    self.assertTrue(entered.wait(timeout=1.0))
                    stop_thread.start()
                    stop_thread.join(timeout=0.8)
                    self.assertTrue(stop_thread.is_alive())

                    release.set()
                    request_thread.join(timeout=1.0)
                    stop_thread.join(timeout=2.0)

                self.assertFalse(request_thread.is_alive())
                self.assertFalse(stop_thread.is_alive())
                self.assertEqual(request_errors, [])
            finally:
                release.set()
                request_thread.join(timeout=2.0)
                stop_thread.join(timeout=2.0)
                if server._server is not None:
                    server.stop()

    def test_webui_terminal_stop_bounds_accepted_operation_drain_by_deadline(self):
        entered = threading.Event()
        release = threading.Event()
        request_errors: list[Exception] = []

        def blocking_post(_runtime, _target, _payload):
            entered.set()
            release.wait(timeout=2.0)
            return WebUiRouteResponse(
                200,
                "application/json; charset=utf-8",
                b"{}",
            )

        with tempfile.TemporaryDirectory() as tmp:
            server = WebUiServer(port=0, app_root=tmp)
            server.start()
            token = self._csrf_token(server)
            request = self._json_request(
                server,
                "api/config",
                {},
                token=token,
                origin=server.url.rstrip("/"),
            )

            def send_request() -> None:
                try:
                    with urlopen(request, timeout=2) as response:
                        response.read()
                except Exception as exc:
                    request_errors.append(exc)

            request_thread = threading.Thread(target=send_request)
            try:
                with patch(
                    "dancing_log.webui_server.handle_post_request",
                    side_effect=blocking_post,
                ):
                    request_thread.start()
                    self.assertTrue(entered.wait(timeout=1.0))
                    started = time.monotonic()
                    with self.assertRaisesRegex(TimeoutError, "shutdown deadline"):
                        server.stop(deadline=started + 0.05)
                    elapsed = time.monotonic() - started
            finally:
                release.set()
                request_thread.join(timeout=2.0)

        self.assertLess(elapsed, 0.3)
        self.assertFalse(request_thread.is_alive())

    def test_invalid_post_headers_are_rejected_without_waiting_for_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = WebUiServer(port=0, app_root=tmp)
            server.start()
            client = socket.create_connection((server.host, server.port), timeout=1.0)
            client.settimeout(0.5)
            try:
                client.sendall(
                    (
                        "POST /api/config HTTP/1.1\r\n"
                        f"Host: evil.example:{server.port}\r\n"
                        "Content-Type: application/json\r\n"
                        f"Content-Length: {1024 * 1024}\r\n"
                        "Connection: keep-alive\r\n"
                        "\r\n"
                    ).encode("ascii")
                )

                response = client.recv(4096)

                self.assertIn(b" 403 ", response)
                self.assertIn(b"Connection: close", response)
            finally:
                client.close()
                server.stop()

    def test_canonical_redirect_preserves_query_parameters(self):
        response = handle_get_request(
            SimpleNamespace(),
            "/timeline/?date=2026-06-18&sort=desc",
        )

        self.assertEqual(response.status, 302)
        self.assertEqual(
            dict(response.headers)["Location"],
            "/timeline?date=2026-06-18&sort=desc",
        )

    def test_port_80_accepts_http_authority_without_explicit_port(self):
        handler = _WebUiHandler.__new__(_WebUiHandler)
        handler.server = SimpleNamespace(server_address=("127.0.0.1", 80))

        self.assertTrue(handler._is_allowed_host("localhost"))
        self.assertTrue(handler._is_allowed_host("127.0.0.1"))
        self.assertTrue(handler._is_allowed_origin("http://localhost"))
        self.assertTrue(handler._is_allowed_origin("http://127.0.0.1"))
        self.assertFalse(handler._is_allowed_origin("https://localhost"))

    def _csrf_token(self, server: WebUiServer) -> str:
        with urlopen(server.url, timeout=2) as response:
            html = response.read().decode("utf-8")
        bootstrap = self._webui_bootstrap(html)
        token = bootstrap["csrfToken"]
        self.assertTrue(token)
        self.assertNotEqual(token, "__DANCING_LOG_BOOTSTRAP__")
        return token

    def _webui_bootstrap(self, html: str) -> dict:
        marker = '<script id="dancing-log-bootstrap" type="application/json">'
        self.assertIn(marker, html)
        payload = html.split(marker, 1)[1].split("</script>", 1)[0]
        bootstrap = json.loads(payload)
        self.assertIsInstance(bootstrap, dict)
        return bootstrap

    def _assert_slow_request_expires(
        self,
        *,
        initial: bytes,
        trickle: bytes,
        server: WebUiServer,
    ) -> None:
        client: socket.socket | None = None
        writer_stop = threading.Event()
        writer: threading.Thread | None = None
        try:
            with patch.object(
                server._server,
                "request_read_deadline_seconds",
                0.12,
            ):
                client = socket.create_connection(
                    (server.host, server.port), timeout=1.0
                )
                client.sendall(initial)

                registration_deadline = time.monotonic() + 1.0
                while (
                    server._server.active_request_count == 0
                    and time.monotonic() < registration_deadline
                ):
                    time.sleep(0.01)
                self.assertEqual(server._server.active_request_count, 1)

                def trickle_request() -> None:
                    while not writer_stop.wait(0.02):
                        try:
                            client.sendall(trickle)
                        except OSError:
                            return

                writer = threading.Thread(target=trickle_request)
                writer.start()
                deadline = time.monotonic() + 0.6
                while (
                    server._server.active_request_count != 0
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.01)

            self.assertEqual(server._server.active_request_count, 0)
        finally:
            writer_stop.set()
            if client is not None:
                client.close()
            if writer is not None:
                writer.join(timeout=1.0)
            if server._server is not None:
                server.stop()

    def _json_request(
        self,
        server: WebUiServer,
        path: str,
        payload: dict,
        *,
        token: str | None = None,
        origin: str | None = None,
        content_type: str = "application/json",
        host: str | None = None,
    ) -> Request:
        headers = {"Content-Type": content_type}
        if token is not None:
            headers["X-Dancing-Log-CSRF"] = token
        if origin is not None:
            headers["Origin"] = origin
        if host is not None:
            headers["Host"] = host
        return Request(
            f"{server.url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

    def _http_error_json(self, request: Request, expected_code: int) -> dict:
        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=2)
        error = context.exception
        try:
            body = error.read().decode("utf-8")
        finally:
            error.close()
        self.assertEqual(error.code, expected_code)
        return json.loads(body) if body else {}

    def test_webui_serves_main_page_and_config_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = WebUiServer(port=0, app_root=tmp)
            server.start()
            try:
                with urlopen(server.url, timeout=2) as response:
                    html = response.read().decode("utf-8")
                    final_url = response.geturl()
                self.assertEqual(final_url, server.home_url)
                self.assertIn("<title>dancing-log</title>", html)
                self.assertIn('<div id="root"></div>', html)
                self.assertIn(
                    '<script type="module" crossorigin src="/assets/app.js"></script>',
                    html,
                )
                self.assertNotIn("https://", html)
                self.assertNotIn("__DANCING_LOG_BOOTSTRAP__", html)

                bootstrap = self._webui_bootstrap(html)
                self.assertTrue(bootstrap["csrfToken"])
                self.assertEqual(bootstrap["routes"]["timeline"], "/timeline")
                self.assertEqual(
                    bootstrap["routes"]["operations"], "/data-operations"
                )

                with urlopen(f"{server.url}assets/app.js", timeout=2) as response:
                    app_asset = response.read()
                    self.assertEqual(
                        response.headers.get_content_type(), "text/javascript"
                    )
                self.assertGreater(len(app_asset), 100_000)

                with urlopen(f"{server.url}api/config", timeout=2) as response:
                    snapshot = json.loads(response.read().decode("utf-8"))
                self.assertEqual(snapshot["config"]["app_db"], "data/dancing_log.sqlite3")
                self.assertIn("overlay_port", snapshot["config"])
                self.assertEqual(
                    snapshot["config"]["dance_day_boundary_time"],
                    "00:00",
                )
            finally:
                server.stop()

    def test_webui_serves_canonical_page_routes_and_mounted_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = WebUiServer(port=0, app_root=tmp)
            server.start()
            try:
                for path in (
                    "home",
                    "timeline?date=2026-06-18&sort=desc",
                    "catalog",
                    "lists",
                    "insights",
                    "data-operations",
                    "settings",
                ):
                    with urlopen(f"{server.url}{path}", timeout=2) as response:
                        self.assertEqual(response.status, 200)
                        self.assertIn("dancing-log", response.read().decode("utf-8"))

                with urlopen(f"{server.url}api/overlay/state", timeout=2) as response:
                    inactive_snapshot = json.loads(response.read().decode("utf-8"))
                self.assertFalse(inactive_snapshot["overlay_enabled"])

                server.runtime.overlay_state.publish(
                    {
                        "event_key": "wannadance:3114#1",
                        "dance_system_key": "wannadance",
                        "dance_external_id": "3114",
                        "actual_play_at": "2026.05.17 15:30:10",
                    }
                )
                with urlopen(server.overlay_url, timeout=2) as response:
                    overlay_html = response.read().decode("utf-8")
                self.assertIn("/api/overlay/state", overlay_html)
                self.assertIn("/api/overlay/events", overlay_html)

                with urlopen(f"{server.url}api/overlay/state", timeout=2) as response:
                    snapshot = json.loads(response.read().decode("utf-8"))
                self.assertEqual(snapshot["current"]["dance_external_id"], "3114")

                with urlopen(f"{server.url}api/overlay/events", timeout=2) as response:
                    data_line = ""
                    for _ in range(4):
                        line = response.readline().decode("utf-8").strip()
                        if line.startswith("data: "):
                            data_line = line
                            break
                event_snapshot = json.loads(data_line.removeprefix("data: "))
                self.assertEqual(event_snapshot["current"]["dance_external_id"], "3114")

                try:
                    urlopen(f"{server.url}not-a-page", timeout=2)
                except HTTPError as error:
                    self.assertEqual(error.code, 404)
                    error.close()
                else:
                    self.fail("unknown page route should return 404")
            finally:
                server.stop()

    def test_control_pages_deny_framing_but_overlay_allows_obs_embedding(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = WebUiServer(port=0, app_root=tmp)
            server.start()
            try:
                with urlopen(server.home_url, timeout=2) as response:
                    self.assertEqual(response.headers["X-Frame-Options"], "DENY")
                    self.assertEqual(
                        response.headers["Content-Security-Policy"],
                        "frame-ancestors 'none'",
                    )
                with urlopen(server.overlay_url, timeout=2) as response:
                    self.assertIsNone(response.headers["X-Frame-Options"])
                    self.assertIsNone(response.headers["Content-Security-Policy"])
            finally:
                server.stop()

    def test_rejected_post_validates_headers_before_body_and_closes_connection(self):
        payload = b'{"config":{"app_db":"data/test.sqlite3"}}'
        handler = _WebUiHandler.__new__(_WebUiHandler)
        handler.headers = {
            "Content-Length": str(len(payload)),
            "Content-Type": "text/plain",
        }
        handler.rfile = BytesIO(payload)
        handler._validate_post_headers = lambda: (_ for _ in ()).throw(
            RequestRejected(415, "POST requires application/json")
        )
        responses: list[tuple[int, dict]] = []
        handler._send_json = lambda status, body: responses.append((status, body))

        handler.do_POST()

        self.assertEqual(handler.rfile.tell(), 0)
        self.assertTrue(handler.close_connection)
        self.assertEqual(
            responses,
            [(415, {"error": "POST requires application/json"})],
        )

    def test_webui_config_save_preserves_unknown_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config" / "dancing-log.local.json"
            config_path.parent.mkdir()
            config_path.write_text(
                json.dumps(
                    {
                        "app_db": "data/old.sqlite3",
                        "vrcx_db_path": "D:/old/VRCX.sqlite3",
                        "vrc_log_dir": "C:/old/VRChat",
                        "custom_future_key": {"keep": True},
                    }
                ),
                encoding="utf-8",
            )
            server = WebUiServer(port=0, app_root=root)
            server.start()
            try:
                token = self._csrf_token(server)
                payload = {
                    "config": {
                        "app_db": "data/new.sqlite3",
                        "queued_self_dir": "data/queued_self",
                        "capture_dir": "logs/captures",
                        "run_log_dir": "logs/runs",
                        "source_vrc_log_dir": "logs/source-vrc-logs",
                        "recording_frames_dir": "analysis/recording_frames",
                        "self_user_id": "",
                        "vrcx_db_path": "",
                        "vrc_log_dir": "",
                        "wanna_cache_dir": "",
                        "recordings_dir": "",
                        "auto_start_watcher": False,
                        "auto_start_overlay": True,
                        "overlay_port": 8765,
                    }
                }
                request = self._json_request(
                    server,
                    "api/config",
                    payload,
                    token=token,
                    origin=server.url.rstrip("/"),
                )
                with urlopen(request, timeout=2) as response:
                    result = json.loads(response.read().decode("utf-8"))

                saved = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertTrue(result["saved"])
                self.assertEqual(saved["app_db"], "data/new.sqlite3")
                self.assertEqual(saved["custom_future_key"], {"keep": True})
                self.assertTrue(saved["auto_start_overlay"])
                self.assertTrue(saved["auto_start_watcher"])
                self.assertIsNone(saved["vrcx_db_path"])
                self.assertIsNone(saved["vrc_log_dir"])
                self.assertIsNone(result["snapshot"]["config"]["vrcx_db_path"])
                self.assertIsNone(result["snapshot"]["config"]["vrc_log_dir"])
            finally:
                server.stop()

    def test_webui_config_save_rejects_invalid_port_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config" / "dancing-log.local.json"
            config_path.parent.mkdir()
            config_path.write_text(
                json.dumps({"app_db": "data/original.sqlite3"}),
                encoding="utf-8",
            )
            server = WebUiServer(port=0, app_root=root)
            server.start()
            try:
                token = self._csrf_token(server)
                payload = {
                    "config": {
                        "app_db": "data/new.sqlite3",
                        "queued_self_dir": "data/queued_self",
                        "capture_dir": "logs/captures",
                        "run_log_dir": "logs/runs",
                        "source_vrc_log_dir": "logs/source-vrc-logs",
                        "recording_frames_dir": "analysis/recording_frames",
                        "auto_start_watcher": False,
                        "auto_start_overlay": False,
                        "overlay_port": 70000,
                    }
                }
                request = self._json_request(
                    server,
                    "api/config",
                    payload,
                    token=token,
                    origin=server.url.rstrip("/"),
                )
                body = self._http_error_json(request, 400)
                saved = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertIn("overlay_port", body["errors"])
                self.assertEqual(saved["app_db"], "data/original.sqlite3")
            finally:
                server.stop()

    def test_webui_config_save_rejects_cross_origin_text_and_missing_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config" / "dancing-log.local.json"
            config_path.parent.mkdir()
            config_path.write_text(
                json.dumps({"app_db": "data/original.sqlite3"}),
                encoding="utf-8",
            )
            server = WebUiServer(port=0, app_root=root)
            server.start()
            try:
                token = self._csrf_token(server)
                payload = {"config": {"app_db": "data/csrf.sqlite3"}}

                text_request = self._json_request(
                    server,
                    "api/config",
                    payload,
                    token=token,
                    origin="https://example.invalid",
                    content_type="text/plain",
                )
                self._http_error_json(text_request, 415)

                origin_request = self._json_request(
                    server,
                    "api/config",
                    payload,
                    token=token,
                    origin="https://example.invalid",
                )
                self._http_error_json(origin_request, 403)

                missing_token_request = self._json_request(
                    server,
                    "api/config",
                    payload,
                    origin=server.url.rstrip("/"),
                )
                self._http_error_json(missing_token_request, 403)

                host_request = self._json_request(
                    server,
                    "api/config",
                    payload,
                    token=token,
                    origin=server.url.rstrip("/"),
                    host=f"example.invalid:{server.port}",
                )
                self._http_error_json(host_request, 403)

                saved = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(saved["app_db"], "data/original.sqlite3")
            finally:
                server.stop()

    def test_webui_get_and_sse_reject_non_local_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = WebUiServer(port=0, app_root=tmp)
            server.start()
            try:
                hostile_host = f"evil.example:{server.port}"
                config_request = Request(
                    f"{server.url}api/config",
                    headers={"Host": hostile_host},
                )
                config_body = self._http_error_json(config_request, 403)
                self.assertEqual(config_body["error"], "invalid Host")

                events_request = Request(
                    f"{server.url}api/overlay/events",
                    headers={"Host": hostile_host},
                )
                events_body = self._http_error_json(events_request, 403)
                self.assertEqual(events_body["error"], "invalid Host")
                self.assertEqual(server.runtime.overlay_state.subscriber_count, 0)
            finally:
                server.stop()

    def test_webui_stop_terminates_overlay_sse_and_unsubscribes(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = WebUiServer(port=0, app_root=tmp)
            server.start()
            response = urlopen(f"{server.url}api/overlay/events", timeout=2)
            received = bytearray()

            def read_stream() -> None:
                try:
                    while chunk := response.read(1024):
                        received.extend(chunk)
                except (OSError, ValueError):
                    pass

            reader = threading.Thread(target=read_stream, daemon=True)
            reader.start()
            try:
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                    if server.runtime.overlay_state.subscriber_count == 1:
                        break
                    time.sleep(0.01)
                self.assertEqual(server.runtime.overlay_state.subscriber_count, 1)

                server.stop()
                server.runtime.overlay_state.publish_status(
                    {"event_type": "after-stop", "message": "after-stop"}
                )
                reader.join(timeout=1.0)

                self.assertFalse(reader.is_alive())
                self.assertEqual(server.runtime.overlay_state.subscriber_count, 0)
                self.assertNotIn(b"after-stop", received)
            finally:
                response.close()
                if server._server is not None:
                    server.stop()

    def test_webui_stop_reports_sse_drain_timeout_after_other_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = WebUiServer(port=0, app_root=tmp)
            server.start()
            event_streams = server._server.event_streams
            with (
                patch.object(event_streams, "wait_until_drained", return_value=False),
                self.assertRaisesRegex(TimeoutError, "event stream"),
            ):
                server.stop()

            self.assertIsNone(server._server)

    def test_webui_live_controls_use_session_runtime(self):
        calls: list[dict] = []

        def fake_watch_vrc_logs(**kwargs):
            calls.append(kwargs)
            try:
                kwargs["stop_event"].wait(timeout=2.0)
                return {"overlay_port": kwargs["overlay_port"]}
            finally:
                overlay = kwargs.get("overlay")
                if overlay is not None:
                    overlay.close()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "logs").mkdir()
            config = dict(DEFAULT_CONFIG)
            config["vrc_log_dir"] = str(root / "logs")
            config["overlay_port"] = 9911
            config_path = root / "config" / "dancing-log.local.json"
            config_path.parent.mkdir()
            config_path.write_text(json.dumps(config), encoding="utf-8")

            server = WebUiServer(
                port=0,
                app_root=root,
                watch_vrc_logs_func=fake_watch_vrc_logs,
            )
            server.start()
            try:
                token = self._csrf_token(server)
                with urlopen(f"{server.url}api/summary", timeout=2) as response:
                    summary = json.loads(response.read().decode("utf-8"))
                self.assertFalse(summary["session"]["watcher_running"])
                self.assertFalse(summary["session"]["overlay_running"])
                self.assertEqual(summary["session"]["session_state"], "open")
                self.assertEqual(summary["session"]["watcher_state"], "stopped")
                self.assertEqual(summary["session"]["overlay_state"], "stopped")
                with urlopen(f"{server.url}api/overlay/state", timeout=2) as response:
                    overlay_snapshot = json.loads(response.read().decode("utf-8"))
                self.assertFalse(overlay_snapshot["overlay_enabled"])

                watcher_start = self._json_request(
                    server,
                    "api/live/watcher",
                    {"action": "start"},
                    token=token,
                    origin=server.url.rstrip("/"),
                )
                with urlopen(watcher_start, timeout=2) as response:
                    result = json.loads(response.read().decode("utf-8"))
                wait_for_call_count(calls, 1)
                self.assertTrue(result["session"]["watcher_running"])
                self.assertFalse(result["session"]["overlay_running"])
                self.assertEqual(result["session"]["watcher_state"], "running")
                self.assertEqual(result["session"]["overlay_state"], "stopped")
                with urlopen(f"{server.url}api/overlay/state", timeout=2) as response:
                    overlay_snapshot = json.loads(response.read().decode("utf-8"))
                self.assertFalse(overlay_snapshot["overlay_enabled"])
                self.assertFalse(calls[-1]["live_db"])
                self.assertTrue(calls[-1]["record_playback"])
                self.assertIsNone(calls[-1]["overlay_port"])
                self.assertEqual(calls[-1]["overlay"].url, server.overlay_url)

                overlay_start = self._json_request(
                    server,
                    "api/live/overlay",
                    {"action": "start"},
                    token=token,
                    origin=server.url.rstrip("/"),
                )
                with urlopen(overlay_start, timeout=2) as response:
                    result = json.loads(response.read().decode("utf-8"))
                self.assertEqual(len(calls), 1)
                self.assertTrue(result["session"]["watcher_running"])
                self.assertTrue(result["session"]["overlay_running"])
                self.assertEqual(result["session"]["watcher_state"], "running")
                self.assertEqual(result["session"]["overlay_state"], "running")
                with urlopen(f"{server.url}api/overlay/state", timeout=2) as response:
                    overlay_snapshot = json.loads(response.read().decode("utf-8"))
                self.assertTrue(overlay_snapshot["overlay_enabled"])
                self.assertEqual(
                    overlay_snapshot["status"]["message"],
                    "Waiting for playback",
                )
                self.assertIsNone(calls[-1]["overlay_port"])
                self.assertEqual(calls[-1]["overlay"].url, server.overlay_url)
                self.assertTrue(calls[-1]["record_playback"])

                overlay_stop = self._json_request(
                    server,
                    "api/live/overlay",
                    {"action": "stop"},
                    token=token,
                    origin=server.url.rstrip("/"),
                )
                with urlopen(overlay_stop, timeout=2) as response:
                    result = json.loads(response.read().decode("utf-8"))
                self.assertEqual(len(calls), 1)
                self.assertTrue(result["session"]["watcher_running"])
                self.assertFalse(result["session"]["overlay_running"])
                with urlopen(f"{server.url}api/overlay/state", timeout=2) as response:
                    overlay_snapshot = json.loads(response.read().decode("utf-8"))
                self.assertFalse(overlay_snapshot["overlay_enabled"])
                self.assertIsNone(calls[-1]["overlay_port"])
                self.assertEqual(calls[-1]["overlay"].url, server.overlay_url)

                watcher_stop = self._json_request(
                    server,
                    "api/live/watcher",
                    {"action": "stop"},
                    token=token,
                    origin=server.url.rstrip("/"),
                )
                with urlopen(watcher_stop, timeout=2) as response:
                    result = json.loads(response.read().decode("utf-8"))
                self.assertFalse(result["session"]["watcher_running"])
                self.assertFalse(result["session"]["overlay_running"])

                with urlopen(f"{server.url}api/summary", timeout=2) as response:
                    summary = json.loads(response.read().decode("utf-8"))
                self.assertEqual(
                    summary["session"]["last_watcher_stats"],
                    {"overlay_port": None},
                )
            finally:
                server.stop()

    def test_webui_live_controls_reject_unknown_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = WebUiServer(port=0, app_root=tmp, watch_vrc_logs_func=lambda **_kwargs: None)
            server.start()
            try:
                token = self._csrf_token(server)
                request = self._json_request(
                    server,
                    "api/live/watcher",
                    {"action": "toggle"},
                    token=token,
                    origin=server.url.rstrip("/"),
                )
                body = self._http_error_json(request, 400)
                self.assertEqual(body["error"], "action must be start or stop")
            finally:
                server.stop()

    def test_home_summary_uses_live_state_while_overlay_is_disabled(self):
        published = threading.Event()

        def fake_watch_vrc_logs(**kwargs):
            kwargs["overlay"].publish(
                {
                    "event_key": "wannadance:3114#home",
                    "live_event_key": "live-home",
                    "dance_system_key": "wannadance",
                    "dance_external_id": "3114",
                    "actual_play_at": "2026.07.18 20:30:00",
                    "video_name": "Home Live Song",
                }
            )
            published.set()
            kwargs["stop_event"].wait(timeout=2.0)
            return {"finished": True}

        with tempfile.TemporaryDirectory() as tmp:
            server = WebUiServer(
                port=0,
                app_root=tmp,
                watch_vrc_logs_func=fake_watch_vrc_logs,
            )
            server.start()
            try:
                token = self._csrf_token(server)
                start = self._json_request(
                    server,
                    "api/live/watcher",
                    {"action": "start"},
                    token=token,
                    origin=server.url.rstrip("/"),
                )
                with urlopen(start, timeout=2):
                    pass
                self.assertTrue(published.wait(timeout=1.0))

                with urlopen(f"{server.url}api/summary", timeout=2) as response:
                    summary = json.loads(response.read().decode("utf-8"))
                with urlopen(
                    f"{server.url}api/overlay/state", timeout=2
                ) as response:
                    overlay = json.loads(response.read().decode("utf-8"))

                self.assertEqual(
                    summary["current_live"]["dance_external_id"],
                    "3114",
                )
                self.assertFalse(overlay["overlay_enabled"])
                self.assertIsNone(overlay["current"])
            finally:
                server.stop()

    def test_watcher_lock_conflict_returns_409_with_current_session_status(self):
        watcher_started = threading.Event()

        def blocking_watch_vrc_logs(**kwargs):
            watcher_started.set()
            kwargs["stop_event"].wait(timeout=2.0)
            return {"finished": True}

        with tempfile.TemporaryDirectory() as tmp:
            owner = LiveAppSessionRuntime(
                app_root=tmp,
                watch_vrc_logs_func=blocking_watch_vrc_logs,
            )
            owner.start_watcher()
            self.assertTrue(watcher_started.wait(timeout=1.0))
            server = WebUiServer(port=0, app_root=tmp)
            server.start()
            try:
                token = self._csrf_token(server)
                start = self._json_request(
                    server,
                    "api/live/watcher",
                    {"action": "start"},
                    token=token,
                    origin=server.url.rstrip("/"),
                )

                body = self._http_error_json(start, 409)

                self.assertIn("already active", body["error"])
                self.assertEqual(body["session"]["last_error"], body["error"])
                self.assertEqual(body["session"]["watcher_state"], "stopped")
            finally:
                server.stop()
                owner.close()

    def test_stop_unmounts_adapter_from_external_session(self):
        watcher_started = threading.Event()

        def blocking_watch_vrc_logs(**kwargs):
            watcher_started.set()
            kwargs["stop_event"].wait(timeout=2.0)
            return {"finished": True}

        with tempfile.TemporaryDirectory() as tmp:
            session = LiveAppSessionRuntime(
                app_root=tmp,
                watch_vrc_logs_func=blocking_watch_vrc_logs,
            )
            server = WebUiServer(
                port=0,
                app_root=tmp,
                session_runtime=session,
            )
            server.start()
            mounted_overlay = server._mounted_overlay
            try:
                self.assertIsNotNone(mounted_overlay)
                session.start_watcher()
                self.assertTrue(watcher_started.wait(timeout=1.0))

                server.stop()

                self.assertIsNone(session._mounted_overlay)
                self.assertFalse(mounted_overlay.enabled)
                self.assertEqual(session.status().session_state, "open")
                self.assertTrue(session.status().watcher_running)
                self.assertFalse(session.status().overlay_running)
            finally:
                if server._server is not None:
                    server.stop()
                session.close()

    def test_webui_live_control_reports_transition_timeout_as_conflict(self):
        class TimedOutSession:
            def start_overlay(self) -> None:
                raise TimeoutError("watcher did not stop; lifecycle transition cancelled")

            def stop_overlay(self) -> None:
                raise TimeoutError("watcher did not stop; lifecycle transition cancelled")

            def status(self):
                return SimpleNamespace(
                    session_state="open",
                    watcher_running=True,
                    overlay_running=True,
                    watcher_state="stopping",
                    overlay_state="stopping",
                    last_error="watcher did not stop",
                    last_watcher_stats=None,
                )

        runtime = SimpleNamespace(session=TimedOutSession())

        for action in ("start", "stop"):
            with self.subTest(action=action):
                body, status = control_live_overlay_from_payload(
                    runtime,
                    {"action": action},
                )

                self.assertEqual(status, 409)
                self.assertIn("lifecycle transition cancelled", body["error"])
                self.assertTrue(body["session"]["watcher_running"])
                self.assertTrue(body["session"]["overlay_running"])
                self.assertEqual(body["session"]["watcher_state"], "stopping")
                self.assertEqual(body["session"]["overlay_state"], "stopping")

    def test_webui_live_start_reports_closed_session_as_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = WebUiRuntime.from_root(
                tmp,
                watch_vrc_logs_func=lambda **_kwargs: None,
            ).session
            session.close()
            runtime = SimpleNamespace(session=session)

            body, status = control_live_overlay_from_payload(
                runtime,
                {"action": "start"},
            )

        self.assertEqual(status, 409)
        self.assertIn("closed", body["error"])
        self.assertEqual(body["session"]["session_state"], "closed")
        self.assertEqual(body["session"]["watcher_state"], "stopped")

    def test_webui_playback_review_endpoint_updates_timeline_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "data" / "dancing_log.sqlite3"
            with connect_db(db_path) as conn:
                track_id = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "700",
                    {"title": "Review Song", "artist": "Review Artist"},
                )
                playback_record_id = insert_playback_record(
                    conn,
                    track_id=track_id,
                    played_at="2026-06-18T20:40:00+08:00",
                    playback_status=EFFECTIVE_PLAYBACK_NEEDS_ATTENTION,
                    counts_in_history=0,
                )
                conn.commit()

            server = WebUiServer(port=0, app_root=root)
            server.start()
            try:
                token = self._csrf_token(server)
                accept_request = self._json_request(
                    server,
                    "api/playback-review",
                    {"playback_record_id": playback_record_id, "action": "accept"},
                    token=token,
                    origin=server.url.rstrip("/"),
                )
                with urlopen(accept_request, timeout=2) as response:
                    accept_result = json.loads(response.read().decode("utf-8"))
                self.assertEqual(
                    accept_result["review"],
                    {
                        "playback_record_id": playback_record_id,
                        "default_playback_status": "needs_attention",
                        "manual_decision_status": "accepted",
                        "effective_playback_status": "accepted",
                    },
                )

                with urlopen(f"{server.url}api/timeline?date=2026-06-18", timeout=2) as response:
                    timeline = json.loads(response.read().decode("utf-8"))
                row = timeline["records"][0]
                self.assertEqual(row["id"], playback_record_id)
                self.assertEqual(row["review_status"], "accepted")
                self.assertEqual(row["default_playback_status"], "needs_attention")
                self.assertEqual(row["manual_decision_status"], "accepted")
                self.assertTrue(row["has_manual_decision"])

                restore_request = self._json_request(
                    server,
                    "api/playback-review",
                    {"playback_record_id": playback_record_id, "action": "restore_default"},
                    token=token,
                    origin=server.url.rstrip("/"),
                )
                with urlopen(restore_request, timeout=2) as response:
                    restore_result = json.loads(response.read().decode("utf-8"))
                self.assertEqual(restore_result["review"]["manual_decision_status"], None)
                self.assertEqual(
                    restore_result["review"]["effective_playback_status"],
                    "needs_attention",
                )

                with urlopen(f"{server.url}api/timeline?date=2026-06-18", timeout=2) as response:
                    restored_timeline = json.loads(response.read().decode("utf-8"))
                restored_row = restored_timeline["records"][0]
                self.assertEqual(restored_row["review_status"], "needs_attention")
                self.assertIsNone(restored_row["manual_decision_status"])
                self.assertFalse(restored_row["has_manual_decision"])
            finally:
                server.stop()

    def test_webui_playback_review_endpoint_does_not_create_missing_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "data" / "dancing_log.sqlite3"
            body, status = update_playback_review_from_payload(
                WebUiRuntime.from_root(root),
                {"playback_record_id": 1, "action": "accept"},
            )

            self.assertEqual(status, 400)
            self.assertEqual(body["error"], "database not found")
            self.assertFalse(db_path.exists())

    def test_webui_resolve_path_uses_draft_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = WebUiServer(port=0, app_root=root)
            server.start()
            try:
                token = self._csrf_token(server)
                request = self._json_request(
                    server,
                    "api/resolve-path",
                    {"field": "app_db", "current_value": "data/new.sqlite3"},
                    token=token,
                    origin=server.url.rstrip("/"),
                )
                with urlopen(request, timeout=2) as response:
                    result = json.loads(response.read().decode("utf-8"))

                self.assertEqual(result["field"], "app_db")
                self.assertEqual(result["path"]["resolved"], str(root / "data" / "new.sqlite3"))
                self.assertFalse(result["path"]["exists"])

                null_request = self._json_request(
                    server,
                    "api/resolve-path",
                    {"field": "vrcx_db_path", "current_value": ""},
                    token=token,
                    origin=server.url.rstrip("/"),
                )
                with urlopen(null_request, timeout=2) as response:
                    null_result = json.loads(response.read().decode("utf-8"))
                self.assertIsNone(null_result["path"]["resolved"])
            finally:
                server.stop()

    def test_webui_read_snapshots_do_not_initialize_empty_sqlite_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "data" / "dancing_log.sqlite3"
            db_path.parent.mkdir()
            db_path.write_bytes(b"")
            runtime = WebUiRuntime.from_root(root)

            catalog = load_catalog_snapshot(runtime, {})
            insights = load_insights_snapshot(runtime)
            timeline = load_timeline_snapshot(runtime, {"date": ["2026-06-18"]})

            self.assertTrue(catalog["database_exists"])
            self.assertTrue(insights["database_exists"])
            self.assertTrue(timeline["database_exists"])
            self.assertEqual(db_path.stat().st_size, 0)

    def test_timeline_without_date_defaults_to_latest_playback_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "data" / "dancing_log.sqlite3"
            with connect_db(db_path) as conn:
                older_track = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "201",
                    {"title": "Older Song", "artist": "Older Artist"},
                )
                latest_track = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "202",
                    {"title": "Latest Song", "artist": "Latest Artist"},
                )
                insert_playback_record(
                    conn,
                    track_id=older_track,
                    played_at="2026-06-18T20:00:00+08:00",
                    source_type="self",
                )
                insert_playback_record(
                    conn,
                    track_id=latest_track,
                    played_at="2026-06-22T20:00:00",
                    source_type="self",
                )
                conn.commit()

            timeline = load_timeline_snapshot(WebUiRuntime.from_root(root), {})

            self.assertEqual(timeline["date"], "2026-06-22")
            self.assertEqual(
                [record["display"] for record in timeline["records"]],
                ["202. Latest Song - Latest Artist"],
            )

    def test_timeline_uses_configured_local_dance_day_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_app_config(
                {"dance_day_boundary_time": "00:00"},
                app_root=root,
            )
            db_path = root / "data" / "dancing_log.sqlite3"
            with connect_db(db_path) as conn:
                late_night_track = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "203",
                    {"title": "Late Night Song"},
                )
                insert_playback_record(
                    conn,
                    track_id=late_night_track,
                    played_at="2026-06-23T02:30:00",
                    source_type="self",
                )
                conn.commit()

            runtime = WebUiRuntime.from_root(root)
            natural_day_before_change = load_timeline_snapshot(
                runtime,
                {"date": ["2026-06-23"]},
            )
            with connect_db(db_path) as conn:
                stored_timestamp_before_change = conn.execute(
                    "SELECT played_at FROM playback_records"
                ).fetchone()[0]
            save_app_config(
                {"dance_day_boundary_time": "03:00"},
                app_root=root,
            )
            previous_day = load_timeline_snapshot(
                runtime,
                {"date": ["2026-06-22"]},
            )
            natural_day = load_timeline_snapshot(
                runtime,
                {"date": ["2026-06-23"]},
            )
            latest = load_timeline_snapshot(runtime, {})
            with connect_db(db_path) as conn:
                stored_timestamp = conn.execute(
                    "SELECT played_at FROM playback_records"
                ).fetchone()[0]

            self.assertEqual(
                [
                    record["display"]
                    for record in natural_day_before_change["records"]
                ],
                ["203. Late Night Song"],
            )
            self.assertEqual(
                [record["display"] for record in previous_day["records"]],
                ["203. Late Night Song"],
            )
            self.assertEqual(natural_day["records"], [])
            self.assertEqual(latest["date"], "2026-06-22")
            self.assertEqual(stored_timestamp, stored_timestamp_before_change)

    def test_webui_read_snapshots_use_playback_records_not_legacy_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "data" / "dancing_log.sqlite3"
            with connect_db(db_path) as conn:
                legacy_track = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "100",
                    {"title": "Legacy Song", "artist": "Legacy Artist"},
                )
                evidence_track = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "200",
                    {"title": "Evidence Song", "artist": "Evidence Artist"},
                )
                attention_track = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "300",
                    {"title": "Attention Song", "artist": "Attention Artist"},
                )
                excluded_track = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "500",
                    {"title": "False Positive", "artist": "Excluded Artist"},
                )
                manual_accepted_track = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "600",
                    {"title": "Manual Keep", "artist": "Manual Artist"},
                )
                live_track = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "400",
                    {"title": "Live Evidence", "artist": "Live Artist"},
                )
                evidence_record = insert_playback_record(
                    conn,
                    track_id=evidence_track,
                    played_at="2026-06-18T20:00:00+08:00",
                    source_type="self",
                )
                attention_record = insert_playback_record(
                    conn,
                    track_id=attention_track,
                    played_at="2026-06-18T20:10:00+08:00",
                    source_type="player",
                    source_display_name="Alice",
                    requester_display_name="Alice",
                    requester_user_id="usr_alice",
                    playback_status="needs_attention",
                    counts_in_history=0,
                    status_reason="interrupted",
                    catalog_attention=1,
                )
                excluded_record = insert_playback_record(
                    conn,
                    track_id=excluded_track,
                    played_at="2026-06-18T20:15:00+08:00",
                    source_type="self",
                    catalog_attention=1,
                )
                manual_accepted_record = insert_playback_record(
                    conn,
                    track_id=manual_accepted_track,
                    played_at="2026-06-18T20:18:00+08:00",
                    source_type="player",
                    playback_status="needs_attention",
                    counts_in_history=0,
                    status_reason="low_confidence",
                )
                live_record = insert_playback_record(
                    conn,
                    track_id=live_track,
                    played_at="2026-06-18T20:20:00+08:00",
                    source_kind="live_watcher",
                    source_table="live_playback_events",
                    source_type="player",
                )
                set_manual_playback_decision(
                    conn,
                    excluded_record,
                    EFFECTIVE_PLAYBACK_EXCLUDED,
                    reason="false_positive",
                )
                set_manual_playback_decision(
                    conn,
                    manual_accepted_record,
                    EFFECTIVE_PLAYBACK_ACCEPTED,
                    reason="confirmed",
                )
                upsert_live_playback_event(
                    conn,
                    {
                        "event_key": "wannadance:999#1",
                        "actual_play_at": "2026-06-18T20:30:00+08:00",
                        "observed_mid_play": False,
                        "dance_system_key": WANNA_SYSTEM_KEY,
                        "dance_external_id": "999",
                        "video_name": "Legacy Live Row",
                        "signal_count": 1,
                    },
                    session_id="session-one",
                )
                conn.execute(
                    """
                    INSERT INTO dance_events (
                        played_at,
                        dance_track_id,
                        source,
                        confidence,
                        event_source,
                        event_key
                    )
                    VALUES (?, ?, 'random', 0.7, 'legacy-test', 'legacy-webui-event')
                    """,
                    ("2026-06-18T19:00:00+08:00", legacy_track),
                )
                conn.commit()

            runtime = WebUiRuntime.from_root(root)

            summary = load_summary_snapshot(runtime)
            timeline = load_timeline_snapshot(runtime, {"date": ["2026-06-18"]})
            live_timeline = load_timeline_snapshot(
                runtime,
                {"date": ["2026-06-18"], "source": ["live"]},
            )
            insights = load_insights_snapshot(runtime)

            self.assertEqual(timeline["source"], "all")
            self.assertEqual(live_timeline["source"], "live")
            self.assertEqual(summary["counts"]["playback_records"], 5)
            self.assertEqual(summary["counts"]["accepted_playback_records"], 3)
            self.assertEqual(summary["counts"]["needs_attention_playback_records"], 1)
            self.assertEqual(summary["counts"]["legacy_dance_events"], 1)
            self.assertEqual(summary["counts"]["legacy_live_playback_events"], 1)
            self.assertEqual(
                {
                    record_id: next(
                        record["review_status"]
                        for record in timeline["records"]
                        if record["id"] == record_id
                    )
                    for record_id in (
                        evidence_record,
                        attention_record,
                        excluded_record,
                        manual_accepted_record,
                        live_record,
                    )
                },
                {
                    evidence_record: "accepted",
                    attention_record: "needs_attention",
                    excluded_record: "excluded",
                    manual_accepted_record: "accepted",
                    live_record: "accepted",
                },
            )
            self.assertEqual(
                {
                    record_id: next(
                        (
                            record["default_playback_status"],
                            record["manual_decision_status"],
                            record["effective_playback_status"],
                            record["has_manual_decision"],
                        )
                        for record in timeline["records"]
                        if record["id"] == record_id
                    )
                    for record_id in (
                        evidence_record,
                        attention_record,
                        excluded_record,
                        manual_accepted_record,
                    )
                },
                {
                    evidence_record: ("accepted", None, "accepted", False),
                    attention_record: ("needs_attention", None, "needs_attention", False),
                    excluded_record: ("accepted", "excluded", "excluded", True),
                    manual_accepted_record: (
                        "needs_attention",
                        "accepted",
                        "accepted",
                        True,
                    ),
                },
            )
            self.assertEqual(
                [record["display"] for record in timeline["records"]],
                [
                    "200. Evidence Song - Evidence Artist",
                    "300. Attention Song - Attention Artist",
                    "500. False Positive - Excluded Artist",
                    "600. Manual Keep - Manual Artist",
                    "400. Live Evidence - Live Artist",
                ],
            )
            attention_timeline_record = next(
                record for record in timeline["records"] if record["id"] == attention_record
            )
            self.assertEqual(attention_timeline_record["source_type"], "player")
            self.assertEqual(attention_timeline_record["source_display_name"], "Alice")
            self.assertEqual(attention_timeline_record["requester_display_name"], "Alice")
            self.assertEqual(attention_timeline_record["requester_user_id"], "usr_alice")
            self.assertEqual(attention_timeline_record["dance_system_key"], WANNA_SYSTEM_KEY)
            self.assertEqual(attention_timeline_record["dance_system_name"], "WannaDance")
            self.assertEqual(
                [record["display"] for record in live_timeline["records"]],
                ["400. Live Evidence - Live Artist"],
            )
            self.assertEqual(
                {row["source"]: row["count"] for row in insights["source_distribution"]},
                {"player": 2, "self": 1},
            )
            self.assertEqual(
                {row["external_id"] for row in insights["top_tracks"]},
                {"200", "400", "600"},
            )
            self.assertEqual(
                insights["attention_counts"],
                {"needs_attention": 1, "catalog_attention": 0},
            )
            recommendation_counts = {
                row["external_id"]: row["_dance_count"]
                for row in insights["recommendations"]
            }
            self.assertEqual(recommendation_counts["100"], 0)
            self.assertEqual(recommendation_counts["200"], 1)
            self.assertEqual(recommendation_counts["300"], 0)
            self.assertEqual(recommendation_counts["400"], 1)
            self.assertEqual(recommendation_counts["500"], 0)
            self.assertEqual(recommendation_counts["600"], 1)

    def test_webui_config_snapshot_does_not_migrate_legacy_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy_path = root / "data" / "local_config.json"
            new_path = root / "config" / "dancing-log.local.json"
            legacy_path.parent.mkdir()
            legacy_path.write_text(json.dumps({"app_db": "data/legacy.sqlite3"}), encoding="utf-8")

            snapshot = load_config_snapshot(WebUiRuntime.from_root(root))

            self.assertEqual(snapshot["config"]["app_db"], "data/legacy.sqlite3")
            self.assertFalse(new_path.exists())

    def test_webui_config_snapshot_previews_standard_vrcx_database_without_saving(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            appdata = root / "Roaming"
            standard = appdata / "VRCX" / "VRCX.sqlite3"
            standard.parent.mkdir(parents=True)
            standard.write_bytes(b"")

            with patch.dict("os.environ", {"APPDATA": str(appdata)}):
                snapshot = load_config_snapshot(WebUiRuntime.from_root(root))

            candidates = {
                candidate["field"]: candidate
                for candidate in snapshot["detected_sources"]
            }
            self.assertEqual(candidates["vrcx_db_path"]["value"], str(standard))
            self.assertTrue(candidates["vrcx_db_path"]["exists"])
            self.assertIsNone(snapshot["config"]["vrcx_db_path"])
            self.assertFalse((root / "config" / "dancing-log.local.json").exists())

    def test_webui_operations_snapshot_uses_shared_catalog(self):
        snapshot = load_operations_snapshot()

        self.assertEqual(snapshot, operation_catalog_snapshot())
        operations = {operation["key"]: operation for operation in snapshot["operations"]}
        self.assertEqual(operations["rebuild-data"]["parameters"][0]["key"], "archive_existing")
        self.assertEqual(operations["sync-wanna"]["text"]["zh"]["risk"], "更新目录记录")

    def test_webui_runs_operation_through_shared_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = WebUiServer(port=0, app_root=root)
            server.start()
            try:
                token = self._csrf_token(server)
                fake_result = DataOperationResult(
                    operation_key="sync-wanna",
                    title="Sync WannaDance catalog",
                    status="completed",
                    summary="done",
                    lines=("done",),
                    metrics={"count": 1},
                )
                with patch(
                    "dancing_log.webui_endpoints.run_data_operation_request",
                    return_value=fake_result,
                ) as runner:
                    request = self._json_request(
                        server,
                        "api/operations/run",
                        {
                            "operation": "sync-wanna",
                            "parameters": {"offline": "true", "write_files": False},
                        },
                        token=token,
                        origin=server.url.rstrip("/"),
                    )
                    with urlopen(request, timeout=2) as response:
                        payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.stop()

            self.assertEqual(payload["result"]["operation_key"], "sync-wanna")
            operation_request = runner.call_args.args[0]
            runtime_config = runner.call_args.kwargs["config"]
            self.assertEqual(operation_request.operation_key, "sync-wanna")
            self.assertTrue(operation_request.params["offline"])
            self.assertFalse(operation_request.params["write_files"])
            self.assertEqual(runtime_config.app_root, root.resolve())

    def test_webui_operation_run_rejects_invalid_payload_before_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = WebUiServer(port=0, app_root=tmp)
            server.start()
            try:
                token = self._csrf_token(server)
                with patch("dancing_log.webui_endpoints.run_data_operation_request") as runner:
                    request = self._json_request(
                        server,
                        "api/operations/run",
                        {
                            "operation": "import-vrcx",
                            "parameters": {"blank_requester_source": "self"},
                        },
                        token=token,
                        origin=server.url.rstrip("/"),
                    )
                    error = self._http_error_json(request, 400)
            finally:
                server.stop()

            self.assertIn("blank_requester_source must be one of", error["error"])
            runner.assert_not_called()

    def test_windows_picker_options_use_ifileopendialog_modes(self):
        directory_options = _file_dialog_options("directory", 0)
        file_options = _file_dialog_options("file", 0)

        self.assertTrue(directory_options & FOS_PICKFOLDERS)
        self.assertTrue(directory_options & FOS_FORCEFILESYSTEM)
        self.assertTrue(directory_options & FOS_PATHMUSTEXIST)
        self.assertFalse(directory_options & FOS_FILEMUSTEXIST)
        self.assertTrue(file_options & FOS_FILEMUSTEXIST)
        self.assertTrue(file_options & FOS_FORCEFILESYSTEM)
        self.assertTrue(file_options & FOS_PATHMUSTEXIST)
        self.assertFalse(file_options & FOS_PICKFOLDERS)

    def test_windows_picker_delegates_to_ifileopendialog_backend(self):
        with patch("dancing_log.windows_picker._show_windows_file_open_dialog", return_value="C:\\temp\\x.sqlite3") as picker:
            selected = _run_windows_picker({"picker": "file", "label": "App database"}, "C:\\temp")

        self.assertEqual(selected, "C:\\temp\\x.sqlite3")
        picker.assert_called_once_with(mode="file", title="App database", initial="C:\\temp")


if __name__ == "__main__":
    unittest.main()
