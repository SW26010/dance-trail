# VRCX Integration Notes

> Privacy note: Personal paths and activity examples are anonymized. Replace example paths with your own; sample timestamps are illustrative. Aggregate results and technical conclusions are retained.

Date: 2026-05-16

## Goal

Evaluate whether local VRCX data can be used as a reliable source of dance song play history, and record the implications for `dancing-log` as an eventually open-source project.

## Open-source Boundary

For this project, code and personal data should stay fully separated.

Recommended layout:

- `dancing_log/`: source code only
- `docs/`: design notes and public documentation
- `data/`: local derived datasets, ignored by git
- `analysis/`: local scratch copies, ignored by git
- `.env` or future config file: local paths and user-specific settings, ignored by git

The repository should never contain:

- raw VRCX database copies
- personal VRChat identifiers
- local logs
- generated song history snapshots

## Recommended Song Source Model

The current source model is too coarse for the next phase.

Recommended enum values:

- `queued_self`: pre-queued by self, stronger intent than ad-hoc self-pick
- `self`: actively picked by self on the spot
- `recommend`: selected from this tool's daily recommendation list
- `other`: requested by someone else
- `random`: chosen by world/system randomness

Notes:

- `queued_self` and `self` should remain separate in analytics.
- `recommend` is not the same thing as `self`, even if the user ultimately confirms the play.
- `random` should be treated as a first-class source, not folded into unknown or other.

## Storage Recommendation

Recommendation: use SQLite as the primary local store, and keep CSV as an export format only.

Why SQLite is the better fit now:

- we already need to integrate with another SQLite source (`VRCX.sqlite3`)
- history is event-shaped, not just table-shaped
- source inference will likely require joins, filtering, deduplication, and backfills
- future analytics will be easier with SQL than with ad-hoc CSV mutation
- we can still export `songs.csv` or `dance_log.csv` for inspection and sharing

Suggested direction:

- primary app database: `data/dancing_log.sqlite3`
- optional export commands:
  - songs -> CSV
  - dance history -> CSV
  - recommendation snapshots -> CSV if needed

## Local VRCX Findings

Analyzed from a copied local snapshot of `path/to/vrcx-snapshot`.

Important files found:

- `VRCX.sqlite3`
- `VRCX-WorldData.db`

Key table found in `VRCX.sqlite3`:

- `gamelog_video_play`

Schema:

- `created_at`
- `video_url`
- `video_name`
- `video_id`
- `location`
- `display_name`
- `user_id`

Other relevant tables:

- `gamelog_location`
- `gamelog_join_leave`
- `gamelog_event`
- `gamelog_resource_load`

Observed local counts from the copied database:

- `gamelog_video_play`: 8067 rows
- rows with `api.udon.dance`: 6745
- rows with non-empty `display_name`: 6621
- rows with non-empty `user_id`: 6201
- `api.udon.dance` rows with blank `display_name`: 1052

This is strong evidence that VRCX already stores a usable local playback history for dance-world song events.

## What VRCX Source Code Confirms

Repository inspected:

- `vrcx-team/VRCX`

Relevant files:

- `src/services/database/gameLog.js`
- `src/coordinators/gameLogCoordinator.js`
- `src/stores/gameLog/mediaParsers.js`
- `src/services/gameLog.js`
- `Dotnet/LogWatcher.cs`
- `Dotnet/AppApi/Cef/Folders.cs`

What the source code confirms:

- VRCX persists video play events into `gamelog_video_play`
- VRCX exposes those events in its own game log and sessions views
- special parsers exist for dance/media worlds such as:
  - `PyPyDance`
  - `VRDancing`
  - `ZuwaZuwaDance`
  - `LSMedia`
  - `PopcornPalace`
- parsed events are normalized into a common `VideoPlay` shape with:
  - timestamp
  - video URL
  - display name
  - inferred user id
  - location

## Real Playback Event Source

The true upstream source is not `VRCX.sqlite3`.

VRCX watches VRChat's own Unity output logs:

- Windows path: `%LOCALAPPDATA%Low\VRChat\VRChat`
- File pattern: `output_log_*.txt`

In VRCX, `Dotnet/LogWatcher.cs` initializes its log directory through:

- `Program.AppApiInstance.GetVRChatAppDataLocation()`

For the CEF desktop build, `Dotnet/AppApi/Cef/Folders.cs` resolves that to:

- `Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData) + @"Low\VRChat\VRChat"`

Then `LogWatcher` scans `output_log_*.txt`, parses relevant lines, and emits normalized event arrays:

- `[fileName, timestamp, "video-play", videoUrl]`
- `[fileName, timestamp, "video-play", videoUrl, displayName]`
- `[fileName, timestamp, "vrcx", rawWorldData]`
- `[fileName, timestamp, "video-sync", timestamp]`

VRCX recognizes several raw VRChat log formats as playback events:

- `[Video Playback] Attempting to resolve URL '...'`
- `[Video Playback] Resolving URL '...'`
- `User <displayName> added URL <url>`
- `[USharpVideo] Started video load for URL: <url>, requested by <displayName>`
- `[VRCX] VideoPlay(PyPyDance) "...",...`
- `[VRCX] VideoPlay(VRDancing) "...",...`
- `[VRCX] VideoPlay(ZuwaZuwaDance) "...",...`
- `[VRCX] LSMedia ...`
- `[VRCX] VideoPlay(PopcornPalace) {...}`

The JS side then calls `LogWatcher.Get()` from `src/services/gameLog.js`, parses the event in `gameLogCoordinator.js`, applies world-specific media parsers from `mediaParsers.js`, and finally writes normalized rows into `gamelog_video_play`.

So the data hierarchy is:

1. VRChat `output_log_*.txt` is the real event source.
2. VRCX `LogWatcher` is the parser/tailer.
3. VRCX `gamelog_video_play` is the derived durable cache.
4. `dancing-log` should import from VRCX SQLite first, and optionally support direct VRChat log parsing later.

Local verification note:

- the copied VRCX database contains historical parsed video events through `2026-02-06`
- the current account's local VRChat log directory only showed `2026-03-29` logs during this check
- those current logs did not contain dance playback lines matching the VRCX parser patterns
- this means VRCX SQLite is currently the better local source for historical imports, while raw log tailing is the better source for live capture

One especially useful detail:

- in the parser for some dance-world events, `displayName === "Random"` is explicitly normalized away

Implication:

- the VRCX DB is a strong source for "what played"
- but it may not always preserve the original source semantics cleanly enough to distinguish:
  - random
  - self-picked
  - pre-queued self-picked
  - other-picked

## Practical Feasibility Assessment

### What is already feasible

We can reliably mine from VRCX:

- play timestamp
- world / instance context
- song URL or world API URL
- often the triggering display name
- often the triggering user id
- often a readable song title

For `api.udon.dance` specifically, the URL includes a song id:

- example: `http://api.udon.dance/Api/Songs/play?node=nya&id=4413`

That means we can likely:

1. parse the song id from VRCX playback history
2. map it to the Wanna song id / metadata set
3. infer whether the player was self or someone else by comparing `user_id`

### What is not yet proven

These distinctions are still not guaranteed from the current evidence:

- `queued_self` vs `self`
- `other` vs `random` when `display_name` / `user_id` is blank

The blank `display_name` rows may represent:

- random picks
- parser limitations
- worlds that omit requester identity
- playback events restored from state rather than explicit requests

So the remaining hard problem is not "can we get play history?"
The remaining hard problem is "can we infer source semantics with enough confidence?"

## Recommended Next Steps

1. Add a standalone importer that reads a copied VRCX SQLite file and extracts candidate dance events into a normalized staging table.
2. Store local app data in SQLite, not CSV-first.
3. Introduce the expanded source enum now, even if some imported rows initially land as `unknown`.
4. Build source inference rules in layers:
   - exact self-match by `user_id`
   - exact other-match by non-self `user_id`
   - explicit random markers if present
   - fallback `unknown`
5. Only later decide whether `queued_self` can be inferred from world-specific semantics or needs manual confirmation.

Deferred follow-up:

- after blank-requester rows are promoted to `random`, the remaining `unknown` rows are mostly "has `display_name`, missing `user_id`"
- current volume is small enough to defer
- a plausible next pass is:
  - use VRCX player-history style tables keyed by local account
  - search for rows near the playback timestamp with the same `display_name`
  - recover the stable VRChat `user_id` when the match is unambiguous
  - then backfill `self` or `other`

## Conservative Conclusion

The VRCX path is viable and worth prioritizing.

It is already strong enough to support:

- automated ingestion of many song play records
- self vs non-self inference for a large subset of rows
- song id extraction from `api.udon.dance`

It is not yet strong enough to guarantee all future source categories without additional world-specific rules or a manual correction flow.
