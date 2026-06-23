from __future__ import annotations

import json
import sqlite3


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
    catalog_attention: int = 0,
    source_row_id: int | None = None,
) -> int:
    if source_row_id is None:
        row = conn.execute(
            "SELECT COALESCE(MAX(source_row_id), 0) + 1 AS next_id FROM playback_records"
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

    fingerprint = (
        f"test:{source_kind}:{source_table}:{source_row_id}:"
        f"{track['system_key']}:{track['external_id']}:{played_at}"
    )
    conn.execute(
        """
        INSERT INTO playback_records (
            cleanup_batch_id,
            played_at,
            original_played_at,
            dance_track_id,
            dance_system_key,
            dance_external_id,
            source_kind,
            source_root_key,
            source_root_path,
            source_table,
            source_row_id,
            source_event_key,
            source_fingerprint,
            playback_status,
            counts_in_history,
            status_reason,
            source_priority,
            confidence,
            event_source,
            source_type,
            source_display_name,
            video_url,
            video_name,
            requester_display_name,
            requester_user_id,
            location,
            completion_status,
            completion_reason,
            catalog_status,
            catalog_attention,
            provenance_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "test-batch",
            played_at,
            played_at,
            track_id,
            track["system_key"],
            track["external_id"],
            source_kind,
            "test-root",
            "test-root",
            source_table,
            source_row_id,
            f"test-event-{source_row_id}",
            fingerprint,
            playback_status,
            counts_in_history,
            status_reason,
            10,
            1.0,
            "test",
            source_type,
            source_display_name,
            None,
            video_name,
            requester_display_name,
            None,
            None,
            "completed" if playback_status == "accepted" else None,
            status_reason,
            "existing",
            catalog_attention,
            json.dumps({"test": True}),
        ),
    )
    row = conn.execute(
        "SELECT id FROM playback_records WHERE source_fingerprint = ?",
        (fingerprint,),
    ).fetchone()
    return int(row["id"])
