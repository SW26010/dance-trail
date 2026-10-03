"""Effective playback acceptance projection.

Playback Evidence remains the immutable source record. This module projects
that evidence plus any active Manual Playback Decision into the user-facing
effective state consumed by Timeline, Insights, reports, and recommendations.
"""

from __future__ import annotations

import sqlite3

from dance_trail.time_utils import SQLITE_UTC_NOW

EFFECTIVE_PLAYBACK_ACCEPTED = "accepted"
EFFECTIVE_PLAYBACK_EXCLUDED = "excluded"
EFFECTIVE_PLAYBACK_NEEDS_ATTENTION = "needs_attention"
EFFECTIVE_PLAYBACK_PENDING = "pending"

MANUAL_PLAYBACK_DECISIONS_TABLE = "manual_playback_decisions"

_VALID_EFFECTIVE_STATUSES = {
    EFFECTIVE_PLAYBACK_ACCEPTED,
    EFFECTIVE_PLAYBACK_EXCLUDED,
    EFFECTIVE_PLAYBACK_NEEDS_ATTENTION,
}


def init_manual_playback_decision_schema(conn: sqlite3.Connection) -> None:
    """Create the reversible Manual Playback Decision overlay schema."""
    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS manual_playback_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            playback_record_id INTEGER NOT NULL,
            decision_status TEXT NOT NULL CHECK (
                decision_status IN ('accepted', 'excluded', 'needs_attention')
            ),
            decision_reason TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            decided_at TEXT NOT NULL DEFAULT ({SQLITE_UTC_NOW}),
            updated_at TEXT NOT NULL DEFAULT ({SQLITE_UTC_NOW}),
            FOREIGN KEY(playback_record_id) REFERENCES playback_records(id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_manual_playback_decisions_active
            ON manual_playback_decisions(playback_record_id)
            WHERE active = 1;
        CREATE INDEX IF NOT EXISTS idx_manual_playback_decisions_record
            ON manual_playback_decisions(playback_record_id, active);
        """
    )


def set_manual_playback_decision(
    conn: sqlite3.Connection,
    playback_record_id: int,
    decision_status: str,
    *,
    reason: str = "",
    note: str = "",
) -> None:
    """Set one active manual decision without mutating playback evidence."""
    normalized_status = _validate_effective_status(decision_status)
    record_id = int(playback_record_id)
    conn.execute(
        f"""
        UPDATE manual_playback_decisions
        SET active = 0, updated_at = {SQLITE_UTC_NOW}
        WHERE playback_record_id = ? AND active = 1
        """,
        (record_id,),
    )
    conn.execute(
        f"""
        INSERT INTO manual_playback_decisions (
            playback_record_id,
            decision_status,
            decision_reason,
            note,
            active,
            decided_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, 1, {SQLITE_UTC_NOW}, {SQLITE_UTC_NOW})
        """,
        (record_id, normalized_status, reason, note),
    )


def clear_manual_playback_decision(
    conn: sqlite3.Connection,
    playback_record_id: int,
) -> None:
    """Remove the active overlay so evidence rules decide again."""
    conn.execute(
        f"""
        UPDATE manual_playback_decisions
        SET active = 0, updated_at = {SQLITE_UTC_NOW}
        WHERE playback_record_id = ? AND active = 1
        """,
        (int(playback_record_id),),
    )


def playback_projection_join_sql(conn: sqlite3.Connection) -> str:
    """Return the optional manual-decision join for a `playback_records pr` query."""
    if not _table_exists(conn, MANUAL_PLAYBACK_DECISIONS_TABLE):
        return ""
    return """
        LEFT JOIN manual_playback_decisions mpd
            ON mpd.playback_record_id = pr.id
            AND mpd.active = 1
        """


def playback_projection_select_sql(conn: sqlite3.Connection) -> str:
    """Return projection columns for a `playback_records pr` query."""
    return f"""
            {default_playback_status_sql()} AS default_playback_status,
            {manual_decision_status_sql(conn)} AS manual_decision_status,
            {effective_playback_status_sql(conn)} AS effective_playback_status
        """


def accepted_playback_where_sql(conn: sqlite3.Connection) -> str:
    """Return a WHERE expression for effective accepted playback records."""
    return (
        f"{effective_playback_status_sql(conn)} = "
        f"'{EFFECTIVE_PLAYBACK_ACCEPTED}'"
    )


def effective_playback_status_sql(conn: sqlite3.Connection) -> str:
    """Return SQL for the effective state of a `playback_records pr` row."""
    default_status = default_playback_status_sql()
    if not _table_exists(conn, MANUAL_PLAYBACK_DECISIONS_TABLE):
        return default_status
    return f"COALESCE(mpd.decision_status, {default_status})"


def default_playback_status_sql() -> str:
    """Return SQL for the evidence-derived state before manual overlay."""
    return "pr.default_acceptance_status"


def manual_decision_status_sql(conn: sqlite3.Connection) -> str:
    if not _table_exists(conn, MANUAL_PLAYBACK_DECISIONS_TABLE):
        return "NULL"
    return "mpd.decision_status"


def _validate_effective_status(value: str) -> str:
    normalized = str(value).strip().lower()
    if normalized not in _VALID_EFFECTIVE_STATUSES:
        allowed = ", ".join(sorted(_VALID_EFFECTIVE_STATUSES))
        raise ValueError(f"manual playback decision must be one of: {allowed}")
    return normalized


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None
