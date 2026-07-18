"""Local Dance Day assignment and range semantics.

The Module owns the application-local time zone, the configurable wall-clock
boundary, and the half-open date ranges derived from them. Callers should not
repeat timezone conversion or compare ``datetime.date()`` directly.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, tzinfo
import re
from typing import Any

from tzlocal import get_localzone

from dancing_log.time_utils import parse_timestamp


DANCE_DAY_BOUNDARY_CONFIG_KEY = "dance_day_boundary_time"
DEFAULT_DANCE_DAY_BOUNDARY_TIME = "00:00"
MIN_DANCE_DAY_BOUNDARY_TIME = time(0, 0)
MAX_DANCE_DAY_BOUNDARY_TIME = time(6, 0)

_BOUNDARY_TEXT_RE = re.compile(r"^(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2})$")


@dataclass(frozen=True)
class LocalDanceDayRange:
    """One Local Dance Day as a start-inclusive, end-exclusive range."""

    dance_date: date
    start_utc: datetime
    end_utc: datetime

    def __post_init__(self) -> None:
        if self.start_utc.tzinfo is None or self.end_utc.tzinfo is None:
            raise ValueError("Local Dance Day range endpoints must be aware UTC instants")
        if (
            self.start_utc.utcoffset() != timedelta(0)
            or self.end_utc.utcoffset() != timedelta(0)
        ):
            raise ValueError("Local Dance Day range endpoints must be UTC")
        if self.end_utc < self.start_utc:
            raise ValueError("Local Dance Day range end must not precede its start")

    def contains(self, value: datetime) -> bool:
        if value.tzinfo is None:
            raise ValueError("Local Dance Day range membership requires an aware datetime")
        value_utc = value.astimezone(UTC)
        return self.start_utc <= value_utc < self.end_utc


@dataclass(frozen=True)
class LocalDanceDayBoundary:
    """Assign timestamps to Local Dance Days through one domain Interface."""

    boundary_time: time = MIN_DANCE_DAY_BOUNDARY_TIME
    time_zone: tzinfo = field(default_factory=get_localzone)

    def __post_init__(self) -> None:
        _validate_boundary_time(self.boundary_time)
        if self.time_zone is None:
            raise ValueError("Local Dance Day time zone must be a usable tzinfo")
        try:
            datetime.now(self.time_zone)
        except (TypeError, ValueError) as exc:
            raise ValueError("Local Dance Day time zone must be a usable tzinfo") from exc

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any],
        *,
        time_zone: tzinfo | None = None,
    ) -> "LocalDanceDayBoundary":
        value = config.get(
            DANCE_DAY_BOUNDARY_CONFIG_KEY,
            DEFAULT_DANCE_DAY_BOUNDARY_TIME,
        )
        return cls(
            boundary_time=_parse_boundary_time(value),
            time_zone=time_zone if time_zone is not None else get_localzone(),
        )

    @property
    def config_value(self) -> str:
        return self.boundary_time.strftime("%H:%M")

    def local_datetime(self, value: object) -> datetime:
        """Parse a supported timestamp and return it in the owned time zone."""
        return parse_timestamp(value, local_tz=self.time_zone).astimezone(self.time_zone)

    def date_for(self, value: object) -> date:
        """Return the Local Dance Day containing ``value``."""
        local_value = self.local_datetime(value)
        local_date = local_value.date()
        local_date_start = self._resolved_boundary(local_date)
        candidate_date = (
            local_date
            if local_value.astimezone(UTC) >= local_date_start.astimezone(UTC)
            else local_date - timedelta(days=1)
        )
        day_range = self.range_for(candidate_date)
        if not day_range.contains(local_value):
            raise ValueError("timestamp could not be assigned to its Local Dance Day range")
        return candidate_date

    def current_date(self, *, now: datetime | None = None) -> date:
        """Return the current Local Dance Day using an injectable instant."""
        return self.date_for(now if now is not None else datetime.now(UTC))

    def range_for(self, dance_date: date) -> LocalDanceDayRange:
        """Return UTC instants for ``[date@boundary, next-date@boundary)``."""
        if isinstance(dance_date, datetime) or not isinstance(dance_date, date):
            raise TypeError("dance_date must be a date")
        start = self._resolved_boundary(dance_date)
        end = self._resolved_boundary(dance_date + timedelta(days=1))
        return LocalDanceDayRange(
            dance_date=dance_date,
            start_utc=start.astimezone(UTC),
            end_utc=end.astimezone(UTC),
        )

    def _resolved_boundary(self, local_date: date) -> datetime:
        wall_value = datetime.combine(local_date, self.boundary_time)
        candidates = self._valid_wall_time_candidates(wall_value)

        if candidates:
            # A repeated wall time begins the new dance day on its first
            # occurrence (fold=0), which is the earliest UTC instant.
            return candidates[min(candidates)]

        # A spring-forward gap has no instant for the configured wall time.
        # Advance on the wall clock to the first valid minute, rather than
        # shifting by the gap duration. The inclusive 24-hour endpoint also
        # handles a historically skipped local calendar date as a zero-length
        # dance day.
        for minute in range(1, 24 * 60 + 1):
            advanced_wall_value = wall_value + timedelta(minutes=minute)
            advanced_candidates = self._valid_wall_time_candidates(
                advanced_wall_value
            )
            if advanced_candidates:
                return advanced_candidates[min(advanced_candidates)]
        raise ValueError(
            f"Local Dance Day boundary could not be resolved on "
            f"{local_date.isoformat()} in {self.time_zone}"
        )

    def _valid_wall_time_candidates(
        self,
        wall_value: datetime,
    ) -> dict[datetime, datetime]:
        candidates: dict[datetime, datetime] = {}
        for fold in (0, 1):
            candidate = wall_value.replace(tzinfo=self.time_zone, fold=fold)
            round_trip = candidate.astimezone(UTC).astimezone(self.time_zone)
            if round_trip.replace(tzinfo=None) == wall_value:
                candidates[candidate.astimezone(UTC)] = candidate
        return candidates


def _parse_boundary_time(value: object) -> time:
    if not isinstance(value, str):
        raise ValueError(
            f"{DANCE_DAY_BOUNDARY_CONFIG_KEY} must use HH:MM from 00:00 to 06:00"
        )
    match = _BOUNDARY_TEXT_RE.fullmatch(value)
    if match is None:
        raise ValueError(
            f"{DANCE_DAY_BOUNDARY_CONFIG_KEY} must use HH:MM from 00:00 to 06:00"
        )
    try:
        parsed = time(int(match.group("hour")), int(match.group("minute")))
    except ValueError as exc:
        raise ValueError(
            f"{DANCE_DAY_BOUNDARY_CONFIG_KEY} must use HH:MM from 00:00 to 06:00"
        ) from exc
    _validate_boundary_time(parsed)
    return parsed


def _validate_boundary_time(value: time) -> None:
    if not isinstance(value, time):
        raise TypeError("Local Dance Day boundary must be a time")
    if value.tzinfo is not None or value.second or value.microsecond:
        raise ValueError("Local Dance Day boundary must be a whole local minute")
    if not MIN_DANCE_DAY_BOUNDARY_TIME <= value <= MAX_DANCE_DAY_BOUNDARY_TIME:
        raise ValueError(
            f"{DANCE_DAY_BOUNDARY_CONFIG_KEY} must be between 00:00 and 06:00"
        )
