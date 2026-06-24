"""Local Playback Evidence read model.

`playback_records` is the v0 user-facing playback history root after the
legacy cleanup. Legacy tables may still exist for compatibility and diagnosis,
but ordinary Timeline, Insights, day, and recommendation reads should come
through this module.
"""

from __future__ import annotations

import sqlite3

from dancing_log.time_utils import SQLITE_UTC_NOW
from dancing_log.playback_projection import (
    EFFECTIVE_PLAYBACK_ACCEPTED,
    EFFECTIVE_PLAYBACK_EXCLUDED,
    EFFECTIVE_PLAYBACK_NEEDS_ATTENTION,
    EFFECTIVE_PLAYBACK_PENDING,
    accepted_playback_where_sql,
    effective_playback_status_sql,
    playback_projection_join_sql,
    playback_projection_select_sql,
)

PLAYBACK_STATUS_ACCEPTED = EFFECTIVE_PLAYBACK_ACCEPTED
PLAYBACK_STATUS_NEEDS_ATTENTION = EFFECTIVE_PLAYBACK_NEEDS_ATTENTION
PLAYBACK_STATUS_PENDING = EFFECTIVE_PLAYBACK_PENDING
LIVE_PLAYBACK_SOURCE_TABLE = "live_playback_events"
LIVE_WATCHER_SOURCE_KIND = "live_watcher"


def init_playback_records_schema(conn: sqlite3.Connection) -> None:
    """Create the Local Playback Evidence v0 schema."""
    conn.executescript(
        f"""
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
            imported_at TEXT NOT NULL DEFAULT ({SQLITE_UTC_NOW}),
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
    projection_join = playback_projection_join_sql(conn)
    effective_status = effective_playback_status_sql(conn)
    row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(
                CASE
                    WHEN {effective_status} = '{EFFECTIVE_PLAYBACK_ACCEPTED}' THEN 1
                    ELSE 0
                END
            ), 0) AS accepted,
            COALESCE(SUM(
                CASE
                    WHEN {effective_status} = '{EFFECTIVE_PLAYBACK_NEEDS_ATTENTION}' THEN 1
                    ELSE 0
                END
            ), 0) AS needs_attention,
            COALESCE(SUM(
                CASE
                    WHEN pr.catalog_attention = 1
                        AND {effective_status} != '{EFFECTIVE_PLAYBACK_EXCLUDED}'
                        THEN 1
                    ELSE 0
                END
            ), 0) AS catalog_attention
        FROM playback_records pr
        {projection_join}
        """
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
    projection_join = playback_projection_join_sql(conn)
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
        {projection_join}
        LEFT JOIN dance_tracks dt ON dt.id = pr.dance_track_id
        WHERE {accepted_playback_where_sql(conn)}
        ORDER BY pr.played_at DESC, pr.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def read_daily_playback_rows(
    conn: sqlite3.Connection,
    *,
    source: str = "accepted",
) -> list[dict]:
    """Return effective accepted playback rows for day report rendering."""
    return _read_projected_playback_rows(
        conn,
        source=source,
        effective_status=EFFECTIVE_PLAYBACK_ACCEPTED,
    )


def read_timeline_playback_rows(
    conn: sqlite3.Connection,
    *,
    source: str = "all",
) -> list[dict]:
    """Return playback rows with effective status for Timeline review."""
    return _read_projected_playback_rows(
        conn,
        source=source,
        effective_status=None,
    )


def _read_projected_playback_rows(
    conn: sqlite3.Connection,
    *,
    source: str,
    effective_status: str | None,
) -> list[dict]:
    if not _table_exists(conn, "playback_records"):
        return []
    projection_join = playback_projection_join_sql(conn)
    where: list[str] = []
    params: list[object] = []
    if effective_status == EFFECTIVE_PLAYBACK_ACCEPTED:
        where.append(accepted_playback_where_sql(conn))
    elif effective_status is not None:
        where.append(f"{effective_playback_status_sql(conn)} = ?")
        params.append(effective_status)
    if source == "live":
        where.append("pr.source_kind = ?")
        params.append(LIVE_WATCHER_SOURCE_KIND)
    where_sql = " AND ".join(where) if where else "1 = 1"
    rows = [
        dict(row)
        for row in conn.execute(
            f"""
            SELECT
                pr.id AS event_id,
                pr.played_at,
                pr.video_name,
                pr.dance_external_id AS external_id,
                COALESCE(ds.key, pr.dance_system_key) AS dance_system_key,
                ds.name AS dance_system_name,
                COALESCE(dt.title, pr.video_name) AS title,
                dt.artist,
                dt.dancer,
                dt.group_name,
                dt.major,
                pr.source_type,
                pr.source_display_name,
                pr.requester_display_name,
                pr.requester_user_id,
                pr.playback_status,
                pr.status_reason,
                pr.catalog_attention,
                {playback_projection_select_sql(conn)}
            FROM playback_records pr
            {projection_join}
            LEFT JOIN dance_tracks dt ON dt.id = pr.dance_track_id
            LEFT JOIN dance_systems ds ON ds.id = dt.system_id
            WHERE {where_sql}
            ORDER BY pr.played_at, pr.id
            """,
            params,
        ).fetchall()
    ]
    return rows


def read_accepted_playback_history(conn: sqlite3.Connection) -> list[dict]:
    """Return accepted history in the shape recommendation code expects."""
    if not _table_exists(conn, "playback_records"):
        return []
    projection_join = playback_projection_join_sql(conn)
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
        {projection_join}
        LEFT JOIN dance_tracks dt ON dt.id = pr.dance_track_id
        LEFT JOIN dance_systems ds ON ds.id = dt.system_id
        WHERE {accepted_playback_where_sql(conn)}
            AND pr.dance_track_id IS NOT NULL
        ORDER BY pr.played_at, pr.id
        """
    ).fetchall()
    return [dict(row) for row in rows]


def read_source_distribution(conn: sqlite3.Connection) -> list[dict]:
    """Return accepted-history source distribution."""
    if not _table_exists(conn, "playback_records"):
        return []
    projection_join = playback_projection_join_sql(conn)
    rows = conn.execute(
        f"""
        SELECT {_source_label_sql()} AS source, COUNT(*) AS count
        FROM playback_records pr
        {projection_join}
        WHERE {accepted_playback_where_sql(conn)}
        GROUP BY source
        ORDER BY count DESC, source
        """
    ).fetchall()
    return [dict(row) for row in rows]


def read_top_tracks(conn: sqlite3.Connection, *, limit: int = 10) -> list[dict]:
    """Return top accepted playback tracks."""
    if not _table_exists(conn, "playback_records"):
        return []
    projection_join = playback_projection_join_sql(conn)
    rows = conn.execute(
        f"""
        SELECT
            COALESCE(dt.external_id, pr.dance_external_id) AS external_id,
            COALESCE(dt.title, pr.video_name) AS title,
            dt.artist,
            COUNT(*) AS count
        FROM playback_records pr
        {projection_join}
        LEFT JOIN dance_tracks dt ON dt.id = pr.dance_track_id
        WHERE {accepted_playback_where_sql(conn)}
        GROUP BY COALESCE(pr.dance_track_id, pr.dance_system_key || ':' || pr.dance_external_id)
        ORDER BY count DESC, MAX(pr.played_at) DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


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
