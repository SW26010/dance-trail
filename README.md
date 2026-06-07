# dancing-log

> Privacy note: Personal paths and activity examples are anonymized. Replace example paths with your own; sample timestamps are illustrative. Aggregate results and technical conclusions are retained.

`dancing-log` is a local VRChat dance playback timeline tool. It records what
was played, when it was played, where the event came from, and how it maps back
to dance-system catalog entries and recordings.

The current implementation uses SQLite as runtime state. CSV/JSON files are
temporary import/export artifacts only.

## Current Data Model

The database now separates three concepts:

- `dance_systems`: dance systems such as `wannadance`.
- `dance_tracks`: a playable dance entry inside one dance system.
- `music_tracks`: a real music track, shared by one or more dance versions.

WannaDance-specific cache fields live in `wannadance_songs`, not in
`dance_events`. A playback event points to `dance_events.dance_track_id`, which
points to `dance_tracks.id`.

Core tables:

- `dance_systems`
- `dance_tracks`
- `wannadance_songs`
- `music_tracks`
- `dance_track_music_links`
- `dance_events`
- `vrcx_import_events`

Deferred tables:

- music provider matches, such as NetEase or Kugou ids
- popularity snapshots and comment-count history

See `docs/dance_data_model.md` for the design rationale.

Related docs:

- `docs/dance_data_model.md`: current SQLite model and table boundaries.
- `docs/app_directories.md`: application-root paths, local config, and output directories.
- `docs/wanna_catalog_sync.md`: WannaDance API/cache sync behavior.
- `docs/vrcx_integration_notes.md`: VRCX source research and importer status.
- `docs/music_api_research.md`: archived provider-matching research.

Chinese docs:

- `README.zh-CN.md`: Chinese project overview and daily commands.
- `docs/app_directories.zh-CN.md`: Chinese application-directory notes.
- `docs/dance_data_model.zh-CN.md`: Chinese data model notes.
- `docs/wanna_catalog_sync.zh-CN.md`: Chinese WannaDance sync notes.
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

Generate recommendations:

```bash
uv run python main.py recommend
uv run python main.py recommend -n 10
```

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

If `config/dancing-log.local.json` contains `vrcx_db_path`, the path can be omitted:

```bash
uv run python main.py import-vrcx
```

The importer currently supports WannaDance and observed PyPyDance URLs. Dudu
and other systems are counted as unsupported instead of being misclassified as
WannaDance.

## Live VRChat Log Capture

Capture live VRChat Unity output logs for parser forensics:

```bash
uv run python main.py watch-vrc-log
```

The watcher uses `vrc_log_dir` from `config/dancing-log.local.json` when present, then
falls back to the standard Windows LocalLow path. It writes only local ignored
artifacts under `logs/captures/<session>/`:

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

For deterministic offline replay of a fixed corpus, use the replay helper
instead of `watch-vrc-log --from-start`:

```bash
python scripts/replay_vrc_logs.py baseline --log-dir analysis/vrc_logs --output analysis/replay_gt/current-head
python scripts/replay_vrc_logs.py compare --baseline analysis/replay_gt/current-head --output analysis/replay_runs/post-refactor --manual-gt analysis/promote_GT/sample-history.txt --vrcx-db "path/to/vrcx-snapshot/VRCX.sqlite3"
```

`baseline` and `compare` replay every matched log file in filename order and
write ignored artifacts under `analysis/`. `diff_report.md` compares folded
playback events, live SQLite promotion results, the optional manual GT file, and
an optional read-only VRCX row count for the manual window.

For live local state and OBS overlay output:

```bash
uv run python main.py watch-vrc-log --live-db --overlay-port 8765
```

The local overlay page is available at `http://127.0.0.1:8765/overlay`. It is
self-contained, binds only to localhost, and updates through server-sent events.
`live_playback_events` is updated immediately as log signals arrive; official
`dance_events` are written only when `--promote-live` is passed and the live row
has played at least 80% of the known `duration_seconds`.

Room leave and VRChat quit/shutdown log events clear the overlay's current
playback and mark pending live rows as interrupted. Entering-room status is
shown only until a newer playback event arrives, so stale room transitions do
not cover the current track.

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
for promotion into official history.

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
  "recordings_dir": null
}
```

## Research Scripts

`scripts/match_netease.py` and `scripts/test_music_apis.py` remain research
tools. They are not part of the current runtime data model.

`scripts/init_songs.py` is deprecated because the runtime database no longer
has a `songs` table.
