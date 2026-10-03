"""Shared timestamp normalization helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone, tzinfo
from typing import Any

from tzlocal import get_localzone


UTC = timezone.utc
SQLITE_UTC_NOW = "strftime('%Y-%m-%dT%H:%M:%SZ','now')"

VRCHAT_TIMESTAMP_FORMATS = (
    "%Y.%m.%d %H:%M:%S.%f",
    "%Y.%m.%d %H:%M:%S",
)


def now_utc_iso() -> str:
    """Return the current time as canonical UTC ISO 8601 text."""
    return format_utc_iso(datetime.now(UTC))


def normalize_timestamp(
    value: object,
    *,
    local_tz: tzinfo | None = None,
) -> str:
    """Normalize supported source timestamps to UTC ISO 8601 text with ``Z``.

    Naive ISO strings and VRChat dotted timestamps are treated as VRChat local
    wall-clock time. Aware ISO strings are converted to UTC.
    """
    parsed = parse_timestamp(value, local_tz=local_tz)
    return format_utc_iso(parsed)


def normalize_optional_timestamp(
    value: object,
    *,
    local_tz: tzinfo | None = None,
) -> str | None:
    if value in (None, ""):
        return None
    return normalize_timestamp(value, local_tz=local_tz)


def normalize_timestamp_fields(
    values: Mapping[str, Any],
    field_names: Iterable[str],
    *,
    local_tz: tzinfo | None = None,
) -> dict[str, Any]:
    normalized = dict(values)
    for field_name in field_names:
        if field_name in normalized:
            normalized[field_name] = normalize_optional_timestamp(
                normalized[field_name],
                local_tz=local_tz,
            )
    return normalized


def parse_timestamp(
    value: object,
    *,
    local_tz: tzinfo | None = None,
) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            raise ValueError("timestamp must not be empty")
        parsed = _parse_iso_timestamp(text) or _parse_vrc_timestamp(text)
        if parsed is None:
            raise ValueError(f"unsupported timestamp: {value}")

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=local_tz or get_localzone())
    return parsed


def format_utc_iso(value: datetime) -> str:
    utc = value.astimezone(UTC)
    timespec = "microseconds" if utc.microsecond else "seconds"
    return utc.isoformat(timespec=timespec).replace("+00:00", "Z")


def _parse_iso_timestamp(text: str) -> datetime | None:
    iso_text = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        return datetime.fromisoformat(iso_text)
    except ValueError:
        return None


def _parse_vrc_timestamp(text: str) -> datetime | None:
    for fmt in VRCHAT_TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None
