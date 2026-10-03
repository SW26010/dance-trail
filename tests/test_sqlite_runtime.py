import json
import hashlib
import re
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from dance_trail.app_paths import save_app_config
from dance_trail.models import (
    SOURCE_RECOMMEND,
    add_dance_record,
    generate_daily_playlist,
)
from dance_trail.favorite_importer import FavoriteImportError, import_favorites_file
from dance_trail.local_dance_day import LocalDanceDayBoundary
from dance_trail.queued_self_importer import sync_queued_self_manifests
from dance_trail.playback_projection import (
    EFFECTIVE_PLAYBACK_ACCEPTED,
    EFFECTIVE_PLAYBACK_EXCLUDED,
    EFFECTIVE_PLAYBACK_PENDING,
    set_manual_playback_decision,
)
from dance_trail.playback_evidence import read_timeline_playback_rows
from dance_trail.playback_record_writer import (
    PROJECT_SOURCE_ROOT_KEY,
    PROJECT_SOURCE_ROOT_PATH,
    PlaybackRecordOriginWrite,
    PlaybackRecordWrite,
    origin_key,
    playback_evidence_key,
    upsert_evidence_record,
)
from dance_trail.rebuild import archive_existing_data
from dance_trail.storage import (
    DUDU_SYSTEM_KEY,
    WANNA_SYSTEM_KEY,
    add_dance_event,
    connect_db,
    ensure_dance_track,
    load_dance_log,
    load_current_live_playback_event,
    load_dance_tracks,
    mark_live_playback_event_completed,
    make_live_playback_event_key,
    promote_live_playback_event,
    repair_stale_watcher_pending_records,
    upsert_live_playback_event,
)
from dance_trail.watcher_playback_materializer import (
    WATCHER_INTERRUPTED_UNEXPECTEDLY_REASON,
    WATCHER_PENDING_REASON,
    WATCHER_PLAYBACK_SOURCE_TABLE,
)
from dance_trail.vrcx_importer import import_vrcx_database
from dance_trail.wanna_catalog import sync_wanna_catalog, upsert_catalog
from tests.playback_record_helpers import insert_playback_record


ISO_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


def make_test_playback_record(
    *,
    played_at: str,
    original_played_at: str,
    dance_track_id: int | None,
    dance_system_key: str,
    dance_external_id: str,
    evidence_source: str,
    source_table: str,
    source_row_id: int,
    source_event_key: str,
    request_type: str | None,
    default_acceptance_status: str = "accepted",
    requester_display_name: str | None = None,
    requester_user_id: str | None = None,
    observation_status: str | None = None,
    observation_reason: str | None = None,
    observed_end_at: str | None = None,
    video_url: str | None = None,
    video_name: str | None = None,
    origin_source: str | None = None,
    origin_json: dict | None = None,
) -> PlaybackRecordWrite:
    payload = {"original_played_at": original_played_at}
    if origin_json:
        payload.update(origin_json)
    return PlaybackRecordWrite(
        evidence_key=playback_evidence_key(
            PROJECT_SOURCE_ROOT_KEY,
            source_table,
            source_row_id,
            source_event_key,
        ),
        evidence_source=evidence_source,
        played_at=played_at,
        dance_track_id=dance_track_id,
        dance_system_key=dance_system_key,
        dance_external_id=dance_external_id,
        request_type=request_type,
        default_acceptance_status=default_acceptance_status,
        requester_display_name=requester_display_name,
        requester_user_id=requester_user_id,
        observation_status=observation_status,
        observation_reason=observation_reason,
        observed_end_at=observed_end_at,
        video_url=video_url,
        video_name=video_name,
        origins=(
            PlaybackRecordOriginWrite(
                origin_key=origin_key(
                    PROJECT_SOURCE_ROOT_KEY,
                    source_table,
                    source_row_id,
                    source_event_key,
                ),
                origin_source=origin_source or evidence_source,
                origin_root_key=PROJECT_SOURCE_ROOT_KEY,
                origin_root_path=PROJECT_SOURCE_ROOT_PATH,
                origin_table=source_table,
                origin_row_id=source_row_id,
                origin_event_key=source_event_key,
                origin_json=payload,
            ),
        ),
    )


def favorite_map(db_path: Path | str) -> dict[tuple[str, str], int]:
    with connect_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT ds.key AS system_key, dt.external_id, dt.favorite
            FROM dance_tracks dt
            JOIN dance_systems ds ON ds.id = dt.system_id
            """
        ).fetchall()
    return {
        (row["system_key"], row["external_id"]): int(row["favorite"])
        for row in rows
    }


def vrcx_event_key(
    *,
    rowid: int,
    created_at: str,
    video_url: str,
    display_name: str = "",
    user_id: str = "",
) -> str:
    parts = [str(rowid), created_at, video_url, display_name, user_id]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


class SQLiteRuntimeTest(unittest.TestCase):
    def test_fresh_schema_uses_dance_tracks_not_legacy_songs(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "app.sqlite3")
            with connect_db(db_path) as conn:
                tables = {
                    row["name"]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                dance_event_columns = {
                    row["name"]
                    for row in conn.execute("PRAGMA table_info(dance_events)")
                }
                playback_columns = {
                    row["name"]
                    for row in conn.execute("PRAGMA table_info(playback_records)")
                }

            self.assertIn("dance_systems", tables)
            self.assertIn("dance_tracks", tables)
            self.assertIn("wannadance_songs", tables)
            self.assertIn("music_tracks", tables)
            self.assertIn("dance_track_music_links", tables)
            self.assertIn("playback_records", tables)
            self.assertIn("playback_record_origins", tables)
            self.assertIn("manual_playback_decisions", tables)
            self.assertIn("live_playback_events", tables)
            self.assertNotIn("songs", tables)
            self.assertIn("dance_track_id", dance_event_columns)
            self.assertNotIn("song_id", dance_event_columns)
            self.assertIn("evidence_key", playback_columns)
            self.assertIn("default_acceptance_status", playback_columns)
            self.assertNotIn("source_fingerprint", playback_columns)
            self.assertNotIn("counts_in_history", playback_columns)

    def test_runtime_metadata_timestamps_are_iso8601(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "app.sqlite3")
            with connect_db(db_path) as conn:
                track_id = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "3114",
                    {"title": "Song"},
                )
                row = conn.execute(
                    """
                    SELECT
                        ds.created_at AS system_created_at,
                        dt.created_at AS track_created_at,
                        dt.updated_at AS track_updated_at
                    FROM dance_tracks dt
                    JOIN dance_systems ds ON ds.id = dt.system_id
                    WHERE dt.id = ?
                    """,
                    (track_id,),
                ).fetchone()

            self.assertRegex(row["system_created_at"], ISO_UTC_RE)
            self.assertRegex(row["track_created_at"], ISO_UTC_RE)
            self.assertRegex(row["track_updated_at"], ISO_UTC_RE)

    def test_live_playback_upsert_is_idempotent_and_session_scoped(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "app.sqlite3"
            event = {
                "event_key": "wannadance:3114#1",
                "canonical_key": "wannadance:3114",
                "first_seen_at": "2026.05.17 15:30:00",
                "actual_play_at": None,
                "observed_mid_play": False,
                "video_url": "https://api.udon.dance/Api/Songs/play?id=3114",
                "dance_system_key": WANNA_SYSTEM_KEY,
                "dance_external_id": "3114",
                "video_name": "First Title",
                "source_type": "player",
                "source_display_name": "Alice",
                "signal_count": 1,
                "parser_names": ["video_playback_resolve"],
                "raw_event_types": ["resolve-attempt"],
            }

            key_one = make_live_playback_event_key("session-one", event["event_key"])
            key_two = make_live_playback_event_key("session-two", event["event_key"])
            self.assertNotEqual(key_one, key_two)

            with connect_db(db_path) as conn:
                row_id = upsert_live_playback_event(conn, event, session_id="session-one")
                event["video_name"] = "Updated Title"
                event["signal_count"] = 2
                self.assertEqual(
                    upsert_live_playback_event(conn, event, session_id="session-one"),
                    row_id,
                )
                conn.commit()
                rows = conn.execute("SELECT * FROM live_playback_events").fetchall()

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["video_name"], "Updated Title")
            self.assertEqual(rows[0]["signal_count"], 2)
            self.assertEqual(json.loads(rows[0]["parser_names_json"]), ["video_playback_resolve"])
            current = load_current_live_playback_event(db_path)
            self.assertEqual(current["event"]["video_name"], "Updated Title")
            self.assertFalse(current["observed_mid_play"])

    def test_live_playback_event_timestamps_are_iso8601(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "app.sqlite3"
            event = {
                "event_key": "wannadance:3114#1",
                "canonical_key": "wannadance:3114",
                "first_seen_at": "2026.05.17 15:30:00",
                "last_seen_at": "2026.05.17 15:30:12",
                "actual_play_at": "2026.05.17 15:30:10",
                "observed_mid_play": False,
                "video_url": "https://api.udon.dance/Api/Songs/play?id=3114",
                "dance_system_key": WANNA_SYSTEM_KEY,
                "dance_external_id": "3114",
                "video_name": "First Title",
                "signal_count": 1,
                "parser_names": ["usharp_delayed_video_ready"],
                "raw_event_types": ["actual-play"],
            }

            with connect_db(db_path) as conn:
                upsert_live_playback_event(conn, event, session_id="session-one")
                live_key = make_live_playback_event_key("session-one", event["event_key"])
                mark_live_playback_event_completed(
                    conn,
                    live_key,
                    completed_at="2026.05.17 15:30:12",
                    played_seconds=2,
                    required_played_seconds=2,
                    reason="test_complete",
                )
                conn.commit()
                row = conn.execute("SELECT * FROM live_playback_events").fetchone()

            row_event = json.loads(row["event_json"])
            self.assertEqual(row["first_seen_at"], "2026-05-17T07:30:00Z")
            self.assertEqual(row["actual_play_at"], "2026-05-17T07:30:10Z")
            self.assertEqual(row["completed_at"], "2026-05-17T07:30:12Z")
            self.assertRegex(row["created_at"], ISO_UTC_RE)
            self.assertRegex(row["last_updated_at"], ISO_UTC_RE)
            self.assertEqual(row_event["actual_play_at"], "2026-05-17T07:30:10Z")
            self.assertEqual(row_event["source_time_text"]["actual_play_at"], "2026.05.17 15:30:10")

    def test_live_playback_upsert_preserves_existing_requester_user_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "app.sqlite3"
            event = {
                "event_key": "wannadance:3114#1",
                "canonical_key": "wannadance:3114",
                "first_seen_at": "2026.05.17 15:30:00",
                "actual_play_at": None,
                "observed_mid_play": False,
                "video_url": "https://api.udon.dance/Api/Songs/play?id=3114",
                "dance_system_key": WANNA_SYSTEM_KEY,
                "dance_external_id": "3114",
                "video_name": "First Title",
                "source_type": "player",
                "source_display_name": "Alice",
                "requester_user_id": "usr_alice",
                "requester_user_id_source": "active",
                "signal_count": 1,
                "parser_names": ["video_playback_resolve"],
                "raw_event_types": ["resolve-attempt"],
            }

            with connect_db(db_path) as conn:
                upsert_live_playback_event(conn, event, session_id="session-one")
                updated = dict(event)
                updated["video_name"] = "Updated Title"
                updated["requester_user_id"] = "usr_bob"
                updated["requester_user_id_source"] = "expired"
                upsert_live_playback_event(conn, updated, session_id="session-one")
                conn.commit()
                row = conn.execute("SELECT * FROM live_playback_events").fetchone()

            current = load_current_live_playback_event(db_path)
            row_event = json.loads(row["event_json"])
            self.assertEqual(row["video_name"], "Updated Title")
            self.assertEqual(row["requester_user_id"], "usr_alice")
            self.assertEqual(row_event["requester_user_id"], "usr_alice")
            self.assertEqual(row_event["requester_user_id_source"], "active")
            self.assertEqual(current["event"]["requester_user_id"], "usr_alice")
            self.assertEqual(current["event"]["requester_user_id_source"], "active")

    def test_promote_live_playback_event_is_explicit_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "app.sqlite3"
            event = {
                "event_key": "wannadance:3114#1",
                "canonical_key": "wannadance:3114",
                "first_seen_at": "2026.05.17 15:30:00",
                "actual_play_at": "2026.05.17 15:30:10",
                "observed_mid_play": False,
                "duration_seconds": 2,
                "video_url": "https://api.udon.dance/Api/Songs/play?id=3114",
                "dance_system_key": WANNA_SYSTEM_KEY,
                "dance_external_id": "3114",
                "video_name": "Promoted Title",
                "source_type": "player",
                "source_display_name": "Alice",
                "requester_user_id": "usr_alice",
                "signal_count": 3,
                "parser_names": ["usharp_delayed_video_ready"],
                "raw_event_types": ["actual-play"],
            }

            with connect_db(db_path) as conn:
                upsert_live_playback_event(conn, event, session_id="session-one")
                self.assertEqual(conn.execute("SELECT count(*) FROM dance_events").fetchone()[0], 0)
                live_key = make_live_playback_event_key("session-one", event["event_key"])
                self.assertIsNone(promote_live_playback_event(conn, live_key))
                self.assertTrue(
                    mark_live_playback_event_completed(
                        conn,
                        live_key,
                        completed_at="2026.05.17 15:30:12",
                        played_seconds=2,
                        required_played_seconds=2,
                        reason="test_complete",
                    )
                )
                first_id = promote_live_playback_event(conn, live_key)
                second_id = promote_live_playback_event(conn, live_key)
                conn.commit()
                dance_rows = conn.execute("SELECT * FROM dance_events").fetchall()
                playback_rows = conn.execute("SELECT * FROM playback_records").fetchall()
                origin_row = conn.execute(
                    "SELECT * FROM playback_record_origins"
                ).fetchone()
                live_row = conn.execute("SELECT * FROM live_playback_events").fetchone()

            self.assertEqual(first_id, second_id)
            self.assertEqual(len(dance_rows), 0)
            self.assertEqual(len(playback_rows), 1)
            self.assertEqual(playback_rows[0]["request_type"], "player")
            self.assertEqual(playback_rows[0]["played_at"], "2026-05-17T07:30:10Z")
            origin_json = json.loads(origin_row["origin_json"])
            self.assertEqual(origin_json["original_played_at"], "2026.05.17 15:30:10")
            self.assertEqual(playback_rows[0]["requester_display_name"], "Alice")
            self.assertEqual(playback_rows[0]["requester_user_id"], "usr_alice")
            self.assertEqual(live_row["requester_user_id"], "usr_alice")
            self.assertEqual(live_row["promoted_playback_record_id"], first_id)
            self.assertEqual(live_row["completion_status"], "completed")

    def test_promote_live_playback_event_skips_mid_play(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "app.sqlite3"
            event = {
                "event_key": "pypydance:4678#1",
                "canonical_key": "pypydance:4678",
                "first_seen_at": "2026.05.17 17:15:30",
                "actual_play_at": "2026.05.17 17:14:12.67008",
                "observed_mid_play": True,
                "dance_system_key": "pypydance",
                "dance_external_id": "4678",
                "source_type": "player",
                "signal_count": 2,
                "parser_names": ["vrcx_video_play"],
                "raw_event_types": ["playback-progress"],
            }

            with connect_db(db_path) as conn:
                upsert_live_playback_event(conn, event, session_id="session-one")
                live_key = make_live_playback_event_key("session-one", event["event_key"])
                self.assertIsNone(promote_live_playback_event(conn, live_key))
                conn.commit()
                event_count = conn.execute("SELECT count(*) FROM dance_events").fetchone()[0]

            self.assertEqual(event_count, 0)

    def test_promote_live_playback_event_reuses_cleanup_source_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "app.sqlite3"
            event = {
                "event_key": "wannadance:5038#1",
                "canonical_key": "wannadance:5038",
                "first_seen_at": "2026.05.17 16:30:00",
                "actual_play_at": "2026.05.17 16:30:10",
                "observed_mid_play": False,
                "duration_seconds": 2,
                "video_url": "https://api.udon.dance/Api/Songs/play?id=5038",
                "dance_system_key": WANNA_SYSTEM_KEY,
                "dance_external_id": "5038",
                "video_name": "Existing Live Evidence",
                "source_type": "player",
                "source_display_name": "Alice",
                "signal_count": 3,
                "parser_names": ["usharp_delayed_video_ready"],
                "raw_event_types": ["actual-play"],
            }

            with connect_db(db_path) as conn:
                live_row_id = upsert_live_playback_event(conn, event, session_id="session-one")
                live_key = make_live_playback_event_key("session-one", event["event_key"])
                track_id = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "5038",
                    {"title": "Existing Live Evidence"},
                )
                existing = upsert_evidence_record(
                    conn,
                    make_test_playback_record(
                        played_at=event["actual_play_at"],
                        original_played_at=event["actual_play_at"],
                        dance_track_id=track_id,
                        dance_system_key=WANNA_SYSTEM_KEY,
                        dance_external_id="5038",
                        evidence_source="vrc_log_live",
                        source_table="live_playback_events",
                        source_row_id=live_row_id,
                        source_event_key=live_key,
                        request_type="player",
                        observation_status="completed",
                        observation_reason="observed_completion_threshold",
                        origin_source="vrchat_log",
                    ),
                )
                self.assertTrue(
                    mark_live_playback_event_completed(
                        conn,
                        live_key,
                        completed_at="2026.05.17 16:30:12",
                        played_seconds=2,
                        required_played_seconds=2,
                        reason="observed_completion_threshold",
                    )
                )
                promoted_id = promote_live_playback_event(conn, live_key)
                playback_rows = conn.execute("SELECT * FROM playback_records").fetchall()
                origin_row = conn.execute(
                    "SELECT * FROM playback_record_origins"
                ).fetchone()
                live_row = conn.execute("SELECT * FROM live_playback_events").fetchone()

            self.assertEqual(promoted_id, existing.playback_record_id)
            self.assertEqual(len(playback_rows), 1)
            self.assertEqual(origin_row["origin_root_key"], PROJECT_SOURCE_ROOT_KEY)
            self.assertEqual(origin_row["origin_table"], "live_playback_events")
            self.assertEqual(live_row["promoted_playback_record_id"], existing.playback_record_id)

    def test_playback_record_writer_reports_noop_as_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "app.sqlite3"
            with connect_db(db_path) as conn:
                track_id = ensure_dance_track(conn, WANNA_SYSTEM_KEY, "5038")
                record = make_test_playback_record(
                    played_at="2026-04-17T20:30:00+08:00",
                    original_played_at="2026-04-17T20:30:00+08:00",
                    dance_track_id=track_id,
                    dance_system_key=WANNA_SYSTEM_KEY,
                    dance_external_id="5038",
                    evidence_source="manual_log",
                    source_table="manual_log",
                    source_row_id=0,
                    source_event_key="manual-event",
                    request_type="self",
                    origin_source="manual_log",
                    origin_json={"manual_log": {"note": "first"}},
                )

                inserted = upsert_evidence_record(conn, record)
                unchanged = upsert_evidence_record(conn, record)
                changed = upsert_evidence_record(
                    conn,
                    PlaybackRecordWrite(
                        **{
                            **record.__dict__,
                            "request_type": "queued_self",
                        }
                    ),
                )
                rows = conn.execute("SELECT * FROM playback_records").fetchall()

            self.assertEqual(inserted.changed, 1)
            self.assertEqual(unchanged.changed, 0)
            self.assertEqual(changed.changed, 1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["request_type"], "queued_self")

    def test_playback_record_writer_normalizes_timestamps_to_iso8601(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "app.sqlite3"
            with connect_db(db_path) as conn:
                track_id = ensure_dance_track(conn, WANNA_SYSTEM_KEY, "5038")
                upsert_evidence_record(
                    conn,
                    make_test_playback_record(
                        played_at="2026.05.17 15:30:10",
                        original_played_at="2026.05.17 15:30:10",
                        dance_track_id=track_id,
                        dance_system_key=WANNA_SYSTEM_KEY,
                        dance_external_id="5038",
                        evidence_source="vrc_log_live",
                        source_table="watcher_playback_events",
                        source_row_id=0,
                        source_event_key="watcher-event",
                        request_type="player",
                        origin_source="vrchat_log",
                    ),
                )
                row = conn.execute("SELECT * FROM playback_records").fetchone()
                origin = conn.execute(
                    "SELECT * FROM playback_record_origins"
                ).fetchone()

            self.assertEqual(row["played_at"], "2026-05-17T07:30:10Z")
            origin_json = json.loads(origin["origin_json"])
            self.assertEqual(origin_json["original_played_at"], "2026.05.17 15:30:10")
            self.assertRegex(row["created_at"], ISO_UTC_RE)
            self.assertRegex(row["updated_at"], ISO_UTC_RE)

    def test_manual_log_source_identity_uses_raw_source_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "app.sqlite3"
            raw_played_at = "2026.05.17 15:30:10"

            add_dance_event(
                system_key=WANNA_SYSTEM_KEY,
                external_id="5038",
                source="other",
                played_at=raw_played_at,
                event_source="manual",
                path=db_path,
            )

            with connect_db(db_path) as conn:
                row = conn.execute(
                    """
                    SELECT
                        pr.played_at,
                        pro.origin_event_key,
                        pro.origin_json
                    FROM playback_records pr
                    JOIN playback_record_origins pro
                        ON pro.playback_record_id = pr.id
                    """
                ).fetchone()

            expected_key = hashlib.sha256(
                "\x1f".join(
                    [
                        "manual",
                        raw_played_at,
                        f"{WANNA_SYSTEM_KEY}:5038",
                        "other",
                        "",
                    ]
                ).encode("utf-8")
            ).hexdigest()
            origin_json = json.loads(row["origin_json"])
            self.assertEqual(row["origin_event_key"], expected_key)
            self.assertEqual(row["played_at"], "2026-05-17T07:30:10Z")
            self.assertEqual(origin_json["original_played_at"], raw_played_at)

    def test_connect_db_does_not_repair_existing_timestamps_implicitly(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "app.sqlite3"
            with connect_db(db_path) as conn:
                track_id = ensure_dance_track(conn, WANNA_SYSTEM_KEY, "5038")
                result = upsert_evidence_record(
                    conn,
                    make_test_playback_record(
                        played_at="2026-05-17T07:30:10Z",
                        original_played_at="2026.05.17 15:30:10",
                        dance_track_id=track_id,
                        dance_system_key=WANNA_SYSTEM_KEY,
                        dance_external_id="5038",
                        evidence_source="vrc_log_live",
                        source_table="watcher_playback_events",
                        source_row_id=0,
                        source_event_key="watcher-event",
                        request_type="player",
                        origin_source="vrchat_log",
                    ),
                )
                conn.execute(
                    """
                    UPDATE playback_records
                    SET played_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        "2026.05.17 15:30:10",
                        "2026-06-24 03:11:07",
                        result.playback_record_id,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO live_playback_events (
                        event_key,
                        session_id,
                        playback_event_key,
                        actual_play_at,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        "live-event",
                        "session-one",
                        "wannadance:5038#1",
                        "2026.05.17 15:30:10",
                        "2026-06-24 03:11:07",
                    ),
                )
                conn.commit()

            with connect_db(db_path) as conn:
                record = conn.execute("SELECT * FROM playback_records").fetchone()
                live = conn.execute("SELECT * FROM live_playback_events").fetchone()

            self.assertEqual(record["played_at"], "2026.05.17 15:30:10")
            self.assertEqual(record["updated_at"], "2026-06-24 03:11:07")
            self.assertEqual(live["actual_play_at"], "2026.05.17 15:30:10")
            self.assertEqual(live["created_at"], "2026-06-24 03:11:07")

    def test_wanna_catalog_writes_tracks_specific_fields_and_music_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "app.sqlite3")
            song = {
                "id": 5038,
                "name": "Good Time",
                "artist": "Owl City",
                "dancer": "JAMAA",
                "player_count": 1,
                "group": "Solo",
                "major": "Just Dance",
                "cache_url": "https://example.test/video.mp4",
                "cache_flip": 1,
            }

            with connect_db(db_path) as conn:
                self.assertEqual(upsert_catalog(conn, [song]), 1)
                self.assertEqual(upsert_catalog(conn, [song]), 1)
                track_count = conn.execute("SELECT count(*) FROM dance_tracks").fetchone()[0]
                wanna_count = conn.execute("SELECT count(*) FROM wannadance_songs").fetchone()[0]
                music_count = conn.execute("SELECT count(*) FROM music_tracks").fetchone()[0]
                link_count = conn.execute("SELECT count(*) FROM dance_track_music_links").fetchone()[0]
                row = conn.execute(
                    """
                    SELECT dt.title, dt.artist, ws.cache_url, ws.cache_flip
                    FROM dance_tracks dt
                    JOIN wannadance_songs ws ON ws.dance_track_id = dt.id
                    """
                ).fetchone()

            self.assertEqual(track_count, 1)
            self.assertEqual(wanna_count, 1)
            self.assertEqual(music_count, 1)
            self.assertEqual(link_count, 1)
            self.assertEqual(row["title"], "Good Time")
            self.assertEqual(row["artist"], "Owl City")
            self.assertEqual(row["cache_url"], "https://example.test/video.mp4")
            self.assertEqual(row["cache_flip"], 1)

    def test_sync_wanna_catalog_default_loads_saved_app_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_track_dir = root / "cache" / "5038"
            cache_track_dir.mkdir(parents=True)
            (cache_track_dir / "metadata.json").write_text(
                '{"id":5038,"title":"Configured Song","artist":"Configured Artist"}',
                encoding="utf-8",
            )
            save_app_config(
                {
                    "app_db": "custom/app.sqlite3",
                    "wanna_cache_dir": "cache",
                },
                app_root=root,
            )

            with patch("dance_trail.app_paths.default_app_root", return_value=root):
                stats = sync_wanna_catalog(use_api=False)

            self.assertEqual(stats.cache_count, 1)
            self.assertTrue((root / "custom" / "app.sqlite3").exists())
            self.assertFalse((root / "data" / "dance_trail.sqlite3").exists())

    def test_manual_log_uses_system_external_id_and_preserves_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "app.sqlite3")
            with connect_db(db_path) as conn:
                upsert_catalog(
                    conn,
                    [
                        {
                            "id": 5038,
                            "name": "Good Time",
                            "artist": "Owl City",
                            "dancer": "JAMAA",
                            "player_count": 1,
                            "group": "Solo",
                            "major": "Just Dance",
                        }
                    ],
                )

            actual_source = add_dance_record(
                WANNA_SYSTEM_KEY,
                "5038",
                note="nice run",
                timestamp="2026-04-17T20:30:00+08:00",
                db_path=db_path,
            )

            self.assertEqual(actual_source, SOURCE_RECOMMEND)
            with connect_db(db_path) as conn:
                row = conn.execute(
                    """
                    SELECT
                        pr.request_type,
                        pro.origin_json,
                        ds.key AS system_key,
                        dt.external_id
                    FROM playback_records pr
                    JOIN playback_record_origins pro
                        ON pro.playback_record_id = pr.id
                    JOIN dance_tracks dt ON dt.id = pr.dance_track_id
                    JOIN dance_systems ds ON ds.id = dt.system_id
                    """
                ).fetchone()
            self.assertEqual(row["system_key"], WANNA_SYSTEM_KEY)
            self.assertEqual(row["external_id"], "5038")
            self.assertEqual(row["request_type"], SOURCE_RECOMMEND)
            self.assertEqual(json.loads(row["origin_json"])["manual_log"]["note"], "nice run")

    def test_recommendation_history_reads_playback_records_not_legacy_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "app.sqlite3")
            with connect_db(db_path) as conn:
                legacy_track_id = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "100",
                    {"title": "Legacy Song", "artist": "Legacy Artist"},
                )
                evidence_track_id = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "200",
                    {"title": "Evidence Song", "artist": "Evidence Artist"},
                )
                excluded_track_id = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "300",
                    {"title": "Excluded Song", "artist": "Excluded Artist"},
                )
                manual_accepted_track_id = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "400",
                        {"title": "Manual Song", "artist": "Manual Artist"},
                )
                pending_track_id = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "500",
                    {"title": "Pending Song", "artist": "Pending Artist"},
                )
                insert_playback_record(
                    conn,
                    track_id=evidence_track_id,
                    played_at="2026-06-18T20:00:00+08:00",
                    source_type="self",
                )
                excluded_record_id = insert_playback_record(
                    conn,
                    track_id=excluded_track_id,
                    played_at="2026-06-18T20:10:00+08:00",
                    source_type="self",
                )
                manual_accepted_record_id = insert_playback_record(
                    conn,
                    track_id=manual_accepted_track_id,
                    played_at="2026-06-18T20:20:00+08:00",
                    source_type="player",
                    playback_status="needs_attention",
                    counts_in_history=0,
                )
                pending_record_id = insert_playback_record(
                    conn,
                    track_id=pending_track_id,
                    played_at="2026-06-18T20:30:00+08:00",
                    source_kind="live_watcher",
                    source_table=WATCHER_PLAYBACK_SOURCE_TABLE,
                    source_type="player",
                    playback_status=EFFECTIVE_PLAYBACK_PENDING,
                    counts_in_history=0,
                    status_reason=WATCHER_PENDING_REASON,
                )
                set_manual_playback_decision(
                    conn,
                    excluded_record_id,
                    EFFECTIVE_PLAYBACK_EXCLUDED,
                )
                set_manual_playback_decision(
                    conn,
                    manual_accepted_record_id,
                    EFFECTIVE_PLAYBACK_ACCEPTED,
                )
                conn.commit()

            with connect_db(db_path) as conn:
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
                    VALUES (?, ?, 'random', 0.7, 'legacy-test', 'legacy-event')
                    """,
                    ("2026-06-18T19:00:00+08:00", legacy_track_id),
                )
                conn.commit()

            records = load_dance_log(db_path)
            with connect_db(db_path) as conn:
                timeline_rows = read_timeline_playback_rows(conn)

            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["dance_track_id"], evidence_track_id)
            self.assertEqual(records[1]["dance_track_id"], manual_accepted_track_id)
            self.assertNotEqual(records[0]["dance_track_id"], legacy_track_id)
            self.assertEqual(records[0]["external_id"], "200")
            self.assertNotIn(
                excluded_track_id,
                {record["dance_track_id"] for record in records},
            )
            by_event_id = {row["event_id"]: row for row in timeline_rows}
            self.assertEqual(
                by_event_id[pending_record_id]["effective_playback_status"],
                EFFECTIVE_PLAYBACK_PENDING,
            )
            self.assertNotIn(
                pending_track_id,
                {record["dance_track_id"] for record in records},
            )

    def test_repair_stale_watcher_pending_records_marks_unexpected_interruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "app.sqlite3"
            with connect_db(db_path) as conn:
                track_id = ensure_dance_track(conn, WANNA_SYSTEM_KEY, "5038")
                pending_record_id = insert_playback_record(
                    conn,
                    track_id=track_id,
                    played_at="2026-06-18T20:30:00+08:00",
                    source_kind="live_watcher",
                    source_table=WATCHER_PLAYBACK_SOURCE_TABLE,
                    playback_status=EFFECTIVE_PLAYBACK_PENDING,
                    counts_in_history=0,
                    status_reason=WATCHER_PENDING_REASON,
                )

                changed = repair_stale_watcher_pending_records(conn)
                second_changed = repair_stale_watcher_pending_records(conn)
                row = conn.execute(
                    "SELECT * FROM playback_records WHERE id = ?",
                    (pending_record_id,),
                ).fetchone()

            self.assertEqual(changed, 1)
            self.assertEqual(second_changed, 0)
            self.assertEqual(row["default_acceptance_status"], "needs_attention")
            self.assertEqual(row["observation_status"], "interrupted")
            self.assertEqual(row["observation_reason"], WATCHER_INTERRUPTED_UNEXPECTEDLY_REASON)

    def test_recommendation_uses_dance_track_ids_without_popularity(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "app.sqlite3")
            with connect_db(db_path) as conn:
                track_id = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "1",
                    {"title": "Song", "artist": "Artist"},
                )
                conn.execute(
                    "UPDATE dance_tracks SET favorite = 1, want_to_learn = 1 WHERE id = ?",
                    (track_id,),
                )
                conn.commit()

            tracks = load_dance_tracks(db_path)
            playlist = generate_daily_playlist(tracks, [], count=1)

            self.assertEqual(playlist[0]["id"], track_id)
            self.assertEqual(playlist[0]["system_key"], WANNA_SYSTEM_KEY)
            self.assertNotIn("popularity", playlist[0])

    def test_recommendation_seed_uses_current_local_dance_day(self):
        fixed_now = datetime(2026, 6, 17, 18, 30, tzinfo=timezone.utc)

        class BoundaryAtFixedInstant(LocalDanceDayBoundary):
            def current_date(self, *, now=None):
                return super().current_date(now=fixed_now)

        boundary = BoundaryAtFixedInstant.from_config(
            {"dance_day_boundary_time": "03:00"},
            time_zone=timezone(timedelta(hours=8)),
        )

        with patch("dance_trail.models._playlist_seed", return_value=0) as seed:
            playlist = generate_daily_playlist(
                [],
                [],
                dance_day_boundary=boundary,
            )

        self.assertEqual(playlist, [])
        seed.assert_called_once_with(date(2026, 6, 17))

    def test_import_favorites_replaces_system_favorites_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "app.sqlite3"
            favorites_path = root / "favorites.txt"
            with connect_db(db_path) as conn:
                for external_id in ("1", "2", "3"):
                    ensure_dance_track(conn, WANNA_SYSTEM_KEY, external_id)
                conn.execute(
                    """
                    UPDATE dance_tracks
                    SET favorite = 1
                    WHERE external_id IN ('2', '3')
                    """
                )
                conn.commit()
            favorites_path.write_text("1\n2\n1\n", encoding="utf-8")

            stats = import_favorites_file(
                system_key=WANNA_SYSTEM_KEY,
                favorites_file=favorites_path,
                app_db_path=db_path,
            )

            self.assertEqual(stats.input_ids, 3)
            self.assertEqual(stats.unique_ids, 2)
            self.assertEqual(stats.duplicate_ids, 1)
            self.assertEqual(stats.favorites_set, 1)
            self.assertEqual(stats.favorites_cleared, 1)
            self.assertEqual(
                favorite_map(db_path),
                {
                    (WANNA_SYSTEM_KEY, "1"): 1,
                    (WANNA_SYSTEM_KEY, "2"): 1,
                    (WANNA_SYSTEM_KEY, "3"): 0,
                },
            )

    def test_import_favorites_parses_wanna_favorite_comma_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "app.sqlite3"
            favorites_path = root / "liked_songs_wannadance.txt"
            with connect_db(db_path) as conn:
                for external_id in ("6495", "10508", "5929"):
                    ensure_dance_track(conn, WANNA_SYSTEM_KEY, external_id)
                conn.commit()
            favorites_path.write_text(
                "WannaFavorite:6495,10508,5929,6495\n",
                encoding="utf-8",
            )

            stats = import_favorites_file(
                system_key=WANNA_SYSTEM_KEY,
                favorites_file=favorites_path,
                app_db_path=db_path,
            )

            self.assertEqual(stats.input_ids, 4)
            self.assertEqual(stats.unique_ids, 3)
            self.assertEqual(stats.duplicate_ids, 1)
            self.assertEqual(stats.favorites_set, 3)
            self.assertEqual(
                favorite_map(db_path),
                {
                    (WANNA_SYSTEM_KEY, "6495"): 1,
                    (WANNA_SYSTEM_KEY, "10508"): 1,
                    (WANNA_SYSTEM_KEY, "5929"): 1,
                },
            )

    def test_import_favorites_additive_does_not_clear_existing_favorites(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "app.sqlite3"
            favorites_path = root / "favorites.txt"
            with connect_db(db_path) as conn:
                for external_id in ("1", "2", "3"):
                    ensure_dance_track(conn, WANNA_SYSTEM_KEY, external_id)
                conn.execute(
                    "UPDATE dance_tracks SET favorite = 1 WHERE external_id = '3'"
                )
                conn.commit()
            favorites_path.write_text("1\n2\n", encoding="utf-8")

            stats = import_favorites_file(
                system_key=WANNA_SYSTEM_KEY,
                favorites_file=favorites_path,
                app_db_path=db_path,
                additive=True,
            )

            self.assertEqual(stats.favorites_set, 2)
            self.assertEqual(stats.favorites_cleared, 0)
            self.assertEqual(
                favorite_map(db_path),
                {
                    (WANNA_SYSTEM_KEY, "1"): 1,
                    (WANNA_SYSTEM_KEY, "2"): 1,
                    (WANNA_SYSTEM_KEY, "3"): 1,
                },
            )

    def test_import_favorites_dry_run_reports_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "app.sqlite3"
            favorites_path = root / "favorites.txt"
            with connect_db(db_path) as conn:
                ensure_dance_track(conn, WANNA_SYSTEM_KEY, "1")
                ensure_dance_track(conn, WANNA_SYSTEM_KEY, "2")
                conn.execute(
                    "UPDATE dance_tracks SET favorite = 1 WHERE external_id = '2'"
                )
                conn.commit()
            favorites_path.write_text("1\n", encoding="utf-8")

            stats = import_favorites_file(
                system_key=WANNA_SYSTEM_KEY,
                favorites_file=favorites_path,
                app_db_path=db_path,
                dry_run=True,
            )

            self.assertTrue(stats.dry_run)
            self.assertEqual(stats.favorites_set, 1)
            self.assertEqual(stats.favorites_cleared, 1)
            self.assertEqual(
                favorite_map(db_path),
                {
                    (WANNA_SYSTEM_KEY, "1"): 0,
                    (WANNA_SYSTEM_KEY, "2"): 1,
                },
            )

    def test_import_favorites_unknown_id_fails_without_partial_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "app.sqlite3"
            favorites_path = root / "favorites.txt"
            with connect_db(db_path) as conn:
                ensure_dance_track(conn, WANNA_SYSTEM_KEY, "1")
                ensure_dance_track(conn, WANNA_SYSTEM_KEY, "2")
                conn.execute(
                    "UPDATE dance_tracks SET favorite = 1 WHERE external_id = '2'"
                )
                conn.commit()
            favorites_path.write_text("1\n999\n", encoding="utf-8")

            with self.assertRaisesRegex(FavoriteImportError, "999"):
                import_favorites_file(
                    system_key=WANNA_SYSTEM_KEY,
                    favorites_file=favorites_path,
                    app_db_path=db_path,
                )

            self.assertEqual(
                favorite_map(db_path),
                {
                    (WANNA_SYSTEM_KEY, "1"): 0,
                    (WANNA_SYSTEM_KEY, "2"): 1,
                },
            )

    def test_import_favorites_replace_is_scoped_to_one_system(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "app.sqlite3"
            favorites_path = root / "favorites.txt"
            with connect_db(db_path) as conn:
                ensure_dance_track(conn, WANNA_SYSTEM_KEY, "1")
                ensure_dance_track(conn, WANNA_SYSTEM_KEY, "2")
                ensure_dance_track(conn, "otherdance", "1")
                conn.execute("UPDATE dance_tracks SET favorite = 1")
                conn.commit()
            favorites_path.write_text("1\n", encoding="utf-8")

            stats = import_favorites_file(
                system_key=WANNA_SYSTEM_KEY,
                favorites_file=favorites_path,
                app_db_path=db_path,
            )

            self.assertEqual(stats.favorites_cleared, 1)
            self.assertEqual(
                favorite_map(db_path),
                {
                    (WANNA_SYSTEM_KEY, "1"): 1,
                    (WANNA_SYSTEM_KEY, "2"): 0,
                    ("otherdance", "1"): 1,
                },
            )

    def test_import_favorites_blank_line_fails_without_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "app.sqlite3"
            favorites_path = root / "favorites.txt"
            with connect_db(db_path) as conn:
                ensure_dance_track(conn, WANNA_SYSTEM_KEY, "1")
                conn.commit()
            favorites_path.write_text("1\n\n", encoding="utf-8")

            with self.assertRaisesRegex(FavoriteImportError, "line 2"):
                import_favorites_file(
                    system_key=WANNA_SYSTEM_KEY,
                    favorites_file=favorites_path,
                    app_db_path=db_path,
                )

            self.assertEqual(favorite_map(db_path), {(WANNA_SYSTEM_KEY, "1"): 0})

    def test_vrcx_import_writes_new_tables_and_skips_unsupported_systems(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vrcx_path = root / "VRCX.sqlite3"
            app_path = root / "app.sqlite3"
            with closing(sqlite3.connect(vrcx_path)) as conn:
                conn.execute(
                    """
                    CREATE TABLE gamelog_video_play (
                        created_at TEXT,
                        video_url TEXT,
                        video_name TEXT,
                        video_id TEXT,
                        location TEXT,
                        display_name TEXT,
                        user_id TEXT
                    )
                    """
                )
                conn.executemany(
                    "INSERT INTO gamelog_video_play VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            "2026-05-15T14:20:11.000Z",
                            "https://api.udon.dance/Api/Songs/play?id=3114",
                            "Song Name",
                            "",
                            "wrld_1",
                            "",
                            "",
                        ),
                        (
                            "2026-05-15T15:20:11.000Z",
                            "http://jd.pypy.moe/api/v1/videos/4051.mp4",
                            "PyPy Song",
                            "",
                            "wrld_2",
                            "",
                            "",
                        ),
                        (
                            "2026-05-15T16:20:11.000Z",
                            "https://api.dudufit.dance/api/v1/videos/1321?cdn=jpn",
                            "Dudu Song",
                            "",
                            "wrld_3",
                            "Alice",
                            "",
                        ),
                    ],
                )
                conn.commit()

            stats = import_vrcx_database(vrcx_path, app_db_path=app_path)

            self.assertEqual(stats.playback_records_changed, 3)
            self.assertEqual(stats.dance_events_changed, 3)
            self.assertEqual(stats.skipped_unsupported, 0)
            with connect_db(app_path) as conn:
                wanna_track_count = conn.execute(
                    """
                    SELECT count(*)
                    FROM dance_tracks dt
                    JOIN dance_systems ds ON ds.id = dt.system_id
                    WHERE ds.key = ? AND dt.external_id = '3114'
                    """,
                    (WANNA_SYSTEM_KEY,),
                ).fetchone()[0]
                pypy_track_count = conn.execute(
                    """
                    SELECT count(*)
                    FROM dance_tracks dt
                    JOIN dance_systems ds ON ds.id = dt.system_id
                    WHERE ds.key = 'pypydance' AND dt.external_id = '4051'
                    """
                ).fetchone()[0]
                dudu_track_count = conn.execute(
                    """
                    SELECT count(*)
                    FROM dance_tracks dt
                    JOIN dance_systems ds ON ds.id = dt.system_id
                    WHERE ds.key = ? AND dt.external_id = '1321'
                    """,
                    (DUDU_SYSTEM_KEY,),
                ).fetchone()[0]
                event_count = conn.execute("SELECT count(*) FROM dance_events").fetchone()[0]
                playback_count = conn.execute("SELECT count(*) FROM playback_records").fetchone()[0]
                source_tables = {
                    row["origin_table"]
                    for row in conn.execute(
                        "SELECT DISTINCT origin_table FROM playback_record_origins"
                    )
                }
                parsed = conn.execute(
                    """
                    SELECT parsed_external_id, parsed_dance_track_id
                    FROM vrcx_import_events
                    ORDER BY created_at
                    """
                ).fetchall()
                dudu_playback = conn.execute(
                    """
                    SELECT requester_display_name, requester_user_id, request_type
                    FROM playback_records
                    WHERE dance_system_key = ? AND dance_external_id = '1321'
                    """,
                    (DUDU_SYSTEM_KEY,),
                ).fetchone()
            self.assertEqual(wanna_track_count, 1)
            self.assertEqual(pypy_track_count, 1)
            self.assertEqual(dudu_track_count, 1)
            self.assertEqual(event_count, 0)
            self.assertEqual(playback_count, 3)
            self.assertEqual(source_tables, {"vrcx_import_events"})
            self.assertEqual(parsed[0]["parsed_external_id"], "3114")
            self.assertEqual(parsed[1]["parsed_external_id"], "4051")
            self.assertEqual(parsed[2]["parsed_external_id"], "1321")
            self.assertIsInstance(parsed[0]["parsed_dance_track_id"], int)
            self.assertIsInstance(parsed[1]["parsed_dance_track_id"], int)
            self.assertIsInstance(parsed[2]["parsed_dance_track_id"], int)
            self.assertEqual(dudu_playback["requester_display_name"], "Alice")
            self.assertIsNone(dudu_playback["requester_user_id"])
            self.assertEqual(dudu_playback["request_type"], "unknown")

    def test_vrcx_import_reuses_cleanup_dance_event_source_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vrcx_path = root / "VRCX.sqlite3"
            app_path = root / "app.sqlite3"
            created_at = "2026-05-15T14:20:11.000Z"
            video_url = "https://api.udon.dance/Api/Songs/play?id=3114"
            event_key = vrcx_event_key(
                rowid=1,
                created_at=created_at,
                video_url=video_url,
            )
            with closing(sqlite3.connect(vrcx_path)) as conn:
                conn.execute(
                    """
                    CREATE TABLE gamelog_video_play (
                        created_at TEXT,
                        video_url TEXT,
                        video_name TEXT,
                        video_id TEXT,
                        location TEXT,
                        display_name TEXT,
                        user_id TEXT
                    )
                    """
                )
                conn.execute(
                    "INSERT INTO gamelog_video_play VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (created_at, video_url, "Song Name", "", "wrld_1", "", ""),
                )
                conn.commit()

            with connect_db(app_path) as conn:
                track_id = ensure_dance_track(conn, WANNA_SYSTEM_KEY, "3114")
                legacy_cursor = conn.execute(
                    """
                    INSERT INTO dance_events (
                        played_at,
                        dance_track_id,
                        source,
                        confidence,
                        event_source,
                        event_key,
                        video_url,
                        video_name,
                        location
                    )
                    VALUES (?, ?, 'random', 0.7, 'vrcx', ?, ?, ?, ?)
                    """,
                    (created_at, track_id, event_key, video_url, "Song Name", "wrld_1"),
                )
                legacy_event_id = int(legacy_cursor.lastrowid)
                existing = upsert_evidence_record(
                    conn,
                    make_test_playback_record(
                        played_at=created_at,
                        original_played_at=created_at,
                        dance_track_id=track_id,
                        dance_system_key=WANNA_SYSTEM_KEY,
                        dance_external_id="3114",
                        evidence_source="vrcx_history",
                        source_table="dance_events",
                        source_row_id=legacy_event_id,
                        source_event_key=event_key,
                        request_type="random",
                        video_url=video_url,
                        video_name="Song Name",
                        requester_display_name="",
                        requester_user_id="",
                        origin_source="vrcx_database",
                        origin_json={
                            "vrcx_location": "wrld_1",
                            "legacy_confidence": 0.7,
                            "legacy_status_reason": "vrcx_import",
                        },
                    ),
                )
                conn.commit()

            stats = import_vrcx_database(vrcx_path, app_db_path=app_path)

            with connect_db(app_path) as conn:
                rows = conn.execute("SELECT * FROM playback_records").fetchall()
                origins = conn.execute("SELECT * FROM playback_record_origins").fetchall()
                source = rows[0]
                origin = origins[0]

            self.assertEqual(stats.playback_records_changed, 0)
            self.assertEqual(len(rows), 1)
            self.assertEqual(len(origins), 1)
            self.assertEqual(source["id"], existing.playback_record_id)
            self.assertEqual(origin["origin_root_key"], PROJECT_SOURCE_ROOT_KEY)
            self.assertEqual(origin["origin_table"], "dance_events")
            self.assertEqual(origin["origin_row_id"], legacy_event_id)

    def test_vrcx_import_normalizes_canonical_time_and_preserves_source_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vrcx_path = root / "VRCX.sqlite3"
            app_path = root / "app.sqlite3"
            raw_created_at = "2026.05.17 15:30:10"
            video_url = "https://api.udon.dance/Api/Songs/play?id=3114"
            with closing(sqlite3.connect(vrcx_path)) as conn:
                conn.execute(
                    """
                    CREATE TABLE gamelog_video_play (
                        created_at TEXT,
                        video_url TEXT,
                        video_name TEXT,
                        video_id TEXT,
                        location TEXT,
                        display_name TEXT,
                        user_id TEXT
                    )
                    """
                )
                conn.execute(
                    "INSERT INTO gamelog_video_play VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        raw_created_at,
                        video_url,
                        "Song Name",
                        "",
                        "wrld_1",
                        "Alice",
                        "usr_alice",
                    ),
                )
                conn.commit()

            stats = import_vrcx_database(vrcx_path, app_db_path=app_path)

            with connect_db(app_path) as conn:
                staging = conn.execute("SELECT * FROM vrcx_import_events").fetchone()
                record = conn.execute("SELECT * FROM playback_records").fetchone()
                origin = conn.execute("SELECT * FROM playback_record_origins").fetchone()
                origin_json = json.loads(origin["origin_json"])

            self.assertEqual(stats.playback_records_changed, 1)
            self.assertEqual(staging["created_at"], "2026-05-17T07:30:10Z")
            self.assertEqual(record["played_at"], "2026-05-17T07:30:10Z")
            self.assertEqual(origin_json["original_played_at"], raw_created_at)
            self.assertEqual(origin_json["source_created_at"], raw_created_at)

    def test_vrcx_import_keeps_request_type_while_queued_self_deferred(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vrcx_path = root / "VRCX.sqlite3"
            app_path = root / "app.sqlite3"
            manifest_dir = root / "queued_self"
            manifest_dir.mkdir()
            with closing(sqlite3.connect(vrcx_path)) as conn:
                conn.execute(
                    """
                    CREATE TABLE gamelog_video_play (
                        created_at TEXT,
                        video_url TEXT,
                        video_name TEXT,
                        video_id TEXT,
                        location TEXT,
                        display_name TEXT,
                        user_id TEXT
                    )
                    """
                )
                conn.execute(
                    "INSERT INTO gamelog_video_play VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        "2026-05-15T14:20:11.000Z",
                        "https://api.udon.dance/Api/Songs/play?id=3114",
                        "Song Name",
                        "",
                        "wrld_1",
                        "",
                        "",
                    ),
                )
                conn.commit()

            import_vrcx_database(vrcx_path, app_db_path=app_path)
            (manifest_dir / "playlist.md").write_text(
                "# 2026-05-15\n3114 Song Name\n",
                encoding="utf-8",
            )
            queued_stats = sync_queued_self_manifests(
                app_db_path=app_path,
                manifest_dir=manifest_dir,
                system_key=WANNA_SYSTEM_KEY,
                dance_day_boundary=LocalDanceDayBoundary.from_config(
                    {},
                    time_zone=timezone(timedelta(hours=8)),
                ),
            )
            reimport_stats = import_vrcx_database(vrcx_path, app_db_path=app_path)

            with connect_db(app_path) as conn:
                row = conn.execute(
                    "SELECT request_type FROM playback_records"
                ).fetchone()
                origins = conn.execute(
                    """
                    SELECT origin_source, origin_table, origin_json
                    FROM playback_record_origins
                    ORDER BY origin_source, origin_table
                    """
                ).fetchall()

            self.assertEqual(queued_stats.matched_entries, 1)
            self.assertEqual(queued_stats.existing_records_updated, 0)
            self.assertEqual(reimport_stats.playback_records_changed, 0)
            self.assertEqual(row["request_type"], "random")
            origin_sources = {origin["origin_source"] for origin in origins}
            self.assertEqual(origin_sources, {"vrcx_database"})

    def test_queued_self_uses_cli_system_for_bare_track_refs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "app.sqlite3"
            manifest_dir = root / "queued_self"
            manifest_dir.mkdir()
            with connect_db(db_path) as conn:
                ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "5038",
                    {"title": "Good Time", "artist": "Owl City"},
                )
                conn.commit()
            add_dance_event(
                system_key=WANNA_SYSTEM_KEY,
                external_id="5038",
                source="other",
                played_at="2026-04-17T20:30:00+08:00",
                event_source="manual",
                path=db_path,
            )
            (manifest_dir / "playlist.md").write_text(
                "# 2026-04-17\n5038 Good Time\n3114 Unmatched id\n",
                encoding="utf-8",
            )

            stats = sync_queued_self_manifests(
                app_db_path=db_path,
                manifest_dir=manifest_dir,
                system_key=WANNA_SYSTEM_KEY,
                dance_day_boundary=LocalDanceDayBoundary.from_config(
                    {},
                    time_zone=timezone(timedelta(hours=8)),
                ),
            )

            self.assertEqual(stats.entries_with_track_ref, 2)
            self.assertEqual(stats.entries_without_track_ref, 0)
            self.assertEqual(stats.matched_entries, 1)
            self.assertEqual(stats.unmatched_entries, 1)
            self.assertEqual(stats.existing_records_updated, 0)
            with connect_db(db_path) as conn:
                source = conn.execute("SELECT request_type FROM playback_records").fetchone()[0]
            self.assertEqual(source, "other")

    def test_queued_self_matches_aware_playback_by_local_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "app.sqlite3"
            manifest_dir = root / "queued_self"
            manifest_dir.mkdir()
            add_dance_event(
                system_key=WANNA_SYSTEM_KEY,
                external_id="5038",
                source="other",
                played_at="2026-05-18T00:22:59+08:00",
                event_source="manual",
                path=db_path,
            )
            (manifest_dir / "playlist.md").write_text(
                "# 2026-05-18\n5038 Good Time\n",
                encoding="utf-8",
            )

            stats = sync_queued_self_manifests(
                app_db_path=db_path,
                manifest_dir=manifest_dir,
                system_key=WANNA_SYSTEM_KEY,
                dance_day_boundary=LocalDanceDayBoundary.from_config(
                    {},
                    time_zone=timezone(timedelta(hours=8)),
                ),
            )

            with connect_db(db_path) as conn:
                row = conn.execute(
                    """
                    SELECT played_at, request_type
                    FROM playback_records
                    """
                ).fetchone()
                origins = conn.execute(
                    """
                    SELECT origin_source, origin_json
                    FROM playback_record_origins
                    ORDER BY origin_source
                    """
                ).fetchall()

            self.assertEqual(stats.matched_entries, 1)
            self.assertEqual(stats.existing_records_updated, 0)
            self.assertEqual(row["played_at"], "2026-05-17T16:22:59Z")
            self.assertEqual(row["request_type"], "other")
            origins_by_source = {origin["origin_source"]: origin for origin in origins}
            manual_json = json.loads(origins_by_source["manual_log"]["origin_json"])
            self.assertEqual(set(origins_by_source), {"manual_log"})
            self.assertEqual(
                manual_json["original_played_at"],
                "2026-05-18T00:22:59+08:00",
            )

    def test_queued_self_uses_dance_day_boundary_and_effective_acceptance(self):
        boundary = LocalDanceDayBoundary.from_config(
            {"dance_day_boundary_time": "03:00"},
            time_zone=timezone(timedelta(hours=8)),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "app.sqlite3"
            manifest_dir = root / "queued_self"
            manifest_dir.mkdir()
            add_dance_event(
                system_key=WANNA_SYSTEM_KEY,
                external_id="5038",
                source="other",
                played_at="2026-05-18T02:00:00+08:00",
                event_source="manual",
                path=db_path,
            )
            (manifest_dir / "playlist.md").write_text(
                "# 2026-05-17\n5038 Good Time\n",
                encoding="utf-8",
            )

            natural_day_stats = sync_queued_self_manifests(
                app_db_path=db_path,
                manifest_dir=manifest_dir,
                system_key=WANNA_SYSTEM_KEY,
                dance_day_boundary=LocalDanceDayBoundary.from_config(
                    {"dance_day_boundary_time": "00:00"},
                    time_zone=timezone(timedelta(hours=8)),
                ),
            )
            accepted_stats = sync_queued_self_manifests(
                app_db_path=db_path,
                manifest_dir=manifest_dir,
                system_key=WANNA_SYSTEM_KEY,
                dance_day_boundary=boundary,
            )

            with connect_db(db_path) as conn:
                playback_record_id = conn.execute(
                    "SELECT id FROM playback_records"
                ).fetchone()[0]
                set_manual_playback_decision(
                    conn,
                    playback_record_id,
                    EFFECTIVE_PLAYBACK_EXCLUDED,
                )
                conn.commit()

            excluded_stats = sync_queued_self_manifests(
                app_db_path=db_path,
                manifest_dir=manifest_dir,
                system_key=WANNA_SYSTEM_KEY,
                dance_day_boundary=boundary,
            )

            self.assertEqual(natural_day_stats.matched_entries, 0)
            self.assertEqual(accepted_stats.matched_entries, 1)
            self.assertEqual(excluded_stats.matched_entries, 0)

    def test_archive_existing_data_keeps_config_and_manifest_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "queued_self").mkdir()
            (root / "queued_self" / "playlist.md").write_text("keep", encoding="utf-8")
            (root / "local_config.json").write_text("{}", encoding="utf-8")
            for name in ("dance_trail.sqlite3", "songs.csv", "wanna_songs.json"):
                (root / name).write_text(name, encoding="utf-8")

            stats = archive_existing_data(root)

            self.assertTrue((root / "local_config.json").exists())
            self.assertTrue((root / "queued_self" / "playlist.md").exists())
            self.assertFalse((root / "dance_trail.sqlite3").exists())
            self.assertFalse((root / "songs.csv").exists())
            self.assertEqual(len(stats.archived), 3)
            self.assertTrue((stats.archive_dir / "dance_trail.sqlite3").exists())

    def test_playback_record_upsert_preserves_existing_requester_user_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "app.sqlite3"
            with connect_db(db_path) as conn:
                track_id = ensure_dance_track(conn, WANNA_SYSTEM_KEY, "3114")
                base = dict(
                    played_at="2026.05.17 15:30:00",
                    original_played_at="2026.05.17 15:30:00",
                    dance_track_id=track_id,
                    dance_system_key=WANNA_SYSTEM_KEY,
                    dance_external_id="3114",
                    evidence_source="vrc_log_live",
                    source_table=WATCHER_PLAYBACK_SOURCE_TABLE,
                    source_row_id=0,
                    source_event_key="watcher-event-key",
                    request_type="player",
                    default_acceptance_status="pending",
                    observation_status="pending",
                    observation_reason=WATCHER_PENDING_REASON,
                    requester_display_name="Alice",
                    origin_source="vrchat_log",
                )
                upsert_evidence_record(
                    conn,
                    make_test_playback_record(
                        **base,
                        video_name="Original Title",
                        requester_user_id="usr_alice",
                        origin_json={
                            "watcher_playback_event": {
                                "event_key": "watcher-event-key",
                                "video_name": "Original Title",
                                "requester_user_id": "usr_alice",
                                "requester_user_id_source": "active",
                            }
                        },
                    ),
                )
                upsert_evidence_record(
                    conn,
                    make_test_playback_record(
                        **base,
                        video_name="Updated Title",
                        requester_user_id="usr_bob",
                        origin_json={
                            "watcher_playback_event": {
                                "event_key": "watcher-event-key",
                                "video_name": "Updated Title",
                                "requester_user_id": "usr_bob",
                                "requester_user_id_source": "expired",
                            }
                        },
                    ),
                )
                upsert_evidence_record(
                    conn,
                    make_test_playback_record(
                        **base,
                        video_name="Final Title",
                        requester_user_id=None,
                        origin_json={
                            "watcher_playback_event": {
                                "event_key": "watcher-event-key",
                                "video_name": "Final Title",
                                "requester_user_id": None,
                                "requester_user_id_source": None,
                            }
                        },
                    ),
                )
                conn.commit()
                row = conn.execute("SELECT * FROM playback_records").fetchone()
                origin = conn.execute("SELECT * FROM playback_record_origins").fetchone()

            origin_json = json.loads(origin["origin_json"])
            provenance_event = origin_json["watcher_playback_event"]
            self.assertEqual(row["video_name"], "Final Title")
            self.assertEqual(row["requester_user_id"], "usr_alice")
            self.assertEqual(provenance_event["video_name"], "Final Title")
            self.assertEqual(provenance_event["requester_user_id"], "usr_alice")
            self.assertEqual(provenance_event["requester_user_id_source"], "active")

    def test_archive_existing_data_archives_custom_app_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            custom_db = root / "runtime" / "custom.sqlite3"
            custom_db.parent.mkdir()
            custom_db.write_text("db", encoding="utf-8")
            Path(str(custom_db) + "-wal").write_text("wal", encoding="utf-8")

            stats = archive_existing_data(root, app_db_path=custom_db)

            self.assertFalse(custom_db.exists())
            self.assertFalse(Path(str(custom_db) + "-wal").exists())
            self.assertTrue((stats.archive_dir / "custom.sqlite3").exists())
            self.assertTrue((stats.archive_dir / "custom.sqlite3-wal").exists())


if __name__ == "__main__":
    unittest.main()
