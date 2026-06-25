"""Runtime writer for Local Playback Evidence records."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from dancing_log.playback_evidence import PLAYBACK_STATUS_ACCEPTED
from dancing_log.time_utils import normalize_timestamp, now_utc_iso


RUNTIME_BATCH_ID = "runtime-playback-writer-v1"
PROJECT_SOURCE_ROOT_KEY = "project"
PROJECT_SOURCE_ROOT_PATH = str(Path(__file__).resolve().parents[1])

# Keep the ADR 0004 fingerprint namespace so future runtime writes resolve to
# the same source identity as rows that may have been created by the cleanup.
SOURCE_FINGERPRINT_NAMESPACE = "legacy-playback-cleanup"

_PLAYBACK_RECORD_COLUMNS = (
    "evidence_key",
    "evidence_source",
    "played_at",
    "dance_track_id",
    "dance_system_key",
    "dance_external_id",
    "request_type",
    "requester_display_name",
    "requester_user_id",
    "default_acceptance_status",
    "observation_status",
    "observation_reason",
    "observed_end_at",
    "video_url",
    "video_name",
    "created_at",
    "updated_at",
)

_ORIGIN_COLUMNS = (
    "playback_record_id",
    "origin_key",
    "origin_source",
    "origin_root_key",
    "origin_root_path",
    "origin_table",
    "origin_row_id",
    "origin_event_key",
    "ingest_run_id",
    "origin_json",
    "created_at",
)

_NOOP_COMPARE_COLUMNS = tuple(
    column
    for column in _PLAYBACK_RECORD_COLUMNS
    if column not in {"created_at", "updated_at"}
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
    observed_end_at: str | None = None
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
    evidence_key = source_fingerprint(
        record.source_root_key,
        record.source_table,
        record.source_row_id,
        record.source_event_key,
    )
    origin_key_value = origin_key(
        record.source_root_key,
        record.source_table,
        record.source_row_id,
        record.source_event_key,
    )
    values = _record_values(record, evidence_key)
    origin_json = _origin_json(record)
    existing = _existing_record(conn, evidence_key, origin_key_value)
    if existing is not None:
        _preserve_existing_requester_identity(values, existing, origin_json)
    if existing is not None and _is_noop(existing, values):
        return PlaybackRecordWriteResult(
            playback_record_id=int(existing["id"]),
            changed=0,
        )

    cursor = conn.execute(
        f"""
        INSERT INTO playback_records ({", ".join(_PLAYBACK_RECORD_COLUMNS)})
        VALUES ({", ".join("?" for _ in _PLAYBACK_RECORD_COLUMNS)})
        ON CONFLICT(evidence_key) DO UPDATE SET
            evidence_source = excluded.evidence_source,
            played_at = excluded.played_at,
            dance_track_id = excluded.dance_track_id,
            dance_system_key = excluded.dance_system_key,
            dance_external_id = excluded.dance_external_id,
            request_type = excluded.request_type,
            requester_display_name = excluded.requester_display_name,
            requester_user_id = COALESCE(NULLIF(playback_records.requester_user_id, ''), excluded.requester_user_id),
            default_acceptance_status = excluded.default_acceptance_status,
            observation_status = excluded.observation_status,
            observation_reason = excluded.observation_reason,
            observed_end_at = excluded.observed_end_at,
            video_url = excluded.video_url,
            video_name = excluded.video_name,
            updated_at = excluded.updated_at
        """,
        tuple(values[column] for column in _PLAYBACK_RECORD_COLUMNS),
    )
    row = conn.execute(
        "SELECT id FROM playback_records WHERE evidence_key = ?",
        (evidence_key,),
    ).fetchone()
    playback_record_id = int(row["id"])
    origin_values = _origin_values(
        record,
        playback_record_id=playback_record_id,
        origin_key_value=origin_key_value,
        origin_json=origin_json,
        batch_id=batch_id,
    )
    conn.execute(
        f"""
        INSERT INTO playback_record_origins ({", ".join(_ORIGIN_COLUMNS)})
        VALUES ({", ".join("?" for _ in _ORIGIN_COLUMNS)})
        ON CONFLICT(origin_key) DO UPDATE SET
            playback_record_id = excluded.playback_record_id,
            origin_source = excluded.origin_source,
            origin_root_key = excluded.origin_root_key,
            origin_root_path = excluded.origin_root_path,
            origin_table = excluded.origin_table,
            origin_row_id = excluded.origin_row_id,
            origin_event_key = excluded.origin_event_key,
            ingest_run_id = excluded.ingest_run_id,
            origin_json = excluded.origin_json
        """,
        tuple(origin_values[column] for column in _ORIGIN_COLUMNS),
    )
    return PlaybackRecordWriteResult(
        playback_record_id=playback_record_id,
        changed=1 if cursor.rowcount else 0,
    )


def _record_values(
    record: PlaybackRecordWrite,
    evidence_key: str,
) -> dict[str, object]:
    played_at = normalize_timestamp(record.played_at)
    now = now_utc_iso()
    return {
        "evidence_key": evidence_key,
        "evidence_source": _evidence_source(record),
        "played_at": played_at,
        "dance_track_id": record.dance_track_id,
        "dance_system_key": record.dance_system_key.strip().lower(),
        "dance_external_id": str(record.dance_external_id).strip(),
        "request_type": _text_or_none(record.source_type),
        "requester_display_name": record.requester_display_name,
        "requester_user_id": record.requester_user_id,
        "default_acceptance_status": _default_acceptance_status(record),
        "observation_status": _text_or_none(record.completion_status),
        "observation_reason": _text_or_none(record.completion_reason),
        "observed_end_at": _normalized_optional_timestamp(
            record.observed_end_at or _observed_end_at_from_provenance(record.provenance)
        ),
        "video_url": record.video_url,
        "video_name": record.video_name,
        "created_at": now,
        "updated_at": now,
    }


def _existing_record(
    conn: sqlite3.Connection,
    evidence_key: str,
    origin_key_value: str,
) -> sqlite3.Row | None:
    return conn.execute(
        f"""
        SELECT
            pr.id,
            {", ".join(f"pr.{column}" for column in _PLAYBACK_RECORD_COLUMNS)},
            pro.origin_json
        FROM playback_records pr
        LEFT JOIN playback_record_origins pro
            ON pro.playback_record_id = pr.id
            AND pro.origin_key = ?
        WHERE pr.evidence_key = ?
        """,
        (origin_key_value, evidence_key),
    ).fetchone()


def _preserve_existing_requester_identity(
    values: dict[str, object],
    existing: sqlite3.Row,
    origin_json: dict[str, object],
) -> None:
    current_user_id = _text_or_none(existing["requester_user_id"])
    if current_user_id is None:
        return
    values["requester_user_id"] = current_user_id
    _origin_json_with_requester_identity(
        origin_json,
        requester_user_id=current_user_id,
        requester_user_id_source=_requester_user_id_source_from_provenance(
            existing["origin_json"]
        ),
    )


def _origin_json_with_requester_identity(
    origin_json: dict[str, object],
    *,
    requester_user_id: str,
    requester_user_id_source: str | None,
) -> None:
    event = origin_json.get("watcher_playback_event")
    if not isinstance(event, dict):
        return

    updated_event = dict(event)
    updated_event["requester_user_id"] = requester_user_id
    updated_event["requester_user_id_source"] = requester_user_id_source
    origin_json["watcher_playback_event"] = updated_event


def _requester_user_id_source_from_provenance(provenance_json: object) -> str | None:
    provenance = _json_dict(str(provenance_json or "{}"))
    event = provenance.get("watcher_playback_event")
    if not isinstance(event, dict):
        return None
    return _text_or_none(event.get("requester_user_id_source"))


def _json_dict(value: str) -> dict:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _text_or_none(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


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


def origin_key(
    source_root_key: str,
    source_table: str,
    source_row_id: Any,
    source_event_key: Any,
) -> str:
    raw = "\x1f".join(
        [
            "playback-origin-v1",
            str(source_root_key),
            str(source_table),
            str(source_row_id),
            str(source_event_key or ""),
        ]
    )
    return f"origin:v1:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def _origin_values(
    record: PlaybackRecordWrite,
    *,
    playback_record_id: int,
    origin_key_value: str,
    origin_json: dict[str, object],
    batch_id: str,
) -> dict[str, object]:
    return {
        "playback_record_id": playback_record_id,
        "origin_key": origin_key_value,
        "origin_source": _origin_source(record),
        "origin_root_key": record.source_root_key,
        "origin_root_path": record.source_root_path,
        "origin_table": record.source_table,
        "origin_row_id": int(record.source_row_id),
        "origin_event_key": record.source_event_key,
        "ingest_run_id": batch_id,
        "origin_json": json.dumps(origin_json, ensure_ascii=False, sort_keys=True),
        "created_at": now_utc_iso(),
    }


def _origin_json(record: PlaybackRecordWrite) -> dict[str, object]:
    origin: dict[str, object] = {}
    original_played_at = _text_or_none(record.original_played_at)
    if original_played_at is not None:
        origin["original_played_at"] = original_played_at
    if record.location:
        origin["vrcx_location"] = record.location
    if record.source_display_name:
        origin["source_display_name"] = record.source_display_name
    if record.status_reason:
        origin["legacy_status_reason"] = record.status_reason
    if record.source_priority is not None:
        origin["legacy_source_priority"] = int(record.source_priority)
    if record.confidence is not None:
        origin["legacy_confidence"] = float(record.confidence)
    if record.catalog_status:
        origin["legacy_catalog_status"] = record.catalog_status
    if record.catalog_attention:
        origin["legacy_catalog_attention"] = int(record.catalog_attention)
    provenance = record.provenance or {}
    if isinstance(provenance, dict):
        origin.update(provenance)
    return origin


def _evidence_source(record: PlaybackRecordWrite) -> str:
    event_source = _text_or_none(record.event_source)
    source_kind = _text_or_none(record.source_kind)
    if event_source in {"vrc_log_live", "vrc_log_replay", "manual_log"}:
        return event_source
    if source_kind == "vrcx_history":
        return "vrcx_history"
    if source_kind == "live_watcher":
        return "vrc_log_live"
    if source_kind == "manual_log":
        return "manual_log"
    return event_source or source_kind or "manual_log"


def _origin_source(record: PlaybackRecordWrite) -> str:
    evidence_source = _evidence_source(record)
    if evidence_source == "vrcx_history":
        return "vrcx_database"
    if evidence_source in {"vrc_log_live", "vrc_log_replay"}:
        return "vrchat_log"
    return evidence_source


def _default_acceptance_status(record: PlaybackRecordWrite) -> str:
    status = _text_or_none(record.playback_status)
    counts = int(record.counts_in_history)
    if status == "accepted" and counts == 1:
        return "accepted"
    if status == "pending" and counts == 0:
        return "pending"
    if status == "needs_attention" and counts == 0:
        return "needs_attention"
    if status == "excluded" and counts == 0:
        return "excluded"
    raise ValueError(
        "playback_status/counts_in_history cannot be mapped to "
        f"default_acceptance_status: {status!r}/{counts!r}"
    )


def _observed_end_at_from_provenance(provenance: dict[str, Any] | None) -> str | None:
    if not isinstance(provenance, dict):
        return None
    for key in ("watcher_playback_event", "live_playback_event"):
        event = provenance.get(key)
        if not isinstance(event, dict):
            continue
        value = event.get("completed_at") or event.get("interrupted_at")
        if value:
            return str(value)
    return None


def _normalized_optional_timestamp(value: str | None) -> str | None:
    text = _text_or_none(value)
    return normalize_timestamp(text) if text is not None else None
