# 0013. Limit the watcher to source evidence capture

Date: 2026-07-19

## Status

Accepted

## Context

The VRChat log watcher is a source adapter. It observes an append-only external
log stream whose source-specific payloads may expose direct facts such as a
dance identity, source timestamp, `isRandom`, `playerName`, `shuffle`, or a
requester user id. Those facts must remain distinguishable from later product
interpretations.

Older and transitional paths combine capture with folded playback-event state,
watcher-side source labels, settlement, and materialization into product rows.
That makes a parser or capture-loop change capable of silently changing
canonical event summaries, Request Source Type, or history policy. It also
makes rebuilding those projections depend on replaying the watcher itself.

## Decision

The watcher owns only source evidence capture:

- read newly appended VRChat log lines;
- parse source-specific payloads;
- perform deterministic normalization needed to record the observation, such
  as timestamp, URL, dance-system identity, field shape, and units;
- perform bounded same-session correlation or identity enrichment only when the
  contributing observations and provenance remain recorded;
- write the organized observation to the Local Playback Evidence store with
  its raw value or payload, source file, line range, parser name, and other
  audit coordinates.

The watcher does not own:

- a durable `events` summary table or a canonical playback occurrence model;
- merging multiple evidence observations into one canonical event;
- Request Source Type Inference, including `random`, `self`, `other`, or
  `unknown` classification;
- Default Acceptance Result, Review Attention, or accepted-history policy;
- historical repair, rebuild, deduplication, or cross-source reconciliation.

An observed source marker is stored as evidence, not as its later conclusion.
For example, the watcher records `isRandom=true`, PyPyDance's `Random` marker,
or `shuffle=true`; a downstream Request Source Type Inference process decides
whether the current evidence projects to `request_type=random`. Likewise, an
observed source name or user id remains requester evidence until a downstream
identity and request-source process interprets it.

Runtime-only folding may still exist to drive the current overlay or Live
Status, but it is ephemeral operational state. It must not become a durable
product event table or an input that cannot be rebuilt from recorded evidence.

Current compatibility code may still pass watcher observations through folded
event objects or write legacy watcher-side type fields. Those paths are
transitional implementation debt, not the target responsibility boundary, and
new features must not deepen them.

This decision retains ADR 0005's deprecation of `live_playback_events` and its
in-memory Live Status direction. It supersedes any interpretation of ADR 0005
that assigns canonical event summarization, request-type inference, acceptance
policy, or repair ownership to the watcher.

## Consequences

Source adapters stay faithful and replayable. Event/occurrence projection,
Request Source Type Inference, acceptance policy, and repair can evolve and be
rerun without changing the captured evidence.

Evidence rows must preserve enough provenance to explain every downstream
projection. A bare normalized label without the direct source marker that
supported it is insufficient.

Downstream projections may be eventually consistent with newly captured
evidence. Realtime UI state may use the in-memory watcher stream, but durable
Timeline and Insights semantics come from the downstream evidence consumers.
