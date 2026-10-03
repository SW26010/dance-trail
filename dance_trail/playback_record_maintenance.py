"""Maintenance mutations for Local Playback Evidence projections."""

from __future__ import annotations

import sqlite3

from dance_trail.playback_evidence import (
    PLAYBACK_STATUS_NEEDS_ATTENTION,
    PLAYBACK_STATUS_PENDING,
)
from dance_trail.time_utils import SQLITE_UTC_NOW


def mark_watcher_pending_interrupted(
    conn: sqlite3.Connection,
    *,
    evidence_source: str,
    origin_table: str,
    pending_reason: str,
    interrupted_reason: str,
) -> int:
    """Convert stale watcher pending records left by an ungraceful exit."""
    cursor = conn.execute(
        f"""
        UPDATE playback_records
        SET
            default_acceptance_status = ?,
            observation_status = 'interrupted',
            observation_reason = ?,
            updated_at = {SQLITE_UTC_NOW}
        WHERE id IN (
            SELECT pr.id
            FROM playback_records pr
            JOIN playback_record_origins pro
                ON pro.playback_record_id = pr.id
            WHERE pr.evidence_source = ?
                AND pro.origin_table = ?
                AND pr.default_acceptance_status = ?
                AND (
                    pr.observation_status = 'pending'
                    OR pr.observation_reason = ?
                    OR pr.observation_reason IS NULL
                )
        )
        """,
        (
            PLAYBACK_STATUS_NEEDS_ATTENTION,
            interrupted_reason,
            evidence_source,
            origin_table,
            PLAYBACK_STATUS_PENDING,
            pending_reason,
        ),
    )
    return int(cursor.rowcount or 0)
