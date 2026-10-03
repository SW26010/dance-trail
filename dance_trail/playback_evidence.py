"""Local Playback Evidence read model.

`playback_records` is the normalized Local Playback Evidence root. Legacy
tables may still exist for compatibility and diagnosis, but ordinary Timeline,
Insights, day, and recommendation reads should come through this module.
"""

from __future__ import annotations

import sqlite3

from dance_trail.time_utils import SQLITE_UTC_NOW
from dance_trail.playback_projection import (
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


def init_playback_records_schema(conn: sqlite3.Connection) -> None:
    """Create the Local Playback Evidence v1 schema."""
    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS playback_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            evidence_key TEXT NOT NULL UNIQUE,
            evidence_source TEXT NOT NULL,
            played_at TEXT NOT NULL,
            dance_track_id INTEGER,
            dance_system_key TEXT NOT NULL,
            dance_external_id TEXT NOT NULL,
            request_type TEXT,
            requester_display_name TEXT,
            requester_user_id TEXT,
            default_acceptance_status TEXT NOT NULL,
            observation_status TEXT,
            observation_reason TEXT,
            observed_end_at TEXT,
            video_url TEXT,
            video_name TEXT,
            created_at TEXT NOT NULL DEFAULT ({SQLITE_UTC_NOW}),
            updated_at TEXT NOT NULL DEFAULT ({SQLITE_UTC_NOW}),
            FOREIGN KEY(dance_track_id) REFERENCES dance_tracks(id)
        );

        CREATE TABLE IF NOT EXISTS playback_record_origins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            playback_record_id INTEGER NOT NULL,
            origin_key TEXT NOT NULL UNIQUE,
            origin_source TEXT NOT NULL,
            origin_root_key TEXT,
            origin_root_path TEXT,
            origin_table TEXT,
            origin_row_id INTEGER,
            origin_event_key TEXT,
            ingest_run_id TEXT,
            origin_json TEXT NOT NULL DEFAULT '{{}}',
            created_at TEXT NOT NULL DEFAULT ({SQLITE_UTC_NOW}),
            FOREIGN KEY(playback_record_id) REFERENCES playback_records(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_playback_records_played_at
            ON playback_records(played_at);
        CREATE INDEX IF NOT EXISTS idx_playback_records_identity
            ON playback_records(dance_system_key, dance_external_id);
        CREATE INDEX IF NOT EXISTS idx_playback_records_acceptance
            ON playback_records(default_acceptance_status);
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
                    WHEN pr.dance_track_id IS NULL
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
        where.append("pr.evidence_source = ?")
        params.append("vrc_log_live")
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
                pr.request_type AS source_type,
                pr.requester_display_name AS source_display_name,
                pr.requester_display_name,
                pr.requester_user_id,
                pr.default_acceptance_status AS playback_status,
                pr.observation_reason AS status_reason,
                CASE WHEN pr.dance_track_id IS NULL THEN 1 ELSE 0 END AS catalog_attention,
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
                NULLIF(pr.request_type, ''),
                NULLIF(pr.evidence_source, ''),
                'unknown'
            )
        """


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None
