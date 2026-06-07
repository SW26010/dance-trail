"""Lightweight VRChat output log watcher for playback forensics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
import csv
import json
import os
import re
import time

from dancing_log.app_paths import DEFAULT_CAPTURE_ROOT
from dancing_log.vrcx_importer import parse_dance_url


LOG_FILE_PATTERN = "output_log_*.txt"
PROMOTION_COMPLETION_RATIO = 0.8
COMPLETION_EPSILON_SECONDS = 0.001
PREVIEW_SUPPRESSION_SECONDS = 90.0
RETRY_MERGE_SECONDS = 30.0

VIDEO_TOKENS = (
    "video playback",
    "usharpvideo",
    "videoplay",
    "lsmedia",
    "previewvideo",
    "playqueuevideo",
    "playrandomvideo",
    "videoduration",
    "queue info serialized",
    "syncedqueuedinfojson",
    "deserializevideouserdata",
    "added url",
    "resolving url",
    "resolve url",
    "resolved to",
    "playvideointernal",
    "loadroutedurl",
    "video loaded",
    "delayedvideoready",
    "onvideostart",
    "playing synced",
)
LIFECYCLE_TOKENS = (
    "onleftroom",
    "entering room:",
    "handleapplicationquit",
    "[avprovideo] shutdown",
)

TIMESTAMP_RE = re.compile(
    r"^(?P<timestamp>\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)"
)
URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
COLOR_TAG_RE = re.compile(r"</?color(?:=[^>]*)?>", re.IGNORECASE)
VIDEO_PLAYBACK_RE = re.compile(
    r"\[Video Playback\]\s+"
    r"(?P<action>Attempting to resolve URL|Resolving URL)\s+"
    r"'(?P<url>[^']+)'",
    re.IGNORECASE,
)
VIDEO_RESOLVED_RE = re.compile(
    r"\[Video Playback\]\s+URL\s+'(?P<url>[^']+)'\s+resolved to\s+'(?P<resolved_url>[^']+)'",
    re.IGNORECASE,
)
USER_ADDED_URL_RE = re.compile(
    r"\bUser\s+(?P<display_name>.+?)\s+added URL\s+(?P<url>https?://\S+)",
    re.IGNORECASE,
)
USHARP_VIDEO_RE = re.compile(
    r"\[USharpVideo(?:\s*\([^)]+\))?\]\s+Started video load for URL:\s*"
    r"(?P<url>https?://\S+)"
    r"(?:,\s*requested by\s*(?P<display_name>.*?))?\s*$",
    re.IGNORECASE,
)
USHARP_PLAY_INTERNAL_RE = re.compile(
    r"\[USharpVideo(?:\s*\([^)]+\))?\]\s+PlayVideoInternal:\s+Playing video\s+"
    r"(?P<url>https?://\S+)",
    re.IGNORECASE,
)
USHARP_LOAD_ROUTED_RE = re.compile(
    r"\[USharpVideo(?:\s*\([^)]+\))?\]\s+LoadRoutedURL:\s+"
    r"(?P<url>https?://\S+)\s+routed to\s+(?P<routed_url>https?://\S+)",
    re.IGNORECASE,
)
USHARP_VIDEO_LOADED_RE = re.compile(
    r"\[USharpVideo(?:\s*\([^)]+\))?\]\s+Video loaded\s+"
    r"\((?P<load_seconds>[\d.]+)\s+seconds\),\s+but let's wait for\s+"
    r"(?P<wait_seconds>[\d.]+)\s+seconds before playing it",
    re.IGNORECASE,
)
USHARP_DELAYED_READY_RE = re.compile(
    r"\[USharpVideo(?:\s*\([^)]+\))?\]\s+DelayedVideoReady:\s+Time's up,\s+let's play",
    re.IGNORECASE,
)
USHARP_ON_VIDEO_START_RE = re.compile(
    r"\[USharpVideo(?:\s*\([^)]+\))?\]\s+OnVideoStart:\s+Started video:\s+"
    r"(?P<url>https?://\S+)",
    re.IGNORECASE,
)
USHARP_PLAYING_SYNCED_RE = re.compile(
    r"\[USharpVideo(?:\s*\([^)]+\))?\]\s+Playing synced\s+"
    r"(?P<url>https?://\S+)",
    re.IGNORECASE,
)
WANNADANCE_PREVIEW_RE = re.compile(
    r"\[VideoListManager\]\s+PreviewVideo:\s+"
    r"(?P<video_id>\d+)\s+"
    r"(?P<url>https?://\S+)"
    r"(?:,\s*time\s+(?P<preview_start>[\d.]+)\s*-\s*(?P<preview_end>[\d.]+))?",
    re.IGNORECASE,
)
WANNADANCE_QUEUE_INFO_RE = re.compile(
    r"\[VideoQueueManager\].*?:\s+"
    r"(?:OnPreSerialization:\s+queue info serialized:\s*|"
    r"OnDeserialization:\s+syncedQueuedInfoJson\s*=\s*)"
    r"(?P<payload>\[.*\])",
    re.IGNORECASE,
)
WANNADANCE_USER_DATA_RE = re.compile(
    r"\[VideoQueueManager\].*?:\s+DeserializeVideoUserData:\s+userData\s*=\s*"
    r"(?P<payload>\{.*\})",
    re.IGNORECASE,
)
WANNADANCE_PLAY_VIDEO_RE = re.compile(
    r"\[VideoQueueManager\].*?:\s+"
    r"(?P<action>PlayQueueVideo|PlayRandomVideo):\s+"
    r".*?\buserData\s*=\s*(?P<payload>\{.*\})\s*,\s*"
    r"videoDuration\s*=\s*(?P<duration>[\d.]+)",
    re.IGNORECASE,
)
VRCX_VIDEO_PLAY_RE = re.compile(
    r"\[VRCX\]\s+VideoPlay\((?P<world>[^)]+)\)\s*(?P<payload>.*)",
    re.IGNORECASE,
)
VRCX_LSMEDIA_RE = re.compile(
    r"\[VRCX\]\s+LSMedia\s*(?P<payload>.*)",
    re.IGNORECASE,
)
ROOM_LEFT_RE = re.compile(r"\[Behaviour\]\s+OnLeftRoom\b", re.IGNORECASE)
ROOM_ENTERING_RE = re.compile(
    r"\[Behaviour\]\s+Entering Room:\s*(?P<room_name>.+?)\s*$",
    re.IGNORECASE,
)
APPLICATION_QUIT_RE = re.compile(r"\bVRCApplication:\s+HandleApplicationQuit\b", re.IGNORECASE)
AVPRO_SHUTDOWN_RE = re.compile(r"\[AVProVideo\]\s+Shutdown\b", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedVrcLogEvent:
    """One parsed playback-like event from a VRChat output log line."""

    timestamp: str | None
    event_type: str
    video_url: str | None
    display_name: str | None
    parser_name: str
    raw_line: str
    world_parser: str | None = None
    video_name: str | None = None
    video_id: str | None = None
    requester_marker: str | None = None
    source_hint: str | None = None
    actual_play_at: str | None = None
    actual_play_signal_at: str | None = None
    actual_play_offset_seconds: float | None = None
    actual_play_method: str | None = None
    routed_url: str | None = None
    resolved_url: str | None = None
    video_offset_seconds: float | None = None
    duration_seconds: float | None = None
    duration_source: str | None = None
    load_seconds: float | None = None
    wait_seconds: float | None = None

    def to_capture_record(
        self,
        *,
        source_file: Path | str | None = None,
        line_number: int | None = None,
        byte_offset: int | None = None,
    ) -> dict:
        parsed = parse_dance_url(self.video_url)
        return {
            "captured_at": _utc_now(),
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "video_url": self.video_url,
            "display_name": self.display_name,
            "video_name": self.video_name,
            "video_id": self.video_id,
            "requester_marker": self.requester_marker,
            "source_hint": self.source_hint,
            "actual_play_at": self.actual_play_at,
            "actual_play_signal_at": self.actual_play_signal_at,
            "actual_play_offset_seconds": self.actual_play_offset_seconds,
            "actual_play_method": self.actual_play_method,
            "parser_name": self.parser_name,
            "world_parser": self.world_parser,
            "dance_system_key": parsed.system_key,
            "dance_external_id": parsed.external_id,
            "url_kind": parsed.url_kind,
            "parse_method": parsed.method,
            "routed_url": self.routed_url,
            "resolved_url": self.resolved_url,
            "video_offset_seconds": self.video_offset_seconds,
            "duration_seconds": self.duration_seconds,
            "duration_source": self.duration_source,
            "load_seconds": self.load_seconds,
            "wait_seconds": self.wait_seconds,
            "source_file": str(source_file) if source_file is not None else None,
            "line_number": line_number,
            "byte_offset": byte_offset,
            "raw_line": _trim_newline(self.raw_line),
        }


@dataclass
class WatchStats:
    """Summary of one watcher session."""

    session_dir: Path
    started_at: str
    ended_at: str | None = None
    raw_lines: int = 0
    candidate_lines: int = 0
    parsed_events: int = 0
    lifecycle_events: int = 0
    playback_events: int = 0
    delay_metrics: dict[str, float | int | None] = field(default_factory=dict)
    parser_counts: dict[str, int] = field(default_factory=dict)
    last_file: str | None = None
    last_offset: int = 0
    last_log_timestamp: str | None = None
    idle_stopped: bool = False
    live_session_id: str | None = None
    live_db_updates: int = 0
    live_promotions: int = 0
    overlay_url: str | None = None
    replayed_files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "session_dir": str(self.session_dir),
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "raw_lines": self.raw_lines,
            "candidate_lines": self.candidate_lines,
            "parsed_events": self.parsed_events,
            "lifecycle_events": self.lifecycle_events,
            "playback_events": self.playback_events,
            "delay_metrics": self.delay_metrics,
            "parser_counts": dict(sorted(self.parser_counts.items())),
            "last_file": self.last_file,
            "last_offset": self.last_offset,
            "last_log_timestamp": self.last_log_timestamp,
            "idle_stopped": self.idle_stopped,
            "live_session_id": self.live_session_id,
            "live_db_updates": self.live_db_updates,
            "live_promotions": self.live_promotions,
            "overlay_url": self.overlay_url,
            "replayed_files": self.replayed_files,
            "errors": self.errors,
        }


class _LivePlaybackRuntime:
    """Shared live DB and overlay side effects for tailing and offline replay."""

    def __init__(
        self,
        *,
        stats: WatchStats,
        app_db_path: Path | str | None,
        live_db: bool,
        promote_live: bool,
        overlay_port: int | None,
    ) -> None:
        self.stats = stats
        self.promote_live = promote_live
        self.app_conn = None
        self.overlay_server = None
        self.playback_builder = None
        self.live_events: dict[str, dict] = {}
        self.finalized_live_keys: set[str] = set()
        self.promoted_keys: set[str] = set()
        self.current_room_name: str | None = None

        if live_db or promote_live:
            from dancing_log.storage import (
                connect_db,
                mark_live_playback_event_completed,
                mark_live_playback_event_interrupted,
                make_live_playback_event_key,
                promote_live_playback_event,
                upsert_live_playback_event,
            )

            self.app_conn = connect_db(app_db_path)
            self.mark_live_playback_event_completed = mark_live_playback_event_completed
            self.mark_live_playback_event_interrupted = mark_live_playback_event_interrupted
            self.make_live_playback_event_key = make_live_playback_event_key
            self.promote_live_playback_event = promote_live_playback_event
            self.upsert_live_playback_event = upsert_live_playback_event
        else:
            self.mark_live_playback_event_completed = None
            self.mark_live_playback_event_interrupted = None
            self.make_live_playback_event_key = None
            self.promote_live_playback_event = None
            self.upsert_live_playback_event = None

        if overlay_port is not None:
            from dancing_log.overlay_server import OverlayServer

            self.overlay_server = OverlayServer(port=overlay_port)
            self.overlay_server.start()
            self.stats.overlay_url = self.overlay_server.url

    def close(self) -> None:
        if self.overlay_server is not None:
            self.overlay_server.stop()
            self.overlay_server = None
        if self.app_conn is not None:
            self.app_conn.close()
            self.app_conn = None

    def is_stale_observation(self, observed_at: str | None) -> bool:
        return _timestamp_before(observed_at, self.stats.last_log_timestamp)

    def promote_completed_event(self, live_event_key: str) -> None:
        if not self.promote_live or self.app_conn is None:
            return
        dance_event_id = self.promote_live_playback_event(self.app_conn, live_event_key)
        if dance_event_id is not None and live_event_key not in self.promoted_keys:
            self.promoted_keys.add(live_event_key)
            self.stats.live_promotions += 1

    def publish_live_settlement(
        self,
        event: dict,
        *,
        completion_status: str,
        observed_at: str,
        played_seconds: float | None,
        required_played_seconds: float | None,
        reason: str,
    ) -> None:
        event["completion_status"] = completion_status
        event["completion_reason"] = reason
        event["played_seconds"] = played_seconds
        event["required_played_seconds"] = required_played_seconds
        if completion_status == "completed":
            event["completed_at"] = observed_at
            event["interrupted_at"] = None
        else:
            event["completed_at"] = None
            event["interrupted_at"] = observed_at
        if self.overlay_server is not None:
            self.overlay_server.publish(event)

    def settle_live_event(
        self,
        event: dict,
        *,
        observed_at: str,
        interrupt_if_incomplete: bool,
        completion_reason: str,
        interrupt_reason: str,
    ) -> bool:
        if self.app_conn is None:
            return False
        live_event_key = event.get("live_event_key")
        if not live_event_key or live_event_key in self.finalized_live_keys:
            return False

        actual_play_at = event.get("actual_play_at")
        duration_seconds = _float_or_none(
            str(event.get("duration_seconds")) if event.get("duration_seconds") is not None else None
        )
        played_seconds_at_observed = (
            _seconds_between(actual_play_at, observed_at) if actual_play_at else None
        )
        if played_seconds_at_observed is not None and played_seconds_at_observed < 0:
            return False

        if event.get("observed_mid_play"):
            if not interrupt_if_incomplete:
                return False
            played_seconds = played_seconds_at_observed
            changed = self.mark_live_playback_event_interrupted(
                self.app_conn,
                live_event_key,
                interrupted_at=observed_at,
                played_seconds=played_seconds,
                required_played_seconds=duration_seconds,
                reason="observed_mid_play",
            )
            self.finalized_live_keys.add(live_event_key)
            if changed:
                self.publish_live_settlement(
                    event,
                    completion_status="interrupted",
                    observed_at=observed_at,
                    played_seconds=played_seconds,
                    required_played_seconds=duration_seconds,
                    reason="observed_mid_play",
                )
            return changed

        if not event.get("dance_system_key") or not event.get("dance_external_id"):
            return False

        if not actual_play_at:
            if not interrupt_if_incomplete:
                return False
            changed = self.mark_live_playback_event_interrupted(
                self.app_conn,
                live_event_key,
                interrupted_at=observed_at,
                played_seconds=None,
                required_played_seconds=duration_seconds,
                reason=interrupt_reason,
            )
            self.finalized_live_keys.add(live_event_key)
            if changed:
                self.publish_live_settlement(
                    event,
                    completion_status="interrupted",
                    observed_at=observed_at,
                    played_seconds=None,
                    required_played_seconds=duration_seconds,
                    reason=interrupt_reason,
                )
            return changed

        if duration_seconds is None or duration_seconds <= 0:
            if not interrupt_if_incomplete:
                return False
            reason = (
                "unknown_duration_before_superseded"
                if interrupt_reason == "superseded_before_completion"
                else interrupt_reason
            )
            played_seconds = played_seconds_at_observed
            changed = self.mark_live_playback_event_interrupted(
                self.app_conn,
                live_event_key,
                interrupted_at=observed_at,
                played_seconds=played_seconds,
                required_played_seconds=None,
                reason=reason,
            )
            self.finalized_live_keys.add(live_event_key)
            if changed:
                self.publish_live_settlement(
                    event,
                    completion_status="interrupted",
                    observed_at=observed_at,
                    played_seconds=played_seconds,
                    required_played_seconds=None,
                    reason=reason,
                )
            return changed

        played_seconds = played_seconds_at_observed
        required_played_seconds = duration_seconds * PROMOTION_COMPLETION_RATIO
        if played_seconds is None:
            return False
        if played_seconds + COMPLETION_EPSILON_SECONDS >= required_played_seconds:
            changed = self.mark_live_playback_event_completed(
                self.app_conn,
                live_event_key,
                completed_at=observed_at,
                played_seconds=played_seconds,
                required_played_seconds=required_played_seconds,
                reason=completion_reason,
            )
            self.promote_completed_event(live_event_key)
            self.finalized_live_keys.add(live_event_key)
            if changed:
                self.publish_live_settlement(
                    event,
                    completion_status="completed",
                    observed_at=observed_at,
                    played_seconds=played_seconds,
                    required_played_seconds=required_played_seconds,
                    reason=completion_reason,
                )
            return changed

        if not interrupt_if_incomplete:
            return False

        changed = self.mark_live_playback_event_interrupted(
            self.app_conn,
            live_event_key,
            interrupted_at=observed_at,
            played_seconds=played_seconds,
            required_played_seconds=required_played_seconds,
            reason=interrupt_reason,
        )
        self.finalized_live_keys.add(live_event_key)
        if changed:
            self.publish_live_settlement(
                event,
                completion_status="interrupted",
                observed_at=observed_at,
                played_seconds=played_seconds,
                required_played_seconds=required_played_seconds,
                reason=interrupt_reason,
            )
        return changed

    def settle_pending_events(
        self,
        *,
        observed_at: str,
        current_live_event_key: str | None = None,
        interrupt_others: bool = False,
        interrupt_started_others: bool = False,
        completion_reason: str = "observed_completion_threshold",
        interrupt_reason: str = "superseded_before_completion",
    ) -> bool:
        if self.is_stale_observation(observed_at):
            return False
        changed = False
        for live_event_key, event in list(self.live_events.items()):
            if live_event_key == current_live_event_key:
                continue
            interrupt_if_incomplete = interrupt_others or (
                interrupt_started_others and bool(event.get("actual_play_at"))
            )
            changed = (
                self.settle_live_event(
                    event,
                    observed_at=observed_at,
                    interrupt_if_incomplete=interrupt_if_incomplete,
                    completion_reason=completion_reason,
                    interrupt_reason=interrupt_reason,
                )
                or changed
            )
        return changed

    def handle_log_progress(self, timestamp: str | None) -> None:
        if not timestamp:
            return
        self.stats.last_log_timestamp = timestamp
        if self.app_conn is None:
            return
        try:
            if self.settle_pending_events(observed_at=timestamp):
                self.app_conn.commit()
        except Exception as exc:
            _record_error(self.stats.errors, f"live completion check failed: {exc}")
            self.app_conn.rollback()

    def handle_playback_update(self, event: dict) -> None:
        update = dict(event)
        update["live_session_id"] = self.stats.live_session_id
        if self.app_conn is not None:
            live_event_key = self.make_live_playback_event_key(
                self.stats.live_session_id,
                str(event["event_key"]),
            )
            update["live_event_key"] = live_event_key
            try:
                self.upsert_live_playback_event(
                    self.app_conn,
                    event,
                    session_id=self.stats.live_session_id,
                    event_key=live_event_key,
                )
                self.stats.live_db_updates += 1
                existing_update = self.live_events.get(live_event_key)
                if existing_update is not None and existing_update.get("completion_status"):
                    for field_name in (
                        "completion_status",
                        "completion_reason",
                        "completed_at",
                        "interrupted_at",
                        "played_seconds",
                        "required_played_seconds",
                    ):
                        update[field_name] = existing_update.get(field_name)
                self.live_events[live_event_key] = update
                actual_observed_at = event.get("actual_play_at")
                if actual_observed_at:
                    self.settle_pending_events(
                        observed_at=actual_observed_at,
                        current_live_event_key=live_event_key,
                        interrupt_others=True,
                    )
                else:
                    first_observed_at = event.get("first_seen_at")
                    if first_observed_at:
                        self.settle_pending_events(
                            observed_at=first_observed_at,
                            current_live_event_key=live_event_key,
                            interrupt_started_others=True,
                        )
                current_observed_at = event.get("last_seen_at") or actual_observed_at
                if current_observed_at and not self.is_stale_observation(current_observed_at):
                    self.settle_live_event(
                        update,
                        observed_at=current_observed_at,
                        interrupt_if_incomplete=False,
                        completion_reason="observed_completion_threshold",
                        interrupt_reason="superseded_before_completion",
                    )
                self.app_conn.commit()
            except Exception as exc:
                _record_error(self.stats.errors, f"live DB update failed: {exc}")
                self.app_conn.rollback()
        if self.overlay_server is not None:
            self.overlay_server.publish(update)

    def handle_lifecycle_event(self, event: dict) -> None:
        event_type = event.get("event_type")
        if event.get("room_name"):
            self.current_room_name = event.get("room_name")

        if event_type == "room-entering":
            if self.overlay_server is not None:
                self.overlay_server.publish_status(event)
            return

        if event_type not in {"room-left", "application-quit", "video-shutdown"}:
            return

        if self.playback_builder is not None:
            self.playback_builder.close_open_events()

        observed_at = event.get("observed_at") or event.get("timestamp") or self.stats.last_log_timestamp
        interrupt_reason = {
            "room-left": "room_left",
            "application-quit": "application_quit",
            "video-shutdown": "application_quit",
        }.get(str(event_type), "playback_stopped")

        if observed_at and self.app_conn is not None:
            try:
                if self.settle_pending_events(
                    observed_at=observed_at,
                    interrupt_others=True,
                    completion_reason="observed_completion_threshold",
                    interrupt_reason=interrupt_reason,
                ):
                    self.app_conn.commit()
            except Exception as exc:
                _record_error(self.stats.errors, f"live lifecycle settlement failed: {exc}")
                self.app_conn.rollback()

        if self.overlay_server is not None:
            status = dict(event)
            status["room_name"] = status.get("room_name") or self.current_room_name
            status["clear_current"] = True
            self.overlay_server.publish_status(status)

        if event_type in {"room-left", "application-quit"}:
            self.current_room_name = None


class PlaybackEventBuilder:
    """Fold line-level parser signals into per-song playback events."""

    def __init__(self, update_callback: Callable[[dict], None] | None = None) -> None:
        self._events: dict[str, dict] = {}
        self._open_by_canonical: dict[str, str] = {}
        self._occurrence_counts: dict[str, int] = {}
        self._preview_until_by_canonical: dict[str, datetime | None] = {}
        self._metadata_by_canonical: dict[str, dict] = {}
        self._active_key: str | None = None
        self._update_callback = update_callback

    def observe(self, record: dict) -> None:
        canonical_key = self._canonical_key_for_record(record)
        event_type = record.get("event_type")
        if event_type == "metadata":
            if canonical_key is not None:
                self._remember_metadata(canonical_key, record)
            return
        if event_type == "preview":
            if canonical_key is not None:
                self._mark_preview(canonical_key, record.get("timestamp"))
            return

        if canonical_key is not None and record.get("parser_name") in {"user_added_url", "vrcx_video_play"}:
            self._preview_until_by_canonical.pop(canonical_key, None)
        elif canonical_key is not None and self._is_preview_suppressed(canonical_key, record.get("timestamp")):
            return

        key = None
        if canonical_key is not None:
            key = self._event_key_for_record(canonical_key, record)
        timestamp = record.get("timestamp")

        if key is None and record.get("event_type") == "video-loaded":
            key = self._active_key
        if key is None and record.get("event_type") == "actual-play":
            key = self._active_key or self._key_for_actual_play(timestamp)
        if key is None:
            return

        event = self._events.setdefault(key, self._new_event(key))
        if canonical_key is not None and canonical_key in self._metadata_by_canonical:
            self._merge_signal(event, self._metadata_by_canonical[canonical_key])
        self._merge_signal(event, record)

        if record.get("video_url"):
            self._active_key = key
        if self._update_callback is not None:
            self._update_callback(self._finalize_event(event))

    def records(self) -> list[dict]:
        records = [self._finalize_event(event) for event in self._events.values()]
        return sorted(
            records,
            key=lambda event: (
                _timestamp_sort_key(event.get("first_seen_at")),
                event.get("event_key") or "",
            ),
        )

    def close_open_events(self) -> None:
        self._open_by_canonical.clear()
        self._active_key = None

    def _new_event(self, key: str, canonical_key: str | None = None) -> dict:
        return {
            "event_key": key,
            "canonical_key": canonical_key,
            "first_seen_at": None,
            "request_at": None,
            "load_started_at": None,
            "resolve_attempt_at": None,
            "resolved_at": None,
            "video_loaded_at": None,
            "expected_ready_at": None,
            "last_seen_at": None,
            "actual_play_at": None,
            "actual_play_signal_at": None,
            "actual_play_offset_seconds": None,
            "actual_play_method": None,
            "on_video_start_at": None,
            "synced_play_at": None,
            "observed_mid_play": False,
            "elapsed_at_first_seen_seconds": None,
            "video_url": None,
            "routed_url": None,
            "resolved_url": None,
            "dance_system_key": None,
            "dance_external_id": None,
            "url_kind": None,
            "video_name": None,
            "video_id": None,
            "display_name": None,
            "requester_marker": None,
            "source_hint": None,
            "source_type": None,
            "source_display_name": None,
            "world_parser": None,
            "duration_seconds": None,
            "duration_source": None,
            "load_seconds": None,
            "wait_seconds": None,
            "source_file": None,
            "first_line_number": None,
            "last_line_number": None,
            "signal_count": 0,
            "parser_names": set(),
            "raw_event_types": set(),
        }

    def _merge_signal(self, event: dict, record: dict) -> None:
        timestamp = record.get("timestamp")
        timestamp_dt = _parse_vrc_timestamp(timestamp)
        event_type = record.get("event_type")

        if event_type == "metadata":
            event["parser_names"].add(record.get("parser_name"))
            event["raw_event_types"].add(event_type)
            self._copy_first(event, record, "source_file")
            self._copy_first(event, record, "dance_system_key")
            self._copy_first(event, record, "dance_external_id")
            self._copy_first(event, record, "url_kind")
            self._copy_first(event, record, "world_parser")
            self._copy_first(event, record, "video_id")
            self._copy_first(event, record, "video_name")
            self._copy_first(event, record, "display_name")
            self._copy_first(event, record, "requester_marker")
            self._copy_first(event, record, "source_hint")
            self._merge_duration(event, record)
            for field_name in ("video_url", "routed_url", "resolved_url"):
                if event.get(field_name) in (None, "") and record.get(field_name):
                    event[field_name] = record[field_name]
            return

        if event["first_seen_at"] is None or _timestamp_sort_key(timestamp) < _timestamp_sort_key(event["first_seen_at"]):
            event["first_seen_at"] = timestamp
        if _timestamp_sort_key(timestamp) > _timestamp_sort_key(event.get("last_seen_at")):
            event["last_seen_at"] = timestamp
        event["signal_count"] += 1
        event["parser_names"].add(record.get("parser_name"))
        event["raw_event_types"].add(event_type)

        self._copy_first(event, record, "source_file")
        self._copy_first(event, record, "dance_system_key")
        self._copy_first(event, record, "dance_external_id")
        self._copy_first(event, record, "url_kind")
        self._copy_first(event, record, "world_parser")
        self._copy_first(event, record, "video_id")
        self._copy_first(event, record, "video_name")
        self._copy_first(event, record, "display_name")
        self._copy_first(event, record, "requester_marker")
        self._copy_first(event, record, "source_hint")
        self._merge_duration(event, record)

        for field_name in ("video_url", "routed_url", "resolved_url"):
            if record.get(field_name):
                event[field_name] = record[field_name]

        line_number = record.get("line_number")
        if isinstance(line_number, int):
            if event["first_line_number"] is None or line_number < event["first_line_number"]:
                event["first_line_number"] = line_number
            if event["last_line_number"] is None or line_number > event["last_line_number"]:
                event["last_line_number"] = line_number

        if event_type == "request":
            self._copy_time(event, "request_at", timestamp)
        elif event_type == "load-start":
            self._copy_time(event, "load_started_at", timestamp)
        elif event_type == "resolve-attempt":
            self._copy_time(event, "resolve_attempt_at", timestamp)
        elif event_type == "resolve-complete":
            self._copy_time(event, "resolved_at", timestamp)
        elif event_type == "video-loaded":
            self._copy_time(event, "video_loaded_at", timestamp)
            event["load_seconds"] = record.get("load_seconds")
            event["wait_seconds"] = record.get("wait_seconds")
            if timestamp_dt is not None and record.get("wait_seconds") is not None:
                event["expected_ready_at"] = _format_vrc_timestamp(
                    timestamp_dt + timedelta(seconds=float(record["wait_seconds"]))
                )
        elif event_type == "actual-play":
            self._copy_time(event, "actual_play_at", timestamp, prefer_latest=True)
            self._copy_time(event, "actual_play_signal_at", timestamp, prefer_latest=True)
            event["actual_play_method"] = (
                record.get("actual_play_method")
                or record.get("parser_name")
                or event.get("actual_play_method")
            )
        elif event_type == "playback-progress":
            self._copy_time(event, "actual_play_signal_at", timestamp)
            if event["actual_play_at"] is None:
                self._copy_time(event, "actual_play_at", record.get("actual_play_at") or timestamp)
            self._copy_first(event, record, "actual_play_offset_seconds")
            self._copy_first(event, record, "actual_play_method")
        elif event_type == "playback-sync":
            self._copy_time(event, "synced_play_at", timestamp)
        elif event_type == "on-video-start":
            self._copy_time(event, "on_video_start_at", timestamp, prefer_latest=True)
            if event["actual_play_at"] is None or event.get("actual_play_method") == "usharp_delayed_video_ready":
                self._copy_time(event, "actual_play_at", timestamp, prefer_latest=True)
                event["actual_play_method"] = record.get("parser_name")
            self._copy_time(event, "actual_play_signal_at", timestamp, prefer_latest=True)
            if event["actual_play_method"] is None:
                event["actual_play_method"] = record.get("parser_name")

    def _remember_metadata(self, canonical_key: str, record: dict) -> None:
        metadata = self._metadata_by_canonical.setdefault(canonical_key, dict(record))
        for field_name in (
            "video_url",
            "display_name",
            "video_name",
            "video_id",
            "requester_marker",
            "source_hint",
            "dance_system_key",
            "dance_external_id",
            "url_kind",
            "world_parser",
            "source_file",
        ):
            if metadata.get(field_name) in (None, "") and record.get(field_name) not in (None, ""):
                metadata[field_name] = record[field_name]
        self._merge_duration(metadata, record)

        current_key = self._open_by_canonical.get(canonical_key)
        if current_key is None:
            return
        current_event = self._events.get(current_key)
        if current_event is None:
            return
        self._merge_signal(current_event, record)
        if self._update_callback is not None:
            self._update_callback(self._finalize_event(current_event))

    def _finalize_event(self, event: dict) -> dict:
        finalized = dict(event)
        finalized["parser_names"] = sorted(name for name in event["parser_names"] if name)
        finalized["raw_event_types"] = sorted(name for name in event["raw_event_types"] if name)
        for set_field in ("parser_names", "raw_event_types"):
            if not finalized[set_field]:
                finalized[set_field] = []

        if finalized["actual_play_at"] is None and finalized["on_video_start_at"] is not None:
            finalized["actual_play_at"] = finalized["on_video_start_at"]

        source_type, source_display_name = _source_fields(finalized)
        finalized["source_type"] = source_type
        finalized["source_display_name"] = source_display_name

        delay_to_actual = _seconds_between(
            finalized.get("first_seen_at"),
            finalized.get("actual_play_at"),
        )
        if delay_to_actual is not None and delay_to_actual < 0:
            finalized["observed_mid_play"] = True
            finalized["elapsed_at_first_seen_seconds"] = round(abs(delay_to_actual), 3)
            finalized["delay_to_actual_seconds"] = None
        elif finalized.get("observed_mid_play"):
            finalized["elapsed_at_first_seen_seconds"] = None
            finalized["delay_to_actual_seconds"] = None
        else:
            finalized["elapsed_at_first_seen_seconds"] = None
            finalized["delay_to_actual_seconds"] = delay_to_actual
        finalized["load_to_actual_seconds"] = _seconds_between(
            finalized.get("video_loaded_at"),
            finalized.get("actual_play_at"),
        )
        finalized["request_to_resolve_seconds"] = _seconds_between(
            finalized.get("first_seen_at"),
            finalized.get("resolved_at"),
        )
        return finalized

    def _canonical_key_for_record(self, record: dict) -> str | None:
        url = record.get("video_url") or record.get("routed_url")
        if not url:
            return None
        parsed = parse_dance_url(url)
        if parsed.system_key and parsed.external_id:
            return f"{parsed.system_key}:{parsed.external_id}"
        return f"url:{url}"

    def _event_key_for_record(self, canonical_key: str, record: dict) -> str:
        current_key = self._open_by_canonical.get(canonical_key)
        current_event = self._events.get(current_key) if current_key is not None else None
        event_type = record.get("event_type")
        if event_type in {"request", "load-start"}:
            if current_key is None or current_event is None or current_event.get("actual_play_at"):
                return self._new_occurrence(canonical_key, record.get("timestamp"))
            return current_key
        if event_type in {"route", "resolve-attempt", "resolve-complete"} and current_event is not None:
            if current_event.get("actual_play_at") and not self._is_recent_same_occurrence(
                current_event,
                record.get("timestamp"),
            ):
                return self._new_occurrence(canonical_key, record.get("timestamp"))
            return current_key
        if current_key is None:
            return self._new_occurrence(canonical_key, record.get("timestamp"))
        return current_key

    @staticmethod
    def _is_recent_same_occurrence(event: dict, timestamp: str | None) -> bool:
        last_seen_at = event.get("last_seen_at") or event.get("actual_play_at")
        seconds_since_last_seen = _seconds_between(last_seen_at, timestamp)
        return seconds_since_last_seen is not None and 0 <= seconds_since_last_seen <= RETRY_MERGE_SECONDS

    def _new_occurrence(self, canonical_key: str, timestamp: str | None) -> str:
        count = self._occurrence_counts.get(canonical_key, 0) + 1
        self._occurrence_counts[canonical_key] = count
        event_key = f"{canonical_key}#{count}"
        self._events[event_key] = self._new_event(event_key, canonical_key)
        self._open_by_canonical[canonical_key] = event_key
        return event_key

    def _mark_preview(self, canonical_key: str, timestamp: str | None) -> None:
        timestamp_dt = _parse_vrc_timestamp(timestamp)
        if timestamp_dt is None:
            self._preview_until_by_canonical[canonical_key] = None
            return
        self._preview_until_by_canonical[canonical_key] = timestamp_dt + timedelta(
            seconds=PREVIEW_SUPPRESSION_SECONDS
        )

    def _is_preview_suppressed(self, canonical_key: str, timestamp: str | None) -> bool:
        if canonical_key not in self._preview_until_by_canonical:
            return False
        suppress_until = self._preview_until_by_canonical[canonical_key]
        if suppress_until is None:
            return True
        timestamp_dt = _parse_vrc_timestamp(timestamp)
        if timestamp_dt is None or timestamp_dt <= suppress_until:
            return True
        self._preview_until_by_canonical.pop(canonical_key, None)
        return False

    def _key_for_actual_play(self, timestamp: str | None) -> str | None:
        timestamp_dt = _parse_vrc_timestamp(timestamp)
        if timestamp_dt is None:
            return self._active_key

        best_key = None
        best_delta = None
        for key, event in self._events.items():
            if event.get("actual_play_at"):
                continue
            expected_dt = _parse_vrc_timestamp(event.get("expected_ready_at"))
            if expected_dt is None:
                continue
            delta = abs((timestamp_dt - expected_dt).total_seconds())
            if best_delta is None or delta < best_delta:
                best_key = key
                best_delta = delta
        if best_delta is not None and best_delta <= 3.0:
            return best_key
        return self._active_key

    @staticmethod
    def _copy_first(event: dict, record: dict, field_name: str) -> None:
        if event.get(field_name) in (None, "") and record.get(field_name) not in (None, ""):
            event[field_name] = record[field_name]

    @staticmethod
    def _merge_duration(event: dict, record: dict) -> None:
        incoming_duration = record.get("duration_seconds")
        if incoming_duration in (None, ""):
            return

        existing_duration = event.get("duration_seconds")
        incoming_source = record.get("duration_source")
        existing_source = event.get("duration_source")
        if existing_duration in (None, ""):
            event["duration_seconds"] = incoming_duration
            event["duration_source"] = incoming_source
            return

        if _duration_values_differ(existing_duration, incoming_duration):
            event.setdefault("duration_conflicts", []).append(
                {
                    "existing_duration_seconds": existing_duration,
                    "existing_duration_source": existing_source,
                    "incoming_duration_seconds": incoming_duration,
                    "incoming_duration_source": incoming_source,
                }
            )

        if _duration_source_priority(incoming_source) > _duration_source_priority(existing_source):
            event["duration_seconds"] = incoming_duration
            event["duration_source"] = incoming_source

    @staticmethod
    def _copy_time(
        event: dict,
        field_name: str,
        timestamp: str | None,
        *,
        prefer_latest: bool = False,
    ) -> None:
        if timestamp is None:
            return
        if event.get(field_name) is None:
            event[field_name] = timestamp
            return
        if prefer_latest and _timestamp_sort_key(timestamp) > _timestamp_sort_key(event[field_name]):
            event[field_name] = timestamp


def default_vrc_log_dir() -> Path:
    """Return VRChat's default Windows output log directory."""
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        local_path = Path(local_appdata)
        if local_path.name.lower() == "local":
            return local_path.with_name("LocalLow") / "VRChat" / "VRChat"
        return Path(f"{local_appdata}Low") / "VRChat" / "VRChat"
    return Path.home() / "AppData" / "LocalLow" / "VRChat" / "VRChat"


def is_video_candidate_line(line: str) -> bool:
    """Return true when the line is worth running heavier video parsers on."""
    folded = line.casefold()
    return any(token in folded for token in VIDEO_TOKENS)


def is_lifecycle_candidate_line(line: str) -> bool:
    """Return true when the line may describe a room or app lifecycle event."""
    folded = _strip_color_tags(line).casefold()
    return any(token in folded for token in LIFECYCLE_TOKENS)


def parse_vrc_lifecycle_event(line: str) -> dict | None:
    """Parse one VRChat output log line into a room/app lifecycle event."""
    if not is_lifecycle_candidate_line(line):
        return None

    timestamp = _extract_timestamp(line)
    plain_line = _strip_color_tags(line)

    if ROOM_LEFT_RE.search(plain_line):
        return _lifecycle_event(
            timestamp=timestamp,
            event_type="room-left",
            parser_name="vrc_room_left",
            message="Room left",
            raw_line=line,
            clear_current=True,
        )

    match = ROOM_ENTERING_RE.search(plain_line)
    if match:
        room_name = _clean_display_name(match.group("room_name"))
        message = f"Entering {room_name}" if room_name else "Entering room"
        return _lifecycle_event(
            timestamp=timestamp,
            event_type="room-entering",
            parser_name="vrc_room_entering",
            message=message,
            raw_line=line,
            room_name=room_name,
        )

    if APPLICATION_QUIT_RE.search(plain_line):
        return _lifecycle_event(
            timestamp=timestamp,
            event_type="application-quit",
            parser_name="vrc_application_quit",
            message="VRChat ended",
            raw_line=line,
            clear_current=True,
        )

    if AVPRO_SHUTDOWN_RE.search(plain_line):
        return _lifecycle_event(
            timestamp=timestamp,
            event_type="video-shutdown",
            parser_name="avpro_video_shutdown",
            message="VRChat ended",
            raw_line=line,
            clear_current=True,
        )

    return None


def parse_vrc_log_line(line: str) -> list[ParsedVrcLogEvent]:
    """Parse one VRChat output log line into zero or more playback events."""
    if not is_video_candidate_line(line):
        return []

    timestamp = _extract_timestamp(line)
    plain_line = _strip_color_tags(line)
    events: list[ParsedVrcLogEvent] = []

    match = WANNADANCE_PREVIEW_RE.search(plain_line)
    if match:
        events.append(
            ParsedVrcLogEvent(
                timestamp=timestamp,
                event_type="preview",
                video_url=_clean_url(match.group("url")),
                display_name=None,
                parser_name="wannadance_preview",
                raw_line=line,
                video_id=match.group("video_id"),
                source_hint="preview",
            )
        )

    match = WANNADANCE_QUEUE_INFO_RE.search(plain_line)
    if match:
        events.extend(
            _events_from_wannadance_queue_info(
                timestamp=timestamp,
                payload=match.group("payload"),
                raw_line=line,
            )
        )

    match = WANNADANCE_USER_DATA_RE.search(plain_line)
    if match:
        event = _event_from_wannadance_user_data(
            timestamp=timestamp,
            payload=match.group("payload"),
            raw_line=line,
        )
        if event is not None:
            events.append(event)

    match = WANNADANCE_PLAY_VIDEO_RE.search(plain_line)
    if match:
        event = _event_from_wannadance_play_video(
            timestamp=timestamp,
            payload=match.group("payload"),
            duration=match.group("duration"),
            raw_line=line,
        )
        if event is not None:
            events.append(event)

    match = VIDEO_PLAYBACK_RE.search(plain_line)
    if match:
        events.append(
            ParsedVrcLogEvent(
                timestamp=timestamp,
                event_type="resolve-attempt",
                video_url=_clean_url(match.group("url")),
                display_name=None,
                parser_name="video_playback_resolve",
                raw_line=line,
            )
        )

    match = VIDEO_RESOLVED_RE.search(plain_line)
    if match:
        events.append(
            ParsedVrcLogEvent(
                timestamp=timestamp,
                event_type="resolve-complete",
                video_url=_clean_url(match.group("url")),
                display_name=None,
                parser_name="video_playback_resolved",
                raw_line=line,
                resolved_url=_clean_url(match.group("resolved_url")),
            )
        )

    match = USER_ADDED_URL_RE.search(plain_line)
    if match:
        events.append(
            ParsedVrcLogEvent(
                timestamp=timestamp,
                event_type="request",
                video_url=_clean_url(match.group("url")),
                display_name=_clean_display_name(match.group("display_name")),
                parser_name="user_added_url",
                raw_line=line,
            )
        )

    match = USHARP_PLAY_INTERNAL_RE.search(plain_line)
    if match:
        events.append(
            ParsedVrcLogEvent(
                timestamp=timestamp,
                event_type="request",
                video_url=_clean_url(match.group("url")),
                display_name=None,
                parser_name="usharp_play_internal",
                raw_line=line,
            )
        )

    match = USHARP_VIDEO_RE.search(plain_line)
    if match:
        events.append(
            ParsedVrcLogEvent(
                timestamp=timestamp,
                event_type="load-start",
                video_url=_clean_url(match.group("url")),
                display_name=_clean_display_name(match.group("display_name")),
                parser_name="usharp_video_load",
                raw_line=line,
            )
        )

    match = USHARP_LOAD_ROUTED_RE.search(plain_line)
    if match:
        events.append(
            ParsedVrcLogEvent(
                timestamp=timestamp,
                event_type="route",
                video_url=_clean_url(match.group("url")),
                display_name=None,
                parser_name="usharp_load_routed_url",
                raw_line=line,
                routed_url=_clean_url(match.group("routed_url")),
            )
        )

    match = USHARP_VIDEO_LOADED_RE.search(plain_line)
    if match:
        events.append(
            ParsedVrcLogEvent(
                timestamp=timestamp,
                event_type="video-loaded",
                video_url=None,
                display_name=None,
                parser_name="usharp_video_loaded",
                raw_line=line,
                load_seconds=_float_or_none(match.group("load_seconds")),
                wait_seconds=_float_or_none(match.group("wait_seconds")),
            )
        )

    match = USHARP_DELAYED_READY_RE.search(plain_line)
    if match:
        events.append(
            ParsedVrcLogEvent(
                timestamp=timestamp,
                event_type="actual-play",
                video_url=None,
                display_name=None,
                parser_name="usharp_delayed_video_ready",
                raw_line=line,
            )
        )

    match = USHARP_ON_VIDEO_START_RE.search(plain_line)
    if match:
        events.append(
            ParsedVrcLogEvent(
                timestamp=timestamp,
                event_type="on-video-start",
                video_url=_clean_url(match.group("url")),
                display_name=None,
                parser_name="usharp_on_video_start",
                raw_line=line,
            )
        )

    match = USHARP_PLAYING_SYNCED_RE.search(plain_line)
    if match:
        events.append(
            ParsedVrcLogEvent(
                timestamp=timestamp,
                event_type="playback-sync",
                video_url=_clean_url(match.group("url")),
                display_name=None,
                parser_name="usharp_playing_synced",
                raw_line=line,
            )
        )

    match = VRCX_VIDEO_PLAY_RE.search(plain_line)
    if match:
        events.extend(
            _events_from_payload(
                timestamp=timestamp,
                payload=match.group("payload"),
                parser_name="vrcx_video_play",
                raw_line=line,
                world_parser=match.group("world").strip() or None,
            )
        )

    match = VRCX_LSMEDIA_RE.search(plain_line)
    if match:
        events.extend(
            _events_from_payload(
                timestamp=timestamp,
                payload=match.group("payload"),
                parser_name="vrcx_lsmedia",
                raw_line=line,
                world_parser="LSMedia",
            )
        )

    return _dedupe_events(events)


def _events_from_wannadance_queue_info(
    *,
    timestamp: str | None,
    payload: str,
    raw_line: str,
) -> list[ParsedVrcLogEvent]:
    value = _try_json(payload)
    if not isinstance(value, list):
        return []
    events: list[ParsedVrcLogEvent] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        song_id = entry.get("songId") or entry.get("song_id") or entry.get("id")
        title = entry.get("title") or entry.get("videoTitle")
        player_names = entry.get("playerNames") or entry.get("player_names") or []
        display_name = None
        if isinstance(player_names, list):
            names = [_clean_display_name(str(name)) for name in player_names]
            names = [name for name in names if name]
            display_name = " / ".join(names) if names else None
        elif isinstance(player_names, str):
            display_name = _clean_display_name(player_names)
        events.append(
            _wanna_metadata_event(
                timestamp=timestamp,
                raw_line=raw_line,
                parser_name="wannadance_queue_info",
                song_id=song_id,
                video_url=entry.get("videoUrl") or entry.get("video_url"),
                title=title,
                display_name=display_name,
                is_random=entry.get("isRandom"),
                duration_seconds=_float_or_none(
                    str(entry.get("duration")) if entry.get("duration") is not None else None
                ),
                duration_source="wanna_queue_json",
            )
        )
    return [event for event in events if event is not None]


def _event_from_wannadance_user_data(
    *,
    timestamp: str | None,
    payload: str,
    raw_line: str,
) -> ParsedVrcLogEvent | None:
    value = _try_json(payload)
    if not isinstance(value, dict):
        return None
    return _wanna_metadata_event(
        timestamp=timestamp,
        raw_line=raw_line,
        parser_name="wannadance_user_data",
        song_id=value.get("songId") or value.get("song_id") or value.get("id"),
        video_url=value.get("videoUrl") or value.get("video_url"),
        title=value.get("videoTitle") or value.get("title") or value.get("name"),
        display_name=value.get("playerName") or value.get("displayName"),
        is_random=value.get("isRandom"),
        duration_seconds=_float_or_none(
            str(value.get("duration")) if value.get("duration") is not None else None
        ),
        duration_source="wanna_queue_json",
    )


def _event_from_wannadance_play_video(
    *,
    timestamp: str | None,
    payload: str,
    duration: str,
    raw_line: str,
) -> ParsedVrcLogEvent | None:
    value = _try_json(payload)
    if not isinstance(value, dict):
        return None
    return _wanna_metadata_event(
        timestamp=timestamp,
        raw_line=raw_line,
        parser_name="wannadance_play_video",
        song_id=value.get("songId") or value.get("song_id") or value.get("id"),
        video_url=value.get("videoUrl") or value.get("video_url"),
        title=value.get("videoTitle") or value.get("title") or value.get("infoString"),
        display_name=value.get("playerName") or value.get("displayName"),
        is_random=value.get("isRandom"),
        duration_seconds=_float_or_none(duration),
        duration_source="wanna_video_duration",
    )


def _wanna_metadata_event(
    *,
    timestamp: str | None,
    raw_line: str,
    parser_name: str,
    song_id,
    video_url,
    title,
    display_name,
    is_random,
    duration_seconds: float | None,
    duration_source: str | None,
) -> ParsedVrcLogEvent | None:
    song_id_text = str(song_id).strip() if song_id is not None else ""
    if not song_id_text and not video_url:
        return None

    clean_url = _clean_url(str(video_url)) if video_url else _wanna_video_url(song_id_text)
    title_id, video_name, requester_marker = _parse_video_title_payload(str(title or ""))
    video_id = song_id_text or title_id
    random_source = _truthy(is_random)
    clean_display_name = None if random_source else _clean_display_name(str(display_name)) if display_name is not None else None
    source_hint = "random" if random_source else None

    return ParsedVrcLogEvent(
        timestamp=timestamp,
        event_type="metadata",
        video_url=clean_url,
        display_name=clean_display_name,
        parser_name=parser_name,
        raw_line=raw_line,
        video_name=video_name,
        video_id=video_id or None,
        requester_marker=requester_marker,
        source_hint=source_hint,
        duration_seconds=duration_seconds,
        duration_source=duration_source if duration_seconds is not None else None,
    )


def watch_vrc_logs(
    *,
    log_dir: Path | str | None = None,
    output_dir: Path | str | None = None,
    session_name: str | None = None,
    app_db_path: Path | str | None = None,
    from_start: bool = False,
    include_raw: bool = True,
    live_db: bool = False,
    promote_live: bool = False,
    overlay_port: int | None = None,
    poll_seconds: float = 0.25,
    stop_after_idle_seconds: float | None = None,
) -> WatchStats:
    """Tail VRChat output logs and write raw/candidate/parsed capture artifacts."""
    resolved_log_dir = Path(log_dir) if log_dir is not None else default_vrc_log_dir()
    capture_root = Path(output_dir) if output_dir is not None else DEFAULT_CAPTURE_ROOT
    session_dir = capture_root / (session_name or datetime.now().strftime("%Y-%m-%d_%H%M%S"))
    session_dir.mkdir(parents=True, exist_ok=True)

    stats = WatchStats(session_dir=session_dir, started_at=_utc_now())
    stats.live_session_id = _live_session_id(session_dir, stats.started_at)
    initial_latest = _latest_log_file(resolved_log_dir, stats.errors)
    opened_any_file = False
    current_path: Path | None = None
    current_handle = None
    current_line_number = 0
    idle_since = time.monotonic()
    runtime = _LivePlaybackRuntime(
        stats=stats,
        app_db_path=app_db_path,
        live_db=live_db,
        promote_live=promote_live,
        overlay_port=overlay_port,
    )
    playback_builder = PlaybackEventBuilder(update_callback=runtime.handle_playback_update)
    runtime.playback_builder = playback_builder

    raw_handle = None
    candidates_handle = None
    parsed_handle = None

    try:
        if include_raw:
            raw_handle = open(
                session_dir / "raw_output_log.txt",
                "a",
                encoding="utf-8",
                errors="replace",
                buffering=1,
            )
        candidates_handle = open(
            session_dir / "candidates.jsonl",
            "a",
            encoding="utf-8",
            buffering=1,
        )
        parsed_handle = open(
            session_dir / "parsed_events.jsonl",
            "a",
            encoding="utf-8",
            buffering=1,
        )

        while True:
            latest_path = _latest_log_file(resolved_log_dir, stats.errors)
            if latest_path and latest_path != current_path:
                if current_path is None or _is_newer_log(latest_path, current_path):
                    if current_handle is not None:
                        current_handle.close()
                    current_path = latest_path
                    current_line_number = 0
                    start_offset = _start_offset(
                        latest_path,
                        initial_latest=initial_latest,
                        opened_any_file=opened_any_file,
                        from_start=from_start,
                    )
                    current_handle = open(
                        latest_path,
                        "r",
                        encoding="utf-8",
                        errors="replace",
                    )
                    current_handle.seek(start_offset)
                    stats.last_file = str(latest_path)
                    stats.last_offset = start_offset
                    opened_any_file = True
                    idle_since = time.monotonic()

            made_progress = False
            if current_handle is not None and current_path is not None:
                made_progress, current_line_number = _drain_handle(
                    current_handle=current_handle,
                    current_path=current_path,
                    raw_handle=raw_handle,
                    candidates_handle=candidates_handle,
                    parsed_handle=parsed_handle,
                    stats=stats,
                    playback_builder=playback_builder,
                    line_number=current_line_number,
                    line_timestamp_callback=runtime.handle_log_progress,
                    lifecycle_event_callback=runtime.handle_lifecycle_event,
                )

                try:
                    if current_path.stat().st_size < stats.last_offset:
                        current_handle.close()
                        current_handle = None
                        current_path = None
                        current_line_number = 0
                except OSError as exc:
                    _record_error(stats.errors, f"stat failed for {current_path}: {exc}")

            if made_progress:
                idle_since = time.monotonic()
            else:
                if (
                    stop_after_idle_seconds is not None
                    and time.monotonic() - idle_since >= stop_after_idle_seconds
                ):
                    stats.idle_stopped = True
                    break
                time.sleep(max(poll_seconds, 0.01))
    except KeyboardInterrupt:
        pass
    finally:
        stats.ended_at = _utc_now()
        if current_handle is not None:
            current_handle.close()
        for handle in (raw_handle, candidates_handle, parsed_handle):
            if handle is not None:
                handle.close()
        playback_records = playback_builder.records()
        stats.playback_events = len(playback_records)
        stats.delay_metrics = _delay_metrics(playback_records)
        _write_jsonl_file(session_dir / "playback_events.jsonl", playback_records)
        _write_json(session_dir / "summary.json", stats.to_dict())
        runtime.close()

    return stats


def replay_vrc_log_files(
    *,
    log_files: list[Path | str],
    output_dir: Path | str,
    session_name: str | None = None,
    app_db_path: Path | str | None = None,
    include_raw: bool = True,
    live_db: bool = True,
    promote_live: bool = False,
) -> WatchStats:
    """Replay a fixed sequence of VRChat logs into capture artifacts."""
    replay_files = sorted((Path(path) for path in log_files), key=lambda path: path.name)
    capture_root = Path(output_dir)
    session_dir = capture_root / session_name if session_name else capture_root
    session_dir.mkdir(parents=True, exist_ok=True)

    default_db_path: Path | None = None
    if (live_db or promote_live) and app_db_path is None:
        default_db_path = session_dir / "live.sqlite3"
        if default_db_path.exists():
            default_db_path.unlink()
        app_db_path = default_db_path

    stats = WatchStats(session_dir=session_dir, started_at=_utc_now())
    stats.live_session_id = _live_session_id(session_dir, stats.started_at)
    stats.replayed_files = [str(path) for path in replay_files]
    runtime = _LivePlaybackRuntime(
        stats=stats,
        app_db_path=app_db_path,
        live_db=live_db,
        promote_live=promote_live,
        overlay_port=None,
    )
    playback_builder = PlaybackEventBuilder(update_callback=runtime.handle_playback_update)
    runtime.playback_builder = playback_builder

    raw_handle = None
    candidates_handle = None
    parsed_handle = None

    try:
        if include_raw:
            raw_handle = open(
                session_dir / "raw_output_log.txt",
                "w",
                encoding="utf-8",
                errors="replace",
                buffering=1,
            )
        candidates_handle = open(
            session_dir / "candidates.jsonl",
            "w",
            encoding="utf-8",
            buffering=1,
        )
        parsed_handle = open(
            session_dir / "parsed_events.jsonl",
            "w",
            encoding="utf-8",
            buffering=1,
        )

        for path in replay_files:
            with open(path, "r", encoding="utf-8", errors="replace") as current_handle:
                _drain_handle(
                    current_handle=current_handle,
                    current_path=path,
                    raw_handle=raw_handle,
                    candidates_handle=candidates_handle,
                    parsed_handle=parsed_handle,
                    stats=stats,
                    playback_builder=playback_builder,
                    line_number=0,
                    line_timestamp_callback=runtime.handle_log_progress,
                    lifecycle_event_callback=runtime.handle_lifecycle_event,
                )
    finally:
        stats.ended_at = _utc_now()
        for handle in (raw_handle, candidates_handle, parsed_handle):
            if handle is not None:
                handle.close()
        playback_records = playback_builder.records()
        stats.playback_events = len(playback_records)
        stats.delay_metrics = _delay_metrics(playback_records)
        _write_jsonl_file(session_dir / "playback_events.jsonl", playback_records)
        _write_json(session_dir / "summary.json", stats.to_dict())
        runtime.close()

    return stats


def _drain_handle(
    *,
    current_handle,
    current_path: Path,
    raw_handle,
    candidates_handle,
    parsed_handle,
    stats: WatchStats,
    playback_builder: PlaybackEventBuilder,
    line_number: int,
    line_timestamp_callback: Callable[[str | None], None] | None = None,
    lifecycle_event_callback: Callable[[dict], None] | None = None,
) -> tuple[bool, int]:
    made_progress = False
    while True:
        byte_offset = current_handle.tell()
        line = current_handle.readline()
        if not line:
            break

        made_progress = True
        line_number += 1
        stats.raw_lines += 1
        stats.last_file = str(current_path)
        stats.last_offset = current_handle.tell()
        timestamp = _extract_timestamp(line)
        timestamp_for_settlement = timestamp
        if timestamp and not _timestamp_before(timestamp, stats.last_log_timestamp):
            stats.last_log_timestamp = timestamp
        elif timestamp:
            timestamp_for_settlement = None
        if line_timestamp_callback is not None:
            line_timestamp_callback(timestamp_for_settlement)

        if raw_handle is not None:
            raw_handle.write(line)

        lifecycle_event = parse_vrc_lifecycle_event(line)
        if lifecycle_event is not None:
            stats.lifecycle_events += 1
            lifecycle_event["source_file"] = str(current_path)
            lifecycle_event["line_number"] = line_number
            lifecycle_event["byte_offset"] = byte_offset
            if lifecycle_event_callback is not None:
                lifecycle_event_callback(lifecycle_event)

        if not is_video_candidate_line(line):
            continue

        stats.candidate_lines += 1
        _write_jsonl(
            candidates_handle,
            {
                "captured_at": _utc_now(),
                "source_file": str(current_path),
                "line_number": line_number,
                "byte_offset": byte_offset,
                "raw_line": _trim_newline(line),
            },
        )

        for event in parse_vrc_log_line(line):
            stats.parsed_events += 1
            stats.parser_counts[event.parser_name] = (
                stats.parser_counts.get(event.parser_name, 0) + 1
            )
            record = event.to_capture_record(
                source_file=current_path,
                line_number=line_number,
                byte_offset=byte_offset,
            )
            _write_jsonl(
                parsed_handle,
                record,
            )
            playback_builder.observe(record)
    return made_progress, line_number


def _events_from_payload(
    *,
    timestamp: str | None,
    payload: str,
    parser_name: str,
    raw_line: str,
    world_parser: str | None,
) -> list[ParsedVrcLogEvent]:
    parsed_payload = _parse_video_play_payload(payload)
    urls = parsed_payload["urls"]
    if not urls:
        return []

    event_type = "request"
    actual_play_at = None
    actual_play_signal_at = None
    actual_play_offset_seconds = None
    actual_play_method = None
    video_offset_seconds = parsed_payload["video_offset_seconds"]
    if video_offset_seconds is not None and video_offset_seconds > 0:
        event_type = "playback-progress"
        actual_play_signal_at = timestamp
        actual_play_offset_seconds = video_offset_seconds
        actual_play_method = "vrcx_progress_offset"
        timestamp_dt = _parse_vrc_timestamp(timestamp)
        if timestamp_dt is not None:
            actual_play_at = _format_vrc_timestamp(
                timestamp_dt - timedelta(seconds=video_offset_seconds)
            )

    return [
        ParsedVrcLogEvent(
            timestamp=timestamp,
            event_type=event_type,
            video_url=url,
            display_name=parsed_payload["display_name"],
            parser_name=parser_name,
            raw_line=raw_line,
            world_parser=world_parser,
            video_name=parsed_payload["video_name"],
            video_id=parsed_payload["video_id"],
            requester_marker=parsed_payload["requester_marker"],
            source_hint=parsed_payload["source_hint"],
            actual_play_at=actual_play_at,
            actual_play_signal_at=actual_play_signal_at,
            actual_play_offset_seconds=actual_play_offset_seconds,
            actual_play_method=actual_play_method,
            video_offset_seconds=video_offset_seconds,
            duration_seconds=parsed_payload["duration_seconds"],
            duration_source="vrcx_payload" if parsed_payload["duration_seconds"] is not None else None,
        )
        for url in urls
    ]


def _parse_video_play_payload(payload: str) -> dict:
    fields = _csv_fields(payload)
    urls = _extract_urls(payload)
    display_name = _display_name_from_payload(payload)
    video_offset_seconds = None
    duration_seconds = None
    video_name = None
    video_id = None
    requester_marker = None
    source_hint = None

    if fields:
        url_index = next((index for index, field in enumerate(fields) if URL_RE.search(field)), None)
        if url_index is not None:
            trailing = fields[url_index + 1 :]
            if trailing:
                video_offset_seconds = _float_or_none(trailing[0])
                if video_offset_seconds is not None:
                    display_name = None
            if len(trailing) > 1:
                duration_seconds = _float_or_none(trailing[1])
                if duration_seconds == 114514:
                    duration_seconds = None
            if len(trailing) > 2:
                title_payload = trailing[2]
                video_id, video_name, requester_marker = _parse_video_title_payload(title_payload)
                if requester_marker:
                    if requester_marker.casefold() == "random":
                        source_hint = "random"
                    else:
                        display_name = requester_marker
                        source_hint = "requester_marker"
            elif len(trailing) == 1 and video_offset_seconds is None and display_name is None:
                display_name = _clean_display_name(trailing[0])

    structured = _try_json(payload)
    if structured is not None:
        structured_name = _find_key(structured, {"name", "title", "videoname", "video_name"})
        structured_id = _find_key(structured, {"id", "videoid", "video_id"})
        if isinstance(structured_name, str):
            video_name = video_name or _clean_display_name(structured_name)
        if structured_id is not None:
            video_id = video_id or str(structured_id)

    return {
        "urls": urls,
        "display_name": display_name,
        "video_name": video_name,
        "video_id": video_id,
        "requester_marker": requester_marker,
        "source_hint": source_hint,
        "video_offset_seconds": video_offset_seconds,
        "duration_seconds": duration_seconds,
    }


def _parse_video_title_payload(value: str) -> tuple[str | None, str | None, str | None]:
    text = _clean_display_name(value) or ""
    requester_marker = None
    marker_match = re.search(r"\((?P<marker>[^()]*)\)\s*$", text)
    if marker_match:
        requester_marker = _clean_display_name(marker_match.group("marker"))
        text = text[: marker_match.start()].strip()

    video_id = None
    id_match = re.match(r"^\$?(?P<id>\d+)(?:\.\s*|\s*:\s*)(?P<title>.*)$", text)
    if id_match:
        video_id = id_match.group("id")
        text = id_match.group("title").strip()

    return video_id, text or None, requester_marker


def _display_name_from_payload(payload: str) -> str | None:
    structured = _try_json(payload)
    if structured is not None:
        value = _find_key(structured, {"displayname", "display_name", "requester", "user"})
        if isinstance(value, str):
            return _clean_display_name(value)

    fields = _csv_fields(payload)
    for index, field in enumerate(fields):
        if URL_RE.search(field):
            for candidate in fields[index + 1 :]:
                if candidate.strip() and not URL_RE.search(candidate):
                    return _clean_display_name(candidate)
    return None


def _extract_urls(payload: str) -> list[str]:
    structured = _try_json(payload)
    urls: list[str] = []
    if structured is not None:
        value = _find_key(structured, {"url", "videourl", "video_url"})
        if isinstance(value, str):
            urls.append(value)

    fields = _csv_fields(payload)
    for field in fields:
        urls.extend(match.group(0) for match in URL_RE.finditer(field))

    if not urls:
        urls.extend(match.group(0) for match in URL_RE.finditer(payload))

    cleaned: list[str] = []
    seen: set[str] = set()
    for url in urls:
        clean = _clean_url(url)
        if clean and clean not in seen:
            cleaned.append(clean)
            seen.add(clean)
    return cleaned


def _lifecycle_event(
    *,
    timestamp: str | None,
    event_type: str,
    parser_name: str,
    message: str,
    raw_line: str,
    clear_current: bool = False,
    room_name: str | None = None,
) -> dict:
    return {
        "captured_at": _utc_now(),
        "timestamp": timestamp,
        "observed_at": timestamp,
        "event_type": event_type,
        "parser_name": parser_name,
        "message": message,
        "room_name": room_name,
        "clear_current": clear_current,
        "raw_line": _trim_newline(raw_line),
    }


def _latest_log_file(log_dir: Path, errors: list[str]) -> Path | None:
    try:
        candidates = [path for path in log_dir.glob(LOG_FILE_PATTERN) if path.is_file()]
    except OSError as exc:
        _record_error(errors, f"cannot list {log_dir}: {exc}")
        return None
    if not candidates:
        return None
    return max(candidates, key=lambda path: (_mtime_ns(path), path.name))


def _is_newer_log(candidate: Path, current: Path) -> bool:
    return (_mtime_ns(candidate), candidate.name) > (_mtime_ns(current), current.name)


def _mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _start_offset(
    path: Path,
    *,
    initial_latest: Path | None,
    opened_any_file: bool,
    from_start: bool,
) -> int:
    if from_start:
        return 0
    if not opened_any_file and initial_latest is not None and path == initial_latest:
        try:
            return path.stat().st_size
        except OSError:
            return 0
    return 0


def _extract_timestamp(line: str) -> str | None:
    match = TIMESTAMP_RE.match(line)
    return match.group("timestamp") if match else None


def _parse_vrc_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y.%m.%d %H:%M:%S.%f", "%Y.%m.%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def _format_vrc_timestamp(value: datetime) -> str:
    text = value.strftime("%Y.%m.%d %H:%M:%S.%f")
    return text.rstrip("0").rstrip(".")


def _timestamp_sort_key(value: str | None) -> str:
    parsed = _parse_vrc_timestamp(value)
    if parsed is None:
        return ""
    return parsed.isoformat()


def _timestamp_before(left: str | None, right: str | None) -> bool:
    left_key = _timestamp_sort_key(left)
    right_key = _timestamp_sort_key(right)
    return bool(left_key and right_key and left_key < right_key)


def _seconds_between(start: str | None, end: str | None) -> float | None:
    start_dt = _parse_vrc_timestamp(start)
    end_dt = _parse_vrc_timestamp(end)
    if start_dt is None or end_dt is None:
        return None
    return round((end_dt - start_dt).total_seconds(), 3)


def _delay_metrics(playback_records: list[dict]) -> dict[str, float | int | None]:
    delays = [
        float(record["delay_to_actual_seconds"])
        for record in playback_records
        if record.get("delay_to_actual_seconds") is not None
    ]
    if not delays:
        return {
            "count": 0,
            "min_seconds": None,
            "max_seconds": None,
            "avg_seconds": None,
        }
    return {
        "count": len(delays),
        "min_seconds": round(min(delays), 3),
        "max_seconds": round(max(delays), 3),
        "avg_seconds": round(sum(delays) / len(delays), 3),
    }


def _source_fields(event: dict) -> tuple[str, str | None]:
    source_hint = (event.get("source_hint") or "").casefold()
    requester_marker = _clean_display_name(event.get("requester_marker"))
    display_name = _clean_display_name(event.get("display_name"))

    if source_hint == "random" or (requester_marker or "").casefold() == "random":
        return "random", None
    if source_hint == "requester_marker" and requester_marker:
        return "player", requester_marker
    if display_name and display_name.casefold() != "random":
        return "player", display_name
    return "unknown", None


def _strip_color_tags(line: str) -> str:
    return COLOR_TAG_RE.sub("", line)


def _float_or_none(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _duration_values_differ(left, right) -> bool:
    try:
        return abs(float(left) - float(right)) > COMPLETION_EPSILON_SECONDS
    except (TypeError, ValueError):
        return left != right


def _duration_source_priority(source: str | None) -> int:
    return {
        "wanna_queue_json": 10,
        "vrcx_payload": 20,
        "wanna_video_duration": 30,
    }.get(source or "", 0)


def _clean_url(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().strip("\"'").rstrip(".,);]}")


def _wanna_video_url(song_id: str) -> str:
    return f"http://api.udon.dance/Api/Songs/play?id={song_id}"


def _clean_display_name(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().strip("\"'")
    return cleaned or None


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes"}
    return bool(value)


def _trim_newline(value: str) -> str:
    return value.rstrip("\r\n")


def _dedupe_events(events: list[ParsedVrcLogEvent]) -> list[ParsedVrcLogEvent]:
    deduped: list[ParsedVrcLogEvent] = []
    seen: set[tuple[str, str | None, str]] = set()
    for event in events:
        key = (event.video_url, event.display_name, event.parser_name)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(event)
    return deduped


def _try_json(payload: str):
    text = payload.strip()
    if not text.startswith(("{", "[")):
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _csv_fields(payload: str) -> list[str]:
    try:
        return next(csv.reader([payload], skipinitialspace=True))
    except csv.Error:
        return []


def _find_key(value, keys: set[str]):
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).replace("-", "_").replace(" ", "_").lower() in keys:
                return child
        for child in value.values():
            found = _find_key(child, keys)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_key(child, keys)
            if found is not None:
                return found
    return None


def _write_json(path: Path, value: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _write_jsonl(handle, value: dict) -> None:
    json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
    handle.write("\n")


def _write_jsonl_file(path: Path, values: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for value in values:
            _write_jsonl(handle, value)


def _record_error(errors: list[str], message: str) -> None:
    if not errors or errors[-1] != message:
        errors.append(message)


def _live_session_id(session_dir: Path, started_at: str) -> str:
    return f"{session_dir.name}:{started_at}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
