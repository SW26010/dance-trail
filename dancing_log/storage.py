"""SQLite storage for dancing-log.

CSV remains supported for the early CLI commands, while SQLite becomes the
durable event store used by imports and future live capture.
"""

from pathlib import Path
import csv
import sqlite3


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_FILE = DATA_DIR / "dancing_log.sqlite3"
SONGS_CSV_FILE = DATA_DIR / "songs.csv"


def connect_db(path: Path | str | None = None) -> sqlite3.Connection:
    """Open the local app database and ensure the schema exists."""
    db_path = Path(path) if path is not None else DB_FILE
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create the first SQLite schema used by imported playback events."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS songs (
            id INTEGER PRIMARY KEY,
            name TEXT,
            artist TEXT,
            dancer TEXT,
            player_count INTEGER,
            song_group TEXT,
            major TEXT,
            favorite INTEGER NOT NULL DEFAULT 0,
            want_to_learn INTEGER NOT NULL DEFAULT 0,
            netease_id INTEGER,
            popularity REAL,
            comment_count INTEGER,
            cache_category INTEGER,
            cache_title TEXT,
            cache_title_spell TEXT,
            cache_player_index INTEGER,
            cache_volume REAL,
            cache_start_seconds REAL,
            cache_end_seconds REAL,
            cache_flip INTEGER,
            cache_skip_random INTEGER,
            cache_checksum TEXT,
            cache_url TEXT,
            cache_url_for_quest TEXT,
            local_video_path TEXT,
            local_metadata_path TEXT,
            local_download_path TEXT,
            cache_updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS dance_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            played_at TEXT NOT NULL,
            song_id INTEGER,
            source TEXT NOT NULL DEFAULT 'unknown',
            confidence REAL NOT NULL DEFAULT 0.5,
            event_source TEXT NOT NULL,
            event_key TEXT NOT NULL UNIQUE,
            video_url TEXT,
            video_name TEXT,
            requester_display_name TEXT,
            requester_user_id TEXT,
            location TEXT,
            recording_id INTEGER,
            recording_offset_seconds REAL,
            imported_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(song_id) REFERENCES songs(id)
        );

        CREATE TABLE IF NOT EXISTS vrcx_import_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vrcx_rowid INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            video_url TEXT,
            video_name TEXT,
            video_id TEXT,
            location TEXT,
            display_name TEXT,
            user_id TEXT,
            parsed_song_id INTEGER,
            inferred_source TEXT NOT NULL DEFAULT 'unknown',
            confidence REAL NOT NULL DEFAULT 0.5,
            event_key TEXT NOT NULL UNIQUE,
            imported_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_dance_events_played_at
            ON dance_events(played_at);
        CREATE INDEX IF NOT EXISTS idx_dance_events_song_id
            ON dance_events(song_id);
        CREATE INDEX IF NOT EXISTS idx_vrcx_import_events_song_id
            ON vrcx_import_events(parsed_song_id);
        """
    )
    _ensure_song_cache_columns(conn)
    conn.commit()


def _ensure_song_cache_columns(conn: sqlite3.Connection) -> None:
    """Add cache metadata columns for databases created before this schema."""
    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(songs)").fetchall()
    }
    columns = {
        "cache_category": "INTEGER",
        "cache_title": "TEXT",
        "cache_title_spell": "TEXT",
        "cache_player_index": "INTEGER",
        "cache_volume": "REAL",
        "cache_start_seconds": "REAL",
        "cache_end_seconds": "REAL",
        "cache_flip": "INTEGER",
        "cache_skip_random": "INTEGER",
        "cache_checksum": "TEXT",
        "cache_url": "TEXT",
        "cache_url_for_quest": "TEXT",
        "local_video_path": "TEXT",
        "local_metadata_path": "TEXT",
        "local_download_path": "TEXT",
        "cache_updated_at": "TEXT",
    }
    for name, column_type in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE songs ADD COLUMN {name} {column_type}")


def sync_songs_from_csv(
    conn: sqlite3.Connection,
    csv_path: Path | str | None = None,
) -> int:
    """Upsert local songs.csv rows into SQLite when the CSV master exists."""
    path = Path(csv_path) if csv_path is not None else SONGS_CSV_FILE
    if not path.exists():
        return 0

    synced = 0
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            raw_id = row.get("id")
            if not raw_id:
                continue
            song_id = _to_int(raw_id)
            if song_id is None:
                continue
            conn.execute(
                """
                INSERT INTO songs (
                    id,
                    name,
                    artist,
                    dancer,
                    player_count,
                    song_group,
                    major,
                    favorite,
                    want_to_learn,
                    netease_id,
                    popularity,
                    comment_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    artist = excluded.artist,
                    dancer = excluded.dancer,
                    player_count = excluded.player_count,
                    song_group = excluded.song_group,
                    major = excluded.major,
                    favorite = excluded.favorite,
                    want_to_learn = excluded.want_to_learn,
                    netease_id = excluded.netease_id,
                    popularity = excluded.popularity,
                    comment_count = excluded.comment_count
                """,
                (
                    song_id,
                    row.get("name"),
                    row.get("artist"),
                    row.get("dancer"),
                    _to_int(row.get("player_count")),
                    row.get("group"),
                    row.get("major"),
                    _to_int(row.get("favorite"), default=0),
                    _to_int(row.get("want_to_learn"), default=0),
                    _to_int(row.get("netease_id")),
                    _to_float(row.get("popularity")),
                    _to_int(row.get("comment_count")),
                ),
            )
            synced += 1
    conn.commit()
    return synced


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
