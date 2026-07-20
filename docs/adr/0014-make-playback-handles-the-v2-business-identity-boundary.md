# 0014. Make Playback Handles the v2 business identity boundary

Date: 2026-07-20

## Status

Accepted

## Context

ADR 0003 made the unified `playback_records` evidence row the direct Timeline
and Insights contract for v1. V2 separates immutable Playback Evidence,
stable Playback Handles and identity relationships, user-authored state, and
rebuildable current interpretation. Exposing evidence identity to ordinary
business code would make user actions ambiguous and allow source-row structure
to leak back into the product model.

## Decision

Playback Handle is the v2 business identity boundary. Timeline, Insights,
reports, recommendations, exclusions, and Dance Plan Fulfillments
address a playback through an input Handle or its resolved Canonical Handle.
Except for explicitly evidence-focused audit, diagnostic, and provenance
workflows, upper business contracts do not accept or expose `evidence_id`.

A Playback Handle ID is stable only within its owning database. V2 does not
guarantee that Handle IDs are globally unique, retain the same value, or can be
compared directly across databases. If a future cross-database import is
implemented, its conservative default should allocate target-local Handle IDs
and remap memberships, redirects, operations, and user-state references. A
future import protocol may preserve an ID only if it separately establishes
that doing so is safe.

Playback Occurrence is the rebuildable current product shape around a Handle,
not a mandated storage object. An implementation may compute it on demand, use
a database view, retain a rebuildable cache, or query evidence tables directly
for efficiency. Those choices are internal: the result must still resolve
membership, Handle redirects, and current interpretation consistently and be
identified to callers by Handle.

Ordinary upper-layer features access playback through one Handle-based Playback
Read Boundary. That boundary owns redirect resolution, current-interpretation
semantics, and evidence-identity isolation. It may use different internal query
strategies for different workloads; this decision does not require one physical
Occurrence table or one universal SQL query.

ADR 0003 remains the historical v1 implementation decision for
`playback_records`, but evidence-row identity is superseded as the v2 business
boundary.

## Consequences

V2 does not require every reader to access one physical occurrence table.
Evidence can remain directly queryable where useful without becoming the
business identity. Storage and caching may evolve independently as long as
Handle semantics and redirect resolution remain consistent.

Timeline, Insights, reports, and recommendations do not independently
reimplement Handle resolution or expose evidence identifiers merely to obtain
a specialized query plan.

Existing `playback_records` readers and glossary terms belong to the v1 runtime
only. V2 does not consume them as migration or compatibility inputs.
