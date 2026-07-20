# 0015. Cut over cleanly from playback model v1 to v2

Date: 2026-07-20

## Status

Accepted

## Context

V1 uses `playback_records` as both normalized playback storage and a product
read root. V2 uses immutable Playback Evidence, stable Playback Handles,
identity relationships, user intent, and rebuildable current interpretation.
The two generations do not have a safe row-for-row mapping, and preserving a
transitional bridge would require dual identity, dual writes, and cross-model
state reconciliation.

## Decision

V2 denotes the playback database structures, their relationships, and the
domain logic that directly depends on them. It is not a generation of every
application feature. Once that model contract is implemented, the product cuts
its playback-data authority directly from v1 to v2; this does not require
reproducing every v1 UI, report, or operational workflow.

There is no v1-to-v2 data migration, dual write, mixed read authority, or
compatibility fallback. Before cutover the current application remains v1;
after cutover v2 is the sole product authority and `playback_records` no longer
participates in runtime decisions.

Historical VRCX content and VRChat logs that are still available may be
ingested again through normal v2 import and replay adapters. This creates new
v2 Playback Evidence and is not a conversion of v1 records. V1-only user
state and history that cannot be recreated from supported sources may be lost.
The old database may be retained as a manual backup, but v2 does not read it as
a compatibility source.

Application rollout acceptance is specified separately from the v2 model. The
currently confirmed rollout requirements are Timeline browsing by Local Dance
Day and reversible manual accepted/excluded overlays with restoration of the
default result. The current Insights source-distribution and top-track views
may return after cutover and do not block the model authority switch. These
rollout choices do not enlarge the v2 data-model boundary.

## Consequences

Implementation effort stays focused on a coherent v2 model rather than a
temporary bridge. Cutover may cause a short period of unavailable or incomplete
history while supported sources are reingested, and unreconstructable v1 state
is deliberately not preserved.

The physical cutover procedure, backup handling, and timing remain operational
implementation choices; they cannot reintroduce dual authority or v1 runtime
compatibility.

This clean generational cutover does not make already-deployed v2 databases
disposable. V2 stores durable user intent and identity history that source
reingestion cannot reconstruct. Starting with the first v2 schema, subsequent
v2 schema changes therefore use an explicit database-local schema version and
ordered, validated, transactional migrations. This v2-to-v2 evolution path is
separate from, and does not weaken, the decision to provide no v1-to-v2 data
migration.
