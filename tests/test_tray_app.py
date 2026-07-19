import json
import sys
import tempfile
import threading
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

    @unittest.skipUnless(sys.platform == "win32", "Windows shutdown message test")
    def test_windows_query_end_session_accepts_without_cleanup(self):
        from dancing_log import _win_tray

        app = _win_tray.WindowsTrayApp.__new__(_win_tray.WindowsTrayApp)
        app._shutdown = Mock()
        app._hwnd = 123

        result = app._window_proc(
            app._hwnd,
            _win_tray.WM_QUERYENDSESSION,
            0,
            0,
        )

        self.assertEqual(result, 1)
        app._shutdown.assert_not_called()

    @unittest.skipUnless(sys.platform == "win32", "Windows shutdown message test")
    def test_windows_end_session_cleans_up_before_return(self):
        from dancing_log import _win_tray

        events: list[str] = []
        app = _win_tray.WindowsTrayApp.__new__(_win_tray.WindowsTrayApp)
        app._shutdown = Mock(side_effect=lambda **_kwargs: events.append("shutdown"))
        app._remove_tray_icon = Mock(side_effect=lambda: events.append("tray.remove"))
        app._hwnd = 123

        with (
            patch.object(
                _win_tray.user32,
                "PostQuitMessage",
                side_effect=lambda _code: events.append("quit"),
            ),
            patch.object(_win_tray.time, "monotonic", return_value=100.0),
        ):
            result = app._window_proc(
                app._hwnd,
                _win_tray.WM_ENDSESSION,
                1,
                0,
            )

        self.assertEqual(result, 0)
        self.assertEqual(events, ["shutdown", "tray.remove", "quit"])
        app._shutdown.assert_called_once_with(
            deadline=100.0 + _win_tray.END_SESSION_SHUTDOWN_TIMEOUT_SECONDS
        )

    @unittest.skipUnless(sys.platform == "win32", "Windows shutdown message test")
    def test_windows_cancelled_end_session_keeps_resources_open(self):
        from dancing_log import _win_tray

        app = _win_tray.WindowsTrayApp.__new__(_win_tray.WindowsTrayApp)
        app._shutdown = Mock()
        app._hwnd = 123

        result = app._window_proc(
            app._hwnd,
            _win_tray.WM_ENDSESSION,
            0,
            0,
        )

        self.assertEqual(result, 0)
        app._shutdown.assert_not_called()

    def test_shutdown_coordinator_is_ordered_and_idempotent(self):
        from dancing_log import tray_app

        events: list[str] = []
        instance = SimpleNamespace(
            close=Mock(side_effect=lambda: events.append("instance.close"))
        )
        runtime = SimpleNamespace(
            close=Mock(side_effect=lambda: events.append("runtime.close"))
        )
        server = SimpleNamespace(
            stop=Mock(side_effect=lambda: events.append("server.stop"))
        )
        coordinator = tray_app.TrayShutdownCoordinator(instance)
        coordinator.own_runtime(runtime)
        coordinator.own_server(server)

        coordinator.close()
        coordinator.close()

        self.assertEqual(events, ["server.stop", "runtime.close", "instance.close"])

    def test_shutdown_coordinator_propagates_one_deadline_and_releases_mutex(self):
        from dancing_log import tray_app

        events: list[str] = []

        def stop_server(*, deadline: float) -> None:
            events.append(f"server.stop:{deadline:g}")
            raise TimeoutError("HTTP drain deadline expired")

        instance = SimpleNamespace(
            close=Mock(side_effect=lambda: events.append("instance.close"))
        )
        runtime = SimpleNamespace(
            close=Mock(
                side_effect=lambda *, deadline: events.append(
                    f"runtime.close:{deadline:g}"
                )
            )
        )
        server = SimpleNamespace(
            stop=Mock(side_effect=stop_server)
        )
        coordinator = tray_app.TrayShutdownCoordinator(instance)
        coordinator.own_runtime(runtime)
        coordinator.own_server(server)

        with self.assertRaisesRegex(TimeoutError, "HTTP drain deadline expired"):
            coordinator.close(deadline=104.0)

        self.assertEqual(
            events,
            ["server.stop:104", "runtime.close:104", "instance.close"],
        )

    def test_shutdown_coordinator_preserves_composite_failure_on_repeat(self):
        from dancing_log import tray_app

        events: list[str] = []

        def fail(label: str, error: BaseException):
            def action() -> None:
                events.append(label)
                raise error

            return action

        instance = SimpleNamespace(
            close=Mock(side_effect=fail("instance.close", OSError("mutex failed")))
        )
        runtime = SimpleNamespace(
            close=Mock(side_effect=fail("runtime.close", RuntimeError("runtime failed")))
        )
        server = SimpleNamespace(
            stop=Mock(side_effect=fail("server.stop", TimeoutError("server failed")))
        )
        coordinator = tray_app.TrayShutdownCoordinator(instance)
        coordinator.own_runtime(runtime)
        coordinator.own_server(server)

        for _ in range(2):
            with self.assertRaises(ExceptionGroup) as context:
                coordinator.close()
            self.assertEqual(
                [str(error) for error in context.exception.exceptions],
                ["server failed", "runtime failed", "mutex failed"],
            )

        self.assertEqual(events, ["server.stop", "runtime.close", "instance.close"])

    def test_windows_shutdown_stops_server_before_runtime_close(self):
        events: list[str] = []
        instance = SimpleNamespace(
            close=Mock(side_effect=lambda: events.append("instance.close"))
        )
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
            patch(
                "dancing_log.tray_app._acquire_windows_desktop_instance",
                return_value=instance,
            ),
            patch("dancing_log.tray_app.TrayRuntime", return_value=runtime),
            patch("dancing_log.tray_app.WebUiServer", return_value=server),
            patch.dict(sys.modules, {"dancing_log._win_tray": fake_win_tray_module}),
        ):
            run_tray_webui_app(open_browser=False, app_root=".")

        runtime.close.assert_called_once_with()
        server.stop.assert_called_once_with()
        instance.close.assert_called_once_with()
        self.assertEqual(events, ["server.stop", "runtime.close", "instance.close"])

    def test_second_windows_entry_opens_existing_webui_without_starting_service(self):
        from dancing_log.desktop_instance import ExistingWebUiActivation

        with (
            patch.object(sys, "platform", "win32"),
            patch(
                "dancing_log.tray_app._acquire_windows_desktop_instance",
                return_value=None,
            ),
            patch(
                "dancing_log.tray_app._try_activate_existing_webui",
                return_value=ExistingWebUiActivation.READY,
            ) as activate_existing_webui,
            patch("dancing_log.tray_app.TrayRuntime") as tray_runtime,
            patch("dancing_log.tray_app.WebUiServer") as webui_server,
        ):
            run_tray_webui_app(open_browser=True, app_root=".")

        activate_existing_webui.assert_called_once()
        tray_runtime.assert_not_called()
        webui_server.assert_not_called()

    def test_second_windows_entry_honors_browser_suppression(self):
        from dancing_log.desktop_instance import ExistingWebUiActivation

        with (
            patch.object(sys, "platform", "win32"),
            patch(
                "dancing_log.tray_app._acquire_windows_desktop_instance",
                return_value=None,
            ),
            patch(
                "dancing_log.tray_app._try_activate_existing_webui",
                return_value=ExistingWebUiActivation.READY,
            ) as activate_existing_webui,
        ):
            run_tray_webui_app(open_browser=False, app_root=".")

        self.assertFalse(activate_existing_webui.call_args.kwargs["open_browser"])

    def test_second_windows_entry_reselects_as_primary_after_owner_releases_mutex(self):
        from dancing_log.desktop_instance import ExistingWebUiActivation

        instance = SimpleNamespace(close=Mock())
        runtime = SimpleNamespace(session=object(), close=Mock())
        server = SimpleNamespace(start=Mock(), stop=Mock())
        tray_window = SimpleNamespace(run=Mock())
        fake_win_tray_module = SimpleNamespace(
            WindowsTrayApp=Mock(return_value=tray_window)
        )

        with (
            patch.object(sys, "platform", "win32"),
            patch(
                "dancing_log.tray_app._acquire_windows_desktop_instance",
                side_effect=[None, instance],
            ) as acquire_instance,
            patch(
                "dancing_log.tray_app._try_activate_existing_webui",
                return_value=ExistingWebUiActivation.NOT_READY,
            ),
            patch("dancing_log.tray_app.time.sleep"),
            patch("dancing_log.tray_app.TrayRuntime", return_value=runtime),
            patch("dancing_log.tray_app.WebUiServer", return_value=server),
            patch.dict(sys.modules, {"dancing_log._win_tray": fake_win_tray_module}),
        ):
            run_tray_webui_app(open_browser=True, app_root=".")

        self.assertEqual(acquire_instance.call_count, 2)
        server.start.assert_called_once_with()
        tray_window.run.assert_called_once_with(open_browser=True)
        instance.close.assert_called_once_with()

    def test_second_windows_entry_reports_failure_when_owner_remains_unready(self):
        from dancing_log.desktop_instance import ExistingWebUiActivation

        show_error_message = Mock()
        fake_win_tray_module = SimpleNamespace(show_error_message=show_error_message)

        with (
            patch.object(sys, "platform", "win32"),
            patch(
                "dancing_log.tray_app._acquire_windows_desktop_instance",
                return_value=None,
            ) as acquire_instance,
            patch(
                "dancing_log.tray_app._try_activate_existing_webui",
                return_value=ExistingWebUiActivation.NOT_READY,
            ),
            patch(
                "dancing_log.tray_app.time.monotonic",
                side_effect=[10.0, 15.0, 15.0],
            ),
            patch.dict(sys.modules, {"dancing_log._win_tray": fake_win_tray_module}),
        ):
            run_tray_webui_app(open_browser=True, app_root=".")

        self.assertEqual(acquire_instance.call_count, 2)
        show_error_message.assert_called_once()
        self.assertIn("could not activate", show_error_message.call_args.args[0])

    def test_second_windows_entry_shows_activation_failure(self):
        from dancing_log.desktop_instance import ExistingWebUiActivation

        show_error_message = Mock()
        fake_win_tray_module = SimpleNamespace(show_error_message=show_error_message)

        with (
            patch.object(sys, "platform", "win32"),
            patch(
                "dancing_log.tray_app._acquire_windows_desktop_instance",
                return_value=None,
            ),
            patch(
                "dancing_log.tray_app._try_activate_existing_webui",
                return_value=ExistingWebUiActivation.FAILED,
            ),
            patch.dict(sys.modules, {"dancing_log._win_tray": fake_win_tray_module}),
        ):
            run_tray_webui_app(open_browser=True, app_root=".")

        show_error_message.assert_called_once()
        self.assertIn("could not activate", show_error_message.call_args.args[0])

    def test_windows_shutdown_closes_runtime_when_server_stop_fails(self):
        instance = SimpleNamespace(close=Mock())
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
            patch(
                "dancing_log.tray_app._acquire_windows_desktop_instance",
                return_value=instance,
            ),
            patch("dancing_log.tray_app.TrayRuntime", return_value=runtime),
            patch("dancing_log.tray_app.WebUiServer", return_value=server),
            patch.dict(sys.modules, {"dancing_log._win_tray": fake_win_tray_module}),
            self.assertRaisesRegex(TimeoutError, "slow SSE drain"),
        ):
            run_tray_webui_app(open_browser=False, app_root=".")

        server.stop.assert_called_once_with()
        runtime.close.assert_called_once_with()
        instance.close.assert_called_once_with()

    def test_windows_start_failure_closes_runtime_and_instance(self):
        events: list[str] = []
        instance = SimpleNamespace(
            close=Mock(side_effect=lambda: events.append("instance.close"))
        )
        runtime = SimpleNamespace(
            session=object(),
            close=Mock(side_effect=lambda: events.append("runtime.close")),
        )
        server = SimpleNamespace(
            start=Mock(side_effect=OSError("address already in use")),
            stop=Mock(side_effect=lambda: events.append("server.stop")),
        )
        fake_win_tray_module = SimpleNamespace(WindowsTrayApp=Mock())

        with (
            patch.object(sys, "platform", "win32"),
            patch(
                "dancing_log.tray_app._acquire_windows_desktop_instance",
                return_value=instance,
            ),
            patch("dancing_log.tray_app.TrayRuntime", return_value=runtime),
            patch("dancing_log.tray_app.WebUiServer", return_value=server),
            patch.dict(sys.modules, {"dancing_log._win_tray": fake_win_tray_module}),
            self.assertRaisesRegex(OSError, "address already in use"),
        ):
            run_tray_webui_app(open_browser=False, app_root=".")

        server.stop.assert_called_once_with()
        runtime.close.assert_called_once_with()
        instance.close.assert_called_once_with()
        self.assertEqual(events, ["server.stop", "runtime.close", "instance.close"])

    def test_windows_server_construction_failure_closes_runtime_and_instance(self):
        events: list[str] = []
        instance = SimpleNamespace(
            close=Mock(side_effect=lambda: events.append("instance.close"))
        )
        runtime = SimpleNamespace(
            session=object(),
            close=Mock(side_effect=lambda: events.append("runtime.close")),
        )

        with (
            patch.object(sys, "platform", "win32"),
            patch(
                "dancing_log.tray_app._acquire_windows_desktop_instance",
                return_value=instance,
            ),
            patch("dancing_log.tray_app.TrayRuntime", return_value=runtime),
            patch(
                "dancing_log.tray_app.WebUiServer",
                side_effect=OSError("server construction failed"),
            ),
            self.assertRaisesRegex(OSError, "server construction failed"),
        ):
            run_tray_webui_app(open_browser=False, app_root=".")

        runtime.close.assert_called_once_with()
        instance.close.assert_called_once_with()
        self.assertEqual(events, ["runtime.close", "instance.close"])

    def test_windows_shutdown_preserves_server_and_instance_close_failures(self):
        instance = SimpleNamespace(
            close=Mock(side_effect=OSError("mutex cleanup failed"))
        )
        runtime = SimpleNamespace(session=object(), close=Mock())
        server = SimpleNamespace(
            start=Mock(),
            stop=Mock(side_effect=TimeoutError("server cleanup failed")),
        )
        tray_window = SimpleNamespace(run=Mock())
        fake_win_tray_module = SimpleNamespace(
            WindowsTrayApp=Mock(return_value=tray_window)
        )

        with (
            patch.object(sys, "platform", "win32"),
            patch(
                "dancing_log.tray_app._acquire_windows_desktop_instance",
                return_value=instance,
            ),
            patch("dancing_log.tray_app.TrayRuntime", return_value=runtime),
            patch("dancing_log.tray_app.WebUiServer", return_value=server),
            patch.dict(sys.modules, {"dancing_log._win_tray": fake_win_tray_module}),
            self.assertRaises(ExceptionGroup) as context,
        ):
            run_tray_webui_app(open_browser=False, app_root=".")

        self.assertEqual(
            [str(error) for error in context.exception.exceptions],
            ["server cleanup failed", "mutex cleanup failed"],
        )
        runtime.close.assert_called_once_with()

    def test_windows_entry_rejects_noncanonical_port_before_acquiring_instance(self):
        with (
            patch.object(sys, "platform", "win32"),
            patch(
                "dancing_log.tray_app._acquire_windows_desktop_instance",
                return_value=None,
            ) as acquire_instance,
            self.assertRaisesRegex(ValueError, "canonical port"),
        ):
            run_tray_webui_app(port=9988, open_browser=False, app_root=".")

        acquire_instance.assert_not_called()

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
