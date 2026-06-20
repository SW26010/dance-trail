"""Shared helpers for VRChat log timestamps and normalized text."""

from __future__ import annotations

from datetime import datetime
import re


TIMESTAMP_RE = re.compile(
    r"^(?P<timestamp>\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)"
)


def extract_timestamp(line: str) -> str | None:
    match = TIMESTAMP_RE.match(line)
    return match.group("timestamp") if match else None


def parse_vrc_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y.%m.%d %H:%M:%S.%f", "%Y.%m.%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def format_vrc_timestamp(value: datetime) -> str:
    text = value.strftime("%Y.%m.%d %H:%M:%S.%f")
    return text.rstrip("0").rstrip(".")


def timestamp_sort_key(value: str | None) -> str:
    parsed = parse_vrc_timestamp(value)
    if parsed is None:
        return ""
    return parsed.isoformat()


def timestamp_before(left: str | None, right: str | None) -> bool:
    left_key = timestamp_sort_key(left)
    right_key = timestamp_sort_key(right)
    return bool(left_key and right_key and left_key < right_key)


def seconds_between(start: str | None, end: str | None) -> float | None:
    start_dt = parse_vrc_timestamp(start)
    end_dt = parse_vrc_timestamp(end)
    if start_dt is None or end_dt is None:
        return None
    return round((end_dt - start_dt).total_seconds(), 3)


def float_or_none(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def clean_display_name(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().strip("\"'")
    return cleaned or None


def trim_newline(value: str) -> str:
    return value.rstrip("\r\n")
