"""SQLite storage for dancing-log.

SQLite is the primary local store. CSV should be treated as an import/export
artifact, not as runtime state.
"""

from __future__ import annotations

from pathlib import Path
import hashlib
import json
import re
import sqlite3
import unicodedata

from dancing_log.app_paths import AppPaths
from dancing_log.live_playback_settlement import is_live_playback_promotable
from dancing_log.playback_evidence import (
    PLAYBACK_STATUS_NEEDS_ATTENTION,
    PLAYBACK_STATUS_PENDING,
    init_playback_records_schema,
    read_accepted_playback_history,
)
from dancing_log.playback_projection import init_manual_playback_decision_schema
from dancing_log.playback_record_writer import PlaybackRecordWrite, upsert_playback_record
from dancing_log.watcher_playback_materializer import (
    WATCHER_INTERRUPTED_UNEXPECTEDLY_REASON,
    WATCHER_PENDING_REASON,
    WATCHER_PLAYBACK_SOURCE_KIND,
    WATCHER_PLAYBACK_SOURCE_TABLE,
)

WANNA_SYSTEM_KEY = "wannadance"
WANNA_SYSTEM_NAME = "WannaDance"


class ClosingConnection(sqlite3.Connection):
    """SQLite connection that closes when used as a context manager."""

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        suppress = super().__exit__(exc_type, exc_value, traceback)
        self.close()
        return suppress


def connect_db(path: Path | str | None = None) -> sqlite3.Connection:
    """Open the local app database and ensure the schema exists."""
    db_path = Path(path) if path is not None else AppPaths.from_root().db_file
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, factory=ClosingConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create the current multi-system dance-track schema."""
    _assert_not_legacy_schema(conn)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS dance_systems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS dance_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            system_id INTEGER NOT NULL,
            external_id TEXT NOT NULL,
            title TEXT,
            artist TEXT,
            dancer TEXT,
            player_count INTEGER,
            group_name TEXT,
            major TEXT,
            favorite INTEGER NOT NULL DEFAULT 0,
            want_to_learn INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(system_id) REFERENCES dance_systems(id),
            UNIQUE(system_id, external_id)
        );

        CREATE TABLE IF NOT EXISTS wannadance_songs (
            dance_track_id INTEGER PRIMARY KEY,
            wanna_id INTEGER NOT NULL UNIQUE,
            cache_category INTEGER,
            cache_title TEXT,
            cache_title_spell TEXT,
            cache_player_index INTEGER,
            cache_volume REAL,
            cache_start_seconds REAL,
            cache_end_seconds REAL,
            cache_flip INTEGER,
            cache_skip_random INTEGER,
            cache_checksum TEXT,
            cache_url TEXT,
            cache_url_for_quest TEXT,
            local_video_path TEXT,
            local_metadata_path TEXT,
            local_download_path TEXT,
            cache_updated_at TEXT,
            FOREIGN KEY(dance_track_id) REFERENCES dance_tracks(id)
        );

        CREATE TABLE IF NOT EXISTS music_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            artist TEXT,
            normalized_title TEXT NOT NULL,
            normalized_artist TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(normalized_title, normalized_artist)
        );

        CREATE TABLE IF NOT EXISTS dance_track_music_links (
            dance_track_id INTEGER NOT NULL,
            music_track_id INTEGER NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0,
            match_method TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY(dance_track_id, music_track_id),
            FOREIGN KEY(dance_track_id) REFERENCES dance_tracks(id),
            FOREIGN KEY(music_track_id) REFERENCES music_tracks(id)
        );

        CREATE TABLE IF NOT EXISTS dance_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            played_at TEXT NOT NULL,
            dance_track_id INTEGER,
            source TEXT NOT NULL DEFAULT 'unknown',
            confidence REAL NOT NULL DEFAULT 0.5,
            event_source TEXT NOT NULL,
            event_key TEXT NOT NULL UNIQUE,
            video_url TEXT,
            video_name TEXT,
            requester_display_name TEXT,
            requester_user_id TEXT,
            location TEXT,
            note TEXT,
            recording_id INTEGER,
            recording_offset_seconds REAL,
            imported_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(dance_track_id) REFERENCES dance_tracks(id)
        );

        CREATE TABLE IF NOT EXISTS vrcx_import_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vrcx_rowid INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            video_url TEXT,
            video_name TEXT,
            video_id TEXT,
            location TEXT,
            display_name TEXT,
            user_id TEXT,
            parsed_system_id INTEGER,
            parsed_external_id TEXT,
            parsed_dance_track_id INTEGER,
            inferred_source TEXT NOT NULL DEFAULT 'unknown',
            confidence REAL NOT NULL DEFAULT 0.5,
            event_key TEXT NOT NULL UNIQUE,
            imported_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(parsed_system_id) REFERENCES dance_systems(id),
            FOREIGN KEY(parsed_dance_track_id) REFERENCES dance_tracks(id)
        );

        CREATE TABLE IF NOT EXISTS live_playback_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_key TEXT NOT NULL UNIQUE,
            session_id TEXT NOT NULL,
            playback_event_key TEXT NOT NULL,
            canonical_key TEXT,
            first_seen_at TEXT,
            request_at TEXT,
            load_started_at TEXT,
            resolve_attempt_at TEXT,
            resolved_at TEXT,
            video_loaded_at TEXT,
            expected_ready_at TEXT,
            last_seen_at TEXT,
            actual_play_at TEXT,
            actual_play_signal_at TEXT,
            actual_play_offset_seconds REAL,
            actual_play_method TEXT,
            on_video_start_at TEXT,
            synced_play_at TEXT,
            observed_mid_play INTEGER NOT NULL DEFAULT 0,
            elapsed_at_first_seen_seconds REAL,
            delay_to_actual_seconds REAL,
            load_to_actual_seconds REAL,
            request_to_resolve_seconds REAL,
            video_url TEXT,
            routed_url TEXT,
            resolved_url TEXT,
            dance_system_key TEXT,
            dance_external_id TEXT,
            url_kind TEXT,
            video_name TEXT,
            video_id TEXT,
            display_name TEXT,
            requester_marker TEXT,
            source_hint TEXT,
            source_type TEXT,
            source_display_name TEXT,
            world_parser TEXT,
            duration_seconds REAL,
            duration_source TEXT,
            load_seconds REAL,
            wait_seconds REAL,
            source_file TEXT,
            first_line_number INTEGER,
            last_line_number INTEGER,
            signal_count INTEGER NOT NULL DEFAULT 0,
            parser_names_json TEXT NOT NULL DEFAULT '[]',
            raw_event_types_json TEXT NOT NULL DEFAULT '[]',
            event_json TEXT NOT NULL DEFAULT '{}',
            completion_status TEXT NOT NULL DEFAULT 'pending',
            completion_reason TEXT,
            completed_at TEXT,
            interrupted_at TEXT,
            played_seconds REAL,
            required_played_seconds REAL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            promoted_dance_event_id INTEGER,
            promoted_playback_record_id INTEGER,
            promoted_at TEXT,
            FOREIGN KEY(promoted_dance_event_id) REFERENCES dance_events(id),
            FOREIGN KEY(promoted_playback_record_id) REFERENCES playback_records(id)
        );

        CREATE INDEX IF NOT EXISTS idx_dance_tracks_system_external
            ON dance_tracks(system_id, external_id);
        CREATE INDEX IF NOT EXISTS idx_dance_events_played_at
            ON dance_events(played_at);
        CREATE INDEX IF NOT EXISTS idx_dance_events_dance_track_id
            ON dance_events(dance_track_id);
        CREATE INDEX IF NOT EXISTS idx_vrcx_import_events_track
            ON vrcx_import_events(parsed_dance_track_id);
        CREATE INDEX IF NOT EXISTS idx_live_playback_events_session
            ON live_playback_events(session_id, first_seen_at);
        CREATE INDEX IF NOT EXISTS idx_live_playback_events_actual_play
            ON live_playback_events(actual_play_at);
        CREATE INDEX IF NOT EXISTS idx_live_playback_events_completion
            ON live_playback_events(completion_status);
        """
    )
    init_playback_records_schema(conn)
    init_manual_playback_decision_schema(conn)
    _ensure_live_playback_columns(conn)
    ensure_dance_system(conn, WANNA_SYSTEM_KEY, WANNA_SYSTEM_NAME)
    conn.commit()


def _assert_not_legacy_schema(conn: sqlite3.Connection) -> None:
    table_names = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    if "songs" in table_names:
        raise RuntimeError(
            "Legacy database schema detected. Run "
            "`uv run python main.py rebuild-data --archive-existing` "
            "to archive old data and create the new schema."
        )
    if "dance_events" in table_names:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(dance_events)").fetchall()
        }
        if "song_id" in columns and "dance_track_id" not in columns:
            raise RuntimeError(
                "Legacy dance_events schema detected. Run "
                "`uv run python main.py rebuild-data --archive-existing` first."
            )


def ensure_dance_system(conn: sqlite3.Connection, key: str, name: str) -> int:
    """Create or return a dance system row."""
    normalized_key = key.strip().lower()
    if not normalized_key:
        raise ValueError("system key must not be empty")
    display_name = name.strip() or normalized_key
    conn.execute(
        """
        INSERT INTO dance_systems (key, name)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET
            name = excluded.name
        """,
        (normalized_key, display_name),
    )
    row = conn.execute(
        "SELECT id FROM dance_systems WHERE key = ?",
        (normalized_key,),
    ).fetchone()
    return int(row["id"])


def ensure_dance_track(
    conn: sqlite3.Connection,
    system_key: str,
    external_id: object,
    metadata: dict | None = None,
) -> int:
    """Create or return a dance track row for a system-specific external id."""
    system_id = ensure_dance_system(conn, system_key, _system_display_name(system_key))
    external_id_text = _external_id_text(external_id)
    metadata = metadata or {}
    conn.execute(
        """
        INSERT INTO dance_tracks (
            system_id,
            external_id,
            title,
            artist,
            dancer,
            player_count,
            group_name,
            major
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(system_id, external_id) DO UPDATE SET
            title = COALESCE(NULLIF(excluded.title, ''), dance_tracks.title),
            artist = COALESCE(NULLIF(excluded.artist, ''), dance_tracks.artist),
            dancer = COALESCE(NULLIF(excluded.dancer, ''), dance_tracks.dancer),
            player_count = COALESCE(excluded.player_count, dance_tracks.player_count),
            group_name = COALESCE(NULLIF(excluded.group_name, ''), dance_tracks.group_name),
            major = COALESCE(NULLIF(excluded.major, ''), dance_tracks.major),
            updated_at = datetime('now')
        """,
        (
            system_id,
            external_id_text,
            metadata.get("title") or metadata.get("name"),
            metadata.get("artist"),
            metadata.get("dancer"),
            metadata.get("player_count"),
            metadata.get("group") or metadata.get("group_name"),
            metadata.get("major"),
        ),
    )
    row = conn.execute(
        """
        SELECT id
        FROM dance_tracks
        WHERE system_id = ? AND external_id = ?
        """,
        (system_id, external_id_text),
    ).fetchone()
    return int(row["id"])


def get_dance_track(
    system_key: str,
    external_id: object,
    path: Path | str | None = None,
) -> dict | None:
    """Return one dance track by system key and external id."""
    with connect_db(path) as conn:
        return _get_dance_track(conn, system_key, external_id)


def _get_dance_track(
    conn: sqlite3.Connection,
    system_key: str,
    external_id: object,
) -> dict | None:
    row = conn.execute(
        """
        SELECT
            dt.id,
            ds.key AS system_key,
            ds.name AS system_name,
            dt.external_id,
            dt.title,
            dt.artist,
            dt.dancer,
            dt.player_count,
            dt.group_name AS "group",
            dt.major,
            dt.favorite,
            dt.want_to_learn
        FROM dance_tracks dt
        JOIN dance_systems ds ON ds.id = dt.system_id
        WHERE ds.key = ? AND dt.external_id = ?
        """,
        (system_key.strip().lower(), _external_id_text(external_id)),
    ).fetchone()
    return dict(row) if row else None


def load_dance_tracks(path: Path | str | None = None) -> list[dict]:
    """Load dance tracks in the shape expected by recommendation code."""
    with connect_db(path) as conn:
        rows = conn.execute(
            """
            SELECT
                dt.id,
                ds.key AS system_key,
                ds.name AS system_name,
                dt.external_id,
                dt.title,
                dt.artist,
                dt.dancer,
                dt.player_count,
                dt.group_name AS "group",
                dt.major,
                dt.favorite,
                dt.want_to_learn
            FROM dance_tracks dt
            JOIN dance_systems ds ON ds.id = dt.system_id
            ORDER BY ds.key, CAST(dt.external_id AS INTEGER), dt.external_id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def load_dance_log(path: Path | str | None = None) -> list[dict]:
    """Load accepted Local Playback Evidence for recommendation/runtime reads."""
    with connect_db(path) as conn:
        return read_accepted_playback_history(conn)


def add_dance_event(
    *,
    system_key: str,
    external_id: object,
    source: str,
    played_at: str,
    note: str = "",
    event_source: str = "manual",
    confidence: float = 1.0,
    video_url: str | None = None,
    video_name: str | None = None,
    requester_display_name: str | None = None,
    requester_user_id: str | None = None,
    location: str | None = None,
    path: Path | str | None = None,
) -> str:
    """Insert accepted Local Playback Evidence and return its source event key."""
    with connect_db(path) as conn:
        normalized_system_key = system_key.strip().lower()
        external_id_text = _external_id_text(external_id)
        dance_track_id = ensure_dance_track(conn, normalized_system_key, external_id_text)
        system_external = f"{normalized_system_key}:{external_id_text}"
        base_key = _event_key(event_source, played_at, system_external, source, note)
        event_key = _unique_event_key(conn, base_key)
        upsert_playback_record(
            conn,
            PlaybackRecordWrite(
                played_at=played_at,
                original_played_at=played_at,
                dance_track_id=dance_track_id,
                dance_system_key=normalized_system_key,
                dance_external_id=external_id_text,
                source_kind="manual_log",
                source_table="manual_log",
                source_row_id=0,
                source_event_key=event_key,
                status_reason=event_source,
                source_priority=40,
                confidence=confidence,
                event_source=event_source,
                source_type=source,
                video_url=video_url,
                video_name=video_name,
                requester_display_name=requester_display_name,
                requester_user_id=requester_user_id,
                location=location,
                provenance={
                    "manual_log": {
                        "event_key": event_key,
                        "played_at": played_at,
                        "system_key": normalized_system_key,
                        "external_id": external_id_text,
                        "source": source,
                        "note": note,
                    }
                },
            ),
        )
        conn.commit()
        return event_key


def make_live_playback_event_key(session_id: str, playback_event_key: str) -> str:
    """Return the persistent SQLite key for one live playback occurrence."""
    return _event_key("live-vrc-log", session_id, playback_event_key)


def upsert_live_playback_event(
    conn: sqlite3.Connection,
    event: dict,
    *,
    session_id: str,
    event_key: str | None = None,
) -> int:
    """Insert or update the latest folded live playback state."""
    playback_event_key = str(event.get("event_key") or "")
    if not playback_event_key:
        raise ValueError("live playback event must include event_key")
    persistent_key = event_key or make_live_playback_event_key(session_id, playback_event_key)
    parser_names_json = _json_text(event.get("parser_names") or [])
    raw_event_types_json = _json_text(event.get("raw_event_types") or [])
    event_json = _json_text(event)

    conn.execute(
        """
        INSERT INTO live_playback_events (
            event_key,
            session_id,
            playback_event_key,
            canonical_key,
            first_seen_at,
            request_at,
            load_started_at,
            resolve_attempt_at,
            resolved_at,
            video_loaded_at,
            expected_ready_at,
            last_seen_at,
            actual_play_at,
            actual_play_signal_at,
            actual_play_offset_seconds,
            actual_play_method,
            on_video_start_at,
            synced_play_at,
            observed_mid_play,
            elapsed_at_first_seen_seconds,
            delay_to_actual_seconds,
            load_to_actual_seconds,
            request_to_resolve_seconds,
            video_url,
            routed_url,
            resolved_url,
            dance_system_key,
            dance_external_id,
            url_kind,
            video_name,
            video_id,
            display_name,
            requester_marker,
            source_hint,
            source_type,
            source_display_name,
            world_parser,
            duration_seconds,
            duration_source,
            load_seconds,
            wait_seconds,
            source_file,
            first_line_number,
            last_line_number,
            signal_count,
            parser_names_json,
            raw_event_types_json,
            event_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(event_key) DO UPDATE SET
            session_id = excluded.session_id,
            playback_event_key = excluded.playback_event_key,
            canonical_key = excluded.canonical_key,
            first_seen_at = excluded.first_seen_at,
            request_at = excluded.request_at,
            load_started_at = excluded.load_started_at,
            resolve_attempt_at = excluded.resolve_attempt_at,
            resolved_at = excluded.resolved_at,
            video_loaded_at = excluded.video_loaded_at,
            expected_ready_at = excluded.expected_ready_at,
            last_seen_at = excluded.last_seen_at,
            actual_play_at = excluded.actual_play_at,
            actual_play_signal_at = excluded.actual_play_signal_at,
            actual_play_offset_seconds = excluded.actual_play_offset_seconds,
            actual_play_method = excluded.actual_play_method,
            on_video_start_at = excluded.on_video_start_at,
            synced_play_at = excluded.synced_play_at,
            observed_mid_play = excluded.observed_mid_play,
            elapsed_at_first_seen_seconds = excluded.elapsed_at_first_seen_seconds,
            delay_to_actual_seconds = excluded.delay_to_actual_seconds,
            load_to_actual_seconds = excluded.load_to_actual_seconds,
            request_to_resolve_seconds = excluded.request_to_resolve_seconds,
            video_url = excluded.video_url,
            routed_url = excluded.routed_url,
            resolved_url = excluded.resolved_url,
            dance_system_key = excluded.dance_system_key,
            dance_external_id = excluded.dance_external_id,
            url_kind = excluded.url_kind,
            video_name = excluded.video_name,
            video_id = excluded.video_id,
            display_name = excluded.display_name,
            requester_marker = excluded.requester_marker,
            source_hint = excluded.source_hint,
            source_type = excluded.source_type,
            source_display_name = excluded.source_display_name,
            world_parser = excluded.world_parser,
            duration_seconds = excluded.duration_seconds,
            duration_source = excluded.duration_source,
            load_seconds = excluded.load_seconds,
            wait_seconds = excluded.wait_seconds,
            source_file = excluded.source_file,
            first_line_number = excluded.first_line_number,
            last_line_number = excluded.last_line_number,
            signal_count = excluded.signal_count,
            parser_names_json = excluded.parser_names_json,
            raw_event_types_json = excluded.raw_event_types_json,
            event_json = excluded.event_json,
            last_updated_at = datetime('now')
        """,
        (
            persistent_key,
            session_id,
            playback_event_key,
            event.get("canonical_key"),
            event.get("first_seen_at"),
            event.get("request_at"),
            event.get("load_started_at"),
            event.get("resolve_attempt_at"),
            event.get("resolved_at"),
            event.get("video_loaded_at"),
            event.get("expected_ready_at"),
            event.get("last_seen_at"),
            event.get("actual_play_at"),
            event.get("actual_play_signal_at"),
            event.get("actual_play_offset_seconds"),
            event.get("actual_play_method"),
            event.get("on_video_start_at"),
            event.get("synced_play_at"),
            _bool_int(event.get("observed_mid_play")),
            event.get("elapsed_at_first_seen_seconds"),
            event.get("delay_to_actual_seconds"),
            event.get("load_to_actual_seconds"),
            event.get("request_to_resolve_seconds"),
            event.get("video_url"),
            event.get("routed_url"),
            event.get("resolved_url"),
            event.get("dance_system_key"),
            event.get("dance_external_id"),
            event.get("url_kind"),
            event.get("video_name"),
            event.get("video_id"),
            event.get("display_name"),
            event.get("requester_marker"),
            event.get("source_hint"),
            event.get("source_type"),
            event.get("source_display_name"),
            event.get("world_parser"),
            event.get("duration_seconds"),
            event.get("duration_source"),
            event.get("load_seconds"),
            event.get("wait_seconds"),
            event.get("source_file"),
            event.get("first_line_number"),
            event.get("last_line_number"),
            event.get("signal_count") or 0,
            parser_names_json,
            raw_event_types_json,
            event_json,
        ),
    )
    row = conn.execute(
        "SELECT id FROM live_playback_events WHERE event_key = ?",
        (persistent_key,),
    ).fetchone()
    return int(row["id"])


def promote_live_playback_event(
    conn: sqlite3.Connection,
    event_key: str,
) -> int | None:
    """Promote one eligible live event into accepted Local Playback Evidence."""
    row = conn.execute(
        "SELECT * FROM live_playback_events WHERE event_key = ?",
        (event_key,),
    ).fetchone()
    if row is None:
        return None
    if row["promoted_playback_record_id"] is not None:
        return int(row["promoted_playback_record_id"])
    if not _live_event_is_promotable(row):
        return None

    dance_track_id = ensure_dance_track(
        conn,
        row["dance_system_key"],
        row["dance_external_id"],
        {"title": row["video_name"]},
    )
    display_name = row["source_display_name"] or row["display_name"]
    write_result = upsert_playback_record(
        conn,
        PlaybackRecordWrite(
            played_at=row["actual_play_at"],
            original_played_at=row["actual_play_at"],
            dance_track_id=dance_track_id,
            dance_system_key=row["dance_system_key"],
            dance_external_id=row["dance_external_id"],
            source_kind="live_watcher",
            source_table="live_playback_events",
            source_row_id=int(row["id"]),
            source_event_key=event_key,
            status_reason=row["completion_reason"] or "observed_completion_threshold",
            source_priority=30,
            confidence=1.0,
            event_source="vrc_log_live",
            source_type=row["source_type"],
            source_display_name=display_name,
            video_url=row["video_url"] or row["resolved_url"] or row["routed_url"],
            video_name=row["video_name"],
            requester_display_name=display_name,
            completion_status=row["completion_status"],
            completion_reason=row["completion_reason"],
            provenance={"live_playback_event": dict(row)},
        ),
    )
    conn.execute(
        """
        UPDATE live_playback_events
        SET promoted_playback_record_id = ?, promoted_at = COALESCE(promoted_at, datetime('now'))
        WHERE event_key = ?
        """,
        (write_result.playback_record_id, event_key),
    )
    return write_result.playback_record_id


def repair_stale_watcher_pending_records(conn: sqlite3.Connection) -> int:
    """Convert stale watcher pending records left by an ungraceful exit."""
    cursor = conn.execute(
        """
        UPDATE playback_records
        SET
            playback_status = ?,
            counts_in_history = 0,
            status_reason = ?,
            completion_status = 'interrupted',
            completion_reason = ?
        WHERE source_kind = ?
            AND source_table = ?
            AND playback_status = ?
            AND counts_in_history = 0
            AND status_reason = ?
        """,
        (
            PLAYBACK_STATUS_NEEDS_ATTENTION,
            WATCHER_INTERRUPTED_UNEXPECTEDLY_REASON,
            WATCHER_INTERRUPTED_UNEXPECTEDLY_REASON,
            WATCHER_PLAYBACK_SOURCE_KIND,
            WATCHER_PLAYBACK_SOURCE_TABLE,
            PLAYBACK_STATUS_PENDING,
            WATCHER_PENDING_REASON,
        ),
    )
    return int(cursor.rowcount or 0)


def mark_live_playback_event_completed(
    conn: sqlite3.Connection,
    event_key: str,
    *,
    completed_at: str,
    played_seconds: float,
    required_played_seconds: float,
    reason: str,
) -> bool:
    """Mark a live playback row as complete enough for strict promotion."""
    cursor = conn.execute(
        """
        UPDATE live_playback_events
        SET
            completion_status = 'completed',
            completion_reason = ?,
            completed_at = ?,
            interrupted_at = NULL,
            played_seconds = ?,
            required_played_seconds = ?,
            last_updated_at = datetime('now')
        WHERE event_key = ?
            AND completion_status = 'pending'
            AND promoted_playback_record_id IS NULL
        """,
        (
            reason,
            completed_at,
            round(float(played_seconds), 3),
            round(float(required_played_seconds), 3),
            event_key,
        ),
    )
    return cursor.rowcount > 0


def mark_live_playback_event_interrupted(
    conn: sqlite3.Connection,
    event_key: str,
    *,
    interrupted_at: str,
    played_seconds: float | None,
    required_played_seconds: float | None,
    reason: str,
) -> bool:
    """Mark a live playback row as ineligible for legacy promotion."""
    cursor = conn.execute(
        """
        UPDATE live_playback_events
        SET
            completion_status = 'interrupted',
            completion_reason = ?,
            interrupted_at = ?,
            played_seconds = ?,
            required_played_seconds = ?,
            last_updated_at = datetime('now')
        WHERE event_key = ?
            AND completion_status = 'pending'
            AND promoted_playback_record_id IS NULL
        """,
        (
            reason,
            interrupted_at,
            round(float(played_seconds), 3) if played_seconds is not None else None,
            round(float(required_played_seconds), 3) if required_played_seconds is not None else None,
            event_key,
        ),
    )
    return cursor.rowcount > 0


def load_recent_live_playback_events(
    path: Path | str | None = None,
    *,
    limit: int = 20,
) -> list[dict]:
    """Return recent live playback rows with decoded JSON fields."""
    with connect_db(path) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM live_playback_events
            ORDER BY COALESCE(actual_play_at, first_seen_at, last_updated_at) DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_live_row_to_dict(row) for row in rows]


def load_current_live_playback_event(path: Path | str | None = None) -> dict | None:
    """Return the newest live playback row, if one exists."""
    events = load_recent_live_playback_events(path, limit=1)
    return events[0] if events else None


def ensure_music_track(conn: sqlite3.Connection, title: str, artist: str | None) -> int:
    """Create or return a canonical music track row."""
    normalized_title = normalize_music_text(title)
    normalized_artist = normalize_music_text(artist or "")
    if not normalized_title:
        raise ValueError("music title must not be empty")
    conn.execute(
        """
        INSERT INTO music_tracks (
            title,
            artist,
            normalized_title,
            normalized_artist
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT(normalized_title, normalized_artist) DO UPDATE SET
            title = COALESCE(NULLIF(excluded.title, ''), music_tracks.title),
            artist = COALESCE(NULLIF(excluded.artist, ''), music_tracks.artist),
            updated_at = datetime('now')
        """,
        (title, artist or "", normalized_title, normalized_artist),
    )
    row = conn.execute(
        """
        SELECT id
        FROM music_tracks
        WHERE normalized_title = ? AND normalized_artist = ?
        """,
        (normalized_title, normalized_artist),
    ).fetchone()
    return int(row["id"])


def link_dance_track_to_music(
    conn: sqlite3.Connection,
    dance_track_id: int,
    music_track_id: int,
    *,
    confidence: float = 0.85,
    match_method: str = "title_artist_auto",
) -> None:
    """Create or update a dance-track to music-track link."""
    conn.execute(
        """
        INSERT INTO dance_track_music_links (
            dance_track_id,
            music_track_id,
            confidence,
            match_method
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT(dance_track_id, music_track_id) DO UPDATE SET
            confidence = excluded.confidence,
            match_method = excluded.match_method,
            updated_at = datetime('now')
        """,
        (dance_track_id, music_track_id, confidence, match_method),
    )


def normalize_music_text(value: str) -> str:
    """Normalize text for conservative title/artist matching."""
    normalized = unicodedata.normalize("NFKC", value or "")
    normalized = normalized.casefold()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _system_display_name(system_key: str) -> str:
    if system_key.strip().lower() == WANNA_SYSTEM_KEY:
        return WANNA_SYSTEM_NAME
    return system_key.strip()


def _external_id_text(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("external id must not be empty")
    return text


def _live_event_is_promotable(row: sqlite3.Row) -> bool:
    return is_live_playback_promotable(row)


def _live_row_to_dict(row: sqlite3.Row) -> dict:
    value = dict(row)
    value["observed_mid_play"] = bool(value.get("observed_mid_play"))
    value["parser_names"] = _json_list(value.pop("parser_names_json", "[]"))
    value["raw_event_types"] = _json_list(value.pop("raw_event_types_json", "[]"))
    value["event"] = _json_object(value.pop("event_json", "{}"))
    return value


def _json_text(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_list(value: str | None) -> list:
    parsed = _json_object(value or "[]")
    return parsed if isinstance(parsed, list) else []


def _json_object(value: str | None):
    try:
        return json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}


def _bool_int(value: object) -> int:
    return 1 if bool(value) else 0


def _ensure_live_playback_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(live_playback_events)").fetchall()
    }
    additions = {
        "last_seen_at": "TEXT",
        "completion_status": "TEXT NOT NULL DEFAULT 'pending'",
        "completion_reason": "TEXT",
        "completed_at": "TEXT",
        "interrupted_at": "TEXT",
        "played_seconds": "REAL",
        "required_played_seconds": "REAL",
        "duration_source": "TEXT",
        "promoted_playback_record_id": "INTEGER",
    }
    for column, definition in additions.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE live_playback_events ADD COLUMN {column} {definition}")


def _event_key(*parts: object) -> str:
    return hashlib.sha256(
        "\x1f".join(str(part or "") for part in parts).encode("utf-8")
    ).hexdigest()


def _unique_event_key(conn: sqlite3.Connection, base_key: str) -> str:
    event_key = base_key
    suffix = 2
    while (
        conn.execute(
            "SELECT 1 FROM dance_events WHERE event_key = ?",
            (event_key,),
        ).fetchone()
        or conn.execute(
            """
            SELECT 1
            FROM playback_records
            WHERE source_table = 'manual_log' AND source_event_key = ?
            """,
            (event_key,),
        ).fetchone()
    ):
        event_key = _event_key(base_key, suffix)
        suffix += 1
    return event_key
