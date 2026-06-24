"""Fold parsed VRChat playback signals into live Playback Records."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from dancing_log.vrc_log_utils import (
    clean_display_name,
    format_vrc_timestamp,
    parse_vrc_timestamp,
    seconds_between,
    timestamp_sort_key,
)
from dancing_log.vrcx_importer import parse_dance_url


DURATION_CONFLICT_EPSILON_SECONDS = 0.001
PREVIEW_SUPPRESSION_SECONDS = 90.0
RETRY_MERGE_SECONDS = 30.0

__all__ = [
    "DURATION_CONFLICT_EPSILON_SECONDS",
    "PREVIEW_SUPPRESSION_SECONDS",
    "RETRY_MERGE_SECONDS",
    "PlaybackEventBuilder",
    "playback_delay_metrics",
]


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

    def observe(self, record: dict) -> dict | None:
        canonical_key = self._canonical_key_for_record(record)
        event_type = record.get("event_type")
        if event_type == "metadata":
            if canonical_key is not None:
                return self._remember_metadata(canonical_key, record)
            return None
        if event_type == "preview":
            if canonical_key is not None:
                self._mark_preview(canonical_key, record.get("timestamp"))
            return None

        if canonical_key is not None and record.get("parser_name") in {"user_added_url", "vrcx_video_play"}:
            self._preview_until_by_canonical.pop(canonical_key, None)
        elif canonical_key is not None and self._is_preview_suppressed(canonical_key, record.get("timestamp")):
            return None

        key = None
        if canonical_key is not None:
            key = self._event_key_for_record(canonical_key, record)
        timestamp = record.get("timestamp")

        if key is None and record.get("event_type") == "video-loaded":
            key = self._active_key
        if key is None and record.get("event_type") == "actual-play":
            key = self._active_key or self._key_for_actual_play(timestamp)
        if key is None:
            return None

        event = self._events.setdefault(key, self._new_event(key))
        if canonical_key is not None and canonical_key in self._metadata_by_canonical:
            self._merge_signal(event, self._metadata_by_canonical[canonical_key])
        self._merge_signal(event, record)

        if record.get("video_url"):
            self._active_key = key
        finalized = self._finalize_event(event)
        if self._update_callback is not None:
            self._update_callback(finalized)
        return finalized

    def records(self) -> list[dict]:
        records = [self._finalize_event(event) for event in self._events.values()]
        return sorted(
            records,
            key=lambda event: (
                timestamp_sort_key(event.get("first_seen_at")),
                event.get("event_key") or "",
            ),
        )

    def close_open_events(self) -> None:
        self._open_by_canonical.clear()
        self._active_key = None

    def backfill_requester_user_id(
        self,
        event_key: str,
        requester_user_id: str,
        *,
        source: str | None = None,
    ) -> dict | None:
        """Fill a missing requester user id on one folded event."""
        event = self._events.get(event_key)
        if event is None or event.get("requester_user_id"):
            return None
        if not requester_user_id:
            return None
        event["requester_user_id"] = requester_user_id
        if source:
            event["requester_user_id_source"] = source
        finalized = self._finalize_event(event)
        if self._update_callback is not None:
            self._update_callback(finalized)
        return finalized

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
            "requester_user_id": None,
            "requester_user_id_source": None,
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
        timestamp_dt = parse_vrc_timestamp(timestamp)
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
            self._copy_first(event, record, "requester_user_id")
            self._copy_first(event, record, "requester_user_id_source")
            self._copy_first(event, record, "source_hint")
            self._merge_duration(event, record)
            for field_name in ("video_url", "routed_url", "resolved_url"):
                if event.get(field_name) in (None, "") and record.get(field_name):
                    event[field_name] = record[field_name]
            return

        if event["first_seen_at"] is None or timestamp_sort_key(timestamp) < timestamp_sort_key(event["first_seen_at"]):
            event["first_seen_at"] = timestamp
        if timestamp_sort_key(timestamp) > timestamp_sort_key(event.get("last_seen_at")):
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
        self._copy_first(event, record, "requester_user_id")
        self._copy_first(event, record, "requester_user_id_source")
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
                event["expected_ready_at"] = format_vrc_timestamp(
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

    def _remember_metadata(self, canonical_key: str, record: dict) -> dict | None:
        metadata = self._metadata_by_canonical.setdefault(canonical_key, dict(record))
        for field_name in (
            "video_url",
            "display_name",
            "video_name",
            "video_id",
            "requester_marker",
            "requester_user_id",
            "requester_user_id_source",
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
            return None
        current_event = self._events.get(current_key)
        if current_event is None:
            return None
        self._merge_signal(current_event, record)
        finalized = self._finalize_event(current_event)
        if self._update_callback is not None:
            self._update_callback(finalized)
        return finalized

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

        delay_to_actual = seconds_between(
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
        finalized["load_to_actual_seconds"] = seconds_between(
            finalized.get("video_loaded_at"),
            finalized.get("actual_play_at"),
        )
        finalized["request_to_resolve_seconds"] = seconds_between(
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
        seconds_since_last_seen = seconds_between(last_seen_at, timestamp)
        return seconds_since_last_seen is not None and 0 <= seconds_since_last_seen <= RETRY_MERGE_SECONDS

    def _new_occurrence(self, canonical_key: str, timestamp: str | None) -> str:
        count = self._occurrence_counts.get(canonical_key, 0) + 1
        self._occurrence_counts[canonical_key] = count
        event_key = f"{canonical_key}#{count}"
        self._events[event_key] = self._new_event(event_key, canonical_key)
        self._open_by_canonical[canonical_key] = event_key
        return event_key

    def _mark_preview(self, canonical_key: str, timestamp: str | None) -> None:
        timestamp_dt = parse_vrc_timestamp(timestamp)
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
        timestamp_dt = parse_vrc_timestamp(timestamp)
        if timestamp_dt is None or timestamp_dt <= suppress_until:
            return True
        self._preview_until_by_canonical.pop(canonical_key, None)
        return False

    def _key_for_actual_play(self, timestamp: str | None) -> str | None:
        timestamp_dt = parse_vrc_timestamp(timestamp)
        if timestamp_dt is None:
            return self._active_key

        best_key = None
        best_delta = None
        for key, event in self._events.items():
            if event.get("actual_play_at"):
                continue
            expected_dt = parse_vrc_timestamp(event.get("expected_ready_at"))
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
        if prefer_latest and timestamp_sort_key(timestamp) > timestamp_sort_key(event[field_name]):
            event[field_name] = timestamp


def playback_delay_metrics(playback_records: list[dict]) -> dict[str, float | int | None]:
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
    requester_marker = clean_display_name(event.get("requester_marker"))
    display_name = clean_display_name(event.get("display_name"))

    if source_hint == "random" or (requester_marker or "").casefold() == "random":
        return "random", None
    if source_hint == "requester_marker" and requester_marker:
        return "player", requester_marker
    if display_name and display_name.casefold() != "random":
        return "player", display_name
    return "unknown", None


def _duration_values_differ(left, right) -> bool:
    try:
        return abs(float(left) - float(right)) > DURATION_CONFLICT_EPSILON_SECONDS
    except (TypeError, ValueError):
        return left != right


def _duration_source_priority(source: str | None) -> int:
    return {
        "wanna_queue_json": 10,
        "vrcx_payload": 20,
        "wanna_video_duration": 30,
    }.get(source or "", 0)


