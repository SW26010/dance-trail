import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

import main as cli
from dancing_log.storage import (
    WANNA_SYSTEM_KEY,
    add_dance_event,
    connect_db,
    ensure_dance_track,
    upsert_live_playback_event,
)


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
                ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "11253",
                    {"title": "Mmchk", "artist": "NEXZ", "dancer": "Golfy"},
                )
                conn.commit()
            add_dance_event(
                system_key=WANNA_SYSTEM_KEY,
                external_id="11253",
                source="random",
                played_at="2026.06.07 18:12:08",
                event_source="manual",
                path=db_path,
            )

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


if __name__ == "__main__":
    unittest.main()
