"""Local Playback Evidence read model.

`playback_records` is the v0 user-facing playback history root after the
legacy cleanup. Legacy tables may still exist for compatibility and diagnosis,
but ordinary Timeline, Insights, day, and recommendation reads should come
through this module.
"""

from __future__ import annotations

import sqlite3


PLAYBACK_STATUS_ACCEPTED = "accepted"
PLAYBACK_STATUS_NEEDS_ATTENTION = "needs_attention"
LIVE_PLAYBACK_SOURCE_TABLE = "live_playback_events"


def init_playback_records_schema(conn: sqlite3.Connection) -> None:
    """Create the Local Playback Evidence v0 schema."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS playback_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cleanup_batch_id TEXT NOT NULL,
            played_at TEXT NOT NULL,
            original_played_at TEXT NOT NULL,
            dance_track_id INTEGER,
            dance_system_key TEXT NOT NULL,
            dance_external_id TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            source_root_key TEXT NOT NULL,
            source_root_path TEXT NOT NULL,
            source_table TEXT NOT NULL,
            source_row_id INTEGER NOT NULL,
            source_event_key TEXT,
            source_fingerprint TEXT NOT NULL UNIQUE,
            playback_status TEXT NOT NULL,
            counts_in_history INTEGER NOT NULL DEFAULT 0,
            status_reason TEXT NOT NULL,
            source_priority INTEGER NOT NULL DEFAULT 0,
            confidence REAL,
            event_source TEXT,
            source_type TEXT,
            source_display_name TEXT,
            video_url TEXT,
            video_name TEXT,
            requester_display_name TEXT,
            requester_user_id TEXT,
            location TEXT,
            completion_status TEXT,
            completion_reason TEXT,
            catalog_status TEXT NOT NULL DEFAULT 'existing',
            catalog_attention INTEGER NOT NULL DEFAULT 0,
            provenance_json TEXT NOT NULL,
            imported_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(dance_track_id) REFERENCES dance_tracks(id)
        );

        CREATE INDEX IF NOT EXISTS idx_playback_records_played_at
            ON playback_records(played_at);
        CREATE INDEX IF NOT EXISTS idx_playback_records_track
            ON playback_records(dance_track_id);
        CREATE INDEX IF NOT EXISTS idx_playback_records_identity
            ON playback_records(dance_system_key, dance_external_id);
        CREATE INDEX IF NOT EXISTS idx_playback_records_status
            ON playback_records(playback_status, counts_in_history);
        CREATE INDEX IF NOT EXISTS idx_playback_records_source
            ON playback_records(source_kind, source_root_key);
        """
    )


def count_playback_records(conn: sqlite3.Connection) -> dict[str, int]:
    """Return aggregate Local Playback Evidence counts."""
    if not _table_exists(conn, "playback_records"):
        return {
            "playback_records": 0,
            "accepted_playback_records": 0,
            "needs_attention_playback_records": 0,
            "catalog_attention_playback_records": 0,
        }
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(
                CASE
                    WHEN playback_status = ? AND counts_in_history = 1 THEN 1
                    ELSE 0
                END
            ), 0) AS accepted,
            COALESCE(SUM(
                CASE
                    WHEN playback_status = ? THEN 1
                    ELSE 0
                END
            ), 0) AS needs_attention,
            COALESCE(SUM(
                CASE
                    WHEN catalog_attention = 1 THEN 1
                    ELSE 0
                END
            ), 0) AS catalog_attention
        FROM playback_records
        """,
        (PLAYBACK_STATUS_ACCEPTED, PLAYBACK_STATUS_NEEDS_ATTENTION),
    ).fetchone()
    return {
        "playback_records": int(row["total"]),
        "accepted_playback_records": int(row["accepted"]),
        "needs_attention_playback_records": int(row["needs_attention"]),
        "catalog_attention_playback_records": int(row["catalog_attention"]),
    }


def read_attention_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Return counts for playback records that need review attention."""
    counts = count_playback_records(conn)
    return {
        "needs_attention": counts["needs_attention_playback_records"],
        "catalog_attention": counts["catalog_attention_playback_records"],
    }


def read_recent_playback_records(
    conn: sqlite3.Connection,
    *,
    limit: int = 8,
) -> list[dict]:
    """Return recent accepted playback records for the Home snapshot."""
    if not _table_exists(conn, "playback_records"):
        return []
    rows = conn.execute(
        f"""
        SELECT
            pr.id,
            pr.played_at,
            {_source_label_sql()} AS source,
            pr.video_name,
            pr.dance_external_id AS external_id,
            dt.title,
            dt.artist,
            dt.dancer
        FROM playback_records pr
        LEFT JOIN dance_tracks dt ON dt.id = pr.dance_track_id
        WHERE {_accepted_history_sql()}
        ORDER BY pr.played_at DESC, pr.id DESC
        LIMIT ?
        """,
        (PLAYBACK_STATUS_ACCEPTED, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def read_daily_playback_rows(
    conn: sqlite3.Connection,
    *,
    source: str = "accepted",
) -> list[dict]:
    """Return playback rows for day filtering and Timeline rendering."""
    if not _table_exists(conn, "playback_records"):
        return []
    where = [_accepted_history_sql()]
    params: list[object] = [PLAYBACK_STATUS_ACCEPTED]
    if source == "live":
        where.append("pr.source_table = ?")
        params.append(LIVE_PLAYBACK_SOURCE_TABLE)
    rows = conn.execute(
        f"""
        SELECT
            pr.id AS event_id,
            pr.played_at,
            pr.video_name,
            pr.dance_external_id AS external_id,
            COALESCE(dt.title, pr.video_name) AS title,
            dt.artist,
            dt.dancer,
            dt.group_name,
            dt.major,
            pr.playback_status,
            pr.status_reason,
            pr.catalog_attention
        FROM playback_records pr
        LEFT JOIN dance_tracks dt ON dt.id = pr.dance_track_id
        WHERE {" AND ".join(where)}
        ORDER BY pr.played_at, pr.id
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def read_accepted_playback_history(conn: sqlite3.Connection) -> list[dict]:
    """Return accepted history in the shape recommendation code expects."""
    if not _table_exists(conn, "playback_records"):
        return []
    rows = conn.execute(
        f"""
        SELECT
            pr.played_at AS timestamp,
            pr.dance_track_id,
            COALESCE(ds.key, pr.dance_system_key) AS system_key,
            COALESCE(dt.external_id, pr.dance_external_id) AS external_id,
            {_source_label_sql()} AS source,
            '' AS note
        FROM playback_records pr
        LEFT JOIN dance_tracks dt ON dt.id = pr.dance_track_id
        LEFT JOIN dance_systems ds ON ds.id = dt.system_id
        WHERE {_accepted_history_sql()}
            AND pr.dance_track_id IS NOT NULL
        ORDER BY pr.played_at, pr.id
        """,
        (PLAYBACK_STATUS_ACCEPTED,),
    ).fetchall()
    return [dict(row) for row in rows]


def read_source_distribution(conn: sqlite3.Connection) -> list[dict]:
    """Return accepted-history source distribution."""
    if not _table_exists(conn, "playback_records"):
        return []
    rows = conn.execute(
        f"""
        SELECT {_source_label_sql()} AS source, COUNT(*) AS count
        FROM playback_records pr
        WHERE {_accepted_history_sql()}
        GROUP BY source
        ORDER BY count DESC, source
        """,
        (PLAYBACK_STATUS_ACCEPTED,),
    ).fetchall()
    return [dict(row) for row in rows]


def read_top_tracks(conn: sqlite3.Connection, *, limit: int = 10) -> list[dict]:
    """Return top accepted playback tracks."""
    if not _table_exists(conn, "playback_records"):
        return []
    rows = conn.execute(
        f"""
        SELECT
            COALESCE(dt.external_id, pr.dance_external_id) AS external_id,
            COALESCE(dt.title, pr.video_name) AS title,
            dt.artist,
            COUNT(*) AS count
        FROM playback_records pr
        LEFT JOIN dance_tracks dt ON dt.id = pr.dance_track_id
        WHERE {_accepted_history_sql()}
        GROUP BY COALESCE(pr.dance_track_id, pr.dance_system_key || ':' || pr.dance_external_id)
        ORDER BY count DESC, MAX(pr.played_at) DESC
        LIMIT ?
        """,
        (PLAYBACK_STATUS_ACCEPTED, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def _accepted_history_sql() -> str:
    return "pr.playback_status = ? AND pr.counts_in_history = 1"


def _source_label_sql() -> str:
    return """
            COALESCE(
                NULLIF(pr.source_type, ''),
                NULLIF(pr.event_source, ''),
                NULLIF(pr.source_kind, ''),
                'unknown'
            )
        """


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None
