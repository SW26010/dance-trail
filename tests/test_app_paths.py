import json
import tempfile
import unittest
from pathlib import Path

from dancing_log.app_paths import (
    AppRuntimeConfig,
    CONFIG_FIELDS,
    DEFAULT_CONFIG,
    load_app_config,
    resolve_app_path,
    save_app_config,
    validate_supported_config,
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

    def test_save_app_config_preserves_unknown_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = save_app_config(
                {
                    "app_db": "data/custom.sqlite3",
                    "unknown": "keep me",
                },
                app_root=root,
            )

            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(raw["app_db"], "data/custom.sqlite3")
            self.assertEqual(raw["unknown"], "keep me")

    def test_overlay_auto_start_implies_watcher_auto_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = save_app_config(
                {
                    "auto_start_overlay": True,
                },
                app_root=root,
            )

            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(raw["auto_start_overlay"])
            self.assertTrue(raw["auto_start_watcher"])

    def test_config_fields_describe_default_config_keys(self):
        self.assertEqual([field["key"] for field in CONFIG_FIELDS], list(DEFAULT_CONFIG))

    def test_validate_supported_config_preserves_overlay_watcher_dependency(self):
        config, errors = validate_supported_config(
            {
                "auto_start_watcher": False,
                "auto_start_overlay": True,
                "overlay_port": 8765,
            }
        )

        self.assertEqual(errors, {})
        self.assertTrue(config["auto_start_overlay"])
        self.assertTrue(config["auto_start_watcher"])

    def test_runtime_config_resolves_internal_and_external_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = AppRuntimeConfig.from_config(
                {
                    "app_db": "db/app.sqlite3",
                    "wanna_cache_dir": "cache/wanna",
                    "vrcx_db_path": "",
                    "overlay_port": 9911,
                },
                app_root=root,
            )

            self.assertEqual(runtime.app_db_path, root / "db" / "app.sqlite3")
            self.assertEqual(runtime.wanna_cache_dir, root / "cache" / "wanna")
            self.assertIsNone(runtime.vrcx_db_path)
            self.assertEqual(runtime.overlay_port, 9911)
            self.assertEqual(runtime.supported_values()["app_db"], "db/app.sqlite3")

    def test_runtime_watcher_config_preserves_defaults_and_empty_override_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = AppRuntimeConfig.from_config(
                {
                    "app_db": "data/custom.sqlite3",
                    "capture_dir": "logs/custom-captures",
                    "source_vrc_log_dir": "logs/custom-source",
                    "overlay_port": 9911,
                },
                app_root=root,
            )

            watcher = runtime.watcher_config(
                default_log_dir=root / "LocalLow" / "VRChat",
                output_dir="",
            )

            self.assertEqual(watcher.log_dir, root / "LocalLow" / "VRChat")
            self.assertEqual(watcher.output_dir, root / "logs" / "custom-captures")
            self.assertEqual(watcher.app_db_path, root / "data" / "custom.sqlite3")
            self.assertEqual(watcher.source_log_dir, root / "logs" / "custom-source")
            self.assertEqual(watcher.overlay_port, 9911)

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
