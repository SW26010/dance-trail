import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from dancing_log.app_paths import DEFAULT_CONFIG
from dancing_log.data_operations import DataOperationResult, operation_catalog_snapshot
from dancing_log.playback_projection import (
    EFFECTIVE_PLAYBACK_ACCEPTED,
    EFFECTIVE_PLAYBACK_EXCLUDED,
    EFFECTIVE_PLAYBACK_NEEDS_ATTENTION,
    set_manual_playback_decision,
)
from dancing_log.webui_endpoints import (
    load_catalog_snapshot,
    load_insights_snapshot,
    load_operations_snapshot,
    load_summary_snapshot,
    load_timeline_snapshot,
    update_playback_review_from_payload,
)
from dancing_log.storage import (
    WANNA_SYSTEM_KEY,
    connect_db,
    ensure_dance_track,
    upsert_live_playback_event,
)
from dancing_log.webui_server import WebUiRuntime, WebUiServer
from dancing_log.webui_settings import load_config_snapshot
from dancing_log.windows_picker import (
    FOS_FILEMUSTEXIST,
    FOS_FORCEFILESYSTEM,
    FOS_PATHMUSTEXIST,
    FOS_PICKFOLDERS,
    _file_dialog_options,
    _run_windows_picker,
)
from tests.playback_record_helpers import insert_playback_record


def wait_for_call_count(calls: list[dict], count: int) -> None:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if len(calls) >= count:
            return
        time.sleep(0.01)
    raise AssertionError(f"expected {count} watcher calls, got {len(calls)}")


class WebUiServerTest(unittest.TestCase):
    def _csrf_token(self, server: WebUiServer) -> str:
        with urlopen(server.url, timeout=2) as response:
            html = response.read().decode("utf-8")
        marker = 'const CSRF_TOKEN = "'
        self.assertIn(marker, html)
        token = html.split(marker, 1)[1].split('"', 1)[0]
        self.assertTrue(token)
        self.assertNotEqual(token, "__DANCING_LOG_CSRF_TOKEN__")
        return token

    def _json_request(
        self,
        server: WebUiServer,
        path: str,
        payload: dict,
        *,
        token: str | None = None,
        origin: str | None = None,
        content_type: str = "application/json",
        host: str | None = None,
    ) -> Request:
        headers = {"Content-Type": content_type}
        if token is not None:
            headers["X-Dancing-Log-CSRF"] = token
        if origin is not None:
            headers["Origin"] = origin
        if host is not None:
            headers["Host"] = host
        return Request(
            f"{server.url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

    def _http_error_json(self, request: Request, expected_code: int) -> dict:
        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=2)
        error = context.exception
        try:
            body = error.read().decode("utf-8")
        finally:
            error.close()
        self.assertEqual(error.code, expected_code)
        return json.loads(body) if body else {}

    def test_webui_serves_main_page_and_config_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = WebUiServer(port=0, app_root=tmp)
            server.start()
            try:
                with urlopen(server.url, timeout=2) as response:
                    html = response.read().decode("utf-8")
                self.assertIn("dancing-log", html)
                self.assertIn("Settings", html)
                self.assertIn("dancing-log.language", html)
                self.assertIn("中文", html)
                self.assertIn("本地 Web UI", html)
                self.assertIn("/api/playback-review", html)
                self.assertIn("data-playback-action", html)
                self.assertIn("Restore default", html)
                self.assertNotIn("timeline-source", html)
                self.assertIn("prefers-color-scheme: dark", html)
                self.assertIn("color-scheme: dark", html)
                self.assertNotIn("https://", html)
                self.assertIn('const CSRF_TOKEN = "', html)
                self.assertIn("AUTOMATIC_SOURCE_PATH_KEYS", html)
                self.assertIn("data-path-custom", html)
                self.assertNotIn("data-save-settings", html)
                self.assertIn("isFieldDirty", html)
                self.assertNotIn("autoSaveConfigKey", html)
                self.assertNotIn("__DANCING_LOG_CSRF_TOKEN__", html)

                with urlopen(f"{server.url}api/config", timeout=2) as response:
                    snapshot = json.loads(response.read().decode("utf-8"))
                self.assertEqual(snapshot["config"]["app_db"], "data/dancing_log.sqlite3")
                self.assertIn("overlay_port", snapshot["config"])
            finally:
                server.stop()

    def test_webui_config_save_preserves_unknown_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config" / "dancing-log.local.json"
            config_path.parent.mkdir()
            config_path.write_text(
                json.dumps(
                    {
                        "app_db": "data/old.sqlite3",
                        "vrcx_db_path": "D:/old/VRCX.sqlite3",
                        "vrc_log_dir": "C:/old/VRChat",
                        "custom_future_key": {"keep": True},
                    }
                ),
                encoding="utf-8",
            )
            server = WebUiServer(port=0, app_root=root)
            server.start()
            try:
                token = self._csrf_token(server)
                payload = {
                    "config": {
                        "app_db": "data/new.sqlite3",
                        "queued_self_dir": "data/queued_self",
                        "capture_dir": "logs/captures",
                        "run_log_dir": "logs/runs",
                        "source_vrc_log_dir": "logs/source-vrc-logs",
                        "recording_frames_dir": "analysis/recording_frames",
                        "self_user_id": "",
                        "vrcx_db_path": "",
                        "vrc_log_dir": "",
                        "wanna_cache_dir": "",
                        "recordings_dir": "",
                        "auto_start_watcher": False,
                        "auto_start_overlay": True,
                        "overlay_port": 8765,
                    }
                }
                request = self._json_request(
                    server,
                    "api/config",
                    payload,
                    token=token,
                    origin=server.url.rstrip("/"),
                )
                with urlopen(request, timeout=2) as response:
                    result = json.loads(response.read().decode("utf-8"))

                saved = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertTrue(result["saved"])
                self.assertEqual(saved["app_db"], "data/new.sqlite3")
                self.assertEqual(saved["custom_future_key"], {"keep": True})
                self.assertTrue(saved["auto_start_overlay"])
                self.assertTrue(saved["auto_start_watcher"])
                self.assertIsNone(saved["vrcx_db_path"])
                self.assertIsNone(saved["vrc_log_dir"])
                self.assertIsNone(result["snapshot"]["config"]["vrcx_db_path"])
                self.assertIsNone(result["snapshot"]["config"]["vrc_log_dir"])
            finally:
                server.stop()

    def test_webui_config_save_rejects_invalid_port_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config" / "dancing-log.local.json"
            config_path.parent.mkdir()
            config_path.write_text(
                json.dumps({"app_db": "data/original.sqlite3"}),
                encoding="utf-8",
            )
            server = WebUiServer(port=0, app_root=root)
            server.start()
            try:
                token = self._csrf_token(server)
                payload = {
                    "config": {
                        "app_db": "data/new.sqlite3",
                        "queued_self_dir": "data/queued_self",
                        "capture_dir": "logs/captures",
                        "run_log_dir": "logs/runs",
                        "source_vrc_log_dir": "logs/source-vrc-logs",
                        "recording_frames_dir": "analysis/recording_frames",
                        "auto_start_watcher": False,
                        "auto_start_overlay": False,
                        "overlay_port": 70000,
                    }
                }
                request = self._json_request(
                    server,
                    "api/config",
                    payload,
                    token=token,
                    origin=server.url.rstrip("/"),
                )
                body = self._http_error_json(request, 400)
                saved = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertIn("overlay_port", body["errors"])
                self.assertEqual(saved["app_db"], "data/original.sqlite3")
            finally:
                server.stop()

    def test_webui_config_save_rejects_cross_origin_text_and_missing_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config" / "dancing-log.local.json"
            config_path.parent.mkdir()
            config_path.write_text(
                json.dumps({"app_db": "data/original.sqlite3"}),
                encoding="utf-8",
            )
            server = WebUiServer(port=0, app_root=root)
            server.start()
            try:
                token = self._csrf_token(server)
                payload = {"config": {"app_db": "data/csrf.sqlite3"}}

                text_request = self._json_request(
                    server,
                    "api/config",
                    payload,
                    token=token,
                    origin="https://example.invalid",
                    content_type="text/plain",
                )
                self._http_error_json(text_request, 415)

                origin_request = self._json_request(
                    server,
                    "api/config",
                    payload,
                    token=token,
                    origin="https://example.invalid",
                )
                self._http_error_json(origin_request, 403)

                missing_token_request = self._json_request(
                    server,
                    "api/config",
                    payload,
                    origin=server.url.rstrip("/"),
                )
                self._http_error_json(missing_token_request, 403)

                host_request = self._json_request(
                    server,
                    "api/config",
                    payload,
                    token=token,
                    origin=server.url.rstrip("/"),
                    host=f"example.invalid:{server.port}",
                )
                self._http_error_json(host_request, 403)

                saved = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(saved["app_db"], "data/original.sqlite3")
            finally:
                server.stop()

    def test_webui_live_controls_use_session_runtime(self):
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

            server = WebUiServer(
                port=0,
                app_root=root,
                watch_vrc_logs_func=fake_watch_vrc_logs,
            )
            server.start()
            try:
                token = self._csrf_token(server)
                with urlopen(f"{server.url}api/summary", timeout=2) as response:
                    summary = json.loads(response.read().decode("utf-8"))
                self.assertFalse(summary["session"]["watcher_running"])
                self.assertFalse(summary["session"]["overlay_running"])

                watcher_start = self._json_request(
                    server,
                    "api/live/watcher",
                    {"action": "start"},
                    token=token,
                    origin=server.url.rstrip("/"),
                )
                with urlopen(watcher_start, timeout=2) as response:
                    result = json.loads(response.read().decode("utf-8"))
                wait_for_call_count(calls, 1)
                self.assertTrue(result["session"]["watcher_running"])
                self.assertFalse(result["session"]["overlay_running"])
                self.assertFalse(calls[-1]["live_db"])
                self.assertTrue(calls[-1]["record_playback"])
                self.assertIsNone(calls[-1]["overlay_port"])

                overlay_start = self._json_request(
                    server,
                    "api/live/overlay",
                    {"action": "start"},
                    token=token,
                    origin=server.url.rstrip("/"),
                )
                with urlopen(overlay_start, timeout=2) as response:
                    result = json.loads(response.read().decode("utf-8"))
                wait_for_call_count(calls, 2)
                self.assertTrue(result["session"]["watcher_running"])
                self.assertTrue(result["session"]["overlay_running"])
                self.assertEqual(calls[-1]["overlay_port"], 9911)
                self.assertTrue(calls[-1]["record_playback"])

                overlay_stop = self._json_request(
                    server,
                    "api/live/overlay",
                    {"action": "stop"},
                    token=token,
                    origin=server.url.rstrip("/"),
                )
                with urlopen(overlay_stop, timeout=2) as response:
                    result = json.loads(response.read().decode("utf-8"))
                wait_for_call_count(calls, 3)
                self.assertTrue(result["session"]["watcher_running"])
                self.assertFalse(result["session"]["overlay_running"])
                self.assertIsNone(calls[-1]["overlay_port"])

                watcher_stop = self._json_request(
                    server,
                    "api/live/watcher",
                    {"action": "stop"},
                    token=token,
                    origin=server.url.rstrip("/"),
                )
                with urlopen(watcher_stop, timeout=2) as response:
                    result = json.loads(response.read().decode("utf-8"))
                self.assertFalse(result["session"]["watcher_running"])
                self.assertFalse(result["session"]["overlay_running"])

                with urlopen(f"{server.url}api/summary", timeout=2) as response:
                    summary = json.loads(response.read().decode("utf-8"))
                self.assertEqual(
                    summary["session"]["last_watcher_stats"],
                    {"overlay_port": None},
                )
            finally:
                server.stop()

    def test_webui_live_controls_reject_unknown_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = WebUiServer(port=0, app_root=tmp, watch_vrc_logs_func=lambda **_kwargs: None)
            server.start()
            try:
                token = self._csrf_token(server)
                request = self._json_request(
                    server,
                    "api/live/watcher",
                    {"action": "toggle"},
                    token=token,
                    origin=server.url.rstrip("/"),
                )
                body = self._http_error_json(request, 400)
                self.assertEqual(body["error"], "action must be start or stop")
            finally:
                server.stop()

    def test_webui_playback_review_endpoint_updates_timeline_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "data" / "dancing_log.sqlite3"
            with connect_db(db_path) as conn:
                track_id = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "700",
                    {"title": "Review Song", "artist": "Review Artist"},
                )
                playback_record_id = insert_playback_record(
                    conn,
                    track_id=track_id,
                    played_at="2026-06-18T20:40:00+08:00",
                    playback_status=EFFECTIVE_PLAYBACK_NEEDS_ATTENTION,
                    counts_in_history=0,
                )
                conn.commit()

            server = WebUiServer(port=0, app_root=root)
            server.start()
            try:
                token = self._csrf_token(server)
                accept_request = self._json_request(
                    server,
                    "api/playback-review",
                    {"playback_record_id": playback_record_id, "action": "accept"},
                    token=token,
                    origin=server.url.rstrip("/"),
                )
                with urlopen(accept_request, timeout=2) as response:
                    accept_result = json.loads(response.read().decode("utf-8"))
                self.assertEqual(
                    accept_result["review"],
                    {
                        "playback_record_id": playback_record_id,
                        "default_playback_status": "needs_attention",
                        "manual_decision_status": "accepted",
                        "effective_playback_status": "accepted",
                    },
                )

                with urlopen(f"{server.url}api/timeline?date=2026-06-18", timeout=2) as response:
                    timeline = json.loads(response.read().decode("utf-8"))
                row = timeline["records"][0]
                self.assertEqual(row["id"], playback_record_id)
                self.assertEqual(row["review_status"], "accepted")
                self.assertEqual(row["default_playback_status"], "needs_attention")
                self.assertEqual(row["manual_decision_status"], "accepted")
                self.assertTrue(row["has_manual_decision"])

                restore_request = self._json_request(
                    server,
                    "api/playback-review",
                    {"playback_record_id": playback_record_id, "action": "restore_default"},
                    token=token,
                    origin=server.url.rstrip("/"),
                )
                with urlopen(restore_request, timeout=2) as response:
                    restore_result = json.loads(response.read().decode("utf-8"))
                self.assertEqual(restore_result["review"]["manual_decision_status"], None)
                self.assertEqual(
                    restore_result["review"]["effective_playback_status"],
                    "needs_attention",
                )

                with urlopen(f"{server.url}api/timeline?date=2026-06-18", timeout=2) as response:
                    restored_timeline = json.loads(response.read().decode("utf-8"))
                restored_row = restored_timeline["records"][0]
                self.assertEqual(restored_row["review_status"], "needs_attention")
                self.assertIsNone(restored_row["manual_decision_status"])
                self.assertFalse(restored_row["has_manual_decision"])
            finally:
                server.stop()

    def test_webui_playback_review_endpoint_does_not_create_missing_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "data" / "dancing_log.sqlite3"
            body, status = update_playback_review_from_payload(
                WebUiRuntime.from_root(root),
                {"playback_record_id": 1, "action": "accept"},
            )

            self.assertEqual(status, 400)
            self.assertEqual(body["error"], "database not found")
            self.assertFalse(db_path.exists())

    def test_webui_resolve_path_uses_draft_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = WebUiServer(port=0, app_root=root)
            server.start()
            try:
                token = self._csrf_token(server)
                request = self._json_request(
                    server,
                    "api/resolve-path",
                    {"field": "app_db", "current_value": "data/new.sqlite3"},
                    token=token,
                    origin=server.url.rstrip("/"),
                )
                with urlopen(request, timeout=2) as response:
                    result = json.loads(response.read().decode("utf-8"))

                self.assertEqual(result["field"], "app_db")
                self.assertEqual(result["path"]["resolved"], str(root / "data" / "new.sqlite3"))
                self.assertFalse(result["path"]["exists"])

                null_request = self._json_request(
                    server,
                    "api/resolve-path",
                    {"field": "vrcx_db_path", "current_value": ""},
                    token=token,
                    origin=server.url.rstrip("/"),
                )
                with urlopen(null_request, timeout=2) as response:
                    null_result = json.loads(response.read().decode("utf-8"))
                self.assertIsNone(null_result["path"]["resolved"])
            finally:
                server.stop()

    def test_webui_read_snapshots_do_not_initialize_empty_sqlite_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "data" / "dancing_log.sqlite3"
            db_path.parent.mkdir()
            db_path.write_bytes(b"")
            runtime = WebUiRuntime.from_root(root)

            catalog = load_catalog_snapshot(runtime, {})
            insights = load_insights_snapshot(runtime)
            timeline = load_timeline_snapshot(runtime, {"date": ["2026-06-18"]})

            self.assertTrue(catalog["database_exists"])
            self.assertTrue(insights["database_exists"])
            self.assertTrue(timeline["database_exists"])
            self.assertEqual(db_path.stat().st_size, 0)

    def test_webui_read_snapshots_use_playback_records_not_legacy_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "data" / "dancing_log.sqlite3"
            with connect_db(db_path) as conn:
                legacy_track = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "100",
                    {"title": "Legacy Song", "artist": "Legacy Artist"},
                )
                evidence_track = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "200",
                    {"title": "Evidence Song", "artist": "Evidence Artist"},
                )
                attention_track = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "300",
                    {"title": "Attention Song", "artist": "Attention Artist"},
                )
                excluded_track = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "500",
                    {"title": "False Positive", "artist": "Excluded Artist"},
                )
                manual_accepted_track = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "600",
                    {"title": "Manual Keep", "artist": "Manual Artist"},
                )
                live_track = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "400",
                    {"title": "Live Evidence", "artist": "Live Artist"},
                )
                evidence_record = insert_playback_record(
                    conn,
                    track_id=evidence_track,
                    played_at="2026-06-18T20:00:00+08:00",
                    source_type="self",
                )
                attention_record = insert_playback_record(
                    conn,
                    track_id=attention_track,
                    played_at="2026-06-18T20:10:00+08:00",
                    source_type="player",
                    playback_status="needs_attention",
                    counts_in_history=0,
                    status_reason="interrupted",
                    catalog_attention=1,
                )
                excluded_record = insert_playback_record(
                    conn,
                    track_id=excluded_track,
                    played_at="2026-06-18T20:15:00+08:00",
                    source_type="self",
                    catalog_attention=1,
                )
                manual_accepted_record = insert_playback_record(
                    conn,
                    track_id=manual_accepted_track,
                    played_at="2026-06-18T20:18:00+08:00",
                    source_type="player",
                    playback_status="needs_attention",
                    counts_in_history=0,
                    status_reason="low_confidence",
                )
                live_record = insert_playback_record(
                    conn,
                    track_id=live_track,
                    played_at="2026-06-18T20:20:00+08:00",
                    source_kind="live_watcher",
                    source_table="live_playback_events",
                    source_type="player",
                )
                set_manual_playback_decision(
                    conn,
                    excluded_record,
                    EFFECTIVE_PLAYBACK_EXCLUDED,
                    reason="false_positive",
                )
                set_manual_playback_decision(
                    conn,
                    manual_accepted_record,
                    EFFECTIVE_PLAYBACK_ACCEPTED,
                    reason="confirmed",
                )
                upsert_live_playback_event(
                    conn,
                    {
                        "event_key": "wannadance:999#1",
                        "actual_play_at": "2026-06-18T20:30:00+08:00",
                        "observed_mid_play": False,
                        "dance_system_key": WANNA_SYSTEM_KEY,
                        "dance_external_id": "999",
                        "video_name": "Legacy Live Row",
                        "signal_count": 1,
                    },
                    session_id="session-one",
                )
                conn.execute(
                    """
                    INSERT INTO dance_events (
                        played_at,
                        dance_track_id,
                        source,
                        confidence,
                        event_source,
                        event_key
                    )
                    VALUES (?, ?, 'random', 0.7, 'legacy-test', 'legacy-webui-event')
                    """,
                    ("2026-06-18T19:00:00+08:00", legacy_track),
                )
                conn.commit()

            runtime = WebUiRuntime.from_root(root)

            summary = load_summary_snapshot(runtime)
            timeline = load_timeline_snapshot(runtime, {"date": ["2026-06-18"]})
            live_timeline = load_timeline_snapshot(
                runtime,
                {"date": ["2026-06-18"], "source": ["live"]},
            )
            insights = load_insights_snapshot(runtime)

            self.assertEqual(timeline["source"], "all")
            self.assertEqual(live_timeline["source"], "live")
            self.assertEqual(summary["counts"]["playback_records"], 5)
            self.assertEqual(summary["counts"]["accepted_playback_records"], 3)
            self.assertEqual(summary["counts"]["needs_attention_playback_records"], 1)
            self.assertEqual(summary["counts"]["legacy_dance_events"], 1)
            self.assertEqual(summary["counts"]["legacy_live_playback_events"], 1)
            self.assertEqual(
                {
                    record_id: next(
                        record["review_status"]
                        for record in timeline["records"]
                        if record["id"] == record_id
                    )
                    for record_id in (
                        evidence_record,
                        attention_record,
                        excluded_record,
                        manual_accepted_record,
                        live_record,
                    )
                },
                {
                    evidence_record: "accepted",
                    attention_record: "needs_attention",
                    excluded_record: "excluded",
                    manual_accepted_record: "accepted",
                    live_record: "accepted",
                },
            )
            self.assertEqual(
                {
                    record_id: next(
                        (
                            record["default_playback_status"],
                            record["manual_decision_status"],
                            record["effective_playback_status"],
                            record["has_manual_decision"],
                        )
                        for record in timeline["records"]
                        if record["id"] == record_id
                    )
                    for record_id in (
                        evidence_record,
                        attention_record,
                        excluded_record,
                        manual_accepted_record,
                    )
                },
                {
                    evidence_record: ("accepted", None, "accepted", False),
                    attention_record: ("needs_attention", None, "needs_attention", False),
                    excluded_record: ("accepted", "excluded", "excluded", True),
                    manual_accepted_record: (
                        "needs_attention",
                        "accepted",
                        "accepted",
                        True,
                    ),
                },
            )
            self.assertEqual(
                [record["display"] for record in timeline["records"]],
                [
                    "200. Evidence Song - Evidence Artist",
                    "300. Attention Song - Attention Artist",
                    "500. False Positive - Excluded Artist",
                    "600. Manual Keep - Manual Artist",
                    "400. Live Evidence - Live Artist",
                ],
            )
            self.assertEqual(
                [record["display"] for record in live_timeline["records"]],
                ["400. Live Evidence - Live Artist"],
            )
            self.assertEqual(
                {row["source"]: row["count"] for row in insights["source_distribution"]},
                {"player": 2, "self": 1},
            )
            self.assertEqual(
                {row["external_id"] for row in insights["top_tracks"]},
                {"200", "400", "600"},
            )
            self.assertEqual(
                insights["attention_counts"],
                {"needs_attention": 1, "catalog_attention": 1},
            )
            recommendation_counts = {
                row["external_id"]: row["_dance_count"]
                for row in insights["recommendations"]
            }
            self.assertEqual(recommendation_counts["100"], 0)
            self.assertEqual(recommendation_counts["200"], 1)
            self.assertEqual(recommendation_counts["300"], 0)
            self.assertEqual(recommendation_counts["400"], 1)
            self.assertEqual(recommendation_counts["500"], 0)
            self.assertEqual(recommendation_counts["600"], 1)

    def test_webui_config_snapshot_does_not_migrate_legacy_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy_path = root / "data" / "local_config.json"
            new_path = root / "config" / "dancing-log.local.json"
            legacy_path.parent.mkdir()
            legacy_path.write_text(json.dumps({"app_db": "data/legacy.sqlite3"}), encoding="utf-8")

            snapshot = load_config_snapshot(WebUiRuntime.from_root(root))

            self.assertEqual(snapshot["config"]["app_db"], "data/legacy.sqlite3")
            self.assertFalse(new_path.exists())

    def test_webui_config_snapshot_previews_standard_vrcx_database_without_saving(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            appdata = root / "Roaming"
            standard = appdata / "VRCX" / "VRCX.sqlite3"
            standard.parent.mkdir(parents=True)
            standard.write_bytes(b"")

            with patch.dict("os.environ", {"APPDATA": str(appdata)}):
                snapshot = load_config_snapshot(WebUiRuntime.from_root(root))

            candidates = {
                candidate["field"]: candidate
                for candidate in snapshot["detected_sources"]
            }
            self.assertEqual(candidates["vrcx_db_path"]["value"], str(standard))
            self.assertTrue(candidates["vrcx_db_path"]["exists"])
            self.assertIsNone(snapshot["config"]["vrcx_db_path"])
            self.assertFalse((root / "config" / "dancing-log.local.json").exists())

    def test_webui_operations_snapshot_uses_shared_catalog(self):
        snapshot = load_operations_snapshot()

        self.assertEqual(snapshot, operation_catalog_snapshot())
        operations = {operation["key"]: operation for operation in snapshot["operations"]}
        self.assertEqual(operations["rebuild-data"]["parameters"][0]["key"], "archive_existing")
        self.assertEqual(operations["sync-wanna"]["text"]["zh"]["risk"], "更新目录记录")

    def test_webui_runs_operation_through_shared_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = WebUiServer(port=0, app_root=root)
            server.start()
            try:
                token = self._csrf_token(server)
                fake_result = DataOperationResult(
                    operation_key="sync-wanna",
                    title="Sync WannaDance catalog",
                    status="completed",
                    summary="done",
                    lines=("done",),
                    metrics={"count": 1},
                )
                with patch(
                    "dancing_log.webui_endpoints.run_data_operation_request",
                    return_value=fake_result,
                ) as runner:
                    request = self._json_request(
                        server,
                        "api/operations/run",
                        {
                            "operation": "sync-wanna",
                            "parameters": {"offline": "true", "write_files": False},
                        },
                        token=token,
                        origin=server.url.rstrip("/"),
                    )
                    with urlopen(request, timeout=2) as response:
                        payload = json.loads(response.read().decode("utf-8"))
            finally:
                server.stop()

            self.assertEqual(payload["result"]["operation_key"], "sync-wanna")
            operation_request = runner.call_args.args[0]
            runtime_config = runner.call_args.kwargs["config"]
            self.assertEqual(operation_request.operation_key, "sync-wanna")
            self.assertTrue(operation_request.params["offline"])
            self.assertFalse(operation_request.params["write_files"])
            self.assertEqual(runtime_config.app_root, root.resolve())

    def test_webui_operation_run_rejects_invalid_payload_before_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = WebUiServer(port=0, app_root=tmp)
            server.start()
            try:
                token = self._csrf_token(server)
                with patch("dancing_log.webui_endpoints.run_data_operation_request") as runner:
                    request = self._json_request(
                        server,
                        "api/operations/run",
                        {
                            "operation": "import-vrcx",
                            "parameters": {"blank_requester_source": "self"},
                        },
                        token=token,
                        origin=server.url.rstrip("/"),
                    )
                    error = self._http_error_json(request, 400)
            finally:
                server.stop()

            self.assertIn("blank_requester_source must be one of", error["error"])
            runner.assert_not_called()

    def test_windows_picker_options_use_ifileopendialog_modes(self):
        directory_options = _file_dialog_options("directory", 0)
        file_options = _file_dialog_options("file", 0)

        self.assertTrue(directory_options & FOS_PICKFOLDERS)
        self.assertTrue(directory_options & FOS_FORCEFILESYSTEM)
        self.assertTrue(directory_options & FOS_PATHMUSTEXIST)
        self.assertFalse(directory_options & FOS_FILEMUSTEXIST)
        self.assertTrue(file_options & FOS_FILEMUSTEXIST)
        self.assertTrue(file_options & FOS_FORCEFILESYSTEM)
        self.assertTrue(file_options & FOS_PATHMUSTEXIST)
        self.assertFalse(file_options & FOS_PICKFOLDERS)

    def test_windows_picker_delegates_to_ifileopendialog_backend(self):
        with patch("dancing_log.windows_picker._show_windows_file_open_dialog", return_value="C:\\temp\\x.sqlite3") as picker:
            selected = _run_windows_picker({"picker": "file", "label": "App database"}, "C:\\temp")

        self.assertEqual(selected, "C:\\temp\\x.sqlite3")
        picker.assert_called_once_with(mode="file", title="App database", initial="C:\\temp")


if __name__ == "__main__":
    unittest.main()
