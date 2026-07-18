# Centralize Local Dance Day semantics

Date: 2026-07-18

## Status

Accepted

## Context

Timeline, daily reports, queued-self matching, and recommendation seeding each
derived a date independently. Those implementations mixed host natural dates,
an assumed UTC+8 offset, and SQLite date modifiers, so they could disagree and
could not apply the configurable Local Dance Day Boundary consistently.

## Decision

Use one `LocalDanceDayBoundary` Module as the seam for local-time conversion,
Local Dance Day assignment, and half-open day ranges. The boundary is stored as
`dance_day_boundary_time` in `HH:MM` form, defaults to `00:00`, and is limited
to `00:00` through `06:00` inclusive.

The Module reads the operating system's real local IANA time-zone rules rather
than assuming a UTC offset. A time zone remains injectable for deterministic
tests and future explicit configuration. Ranges are compared as UTC instants.
If a spring DST transition removes the configured wall time, the boundary is
the first valid wall-clock minute after it. If an autumn transition repeats the
configured time, the first occurrence (`fold=0`) begins the new dance day.

Callers read the current configuration whenever they construct the Module.
Playback rows and plan items do not store a copy of the current boundary.

## Consequences

Timeline, daily CLI/report, queued-self matching, and daily recommendation
seeding now share one date contract. Future Dance Plan fulfillment and
Recommendation List Snapshot work must consume the same Interface instead of
using `.date()` or SQL timezone modifiers.

Changing the configured boundary can regroup existing playback views without
rewriting playback timestamps. The persisted-day semantics of a future frozen
Recommendation List Snapshot remain a separate product decision to make when
that schema is designed.
