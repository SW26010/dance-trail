import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

import main as cli


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


if __name__ == "__main__":
    unittest.main()
