# Dance Data Model

Date: 2026-05-17
Updated: 2026-07-19

Primary data-model definition described here: v0 (runtime and historical reference)

This document describes the current SQLite runtime model for `dance-trail`.
The project no longer uses the legacy `songs` table or
`dance_events.song_id` path.
After the legacy cleanup recorded in ADR 0004, `playback_records` is the
Local Playback Evidence v0 read contract for normal Timeline and Insights
queries.

The directional definition for the next playback data model is
`docs/playback_data_model_redesign.zh-CN.md`. This document remains the
current/v0 runtime model description and must not constrain the new structure
or its future field design.

ADR 0013 defines the next responsibility boundary: the watcher only captures,
deterministically organizes, and persists source evidence. It does not own a
durable event/occurrence summary, Request Source Type Inference, acceptance
state, or historical repair. Watcher folding, settlement, or direct
`playback_records` writes described below are current/v0 runtime facts, not
long-term ownership of those product projections.

## Current Scope

The first refactor implements the core model directly:

- SQLite is the runtime store.
- Generated CSV/JSON files are import/export artifacts only.
- Existing generated data is archived during rebuild, not migrated in place.
- `config/dance-trail.local.json` and `data/queued_self/` are preserved as local inputs.
- WannaDance is the first dance system with catalog sync implemented.
- PyPyDance URL identity is supported from observed logs. DuDu FitDance has
  experimental support from a small sample set: official/API URLs, VRChat log
  metadata, and VRCX URLs can be recognized as `dudu`. Dudu catalog sync
  remains unimplemented; VRDancing and other systems are still unsupported.
- `music_tracks` and `dance_track_music_links` are implemented with conservative
  title/artist matching.
- `playback_records` is the current Local Playback Evidence root for accepted
  history, review attention, Timeline, and Insights reads.
- `dance_events`, `vrcx_import_events`, and `live_playback_events` are retained
  as Legacy Playback Roots, staging provenance, or runtime observation tables
  during the transition.
- Manual logging, VRCX import, queued-self sync, and watcher-derived live
  evidence write target-owned Local Playback Evidence into `playback_records`.
- Provider matching and popularity snapshots are deferred.

## Why The Model Changed

The original schema was convenient for a WannaDance-only workflow, but it mixed
several different concepts in one place:

- a dance-system catalog entry
- a real music track
- WannaDance-specific cache fields
- recommendation metadata
- playback history

That becomes painful once playback events can come from multiple dance systems.
Different systems can use different ids for the same song, and even one system
can have multiple choreographies, remixes, or player-count versions for the same
music track.

The current model separates "a playable dance entry in one dance system" from
"the real music track that entry uses".

## Core Concepts

### Dance System

A dance system is the source namespace for playable entries. Examples:

- `wannadance`
- `pypydance`
- `dudu`
- `vrdancing`

Only `wannadance` has catalog sync implemented today. `pypydance` supports
URL/playback identity. `dudu` has experimental playback identity support and can
produce playback evidence from the watcher/VRCX path, but it does not yet have
catalog sync and should not be described as full DuDu FitDance support.

### Dance Track

A dance track is one playable version inside one dance system.

Examples:

- WannaDance `3114`: `Boy With Luv (Extreme) / BTS & Halsey`
- WannaDance `5038`: `Good Time / Owl City`
- A future PyPyDance entry with its own id and metadata

The stable identity is `(system_id, external_id)`.

### Music Track

A music track represents the real song, independent of dance system and
choreography.

Examples:

- `Good Time / Owl City`
- `Boy With Luv / BTS & Halsey`

It intentionally does not contain dancer, player count, choreography version, or
dance-system id.

### Playback Record

A playback record is Local Playback Evidence that a dance track was observed,
imported, cleaned, or merged at a time.

It points to `playback_records.dance_track_id`, not to a WannaDance id directly.
Default acceptance fields such as `playback_status` and `counts_in_history`
live on the playback record. Normal Timeline, Insights, daily report, and
recommendation reads use the effective playback projection: the default
playback-record state plus any active Manual Playback Decision overlay.

### Legacy Dance Event

A legacy dance event is an older normalized playback-history row in
`dance_events`. It is kept for compatibility, migration, and diagnosis, but it
is not the long-term canonical root for ordinary playback history.

## Runtime Tables

### `dance_systems`

Stores supported dance systems.

| Column | Type | Meaning |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | Internal system id |
| `key` | TEXT UNIQUE NOT NULL | Stable machine key, for example `wannadance` |
| `name` | TEXT NOT NULL | Display name |
| `created_at` | TEXT | Creation timestamp |

### `dance_tracks`

Stores playable dance entries.

| Column | Type | Meaning |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | Internal dance-track id |
| `system_id` | INTEGER NOT NULL | References `dance_systems.id` |
| `external_id` | TEXT NOT NULL | Id inside the dance system |
| `title` | TEXT | Dance-system title |
| `artist` | TEXT | Dance-system artist |
| `dancer` | TEXT | Dancer, choreographer, or version name |
| `player_count` | INTEGER | Number of dancers |
| `group_name` | TEXT | System-specific group/category |
| `major` | TEXT | Larger category |
| `favorite` | INTEGER NOT NULL DEFAULT 0 | Local preference flag |
| `want_to_learn` | INTEGER NOT NULL DEFAULT 0 | Local learning flag |
| `created_at` | TEXT | Creation timestamp |
| `updated_at` | TEXT | Update timestamp |

Constraint:

```sql
UNIQUE(system_id, external_id)
```

### `wannadance_songs`

Stores WannaDance-specific extension fields. These fields are intentionally not
stored in `dance_tracks` or playback history rows.

| Column | Type | Meaning |
|---|---|---|
| `dance_track_id` | INTEGER PRIMARY KEY | References `dance_tracks.id` |
| `wanna_id` | INTEGER NOT NULL UNIQUE | WannaDance song id |
| `cache_category` | INTEGER | Cache category |
| `cache_title` | TEXT | Local cache title |
| `cache_title_spell` | TEXT | Title spelling |
| `cache_player_index` | INTEGER | Player index |
| `cache_volume` | REAL | Volume |
| `cache_start_seconds` | REAL | Start offset |
| `cache_end_seconds` | REAL | End offset |
| `cache_flip` | INTEGER | Flip flag |
| `cache_skip_random` | INTEGER | Skip-random flag |
| `cache_checksum` | TEXT | Cache checksum |
| `cache_url` | TEXT | Playback URL |
| `cache_url_for_quest` | TEXT | Quest playback URL |
| `local_video_path` | TEXT | Local `video.mp4` path |
| `local_metadata_path` | TEXT | Local `metadata.json` path |
| `local_download_path` | TEXT | Local `download.txt` path |
| `cache_updated_at` | TEXT | Cache file timestamp |

### `music_tracks`

Stores canonical music-track rows created from title/artist pairs.

| Column | Type | Meaning |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | Internal music-track id |
| `title` | TEXT NOT NULL | Song title |
| `artist` | TEXT | Artist |
| `normalized_title` | TEXT NOT NULL | Normalized title for matching |
| `normalized_artist` | TEXT NOT NULL | Normalized artist for matching |
| `created_at` | TEXT | Creation timestamp |
| `updated_at` | TEXT | Update timestamp |

Constraint:

```sql
UNIQUE(normalized_title, normalized_artist)
```

### `dance_track_music_links`

Maps dance-system entries to real music tracks.

| Column | Type | Meaning |
|---|---|---|
| `dance_track_id` | INTEGER NOT NULL | References `dance_tracks.id` |
| `music_track_id` | INTEGER NOT NULL | References `music_tracks.id` |
| `confidence` | REAL NOT NULL DEFAULT 1.0 | Match confidence |
| `match_method` | TEXT NOT NULL | Example: `title_artist_auto` |
| `created_at` | TEXT | Creation timestamp |
| `updated_at` | TEXT | Update timestamp |

Constraint:

```sql
PRIMARY KEY(dance_track_id, music_track_id)
```

### `playback_records`

Stores Local Playback Evidence for normal Timeline, review, and Insights reads.
This table is the v0 read contract after the one-time legacy cleanup.
Canonical timestamp columns store ISO 8601 UTC values with a `Z` suffix.
Raw provenance fields such as `original_played_at` preserve the source text before normalization.

| Column | Type | Meaning |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | Playback record id |
| `cleanup_batch_id` | TEXT NOT NULL | Cleanup batch that created the row |
| `played_at` | TEXT NOT NULL | Normalized playback time |
| `original_played_at` | TEXT NOT NULL | Source timestamp before normalization |
| `dance_track_id` | INTEGER | References `dance_tracks.id` when resolved |
| `dance_system_key` | TEXT NOT NULL | Dance-system key, for example `wannadance` |
| `dance_external_id` | TEXT NOT NULL | System-local dance id |
| `source_kind` | TEXT NOT NULL | Broad evidence kind, such as VRCX or live watcher |
| `source_root_key` | TEXT NOT NULL | Source app root or source set key |
| `source_root_path` | TEXT NOT NULL | Source app root or database path |
| `source_table` | TEXT NOT NULL | Original source table |
| `source_row_id` | INTEGER NOT NULL | Original source row id |
| `source_event_key` | TEXT | Original source event key |
| `source_fingerprint` | TEXT NOT NULL UNIQUE | Stable source-row fingerprint for dedupe |
| `playback_status` | TEXT NOT NULL | `pending`, `accepted`, `needs_attention`, or future status |
| `counts_in_history` | INTEGER NOT NULL DEFAULT 0 | Default evidence-derived history inclusion before manual overlay |
| `status_reason` | TEXT NOT NULL | Reason for the current default status |
| `source_priority` | INTEGER NOT NULL DEFAULT 0 | Evidence Source Priority used for overlap review |
| `confidence` | REAL | Source inference confidence |
| `event_source` | TEXT | Legacy or parser event source |
| `source_type` | TEXT | Request Source Type |
| `source_display_name` | TEXT | Display name attached to source inference |
| `video_url` | TEXT | Raw playback URL |
| `video_name` | TEXT | Raw video name |
| `requester_display_name` | TEXT | Requester display name |
| `requester_user_id` | TEXT | Requester VRChat user id |
| `location` | TEXT | World or instance context |
| `completion_status` | TEXT | Live completion state when applicable |
| `completion_reason` | TEXT | Live completion reason when applicable |
| `catalog_status` | TEXT NOT NULL DEFAULT `existing` | Catalog resolution status |
| `catalog_attention` | INTEGER NOT NULL DEFAULT 0 | Whether catalog data needs attention |
| `provenance_json` | TEXT NOT NULL | Source evidence and cleanup provenance |
| `imported_at` | TEXT NOT NULL | Import timestamp |

Request Source Type and Evidence Source Priority are intentionally separate
concepts. The current schema stores Request Source Type in `source_type`; it is
the request/playback-source classification, for example `queued_self`,
`recommend`, `self`, `other`, `random`, or `unknown`. Its precedence is only
used to preserve a stronger classification when the same playback record is
replayed or reimported; for example, a queued-self overlay must not be downgraded
back to VRCX-inferred `random`. The current schema stores Evidence Source
Priority in `source_priority`; it is the evidence strength used when reviewing
overlapping or conflicting playback records, such as live watcher evidence, VRCX
history, a manual decision, or automatic acceptance. It is not the ordering of
request/source categories. Neither Request Source Type nor its classification
precedence decides whether a row is effectively accepted, excluded, or needs
attention; that acceptance projection is owned by playback evidence, Evidence
Source Priority conflict rules, and active manual playback decisions.

`source_root_path` should identify the source app root or database path when a
row is tied to an external source. Project-owned or ADR 0004 compatibility rows
may preserve the project/app root used by their stable source identity; raw
external database paths should also be recorded in `provenance_json` when the
source table is local staging.

### `manual_playback_decisions`

Stores the reversible Manual Playback Decision overlay for playback records.
This table does not rewrite Local Playback Evidence. One active row, if present,
overrides the default acceptance result projected from `playback_records`.

| Column | Type | Meaning |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | Manual decision id |
| `playback_record_id` | INTEGER NOT NULL | References `playback_records.id` |
| `decision_status` | TEXT NOT NULL | `accepted`, `excluded`, or `needs_attention` |
| `decision_reason` | TEXT NOT NULL DEFAULT `''` | Reason for the manual decision |
| `note` | TEXT NOT NULL DEFAULT `''` | Optional review note |
| `active` | INTEGER NOT NULL DEFAULT 1 | Whether this overlay currently applies |
| `decided_at` | TEXT NOT NULL DEFAULT `strftime('%Y-%m-%dT%H:%M:%SZ','now')` | Original decision timestamp in ISO 8601 UTC |
| `updated_at` | TEXT NOT NULL DEFAULT `strftime('%Y-%m-%dT%H:%M:%SZ','now')` | Last update timestamp in ISO 8601 UTC |

Constraint:

```sql
CREATE UNIQUE INDEX idx_manual_playback_decisions_active
  ON manual_playback_decisions(playback_record_id)
  WHERE active = 1;
```

### `dance_events`

Legacy Playback Root for older normalized playback history. It is retained for
compatibility, migration, and diagnosis. Normal Timeline and Insights reads use
`playback_records` instead. Current product write paths no longer create or
update ordinary history here.

| Column | Type | Meaning |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | Event id |
| `played_at` | TEXT NOT NULL | Playback time |
| `dance_track_id` | INTEGER | References `dance_tracks.id` |
| `source` | TEXT NOT NULL DEFAULT `unknown` | `queued_self`, `recommend`, `self`, `other`, `random`, or `unknown` |
| `confidence` | REAL NOT NULL DEFAULT 0.5 | Source confidence |
| `event_source` | TEXT NOT NULL | Import source, for example `manual`, `vrcx`, or `queued_self_manifest` |
| `event_key` | TEXT NOT NULL UNIQUE | Deduplication key |
| `video_url` | TEXT | Raw playback URL |
| `video_name` | TEXT | Raw video name |
| `requester_display_name` | TEXT | Requester display name |
| `requester_user_id` | TEXT | Requester VRChat user id |
| `location` | TEXT | World or instance context |
| `note` | TEXT | Manual note |
| `recording_id` | INTEGER | Future recording link |
| `recording_offset_seconds` | REAL | Future recording offset |
| `imported_at` | TEXT | Import timestamp |

### `vrcx_import_events`

Stores VRCX import provenance and parse results. During the transition, it
explains imported source rows and can feed migration or cleanup. It is not the
ordinary Timeline or Insights root. The current `import-vrcx` command writes
this table as staging provenance and writes accepted Local Playback Evidence to
`playback_records`.

| Column | Type | Meaning |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | Import row id |
| `vrcx_rowid` | INTEGER NOT NULL | Source VRCX rowid |
| `created_at` | TEXT NOT NULL | VRCX event time |
| `video_url` | TEXT | Raw playback URL |
| `video_name` | TEXT | Raw video name |
| `video_id` | TEXT | VRCX video id |
| `location` | TEXT | World or instance context |
| `display_name` | TEXT | Requester display name |
| `user_id` | TEXT | Requester user id |
| `parsed_system_id` | INTEGER | Parsed dance system |
| `parsed_external_id` | TEXT | Parsed system-local id |
| `parsed_dance_track_id` | INTEGER | Matched `dance_tracks.id` |
| `inferred_source` | TEXT NOT NULL DEFAULT `unknown` | Inferred event source |
| `confidence` | REAL NOT NULL DEFAULT 0.5 | Source confidence |
| `event_key` | TEXT NOT NULL UNIQUE | Deduplication key |
| `imported_at` | TEXT | Import timestamp |

### `live_playback_events`

Deprecated experimental runtime table for legacy live watcher forensics. Normal
watcher workflows write folded observations with stable dance identity directly
to `playback_records`; `--live-db` additionally mirrors folded state here for
diagnosis.

Columns mirror the forensic `playback_events.jsonl` shape, including:
Timestamp columns store ISO 8601 UTC values with a `Z` suffix; raw source
timestamp text is preserved inside `event_json.source_time_text` when the
source used a non-canonical timestamp format.

- `event_key` and `canonical_key`
- `first_seen_at`, `request_at`, `resolved_at`, `video_loaded_at`,
  `actual_play_at`, and `actual_play_signal_at`
- `actual_play_method`, `actual_play_offset_seconds`, `observed_mid_play`,
  `elapsed_at_first_seen_seconds`, and `synced_play_at`
- parsed dance identity fields such as `dance_system_key` and
  `dance_external_id`
- source fields such as `source_type` and `source_display_name`
- `video_url`, `resolved_url`, `video_name`, `duration_seconds`,
  `duration_source`, and raw-line provenance
- completion fields such as `completion_status`, `completion_reason`,
  `completed_at`, `interrupted_at`, `played_seconds`, and
  `required_played_seconds`
- `last_updated_at`, `promoted_dance_event_id`,
  `promoted_playback_record_id`, and `promoted_at` for legacy compatibility

Normal watcher settlement now updates watcher-derived `playback_records`.
Pending records become accepted when conservative completion rules pass, or
non-counting `needs_attention` records when lifecycle or stop boundaries arrive
before acceptance.
Neither case should automatically become a normal delay/statistics event.
`duration_source` records where the runtime duration came from, such as a VRCX
payload or WannaDance queue JSON; it is runtime provenance only and is not added
to normal playback history.

## Relationship Diagram

```mermaid
erDiagram
    dance_systems ||--o{ dance_tracks : contains
    dance_tracks ||--o{ playback_records : evidenced_as
    dance_tracks ||--o{ dance_events : legacy_played_as
    dance_tracks ||--o| wannadance_songs : has_wanna_fields

    dance_tracks ||--o{ dance_track_music_links : maps_to
    music_tracks ||--o{ dance_track_music_links : represents

    vrcx_import_events }o--o| dance_systems : parsed_system
    vrcx_import_events }o--o| dance_tracks : parsed_track
```

## Query Paths

From a playback record to its dance-system entry:

```text
playback_records
  -> dance_tracks
  -> dance_systems
```

From an effectively accepted playback record to normal Insights/history:

```text
playback_records
  LEFT JOIN active manual_playback_decisions
  WHERE effective_playback_status = 'accepted'
```

From a WannaDance playback record to WannaDance cache fields:

```text
playback_records
  -> dance_tracks
  -> wannadance_songs
```

From a dance entry to the real music track:

```text
dance_tracks
  -> dance_track_music_links
  -> music_tracks
```

From a music track to every dance version:

```text
music_tracks
  -> dance_track_music_links
  -> dance_tracks
  -> dance_systems
```

## Deferred Tables

Provider matching and popularity should be modeled separately from the core
timeline:

- `music_provider_matches`: future mapping from `music_tracks` to NetEase,
  Kugou, Last.fm, Spotify, or other provider ids.
- `music_popularity_snapshots`: future time-series snapshots for popularity,
  comment counts, listeners, or similar changing metrics.

These tables should not block the current runtime model. The important boundary
is that provider data belongs to `music_tracks`, not to system-specific dance
entries or playback events.

## Rebuild And Migration Policy

The current implementation does not migrate legacy generated databases in
place. If a legacy `songs` table or `dance_events.song_id` path is detected,
the app asks for a rebuild.

Use:

```bash
uv run python main.py rebuild-data --archive-existing
```

The rebuild flow archives generated files such as:

- `data/dance_trail.sqlite3`
- `data/dance_trail.sqlite3-wal`
- `data/dance_trail.sqlite3-shm`
- `data/songs.csv`
- `data/wanna_songs.csv`
- `data/wanna_songs.json`

It preserves:

- `config/dance-trail.local.json`
- `data/queued_self/`
