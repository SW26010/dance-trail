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
A viewer-facing display surface for live playback status in OBS. It is one feature exposed by the Web UI, not the main interaction surface.
_Avoid_: Web UI, control panel

**Local Web UI**:
The Web UI product boundary for one user operating `dancing-log` on their own machine. It is not a shared service, remote dashboard, or multi-user web app.
_Avoid_: hosted app, LAN dashboard, multi-user app

**Dance List**:
A planned or suggested set of dance items, such as a queued-self list, recommendation list, practice list, or stream list. It represents intention before playback, separate from the catalog of available dance tracks and the timeline of actual dance events.
_Avoid_: catalog, timeline, history

**Catalog**:
The inventory of available dance content and the real music those entries represent. Catalog owns dance tracks, music tracks, local preference flags, and provider matching review, but not planned lists or historical playback.
_Avoid_: dance list, timeline, data operations

**Dance Track**:
One playable dance version inside a dance system, such as a WannaDance, PyPyDance, or Dudu entry. It may represent a specific choreography, dancer, difficulty, player count, or system-local id.
_Avoid_: song, music track

**Dance Preference**:
A user preference attached to a dance track, such as favorite or want-to-learn. It describes preference for a playable dance version, not for the underlying music track.
_Avoid_: music preference, playlist item

**Music Track**:
The real song independent of dance system and choreography. Music-provider links such as NetEase, QQ Music, Spotify, or popularity metrics belong to the music track level.
_Avoid_: dance track, dance-system entry

**Insights**:
Derived views that summarize and explain confirmed playback, catalog, and list data, such as frequency, trends, source distribution, and neglected favorites. Insights are analysis surfaces, not the source of historical truth, and unchecked or discarded playback records do not contribute to normal insight calculations.
_Avoid_: timeline, raw history, catalog

**Data Operations**:
Controlled workflows that change or rebuild local data in bulk, such as importing VRCX history, syncing dance-system catalogs, rebuilding generated data, backup and restore, and future database merge flows. It is not a raw database editor.
_Avoid_: settings, raw SQLite editor, ad hoc table editing

**Settings**:
The local environment and default preference surface for paths, database location, VRChat and VRCX sources, overlay defaults, and watcher defaults. Settings do not own catalog labels, dance lists, playback history, or analytics.
_Avoid_: data operations, catalog management, list management

**Watcher Default**:
A saved preference that affects how the VRChat log watcher should run when an app workflow starts it, such as whether watcher auto-start is desired. It is not an immediate start or stop command.
_Avoid_: live watcher control, process manager

**Overlay Default**:
A saved preference that affects whether the local OBS overlay server should run when the watcher is started by an app workflow. Enabling overlay auto-start implies watcher auto-start, because the overlay depends on live watcher state.
_Avoid_: OBS overlay page, live overlay control

**Desktop Tray Entry**:
The Windows notification-area entry for running `dancing-log` as a local desktop app. It opens the Local Web UI, exposes immediate watcher and overlay controls, and owns quitting the background app session.
_Avoid_: CLI command, Web UI navigation entry, background service

**Live Watcher Control**:
An immediate start or stop command for the current VRChat log watcher process. It changes the running app session and is separate from Watcher Default.
_Avoid_: watcher default, saved configuration, startup preference

**Live Overlay Control**:
An immediate start or stop command for the current OBS Overlay server. It depends on Live Watcher Control: turning overlay on keeps watcher on, and turning watcher off also turns overlay off.
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
The Home surface for current watcher state, current playback, current session activity, overlay availability, and realtime capture health. Live Status is not a separate primary navigation area in the MVP.
_Avoid_: timeline, history, archive, primary navigation

**Timeline**:
The chronological review and correction surface for playback records. Timeline defaults to the full current-day sequence, preserves time order across records, and uses color, icons, and labels to show each record's review status and relevant observation details.
_Avoid_: status buckets, live monitor, insights, data operations

**Playback Record**:
The Web UI timeline item representing one parsed playback-related record, whether it comes from official history, live observation, interrupted observation, or another parsed source. It is not the same as a raw VRChat log line.
_Avoid_: raw log line, database row

**Review Status**:
The user's durable judgment about a playback record: unchecked, user confirmed, or user discarded. User-confirmed records are official history; editing a record's source is a user-confirming action. Review status preserves evidence while controlling whether a record still needs attention.
_Avoid_: deletion, raw parser status, completion status

**Raw VRChat Log**:
Low-level diagnostic evidence captured from VRChat output logs. Raw VRChat logs are not normal user-facing timeline content and should only appear in explicit debugging or forensic details.
_Avoid_: timeline record, playback history
