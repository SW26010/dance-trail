import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from dancing_log.app_paths import DEFAULT_CONFIG
from dancing_log.tray_app import TrayRuntime, run_tray_webui_app


def wait_for_call_count(calls: list[dict], count: int) -> None:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if len(calls) >= count:
            return
        time.sleep(0.01)
    raise AssertionError(f"expected {count} watcher calls, got {len(calls)}")


class TrayRuntimeTest(unittest.TestCase):
    def test_non_windows_entry_uses_webui_server_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(sys, "platform", "linux"),
                patch("dancing_log.webui_server.run_webui_server") as run_webui_server,
            ):
                run_tray_webui_app(port=9988, open_browser=False, app_root=root)

        run_webui_server.assert_called_once_with(
            port=9988,
            open_browser=False,
            app_root=root,
        )

    def test_menu_labels_follow_watcher_and_overlay_state(self):
        calls: list[dict] = []

        def fake_watch_vrc_logs(**kwargs):
            calls.append(kwargs)
            kwargs["stop_event"].wait(timeout=2.0)
            return {"overlay_port": kwargs["overlay_port"]}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "logs").mkdir()
            config = dict(DEFAULT_CONFIG)
            config["vrc_log_dir"] = str(root / "logs")
            config["overlay_port"] = 9911
            config_path = root / "config" / "dancing-log.local.json"
            config_path.parent.mkdir()
            config_path.write_text(json.dumps(config), encoding="utf-8")

            runtime = TrayRuntime(
                app_root=root,
                watch_vrc_logs_func=fake_watch_vrc_logs,
            )
            try:
                labels = [item.label for item in runtime.menu_items() if item.command_id]
                self.assertIn("Start watcher", labels)
                self.assertIn("Start overlay", labels)

                runtime.start_watcher(overlay=False)
                wait_for_call_count(calls, 1)
                self.assertTrue(runtime.watcher_running)
                self.assertFalse(runtime.overlay_running)
                self.assertEqual(calls[-1]["log_dir"], root / "logs")
                self.assertEqual(calls[-1]["output_dir"], root / "logs" / "captures")
                self.assertEqual(calls[-1]["app_db_path"], root / "data" / "dancing_log.sqlite3")
                self.assertEqual(calls[-1]["source_log_dir"], root / "logs" / "source-vrc-logs")
                self.assertTrue(calls[-1]["live_db"])
                self.assertTrue(calls[-1]["promote_live"])
                self.assertIsNone(calls[-1]["overlay_port"])

                labels = [item.label for item in runtime.menu_items() if item.command_id]
                self.assertIn("Stop watcher", labels)
                self.assertIn("Start overlay", labels)

                runtime.start_overlay()
                wait_for_call_count(calls, 2)
                self.assertTrue(runtime.watcher_running)
                self.assertTrue(runtime.overlay_running)
                self.assertEqual(calls[-1]["overlay_port"], 9911)
                self.assertTrue(calls[-1]["promote_live"])

                labels = [item.label for item in runtime.menu_items() if item.command_id]
                self.assertIn("Stop watcher", labels)
                self.assertIn("Stop overlay", labels)

                runtime.stop_overlay()
                wait_for_call_count(calls, 3)
                self.assertTrue(runtime.watcher_running)
                self.assertFalse(runtime.overlay_running)
                self.assertIsNone(calls[-1]["overlay_port"])
                self.assertTrue(calls[-1]["promote_live"])
            finally:
                runtime.close()


if __name__ == "__main__":
    unittest.main()
