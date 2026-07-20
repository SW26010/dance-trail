# 0001. Store Playback Evidence Merge audit data in three SQLite tables

Date: 2026-06-21

## Status

Historical for v1; future v2 reference only

The v2 design does not promise or implement cross-`dancing-log` database
merging. It keeps the capability only as a possible future extension. If that
work is ever revived, a new ADR must redefine the workflow around immutable
Playback Evidence, remapped Playback Handles, temporal memberships and
redirects, and the user state that v2 actually supports. The tables and
conflict semantics below are not v2 requirements.

## Context

`dancing-log` needs a Data Operations workflow for merging playback evidence from one target database and one or more read-only source databases or app roots.

The merge flow must support preview, explicit approval, target backup, in-place execution, source fingerprints, conflict review, and later audit from the Web UI. Merge reads source playback evidence and converts it into target-owned local playback evidence; it does not copy source evidence tables verbatim as the target's long-term evidence. Imported manual acceptance or exclusion remains a reversible decision overlay; it does not rewrite the underlying source evidence. Merge does not run new settlement rules from raw parser completion. If overlapping records carry incompatible acceptance or exclusion judgments, source order does not resolve the conflict; the merge creates Review Attention for user decision. A JSON snapshot in the archive directory is useful for recovery and forensic inspection, but it is awkward as the primary query surface for Data Operations.

## Decision

Store merge audit data in the target app database using three tables:

- `merge_batches`: one approved or executed merge plan, including status, target fingerprint, target backup location, source order, and aggregate summary.
- `merge_sources`: one row per source database or app root in the merge source order, including source path, resolved database path, source fingerprint, and source-level summary.
- `merge_record_actions`: one row per planned or executed record action, such as inserting a playback record, filling a user-editable field, accepting a record, excluding a record, creating Review Attention, reporting a manual conflict, or recording a warning.

This ADR does not add promotion-origin fields. Playback acceptance, exclusion, and Evidence Source Priority semantics are governed by the trust-by-default playback policy, and the local evidence root is governed by ADR 0003. This ADR only decides how merge plans and merge audit data are stored.

Merge audit rows and snapshots may preserve enough source provenance to explain a merge later, but source provenance is not the same as retaining the source database's evidence tables as primary target evidence.

Duplicate detection primarily uses `event_key`. When `event_key` differs but `source_file`, `first_line_number`, and `last_line_number` match, the merge treats the rows as the same playback record with key drift. Near matches based on time, video name, and source display name are shown as preview warnings only; they are not automatically merged.

Saved merge plans may be executed later. Before execution, the target and source fingerprints must still match the saved plan. A matching plan may transition from `planned` to `executed`; a stale plan transitions to `invalidated` and must be regenerated.

`merge_record_actions` records only actions with explanatory value. Exact duplicates or other no-op source records are counted in `merge_sources.summary_json` rather than stored as one row per skipped record.

Also write a JSON snapshot beside the target backup in the archive directory. The database tables are the primary query source for the app; the JSON snapshot is a recovery and audit artifact.

## Consequences

Data Operations can show merge history, source drill-down, and conflict details without parsing archive files.

Users can review a merge plan before executing it, while stale plans are blocked from writing against changed databases.

Merge preserves and applies existing acceptance, exclusion, and Evidence Source Priority state as reversible decisions, but it does not run new settlement or promotion from completed live evidence. Parser completion alone does not create new acceptance judgments during merge.

The target database owns the imported evidence after execution, so future Timeline and Insights queries should read target-local `playback_records` evidence and provenance rather than depend on attached or copied source tables.

Acceptance conflicts remain visible as Review Attention for manual decision.

Merge execution can be explained later even though source databases are never mutated.

Large merges do not flood the audit table with no-op rows, but exact duplicate detail is available only as aggregate source-level counts unless a future debugging mode captures more detail.

The schema grows beyond playback/catalog tables, but the merge audit tables are isolated from normal Timeline and Insights calculations.

Future migrations must preserve these audit rows or intentionally archive them during rebuild workflows.
