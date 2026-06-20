"""Display model for the live OBS overlay."""

from __future__ import annotations

from math import floor, isfinite
from typing import Any, Mapping


SYSTEM_LABELS = {
    "wannadance": "WD",
    "pypydance": "PY",
}


def build_overlay_view_model(event: Mapping[str, Any] | None) -> dict | None:
    """Build the display contract consumed by the browser overlay."""
    if event is None:
        return None

    raw_title = _raw_title(event)
    return {
        "title": _primary_title(raw_title),
        "series_name": _series_name(raw_title),
        "source_label": _source_label(event),
        "system_track_label": _system_track_label(event),
        "timer": _timer_model(event),
    }


def overlay_meta_text(view_model: Mapping[str, Any], elapsed_seconds: float) -> str:
    """Render the non-clock overlay metadata for tests and non-browser callers."""
    parts = [
        str(view_model.get("system_track_label") or "-- ID: ?"),
        _timer_text(view_model.get("timer"), elapsed_seconds),
    ]
    series_name = str(view_model.get("series_name") or "").strip()
    if series_name:
        parts.append(series_name)
    return " | ".join(parts)


def _raw_title(event: Mapping[str, Any]) -> str:
    title = event.get("video_name") or event.get("video_url")
    if title:
        return str(title)
    return f"{event.get('dance_system_key') or 'unknown'}:{event.get('dance_external_id') or '?'}"


def _primary_title(raw_title: str) -> str:
    primary = raw_title.split("|", 1)[0].strip()
    return primary or raw_title


def _series_name(raw_title: str) -> str:
    parts = raw_title.split("|")
    if len(parts) <= 1:
        return ""
    return "|".join(parts[1:]).strip()


def _source_label(event: Mapping[str, Any]) -> str:
    source_type = str(event.get("source_type") or "").strip()
    display_name = str(event.get("source_display_name") or "").strip()
    if source_type == "player":
        return f"source player: {display_name or 'unknown'}"
    if source_type and display_name:
        return f"source {source_type}: {display_name}"
    if source_type:
        return f"source {source_type}"
    if display_name:
        return f"source player: {display_name}"
    return "source unknown"


def _system_track_label(event: Mapping[str, Any]) -> str:
    system = str(event.get("dance_system_key") or "").lower()
    label = SYSTEM_LABELS.get(system) or (system[:2].upper() if system else "--")
    external_id = event.get("dance_external_id") or "?"
    return f"{label} ID: {external_id}"


def _timer_model(event: Mapping[str, Any]) -> dict:
    duration = _positive_float(event.get("duration_seconds"))
    if duration is None:
        return {
            "mode": "elapsed",
            "duration_seconds": None,
        }
    return {
        "mode": "elapsed_total",
        "duration_seconds": duration,
    }


def _timer_text(timer: Any, elapsed_seconds: float) -> str:
    elapsed = _non_negative_float(elapsed_seconds) or 0.0
    if isinstance(timer, Mapping):
        mode = str(timer.get("mode") or "elapsed")
        duration = _positive_float(timer.get("duration_seconds"))
        if mode == "elapsed_total" and duration is not None:
            return f"{format_duration(min(elapsed, duration))}/{format_duration(duration)}"
    return format_duration(elapsed)


def format_duration(seconds: float) -> str:
    value = _non_negative_float(seconds) or 0.0
    total = floor(value)
    minutes = total // 60
    remaining_seconds = total % 60
    return f"{minutes}:{remaining_seconds:02d}"


def _positive_float(value: Any) -> float | None:
    number = _finite_float(value)
    if number is None or number <= 0:
        return None
    return number


def _non_negative_float(value: Any) -> float | None:
    number = _finite_float(value)
    if number is None or number < 0:
        return None
    return number


def _finite_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(number):
        return None
    return number
