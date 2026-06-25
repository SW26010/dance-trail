from __future__ import annotations

import sqlite3

from dancing_log.playback_record_writer import (
    PROJECT_SOURCE_ROOT_KEY,
    PROJECT_SOURCE_ROOT_PATH,
    PlaybackRecordOriginWrite,
    PlaybackRecordWrite,
    origin_key,
    playback_evidence_key,
    upsert_evidence_record,
)


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

    event_key = f"test-event-{source_row_id}"
    result = upsert_evidence_record(
        conn,
        PlaybackRecordWrite(
            evidence_key=playback_evidence_key(
                PROJECT_SOURCE_ROOT_KEY,
                source_table,
                source_row_id,
                event_key,
            ),
            evidence_source=_evidence_source(source_kind),
            played_at=played_at,
            dance_track_id=track_id,
            dance_system_key=track["system_key"],
            dance_external_id=track["external_id"],
            request_type=source_type,
            default_acceptance_status=playback_status,
            video_name=video_name,
            requester_display_name=requester_display_name,
            requester_user_id=requester_user_id,
            observation_status="completed" if playback_status == "accepted" else None,
            observation_reason=status_reason,
            origins=(
                PlaybackRecordOriginWrite(
                    origin_key=origin_key(
                        PROJECT_SOURCE_ROOT_KEY,
                        source_table,
                        source_row_id,
                        event_key,
                    ),
                    origin_source=_origin_source(source_kind),
                    origin_root_key=PROJECT_SOURCE_ROOT_KEY,
                    origin_root_path=PROJECT_SOURCE_ROOT_PATH,
                    origin_table=source_table,
                    origin_row_id=source_row_id,
                    origin_event_key=event_key,
                    origin_json={
                        "original_played_at": played_at,
                        "legacy_status_reason": status_reason,
                        "legacy_source_priority": 10,
                        "legacy_confidence": 1.0,
                        "source_display_name": source_display_name,
                        "legacy_catalog_attention": catalog_attention,
                        "test": True,
                    },
                ),
            ),
        ),
    )
    return result.playback_record_id


def _origin_source(source_kind: str) -> str:
    if source_kind == "vrcx_history":
        return "vrcx_database"
    if source_kind == "live_watcher":
        return "vrchat_log"
    return source_kind


def _evidence_source(source_kind: str) -> str:
    if source_kind == "live_watcher":
        return "vrc_log_live"
    return source_kind
