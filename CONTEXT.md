# DanceTrail

`dance-trail` records and reviews local VRChat dance playback activity, including live playback, historical imports, recommendations, and playback evidence.

## Language

**Web UI**:
The primary user-facing interaction surface for operating `dance-trail` as a whole. It includes configuration, history review, live status, recommendations, imports, and overlay-related controls.
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
The Web UI product boundary for one user operating `dance-trail` on their own machine. It is a Windows desktop productivity surface governed by Fluent 2, WCAG 2.2 AA, and WAI-ARIA APG rather than a SaaS marketing site or mobile application. It is not a shared service, remote dashboard, or multi-user web app. Its HTTP boundary accepts only the expected localhost `Host`, including for read and event-stream requests.
_Avoid_: hosted app, LAN dashboard, multi-user app

**Dance Plan**:
A durable planned set of dance items the user intends to dance. A Dance Plan can remain active across local dates when unfinished items carry forward. It represents intention before playback, separate from the catalog of available dance tracks and the timeline of actual dance events.
_Avoid_: catalog, timeline, history

**Dance Plan Fulfillment**:
The relationship between a Dance Plan item and an accepted Playback Occurrence that satisfied it. Fulfillment makes `planned` available to Request Source Type Inference, but it does not create playback evidence or replace Requester Identity.
_Avoid_: playback evidence, requester identity, manual exclusion

**Superseded Dance Plan Item**:
A Dance Plan item whose planned intent has been taken over by a later same-target item, so it no longer carries forward or directly fulfills playback. It is different from a skipped item and should not silently recreate a fulfillment the user removed.
_Avoid_: skipped item, fulfilled item, deleted playback record

**Removed Dance Plan Item**:
A Dance Plan item the user removed from the active plan while the system keeps enough history to explain or undo the removal. A removed item no longer carries forward, supersedes another item, or fulfills playback.
_Avoid_: active planned item, skipped item, physical database deletion

**Local Dance Day Boundary**:
The user-configured time-of-day that separates one local dance day from the next for daily history, Dance Plan views, intended dates, and fulfillment matching. The default boundary is 00:00 in the operating system's local time zone, but the user may move it later, such as 01:00 or 03:00, so late-night dances still belong to the previous dance day. A missing spring-DST boundary advances to the first valid wall-clock minute; a repeated autumn-DST boundary starts on its first occurrence, and membership is compared as UTC instants so the day never moves backward during a fold.
_Avoid_: timezone, playback timestamp, plan identity

**Catalog**:
The inventory of available dance content and the real music those entries represent. Catalog owns dance tracks, music tracks, local preference flags, and provider matching review, but not dance plans or historical playback.
_Avoid_: dance plan, timeline, data operations

**Dance Track**:
One playable dance version identified by its dance system and system-local external id, such as a WannaDance, PyPyDance, or Dudu entry. That stable source identity exists conceptually even before a local Catalog row is materialized. The row may be created lazily as a minimal identity-only entry when first needed; later Catalog metadata enrichment does not change that identity.
_Avoid_: song, music track

**Dance Preference**:
A user preference attached to a dance track, such as favorite or want-to-learn. It describes preference for a playable dance version, not for the underlying music track.
_Avoid_: music preference, playlist item

**Recommendation Algorithm**:
The deferred, changeable scoring or selection strategy that may propose dance tracks to the user. Its output is not Request Source Type evidence; a future workflow would have to freeze an explicitly enabled or accepted result as a Recommendation List Snapshot.
_Avoid_: recommendation evidence, request source type, dance plan

**Recommendation List Snapshot**:
A possible future frozen list of recommended dance tracks explicitly enabled or accepted for a Local Dance Day. If implemented, it can support `recommend` only for same-day playback after freezing; the v2 Request Source Type Inference does not require snapshots to exist.
_Avoid_: algorithm result, preview, dance plan item, playback record

**Music Track**:
The real song independent of dance system and choreography. Music-provider links such as NetEase, QQ Music, Spotify, or popularity metrics belong to the music track level.
_Avoid_: dance track, dance-system entry

**Insights**:
Derived views that summarize and explain accepted Playback Occurrences, catalog, and dance-plan data, such as frequency, trends, source distribution, and neglected favorites. Insights consume the same handle-based current interpretation as Timeline; source evidence is traceable input rather than an independently counted playback.
_Avoid_: timeline, raw history, catalog

**Data Operations**:
Controlled workflows that change or rebuild local data in bulk, such as importing VRCX history, syncing dance-system catalogs, rebuilding generated data, and backup or restore. Cross-`dance-trail` database merge is only a possible future flow, not a v2 commitment. Data Operations is not a raw database editor.
_Avoid_: settings, raw SQLite editor, ad hoc table editing

**Data Operation Coordinator**:
The shared service seam that holds one App Data Lifetime Lease while dispatching a Data Operation. It serializes bulk workflows across Web UI, CLI, threads, and processes and conflicts with the Live Watcher over the same application root or resolved SQLite database. A caller cannot bypass it by navigating, refreshing, or opening another page.
_Avoid_: page-local running state, HTTP request lock, SQLite transaction

**App Data Lifetime Lease**:
The OS-backed exclusive ownership of one application root and resolved SQLite database for the complete lifetime of a watcher or coordinated bulk write. Persistent lock files identify the scope but do not themselves mean a writer is active.
_Avoid_: database transaction, process-local mutex, lock-file existence check

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
The Windows notification-area entry for running `dance-trail` as a local desktop app. It opens the Local Web UI, exposes immediate watcher and overlay controls, and owns quitting the background app session. One Desktop Tray Entry is allowed per interactive Windows session; a later launch repeatedly chooses among activating the verified existing Local Web UI, acquiring a released or abandoned desktop mutex and becoming the replacement owner, or reporting a visible bounded-time failure. Windows logoff and shutdown notifications give the coordinated Local Web UI, Live App Session Runtime, and desktop-instance cleanup one four-second absolute deadline. Every acquired resource receives a cleanup attempt before the end-session callback returns; a non-cooperative request or watcher is reported as a timeout rather than blocking Windows indefinitely.
_Avoid_: CLI command, Web UI navigation entry, background service

**Live App Session Runtime**:
The runtime module that owns immediate watcher and overlay lifecycle for the current local app session, including start, stop, status, recent errors, and recent watcher stats. Synchronous CLI and background entry points share one watcher owner, and all public watcher entry points enforce the same application/database lifetime exclusion. Lifecycle transitions are serialized and distinguish running, stopping, and stopped; a replacement cannot start until its predecessor has terminated. Closing is irreversible. Normal terminal shutdown rejects incomplete HTTP work, drains accepted writes, and waits for watcher settlement, database commit, and capture finalization. Windows end-session cleanup preserves that ordering within its absolute system-shutdown deadline; pathological non-cooperative work produces a grouped timeout after all remaining cleanup actions are attempted. CLI, Desktop Tray Entry, and Web UI controls use this runtime instead of reimplementing watcher and overlay transition rules.
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
A configurable path for data or output that `dance-trail` owns under the local application boundary by default, such as the app database, queued-self files, captures, run logs, source-log archives, or recording-frame outputs.
_Avoid_: external source path, VRChat log directory

**External Source Path**:
A configurable path to user- or tool-owned data that `dance-trail` reads from outside its own application boundary, such as VRChat logs, VRCX history, WannaDance cache files, or recordings.
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
The set of stable VRChat user ids confirmed to belong to the local user, used to distinguish the user's own playback requests from other requester identities. Any member identifies self across the retained playback history; display names are confirmation labels, not identity keys.
_Avoid_: display name, source path, VRCX database path

**Detected User Identity**:
A candidate stable VRChat user id found from local source metadata. It may be shown with a display-name label for confirmation and added to Self User Identity without replacing its existing members.
_Avoid_: saved configuration, display-name preference, source path

**Manual User Identity**:
A stable VRChat user id explicitly added to or removed from Self User Identity by the user when detection is unavailable, ambiguous, wrong, or stale.
_Avoid_: detected source path, display name, generated default

**Requester Identity**:
The VRChat identity observed for the user who requested or triggered a playback record. It may include the event-time display name and a stable VRChat user id, and it is separate from Self User Identity. Random playback evidence is not Requester Identity and must not be represented by setting requester fields to blank, NULL, or "random".
_Avoid_: self user identity, display-name preference, source classification, random source marker

**Draft Configuration**:
The unsaved Settings form state being edited by the user before it is written to the local app configuration file. Draft configuration can be validated and reset without changing the currently saved configuration.
_Avoid_: active configuration, autosaved settings

**Saved Configuration**:
The local app configuration currently persisted in `config/dance-trail.local.json` and used as the default for app workflows. Saved configuration is changed only by an explicit save action in the Web UI.
_Avoid_: draft configuration, generated defaults

**Valid Configuration Value**:
A draft field value that satisfies the requirement for its specific configuration key and is eligible to be saved. Invalid values may remain in the draft while the user is editing, but they cannot become saved configuration.
_Avoid_: syntactically valid text, best-effort setting

**Unsupported Configuration Key**:
A key found in the local app configuration file that is not part of the current supported Settings contract. Unsupported keys are preserved when saving from the Web UI, but the user is warned that `dance-trail` does not understand them.
_Avoid_: hidden supported setting, raw JSON field

**Live Status**:
The Home surface for current watcher state, current playback, current session activity, overlay availability, and realtime capture health. Its current playback comes from an in-memory watcher state that remains current even when OBS Overlay publication is disabled; Overlay enablement gates the viewer-facing projection, not Home's watcher context. Live Status is not a separate primary navigation area in the MVP.
_Avoid_: timeline, history, archive, primary navigation

**Timeline**:
The chronological review and correction surface whose v2 items each represent one handle-based Playback Occurrence and its current interpretation. Playback Evidence remains available as expandable provenance details, not parallel history items for the same occurrence.
_Avoid_: status buckets, live monitor, insights, data operations

**Playback Record**:
The legacy v1 product and storage term for a normalized `playback_records` row. V2 uses Playback Evidence for immutable source evidence and Playback Occurrence for the user-facing playback unit; Playback Record is not a v2 identity or read root.
_Avoid_: v2 playback identity, occurrence projection, playback evidence

**Playback Occurrence**:
The system's current rebuildable representation of one distinct playback occurrence, addressed by a stable Playback Handle and constructed from evidence, memberships, redirects, and current rules. It is the v2 playback unit exposed to ordinary business features, not a claim that the system stores an independently knowable real-world event. It is a logical product shape rather than a required stored row; its computation or cache never becomes the durable identity.
_Avoid_: evidence row, permanent fact copy, ephemeral row identity, merge group

**Playback Read Boundary**:
The v2 domain boundary through which ordinary upper-layer features read Handle-addressed playback and current interpretation. It owns Handle redirect resolution and evidence-identity isolation while allowing internal queries, views, or caches to vary without changing the business contract.
_Avoid_: occurrence table, shared SQL query, evidence repository, UI-specific resolver

**Playback Handle**:
The stable database-local identifier through which v2 business data references a Playback Occurrence. A Playback Handle contains no playback facts or current interpretation; reads resolve any active Playback Handle Redirect to a Canonical Handle before exposing the current occurrence. Its physical key type is a schema choice rather than a separate domain term.
_Avoid_: global identity, portable database id, playback evidence, occurrence row, permanent fact copy

**Canonical Handle**:
The current representative Playback Handle reached after resolving all active Playback Handle Redirects from an input Handle. `resolved_handle` may name the result of that resolution in code, while `root` is only an internal graph term. Canonical is a current role rather than a permanent flag: the Handle can itself become the source of a later redirect.
_Avoid_: permanent canonical flag, terminal Handle, end Handle, copied occurrence identity

**Playback Evidence Membership**:
The relationship through which one Playback Evidence item has membership in one Playback Handle. Through that relationship, the evidence supports the Playback Occurrence addressed by the Handle. The evidence is the member and the Handle is the membership target; this relationship is not a Handle merge or redirect.
_Avoid_: Handle membership, evidence copy, Handle redirect, occurrence cache

**Playback Identity Operation**:
An instantaneous durable audit record grouping membership and Handle-redirect changes made by one atomic playback-identity action. It owns one occurrence time; relationship validity begins or ends according to whether the relationship references it as its establishing or closing operation.
_Avoid_: relationship-table audit row, generic application operation, reconciliation run

**Playback Evidence**:
An immutable, source-scoped evidence item created when an Evidence Source adapter deterministically organizes the facts it observed. Whenever possible, one adapter should consolidate the bounded raw observations for one playback into one self-contained item, so that one item from that source is sufficient to support a Playback Occurrence; downstream code should not have to assemble fragmented evidence to understand the source's claim. This is an organization principle rather than a uniqueness constraint. Playback Evidence has a stable local identity shared across source kinds and distinct from source-side row ids and log coordinates. It is direct input to Playback Reconciliation and may retain provenance to multiple raw lines or source rows, but it is not a Playback Handle, Playback Occurrence, or current interpretation.
_Avoid_: raw log line, fragmented source fact, playback occurrence, mutable projection

**Source Evidence Location**:
A stable source-scoped coordinate used to recognize the same source record before comparing its content fingerprint. Repeated VRCX imports must resolve the same source row to the same location, and watcher live capture and watcher replay must resolve the same underlying VRChat log event to the same location. Import-run ids, live/replay mode, and watcher session ids are not part of this identity. Exact-ingestion deduplication compares locations and content only among Playback Evidence items that still have an effective Playback Evidence Membership and therefore still support a Playback Handle; an evidence row has no separate active flag.
_Avoid_: evidence id, content fingerprint, import run, watcher session, playback handle

**Playback Evidence Deduplication**:
The same-source check that decides whether incoming source data has already produced the same Playback Evidence. It prevents duplicate ingestion; it does not decide which Playback Evidence items support the same Playback Occurrence.
_Avoid_: Playback Reconciliation, occurrence merge, cross-source matching

**Playback Reconciliation**:
The process that determines which Playback Evidence items from different Evidence Sources support the same Playback Occurrence and which remain independent. Its result is expressed through Playback Evidence Memberships and, when reconciling existing identities, Playback Handle Redirects.
_Avoid_: Playback Evidence Deduplication, source import, evidence parsing, occurrence projection

**Playback Occurrence Merge**:
The semantic effect in which Playback Handles that previously exposed separate Playback Occurrences now resolve to one current Playback Occurrence. It is produced through Playback Handle Redirects rather than by physically merging or rewriting stored occurrence rows.
_Avoid_: evidence merge, row rewrite, Handle deletion, field conflict

**Playback Handle Redirect**:
The durable directed relationship through which one source Playback Handle redirects to one target Playback Handle. Resolving the relationship produces Playback Occurrence Merge semantics while preserving the source Handle and its existing Playback Evidence Memberships.
_Avoid_: Playback Evidence Membership, Handle replacement, occurrence row merge, mutable cache pointer

**Possible Match**:
A relationship reported by Playback Reconciliation between independent Playback Occurrences that appear related but do not satisfy the strict merge rule. It does not prescribe how the algorithm found or evaluated them, change identity or normal consumption, or require user review; new evidence or explicit historical reprocessing may evaluate it again.
_Avoid_: merged playback, review task, negative relationship, hidden deduplication

**Do Not Merge Decision**:
A durable user-authored negative relationship for a specific candidate pair or group that the user has explicitly chosen to keep separate. It is never generated for ordinary unmatched occurrences; normal reconciliation must respect it until an explicit user action or repair revokes it.
_Avoid_: unmatched occurrence, automatic negative relation, possible match, source priority

**Merge Decision**:
An exceptional user decision requested when identity evidence supports merging Playback Occurrences but incompatible user-authored states prevent a lossless automatic merge. It belongs to an explicit merge or historical-repair workflow rather than a general review queue; the user may complete the merge or create a Do Not Merge Decision, and until then both occurrences and their states remain unchanged.
_Avoid_: possible match, routine confirmation, evidence conflict, automatic source priority

**VRChat Log Watcher**:
The source adapter that observes newly appended VRChat log lines, performs deterministic parsing plus bounded same-source organization and enrichment, and publishes one self-contained immutable Playback Evidence item for each organized watcher playback. Mutable pending capture exists only before publication; after the evidence row is written, the watcher cannot backfill or overwrite it. The watcher does not own the canonical Playback Occurrence, Request Source Type Inference, acceptance policy, cross-source reconciliation, or historical repair. Runtime-only folding for Live Status or the OBS Overlay is ephemeral operational state, not a durable product event model.
_Avoid_: event aggregator, request-source classifier, history projector, repair worker

**Watcher-Derived Playback Record**:
A legacy v1 Playback Record projected from evidence captured by the VRChat Log Watcher. V2 instead publishes one self-contained Playback Evidence item after bounded watcher-side organization and enrichment, then lets the Handle-based downstream boundary expose the Playback Occurrence. Neither shape makes the watcher the owner of canonical occurrence identity, Request Source Type Inference, or accepted-history policy.
_Avoid_: live playback record, overlay state, accepted playback record, actual-play-only record

**Manual Log Entry**:
A user-authored source-evidence claim that a playback occurred, with supplied facts such as dance track and played time. It may independently support default inclusion under the Trust-By-Default Playback Policy, but it does not override differing external-source facts and is not a Manual Record Update, Manual Playback Decision, Dance Plan item, or direct Request Source Type edit.
_Avoid_: manual correction, request source override, plan item, manual playback decision

**Watcher Settlement**:
The legacy v1 name for the downstream evidence-policy action that resolves a pending Watcher-Derived Playback Record after enough lifecycle or playback evidence is available. V2 watcher capture instead completes or times out its bounded source-side organization before publishing one immutable Playback Evidence item; downstream acceptance policy remains separate.
_Avoid_: watcher capture, raw event parsing, manual decision, playback record creation

**Playback Observation**:
The locally observed playback lifecycle state for a playback record, such as an active observation, completed observation, interruption, watcher stop, video shutdown, or observed end boundary. Playback Observation can inform the Default Acceptance Result, but it is not the request source, not the evidence identity, and not a manual decision.
_Avoid_: request source, acceptance result, raw watcher payload, manual decision

**Request Source Type**:
The canonical, rebuildable request/playback-source classification of a Playback Occurrence: planned, recommend, self, other, random, or unknown. It is not evidence strength, confidence, or acceptance state; self, other, and random are mutually exclusive siblings, while coarse watcher labels and legacy `queued_self` are not canonical values.
_Avoid_: requester identity, evidence source priority, confidence score, acceptance status, review status, raw watcher label

**Request Source Type Inference**:
The independent, repeatable v2 process that derives a Playback Occurrence's Request Source Type from Handle-resolved Playback Evidence, Requester Identity, Self User Identity, Dance Plan Fulfillment, and any available Recommendation List Snapshot. It runs without recommendation snapshots and is not owned by a watcher, importer, writer, recommendation algorithm, or ordinary read path.
_Avoid_: watcher enrichment, VRCX import, recommendation algorithm, acceptance settlement

**Accepted Playback Occurrence**:
A Playback Occurrence included in normal history and Insights under the Trust-By-Default Playback Policy or an active Manual Acceptance. Manual confirmation is not required for ordinary inclusion.
_Avoid_: accepted playback record, manually confirmed only, promotion-only record, raw parser row

**Pending Playback Record**:
A legacy v1 playback row whose watcher observation has not settled. In v2, pending watcher capture is mutable pre-publication operational state, not Playback Evidence or a Playback Occurrence; Live Status and OBS may consume it, while Timeline and Insights consume only published evidence through the Handle boundary.
_Avoid_: v2 evidence, v2 occurrence, needs attention, excluded, accepted, durable live state

**Default Acceptance Result**:
A system-derived result inferred from published playback evidence before any active manual decision is applied. In v2 the result is accepted or attention-needed. Pending watcher capture exists before evidence publication and is not a Default Acceptance Result. Attention-needed is non-counting and does not by itself require user action; excluded is only a Manual Playback Decision and is never a default result. Restoring the default result means removing the manual accepted/excluded overlay and letting the evidence rules decide again.
_Avoid_: stored truth, permanent user state, raw parser status, history-counting flag

**Manual Playback Decision**:
A reversible user-authored overlay on a Playback Handle that explicitly makes the current Playback Occurrence accepted or excluded. It is strongest while active, but it does not erase Playback Evidence, change evidence membership or redirects, or permanently replace the Default Acceptance Result. Restoring the default closes the active overlay and lets evidence-derived rules govern again; it is not a third persistent inclusion state. Pending is not a Manual Playback Decision because active observation state is inferred from evidence rather than chosen by the user.
_Avoid_: deletion, source rewrite, irreversible confirmation, pending playback

**Manual Acceptance**:
A reversible Manual Playback Decision that a Playback Occurrence should participate in normal history and Insights even when its current default result would not include it. It records user intent on the Playback Handle; it is not required for evidence that already counts under Trust-By-Default Playback Policy, and it does not rewrite evidence.
_Avoid_: source evidence, mandatory confirmation, permanent promotion, default acceptance

**Manual Exclusion**:
A reversible Manual Playback Decision that a Playback Occurrence should not participate in normal history or Insights. It is the single playback-removal intent: views may filter it without creating a separate hidden state, and restoring the default removes the decision while preserving evidence and reviewability.
_Avoid_: deletion, hidden state, parser interruption, automatic conflict

**Review Attention**:
A user-facing cue for a concrete, actionable problem that the product has intentionally chosen to expose. Internal evidence differences are resolved by Playback Reconciliation, and Possible Match does not create Review Attention; normal operation must not depend on the user clearing an attention queue.
_Avoid_: evidence disagreement, possible match, required confirmation, acceptance status, parser status, pending playback

**Trust-By-Default Playback Policy**:
The product rule that supported playback evidence is accepted unless stronger evidence or explicit user judgment excludes it. This policy keeps day-to-day use lightweight: the user handles exceptions instead of confirming every dance.
_Avoid_: manual-only history, review-everything workflow, raw import

**Evidence Source**:
The stable source kind and capability family under which Playback Evidence is produced, such as VRCX history or VRChat log observation. A particular database, file, stream, or producer can naturally be described as a concrete instance of that Evidence Source; its instance-specific identity and coordinates belong to provenance and do not create a different source kind. Evidence Source remains distinct from Request Source Type, import runs, parser versions, and raw record locations; Manual Log Entry is a deferred future source kind.
_Avoid_: request source type, import batch, parser version, raw record location

**Evidence Source Priority**:
The decision-specific precedence used by internal field resolvers when evidence claims differ, evaluated per fact from source capability, provenance lineage, directness, and active user judgment; it is not a global source ordering, and source counts are not votes. Active Manual Playback Decisions govern current inclusion intent, while Manual Log Entries remain source claims; watcher evidence may be preferred to VRCX for overlapping ordinary observed facts without gaining universal authority or controlling Playback Occurrence identity. Deferred Manual Record Updates do not participate in the first v2 resolver.
_Avoid_: global source ranking, majority vote, request source type, filesystem order, newest-row-wins, stored source fact

**Automatic Acceptance**:
A system-derived acceptance decision for a Playback Occurrence, based on supported source semantics or conservative evidence rules. Automatic Acceptance is not limited to an elapsed-time threshold; future rules may use additional conservative signals. It lets normal occurrences count without manual confirmation, but it is weaker than an active Manual Playback Decision.
_Avoid_: manual confirmation, parser completion, promotion

**Ordinary Playback Evidence**:
A supported Playback Evidence item that does not carry a stronger acceptance signal, such as ordinary watcher or VRCX evidence. It can support trust-by-default inclusion but remains evidence rather than a user decision or Playback Occurrence identity.
_Avoid_: playback occurrence, untrusted record, ignored record, needs manual confirmation

**Acceptance Conflict**:
A legacy v1 merge term for overlapping records with incompatible inclusion state. V2 does not expose field-level evidence conflict; when separately used Playback Handles contain incompatible durable user state and identity evidence later supports merging them, the current term is Merge Decision.
_Avoid_: v2 merge state, parser conflict, source-order fill, duplicate row

**User-Editable Playback Field**:
A playback field whose current interpretation could in principle receive a durable user judgment or correction. In the first v2 shape, only acceptance and exclusion are user-editable, through Manual Playback Decisions. Dance-track mapping, requester identity, and note corrections require the deferred Manual Record Update capability. Request Source Type is inferred from stable inputs rather than directly edited by the user.
_Avoid_: parser evidence, raw log metadata, automatic inference

**Source Evidence Field**:
A Playback Evidence field that preserves what the source adapter observed or how it organized that observation, such as source file, line range, raw payload, parser names, and original timing signals. Evidence fields are preserved for audit and are not overwritten by user decisions or any future correction overlay.
_Avoid_: user correction, review status, accepted-history inclusion

**Source Playback Evidence**:
The legacy v1 term for playback evidence inside another `dance-trail` database or app root before a Playback Evidence Merge. Cross-database merge is only a possible future v2 extension; any future design must use v2 Playback Evidence and Handle semantics rather than treating this term as a current contract.
_Avoid_: target history, local evidence, copied truth

**Local Playback Evidence**:
The legacy v1 term for normalized playback evidence owned by the current app root. V2 does not migrate or read it as a compatibility input; any efficient direct evidence query uses v2 Playback Evidence behind the Handle-based business boundary.
_Avoid_: v2 read root, playback occurrence, source row copy, external database state

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
A historical v1 Data Operations design for importing playback records from another `dance-trail` database or app root. V2 does not promise or implement this workflow; it retains only the possibility of a future semantic import that remaps database-local identities and preserves v2 evidence, relationship, and user-state boundaries.
_Avoid_: current v2 requirement, raw SQLite merge, settings import, timeline edit

**Merge Source Order**:
A historical v1 Playback Evidence Merge term for the order in which source databases were to be applied. V2 has no current cross-database merge workflow or source-order contract.
_Avoid_: current v2 policy, filesystem order, modification-time order, implicit priority

**Merge Plan**:
A historical v1 preview artifact for the proposed Playback Evidence Merge workflow. V2 does not currently define or require a cross-database Merge Plan; a future feature would need a new contract based on the then-current v2 model.
_Avoid_: current v2 artifact, rough estimate, execution log, raw diff

**Merge Execution**:
The historical v1 Data Operations action that would apply an approved Merge Plan. It is not a current v2 operation.
_Avoid_: current v2 operation, export-only preview, database replacement, source mutation

**Merge Target Backup**:
The historical v1 restore point proposed for Merge Execution. Ordinary v2 backup and restore remain valid Data Operations, but no cross-database merge-specific backup contract is currently defined.
_Avoid_: current merge requirement, optional export, source backup, partial database copy

**Merge Source Fingerprint**:
The historical v1 audit identity proposed for a source database in Playback Evidence Merge. A future v2 semantic import may define its own source database or snapshot identity, but this fingerprint shape is not reserved now.
_Avoid_: current v2 identity, source backup, display name, temporary picker value

**Review Status**:
The legacy umbrella term for playback review state. In v2, system-derived `needs_attention` belongs to the Default Acceptance Result and is non-counting without requiring user action; the only manual inclusion states are `accepted` and `excluded`, with restore-default represented by closing the active Manual Playback Decision.
_Avoid_: manual needs-attention decision, deletion, raw parser status, completion status

**Manual Record Update**:
A deferred future capability for a user-authored correction to the interpreted fields of an existing Playback Handle, such as dance-track mapping, requester identity, or note, while preserving raw evidence. It is not part of the first v2 schema, resolver inputs, API, or merge behavior. Acceptance and exclusion remain Manual Playback Decisions; a Manual Log Entry remains a separate source-evidence claim.
_Avoid_: current v2 input, parser backfill, automatic merge, raw evidence edit, manual log entry

**Manual Merge Conflict**:
A possible future merge case in which both sides contain incompatible Manual Record Updates. Because Manual Record Update is deferred, this is not a first-v2 Merge Decision cause; current merge decisions concern incompatible user state that v2 actually implements.
_Avoid_: current v2 merge state, automatic overwrite, parser conflict, duplicate row

**Raw VRChat Log**:
Low-level diagnostic evidence captured from VRChat output logs. Raw VRChat logs are not normal user-facing timeline content and should only appear in explicit debugging or forensic details.
_Avoid_: timeline record, playback history
