# 0004. Run a one-time legacy database cleanup into unified records

> Privacy note: Personal paths and activity examples are anonymized. Replace example paths with your own; sample timestamps are illustrative. Aggregate results and technical conclusions are retained.

Date: 2026-06-22

## Status

Accepted

## Context

The current legacy cleanup has four concrete inputs: the project app root, `path/to/portable-snapshot`, `path/to/watcher-snapshot-a`, and `path/to/watcher-snapshot-b`. The project database contains the existing VRCX-derived history, while the portable roots mainly contain old live watcher rows. This is a one-time internal legacy database merge/cleanup to preserve useful old data before the future `playback_records` model takes over; it is not the productized reusable merge workflow.

## Decision

Treat the old databases as read-only Legacy Playback Roots. Do not copy their `dance_events`, `vrcx_import_events`, or `live_playback_events` tables as long-term target evidence. Instead, convert useful legacy rows into target-owned `playback_records`, with source provenance retained for audit and diagnosis.

Use these cleanup rules:

- The project `dance_events` and `vrcx_import_events` rows represent one VRCX history set. Create one legacy VRCX playback record per event, using the VRCX import row as provenance when available rather than creating a second playback record.
- Live watcher rows become playback records only when they have `actual_play_at` and a parsed dance identity.
- Completed live rows with `completion_reason = observed_completion_threshold` become automatically accepted playback records.
- Live rows with actual play evidence but `interrupted`, `pending`, `observed_mid_play`, or other non-completed state are retained with Review Attention but default to not counting in normal history or Insights. They are evidence for later review, not deleted rows and not clean automatic acceptance.
- Live rows without actual play time or without parsed dance identity are excluded from normal playback records and reported in the cleanup summary.
- The target catalog is the authority for dance-track identity. Missing target catalog entries should be synced or created as minimal stubs with attention before the affected playback records are treated as clean.
- For this cleanup, scan `path/to/catalog-snapshot` as supplemental WannaDance metadata before falling back to minimal WannaDance stubs.
- Supplemental WannaDance metadata is best-effort. If artist, dancer, player count, group, or other catalog fields cannot be verified from available metadata, leave them empty rather than guessing from playback display text.
- Missing PyPyDance catalog coverage is not a blocker for this cleanup. Create minimal PyPyDance dance-track stubs with Review Attention rather than waiting for a full PyPyDance catalog model.
- All imported times must be normalized into the new playback-record time format, while original source strings remain provenance.
- Do not automatically merge near-duplicate VRCX and watcher records based only on similar time and dance identity. Report near matches in the cleanup report for later review.
- After cleanup, when review or analysis detects overlapping ordinary VRCX and watcher records and needs one representative result, watcher-derived playback records take priority over VRCX-derived records.
- This cleanup does not need a full manual review UI for retained non-counting watcher evidence. Store the state needed for later review and include counts plus representative examples in the report; a future Timeline/review surface can provide per-record accept or exclude controls.
- After cleanup, normal Timeline and Insights reads should use `playback_records` rather than continuing to read `dance_events`, `vrcx_import_events`, or `live_playback_events`. The old tables may remain for compatibility or forensic inspection, but they must not keep participating in ordinary history/statistics reads where they could double-count cleaned records.

The legacy cleanup should provide a lightweight preview report, back up the target database, write in a transaction, and produce an execution summary. The report only needs enough aggregate detail and representative examples to explain what will be imported, retained for review, excluded, or stubbed; it does not need a row-by-row review UI or a dedicated preview table. Execution must create the target backup before writing. If writing fails, the transaction must roll back without leaving partial cleanup rows, while the backup and failure summary remain available for diagnosis. Do not write the productized merge audit tables (`merge_batches`, `merge_sources`, or `merge_record_actions`) for this cleanup. It is allowed to reuse future merge ideas such as source fingerprints, source order, and provenance on imported records and summary artifacts, but it is not the productized multi-source merge workflow.

## Consequences

The current old data can be cleaned quickly without making old table shapes part of the future public data model.

Future Timeline, Insights, acceptance, exclusion, and merge behavior can be designed around `playback_records` and reversible decisions rather than around `dance_events`.

Some forensic live rows will be preserved only in source provenance or cleanup summaries, not as normal playback records.

Catalog gaps discovered during cleanup are explicit data-quality work instead of hidden nullable timeline records.
