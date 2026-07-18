# dancing-log

> Privacy note: Personal paths and activity examples are anonymized. Replace example paths with your own; sample timestamps are illustrative. Aggregate results and technical conclusions are retained.

`dancing-log` is a local VRChat dance playback timeline tool. It records what
was played, when it was played, where the event came from, and how it maps back
to dance-system catalog entries and recordings.

The current implementation uses SQLite as runtime state. CSV/JSON files are
temporary import/export artifacts only.

## Current Data Model

The database now separates four concepts:

- `dance_systems`: dance systems such as `wannadance`.
- `dance_tracks`: a playable dance entry inside one dance system.
- `music_tracks`: a real music track, shared by one or more dance versions.
- `playback_records`: Local Playback Evidence for Timeline, review, and Insights.

WannaDance-specific cache fields live in `wannadance_songs`, not in
playback history rows. A playback record points to
`playback_records.dance_track_id`, which points to `dance_tracks.id`.

Core tables:

- `dance_systems`
- `dance_tracks`
- `wannadance_songs`
- `music_tracks`
- `dance_track_music_links`
- `playback_records`

Transition and forensic tables:

- `dance_events`
- `vrcx_import_events`
- `live_playback_events`

`dance_events`, `vrcx_import_events`, and `live_playback_events` are Legacy
Playback Roots, staging provenance, or runtime observation tables during the
transition. They may be read for compatibility, migration, and diagnosis, but
normal Timeline reads use the effective playback projection over
`playback_records`, while Insights, daily reports, and recommendations read the
effective accepted projection. Manual logging, VRCX import, queued-self sync,
and watcher-derived live evidence now write target-owned Local Playback
Evidence into `playback_records`.

Deferred tables:

- music provider matches, such as NetEase or Kugou ids
- popularity snapshots and comment-count history

See `docs/dance_data_model.md` for the design rationale.

Related docs:

- `docs/dance_data_model.md`: current SQLite model and table boundaries.
- `docs/app_directories.md`: application-root paths, local config, and output directories.
- `docs/portable_release.md`: Windows portable release build and tag workflow.
- `docs/accessibility/webui-release-checklist.md`: WCAG-EM release evaluation and evidence process.
- `docs/wanna_catalog_sync.md`: WannaDance API/cache sync behavior.
- `docs/vrcx_integration_notes.md`: VRCX source research and importer status.
- `docs/music_api_research.md`: archived provider-matching research.

Chinese docs:

- `README.zh-CN.md`: Chinese project overview and daily commands.
- `docs/app_directories.zh-CN.md`: Chinese application-directory notes.
- `docs/dance_data_model.zh-CN.md`: Chinese data model notes.
- `docs/portable_release.zh-CN.md`: Chinese portable release notes.
- `docs/wanna_catalog_sync.zh-CN.md`: Chinese WannaDance sync notes.
- `docs/dudu_catalog_sync.zh-CN.md`: Chinese DuDu FitDance source notes.
- `docs/vrcx_integration_notes.zh-CN.md`: Chinese VRCX import notes.
- `docs/music_api_research.zh-CN.md`: Chinese music API research notes.

## Quick Start

Python requirement:

```bash
uv run python main.py
```

If `uv` is unavailable in the current shell, use any Python environment with the
project dependencies installed:

```bash
python main.py
```

In Codex's sandbox, `uv` may need elevated execution because the runner process
can be blocked by sandbox permissions.

Populate the local catalog from WannaDance:

```bash
uv run python main.py sync-wanna
uv run python main.py sync-wanna --offline
```

Archive old generated data and rebuild a clean database from local config:

```bash
uv run python main.py rebuild-data --archive-existing
```

The rebuild flow keeps:

- `config/dancing-log.local.json`
- `data/queued_self/`

It archives generated files such as:

- `data/dancing_log.sqlite3`
- `data/songs.csv`
- `data/wanna_songs.csv`
- `data/wanna_songs.json`

## Daily Commands

Manual logging requires an explicit system key:

```bash
uv run python main.py log --system wannadance 5038
uv run python main.py log --system wannadance 5038 --other
uv run python main.py log --system wannadance 5038 --source random
uv run python main.py log --system wannadance 5038 --note "nice run"
uv run python main.py log --system wannadance 5038 --time "2000-01-01T12:00:00+08:00"
```

`5038` is the external id inside the selected system, not the internal
`dance_tracks.id`.

Manual `log` writes an accepted `playback_records` row. The old CLI command name
is kept for compatibility; internally the record is Local Playback Evidence, and
manual notes are retained in the row provenance.

Generate recommendations:

```bash
uv run python main.py recommend
uv run python main.py recommend -n 10
```

Print the dances from one local day, one dance per line:

```bash
uv run python main.py day 2026-06-07
uv run python main.py day 2026-06-07 --live
```

Each line is formatted as `HH:MM:SS song-id. song name`, for example:

```text
12:00:00 8378. Party In The U.S.A. - Miley Cyrus | Just Dance 2025
```

Daily history is read from accepted `playback_records`. Without `--live`, the
command prints all accepted playback records for the day, including accepted
live-derived records. With `--live`, it filters that same Local Playback
Evidence root to accepted records whose source kind is `live_watcher`.
Interrupted, pending, and other review-attention live evidence is retained in
`playback_records`, but it does not print in normal day history until accepted
and counting in history.

Import favorite song IDs from a UTF-8 text file. It can contain one external id
per line, or a WannaDance export line such as `WannaFavorite:6495,10508`:

```bash
uv run python main.py import-favorites --system wannadance data/favorites.txt
uv run python main.py import-favorites --system wannadance data/favorites.txt --additive
uv run python main.py import-favorites --system wannadance data/favorites.txt --dry-run
```

By default, the import replaces the favorite list for the selected dance system.
Use `--additive` to only mark the listed tracks as favorites. Unknown ids fail
the import without changing the database.

The current recommendation score uses:

- favorite flag
- want-to-learn flag
- dance count
- days since last dance

NetEase/Kugou popularity is intentionally not part of the runtime score yet.

## VRCX Import

Import historical playback rows from VRCX:

```bash
uv run python main.py import-vrcx "path/to/vrcx-snapshot/VRCX.sqlite3"
uv run python main.py import-vrcx --dry-run
```

If `config/dancing-log.local.json` contains `vrcx_db_path`, the path can be
omitted. When that field is empty, the importer also tries the standard VRCX
database at `%APPDATA%/VRCX/VRCX.sqlite3` for the current run without saving it
to config:

```bash
uv run python main.py import-vrcx
```

The importer currently supports WannaDance and observed PyPyDance URLs. It also
has experimental recognition for observed DuDu FitDance API/CDN/page URLs. Other
systems are counted as unsupported instead of being misclassified as WannaDance.

`import-vrcx` writes staging provenance to `vrcx_import_events` and accepted
Local Playback Evidence to `playback_records`. It no longer creates normalized
history rows in legacy `dance_events`.

## Live VRChat Log Capture

Watch live VRChat Unity output logs, write capture artifacts, and materialize
watcher-derived Local Playback Evidence:

```bash
uv run python main.py watch-vrc-log
```

The watcher uses `vrc_log_dir` from `config/dancing-log.local.json` when present, then
falls back to the standard Windows LocalLow path. It always writes local ignored
capture artifacts under `logs/captures/<session>/`:

- `raw_output_log.txt`: low-overhead mirror of captured raw lines
- `candidates.jsonl`: video-related lines worth inspecting
- `parsed_events.jsonl`: parsed playback-like events with URL classification
- `playback_events.jsonl`: folded per-song events with playback delay metrics
- `summary.json`: session counts and final read position

It also incrementally archives the active source `output_log_*.txt` under
`logs/source-vrc-logs/` by default. The source archive is copied as bytes and
resumes from the existing archived file size on the next run, so it avoids
duplicating lines and can preserve the original log content. Use
`--no-source-archive` to disable this, or `--source-log-dir` to choose another
archive directory.

By default it starts at the end of the current log file so old large logs are
not rescanned while VRChat is running. Use `--from-start` to replay an existing
log file, or `--no-raw` to skip the full raw mirror and keep only candidate and
parsed JSONL output.

`parsed_events.jsonl` remains a signal-level forensic stream. The deduplicated
event view is `playback_events.jsonl`, which tracks request, resolve, load,
actual-play, source, mid-play progress, and delay fields when those signals appear
in the VRChat log.

The normal watcher path writes a `playback_records` row as soon as a folded
watcher observation has a stable dance identity. New rows start as `pending`
with `counts_in_history=0`, then watcher settlement updates them to accepted
or needs-attention evidence. `live_playback_events` is deprecated for normal
operation. To also mirror folded runtime state into the legacy forensic table,
use the experimental flag:

```bash
uv run python main.py watch-vrc-log --live-db
```

## Local Web UI

Start the main local Web UI:

```bash
uv run python main.py webui
uv run python main.py webui --port 8787 --no-open
```

The Web UI binds only to `127.0.0.1` and opens
`http://127.0.0.1:8787/home` by default. Home, Timeline, Catalog, Lists,
Insights, Data Operations, and Settings use `/home`, `/timeline`, `/catalog`,
`/lists`, `/insights`, `/data-operations`, and `/settings`. Refresh and browser
history preserve the current page, while Timeline stores its date and reverse
sort selection in query parameters.

In desktop/Web UI mode, the OBS overlay shares the same HTTP listener at
`http://127.0.0.1:8787/overlay`; its state and SSE endpoints are
`/api/overlay/state` and `/api/overlay/events`. This mode does not bind a second
overlay port. When live overlay publication is stopped, the route explicitly
shows `Overlay inactive`; `Waiting for playback` is reserved for an enabled
overlay whose watcher has not captured a current playback event yet.
Home continues to show the watcher's in-memory current playback while overlay
publication is disabled; the overlay switch controls only the viewer-facing
projection.
Settings preserves unsupported local config keys as read-only values when it
saves supported fields.

Desktop shutdown first stops the Web UI listener, drains ordinary HTTP handlers,
then irreversibly closes the live app session. Request headers and bodies have an
absolute monotonic read deadline, and shutdown actively closes connections that
have not entered an operation. Only complete, parsed requests receive the
unbounded reliable drain. This lets ordinary writes and terminal watcher
finalization finish without truncating SQLite commits, settlement, or capture
artifacts. A permanently stuck accepted operation or finalizer keeps the process
alive for diagnosis. SSE connections use a separate active close and bounded
drain.
Timeline opens on the latest local date that has playback records, then keeps
calendar and arrow navigation scoped to the selected local date.
The UI supports English and Chinese through a browser-local language switch,
and system, light, and dark Fluent 2 themes through a separate theme selector.
The Local Web UI is a Windows desktop productivity surface governed by Fluent 2,
WCAG 2.2 AA, and WAI-ARIA APG. Run its browser acceptance suite with:

```powershell
uv sync --locked --cache-dir .uv-cache
pnpm install --frozen-lockfile
pnpm exec playwright install chromium
pnpm test:a11y
```

This scans all seven primary pages in light and dark themes with Playwright and
axe, then exercises ARIA, keyboard, focus, validation, failure, and forced-colors
contracts. Automated success is not a complete conformance claim. Follow
`docs/accessibility/webui-release-checklist.md` for the required WCAG-EM manual
release check; Lighthouse Accessibility remains a supporting signal only.

For deterministic offline replay of a fixed corpus, use the replay helper
instead of `watch-vrc-log --from-start`:

```bash
python scripts/replay_vrc_logs.py baseline --log-dir analysis/vrc_logs --output analysis/replay_gt/current-head
python scripts/replay_vrc_logs.py compare --baseline analysis/replay_gt/current-head --output analysis/replay_runs/post-refactor --manual-gt analysis/promote_GT/sample-history.txt --vrcx-db "path/to/vrcx-snapshot/VRCX.sqlite3"
```

`baseline` and `compare` replay every matched log file in filename order and
write ignored artifacts under `analysis/`. `diff_report.md` compares folded
playback events, watcher settlement results, the optional manual GT file, and
an optional read-only VRCX row count for the manual window.

For a standalone watcher and OBS overlay without the Web UI:

```bash
uv run python main.py watch-vrc-log --overlay-port 8765
```

The standalone overlay page is available at `http://127.0.0.1:8765/overlay`. It is
self-contained, binds only to localhost, and updates through server-sent events.
Stopping this server closes accepted ordinary HTTP connections as well as SSE
streams and waits for their handlers to drain before returning.
Watcher processes take exclusive OS-backed locks for the application root and
resolved SQLite database before startup maintenance. The locks remain held through
settlement, database commits, capture artifact cleanup, and finalization, so CLI,
Web UI, and tray workflows cannot run conflicting watchers against the same scope.
Normal watcher evidence is persisted directly in `playback_records` using the
logical source table `watcher_playback_events`. Normal Timeline reads the
effective playback projection and shows accepted, pending, excluded, and
needs-attention status. Insights, daily history, and recommendation history read
the effective accepted projection instead of the legacy source tables. `--live-db`
is deprecated experimental output for legacy forensic inspection only.

Room leave and VRChat quit/shutdown log events clear the overlay's current
playback and settle pending watcher-derived playback records. Graceful watcher
stop also settles pending records: completed-enough observations become
accepted; the rest become non-counting needs-attention records.

WannaDance `PreviewVideo` lines suppress the preview player's load/resolve/start
noise, but a later real VRCX `VideoPlay` for the same song is still accepted.
Same-song retry/resolve signals are folded back into the active playback event,
so the overlay keeps the VRCX title instead of falling back to a raw URL.

WannaDance `PlayQueueVideo` / `PlayRandomVideo ... videoDuration` and
`VideoQueueManager` queue JSON lines are parsed as runtime metadata only. They
can fill `songId`, title, player name, duration, and `duration_source` on a real
playback event, but they do not create playback by themselves and do not depend
on the catalog DB.

WannaDance/PyPyDance `Playing synced` lines are recorded as `synced_play_at`
only; they do not by themselves clear the overlay or mark a row as mid-play.
Mid-play detection comes from explicit progress offsets. Mid-play rows remain
visible in the overlay as pending current playback, but they remain ineligible
for automatic acceptance until watcher settlement.

## Queued-Self Manifests

Queued-self manifests can use bare external ids. Pass the dance system on the
command line when syncing:

```text
# 2026-04-17
5038 Good Time
```

System-prefixed refs such as `wannadance:5038` are still accepted when a
manifest needs to mix systems.

Sync queued-self manifests:

```bash
uv run python main.py sync-queued-self --system wannadance
```

## Application Directories And Local Config

Local machine paths live in `config/dancing-log.local.json` and are ignored by
git. See `docs/app_directories.md` for the full directory contract.

Supported keys:

```json
{
  "config_version": 1,
  "app_db": "data/dancing_log.sqlite3",
  "queued_self_dir": "data/queued_self",
  "capture_dir": "logs/captures",
  "run_log_dir": "logs/runs",
  "source_vrc_log_dir": "logs/source-vrc-logs",
  "recording_frames_dir": "analysis/recording_frames",
  "self_user_id": null,
  "vrcx_db_path": null,
  "vrc_log_dir": null,
  "wanna_cache_dir": null,
  "recordings_dir": null,
  "dance_day_boundary_time": "00:00",
  "auto_start_watcher": false,
  "auto_start_overlay": false,
  "overlay_port": 8765
}
```

`dance_day_boundary_time` is the local wall-clock start of a dance day. It uses
the operating system's local time zone, accepts `00:00` through `06:00`, and is
shared by Timeline, day reports, queued-self matching, and daily recommendation
seeding.

`overlay_port` is an advanced compatibility setting for a standalone watcher
overlay without the Web UI. Desktop/Web UI mode uses the Web UI port.

## Research Scripts

`scripts/match_netease.py`, `scripts/test_music_apis.py`, and `sample-frames`
remain research tools. They are not part of the current runtime data model or
portable release.

`sample-frames` requires optional recording dependencies:

```bash
uv sync --extra recording-tools
```

`scripts/init_songs.py` is deprecated because the runtime database no longer
has a `songs` table.
