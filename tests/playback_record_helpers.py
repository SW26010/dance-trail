from __future__ import annotations

import sqlite3

from dancing_log.playback_record_writer import PlaybackRecordWrite, upsert_playback_record


def insert_playback_record(
    conn: sqlite3.Connection,
    *,
    track_id: int,
    played_at: str,
    source_kind: str = "vrcx_history",
    source_table: str = "dance_events",
    source_type: str = "self",
    playback_status: str = "accepted",
    counts_in_history: int = 1,
    status_reason: str = "test",
    video_name: str | None = None,
    source_display_name: str | None = None,
    requester_display_name: str | None = None,
    requester_user_id: str | None = None,
    catalog_attention: int = 0,
    source_row_id: int | None = None,
) -> int:
    if source_row_id is None:
        row = conn.execute(
            """
            SELECT COALESCE(MAX(origin_row_id), 0) + 1 AS next_id
            FROM playback_record_origins
            """
        ).fetchone()
        source_row_id = int(row["next_id"])
    track = conn.execute(
        """
        SELECT ds.key AS system_key, dt.external_id
        FROM dance_tracks dt
        JOIN dance_systems ds ON ds.id = dt.system_id
        WHERE dt.id = ?
        """,
        (track_id,),
    ).fetchone()
    if track is None:
        raise AssertionError(f"missing dance_track row {track_id}")

    result = upsert_playback_record(
        conn,
        PlaybackRecordWrite(
            played_at=played_at,
            original_played_at=played_at,
            dance_track_id=track_id,
            dance_system_key=track["system_key"],
            dance_external_id=track["external_id"],
            source_kind=source_kind,
            source_table=source_table,
            source_row_id=source_row_id,
            source_event_key=f"test-event-{source_row_id}",
            status_reason=status_reason,
            source_priority=10,
            confidence=1.0,
            event_source="test",
            source_type=source_type,
            source_display_name=source_display_name,
            video_name=video_name,
            requester_display_name=requester_display_name,
            requester_user_id=requester_user_id,
            completion_status="completed" if playback_status == "accepted" else None,
            completion_reason=status_reason,
            playback_status=playback_status,
            counts_in_history=counts_in_history,
            catalog_attention=catalog_attention,
            provenance={"test": True},
        ),
    )
    return result.playback_record_id
