import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dancing_log.app_paths import AppRuntimeConfig, DEFAULT_CONFIG
from dancing_log.data_operations import (
    DataOperationError,
    build_data_operation_request,
    build_data_operation_request_from_payload,
    operation_catalog_snapshot,
    run_data_operation,
)
from dancing_log.vrcx_importer import ImportStats


class DataOperationsTests(unittest.TestCase):
    def test_catalog_exposes_risk_defaults_command_and_localized_text(self):
        snapshot = operation_catalog_snapshot(command_prefix="dancing-log")
        operations = {operation["key"]: operation for operation in snapshot["operations"]}

        self.assertEqual(
            operations["sync-queued-self"]["command"],
            "dancing-log sync-queued-self --system wannadance",
        )
        self.assertEqual(operations["import-vrcx"]["risk"], "writes playback history")
        self.assertEqual(operations["import-vrcx"]["text"]["zh"]["title"], "导入 VRCX 历史")

        queued_params = {
            parameter["key"]: parameter
            for parameter in operations["sync-queued-self"]["parameters"]
        }
        self.assertEqual(queued_params["system"]["default"], "wannadance")
        self.assertEqual(queued_params["manifest_dir"]["default_config_key"], "queued_self_dir")

    def test_sync_wanna_returns_structured_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_track_dir = root / "wanna-cache" / "5038"
            cache_track_dir.mkdir(parents=True)
            (cache_track_dir / "metadata.json").write_text(
                '{"id":5038,"title":"Smoke Song","artist":"Smoke Artist"}',
                encoding="utf-8",
            )
            config = dict(DEFAULT_CONFIG)
            config["app_db"] = "data/smoke.sqlite3"
            config["wanna_cache_dir"] = "wanna-cache"
            runtime_config = AppRuntimeConfig.from_config(config, app_root=root)

            result = run_data_operation(
                "sync-wanna",
                config=runtime_config,
                offline=True,
                write_files=True,
            )

            self.assertEqual(result.operation_key, "sync-wanna")
            self.assertEqual(result.status, "completed")
            self.assertIn("WannaDance catalog sync complete", result.lines)
            self.assertIn("  cached songs: 1", result.lines)
            self.assertEqual(result.metrics["sync_wanna"]["cache_count"], 1)
            self.assertEqual(result.as_dict()["metrics"]["sync_wanna"]["cache_count"], 1)
            self.assertTrue((root / "data" / "smoke.sqlite3").exists())
            self.assertTrue((root / "data" / "wanna_songs.json").exists())
            self.assertTrue((root / "data" / "wanna_songs.csv").exists())

    def test_import_vrcx_requires_configured_source_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_config = AppRuntimeConfig.from_config(DEFAULT_CONFIG, app_root=root)

            with patch.dict("os.environ", {"APPDATA": str(root / "Roaming")}):
                with self.assertRaises(DataOperationError) as context:
                    run_data_operation("import-vrcx", config=runtime_config)

            self.assertIn("Missing VRCX database path", str(context.exception))

    def test_import_vrcx_uses_standard_vrcx_database_for_current_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            appdata = root / "Roaming"
            standard = appdata / "VRCX" / "VRCX.sqlite3"
            standard.parent.mkdir(parents=True)
            standard.write_bytes(b"")
            runtime_config = AppRuntimeConfig.from_config(DEFAULT_CONFIG, app_root=root)

            with (
                patch.dict("os.environ", {"APPDATA": str(appdata)}),
                patch(
                    "dancing_log.vrcx_importer.import_vrcx_database",
                    return_value=ImportStats(scanned=1, candidate_events=1),
                ) as importer,
            ):
                result = run_data_operation("import-vrcx", config=runtime_config, dry_run=True)

            importer.assert_called_once()
            self.assertEqual(importer.call_args.kwargs["vrcx_db_path"], standard)
            self.assertIsNone(runtime_config.config["vrcx_db_path"])
            self.assertEqual(result.status, "dry-run")

    def test_request_builder_coerces_payload_values_and_defaults(self):
        request = build_data_operation_request_from_payload(
            {
                "operation": "import-vrcx",
                "parameters": {
                    "vrcx_db": "history.sqlite3",
                    "blank_requester_source": "unknown",
                    "limit": "25",
                    "dry_run": "true",
                },
            }
        )

        self.assertEqual(request.operation_key, "import-vrcx")
        self.assertEqual(request.params["limit"], 25)
        self.assertTrue(request.params["dry_run"])
        self.assertEqual(request.params["blank_requester_source"], "unknown")

        queued_request = build_data_operation_request("sync-queued-self", {})
        self.assertEqual(queued_request.params["system"], "wannadance")

    def test_request_builder_rejects_unknown_or_invalid_parameters(self):
        with self.assertRaises(DataOperationError) as unknown_context:
            build_data_operation_request("sync-wanna", {"offline": True, "extra": "nope"})
        self.assertIn("Unknown parameter", str(unknown_context.exception))

        with self.assertRaises(DataOperationError) as invalid_context:
            build_data_operation_request("import-vrcx", {"blank_requester_source": "self"})
        self.assertIn("blank_requester_source must be one of", str(invalid_context.exception))

        with self.assertRaises(DataOperationError) as required_context:
            build_data_operation_request("rebuild-data", {"archive_existing": False})
        self.assertIn("--archive-existing is required", str(required_context.exception))


if __name__ == "__main__":
    unittest.main()
