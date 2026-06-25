"""Runtime writer for Local Playback Evidence records."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from dancing_log.time_utils import normalize_timestamp, now_utc_iso


RUNTIME_BATCH_ID = "runtime-playback-writer-v1"
PROJECT_SOURCE_ROOT_KEY = "project"
PROJECT_SOURCE_ROOT_PATH = str(Path(__file__).resolve().parents[1])

# Keep the ADR 0004 namespace so future runtime writes resolve to the same
# evidence identity as rows that may have been created by the cleanup.
EVIDENCE_KEY_NAMESPACE = "legacy-playback-cleanup"

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
class PlaybackRecordOriginWrite:
    origin_key: str
    origin_source: str
    origin_root_key: str | None = None
    origin_root_path: str | None = None
    origin_table: str | None = None
    origin_row_id: int | None = None
    origin_event_key: str | None = None
    origin_json: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class PlaybackRecordWrite:
    evidence_key: str
    evidence_source: str
    played_at: str
    dance_track_id: int | None
    dance_system_key: str
    dance_external_id: str
    request_type: str | None
    default_acceptance_status: str
    requester_display_name: str | None = None
    requester_user_id: str | None = None
    observation_status: str | None = None
    observation_reason: str | None = None
    observed_end_at: str | None = None
    video_url: str | None = None
    video_name: str | None = None
    origins: tuple[PlaybackRecordOriginWrite, ...] = ()


@dataclass(frozen=True)
class PlaybackRecordWriteResult:
    playback_record_id: int
    changed: int


def upsert_evidence_record(
    conn: sqlite3.Connection,
    record: PlaybackRecordWrite,
    *,
    batch_id: str = RUNTIME_BATCH_ID,
) -> PlaybackRecordWriteResult:
    """Insert or update one target-owned Local Playback Evidence projection."""
    values = _record_values(record)
    origins = tuple(record.origins)
    if not origins:
        raise ValueError("at least one playback record origin is required")
    existing = _existing_record(conn, record.evidence_key)
    if existing is not None:
        origins = _preserve_existing_requester_identity(
            conn,
            values,
            existing,
            origins,
        )

    if existing is not None and _is_noop(existing, values):
        playback_record_id = int(existing["id"])
        changed = 0
    else:
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
            (record.evidence_key,),
        ).fetchone()
        playback_record_id = int(row["id"])
        changed = 1 if cursor.rowcount else 0

    for origin in origins:
        attach_origin(
            conn,
            playback_record_id,
            origin,
            batch_id=batch_id,
        )
    return PlaybackRecordWriteResult(
        playback_record_id=playback_record_id,
        changed=changed,
    )


def attach_origin(
    conn: sqlite3.Connection,
    playback_record_id: int,
    origin: PlaybackRecordOriginWrite,
    *,
    batch_id: str = RUNTIME_BATCH_ID,
) -> int:
    """Attach or refresh one origin/provenance row for an evidence record."""
    origin_values = _origin_values(
        origin,
        playback_record_id=playback_record_id,
        batch_id=batch_id,
    )
    cursor = conn.execute(
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
    return int(cursor.rowcount or 0)


def _record_values(record: PlaybackRecordWrite) -> dict[str, object]:
    played_at = normalize_timestamp(record.played_at)
    now = now_utc_iso()
    return {
        "evidence_key": _required_text(record.evidence_key, "evidence_key"),
        "evidence_source": _required_text(record.evidence_source, "evidence_source"),
        "played_at": played_at,
        "dance_track_id": record.dance_track_id,
        "dance_system_key": _required_text(
            record.dance_system_key,
            "dance_system_key",
        ).lower(),
        "dance_external_id": _required_text(
            record.dance_external_id,
            "dance_external_id",
        ),
        "request_type": _text_or_none(record.request_type),
        "requester_display_name": _text_or_none(record.requester_display_name),
        "requester_user_id": _text_or_none(record.requester_user_id),
        "default_acceptance_status": _required_text(
            record.default_acceptance_status,
            "default_acceptance_status",
        ),
        "observation_status": _text_or_none(record.observation_status),
        "observation_reason": _text_or_none(record.observation_reason),
        "observed_end_at": _normalized_optional_timestamp(record.observed_end_at),
        "video_url": _text_or_none(record.video_url),
        "video_name": _text_or_none(record.video_name),
        "created_at": now,
        "updated_at": now,
    }


def _existing_record(
    conn: sqlite3.Connection,
    evidence_key: str,
) -> sqlite3.Row | None:
    return conn.execute(
        f"""
        SELECT
            id,
            {", ".join(_PLAYBACK_RECORD_COLUMNS)}
        FROM playback_records
        WHERE evidence_key = ?
        """,
        (evidence_key,),
    ).fetchone()


def _preserve_existing_requester_identity(
    conn: sqlite3.Connection,
    values: dict[str, object],
    existing: sqlite3.Row,
    origins: tuple[PlaybackRecordOriginWrite, ...],
) -> tuple[PlaybackRecordOriginWrite, ...]:
    current_user_id = _text_or_none(existing["requester_user_id"])
    if current_user_id is None:
        return origins
    values["requester_user_id"] = current_user_id
    current_source = _requester_user_id_source_from_existing_origins(
        conn,
        playback_record_id=int(existing["id"]),
        origin_keys=tuple(origin.origin_key for origin in origins),
    )
    return tuple(
        _origin_with_requester_identity(
            origin,
            requester_user_id=current_user_id,
            requester_user_id_source=current_source,
        )
        for origin in origins
    )


def _origin_with_requester_identity(
    origin: PlaybackRecordOriginWrite,
    *,
    requester_user_id: str,
    requester_user_id_source: str | None,
) -> PlaybackRecordOriginWrite:
    origin_json = _json_dict(origin.origin_json)
    event = origin_json.get("watcher_playback_event")
    if not isinstance(event, dict):
        return origin

    updated_event = dict(event)
    updated_event["requester_user_id"] = requester_user_id
    updated_event["requester_user_id_source"] = requester_user_id_source
    origin_json["watcher_playback_event"] = updated_event
    return replace(origin, origin_json=origin_json)


def _requester_user_id_source_from_existing_origins(
    conn: sqlite3.Connection,
    *,
    playback_record_id: int,
    origin_keys: tuple[str, ...],
) -> str | None:
    for origin_key_value in origin_keys:
        row = conn.execute(
            """
            SELECT origin_json
            FROM playback_record_origins
            WHERE playback_record_id = ? AND origin_key = ?
            """,
            (playback_record_id, origin_key_value),
        ).fetchone()
        if row is not None:
            source = _requester_user_id_source_from_origin_json(row["origin_json"])
            if source is not None:
                return source

    for row in conn.execute(
        """
        SELECT origin_json
        FROM playback_record_origins
        WHERE playback_record_id = ?
        ORDER BY id
        """,
        (playback_record_id,),
    ).fetchall():
        source = _requester_user_id_source_from_origin_json(row["origin_json"])
        if source is not None:
            return source
    return None


def _requester_user_id_source_from_origin_json(origin_json: object) -> str | None:
    origin = _json_dict(origin_json)
    event = origin.get("watcher_playback_event")
    if not isinstance(event, dict):
        return None
    return _text_or_none(event.get("requester_user_id_source"))


def _json_dict(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _text_or_none(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _required_text(value: object, field_name: str) -> str:
    text = _text_or_none(value)
    if text is None:
        raise ValueError(f"{field_name} is required")
    return text


def _is_noop(existing: sqlite3.Row, values: dict[str, object]) -> bool:
    return all(existing[column] == values[column] for column in _NOOP_COMPARE_COLUMNS)


def playback_evidence_key(
    source_root_key: str,
    source_table: str,
    source_row_id: Any,
    source_event_key: Any,
) -> str:
    raw = "\x1f".join(
        [
            EVIDENCE_KEY_NAMESPACE,
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
    origin: PlaybackRecordOriginWrite,
    *,
    playback_record_id: int,
    batch_id: str,
) -> dict[str, object]:
    return {
        "playback_record_id": playback_record_id,
        "origin_key": _required_text(origin.origin_key, "origin_key"),
        "origin_source": _required_text(origin.origin_source, "origin_source"),
        "origin_root_key": _text_or_none(origin.origin_root_key),
        "origin_root_path": _text_or_none(origin.origin_root_path),
        "origin_table": _text_or_none(origin.origin_table),
        "origin_row_id": int(origin.origin_row_id)
        if origin.origin_row_id is not None
        else None,
        "origin_event_key": _text_or_none(origin.origin_event_key),
        "ingest_run_id": batch_id,
        "origin_json": json.dumps(
            _json_dict(origin.origin_json),
            ensure_ascii=False,
            sort_keys=True,
        ),
        "created_at": now_utc_iso(),
    }


def _normalized_optional_timestamp(value: str | None) -> str | None:
    text = _text_or_none(value)
    return normalize_timestamp(text) if text is not None else None
