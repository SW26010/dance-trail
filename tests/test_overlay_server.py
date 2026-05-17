import json
import unittest
from urllib.request import urlopen

from dancing_log.overlay_server import OverlayServer, OverlayState


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
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
