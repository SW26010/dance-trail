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
- we can still export catalog or history snapshots for inspection and sharing

Implemented direction:

- primary app database: `data/dancing_log.sqlite3`
- optional export commands:
  - WannaDance catalog -> optional CSV/JSON artifacts through `sync-wanna --write-files`
  - dance history -> future CSV export if needed
  - recommendation snapshots -> future CSV export if needed

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

## Current Implementation Status

The importer described above is now implemented in `dancing_log/vrcx_importer.py`
and exposed through:

```bash
uv run python main.py import-vrcx
uv run python main.py import-vrcx "path/to/vrcx-snapshot/VRCX.sqlite3"
uv run python main.py import-vrcx --dry-run
```

The VRCX database path can also be stored in `data/local_config.json` as
`vrcx_db_path`.

The importer currently:

- reads `gamelog_video_play`
- parses supported WannaDance and observed PyPyDance playback URLs
- writes provenance rows to `vrcx_import_events`
- writes normalized timeline rows to `dance_events`
- creates placeholder `dance_tracks` rows when a parsed id is not already in the
  catalog
- infers `self`, `other`, `random`, or `unknown` from requester fields
- skips unsupported dance systems instead of misclassifying them as WannaDance
- keeps stronger source inference when the same event is imported again

Supported WannaDance URL families include documented API hosts, observed
WannaDance-compatible API hosts, upstream Kiva hosts, and supported CDN file URL
patterns. Observed PyPyDance API URLs are also parsed into `pypydance:<id>`.

Dudu, VRDancing, and other systems are recognized only as unsupported or unknown
until their real metadata shapes are inspected.

Live raw-log capture is implemented separately in `dancing_log/vrc_log_watcher.py`
and exposed through:

```bash
uv run python main.py watch-vrc-log
```

This command is intentionally forensic-only for the first iterations. It tails
VRChat `output_log_*.txt` files, mirrors raw lines when enabled, writes
video-related candidates to `candidates.jsonl`, writes parsed playback-like
signals to `parsed_events.jsonl`, writes folded per-song rows to
`playback_events.jsonl`, and stores the session under `analysis/vrc_log_capture/`.
It does not write `dance_events`.

The watcher defaults to `data/local_config.json` key `vrc_log_dir`, falling back
to the standard Windows LocalLow VRChat log directory. It starts from the current
log file's end by default to avoid rescanning old large logs during gameplay;
newly created log files are read from the beginning so startup lines are not
missed.

The folded playback rows keep delay-oriented fields such as `first_seen_at`,
`resolved_at`, `video_loaded_at`, `actual_play_at`,
`delay_to_actual_seconds`, and `load_to_actual_seconds`. They also keep source
fields such as `source_type` and `source_display_name`.

Observed captures show two useful actual-play paths:

- WannaDance/USharpVideo exposes `DelayedVideoReady` and `OnVideoStart`, with a
  stable roughly 10 second request-to-play delay in normal starts.
- PyPyDance can emit a second VRCX `VideoPlay` signal with a positive playback
  offset; the watcher uses `timestamp - offset` as an approximate
  `actual_play_at` with `actual_play_method = vrcx_progress_offset`.

Mid-play observations are excluded from delay metrics. Large PyPyDance offsets
set `observed_mid_play` and `elapsed_at_first_seen_seconds`; WannaDance
`Playing synced` lines set `synced_play_at`.

## Live Watcher Performance and Direction

The current `watch-vrc-log` implementation is lightweight enough for live use.
It polls every 0.25 seconds, drains new lines with `readline()`, filters most
lines with cheap token checks, and only runs the heavier parsers on candidate
video lines.

The fifth real capture, `analysis/vrc_log_capture/2026-05-17_171055`, covered
about 7.6 minutes and observed:

- 5546 raw log lines, about 12 lines per second
- 165 candidate lines
- 57 parsed signals
- 9 folded playback events
- VRCX comparison window: 9 VRCX rows, 9 watcher rows, 0 missed, 0 extra
- candidate read latency: min 0.125 seconds, average 0.571 seconds, max 1.23
  seconds, approximate p95 1.026 seconds

Compared with VRCX, the approach is similar but narrower. VRCX's C#
`LogWatcher.cs` also avoids `FileSystemWatcher`, polls the VRChat log directory
on a background thread, tracks file positions, opens files with
`FileShare.ReadWrite`, and passes normalized raw events into the frontend. The
frontend then routes events through `gameLogCoordinator.js`, world-specific
media parsers, and SQLite writes such as `gamelog_video_play`.

The advantage of `watch-vrc-log` is not historical coverage. VRCX SQLite remains
the best historical source. The advantage is owning a low-latency live layer
that can keep richer playback timing fields than VRCX's video table:
`actual_play_at`, `actual_play_method`, `observed_mid_play`,
`elapsed_at_first_seen_seconds`, source fields, resolve/load timing, and raw
line provenance.

## Live Database and OBS Overlay Plan

The next implementation step should keep the forensic JSONL capture, but add a
live update pipeline.

1. Refactor `PlaybackEventBuilder` to emit an update callback every time a
   folded playback event changes.
2. Add a live SQLite table, tentatively `live_playback_events`, keyed by
   `event_key`. It should be upserted as request, resolve, load, progress,
   sync, and actual-play signals arrive.
3. Promote stable live rows into `dance_events` only when the record is safe
   enough. Good initial promotion triggers are:
   - `actual_play_at` exists and `observed_mid_play` is false
   - or a row has been idle long enough to be considered complete
4. Keep `playback_events.jsonl` as a session artifact. It remains useful for
   debugging and for replaying real captures into tests.
5. Add a local-only overlay server, for example:

```bash
uv run python main.py watch-vrc-log --live-db --overlay-port 8765
```

The server should bind to `127.0.0.1` and expose an OBS Browser Source page at:

```text
http://127.0.0.1:8765/overlay
```

The overlay should use server-sent events or WebSocket updates from the same
live state. The first version should show:

- current clock time
- current track title
- dance system and external id
- requester/source, including `random` and player display names
- elapsed / total time when duration is known
- progress bar
- optional small debug line for delay method, sync/mid-play, and source file

The page should be self-contained and local: no external fonts, images, CDNs, or
network calls. OBS should be able to keep it open for a whole recording session
without depending on internet access.

## Recommended Next Steps

1. Implement live playback upserts and a promotion path from
   `live_playback_events` to `dance_events`.
2. Implement the local OBS overlay page on top of the live state.
3. Keep collecting inspection fixtures for real PyPyDance, Dudu, VRDancing, and
   other dance-system VRCX rows.
4. Design one extension table per additional dance system only after the input
   shape is known.
5. Add a correction/backfill command for existing `unknown` source rows.

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
