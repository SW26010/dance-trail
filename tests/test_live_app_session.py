import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import tempfile
import threading
import time
import unittest

from dancing_log.app_paths import DEFAULT_CONFIG
from dancing_log.live_app_session import LiveAppSessionRuntime, LiveWatcherRunOptions
from dancing_log.overlay_server import MountedOverlayAdapter, OverlayState


def wait_for_call_count(calls: list[dict], count: int) -> None:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if len(calls) >= count:
            return
        time.sleep(0.01)
    raise AssertionError(f"expected {count} watcher calls, got {len(calls)}")


def _capture_error(errors: list[Exception], action) -> None:
    try:
        action()
    except Exception as exc:
        errors.append(exc)


class LiveAppSessionRuntimeTest(unittest.TestCase):
    def test_watcher_lifetime_is_exclusive_across_runtime_scopes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shared_db = root / "shared" / "playback.sqlite3"
            cases = (
                (
                    "same app with different databases",
                    root / "same-app",
                    root / "same-app",
                    root / "one.sqlite3",
                    root / "two.sqlite3",
                ),
                (
                    "different apps with same database",
                    root / "app-one",
                    root / "app-two",
                    shared_db,
                    shared_db,
                ),
            )
            for label, first_root, second_root, first_db, second_db in cases:
                with self.subTest(label=label):
                    watcher_started = threading.Event()
                    release_watcher = threading.Event()

                    def blocking_watch_vrc_logs(**_kwargs):
                        watcher_started.set()
                        release_watcher.wait(timeout=2.0)
                        return {"finished": True}

                    first = LiveAppSessionRuntime(
                        app_root=first_root,
                        watch_vrc_logs_func=blocking_watch_vrc_logs,
                    )
                    second = LiveAppSessionRuntime(
                        app_root=second_root,
                        watch_vrc_logs_func=lambda **_kwargs: {"second": True},
                    )
                    first_errors: list[Exception] = []
                    first_thread = threading.Thread(
                        target=lambda: _capture_error(
                            first_errors,
                            lambda: first.run_watcher(
                                LiveWatcherRunOptions(app_db_path=first_db)
                            ),
                        )
                    )
                    try:
                        first_thread.start()
                        self.assertTrue(watcher_started.wait(timeout=1.0))

                        with self.assertRaisesRegex(RuntimeError, "already active"):
                            second.run_watcher(
                                LiveWatcherRunOptions(app_db_path=second_db)
                            )
                    finally:
                        release_watcher.set()
                        first_thread.join(timeout=1.0)
                        first.close()

                    self.assertEqual(first_errors, [])
                    try:
                        self.assertEqual(
                            second.run_watcher(
                                LiveWatcherRunOptions(app_db_path=second_db)
                            ),
                            {"second": True},
                        )
                    finally:
                        second.close()

    def test_watcher_lifetime_lock_is_cross_process(self):
        watcher_started = threading.Event()

        def blocking_watch_vrc_logs(**kwargs):
            watcher_started.set()
            kwargs["stop_event"].wait(timeout=5.0)
            return {"finished": True}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            probe_command = [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "from dancing_log.live_app_session import LiveAppSessionRuntime; "
                    "runtime=LiveAppSessionRuntime(app_root=sys.argv[1], "
                    "watch_vrc_logs_func=lambda **kwargs: None); "
                    "\ntry: runtime.run_watcher()\n"
                    "except BaseException as exc: "
                    "print(type(exc).__name__, str(exc)); sys.exit(3)\n"
                    "else: print('started'); sys.exit(0)"
                ),
                str(root),
            ]
            runtime = LiveAppSessionRuntime(
                app_root=root,
                watch_vrc_logs_func=blocking_watch_vrc_logs,
            )
            try:
                runtime.start_watcher()
                self.assertTrue(watcher_started.wait(timeout=1.0))
                probe = subprocess.run(
                    probe_command,
                    cwd=Path(__file__).resolve().parents[1],
                    capture_output=True,
                    text=True,
                    timeout=5.0,
                    check=False,
                )

                self.assertEqual(probe.returncode, 3, probe.stdout + probe.stderr)
                self.assertIn("already active", probe.stdout)
            finally:
                runtime.close()

            released_probe = subprocess.run(
                probe_command,
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                timeout=5.0,
                check=False,
            )
            self.assertEqual(
                released_probe.returncode,
                0,
                released_probe.stdout + released_probe.stderr,
            )

    def test_background_base_exception_is_reported_and_rethrown_by_close(self):
        watcher_failed = threading.Event()

        def system_exit_watch_vrc_logs(**_kwargs):
            watcher_failed.set()
            raise SystemExit("watcher terminated")

        with tempfile.TemporaryDirectory() as tmp:
            runtime = LiveAppSessionRuntime(
                app_root=tmp,
                watch_vrc_logs_func=system_exit_watch_vrc_logs,
            )
            runtime.start_watcher()
            self.assertTrue(watcher_failed.wait(timeout=1.0))
            deadline = time.monotonic() + 1.0
            while runtime.watcher_running and time.monotonic() < deadline:
                time.sleep(0.01)

            self.assertEqual(runtime.last_error, "watcher terminated")
            with self.assertRaisesRegex(SystemExit, "watcher terminated"):
                runtime.close()

        self.assertEqual(runtime.status().session_state, "closed")

    def test_interactive_stop_times_out_while_overlay_finalizer_is_blocked(self):
        close_started = threading.Event()
        allow_close = threading.Event()

        class BlockingCloseOverlay(MountedOverlayAdapter):
            def close(self) -> None:
                close_started.set()
                allow_close.wait(timeout=2.0)
                super().close()

        def watch_vrc_logs(**_kwargs):
            return {"finished": True}

        with tempfile.TemporaryDirectory() as tmp:
            runtime = LiveAppSessionRuntime(
                app_root=tmp,
                watch_vrc_logs_func=watch_vrc_logs,
                mounted_overlay=BlockingCloseOverlay(
                    OverlayState(enabled=False),
                    url="http://127.0.0.1:8787/overlay",
                ),
                watcher_stop_timeout_seconds=0.05,
            )
            runtime.start_overlay()
            self.assertTrue(close_started.wait(timeout=1.0))
            stop_errors: list[Exception] = []
            stop_thread = threading.Thread(
                target=lambda: _capture_error(stop_errors, runtime.stop_watcher)
            )
            try:
                stop_thread.start()
                stop_thread.join(timeout=0.2)

                self.assertFalse(stop_thread.is_alive())
                self.assertEqual(len(stop_errors), 1)
                self.assertIsInstance(stop_errors[0], TimeoutError)
                self.assertEqual(runtime.status().watcher_state, "stopping")
            finally:
                allow_close.set()
                stop_thread.join(timeout=1.0)
                runtime.close()

    def test_close_propagates_watcher_generation_failure_after_join(self):
        watcher_failed = threading.Event()

        def failing_watch_vrc_logs(**_kwargs):
            watcher_failed.set()
            raise RuntimeError("watcher finalization failed")

        with tempfile.TemporaryDirectory() as tmp:
            runtime = LiveAppSessionRuntime(
                app_root=tmp,
                watch_vrc_logs_func=failing_watch_vrc_logs,
            )
            runtime.start_watcher()
            self.assertTrue(watcher_failed.wait(timeout=1.0))

            with self.assertRaisesRegex(RuntimeError, "watcher finalization failed"):
                runtime.close()

        self.assertEqual(runtime.status().session_state, "closed")
        self.assertEqual(runtime.status().watcher_state, "stopped")
        self.assertEqual(runtime.last_error, "watcher finalization failed")

    def test_close_is_terminal_and_concurrent_start_cannot_revive_watcher(self):
        calls: list[dict] = []
        cleanup_started = threading.Event()
        allow_cleanup = threading.Event()

        def slow_watch_vrc_logs(**kwargs):
            calls.append(kwargs)
            kwargs["stop_event"].wait(timeout=2.0)
            cleanup_started.set()
            allow_cleanup.wait(timeout=2.0)
            return {"call": len(calls)}

        with tempfile.TemporaryDirectory() as tmp:
            runtime = LiveAppSessionRuntime(
                app_root=tmp,
                watch_vrc_logs_func=slow_watch_vrc_logs,
            )
            runtime.start_watcher()
            wait_for_call_count(calls, 1)

            close_errors: list[Exception] = []
            start_errors: list[Exception] = []
            start_attempted = threading.Event()
            close_thread = threading.Thread(
                target=lambda: _capture_error(close_errors, runtime.close)
            )
            close_thread.start()
            self.assertTrue(cleanup_started.wait(timeout=1.0))

            def start_during_close() -> None:
                start_attempted.set()
                _capture_error(start_errors, runtime.start_watcher)

            start_thread = threading.Thread(target=start_during_close)
            start_thread.start()
            self.assertTrue(start_attempted.wait(timeout=1.0))
            start_thread.join(timeout=0.1)
            self.assertTrue(start_thread.is_alive())

            allow_cleanup.set()
            close_thread.join(timeout=1.0)
            start_thread.join(timeout=1.0)

            self.assertFalse(close_thread.is_alive())
            self.assertFalse(start_thread.is_alive())
            self.assertEqual(close_errors, [])
            self.assertEqual(len(start_errors), 1)
            self.assertIsInstance(start_errors[0], RuntimeError)
            self.assertRegex(str(start_errors[0]), "closed")
            self.assertEqual(len(calls), 1)
            self.assertEqual(runtime.status().session_state, "closed")
            self.assertEqual(runtime.status().watcher_state, "stopped")

            runtime.close()
            with self.assertRaisesRegex(RuntimeError, "closed"):
                runtime.start_overlay()

    def test_watcher_finalizer_cannot_disable_a_new_overlay_generation(self):
        calls: list[dict] = []
        close_started = threading.Event()
        allow_close = threading.Event()

        class BlockingCloseOverlay(MountedOverlayAdapter):
            def close(self) -> None:
                super().close()
                close_started.set()
                allow_close.wait(timeout=2.0)

        def watch_vrc_logs(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return {"call": 1}
            kwargs["stop_event"].wait(timeout=2.0)
            return {"call": len(calls)}

        with tempfile.TemporaryDirectory() as tmp:
            state = OverlayState(enabled=False)
            runtime = LiveAppSessionRuntime(
                app_root=tmp,
                watch_vrc_logs_func=watch_vrc_logs,
                mounted_overlay=BlockingCloseOverlay(
                    state,
                    url="http://127.0.0.1:8787/overlay",
                ),
            )
            try:
                runtime.start_overlay()
                self.assertTrue(close_started.wait(timeout=1.0))

                start_errors: list[Exception] = []
                start_attempted = threading.Event()

                def start_new_overlay_generation() -> None:
                    start_attempted.set()
                    _capture_error(start_errors, runtime.start_overlay)

                start_thread = threading.Thread(target=start_new_overlay_generation)
                start_thread.start()
                self.assertTrue(start_attempted.wait(timeout=1.0))
                start_thread.join(timeout=0.1)
                self.assertTrue(start_thread.is_alive())

                allow_close.set()
                start_thread.join(timeout=1.0)
                wait_for_call_count(calls, 2)

                self.assertFalse(start_thread.is_alive())
                self.assertEqual(start_errors, [])
                self.assertEqual(runtime.status().watcher_state, "running")
                self.assertEqual(runtime.status().overlay_state, "running")
                self.assertTrue(state.snapshot()["overlay_enabled"])
            finally:
                allow_close.set()
                runtime.close()

    def test_same_mode_start_waits_for_stopping_watcher_then_restarts(self):
        calls: list[dict] = []
        allow_cleanup = threading.Event()

        def slow_watch_vrc_logs(**kwargs):
            calls.append(kwargs)
            kwargs["stop_event"].wait(timeout=2.0)
            allow_cleanup.wait(timeout=2.0)
            return {"overlay_port": kwargs["overlay_port"]}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config" / "dancing-log.local.json"
            config_path.parent.mkdir()
            config_path.write_text(json.dumps(DEFAULT_CONFIG), encoding="utf-8")
            runtime = LiveAppSessionRuntime(
                app_root=root,
                watch_vrc_logs_func=slow_watch_vrc_logs,
                watcher_stop_timeout_seconds=0.05,
            )
            try:
                runtime.start_watcher()
                wait_for_call_count(calls, 1)
                with self.assertRaises(TimeoutError):
                    runtime.stop_watcher()

                release = threading.Timer(0.01, allow_cleanup.set)
                release.start()
                runtime.start_watcher()
                release.join(timeout=1.0)

                wait_for_call_count(calls, 2)
                self.assertEqual(runtime.status().watcher_state, "running")
            finally:
                allow_cleanup.set()
                runtime.close()

    def test_same_mode_start_during_stopping_never_succeeds_silently(self):
        for overlay in (False, True):
            with self.subTest(overlay=overlay), tempfile.TemporaryDirectory() as tmp:
                calls: list[dict] = []
                allow_cleanup = threading.Event()

                def slow_watch_vrc_logs(**kwargs):
                    calls.append(kwargs)
                    kwargs["stop_event"].wait(timeout=2.0)
                    allow_cleanup.wait(timeout=2.0)
                    return {"overlay_port": kwargs["overlay_port"]}

                root = Path(tmp)
                config_path = root / "config" / "dancing-log.local.json"
                config_path.parent.mkdir()
                config_path.write_text(json.dumps(DEFAULT_CONFIG), encoding="utf-8")
                runtime = LiveAppSessionRuntime(
                    app_root=root,
                    watch_vrc_logs_func=slow_watch_vrc_logs,
                    watcher_stop_timeout_seconds=0.05,
                )
                try:
                    runtime.start_watcher(overlay=overlay)
                    wait_for_call_count(calls, 1)
                    with self.assertRaisesRegex(TimeoutError, "did not stop"):
                        runtime.stop_watcher()

                    self.assertEqual(runtime.status().watcher_state, "stopping")
                    self.assertEqual(
                        runtime.status().overlay_state,
                        "stopping" if overlay else "stopped",
                    )
                    with self.assertRaisesRegex(TimeoutError, "did not stop"):
                        runtime.start_watcher(overlay=overlay)

                    self.assertEqual(len(calls), 1)
                    self.assertEqual(runtime.status().watcher_state, "stopping")
                finally:
                    allow_cleanup.set()
                    deadline = time.monotonic() + 2.0
                    while runtime.watcher_running and time.monotonic() < deadline:
                        time.sleep(0.01)
                    runtime.close()

    def test_start_overlay_does_not_stop_or_replace_running_watcher(self):
        calls: list[dict] = []
        allow_cleanup = threading.Event()

        def slow_watch_vrc_logs(**kwargs):
            calls.append(kwargs)
            kwargs["stop_event"].wait(timeout=2.0)
            allow_cleanup.wait(timeout=2.0)
            return {"overlay_port": kwargs["overlay_port"]}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config" / "dancing-log.local.json"
            config_path.parent.mkdir()
            config_path.write_text(json.dumps(DEFAULT_CONFIG), encoding="utf-8")
            state = OverlayState(enabled=False)
            runtime = LiveAppSessionRuntime(
                app_root=root,
                watch_vrc_logs_func=slow_watch_vrc_logs,
                mounted_overlay=MountedOverlayAdapter(
                    state,
                    url="http://127.0.0.1:8787/overlay",
                ),
                watcher_stop_timeout_seconds=0.05,
            )
            try:
                runtime.start_watcher()
                wait_for_call_count(calls, 1)
                original_stop_event = calls[0]["stop_event"]

                runtime.start_overlay()

                self.assertEqual(len(calls), 1)
                self.assertFalse(original_stop_event.is_set())
                self.assertTrue(runtime.watcher_running)
                self.assertTrue(runtime.overlay_running)
                self.assertTrue(state.snapshot()["overlay_enabled"])
            finally:
                allow_cleanup.set()
                runtime.close()

    def test_stop_overlay_does_not_settle_or_restart_watcher(self):
        calls: list[dict] = []
        settlements: list[str] = []

        def slow_watch_vrc_logs(**kwargs):
            calls.append(kwargs)
            kwargs["stop_event"].wait(timeout=2.0)
            settlements.append("watcher_stopped")
            return {"overlay_port": kwargs["overlay_port"]}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config" / "dancing-log.local.json"
            config_path.parent.mkdir()
            config_path.write_text(json.dumps(DEFAULT_CONFIG), encoding="utf-8")
            state = OverlayState(enabled=False)
            runtime = LiveAppSessionRuntime(
                app_root=root,
                watch_vrc_logs_func=slow_watch_vrc_logs,
                mounted_overlay=MountedOverlayAdapter(
                    state,
                    url="http://127.0.0.1:8787/overlay",
                ),
                watcher_stop_timeout_seconds=0.05,
            )
            try:
                runtime.start_overlay()
                wait_for_call_count(calls, 1)
                original_stop_event = calls[0]["stop_event"]

                runtime.stop_overlay()

                self.assertEqual(len(calls), 1)
                self.assertFalse(original_stop_event.is_set())
                self.assertEqual(settlements, [])
                self.assertTrue(runtime.watcher_running)
                self.assertFalse(runtime.overlay_running)
                self.assertFalse(state.snapshot()["overlay_enabled"])
            finally:
                runtime.close()

    def test_close_waits_for_watcher_cleanup_past_interactive_timeout(self):
        cleanup_started = threading.Event()
        allow_cleanup = threading.Event()
        cleanup_finished = threading.Event()

        def slow_watch_vrc_logs(**kwargs):
            kwargs["stop_event"].wait(timeout=2.0)
            cleanup_started.set()
            allow_cleanup.wait(timeout=2.0)
            cleanup_finished.set()
            return {"closed": True}

        with tempfile.TemporaryDirectory() as tmp:
            runtime = LiveAppSessionRuntime(
                app_root=tmp,
                watch_vrc_logs_func=slow_watch_vrc_logs,
                watcher_stop_timeout_seconds=0.01,
            )
            runtime.start_watcher()
            deadline = time.monotonic() + 2.0
            while not runtime.watcher_running and time.monotonic() < deadline:
                time.sleep(0.01)

            release = threading.Timer(0.05, allow_cleanup.set)
            release.start()
            runtime.close()
            release.join(timeout=1.0)

        self.assertTrue(cleanup_started.is_set())
        self.assertTrue(cleanup_finished.is_set())
        self.assertFalse(runtime.watcher_running)

    def test_mounted_overlay_deactivates_when_watcher_start_fails(self):
        def fake_watch_vrc_logs(**_kwargs):
            raise RuntimeError("watch failed")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config" / "dancing-log.local.json"
            config_path.parent.mkdir()
            config_path.write_text(json.dumps(DEFAULT_CONFIG), encoding="utf-8")
            state = OverlayState(enabled=False)
            runtime = LiveAppSessionRuntime(
                app_root=root,
                watch_vrc_logs_func=fake_watch_vrc_logs,
                mounted_overlay=MountedOverlayAdapter(
                    state,
                    url="http://127.0.0.1:8787/overlay",
                ),
            )

            runtime.start_overlay()
            deadline = time.monotonic() + 2.0
            while runtime.last_error is None and time.monotonic() < deadline:
                time.sleep(0.01)

        snapshot = state.snapshot()
        self.assertEqual(runtime.last_error, "watch failed")
        self.assertFalse(snapshot["overlay_enabled"])
        self.assertEqual(snapshot["status"]["event_type"], "overlay-stopped")

    def test_live_overlay_control_preserves_watcher_and_current_context(self):
        calls: list[dict] = []

        def fake_watch_vrc_logs(**kwargs):
            calls.append(kwargs)
            kwargs["overlay"].publish(
                {
                    "event_key": "wannadance:3114#1",
                    "dance_system_key": "wannadance",
                    "dance_external_id": "3114",
                    "actual_play_at": "2026.05.17 15:30:10",
                }
            )
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
            state = OverlayState(enabled=False)

            runtime = LiveAppSessionRuntime(
                app_root=root,
                watch_vrc_logs_func=fake_watch_vrc_logs,
                mounted_overlay=MountedOverlayAdapter(
                    state,
                    url="http://127.0.0.1:8787/overlay",
                ),
            )
            try:
                runtime.start_watcher()
                wait_for_call_count(calls, 1)
                self.assertTrue(runtime.status().watcher_running)
                self.assertFalse(runtime.status().overlay_running)
                self.assertEqual(calls[-1]["log_dir"], root / "logs")
                self.assertEqual(calls[-1]["output_dir"], root / "logs" / "captures")
                self.assertEqual(calls[-1]["app_db_path"], root / "data" / "dancing_log.sqlite3")
                self.assertEqual(calls[-1]["source_log_dir"], root / "logs" / "source-vrc-logs")
                self.assertFalse(calls[-1]["live_db"])
                self.assertTrue(calls[-1]["record_playback"])
                self.assertIsNone(calls[-1]["overlay_port"])
                self.assertIn("overlay", calls[-1])

                runtime.start_overlay()
                self.assertEqual(len(calls), 1)
                self.assertTrue(runtime.status().watcher_running)
                self.assertTrue(runtime.status().overlay_running)
                self.assertEqual(
                    state.snapshot()["current"]["dance_external_id"],
                    "3114",
                )

                runtime.stop_overlay()
                self.assertEqual(len(calls), 1)
                self.assertTrue(runtime.status().watcher_running)
                self.assertFalse(runtime.status().overlay_running)
                self.assertIsNone(state.snapshot()["current"])
            finally:
                runtime.close()

    def test_run_watcher_resolves_cli_options_and_records_stats(self):
        calls: list[dict] = []
        stats = SimpleNamespace(
            session_dir=Path("capture") / "manual",
            raw_lines=1,
        )

        def fake_watch_vrc_logs(**kwargs):
            calls.append(kwargs)
            return stats

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config" / "dancing-log.local.json"
            config_path.parent.mkdir()
            config_path.write_text(json.dumps(DEFAULT_CONFIG), encoding="utf-8")
            runtime = LiveAppSessionRuntime(
                app_root=root,
                watch_vrc_logs_func=fake_watch_vrc_logs,
            )
            options = LiveWatcherRunOptions(
                log_dir="external-logs",
                output_dir="logs/one-shot",
                session_name="manual",
                app_db_path="data/live.sqlite3",
                from_start=True,
                include_raw=False,
                record_playback=True,
                overlay_port=9999,
                poll_seconds=0.1,
                stop_after_idle_seconds=0.2,
                archive_source_logs=False,
                source_log_dir="logs/source",
            )

            self.assertEqual(runtime.resolved_log_dir(options), root / "external-logs")
            self.assertIs(runtime.run_watcher(options), stats)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["log_dir"], root / "external-logs")
        self.assertEqual(calls[0]["output_dir"], root / "logs" / "one-shot")
        self.assertEqual(calls[0]["session_name"], "manual")
        self.assertEqual(calls[0]["app_db_path"], root / "data" / "live.sqlite3")
        self.assertTrue(calls[0]["from_start"])
        self.assertFalse(calls[0]["include_raw"])
        self.assertFalse(calls[0]["live_db"])
        self.assertTrue(calls[0]["record_playback"])
        self.assertEqual(calls[0]["overlay_port"], 9999)
        self.assertEqual(calls[0]["poll_seconds"], 0.1)
        self.assertEqual(calls[0]["stop_after_idle_seconds"], 0.2)
        self.assertIsNone(calls[0]["stop_event"])
        self.assertFalse(calls[0]["archive_source_logs"])
        self.assertEqual(calls[0]["source_log_dir"], root / "logs" / "source")
        self.assertIs(runtime.status().last_watcher_stats, stats)

    def test_run_watcher_rejects_existing_background_watcher_owner(self):
        calls: list[dict] = []
        watcher_started = threading.Event()
        active_watchers = 0
        max_active_watchers = 0
        active_lock = threading.Lock()

        def owned_watch_vrc_logs(**kwargs):
            nonlocal active_watchers, max_active_watchers
            calls.append(kwargs)
            with active_lock:
                active_watchers += 1
                max_active_watchers = max(max_active_watchers, active_watchers)
            watcher_started.set()
            try:
                stop_event = kwargs.get("stop_event")
                if stop_event is not None:
                    stop_event.wait(timeout=2.0)
                return {"call": len(calls)}
            finally:
                with active_lock:
                    active_watchers -= 1

        with tempfile.TemporaryDirectory() as tmp:
            runtime = LiveAppSessionRuntime(
                app_root=tmp,
                watch_vrc_logs_func=owned_watch_vrc_logs,
            )
            try:
                runtime.start_watcher()
                self.assertTrue(watcher_started.wait(timeout=1.0))

                with self.assertRaisesRegex(RuntimeError, "already running"):
                    runtime.run_watcher()

                self.assertEqual(len(calls), 1)
                self.assertEqual(max_active_watchers, 1)
                self.assertEqual(runtime.status().watcher_state, "running")
            finally:
                runtime.close()

    def test_background_start_rejects_existing_synchronous_watcher_owner(self):
        calls: list[dict] = []
        synchronous_started = threading.Event()
        release_synchronous = threading.Event()

        def owned_watch_vrc_logs(**kwargs):
            calls.append(kwargs)
            stop_event = kwargs.get("stop_event")
            if stop_event is None:
                synchronous_started.set()
                release_synchronous.wait(timeout=2.0)
            else:
                stop_event.wait(timeout=2.0)
            return {"call": len(calls)}

        with tempfile.TemporaryDirectory() as tmp:
            runtime = LiveAppSessionRuntime(
                app_root=tmp,
                watch_vrc_logs_func=owned_watch_vrc_logs,
            )
            run_errors: list[Exception] = []
            start_errors: list[Exception] = []
            run_thread = threading.Thread(
                target=lambda: _capture_error(run_errors, runtime.run_watcher)
            )
            start_thread = threading.Thread(
                target=lambda: _capture_error(start_errors, runtime.start_watcher)
            )
            try:
                run_thread.start()
                self.assertTrue(synchronous_started.wait(timeout=1.0))
                start_thread.start()
                start_thread.join(timeout=0.2)

                self.assertFalse(start_thread.is_alive())
                self.assertEqual(len(start_errors), 1)
                self.assertRegex(str(start_errors[0]), "already running")
                self.assertEqual(len(calls), 1)
                self.assertEqual(runtime.status().watcher_state, "running")
            finally:
                release_synchronous.set()
                run_thread.join(timeout=1.0)
                start_thread.join(timeout=1.0)
                runtime.close()

        self.assertEqual(run_errors, [])

    def test_run_watcher_errors_are_visible_in_status(self):
        def fake_watch_vrc_logs(**_kwargs):
            raise RuntimeError("watch failed")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config" / "dancing-log.local.json"
            config_path.parent.mkdir()
            config_path.write_text(json.dumps(DEFAULT_CONFIG), encoding="utf-8")
            runtime = LiveAppSessionRuntime(
                app_root=root,
                watch_vrc_logs_func=fake_watch_vrc_logs,
            )

            with self.assertRaises(RuntimeError):
                runtime.run_watcher()

        self.assertEqual(runtime.status().last_error, "watch failed")

    def test_close_waits_for_synchronous_watcher_before_marking_closed(self):
        watcher_started = threading.Event()
        release_watcher = threading.Event()
        stats = {"finished": True}

        def blocking_watch_vrc_logs(**_kwargs):
            watcher_started.set()
            release_watcher.wait(timeout=2.0)
            return stats

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config" / "dancing-log.local.json"
            config_path.parent.mkdir()
            config_path.write_text(json.dumps(DEFAULT_CONFIG), encoding="utf-8")
            runtime = LiveAppSessionRuntime(
                app_root=root,
                watch_vrc_logs_func=blocking_watch_vrc_logs,
            )
            run_errors: list[Exception] = []
            close_errors: list[Exception] = []
            run_thread = threading.Thread(
                target=lambda: _capture_error(run_errors, runtime.run_watcher)
            )
            close_thread = threading.Thread(
                target=lambda: _capture_error(close_errors, runtime.close)
            )
            try:
                run_thread.start()
                self.assertTrue(watcher_started.wait(timeout=1.0))
                close_thread.start()
                close_thread.join(timeout=0.1)

                self.assertTrue(close_thread.is_alive())
                self.assertEqual(runtime.status().session_state, "closing")

                release_watcher.set()
                run_thread.join(timeout=1.0)
                close_thread.join(timeout=1.0)

                self.assertFalse(run_thread.is_alive())
                self.assertFalse(close_thread.is_alive())
                self.assertEqual(run_errors, [])
                self.assertEqual(close_errors, [])
                self.assertEqual(runtime.status().session_state, "closed")
                self.assertIs(runtime.status().last_watcher_stats, stats)
            finally:
                release_watcher.set()
                run_thread.join(timeout=1.0)
                close_thread.join(timeout=1.0)


if __name__ == "__main__":
    unittest.main()
