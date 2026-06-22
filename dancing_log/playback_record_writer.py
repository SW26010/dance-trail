"""Runtime writer for Local Playback Evidence records."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from dancing_log.playback_evidence import PLAYBACK_STATUS_ACCEPTED


RUNTIME_BATCH_ID = "runtime-playback-writer-v1"
PROJECT_SOURCE_ROOT_KEY = "project"
PROJECT_SOURCE_ROOT_PATH = str(Path(__file__).resolve().parents[1])

# Keep the ADR 0004 fingerprint namespace so future runtime writes resolve to
# the same source identity as rows that may have been created by the cleanup.
SOURCE_FINGERPRINT_NAMESPACE = "legacy-playback-cleanup"

_WRITE_COLUMNS = (
    "cleanup_batch_id",
    "played_at",
    "original_played_at",
    "dance_track_id",
    "dance_system_key",
    "dance_external_id",
    "source_kind",
    "source_root_key",
    "source_root_path",
    "source_table",
    "source_row_id",
    "source_event_key",
    "source_fingerprint",
    "playback_status",
    "counts_in_history",
    "status_reason",
    "source_priority",
    "confidence",
    "event_source",
    "source_type",
    "source_display_name",
    "video_url",
    "video_name",
    "requester_display_name",
    "requester_user_id",
    "location",
    "completion_status",
    "completion_reason",
    "catalog_status",
    "catalog_attention",
    "provenance_json",
)
_NOOP_COMPARE_COLUMNS = tuple(
    column
    for column in _WRITE_COLUMNS
    if column not in {"cleanup_batch_id", "source_root_path", "provenance_json"}
)


@dataclass(frozen=True)
class PlaybackRecordWrite:
    played_at: str
    original_played_at: str
    dance_track_id: int | None
    dance_system_key: str
    dance_external_id: str
    source_kind: str
    source_table: str
    source_row_id: int
    source_event_key: str | None
    status_reason: str
    source_priority: int
    confidence: float | None
    event_source: str | None
    source_type: str | None
    source_display_name: str | None = None
    video_url: str | None = None
    video_name: str | None = None
    requester_display_name: str | None = None
    requester_user_id: str | None = None
    location: str | None = None
    completion_status: str | None = None
    completion_reason: str | None = None
    playback_status: str = PLAYBACK_STATUS_ACCEPTED
    counts_in_history: int = 1
    catalog_status: str = "existing"
    catalog_attention: int = 0
    source_root_key: str = PROJECT_SOURCE_ROOT_KEY
    source_root_path: str = PROJECT_SOURCE_ROOT_PATH
    provenance: dict[str, Any] | None = None


@dataclass(frozen=True)
class PlaybackRecordWriteResult:
    playback_record_id: int
    changed: int


def upsert_playback_record(
    conn: sqlite3.Connection,
    record: PlaybackRecordWrite,
    *,
    batch_id: str = RUNTIME_BATCH_ID,
) -> PlaybackRecordWriteResult:
    """Insert or update one target-owned Local Playback Evidence row."""
    fingerprint = source_fingerprint(
        record.source_root_key,
        record.source_table,
        record.source_row_id,
        record.source_event_key,
    )
    values = _record_values(record, fingerprint, batch_id)
    existing = _existing_record(conn, fingerprint)
    if existing is not None and _is_noop(existing, values):
        return PlaybackRecordWriteResult(
            playback_record_id=int(existing["id"]),
            changed=0,
        )

    cursor = conn.execute(
        f"""
        INSERT INTO playback_records ({", ".join(_WRITE_COLUMNS)})
        VALUES ({", ".join("?" for _ in _WRITE_COLUMNS)})
        ON CONFLICT(source_fingerprint) DO UPDATE SET
            cleanup_batch_id = excluded.cleanup_batch_id,
            played_at = excluded.played_at,
            original_played_at = excluded.original_played_at,
            dance_track_id = excluded.dance_track_id,
            dance_system_key = excluded.dance_system_key,
            dance_external_id = excluded.dance_external_id,
            source_kind = excluded.source_kind,
            source_root_key = excluded.source_root_key,
            source_root_path = excluded.source_root_path,
            source_table = excluded.source_table,
            source_row_id = excluded.source_row_id,
            source_event_key = excluded.source_event_key,
            playback_status = excluded.playback_status,
            counts_in_history = excluded.counts_in_history,
            status_reason = excluded.status_reason,
            source_priority = excluded.source_priority,
            confidence = excluded.confidence,
            event_source = excluded.event_source,
            source_type = excluded.source_type,
            source_display_name = excluded.source_display_name,
            video_url = excluded.video_url,
            video_name = excluded.video_name,
            requester_display_name = excluded.requester_display_name,
            requester_user_id = excluded.requester_user_id,
            location = excluded.location,
            completion_status = excluded.completion_status,
            completion_reason = excluded.completion_reason,
            catalog_status = excluded.catalog_status,
            catalog_attention = excluded.catalog_attention,
            provenance_json = excluded.provenance_json
        """,
        tuple(values[column] for column in _WRITE_COLUMNS),
    )
    row = conn.execute(
        "SELECT id FROM playback_records WHERE source_fingerprint = ?",
        (fingerprint,),
    ).fetchone()
    return PlaybackRecordWriteResult(
        playback_record_id=int(row["id"]),
        changed=1 if cursor.rowcount else 0,
    )


def _record_values(
    record: PlaybackRecordWrite,
    fingerprint: str,
    batch_id: str,
) -> dict[str, object]:
    return {
        "cleanup_batch_id": batch_id,
        "played_at": record.played_at,
        "original_played_at": record.original_played_at,
        "dance_track_id": record.dance_track_id,
        "dance_system_key": record.dance_system_key.strip().lower(),
        "dance_external_id": str(record.dance_external_id).strip(),
        "source_kind": record.source_kind,
        "source_root_key": record.source_root_key,
        "source_root_path": record.source_root_path,
        "source_table": record.source_table,
        "source_row_id": int(record.source_row_id),
        "source_event_key": record.source_event_key,
        "source_fingerprint": fingerprint,
        "playback_status": record.playback_status,
        "counts_in_history": int(record.counts_in_history),
        "status_reason": record.status_reason,
        "source_priority": int(record.source_priority),
        "confidence": record.confidence,
        "event_source": record.event_source,
        "source_type": record.source_type,
        "source_display_name": record.source_display_name,
        "video_url": record.video_url,
        "video_name": record.video_name,
        "requester_display_name": record.requester_display_name,
        "requester_user_id": record.requester_user_id,
        "location": record.location,
        "completion_status": record.completion_status,
        "completion_reason": record.completion_reason,
        "catalog_status": record.catalog_status,
        "catalog_attention": int(record.catalog_attention),
        "provenance_json": json.dumps(record.provenance or {}, ensure_ascii=False, sort_keys=True),
    }


def _existing_record(
    conn: sqlite3.Connection,
    fingerprint: str,
) -> sqlite3.Row | None:
    return conn.execute(
        f"""
        SELECT id, {", ".join(_WRITE_COLUMNS)}
        FROM playback_records
        WHERE source_fingerprint = ?
        """,
        (fingerprint,),
    ).fetchone()


def _is_noop(existing: sqlite3.Row, values: dict[str, object]) -> bool:
    return all(existing[column] == values[column] for column in _NOOP_COMPARE_COLUMNS)


def source_fingerprint(
    source_root_key: str,
    source_table: str,
    source_row_id: Any,
    source_event_key: Any,
) -> str:
    raw = "\x1f".join(
        [
            SOURCE_FINGERPRINT_NAMESPACE,
            str(source_root_key),
            str(source_table),
            str(source_row_id),
            str(source_event_key or ""),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
