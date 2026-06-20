import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest

from dancing_log.app_paths import DEFAULT_CONFIG
from dancing_log.live_app_session import LiveAppSessionRuntime, LiveWatcherRunOptions


def wait_for_call_count(calls: list[dict], count: int) -> None:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if len(calls) >= count:
            return
        time.sleep(0.01)
    raise AssertionError(f"expected {count} watcher calls, got {len(calls)}")


class LiveAppSessionRuntimeTest(unittest.TestCase):
    def test_live_overlay_control_restarts_watcher_with_configured_overlay(self):
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

            runtime = LiveAppSessionRuntime(
                app_root=root,
                watch_vrc_logs_func=fake_watch_vrc_logs,
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
                self.assertTrue(calls[-1]["live_db"])
                self.assertIsNone(calls[-1]["overlay_port"])

                runtime.start_overlay()
                wait_for_call_count(calls, 2)
                self.assertTrue(runtime.status().watcher_running)
                self.assertTrue(runtime.status().overlay_running)
                self.assertEqual(calls[-1]["overlay_port"], 9911)

                runtime.stop_overlay()
                wait_for_call_count(calls, 3)
                self.assertTrue(runtime.status().watcher_running)
                self.assertFalse(runtime.status().overlay_running)
                self.assertIsNone(calls[-1]["overlay_port"])
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
                promote_live=True,
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
        self.assertTrue(calls[0]["live_db"])
        self.assertTrue(calls[0]["promote_live"])
        self.assertEqual(calls[0]["overlay_port"], 9999)
        self.assertEqual(calls[0]["poll_seconds"], 0.1)
        self.assertEqual(calls[0]["stop_after_idle_seconds"], 0.2)
        self.assertIsNone(calls[0]["stop_event"])
        self.assertFalse(calls[0]["archive_source_logs"])
        self.assertEqual(calls[0]["source_log_dir"], root / "logs" / "source")
        self.assertIs(runtime.status().last_watcher_stats, stats)

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


if __name__ == "__main__":
    unittest.main()
