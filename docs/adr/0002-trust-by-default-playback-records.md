# 0002. Use trust-by-default playback acceptance

Date: 2026-06-22

## Status

Accepted

## Context

`dancing-log` records frequent dance playback activity. Requiring the user to manually confirm every dance would create low-value review work, and over time would likely lead to fatigue, skipped maintenance, or careless confirmations. On the other hand, only counting manually confirmed records would make normal statistics too sparse and would undermine the value of live watcher and VRCX history capture.

Most daily playback records are not ambiguous. The product should help the user by accepting normal records and asking for attention only when evidence conflicts, looks unusual, or is explicitly corrected by the user.

The existing live watcher already contains one automatic completion signal named by code as `PROMOTION_COMPLETION_RATIO` and `observed_completion_threshold`. The exact threshold is an implementation detail. The domain decision is broader: conservative automatic acceptance may be based on multiple present or future signals, not only elapsed-time completion.

## Decision

Adopt a trust-by-default playback policy:

- Supported playback evidence is accepted by default unless stronger evidence or explicit user judgment excludes it.
- Active manual user judgment has the highest priority and can override automatic or parser-derived state.
- Manual acceptance and exclusion are reversible overlays, not permanent rewrites of the underlying evidence. Removing the manual decision restores the default result inferred from evidence and source priority.
- Automatic acceptance, including automatic settlement or promotion, is stronger than ordinary playback evidence.
- Watcher records that are not manually judged or automatically accepted and VRCX records are both ordinary playback evidence unless one carries stronger acceptance or exclusion state.
- When review or analysis must choose one representative record from overlapping ordinary evidence, watcher evidence is preferred over VRCX history.
- Higher-priority evidence can negate lower-priority overlapping records, but lower-priority records remain accepted when no stronger evidence explicitly negates them.
- The user experience should emphasize exception handling, not per-record confirmation.
- After the Local Playback Evidence write path is complete, watcher-driven workflows should default to enabling automatic acceptance for conservative watcher evidence.

The implicit priority order is:

- Active manual user judgment.
- Automatic acceptance or automatic promotion.
- Ordinary watcher evidence that has not yet been judged.
- VRCX history evidence.

The final two categories are both ordinary evidence for trust-by-default inclusion, but watcher evidence has the higher source priority when overlapping ordinary records must be resolved for review or analysis.

The normal user-facing states should be simple:

- Accepted: included in normal history and Insights.
- Needs attention: requires user review because something is conflicting, low-confidence, or unusual.
- Excluded: explicitly kept out of normal history and Insights.

Implementation may still store lower-level provenance, completion, settlement, and promotion metadata, but ordinary UI should not require users to understand those internals.

## Consequences

Normal Insights can include accepted records from the watcher and VRCX without waiting for manual confirmation.

Manual work is focused on false positives, conflicts, and corrections instead of confirming every routine playback.

Automatic watcher settlement is encouraged when the rules are conservative enough, because it reduces user labor while preserving the ability to correct mistakes later.

Once watcher writes target Local Playback Evidence directly, automatic acceptance should become the default watcher behavior rather than an opt-in expert mode. The legacy `--promote-live` path remains a transition/compatibility mechanism until then.

The product must provide a clear Manual Exclusion path so the user can quickly remove false positives from statistics.

The product must also provide a clear way to remove a manual acceptance or exclusion and return the record to its default inferred result, because manual decisions can be mistakes.

Merge and review logic must preserve source priority and provenance so stronger judgments can override weaker evidence without destroying raw evidence.
