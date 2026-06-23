"""Completion and interruption rules for live watcher Playback Records."""

from __future__ import annotations

from dataclasses import dataclass

from dancing_log.vrc_log_utils import float_or_none, seconds_between


PROMOTION_COMPLETION_RATIO = 0.8
COMPLETION_EPSILON_SECONDS = 0.001


@dataclass(frozen=True)
class LivePlaybackSettlement:
    completion_status: str
    observed_at: str
    played_seconds: float | None
    required_played_seconds: float | None
    reason: str


def decide_live_playback_settlement(
    event: dict,
    *,
    observed_at: str,
    interrupt_if_incomplete: bool,
    completion_reason: str,
    interrupt_reason: str,
) -> LivePlaybackSettlement | None:
    actual_play_at = event.get("actual_play_at")
    duration_seconds = float_or_none(
        str(event.get("duration_seconds")) if event.get("duration_seconds") is not None else None
    )
    played_seconds_at_observed = (
        seconds_between(actual_play_at, observed_at) if actual_play_at else None
    )
    if played_seconds_at_observed is not None and played_seconds_at_observed < 0:
        return None

    if event.get("observed_mid_play"):
        if not interrupt_if_incomplete:
            return None
        return LivePlaybackSettlement(
            completion_status="interrupted",
            observed_at=observed_at,
            played_seconds=played_seconds_at_observed,
            required_played_seconds=duration_seconds,
            reason="observed_mid_play",
        )

    if not event.get("dance_system_key") or not event.get("dance_external_id"):
        return None

    if not actual_play_at:
        if not interrupt_if_incomplete:
            return None
        return LivePlaybackSettlement(
            completion_status="interrupted",
            observed_at=observed_at,
            played_seconds=None,
            required_played_seconds=duration_seconds,
            reason=interrupt_reason,
        )

    if duration_seconds is None or duration_seconds <= 0:
        if not interrupt_if_incomplete:
            return None
        reason = (
            "unknown_duration_before_superseded"
            if interrupt_reason == "superseded_before_completion"
            else interrupt_reason
        )
        return LivePlaybackSettlement(
            completion_status="interrupted",
            observed_at=observed_at,
            played_seconds=played_seconds_at_observed,
            required_played_seconds=None,
            reason=reason,
        )

    played_seconds = played_seconds_at_observed
    required_played_seconds = duration_seconds * PROMOTION_COMPLETION_RATIO
    if played_seconds is None:
        return None
    if played_seconds + COMPLETION_EPSILON_SECONDS >= required_played_seconds:
        return LivePlaybackSettlement(
            completion_status="completed",
            observed_at=observed_at,
            played_seconds=played_seconds,
            required_played_seconds=required_played_seconds,
            reason=completion_reason,
        )

    if not interrupt_if_incomplete:
        return None

    return LivePlaybackSettlement(
        completion_status="interrupted",
        observed_at=observed_at,
        played_seconds=played_seconds,
        required_played_seconds=required_played_seconds,
        reason=interrupt_reason,
    )


def is_live_playback_promotable(row) -> bool:
    return bool(
        row["completion_status"] == "completed"
        and row["actual_play_at"]
        and row["dance_system_key"]
        and row["dance_external_id"]
        and row["duration_seconds"] is not None
        and not bool(row["observed_mid_play"])
    )
