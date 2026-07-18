# Dancing Log

`dancing-log` records and reviews local VRChat dance playback activity, including live playback, historical imports, recommendations, and playback evidence.

## Language

**Web UI**:
The primary user-facing interaction surface for operating `dancing-log` as a whole. It includes configuration, history review, live status, recommendations, imports, and overlay-related controls.
_Avoid_: OBS overlay, overlay page

**Navigation Entry**:
A visible Web UI entry point for a workflow the user intentionally opens. The MVP primary navigation entries are Home, Timeline, Catalog, Lists, Insights, Data Operations, and Settings; Overlay remains a product area without its own primary navigation entry.
_Avoid_: product area, database table, feature category

**Home**:
The Web UI overview surface for current status, recent activity, pending attention, and shortcuts into the main work areas. Home highlights watcher and overlay state, unchecked playback records, recent operation results, and missing setup; it does not own catalog, timeline, list, insight, data operation, or settings workflows.
_Avoid_: landing page, dashboard module, catch-all page

**OBS Overlay**:
A viewer-facing display surface for live playback status in OBS. It is one feature exposed by the Web UI, not the main interaction surface. Stopping its standalone listener is terminal for that listener's accepted viewer connections: after stop returns, none may continue serving overlay state.
_Avoid_: Web UI, control panel

**Local Web UI**:
The Web UI product boundary for one user operating `dancing-log` on their own machine. It is not a shared service, remote dashboard, or multi-user web app. Its HTTP boundary accepts only the expected localhost `Host`, including for read and event-stream requests.
_Avoid_: hosted app, LAN dashboard, multi-user app

**Dance Plan**:
A durable planned set of dance items the user intends to dance. A Dance Plan can remain active across local dates when unfinished items carry forward. It represents intention before playback, separate from the catalog of available dance tracks and the timeline of actual dance events.
_Avoid_: catalog, timeline, history

**Dance Plan Fulfillment**:
The relationship between a Dance Plan item and an Accepted Playback Record that satisfied it. Fulfillment can promote the playback record's Request Source Type to planned, but it does not create playback evidence and does not replace requester identity.
_Avoid_: playback evidence, requester identity, manual exclusion

**Superseded Dance Plan Item**:
A Dance Plan item whose planned intent has been taken over by a later same-target item, so it no longer carries forward or directly fulfills playback. It is different from a skipped item and should not silently recreate a fulfillment the user removed.
_Avoid_: skipped item, fulfilled item, deleted playback record

**Removed Dance Plan Item**:
A Dance Plan item the user removed from the active plan while the system keeps enough history to explain or undo the removal. A removed item no longer carries forward, supersedes another item, or fulfills playback.
_Avoid_: active planned item, skipped item, physical database deletion

**Local Dance Day Boundary**:
The user-configured time-of-day that separates one local dance day from the next for daily history, Dance Plan views, intended dates, and fulfillment matching. The default boundary is 00:00 local time, but the user may move it later, such as 01:00 or 03:00, so late-night dances still belong to the previous dance day.
_Avoid_: timezone, playback timestamp, plan identity

**Catalog**:
The inventory of available dance content and the real music those entries represent. Catalog owns dance tracks, music tracks, local preference flags, and provider matching review, but not dance plans or historical playback.
_Avoid_: dance plan, timeline, data operations

**Dance Track**:
One playable dance version inside a dance system, such as a WannaDance, PyPyDance, or Dudu entry. It may represent a specific choreography, dancer, difficulty, player count, or system-local id.
_Avoid_: song, music track

**Dance Preference**:
A user preference attached to a dance track, such as favorite or want-to-learn. It describes preference for a playable dance version, not for the underlying music track.
_Avoid_: music preference, playlist item

**Recommendation Algorithm**:
The changeable scoring or selection strategy that proposes dance tracks to the user. It may change without rewriting historical Request Source Type evidence; only an explicitly enabled or accepted result becomes a Recommendation List Snapshot.
_Avoid_: recommendation evidence, request source type, dance plan

**Recommendation List Snapshot**:
A frozen list of recommended dance tracks explicitly enabled or accepted by the user for a Local Dance Day. It can be evidence for Request Source Type Inference only for same-day playback after the snapshot was frozen, and it is separate from the mutable Recommendation Algorithm, Dance Plan, and playback evidence.
_Avoid_: algorithm result, preview, dance plan item, playback record

**Music Track**:
The real song independent of dance system and choreography. Music-provider links such as NetEase, QQ Music, Spotify, or popularity metrics belong to the music track level.
_Avoid_: dance track, dance-system entry

**Insights**:
Derived views that summarize and explain accepted playback, catalog, and dance-plan data, such as frequency, trends, source distribution, and neglected favorites. Insights are analysis surfaces, not the source of historical truth; manually excluded playback records do not contribute to normal insight calculations.
_Avoid_: timeline, raw history, catalog

**Data Operations**:
Controlled workflows that change or rebuild local data in bulk, such as importing VRCX history, syncing dance-system catalogs, rebuilding generated data, backup and restore, and future database merge flows. It is not a raw database editor.
_Avoid_: settings, raw SQLite editor, ad hoc table editing

**Settings**:
The local environment and default preference surface for paths, database location, VRChat and VRCX sources, overlay defaults, and watcher defaults. Settings does not own catalog labels, dance plans, playback history, or analytics.
_Avoid_: data operations, catalog management, dance plan management

**Watcher Default**:
A saved preference that affects how the VRChat log watcher should run when an app workflow starts it, such as whether watcher auto-start is desired. It is not an immediate start or stop command.
_Avoid_: live watcher control, process manager

**Overlay Default**:
A saved preference that affects whether an app workflow should publish live watcher state to the OBS Overlay. Enabling overlay auto-start implies watcher auto-start, because the overlay depends on live watcher state. In a Local Web UI session the overlay route remains available on the Web UI origin even when publication is stopped.
_Avoid_: OBS overlay page, live overlay control

**Desktop Tray Entry**:
The Windows notification-area entry for running `dancing-log` as a local desktop app. It opens the Local Web UI, exposes immediate watcher and overlay controls, and owns quitting the background app session.
_Avoid_: CLI command, Web UI navigation entry, background service

**Live App Session Runtime**:
The runtime module that owns immediate watcher and overlay lifecycle for the current local app session, including start, stop, status, recent errors, and recent watcher stats. Synchronous CLI and background entry points share one watcher owner, and all public watcher entry points enforce the same application/database lifetime exclusion. Lifecycle transitions are serialized and distinguish running, stopping, and stopped; a replacement cannot start until its predecessor has terminated. Closing is irreversible. Terminal shutdown must reject incomplete HTTP work without truncating an accepted write, watcher settlement, database commit, or capture finalization. CLI, Desktop Tray Entry, and Web UI controls use this runtime instead of reimplementing watcher and overlay transition rules.
_Avoid_: parser runtime, saved configuration, background service

**Live Watcher Control**:
An immediate start or stop command for the current VRChat log watcher process. It changes the running app session and is separate from Watcher Default.
_Avoid_: watcher default, saved configuration, startup preference

**Live Overlay Control**:
An immediate start or stop command for publishing current watcher state to the OBS Overlay. It depends on Live Watcher Control: turning overlay on keeps watcher on, and turning watcher off also turns overlay publication off. In a Local Web UI session it does not start a second HTTP server; the Web UI owns the shared localhost listener. The overlay state contract distinguishes stopped publication from enabled publication that has not captured a current playback event yet.
_Avoid_: overlay default, saved configuration, OBS overlay page

**Full Configuration Editor**:
The Settings surface that exposes every supported local configuration key for inspection and editing. It edits the local app configuration, not catalog data, playback history, or bulk data workflows.
_Avoid_: setup wizard, raw JSON editor, data operations

**Advanced Setting**:
A supported Settings field that remains editable in the Full Configuration Editor but is placed in a lower-priority area because most users do not need to change it during normal setup.
_Avoid_: hidden setting, unsupported configuration key

**Internal App Path**:
A configurable path for data or output that `dancing-log` owns under the local application boundary by default, such as the app database, queued-self files, captures, run logs, source-log archives, or recording-frame outputs.
_Avoid_: external source path, VRChat log directory

**External Source Path**:
A configurable path to user- or tool-owned data that `dancing-log` reads from outside its own application boundary, such as VRChat logs, VRCX history, WannaDance cache files, or recordings.
_Avoid_: internal app path, generated output path

**Detected Source Path**:
A candidate external source path found from the local machine environment. It may be offered to the user in Settings, but it does not become saved configuration unless the user explicitly chooses it.
_Avoid_: saved configuration, default internal path

**Automatic Source Path**:
An External Source Path resolved from the current local machine environment when a workflow needs that source. A preview in Settings shows the current detection result only; it is not a saved value or a promise of what a later run will detect.
_Avoid_: saved configuration, one-time setup result, internal app path

**Manual Source Path**:
An External Source Path explicitly saved by the user for cases where automatic detection is missing, wrong, or not specific enough.
_Avoid_: detected source path, internal app path, generated output path

**Self User Identity**:
The stable VRChat user id for the local user, used to distinguish the user's own playback requests from other requester identities.
_Avoid_: display name, source path, VRCX database path

**Detected User Identity**:
A candidate Self User Identity found from local source metadata. It may be shown with a display-name label for confirmation, but the display name is not the identity key.
_Avoid_: saved configuration, display-name preference, source path

**Manual User Identity**:
A Self User Identity explicitly provided or corrected by the user when detection is unavailable, ambiguous, or stale.
_Avoid_: detected source path, display name, generated default

**Requester Identity**:
The VRChat identity observed for the user who requested or triggered a playback record. It may include the event-time display name and a stable VRChat user id, and it is separate from Self User Identity. Random playback evidence is not Requester Identity and must not be represented by setting requester fields to blank, NULL, or "random".
_Avoid_: self user identity, display-name preference, source classification, random source marker

**Draft Configuration**:
The unsaved Settings form state being edited by the user before it is written to the local app configuration file. Draft configuration can be validated and reset without changing the currently saved configuration.
_Avoid_: active configuration, autosaved settings

**Saved Configuration**:
The local app configuration currently persisted in `config/dancing-log.local.json` and used as the default for app workflows. Saved configuration is changed only by an explicit save action in the Web UI.
_Avoid_: draft configuration, generated defaults

**Valid Configuration Value**:
A draft field value that satisfies the requirement for its specific configuration key and is eligible to be saved. Invalid values may remain in the draft while the user is editing, but they cannot become saved configuration.
_Avoid_: syntactically valid text, best-effort setting

**Unsupported Configuration Key**:
A key found in the local app configuration file that is not part of the current supported Settings contract. Unsupported keys are preserved when saving from the Web UI, but the user is warned that `dancing-log` does not understand them.
_Avoid_: hidden supported setting, raw JSON field

**Live Status**:
The Home surface for current watcher state, current playback, current session activity, overlay availability, and realtime capture health. Its current playback comes from an in-memory watcher state that remains current even when OBS Overlay publication is disabled; Overlay enablement gates the viewer-facing projection, not Home's watcher context. Live Status is not a separate primary navigation area in the MVP.
_Avoid_: timeline, history, archive, primary navigation

**Timeline**:
The chronological review and correction surface for playback records. Timeline defaults to the latest local date that has playback records, preserves time order within the selected date, and uses color, icons, and labels to show each record's acceptance, review attention, and relevant observation details.
_Avoid_: status buckets, live monitor, insights, data operations

**Playback Record**:
The Web UI timeline item representing one parsed playback-related record, whether it comes from historical import, live observation, interrupted observation, or another parsed source. It is not the same as a raw VRChat log line.
_Avoid_: raw log line, database row

**Watcher-Derived Playback Record**:
A Playback Record created from live watcher evidence once the observation has a dance identity. It may represent playback observed from the start or playback discovered after it is already in progress. Its existence means the event is reviewable in Timeline; whether it counts in history is decided separately by acceptance policy.
_Avoid_: live playback record, overlay state, accepted playback record, actual-play-only record

**Manual Log Entry**:
A user-created Local Playback Evidence record for a playback the user says happened, with user-supplied playback facts such as dance track and played time. It creates playback evidence; it is not a Manual Record Update, not a Dance Plan item, and not a direct Request Source Type edit. Request Source Type Inference still decides the record's Request Source Type from stable inputs after the manual evidence exists.
_Avoid_: request source override, plan item, manual playback decision

**Watcher Settlement**:
The watcher action that resolves a pending Watcher-Derived Playback Record into its default acceptance result after enough lifecycle or playback evidence is available. Settlement may accept a record, mark it attention-needed, exclude it, or leave it pending when the observation is still active or the watcher ended before settlement.
_Avoid_: raw event parsing, manual decision, playback record creation

**Playback Observation**:
The locally observed playback lifecycle state for a playback record, such as an active observation, completed observation, interruption, watcher stop, video shutdown, or observed end boundary. Playback Observation can inform the Default Acceptance Result, but it is not the request source, not the evidence identity, and not a manual decision.
_Avoid_: request source, acceptance result, raw watcher payload, manual decision

**Request Source Type**:
The normalized request/playback-source classification stored on a playback record, such as planned, recommend, self, other, random, or unknown. Request Source Type is stored today in legacy `source_type`, with `request_type` as the clearer long-term field name. It is not evidence strength, not a confidence score, and does not decide whether the record is effectively accepted, excluded, or needs attention. Self, other, and random are mutually exclusive sibling classifications rather than an ordered priority ladder. Coarse watcher-side labels such as player and old queued_self values are legacy parser or import evidence, not canonical Request Source Type values.
_Avoid_: requester identity, evidence source priority, confidence score, acceptance status, review status, raw watcher label

**Request Source Type Inference**:
The independent, repeatable process that derives or repairs a playback record's Request Source Type from stable inputs such as Local Playback Evidence, Requester Identity, Self User Identity, Dance Plan Fulfillment, Recommendation List Snapshots, and active Manual Record Updates. It is not a watcher, importer, writer, or ordinary read-path responsibility, and it does not require realtime execution.
_Avoid_: watcher enrichment, VRCX import, recommendation algorithm, acceptance settlement

**Accepted Playback Record**:
A playback record included in normal history and Insights under the trust-by-default policy. A record may be accepted because it comes from a supported source, was automatically settled, or was manually confirmed; manual confirmation is not required for ordinary inclusion.
_Avoid_: manually confirmed only, promotion-only record, raw parser row

**Pending Playback Record**:
A playback record whose evidence is reviewable but not yet settled into accepted, attention-needed, or excluded state. Pending is for active or incomplete observation state; it is not a request for human review by itself and does not count in normal history or Insights. Pending should normally be settled when the watcher stops gracefully; a leftover pending watcher-derived record indicates the watcher ended unexpectedly before settlement. Recovery or repair workflows may convert stale pending watcher records into attention-needed records, but ordinary Timeline or Insights reads should not mutate them.
_Avoid_: needs attention, excluded, accepted, raw live state, graceful final state, read-time repair

**Default Acceptance Result**:
The accepted, pending, excluded, or attention-needed result inferred from playback evidence and Evidence Source Priority before any active manual decision is applied. It is one default evidence-derived outcome, not a combination of a status field plus a separate history-counting flag. Restoring the default result means removing the manual decision overlay and letting the evidence rules decide again.
_Avoid_: stored truth, permanent user state, raw parser status, history-counting flag

**Manual Playback Decision**:
A reversible user-authored decision about whether a playback record should be accepted, excluded, or reviewed. Manual Playback Decision is strongest while active, but it does not erase playback evidence or permanently replace the Default Acceptance Result. Pending is not a Manual Playback Decision because active observation state is inferred from evidence rather than chosen by the user.
_Avoid_: deletion, source rewrite, irreversible confirmation, pending playback

**Manual Exclusion**:
A reversible Manual Playback Decision that a playback record should not count as accepted playback. Manual Exclusion is the normal way for the user to correct false positives without needing to confirm every normal record.
_Avoid_: deletion, parser interruption, automatic conflict

**Review Attention**:
A user-facing cue that a playback record may need human attention because of a conflict, low-confidence evidence, or unusual source state. Review Attention is separate from acceptance and pending observation state: most accepted records should not require attention, and pending records should not be treated as attention-needed until settlement or evidence rules say so.
_Avoid_: required confirmation, acceptance status, parser status, pending playback

**Trust-By-Default Playback Policy**:
The product rule that supported playback evidence is accepted unless stronger evidence or explicit user judgment excludes it. This policy keeps day-to-day use lightweight: the user handles exceptions instead of confirming every dance.
_Avoid_: manual-only history, review-everything workflow, raw import

**Evidence Source**:
The stable adapter family that produced a Local Playback Evidence record, such as VRCX history, VRChat log replay, live VRChat log observation, or manual log entry. Evidence Source identifies the evidence family, not a source table, source row, import operation, script version, or raw payload location.
_Avoid_: request source type, source table, source row id, import batch, script version

**Evidence Source Priority**:
The evidence-strength precedence used when overlapping playback records disagree. Evidence Source Priority is a strategy result derived from evidence source, default acceptance, and active manual decisions; it should not be treated as a separate source fact. Active Manual Playback Decision is strongest, automatic acceptance is stronger than ordinary playback evidence, and ordinary watcher evidence is preferred over VRCX history when review or analysis must choose one representative record. Higher-priority evidence can negate lower-priority overlapping records; without that stronger negation, ordinary records remain accepted under the trust-by-default policy.
_Avoid_: request source type, filesystem order, newest-row-wins, stored source fact

**Automatic Acceptance**:
A system-derived acceptance decision for a playback record, based on supported source semantics or conservative settlement rules. Automatic Acceptance is not limited to an elapsed-time threshold; future rules may use additional conservative signals. Automatic Acceptance lets normal records count without manual confirmation, but it is weaker than an active Manual Playback Decision or Manual Record Update.
_Avoid_: manual confirmation, parser completion, promotion

**Ordinary Playback Evidence**:
A supported playback record with no manual judgment and no automatic acceptance state, such as an unjudged watcher record or a VRCX history record. Ordinary Playback Evidence is accepted by default, but it is weaker than automatic acceptance and manual judgment when overlapping records disagree.
_Avoid_: untrusted record, ignored record, needs manual confirmation

**Acceptance Conflict**:
A Review Attention case where overlapping playback records disagree on accepted or excluded state in a way that source order must not resolve automatically. The user must decide which acceptance judgment, if any, should apply.
_Avoid_: parser conflict, source-order fill, duplicate row

**User-Editable Playback Field**:
A playback-record field where the user can make a durable judgment or correction, such as acceptance, exclusion, dance-track mapping, requester identity, or note. These fields may be overridden by Manual Record Update. Request Source Type is inferred from stable inputs rather than directly edited by the user in the first product shape.
_Avoid_: parser evidence, raw log metadata, automatic inference

**Playback Evidence Field**:
A playback-record field that preserves what the source parser or raw log observed, such as source file, line range, raw event payload, parser names, and original timing signals. Evidence fields are preserved for audit and are not overwritten by Manual Record Update.
_Avoid_: user correction, review status, accepted-history inclusion

**Source Playback Evidence**:
Playback evidence as it exists inside a source database or app root before a Playback Evidence Merge. Source Playback Evidence explains where an imported record came from, but it remains the source's evidence rather than becoming the target app root's long-term evidence verbatim.
_Avoid_: target history, local evidence, copied truth

**Local Playback Evidence**:
Playback evidence owned by the current app root after parsing, importing, or merging. Local Playback Evidence is normalized enough for Timeline, Insights, and review to query directly, even when it is derived from Source Playback Evidence or older local history roots. Source-side coordinates, raw payloads, and legacy source details explain provenance, but they are not the local evidence identity.
_Avoid_: source row copy, raw source event, foreign table, external database state

**Local Evidence Identity**:
The stable identity used by local writers, imports, replays, and merges to decide whether incoming playback evidence represents the same Local Playback Evidence already owned by the current app root. It is separate from the database row id used for local references and from source-side origin identity used for provenance.
_Avoid_: database row id, source row id, origin coordinate, display label

**Playback Record Origin**:
The source-side coordinate, raw payload, and audit detail attached to a Local Playback Evidence record. Playback Record Origin explains where the local evidence came from and how it was ingested; it is not the timeline record, not the local evidence identity, and not a user decision.
_Avoid_: playback record, request source type, local evidence identity, manual decision

**Legacy Playback Root**:
An older local playback-history root kept only to read or migrate existing records into Local Playback Evidence. It is not the long-term canonical root for new playback capture, review, merge, or Insights.
_Avoid_: canonical timeline, source evidence, permanent history root

**Playback Evidence Merge**:
A Data Operations workflow that imports playback records from another `dancing-log` database or app root into the current local review flow. It converts Source Playback Evidence into Local Playback Evidence for Timeline review and does not, by itself, make every imported record count as accepted history.
Playback Evidence Merge may import existing acceptance, exclusion, and review-attention state from source records as reversible decisions, but it does not run new settlement rules from raw parser completion.
_Avoid_: raw SQLite merge, settings import, timeline edit

**Merge Source Order**:
The user-visible order in which multiple source databases or app roots are applied to one target database during a Playback Evidence Merge. The selected order is part of the merge decision because it can affect which source fills still-empty user-editable fields.
_Avoid_: filesystem order, modification-time order, implicit priority

**Merge Plan**:
A user-reviewed plan for a Playback Evidence Merge that describes the target, sources, source order, additions, field fills, skipped records, warnings, and conflicts before any data is written. A Merge Plan is tied to the exact source and target state it previewed; if that state changes, the plan must be refreshed before execution.
_Avoid_: rough estimate, execution log, raw diff

**Merge Execution**:
The Data Operations action that applies an approved Merge Plan to the target database. Merge Execution first backs up the target database, then reads each source in Merge Source Order, and applies the merge in place to the target database.
_Avoid_: export-only preview, database replacement, source mutation

**Merge Target Backup**:
The mandatory restore point captured immediately before Merge Execution. It is stored under the target app root's data archive area and includes the target SQLite database plus any active SQLite sidecar files needed for a consistent restore.
_Avoid_: optional export, source backup, partial database copy

**Merge Source Fingerprint**:
The source-database identity captured for audit during a Playback Evidence Merge, including the source path, resolved database path, file metadata, integrity result, schema fingerprint, and content fingerprint. Source databases are read-only during merge, but their fingerprints are stored so the merge can be explained later.
_Avoid_: source backup, display name, temporary picker value

**Review Status**:
The user's durable attention or correction state for a playback record. Review Status does not mean every accepted playback record must be manually confirmed; under the trust-by-default policy, normal records can count without user action.
_Avoid_: deletion, raw parser status, completion status

**Manual Record Update**:
A user-authored correction to a playback record after import or review, such as dance-track mapping, requester identity, note, or other user-editable timeline fields. For overlapping records, manually updated fields are preferred over imported or parser-derived fields, while raw evidence remains preserved for audit. Acceptance and exclusion are Manual Playback Decisions, not direct Request Source Type edits.
_Avoid_: parser backfill, automatic merge, raw evidence edit

**Manual Merge Conflict**:
A Playback Evidence Merge case where overlapping records both contain Manual Record Updates but disagree on one or more user-editable playback fields. The current target record remains active until the user explicitly chooses whether to keep the target judgment or adopt the source judgment.
_Avoid_: automatic overwrite, parser conflict, duplicate row

**Raw VRChat Log**:
Low-level diagnostic evidence captured from VRChat output logs. Raw VRChat logs are not normal user-facing timeline content and should only appear in explicit debugging or forensic details.
_Avoid_: timeline record, playback history
