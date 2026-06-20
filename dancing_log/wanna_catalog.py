"""WannaDance catalog import and cache synchronization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import csv
import json
import sqlite3
import urllib.request

from dancing_log.app_paths import AppRuntimeConfig
from dancing_log.storage import (
    DATA_DIR,
    WANNA_SYSTEM_KEY,
    connect_db,
    ensure_dance_track,
    ensure_music_track,
    link_dance_track_to_music,
)


API_URL = "https://x.kiva.moe/api/v2/wanna/songs"
WANNA_JSON = DATA_DIR / "wanna_songs.json"
WANNA_CSV = DATA_DIR / "wanna_songs.csv"


@dataclass
class SyncStats:
    api_count: int
    cache_count: int
    db_before: int
    db_after: int
    inserted: int
    updated: int
    missing_in_cache: int
    used_api: bool


def fetch_wanna_api(url: str = API_URL, timeout: int = 60) -> dict:
    """Fetch the public WannaDance catalog API."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "dancing-log/0.1"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def extract_api_songs(data: dict) -> list[dict]:
    """Extract public songs from the WannaDance API response."""
    groups = data.get("data", {}).get("groups", [])
    songs: list[dict] = []
    seen_ids: set[int] = set()
    for group in groups:
        group_title = group.get("title", "")
        major = group.get("major", "")
        for entry in group.get("entries", []):
            if entry.get("disablePublic"):
                continue
            song_id = _to_int(entry.get("id"))
            if song_id is None or song_id in seen_ids:
                continue
            seen_ids.add(song_id)
            songs.append(
                {
                    "id": song_id,
                    "name": entry.get("name", ""),
                    "artist": entry.get("artist", ""),
                    "dancer": entry.get("dancer", ""),
                    "player_count": _to_int(entry.get("playerCount"), default=0),
                    "group": group_title,
                    "major": major,
                }
            )
    songs.sort(key=lambda song: song["id"])
    return songs


def load_cache_songs(cache_dir: Path | str | None) -> list[dict]:
    """Load useful metadata from a local wannadance-song cache directory."""
    if not cache_dir:
        return []
    root = Path(cache_dir)
    if not root.exists():
        return []

    songs: list[dict] = []
    for metadata_path in sorted(root.glob("*/metadata.json"), key=_metadata_sort_key):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        song_id = _to_int(metadata.get("id"))
        if song_id is None:
            song_id = _to_int(metadata_path.parent.name)
        if song_id is None:
            continue

        video_path = metadata_path.parent / "video.mp4"
        download_path = metadata_path.parent / "download.txt"
        songs.append(
            {
                "id": song_id,
                "cache_category": _to_int(metadata.get("category")),
                "cache_title": metadata.get("title", ""),
                "cache_title_spell": metadata.get("titleSpell", ""),
                "cache_player_index": _to_int(metadata.get("playerIndex")),
                "cache_volume": _to_float(metadata.get("volume")),
                "cache_start_seconds": _to_float(metadata.get("start")),
                "cache_end_seconds": _to_float(metadata.get("end")),
                "cache_flip": _to_bool_int(metadata.get("flip")),
                "cache_skip_random": _to_bool_int(metadata.get("skipRandom")),
                "cache_checksum": metadata.get("checksum", ""),
                "cache_url": metadata.get("url", ""),
                "cache_url_for_quest": metadata.get("urlForQuest", ""),
                "local_video_path": str(video_path) if video_path.exists() else "",
                "local_metadata_path": str(metadata_path),
                "local_download_path": str(download_path) if download_path.exists() else "",
                "cache_updated_at": _mtime_iso(metadata_path),
            }
        )
    return songs


def merge_catalog(api_songs: list[dict], cache_songs: list[dict]) -> list[dict]:
    """Merge API catalog rows with local cache metadata by WannaDance song id."""
    merged: dict[int, dict] = {}
    for song in cache_songs:
        song_id = song["id"]
        merged[song_id] = {
            "id": song_id,
            "name": song.get("cache_title", ""),
            "artist": "",
            "dancer": "",
            "player_count": None,
            "group": "",
            "major": "",
            **song,
        }
    for song in api_songs:
        song_id = song["id"]
        row = merged.setdefault(song_id, {"id": song_id})
        row.update(song)
    return sorted(merged.values(), key=lambda song: song["id"])


def sync_wanna_catalog(
    *,
    db_path: Path | str | None = None,
    cache_dir: Path | str | None = None,
    use_api: bool = True,
    write_files: bool = False,
) -> SyncStats:
    """Synchronize WannaDance catalog data into SQLite and optional artifacts."""
    config = AppRuntimeConfig.load(migrate_legacy=True)
    resolved_cache_dir = config.optional_path("wanna_cache_dir", override=cache_dir)
    resolved_db_path = config.path("app_db", override=db_path)

    api_songs: list[dict] = []
    used_api = False
    if use_api:
        try:
            api_songs = extract_api_songs(fetch_wanna_api())
            used_api = True
        except Exception:
            api_songs = []

    cache_songs = load_cache_songs(resolved_cache_dir)
    merged = merge_catalog(api_songs, cache_songs)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if write_files:
        _write_catalog_files(merged, api_songs)

    with connect_db(resolved_db_path) as conn:
        db_before = _wanna_track_count(conn)
        existing_ids = _wanna_external_ids(conn)
        changed = upsert_catalog(conn, merged)
        db_after = _wanna_track_count(conn)
    merged_ids = {str(song["id"]) for song in merged}
    cache_ids = {str(song["id"]) for song in cache_songs}
    inserted = len(merged_ids - existing_ids)
    return SyncStats(
        api_count=len(api_songs),
        cache_count=len(cache_songs),
        db_before=db_before,
        db_after=db_after,
        inserted=inserted,
        updated=changed - inserted,
        missing_in_cache=len(merged_ids - cache_ids),
        used_api=used_api,
    )


def upsert_catalog(conn: sqlite3.Connection, songs: list[dict]) -> int:
    """Upsert merged catalog rows into dance_tracks and wannadance_songs."""
    changed = 0
    for song in songs:
        title = song.get("name") or song.get("cache_title") or ""
        artist = song.get("artist") or ""
        dance_track_id = ensure_dance_track(
            conn,
            WANNA_SYSTEM_KEY,
            song["id"],
            {
                "title": title,
                "artist": artist,
                "dancer": song.get("dancer"),
                "player_count": song.get("player_count"),
                "group": song.get("group"),
                "major": song.get("major"),
            },
        )
        conn.execute(
            """
            INSERT INTO wannadance_songs (
                dance_track_id,
                wanna_id,
                cache_category,
                cache_title,
                cache_title_spell,
                cache_player_index,
                cache_volume,
                cache_start_seconds,
                cache_end_seconds,
                cache_flip,
                cache_skip_random,
                cache_checksum,
                cache_url,
                cache_url_for_quest,
                local_video_path,
                local_metadata_path,
                local_download_path,
                cache_updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dance_track_id) DO UPDATE SET
                wanna_id = excluded.wanna_id,
                cache_category = excluded.cache_category,
                cache_title = excluded.cache_title,
                cache_title_spell = excluded.cache_title_spell,
                cache_player_index = excluded.cache_player_index,
                cache_volume = excluded.cache_volume,
                cache_start_seconds = excluded.cache_start_seconds,
                cache_end_seconds = excluded.cache_end_seconds,
                cache_flip = excluded.cache_flip,
                cache_skip_random = excluded.cache_skip_random,
                cache_checksum = excluded.cache_checksum,
                cache_url = excluded.cache_url,
                cache_url_for_quest = excluded.cache_url_for_quest,
                local_video_path = excluded.local_video_path,
                local_metadata_path = excluded.local_metadata_path,
                local_download_path = excluded.local_download_path,
                cache_updated_at = excluded.cache_updated_at
            """,
            (
                dance_track_id,
                song["id"],
                song.get("cache_category"),
                song.get("cache_title"),
                song.get("cache_title_spell"),
                song.get("cache_player_index"),
                song.get("cache_volume"),
                song.get("cache_start_seconds"),
                song.get("cache_end_seconds"),
                song.get("cache_flip"),
                song.get("cache_skip_random"),
                song.get("cache_checksum"),
                song.get("cache_url"),
                song.get("cache_url_for_quest"),
                song.get("local_video_path"),
                song.get("local_metadata_path"),
                song.get("local_download_path"),
                song.get("cache_updated_at"),
            ),
        )

        if title.strip() and artist.strip():
            music_track_id = ensure_music_track(conn, title, artist)
            link_dance_track_to_music(
                conn,
                dance_track_id,
                music_track_id,
                confidence=0.85,
                match_method="title_artist_auto",
            )
        changed += 1
    conn.commit()
    return changed


def _wanna_track_count(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*)
        FROM dance_tracks dt
        JOIN dance_systems ds ON ds.id = dt.system_id
        WHERE ds.key = ?
        """,
        (WANNA_SYSTEM_KEY,),
    ).fetchone()
    return int(row[0])


def _wanna_external_ids(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        """
        SELECT dt.external_id
        FROM dance_tracks dt
        JOIN dance_systems ds ON ds.id = dt.system_id
        WHERE ds.key = ?
        """,
        (WANNA_SYSTEM_KEY,),
    ).fetchall()
    return {row["external_id"] for row in rows}


def _write_catalog_files(merged: list[dict], api_songs: list[dict]) -> None:
    with open(WANNA_JSON, "w", encoding="utf-8") as f:
        json.dump(api_songs or merged, f, ensure_ascii=False, indent=2)

    public_fields = ["id", "name", "artist", "dancer", "player_count", "group", "major"]
    with open(WANNA_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=public_fields)
        writer.writeheader()
        writer.writerows({field: song.get(field, "") for field in public_fields} for song in merged)


def _metadata_sort_key(path: Path) -> tuple[int, str]:
    return (_to_int(path.parent.name, default=10**12) or 10**12, path.parent.name)


def _mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).astimezone().isoformat()


def _to_int(value: object, default: int | None = None) -> int | None:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_bool_int(value: object) -> int | None:
    if value is None:
        return None
    return 1 if bool(value) else 0
