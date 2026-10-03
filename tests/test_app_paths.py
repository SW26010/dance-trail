import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dance_trail.app_paths import (
    AppRuntimeConfig,
    CONFIG_FIELDS,
    DEFAULT_CONFIG,
    default_vrcx_db_path,
    detect_vrcx_db_path,
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

    def test_load_app_config_ignores_legacy_data_config(self):
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

            config = load_app_config(app_root=root)

            self.assertEqual(config["vrcx_db_path"], DEFAULT_CONFIG["vrcx_db_path"])
            self.assertEqual(config["app_db"], DEFAULT_CONFIG["app_db"])
            migrated = root / "config" / "dance-trail.local.json"
            self.assertFalse(migrated.exists())
            self.assertTrue(legacy.exists())

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

    def test_save_app_config_keeps_existing_file_when_atomic_replace_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config" / "dance-trail.local.json"
            config_path.parent.mkdir(parents=True)
            original = '{"app_db":"data/original.sqlite3"}\n'
            config_path.write_text(original, encoding="utf-8")

            with patch(
                "dance_trail.app_paths.os.replace",
                side_effect=OSError("replace failed"),
            ):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    save_app_config(
                        {"app_db": "data/replacement.sqlite3"},
                        path=config_path,
                    )

            self.assertEqual(config_path.read_text(encoding="utf-8"), original)
            self.assertEqual(list(config_path.parent.glob("*.tmp")), [])

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

    def test_dance_day_boundary_config_defaults_and_validates(self):
        runtime = AppRuntimeConfig.from_config({})

        self.assertEqual(DEFAULT_CONFIG["dance_day_boundary_time"], "00:00")
        self.assertEqual(runtime.dance_day_boundary.config_value, "00:00")

        config, errors = validate_supported_config(
            {"dance_day_boundary_time": "03:30"}
        )
        self.assertEqual(errors, {})
        self.assertEqual(config["dance_day_boundary_time"], "03:30")

        _, errors = validate_supported_config(
            {"dance_day_boundary_time": "06:01"}
        )
        self.assertEqual(
            errors["dance_day_boundary_time"],
            "time must be between 00:00 and 06:00",
        )

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

    def test_vrcx_db_path_auto_detection_uses_only_standard_appdata_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            appdata = root / "Roaming"
            standard = appdata / "VRCX" / "VRCX.sqlite3"
            runtime = AppRuntimeConfig.from_config(DEFAULT_CONFIG, app_root=root)

            with patch.dict("os.environ", {"APPDATA": str(appdata)}):
                self.assertEqual(default_vrcx_db_path(), standard)
                self.assertIsNone(detect_vrcx_db_path())
                self.assertIsNone(runtime.resolve_vrcx_db_path())

                standard.parent.mkdir(parents=True)
                standard.write_bytes(b"")

                self.assertEqual(detect_vrcx_db_path(), standard)
                self.assertEqual(runtime.resolve_vrcx_db_path(), standard)
                self.assertIsNone(runtime.config["vrcx_db_path"])

    def test_runtime_config_resolves_standard_app_root_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = AppRuntimeConfig.from_config(DEFAULT_CONFIG, app_root=root)

            self.assertEqual(
                runtime.paths.local_config_file,
                root / "config" / "dance-trail.local.json",
            )
            self.assertEqual(runtime.app_db_path, root / "data" / "dance_trail.sqlite3")
            self.assertEqual(runtime.queued_self_dir, root / "data" / "queued_self")
            self.assertEqual(runtime.capture_dir, root / "logs" / "captures")
            self.assertEqual(runtime.run_log_dir, root / "logs" / "runs")
            self.assertEqual(
                runtime.source_vrc_log_dir,
                root / "logs" / "source-vrc-logs",
            )
            self.assertEqual(
                runtime.recording_frames_dir,
                root / "analysis" / "recording_frames",
            )

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
