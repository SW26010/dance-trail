# WannaDance Catalog Sync

Date: 2026-05-17

## Purpose

`dance-trail` stores WannaDance catalog metadata in the local SQLite database so
playback events can point to stable dance-track rows and still show useful song
names, artists, dancers, groups, player counts, and local cache paths.

The catalog sync uses two complementary sources:

- Public WannaDance API: canonical public catalog metadata.
- Local `wanna_cache_dir`: local downloaded song cache from
  `config/dance-trail.local.json`.

The local cache remains useful when the API is unavailable because each cached
song directory can contain `metadata.json`, `download.txt`, and `video.mp4`.

## Commands

Preferred online sync:

```powershell
uv run python main.py sync-wanna
```

Offline/cache-only sync:

```powershell
uv run python main.py sync-wanna --offline
```

Export CSV/JSON artifacts for inspection:

```powershell
uv run python main.py sync-wanna --write-files
```

Use an explicit cache directory:

```powershell
uv run python main.py sync-wanna --cache-dir "D:\path\to\wannadance-song"
```

If `uv` is not available in the current shell, the same command can be run with
any Python environment that has the project dependencies installed:

```powershell
python main.py sync-wanna
```

In the Codex sandbox, `uv` may require elevated execution because the runner can
be blocked by sandbox permissions.

## Data Sources

### Public API

Endpoint:

```text
https://x.kiva.moe/api/v2/wanna/songs
```

Fields used:

- `id`
- `name`
- `artist`
- `dancer`
- `playerCount`
- group `title`
- group `major`

Rows with `disablePublic=true` are skipped, and duplicate song ids are
deduplicated.

### Local Cache

Configured through:

```json
{
  "wanna_cache_dir": "D:\\path\\to\\wannadance-song"
}
```

Expected layout:

```text
wannadance-song/
|-- 1/
|   |-- metadata.json
|   |-- download.txt
|   `-- video.mp4
`-- 10000/
    |-- metadata.json
    |-- download.txt
    `-- video.mp4
```

Useful cache metadata:

- `id`
- `category`
- `title`
- `titleSpell`
- `playerIndex`
- `volume`
- `start`
- `end`
- `flip`
- `skipRandom`
- `checksum`
- `url`
- `urlForQuest`

The sync records local paths for `metadata.json`, `download.txt`, and
`video.mp4` when present.

## SQLite Storage

The runtime database no longer has a `songs` table.

WannaDance sync writes the generic entry fields into `dance_tracks`:

- `system_id`
- `external_id`
- `title`
- `artist`
- `dancer`
- `player_count`
- `group_name`
- `major`

WannaDance-specific fields are written into `wannadance_songs`:

- `wanna_id`
- `cache_category`
- `cache_title`
- `cache_title_spell`
- `cache_player_index`
- `cache_volume`
- `cache_start_seconds`
- `cache_end_seconds`
- `cache_flip`
- `cache_skip_random`
- `cache_checksum`
- `cache_url`
- `cache_url_for_quest`
- `local_video_path`
- `local_metadata_path`
- `local_download_path`
- `cache_updated_at`

When both title and artist are present, the sync also creates:

- a `music_tracks` row keyed by normalized title/artist
- a `dance_track_music_links` row with `match_method = 'title_artist_auto'`

Local user flags such as `favorite` and `want_to_learn` live on `dance_tracks`
and are preserved by catalog upserts.

NetEase/Kugou provider ids and popularity fields are not part of the current
runtime schema.

## Merge Rules

1. Load local cache metadata first.
2. Use cache `title` as a fallback song title.
3. Overlay API metadata when available, because it has richer public catalog
   fields such as artist, dancer, player count, group, and major category.
4. Upsert generic fields into `dance_tracks` by `(system_id, external_id)`.
5. Upsert WannaDance-only fields into `wannadance_songs` by `dance_track_id`.
6. Upsert music rows and dance-to-music links when title and artist are present.

The sync does not delete catalog rows that are missing from the latest API or
local cache. Existing playback history may still refer to them.

## Current Local Snapshot

The local database snapshot checked on 2026-05-17 contained:

- `dance_tracks`: 10,204
- `wannadance_songs`: 10,204
- `music_tracks`: 7,378
- `dance_track_music_links`: 9,782

These counts are local derived data, not repository source.

## Generated Files

The sync updates SQLite by default:

- `data/dance_trail.sqlite3`

CSV/JSON files are optional export artifacts when `--write-files` is passed:

- `data/wanna_songs.csv`
- `data/wanna_songs.json`

Legacy `data/songs.csv` is no longer a runtime source.

These files are ignored by git. They are local derived data, not repository
source files.

## Implementation Files

- `dance_trail/wanna_catalog.py`: catalog loading, merging, export, and SQLite
  upsert logic.
- `dance_trail/storage.py`: SQLite schema and shared upsert helpers.
- `scripts/sync_wanna_songs.py`: command-line wrapper.
- `main.py`: exposes the `sync-wanna` command.
