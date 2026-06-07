import json
import tempfile
import unittest
from pathlib import Path

from dancing_log.app_paths import (
    DEFAULT_CONFIG,
    load_app_config,
    resolve_app_path,
    save_app_config,
)
from main import _resolve_recording_path


class AppPathTests(unittest.TestCase):
    def test_resolve_app_path_uses_app_root_for_relative_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(
                resolve_app_path("data/app.sqlite3", "fallback", app_root=root),
                root / "data" / "app.sqlite3",
            )

    def test_resolve_app_path_keeps_absolute_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            absolute = Path(tmp) / "custom.sqlite3"
            self.assertEqual(
                resolve_app_path(absolute, "data/app.sqlite3", app_root=Path("ignored")),
                absolute,
            )

    def test_load_app_config_migrates_legacy_data_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "data" / "local_config.json"
            legacy.parent.mkdir()
            legacy.write_text(
                json.dumps(
                    {
                        "vrcx_db_path": "path/to/vrcx-snapshot/VRCX.sqlite3",
                        "vrc_log_dir": "C:/Users/example/AppData/LocalLow/VRChat/VRChat",
                    }
                ),
                encoding="utf-8",
            )

            config = load_app_config(app_root=root, migrate_legacy=True)

            self.assertEqual(config["vrcx_db_path"], "path/to/vrcx-snapshot/VRCX.sqlite3")
            self.assertEqual(config["app_db"], DEFAULT_CONFIG["app_db"])
            migrated = root / "config" / "dancing-log.local.json"
            self.assertTrue(migrated.exists())
            migrated_config = json.loads(migrated.read_text(encoding="utf-8"))
            self.assertEqual(migrated_config["vrc_log_dir"], config["vrc_log_dir"])

    def test_save_app_config_filters_unknown_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = save_app_config(
                {
                    "app_db": "data/custom.sqlite3",
                    "unknown": "ignore me",
                },
                app_root=root,
            )

            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(raw["app_db"], "data/custom.sqlite3")
            self.assertNotIn("unknown", raw)

    def test_recording_path_prefers_existing_configured_recordings_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recording_dir = root / "recordings"
            recording_dir.mkdir()
            recording = recording_dir / "clip.mkv"
            recording.write_text("", encoding="utf-8")

            self.assertEqual(
                _resolve_recording_path("clip.mkv", "recordings", app_root=root),
                recording,
            )

    def test_recording_path_falls_back_to_app_root_when_configured_candidate_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            self.assertEqual(
                _resolve_recording_path("clip.mkv", "recordings", app_root=root),
                root / "clip.mkv",
            )


if __name__ == "__main__":
    unittest.main()
