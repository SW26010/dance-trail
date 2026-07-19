"""Parse raw VRChat output log lines into playback-like signals."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import timedelta
import json
from pathlib import Path
import re

from dancing_log.time_utils import now_utc_iso
from dancing_log.vrc_log_utils import (
    clean_display_name as _clean_display_name,
    extract_timestamp as _extract_timestamp,
    float_or_none as _float_or_none,
    format_vrc_timestamp as _format_vrc_timestamp,
    parse_vrc_timestamp as _parse_vrc_timestamp,
    trim_newline as _trim_newline,
)
from dancing_log.vrcx_importer import parse_dance_url

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
    "videoqueuehandler",
    "dudufit.dance",
)
LIFECYCLE_TOKENS = (
    "onleftroom",
    "entering room:",
    "handleapplicationquit",
    "[avprovideo] shutdown",
)
IDENTITY_TOKENS = (
    "onplayerjoined",
    "onplayerleft",
    "user authenticated:",
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
DUDU_QUEUE_DATA_RE = re.compile(
    r"\[VideoQueueHandler\.OnDeserialization\]\s+Queue data\s*=\s*(?P<payload>\[.*\])",
    re.IGNORECASE,
)
DUDU_SONG_DATA_RE = re.compile(
    r"\[VideoQueueHandler\.DeserializeVideoSongData\]\s+"
    r"deserialize video data:\s*(?P<payload>\{.*\})",
    re.IGNORECASE,
)
DUDU_ON_VIDEO_PLAY_RE = re.compile(
    r"\[VideoQueueHandler\.OnVideoPlay\]\s+VizVid callback:\s+video playback started",
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
USER_IDENTITY_RE = re.compile(
    r"(?:\[Behaviour\]\s+OnPlayer(?P<player_action>Joined|Left)|User Authenticated:)\s+"
    r"(?P<display_name>.+?)\s+\((?P<user_id>usr_[^)]+)\)",
    re.IGNORECASE,
)


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
    requester_user_id: str | None = None
    requester_user_id_source: str | None = None
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
            "requester_user_id": self.requester_user_id,
            "requester_user_id_source": self.requester_user_id_source,
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


def is_video_candidate_line(line: str) -> bool:
    """Return true when the line is worth running heavier video parsers on."""
    folded = line.casefold()
    return any(token in folded for token in VIDEO_TOKENS)


def is_lifecycle_candidate_line(line: str) -> bool:
    """Return true when the line may describe a room or app lifecycle event."""
    folded = _strip_color_tags(line).casefold()
    return any(token in folded for token in LIFECYCLE_TOKENS)


def is_identity_candidate_line(line: str) -> bool:
    """Return true when the line may contain a VRChat display-name/user-id pair."""
    folded = _strip_color_tags(line).casefold()
    return any(token in folded for token in IDENTITY_TOKENS)


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


def parse_vrc_identity_event(line: str) -> dict | None:
    """Parse a VRChat player identity line into a transient session event."""
    if not is_identity_candidate_line(line):
        return None

    plain_line = _strip_color_tags(line)
    match = USER_IDENTITY_RE.search(plain_line)
    if not match:
        return None

    action = (match.group("player_action") or "authenticated").casefold()
    if action == "joined":
        event_type = "player-joined"
        parser_name = "vrc_player_joined"
    elif action == "left":
        event_type = "player-left"
        parser_name = "vrc_player_left"
    else:
        event_type = "user-authenticated"
        parser_name = "vrc_user_authenticated"

    timestamp = _extract_timestamp(line)
    display_name = _clean_display_name(match.group("display_name"))
    user_id = (match.group("user_id") or "").strip()
    if not display_name or not user_id:
        return None

    return {
        "captured_at": _utc_now(),
        "timestamp": timestamp,
        "observed_at": timestamp,
        "event_type": event_type,
        "parser_name": parser_name,
        "display_name": display_name,
        "user_id": user_id,
        "raw_line": _trim_newline(line),
    }


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

    match = DUDU_QUEUE_DATA_RE.search(plain_line)
    if match:
        events.extend(
            _events_from_dudu_queue_info(
                timestamp=timestamp,
                payload=match.group("payload"),
                raw_line=line,
            )
        )

    match = DUDU_SONG_DATA_RE.search(plain_line)
    if match:
        event = _event_from_dudu_song_data(
            timestamp=timestamp,
            payload=match.group("payload"),
            raw_line=line,
        )
        if event is not None:
            events.append(event)

    match = DUDU_ON_VIDEO_PLAY_RE.search(plain_line)
    if match:
        events.append(
            ParsedVrcLogEvent(
                timestamp=timestamp,
                event_type="actual-play",
                video_url=None,
                display_name=None,
                parser_name="dudu_on_video_play",
                raw_line=line,
                actual_play_method="dudu_on_video_play",
            )
        )

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
        event = _wanna_metadata_event(
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
        if event is not None:
            events.append(event)
    return events


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


def _events_from_dudu_queue_info(
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
        event = _dudu_metadata_event(
                timestamp=timestamp,
                raw_line=raw_line,
                parser_name="dudu_queue_info",
                video_id=_first_present(entry, "songId", "song_id", "id"),
                video_url=entry.get("url") or entry.get("videoUrl") or entry.get("video_url"),
                title=entry.get("title") or entry.get("info") or entry.get("name"),
                display_name=entry.get("playerName") or entry.get("player_name") or entry.get("user"),
                is_random=entry.get("shuffle") or entry.get("isRandom"),
                duration_seconds=_float_or_none(
                    str(entry.get("duration")) if entry.get("duration") is not None else None
                ),
                duration_source="dudu_queue_json",
            )
        if event is not None:
            events.append(event)
    return events


def _event_from_dudu_song_data(
    *,
    timestamp: str | None,
    payload: str,
    raw_line: str,
) -> ParsedVrcLogEvent | None:
    value = _try_json(payload)
    if not isinstance(value, dict):
        return None
    return _dudu_metadata_event(
        timestamp=timestamp,
        raw_line=raw_line,
        parser_name="dudu_song_data",
        video_id=_first_present(value, "id", "songId", "song_id"),
        video_url=value.get("url") or value.get("videoUrl") or value.get("video_url"),
        title=_dudu_title_value(value),
        display_name=value.get("user") or value.get("playerName") or value.get("displayName"),
        is_random=value.get("shuffle") or value.get("isRandom"),
        duration_seconds=_float_or_none(
            str(value.get("duration")) if value.get("duration") is not None else None
        ),
        duration_source="dudu_song_json",
    )


def _dudu_metadata_event(
    *,
    timestamp: str | None,
    raw_line: str,
    parser_name: str,
    video_id,
    video_url,
    title,
    display_name,
    is_random,
    duration_seconds: float | None,
    duration_source: str | None,
) -> ParsedVrcLogEvent | None:
    video_id_text = str(video_id).strip() if video_id is not None else ""
    if not video_id_text and not video_url:
        return None

    clean_url = _clean_url(str(video_url)) if video_url else _dudu_video_url(video_id_text)
    title_id, video_name, requester_marker = _parse_video_title_payload(str(title or ""))
    resolved_video_id = video_id_text or title_id
    random_source = _truthy(is_random)
    clean_display_name = _clean_display_name(str(display_name)) if display_name is not None else None
    source_hint = "random" if random_source else None

    return ParsedVrcLogEvent(
        timestamp=timestamp,
        event_type="metadata",
        video_url=clean_url,
        display_name=clean_display_name,
        parser_name=parser_name,
        raw_line=raw_line,
        video_name=video_name,
        video_id=resolved_video_id or None,
        requester_marker=requester_marker,
        source_hint=source_hint,
        duration_seconds=duration_seconds,
        duration_source=duration_source if duration_seconds is not None else None,
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
            requester_user_id=parsed_payload["requester_user_id"],
            requester_user_id_source="payload" if parsed_payload["requester_user_id"] else None,
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
    requester_user_id = _requester_user_id_from_payload(payload)
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
        "requester_user_id": requester_user_id,
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


def _requester_user_id_from_payload(payload: str) -> str | None:
    structured = _try_json(payload)
    if structured is None:
        return None
    value = _find_key(
        structured,
        {
            "userid",
            "user_id",
            "requesterid",
            "requester_id",
            "playerid",
            "player_id",
            "vrchatuserid",
            "vrchat_user_id",
        },
    )
    if value is None:
        return None
    text = str(value).strip()
    if not text.startswith("usr_"):
        return None
    return text


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


def _strip_color_tags(line: str) -> str:
    return COLOR_TAG_RE.sub("", line)


def _clean_url(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().strip("\"'").rstrip(".,);]}")


def _wanna_video_url(song_id: str) -> str:
    return f"http://api.udon.dance/Api/Songs/play?id={song_id}"


def _dudu_video_url(video_id: str) -> str:
    return f"https://api.dudufit.dance/api/v1/videos/{video_id}"


def _dudu_title_value(value: dict) -> str:
    info = str(value.get("info") or "").strip()
    if info:
        return info

    title = str(value.get("title") or value.get("name") or "").strip()
    artist = str(value.get("artist") or "").strip()
    if title and artist and artist.casefold() not in title.casefold():
        return f"{title} - {artist}"
    return title or artist


def _first_present(mapping: dict, *keys: str):
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes"}
    return bool(value)


def _dedupe_events(events: list[ParsedVrcLogEvent]) -> list[ParsedVrcLogEvent]:
    deduped: list[ParsedVrcLogEvent] = []
    seen: set[tuple[str | None, str | None, str]] = set()
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


def _utc_now() -> str:
    return now_utc_iso()
