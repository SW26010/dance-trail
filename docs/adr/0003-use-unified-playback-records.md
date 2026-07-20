# 0003. Use unified playback records as the local evidence root

Date: 2026-06-22

## Status

Superseded by ADR 0014 for v2. Retained as the accepted v1 implementation record.

## Context

`dancing-log` currently has playback-shaped data in several places: historical `dance_events`, source-specific VRCX import rows, and live watcher rows. The merge design now treats source database evidence as input that must be converted into target-owned Local Playback Evidence, not copied as long-term source-table state. The current data format has not been widely distributed, and existing `dance_events` data is limited enough to treat as legacy input during the merge transition.

## Decision

Use a unified local playback evidence root for future Timeline, Insights, review, and merge behavior. In implementation terms this root should be represented by `playback_records`, with manual acceptance/exclusion/review decisions stored separately as reversible overlays.

`dance_events` is no longer the long-term canonical root for new playback history. It may be read as a legacy source during migration or limited old-data merge, but new capture, import, and merge work should write Local Playback Evidence into `playback_records`. After the transition, the old root should be cut off from primary user-facing workflows.

The `playback_records` schema created by the one-time legacy cleanup is accepted as the Local Playback Evidence v0 read contract for Timeline and Insights. It is not merely a throwaway cleanup artifact. Future work may add manual-decision overlays, cleaner writer APIs, or migrations, but normal product reads should move to this contract before broader write-path redesign.

## Consequences

Timeline and Insights can reason over one local playback model instead of treating `dance_events`, `live_playback_events`, and `vrcx_import_events` as competing history roots.

Merge execution converts source evidence into target-owned playback records, while merge audit tables retain enough source provenance to explain where those records came from.

This increases implementation cost because existing read paths and promotion/import code must move away from writing or querying `dance_events` as the primary history table.

The transition should include a compatibility or migration path for existing `dance_events` rows, but that path is temporary and should not define the future model.

The concrete cleanup rules for the current legacy databases are recorded separately in ADR 0004 so that one-time old-data handling does not become the long-term playback-record contract.
