import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

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
    @unittest.skipUnless(sys.platform == "win32", "Windows tray callback test")
    def test_windows_tray_callback_contains_lifecycle_timeout(self):
        from dancing_log import _win_tray

        app = _win_tray.WindowsTrayApp.__new__(_win_tray.WindowsTrayApp)
        app.runtime = SimpleNamespace(
            toggle_watcher=Mock(side_effect=TimeoutError("watcher is still stopping"))
        )
        app._hwnd = 123

        with patch.object(_win_tray.user32, "MessageBoxW", return_value=1) as message_box:
            result = app._window_proc(
                app._hwnd,
                _win_tray.WM_COMMAND,
                _win_tray.IDM_TOGGLE_WATCHER,
                0,
            )

        self.assertEqual(result, 0)
        message_box.assert_called_once()
        self.assertIn("watcher is still stopping", message_box.call_args.args[1])

    def test_windows_shutdown_stops_server_before_runtime_close(self):
        events: list[str] = []
        runtime = SimpleNamespace(
            session=object(),
            close=Mock(side_effect=lambda: events.append("runtime.close")),
        )
        server = SimpleNamespace(
            start=Mock(),
            stop=Mock(side_effect=lambda: events.append("server.stop")),
        )
        tray_window = SimpleNamespace(run=Mock())
        windows_tray_app = Mock(return_value=tray_window)
        fake_win_tray_module = SimpleNamespace(WindowsTrayApp=windows_tray_app)

        with (
            patch.object(sys, "platform", "win32"),
            patch("dancing_log.tray_app.TrayRuntime", return_value=runtime),
            patch("dancing_log.tray_app.WebUiServer", return_value=server),
            patch.dict(sys.modules, {"dancing_log._win_tray": fake_win_tray_module}),
        ):
            run_tray_webui_app(port=9988, open_browser=False, app_root=".")

        runtime.close.assert_called_once_with()
        server.stop.assert_called_once_with()
        self.assertEqual(events, ["server.stop", "runtime.close"])

    def test_windows_shutdown_closes_runtime_when_server_stop_fails(self):
        runtime = SimpleNamespace(session=object(), close=Mock())
        server = SimpleNamespace(
            start=Mock(),
            stop=Mock(side_effect=TimeoutError("slow SSE drain")),
        )
        tray_window = SimpleNamespace(run=Mock())
        fake_win_tray_module = SimpleNamespace(
            WindowsTrayApp=Mock(return_value=tray_window)
        )

        with (
            patch.object(sys, "platform", "win32"),
            patch("dancing_log.tray_app.TrayRuntime", return_value=runtime),
            patch("dancing_log.tray_app.WebUiServer", return_value=server),
            patch.dict(sys.modules, {"dancing_log._win_tray": fake_win_tray_module}),
            self.assertRaisesRegex(TimeoutError, "slow SSE drain"),
        ):
            run_tray_webui_app(port=9988, open_browser=False, app_root=".")

        server.stop.assert_called_once_with()
        runtime.close.assert_called_once_with()

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
                self.assertFalse(calls[-1]["live_db"])
                self.assertTrue(calls[-1]["record_playback"])
                self.assertIsNone(calls[-1]["overlay_port"])

                labels = [item.label for item in runtime.menu_items() if item.command_id]
                self.assertIn("Stop watcher", labels)
                self.assertIn("Start overlay", labels)

                runtime.start_overlay()
                wait_for_call_count(calls, 2)
                self.assertTrue(runtime.watcher_running)
                self.assertTrue(runtime.overlay_running)
                self.assertEqual(calls[-1]["overlay_port"], 9911)
                self.assertTrue(calls[-1]["record_playback"])

                labels = [item.label for item in runtime.menu_items() if item.command_id]
                self.assertIn("Stop watcher", labels)
                self.assertIn("Stop overlay", labels)

                runtime.stop_overlay()
                wait_for_call_count(calls, 3)
                self.assertTrue(runtime.watcher_running)
                self.assertFalse(runtime.overlay_running)
                self.assertIsNone(calls[-1]["overlay_port"])
                self.assertTrue(calls[-1]["record_playback"])
            finally:
                runtime.close()


if __name__ == "__main__":
    unittest.main()
