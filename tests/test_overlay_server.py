import json
import unittest
from urllib.request import urlopen

from dancing_log.overlay_server import OverlayServer, OverlayState, _OVERLAY_HTML


class OverlayServerTest(unittest.TestCase):
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

            with urlopen(f"http://127.0.0.1:{server.port}/state", timeout=2) as response:
                state = json.loads(response.read().decode("utf-8"))
            self.assertEqual(state["current"]["dance_external_id"], "3114")
            self.assertEqual(state["current_view"]["source_label"], "source player: Alice")
            self.assertEqual(state["current_view"]["timer"]["mode"], "elapsed_total")

            with urlopen(f"http://127.0.0.1:{server.port}/overlay", timeout=2) as response:
                html = response.read().decode("utf-8")
            self.assertIn("/events", html)
            self.assertIn("/state", html)
            self.assertNotIn("https://", html)
            self.assertNotIn("http://", html)
        finally:
            server.stop()

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
            with urlopen(f"http://127.0.0.1:{server.port}/events", timeout=2) as response:
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
        self.assertIn("state.currentView = snapshot.current_view || null;", _OVERLAY_HTML)
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
