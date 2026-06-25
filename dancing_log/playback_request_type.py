"""Request-type seam for Local Playback Evidence records."""

from __future__ import annotations

import sqlite3

from dancing_log.playback_record_writer import (
    RUNTIME_BATCH_ID,
    PlaybackRecordOriginWrite,
)


REQUEST_TYPE_PRECEDENCE = {
    "queued_self": 6,
    "recommend": 5,
    "self": 4,
    "other": 3,
    "random": 2,
    "unknown": 1,
}

REQUEST_TYPE_PRECEDENCE_SQL = """
    CASE {column}
        WHEN 'queued_self' THEN 6
        WHEN 'recommend' THEN 5
        WHEN 'self' THEN 4
        WHEN 'other' THEN 3
        WHEN 'random' THEN 2
        WHEN 'unknown' THEN 1
        ELSE 0
    END
"""


def promote_request_type(
    conn: sqlite3.Connection,
    *,
    dance_system_key: str,
    dance_external_id: str,
    played_local_date: str,
    request_type: str,
    origin: PlaybackRecordOriginWrite | None = None,
    local_date_modifier: str = "+8 hours",
    batch_id: str = RUNTIME_BATCH_ID,
) -> int:
    """Deferred request-type mutation hook.

    The concrete queued-self/request-type promotion rules are intentionally
    paused; callers can depend on this seam without mutating playback_records.
    """
    return 0
