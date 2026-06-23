# 0005. Deprecate live playback event rows for normal watcher runs

Date: 2026-06-23

## Status

Accepted

## Context

The live watcher used `live_playback_events` as a folded runtime table and promoted only eligible completed rows into `playback_records`. That split left some reviewable watcher observations outside Timeline, even though ADR 0003 made `playback_records` the Local Playback Evidence root for Timeline, review, Insights, and history.

## Decision

Normal watcher workflows should write watcher-derived playback evidence directly into `playback_records` once a folded live observation has a dance identity. New records may start as pending and later settle into accepted, attention-needed, or excluded default status. `live_playback_events` is deprecated for normal operation: it may remain available only behind explicit test or experimental paths, and those paths should show a clear deprecation warning.

The watcher write path should use a watcher-specific materializer that maps folded live playback events into `playback_records`, then delegates storage to the generic playback-record writer. Live runtime code should not embed playback-record mapping rules, and the generic writer should not learn watcher-specific settlement policy.

Pending is a first-class effective playback status. Timeline may show pending watcher-derived records, while Insights, daily reports, and recommendations continue to read only effectively accepted records. Manual playback decisions should not support pending; pending is evidence-derived runtime state.

Watcher settlement should keep existing watcher reason values compatible instead of inventing a replacement vocabulary. Current reasons include `observed_completion_threshold`, `room_left`, `application_quit`, `superseded_before_completion`, `unknown_duration_before_superseded`, and `observed_mid_play`. New watcher-derived `playback_records` should also use `live_observation_pending` for an active pending observation, `watcher_stopped` for graceful watcher stop, `video_shutdown` when the video subsystem stops without full application quit, and `watcher_interrupted_unexpectedly` when a recovery or repair workflow converts stale pending records left by an ungraceful watcher exit.

Mid-play observations should begin as pending watcher-derived playback records rather than immediate attention-needed records. They can remain visible as current playback while active, then settle into attention-needed, non-counting records when the watcher observes a lifecycle end or another settlement boundary.

Graceful watcher stop is a settlement boundary, not an automatic interruption. When the watcher stops normally, pending watcher-derived records should first be evaluated for automatic acceptance; records that meet the conservative acceptance rule become accepted, and the remaining pending records become attention-needed, non-counting records with `watcher_stopped`.

Future watcher writes should distinguish `video_shutdown` from `application_quit`. Existing rows or tests that used `application_quit` for video subsystem shutdown remain compatible legacy evidence, but new watcher settlement should preserve the more specific reason.

Stale pending repair is application maintenance, not watcher responsibility and not read-path behavior. App startup maintenance and future Data Operations repair workflows may convert stale `live_observation_pending` watcher records into attention-needed, non-counting records with `watcher_interrupted_unexpectedly`; Timeline, Insights, reports, recommendations, and other ordinary reads must remain side-effect-free.

New watcher-derived playback records should not depend on `live_playback_events.id` for source identity. The old path used that row id because `live_playback_events` was the durable folded-state table; once that table is deprecated for normal operation, the stable source identity should come from the watcher folded event itself. New watcher records should use a logical source table such as `watcher_playback_events` plus the stable watcher event key as `source_event_key`, and the source fingerprint should be derived from that logical source identity. Existing rows that use `source_table = live_playback_events` remain valid legacy evidence and must not conflict with new watcher records.

Overlay and live status should use the in-memory folded watcher event stream during normal operation. They should not introduce another durable live-state table to replace `live_playback_events`; persisted playback evidence belongs in `playback_records`, while current display state belongs to the running watcher session.

The old live promotion CLI vocabulary is internal legacy surface and does not require a long public compatibility period. Normal watcher commands should no longer expose `--promote-live` or `--no-promote-live` semantics. If `--live-db` remains reachable for tests or experiments, it must be explicitly deprecated or experimental and should warn that normal operation writes watcher-derived playback evidence to `playback_records`.

DuduDance identity parsing should not block the watcher playback-record materialization upgrade. Until a Dudu parser can produce a stable dance identity, Dudu-shaped URLs may remain parser evidence or unsupported observations, but they should not create watcher-derived playback records. Adding Dudu identity support is separate catalog/parser work.

Stale pending repair should run from app startup maintenance for write-capable app workflows, including desktop/Web UI startup and standalone watcher startup. Pure read-only commands such as day/history/report-style reads must not repair records as a side effect. Future Data Operations repair may provide an explicit manual entry point for the same repair rule.

## Consequences

Timeline, Insights, daily reports, and recommendations continue to depend on `playback_records` plus the effective projection instead of reading live tables. Overlay and live status should use the in-memory folded event stream or another runtime-only state path, not a normal-history table. Any remaining `live_playback_events` usage is transitional and should not define product semantics.
