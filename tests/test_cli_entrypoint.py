import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import main as cli
from dancing_log.storage import (
    WANNA_SYSTEM_KEY,
    connect_db,
    ensure_dance_track,
    upsert_live_playback_event,
)
from tests.playback_record_helpers import insert_playback_record


class CliEntrypointTests(unittest.TestCase):
    def test_sync_wanna_dispatches_as_builtin_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_track_dir = root / "wanna-cache" / "5038"
            cache_track_dir.mkdir(parents=True)
            (cache_track_dir / "metadata.json").write_text(
                '{"id":5038,"title":"Smoke Song","artist":"Smoke Artist"}',
                encoding="utf-8",
            )

            original_argv = sys.argv
            original_subprocess_run = cli.subprocess.run
            sys.argv = [
                "main.py",
                "sync-wanna",
                "--offline",
                "--app-db",
                str(root / "smoke.sqlite3"),
                "--cache-dir",
                str(root / "wanna-cache"),
            ]

            def fail_subprocess_run(*_args, **_kwargs):
                raise AssertionError("sync-wanna should not dispatch through scripts")

            cli.subprocess.run = fail_subprocess_run
            try:
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    cli.main()
            finally:
                cli.subprocess.run = original_subprocess_run
                sys.argv = original_argv

            self.assertIn("WannaDance catalog sync complete", output.getvalue())
            self.assertIn("cached songs: 1", output.getvalue())

    def test_day_dispatches_as_builtin_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "app.sqlite3"
            with connect_db(db_path) as conn:
                track_id = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "11253",
                    {"title": "Mmchk", "artist": "NEXZ", "dancer": "Golfy"},
                )
                insert_playback_record(
                    conn,
                    track_id=track_id,
                    played_at="2026.06.07 18:12:08",
                    source_type="random",
                )
                conn.commit()

            original_argv = sys.argv
            sys.argv = [
                "main.py",
                "day",
                "2026-06-07",
                "--app-db",
                str(db_path),
            ]
            try:
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    cli.main()
            finally:
                sys.argv = original_argv

            self.assertEqual(
                output.getvalue().strip(),
                "18:12:08 11253. Mmchk - NEXZ | Golfy",
            )

    def test_day_live_dispatches_live_db_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "app.sqlite3"
            with connect_db(db_path) as conn:
                track_id = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "4062",
                    {
                        "title": "Mood (Extreme)",
                        "artist": "24kGoldn & Iann Dior",
                        "dancer": "Just Dance 2022",
                    },
                )
                upsert_live_playback_event(
                    conn,
                    {
                        "event_key": "wannadance:4062#1",
                        "actual_play_at": "2026.06.07 18:09:09",
                        "observed_mid_play": False,
                        "dance_system_key": WANNA_SYSTEM_KEY,
                        "dance_external_id": "4062",
                        "video_name": "Mood (Extreme) - 24kGoldn & Iann Dior | Just Dance 2022",
                        "signal_count": 1,
                    },
                    session_id="session-one",
                )
                insert_playback_record(
                    conn,
                    track_id=track_id,
                    played_at="2026.06.07 18:09:09",
                    source_kind="live_watcher",
                    source_table="live_playback_events",
                    source_type="player",
                    video_name="Mood (Extreme) - 24kGoldn & Iann Dior | Just Dance 2022",
                )
                conn.commit()

            original_argv = sys.argv
            sys.argv = [
                "main.py",
                "day",
                "2026-06-07",
                "--live",
                "--app-db",
                str(db_path),
            ]
            try:
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    cli.main()
            finally:
                sys.argv = original_argv

            self.assertEqual(
                output.getvalue().strip(),
                "18:09:09 4062. Mood (Extreme) - 24kGoldn & Iann Dior | Just Dance 2022",
            )

    def test_watch_vrc_log_dispatches_through_live_app_session_runtime(self):
        calls = {}

        class FakeRuntime:
            def __init__(self, *, migrate_legacy_config=False):
                calls["migrate_legacy_config"] = migrate_legacy_config

            def resolved_log_dir(self, options):
                calls["resolved_options"] = options
                return Path(r"C:\VRChat\Logs")

            def run_watcher(self, options):
                calls["run_options"] = options
                return SimpleNamespace(
                    session_dir=Path("captures") / "manual",
                    raw_lines=7,
                    candidate_lines=3,
                    parsed_events=2,
                    playback_events=1,
                    live_db_updates=4,
                    live_promotions=1,
                    overlay_url="http://127.0.0.1:9876/overlay",
                    source_log_dir="source-logs",
                    source_log_bytes=123,
                    delay_metrics={},
                )

        original_argv = sys.argv
        sys.argv = [
            "main.py",
            "watch-vrc-log",
            "--log-dir",
            "logs/input",
            "--output-dir",
            "logs/output",
            "--session-name",
            "manual",
            "--from-start",
            "--no-raw",
            "--source-log-dir",
            "logs/source",
            "--app-db",
            "data/live.sqlite3",
            "--live-db",
            "--promote-live",
            "--overlay-port",
            "9876",
            "--poll-seconds",
            "0.1",
            "--stop-after-idle-seconds",
            "0.2",
            "--no-source-archive",
        ]
        try:
            output = io.StringIO()
            with (
                patch("dancing_log.live_app_session.LiveAppSessionRuntime", FakeRuntime),
                contextlib.redirect_stdout(output),
            ):
                cli.main()
        finally:
            sys.argv = original_argv

        options = calls["run_options"]
        self.assertTrue(calls["migrate_legacy_config"])
        self.assertIs(calls["resolved_options"], options)
        self.assertEqual(options.log_dir, "logs/input")
        self.assertEqual(options.output_dir, "logs/output")
        self.assertEqual(options.session_name, "manual")
        self.assertEqual(options.source_log_dir, "logs/source")
        self.assertEqual(options.app_db_path, "data/live.sqlite3")
        self.assertTrue(options.from_start)
        self.assertFalse(options.include_raw)
        self.assertTrue(options.live_db)
        self.assertTrue(options.promote_live)
        self.assertEqual(options.overlay_port, 9876)
        self.assertEqual(options.poll_seconds, 0.1)
        self.assertEqual(options.stop_after_idle_seconds, 0.2)
        self.assertFalse(options.archive_source_logs)
        self.assertIn("Watching VRChat logs: C:\\VRChat\\Logs", output.getvalue())
        self.assertIn("overlay URL: http://127.0.0.1:9876/overlay", output.getvalue())

    def test_frozen_entrypoint_excludes_research_commands(self):
        original_argv = sys.argv
        had_frozen = hasattr(sys, "frozen")
        original_frozen = getattr(sys, "frozen", None)
        sys.argv = ["DancingLog.exe", "sample-frames"]
        sys.frozen = True
        try:
            output = io.StringIO()
            with self.assertRaises(SystemExit) as exit_context:
                with contextlib.redirect_stdout(output):
                    cli.main()
        finally:
            sys.argv = original_argv
            if had_frozen:
                sys.frozen = original_frozen
            else:
                delattr(sys, "frozen")

        self.assertEqual(exit_context.exception.code, 2)
        self.assertIn("Usage:", output.getvalue())
        self.assertNotIn("sample-frames", output.getvalue())
        self.assertNotIn("Development/research", output.getvalue())

    def test_frozen_gui_entrypoint_defaults_to_desktop_tray(self):
        original_argv = sys.argv
        original_executable = sys.executable
        had_frozen = hasattr(sys, "frozen")
        original_frozen = getattr(sys, "frozen", None)
        sys.argv = ["DancingLog.exe"]
        sys.executable = r"C:\portable\DancingLog.exe"
        sys.frozen = True
        try:
            with patch("main.run_desktop_tray_entry") as run_tray:
                cli.main()
        finally:
            sys.argv = original_argv
            sys.executable = original_executable
            if had_frozen:
                sys.frozen = original_frozen
            else:
                delattr(sys, "frozen")

        run_tray.assert_called_once_with()

    def test_frozen_cli_entrypoint_without_command_keeps_usage_help(self):
        original_argv = sys.argv
        original_executable = sys.executable
        had_frozen = hasattr(sys, "frozen")
        original_frozen = getattr(sys, "frozen", None)
        sys.argv = ["DancingLogCli.exe"]
        sys.executable = r"C:\portable\DancingLogCli.exe"
        sys.frozen = True
        try:
            output = io.StringIO()
            with self.assertRaises(SystemExit) as exit_context:
                with contextlib.redirect_stdout(output):
                    cli.main()
        finally:
            sys.argv = original_argv
            sys.executable = original_executable
            if had_frozen:
                sys.frozen = original_frozen
            else:
                delattr(sys, "frozen")

        self.assertEqual(exit_context.exception.code, 0)
        self.assertIn("Usage:", output.getvalue())
        self.assertIn("DancingLogCli.exe", output.getvalue())


if __name__ == "__main__":
    unittest.main()
