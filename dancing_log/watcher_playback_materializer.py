"""Map folded watcher playback observations into Local Playback Evidence."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from typing import Any

from dancing_log.playback_evidence import (
    PLAYBACK_STATUS_ACCEPTED,
    PLAYBACK_STATUS_NEEDS_ATTENTION,
    PLAYBACK_STATUS_PENDING,
)
from dancing_log.playback_record_writer import PlaybackRecordWrite


WATCHER_PLAYBACK_SOURCE_TABLE = "watcher_playback_events"
WATCHER_PLAYBACK_SOURCE_KIND = "live_watcher"
WATCHER_PLAYBACK_EVENT_SOURCE = "vrc_log_live"
WATCHER_SOURCE_PRIORITY = 30

WATCHER_PENDING_REASON = "live_observation_pending"
WATCHER_GRACEFUL_STOP_REASON = "watcher_stopped"
WATCHER_INTERRUPTED_UNEXPECTEDLY_REASON = "watcher_interrupted_unexpectedly"


def make_watcher_playback_event_key(
    session_id: str | None,
    playback_event_key: str,
) -> str:
    """Return the stable logical source key for one folded watcher occurrence."""
    return hashlib.sha256(
        "\x1f".join(
            [
                "watcher-playback-event",
                str(session_id or ""),
                str(playback_event_key or ""),
            ]
        ).encode("utf-8")
    ).hexdigest()


def pending_watcher_playback_record(
    event: Mapping[str, Any],
    *,
    source_event_key: str,
    dance_track_id: int | None,
) -> PlaybackRecordWrite | None:
    """Build the initial pending record for a folded watcher event."""
    return watcher_playback_record(
        event,
        source_event_key=source_event_key,
        dance_track_id=dance_track_id,
        playback_status=PLAYBACK_STATUS_PENDING,
        counts_in_history=0,
        status_reason=WATCHER_PENDING_REASON,
        completion_status="pending",
        completion_reason=None,
    )


def accepted_watcher_playback_record(
    event: Mapping[str, Any],
    *,
    source_event_key: str,
    dance_track_id: int | None,
    reason: str,
) -> PlaybackRecordWrite | None:
    """Build an automatically accepted watcher-derived playback record."""
    return watcher_playback_record(
        event,
        source_event_key=source_event_key,
        dance_track_id=dance_track_id,
        playback_status=PLAYBACK_STATUS_ACCEPTED,
        counts_in_history=1,
        status_reason=reason,
        completion_status="completed",
        completion_reason=reason,
    )


def attention_watcher_playback_record(
    event: Mapping[str, Any],
    *,
    source_event_key: str,
    dance_track_id: int | None,
    reason: str,
) -> PlaybackRecordWrite | None:
    """Build a non-counting watcher-derived record that needs review attention."""
    return watcher_playback_record(
        event,
        source_event_key=source_event_key,
        dance_track_id=dance_track_id,
        playback_status=PLAYBACK_STATUS_NEEDS_ATTENTION,
        counts_in_history=0,
        status_reason=reason,
        completion_status="interrupted",
        completion_reason=reason,
    )


def watcher_playback_record(
    event: Mapping[str, Any],
    *,
    source_event_key: str,
    dance_track_id: int | None,
    playback_status: str,
    counts_in_history: int,
    status_reason: str,
    completion_status: str | None,
    completion_reason: str | None,
) -> PlaybackRecordWrite | None:
    """Build a playback-record write for a watcher event with stable identity."""
    system_key = str(event.get("dance_system_key") or "").strip().lower()
    external_id = str(event.get("dance_external_id") or "").strip()
    if not system_key or not external_id:
        return None

    played_at = _played_at(event)
    if not played_at:
        return None

    display_name = event.get("source_display_name") or event.get("display_name")
    return PlaybackRecordWrite(
        played_at=played_at,
        original_played_at=played_at,
        dance_track_id=dance_track_id,
        dance_system_key=system_key,
        dance_external_id=external_id,
        source_kind=WATCHER_PLAYBACK_SOURCE_KIND,
        source_table=WATCHER_PLAYBACK_SOURCE_TABLE,
        source_row_id=0,
        source_event_key=source_event_key,
        playback_status=playback_status,
        counts_in_history=counts_in_history,
        status_reason=status_reason,
        source_priority=WATCHER_SOURCE_PRIORITY,
        confidence=1.0,
        event_source=WATCHER_PLAYBACK_EVENT_SOURCE,
        source_type=event.get("source_type"),
        source_display_name=display_name,
        video_url=event.get("video_url") or event.get("resolved_url") or event.get("routed_url"),
        video_name=event.get("video_name"),
        requester_display_name=display_name,
        completion_status=completion_status,
        completion_reason=completion_reason,
        provenance={"watcher_playback_event": dict(event)},
    )


def _played_at(event: Mapping[str, Any]) -> str | None:
    for field_name in ("actual_play_at", "first_seen_at", "last_seen_at"):
        value = event.get(field_name)
        if value:
            return str(value)
    return None
