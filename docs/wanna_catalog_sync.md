# Wanna Catalog Sync

Date: 2026-05-16

## Purpose

`dancing-log` keeps Wanna Dance song metadata in the local SQLite database so
playback events can point at stable song ids and still show useful song names,
artists, dance groups, and local cache file paths.

The catalog sync now uses two complementary sources:

- Public Wanna Dance API: canonical public catalog metadata.
- Local `wanna_cache_dir`: local downloaded song cache from `data/local_config.json`.

The local cache is useful even when the API is unavailable because each cached
song directory contains `metadata.json`, `download.txt`, and usually `video.mp4`.

## Commands

Preferred online sync:

```powershell
python main.py sync-wanna
```

Offline/cache-only sync:

```powershell
python main.py sync-wanna --offline
```

Skip regenerated CSV/JSON artifacts and update only SQLite:

```powershell
python main.py sync-wanna --no-files
```

Use an explicit cache directory:

```powershell
python main.py sync-wanna --cache-dir "D:\path\to\wannadance-song"
```

The command also works through the project runner when available:

```powershell
uv run python main.py sync-wanna
```

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

The `songs` table remains keyed by Wanna song id.

Existing user-maintained fields are preserved during sync:

- `favorite`
- `want_to_learn`
- `netease_id`
- `popularity`
- `comment_count`

The sync adds cache-related columns:

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

For older databases, these columns are added automatically by
`dancing_log.storage.init_schema()`.

## Merge Rules

1. Load local cache metadata first.
2. Use cache `title` as a fallback song `name`.
3. Overlay API metadata when available, because it has richer public catalog
   fields such as artist, dancer, player count, group, and major category.
4. Upsert by song id into SQLite.
5. Preserve local user flags and NetEase match fields.
6. Keep existing rows that are referenced by playback history, even if they are
   missing from both the latest API and local cache.

## Current Local Result

The 2026-05-16 sync found:

- API songs: 9782
- cached songs: 10203
- SQLite `songs` rows after sync: 10204
- rows with song name: 10203
- rows with API artist metadata: 9782
- rows with local cache metadata: 10203

One legacy row, song id `10985`, was retained because it is referenced by an
existing imported playback event, but it was not present in the latest API or
the local cache.

## Generated Files

The sync refreshes local data artifacts under `data/`:

- `data/dancing_log.sqlite3`
- `data/songs.csv`
- `data/wanna_songs.csv`
- `data/wanna_songs.json`

These files are ignored by git. They are local derived data, not repository
source files.

## Implementation Files

- `dancing_log/wanna_catalog.py`: catalog loading, merging, export, and SQLite
  upsert logic.
- `scripts/sync_wanna_songs.py`: command-line wrapper.
- `dancing_log/storage.py`: SQLite schema and automatic cache-column migration.
- `main.py`: exposes the `sync-wanna` command.
