"""Runtime models and recommendation weighting."""

from __future__ import annotations

import hashlib
import math
from datetime import date, datetime, timezone
from typing import cast

from dancing_log.storage import (
    add_dance_event,
    get_dance_track,
    load_dance_log as load_dance_events_from_db,
    load_dance_tracks as load_dance_tracks_from_db,
)
from dancing_log.local_dance_day import LocalDanceDayBoundary
from dancing_log.time_utils import normalize_timestamp, now_utc_iso


SOURCE_QUEUED_SELF = "queued_self"
SOURCE_SELF = "self"
SOURCE_RECOMMEND = "recommend"
SOURCE_OTHER = "other"
SOURCE_RANDOM = "random"
SOURCE_UNKNOWN = "unknown"

SOURCE_LABELS = {
    SOURCE_QUEUED_SELF: "queued self",
    SOURCE_SELF: "self",
    SOURCE_RECOMMEND: "recommend",
    SOURCE_OTHER: "other",
    SOURCE_RANDOM: "random",
    SOURCE_UNKNOWN: "unknown",
}


def load_dance_tracks(db_path: str | None = None) -> list[dict]:
    """Load dance-track metadata from SQLite."""
    return load_dance_tracks_from_db(db_path)


def load_dance_log(db_path: str | None = None) -> list[dict]:
    """Load normalized dance events from SQLite."""
    return load_dance_events_from_db(db_path)


def _playlist_seed(target_date: date) -> str:
    return f"dancing-log-{target_date.isoformat()}"


def _seeded_tiebreaker(seed: str, track_key: str) -> float:
    h = hashlib.sha256(f"{seed}:{track_key}".encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def get_daily_playlist_track_ids(
    tracks: list[dict],
    dance_log: list[dict],
    target_date: date | None = None,
    count: int = 20,
) -> set[int]:
    playlist = generate_daily_playlist(
        tracks,
        dance_log,
        count=count,
        target_date=target_date,
    )
    return {int(track["id"]) for track in playlist}


def add_dance_record(
    system_key: str,
    external_id: str,
    source: str = SOURCE_SELF,
    note: str = "",
    timestamp: str | None = None,
    auto_detect: bool = True,
    db_path: str | None = None,
    dance_day_boundary: LocalDanceDayBoundary | None = None,
) -> str:
    """Add one dance event for a system-specific dance track."""
    if timestamp is None:
        timestamp = now_utc_iso()
    normalized_timestamp = normalize_timestamp(timestamp)

    actual_source = source
    if auto_detect and source == SOURCE_SELF:
        existing_track = get_dance_track(system_key, external_id, db_path)
        tracks = load_dance_tracks(db_path)
        if existing_track and tracks:
            records = load_dance_log(db_path)
            boundary = dance_day_boundary or LocalDanceDayBoundary.from_config({})
            today = boundary.date_for(normalized_timestamp)
            playlist_ids = get_daily_playlist_track_ids(
                tracks,
                records,
                target_date=today,
            )
            if int(existing_track["id"]) in playlist_ids:
                actual_source = SOURCE_RECOMMEND

    add_dance_event(
        system_key=system_key,
        external_id=external_id,
        source=actual_source,
        note=note,
        played_at=timestamp,
        event_source="manual",
        confidence=1.0,
        path=db_path,
    )
    return actual_source


def compute_recommendation(
    tracks: list[dict],
    dance_log: list[dict],
    now: datetime | None = None,
) -> list[dict]:
    """Compute recommendation weights for dance tracks."""
    if now is None:
        now = datetime.now(timezone.utc).astimezone()

    weight_favorite = 2.0
    weight_frequency = 3.0
    weight_recency = 2.5
    weight_want = 2.5

    dance_stats: dict[int, dict] = {}
    for record in dance_log:
        track_id = int(record["dance_track_id"])
        if track_id not in dance_stats:
            dance_stats[track_id] = {"count": 0, "last_time": None}
        dance_stats[track_id]["count"] += 1
        try:
            played_at = datetime.fromisoformat(record["timestamp"])
            if (
                dance_stats[track_id]["last_time"] is None
                or played_at > dance_stats[track_id]["last_time"]
            ):
                dance_stats[track_id]["last_time"] = played_at
        except (ValueError, TypeError):
            pass

    results = []
    for track in tracks:
        track_id = int(track["id"])
        favorite_score = 1.0 if track.get("favorite") in ("1", "true", True, 1) else 0.0
        want_score = 1.0 if track.get("want_to_learn") in ("1", "true", True, 1) else 0.0

        stats = dance_stats.get(track_id, {"count": 0, "last_time": None})
        dance_count = stats["count"]
        frequency_score = 1.0 / (1.0 + dance_count)

        if stats["last_time"] is not None:
            days_since = (now - stats["last_time"]).total_seconds() / 86400
            recency_score = 1.0 / (1.0 + math.exp(-0.1 * (days_since - 7)))
        else:
            recency_score = 1.0

        weight = (
            weight_favorite * favorite_score
            + weight_frequency * frequency_score
            + weight_recency * recency_score
            + weight_want * want_score
        )

        results.append(
            {
                **track,
                "_weight": round(weight, 3),
                "_dance_count": dance_count,
                "_days_since_last": round(
                    (now - stats["last_time"]).total_seconds() / 86400,
                    1,
                )
                if stats["last_time"]
                else None,
            }
        )

    results.sort(key=lambda item: cast(float, item["_weight"]), reverse=True)
    return results


def generate_daily_playlist(
    tracks: list[dict],
    dance_log: list[dict],
    count: int = 20,
    target_date: date | None = None,
    dance_day_boundary: LocalDanceDayBoundary | None = None,
) -> list[dict]:
    """Generate a deterministic daily recommendation playlist."""
    if target_date is None:
        boundary = dance_day_boundary or LocalDanceDayBoundary.from_config({})
        target_date = boundary.current_date()

    ranked = compute_recommendation(tracks, dance_log)
    seed = _playlist_seed(target_date)
    ranked.sort(
        key=lambda track: (
            -track["_weight"],
            _seeded_tiebreaker(
                seed,
                f"{track.get('system_key')}:{track.get('external_id')}",
            ),
        ),
    )
    return ranked[:count]
