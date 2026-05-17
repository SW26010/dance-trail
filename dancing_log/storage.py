"""SQLite storage for dancing-log.

SQLite is the primary local store. CSV should be treated as an import/export
artifact, not as runtime state.
"""

from pathlib import Path
import hashlib
import sqlite3


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_FILE = DATA_DIR / "dancing_log.sqlite3"


class ClosingConnection(sqlite3.Connection):
    """SQLite connection that closes when used as a context manager."""

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        suppress = super().__exit__(exc_type, exc_value, traceback)
        self.close()
        return suppress


def connect_db(path: Path | str | None = None) -> sqlite3.Connection:
    """Open the local app database and ensure the schema exists."""
    db_path = Path(path) if path is not None else DB_FILE
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, factory=ClosingConnection)
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
            note TEXT,
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
    _ensure_dance_event_columns(conn)
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


def _ensure_dance_event_columns(conn: sqlite3.Connection) -> None:
    """Add event columns for databases created before this schema."""
    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(dance_events)").fetchall()
    }
    if "note" not in existing:
        conn.execute("ALTER TABLE dance_events ADD COLUMN note TEXT")


def load_songs(path: Path | str | None = None) -> list[dict]:
    """Load songs from SQLite using the field names expected by recommendation code."""
    with connect_db(path) as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                name,
                artist,
                dancer,
                player_count,
                song_group AS "group",
                major,
                favorite,
                want_to_learn,
                netease_id,
                popularity,
                comment_count
            FROM songs
            ORDER BY id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_song(song_id: int, path: Path | str | None = None) -> dict | None:
    """Return one song row from SQLite, or None when the song is unknown."""
    with connect_db(path) as conn:
        row = conn.execute(
            """
            SELECT
                id,
                name,
                artist,
                dancer,
                player_count,
                song_group AS "group",
                major,
                favorite,
                want_to_learn,
                netease_id,
                popularity,
                comment_count
            FROM songs
            WHERE id = ?
            """,
            (song_id,),
        ).fetchone()
    return dict(row) if row else None


def load_dance_log(path: Path | str | None = None) -> list[dict]:
    """Load dance events from SQLite in the legacy record shape."""
    with connect_db(path) as conn:
        rows = conn.execute(
            """
            SELECT
                played_at AS timestamp,
                song_id,
                source,
                COALESCE(note, '') AS note
            FROM dance_events
            WHERE song_id IS NOT NULL
            ORDER BY played_at, id
            """
        ).fetchall()
    return [
        {
            "timestamp": row["timestamp"],
            "song_id": str(row["song_id"]),
            "source": row["source"],
            "note": row["note"],
        }
        for row in rows
    ]


def add_dance_event(
    *,
    song_id: int,
    source: str,
    played_at: str,
    note: str = "",
    event_source: str = "manual",
    confidence: float = 1.0,
    path: Path | str | None = None,
) -> str:
    """Insert a dance event into SQLite and return its event key."""
    with connect_db(path) as conn:
        conn.execute("INSERT OR IGNORE INTO songs (id) VALUES (?)", (song_id,))
        base_key = _event_key(event_source, played_at, song_id, source, note)
        event_key = _unique_event_key(conn, base_key)
        conn.execute(
            """
            INSERT INTO dance_events (
                played_at,
                song_id,
                source,
                confidence,
                event_source,
                event_key,
                note
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (played_at, song_id, source, confidence, event_source, event_key, note),
        )
        conn.commit()
        return event_key


def _event_key(*parts: object) -> str:
    return hashlib.sha256(
        "\x1f".join(str(part or "") for part in parts).encode("utf-8")
    ).hexdigest()


def _unique_event_key(conn: sqlite3.Connection, base_key: str) -> str:
    event_key = base_key
    suffix = 2
    while conn.execute(
        "SELECT 1 FROM dance_events WHERE event_key = ?",
        (event_key,),
    ).fetchone():
        event_key = _event_key(base_key, suffix)
        suffix += 1
    return event_key
