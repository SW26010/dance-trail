"""Daily dance-history report helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from pathlib import Path
import re

from dancing_log.storage import connect_db


@dataclass(frozen=True)
class DailyDance:
    """One dance event rendered for a local-day report."""

    event_id: int
    played_at_local: datetime
    display_name: str


def load_daily_dances(
    target_date: date,
    path: Path | str | None = None,
    *,
    local_tz: tzinfo | None = None,
) -> list[DailyDance]:
    """Return official dance events that fall on the requested local date."""
    with connect_db(path) as conn:
        rows = conn.execute(
            """
            SELECT
                de.id AS event_id,
                de.played_at,
                de.video_name,
                dt.external_id,
                dt.title,
                dt.artist,
                dt.dancer,
                dt.group_name,
                dt.major
            FROM dance_events de
            JOIN dance_tracks dt ON dt.id = de.dance_track_id
            ORDER BY de.played_at, de.id
            """
        ).fetchall()

    dances: list[DailyDance] = []
    for row in rows:
        played_at_local = parse_played_at_local(row["played_at"], local_tz=local_tz)
        if played_at_local is None or played_at_local.date() != target_date:
            continue
        dances.append(
            DailyDance(
                event_id=int(row["event_id"]),
                played_at_local=played_at_local,
                display_name=_format_display_name(dict(row)),
            )
        )

    dances.sort(key=lambda dance: (dance.played_at_local, dance.event_id))
    return dances


def load_daily_live_dances(
    target_date: date,
    path: Path | str | None = None,
    *,
    local_tz: tzinfo | None = None,
) -> list[DailyDance]:
    """Return live playback rows observed on the requested local date."""
    with connect_db(path) as conn:
        rows = conn.execute(
            """
            SELECT
                id AS event_id,
                actual_play_at AS played_at,
                video_name,
                dance_external_id AS external_id,
                NULL AS title,
                NULL AS artist,
                NULL AS dancer,
                NULL AS group_name,
                NULL AS major
            FROM live_playback_events
            WHERE actual_play_at IS NOT NULL
                AND dance_external_id IS NOT NULL
                AND COALESCE(observed_mid_play, 0) = 0
            ORDER BY actual_play_at, id
            """
        ).fetchall()

    dances: list[DailyDance] = []
    for row in rows:
        played_at_local = parse_played_at_local(row["played_at"], local_tz=local_tz)
        if played_at_local is None or played_at_local.date() != target_date:
            continue
        dances.append(
            DailyDance(
                event_id=int(row["event_id"]),
                played_at_local=played_at_local,
                display_name=_format_display_name(dict(row)),
            )
        )

    dances.sort(key=lambda dance: (dance.played_at_local, dance.event_id))
    return dances


def format_daily_dance_line(dance: DailyDance) -> str:
    """Format one daily report row as `HH:MM:SS song id song name`."""
    return f"{dance.played_at_local:%H:%M:%S} {dance.display_name}"


def parse_played_at_local(
    value: str | None,
    *,
    local_tz: tzinfo | None = None,
) -> datetime | None:
    """Parse supported stored timestamps and return local time."""
    text = (value or "").strip()
    if not text:
        return None

    iso_text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(iso_text)
    except ValueError:
        parsed = _parse_vrc_local_timestamp(text)
    if parsed is None:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(local_tz)
    return parsed


def _parse_vrc_local_timestamp(value: str) -> datetime | None:
    for fmt in ("%Y.%m.%d %H:%M:%S.%f", "%Y.%m.%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def _format_display_name(row: dict) -> str:
    external_id = str(row.get("external_id") or "").strip()
    video_name = str(row.get("video_name") or "").strip()
    if video_name and _has_external_id_prefix(video_name, external_id):
        return video_name

    title = str(row.get("title") or video_name or "(untitled)").strip()
    artist = str(row.get("artist") or "").strip()
    variant = str(
        row.get("dancer")
        or row.get("group_name")
        or row.get("major")
        or ""
    ).strip()

    display = title
    if artist:
        display = f"{display} - {artist}"
    if variant:
        display = f"{display} | {variant}"
    if external_id:
        return f"{external_id}. {display}"
    return display


def _has_external_id_prefix(value: str, external_id: str) -> bool:
    if not external_id:
        return False
    return bool(re.match(rf"^{re.escape(external_id)}(?:\.|\s)", value))
