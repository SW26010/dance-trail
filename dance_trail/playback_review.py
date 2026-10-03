"""User review write interface for Playback Record manual decisions."""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from dance_trail.playback_projection import (
    EFFECTIVE_PLAYBACK_ACCEPTED,
    EFFECTIVE_PLAYBACK_EXCLUDED,
    EFFECTIVE_PLAYBACK_NEEDS_ATTENTION,
    clear_manual_playback_decision,
    playback_projection_join_sql,
    playback_projection_select_sql,
    set_manual_playback_decision,
)


VALID_MANUAL_PLAYBACK_DECISIONS = frozenset(
    {
        EFFECTIVE_PLAYBACK_ACCEPTED,
        EFFECTIVE_PLAYBACK_EXCLUDED,
        EFFECTIVE_PLAYBACK_NEEDS_ATTENTION,
    }
)


class PlaybackReviewError(ValueError):
    """Expected review-write failure that can be shown in the local UI."""


@dataclass(frozen=True)
class PlaybackReviewState:
    playback_record_id: int
    default_playback_status: str
    manual_decision_status: str | None
    effective_playback_status: str

    def as_dict(self) -> dict:
        return {
            "playback_record_id": self.playback_record_id,
            "default_playback_status": self.default_playback_status,
            "manual_decision_status": self.manual_decision_status,
            "effective_playback_status": self.effective_playback_status,
        }


def set_playback_record_manual_decision(
    conn: sqlite3.Connection,
    playback_record_id: int,
    decision_status: str,
    *,
    reason: str = "timeline_review",
    note: str = "",
) -> PlaybackReviewState:
    """Set the active Manual Playback Decision for one Playback Record."""
    record_id = _validate_playback_record_id(playback_record_id)
    normalized_status = _validate_manual_decision(decision_status)
    _require_playback_record(conn, record_id)
    set_manual_playback_decision(
        conn,
        record_id,
        normalized_status,
        reason=reason,
        note=note,
    )
    return read_playback_review_state(conn, record_id)


def clear_playback_record_manual_decision(
    conn: sqlite3.Connection,
    playback_record_id: int,
) -> PlaybackReviewState:
    """Clear the active Manual Playback Decision so the default result applies."""
    record_id = _validate_playback_record_id(playback_record_id)
    _require_playback_record(conn, record_id)
    clear_manual_playback_decision(conn, record_id)
    return read_playback_review_state(conn, record_id)


def read_playback_review_state(
    conn: sqlite3.Connection,
    playback_record_id: int,
) -> PlaybackReviewState:
    """Read default/manual/effective review state for one Playback Record."""
    record_id = _validate_playback_record_id(playback_record_id)
    if not _table_exists(conn, "playback_records"):
        raise PlaybackReviewError("playback record not found")
    row = conn.execute(
        f"""
        SELECT
            pr.id AS playback_record_id,
            {playback_projection_select_sql(conn)}
        FROM playback_records pr
        {playback_projection_join_sql(conn)}
        WHERE pr.id = ?
        """,
        (record_id,),
    ).fetchone()
    if row is None:
        raise PlaybackReviewError("playback record not found")
    return PlaybackReviewState(
        playback_record_id=int(row["playback_record_id"]),
        default_playback_status=str(row["default_playback_status"]),
        manual_decision_status=(
            str(row["manual_decision_status"])
            if row["manual_decision_status"] is not None
            else None
        ),
        effective_playback_status=str(row["effective_playback_status"]),
    )


def _require_playback_record(conn: sqlite3.Connection, playback_record_id: int) -> None:
    if not _table_exists(conn, "playback_records"):
        raise PlaybackReviewError("playback record not found")
    row = conn.execute(
        "SELECT 1 FROM playback_records WHERE id = ?",
        (playback_record_id,),
    ).fetchone()
    if row is None:
        raise PlaybackReviewError("playback record not found")


def _validate_playback_record_id(value: int) -> int:
    try:
        record_id = int(value)
    except (TypeError, ValueError) as exc:
        raise PlaybackReviewError("playback_record_id must be a positive integer") from exc
    if record_id <= 0:
        raise PlaybackReviewError("playback_record_id must be a positive integer")
    return record_id


def _validate_manual_decision(value: str) -> str:
    normalized = str(value).strip().lower()
    if normalized not in VALID_MANUAL_PLAYBACK_DECISIONS:
        allowed = ", ".join(sorted(VALID_MANUAL_PLAYBACK_DECISIONS))
        raise PlaybackReviewError(f"manual playback decision must be one of: {allowed}")
    return normalized


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None
