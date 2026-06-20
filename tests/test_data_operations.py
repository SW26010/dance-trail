import tempfile
import unittest
from pathlib import Path

from dancing_log.app_paths import AppRuntimeConfig, DEFAULT_CONFIG
from dancing_log.data_operations import (
    DataOperationError,
    operation_catalog_snapshot,
    run_data_operation,
)


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

            result = run_data_operation("sync-wanna", config=runtime_config, offline=True)

            self.assertEqual(result.operation_key, "sync-wanna")
            self.assertEqual(result.status, "completed")
            self.assertIn("WannaDance catalog sync complete", result.lines)
            self.assertIn("  cached songs: 1", result.lines)
            self.assertEqual(result.metrics["sync_wanna"]["cache_count"], 1)
            self.assertEqual(result.as_dict()["metrics"]["sync_wanna"]["cache_count"], 1)

    def test_import_vrcx_requires_configured_source_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_config = AppRuntimeConfig.from_config(DEFAULT_CONFIG, app_root=tmp)

            with self.assertRaises(DataOperationError) as context:
                run_data_operation("import-vrcx", config=runtime_config)

            self.assertIn("Missing VRCX database path", str(context.exception))


if __name__ == "__main__":
    unittest.main()
