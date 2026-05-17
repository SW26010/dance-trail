"""SQLite storage for dancing-log.

SQLite is the primary local store. CSV should be treated as an import/export
artifact, not as runtime state.
"""

from __future__ import annotations

from pathlib import Path
import hashlib
import re
import sqlite3
import unicodedata


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_FILE = DATA_DIR / "dancing_log.sqlite3"
WANNA_SYSTEM_KEY = "wannadance"
WANNA_SYSTEM_NAME = "WannaDance"


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
    """Create the current multi-system dance-track schema."""
    _assert_not_legacy_schema(conn)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS dance_systems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS dance_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            system_id INTEGER NOT NULL,
            external_id TEXT NOT NULL,
            title TEXT,
            artist TEXT,
            dancer TEXT,
            player_count INTEGER,
            group_name TEXT,
            major TEXT,
            favorite INTEGER NOT NULL DEFAULT 0,
            want_to_learn INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(system_id) REFERENCES dance_systems(id),
            UNIQUE(system_id, external_id)
        );

        CREATE TABLE IF NOT EXISTS wannadance_songs (
            dance_track_id INTEGER PRIMARY KEY,
            wanna_id INTEGER NOT NULL UNIQUE,
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
            cache_updated_at TEXT,
            FOREIGN KEY(dance_track_id) REFERENCES dance_tracks(id)
        );

        CREATE TABLE IF NOT EXISTS music_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            artist TEXT,
            normalized_title TEXT NOT NULL,
            normalized_artist TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(normalized_title, normalized_artist)
        );

        CREATE TABLE IF NOT EXISTS dance_track_music_links (
            dance_track_id INTEGER NOT NULL,
            music_track_id INTEGER NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0,
            match_method TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY(dance_track_id, music_track_id),
            FOREIGN KEY(dance_track_id) REFERENCES dance_tracks(id),
            FOREIGN KEY(music_track_id) REFERENCES music_tracks(id)
        );

        CREATE TABLE IF NOT EXISTS dance_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            played_at TEXT NOT NULL,
            dance_track_id INTEGER,
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
            FOREIGN KEY(dance_track_id) REFERENCES dance_tracks(id)
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
            parsed_system_id INTEGER,
            parsed_external_id TEXT,
            parsed_dance_track_id INTEGER,
            inferred_source TEXT NOT NULL DEFAULT 'unknown',
            confidence REAL NOT NULL DEFAULT 0.5,
            event_key TEXT NOT NULL UNIQUE,
            imported_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(parsed_system_id) REFERENCES dance_systems(id),
            FOREIGN KEY(parsed_dance_track_id) REFERENCES dance_tracks(id)
        );

        CREATE INDEX IF NOT EXISTS idx_dance_tracks_system_external
            ON dance_tracks(system_id, external_id);
        CREATE INDEX IF NOT EXISTS idx_dance_events_played_at
            ON dance_events(played_at);
        CREATE INDEX IF NOT EXISTS idx_dance_events_dance_track_id
            ON dance_events(dance_track_id);
        CREATE INDEX IF NOT EXISTS idx_vrcx_import_events_track
            ON vrcx_import_events(parsed_dance_track_id);
        """
    )
    ensure_dance_system(conn, WANNA_SYSTEM_KEY, WANNA_SYSTEM_NAME)
    conn.commit()


def _assert_not_legacy_schema(conn: sqlite3.Connection) -> None:
    table_names = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    if "songs" in table_names:
        raise RuntimeError(
            "Legacy database schema detected. Run "
            "`uv run python main.py rebuild-data --archive-existing` "
            "to archive old data and create the new schema."
        )
    if "dance_events" in table_names:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(dance_events)").fetchall()
        }
        if "song_id" in columns and "dance_track_id" not in columns:
            raise RuntimeError(
                "Legacy dance_events schema detected. Run "
                "`uv run python main.py rebuild-data --archive-existing` first."
            )


def ensure_dance_system(conn: sqlite3.Connection, key: str, name: str) -> int:
    """Create or return a dance system row."""
    normalized_key = key.strip().lower()
    if not normalized_key:
        raise ValueError("system key must not be empty")
    display_name = name.strip() or normalized_key
    conn.execute(
        """
        INSERT INTO dance_systems (key, name)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET
            name = excluded.name
        """,
        (normalized_key, display_name),
    )
    row = conn.execute(
        "SELECT id FROM dance_systems WHERE key = ?",
        (normalized_key,),
    ).fetchone()
    return int(row["id"])


def ensure_dance_track(
    conn: sqlite3.Connection,
    system_key: str,
    external_id: object,
    metadata: dict | None = None,
) -> int:
    """Create or return a dance track row for a system-specific external id."""
    system_id = ensure_dance_system(conn, system_key, _system_display_name(system_key))
    external_id_text = _external_id_text(external_id)
    metadata = metadata or {}
    conn.execute(
        """
        INSERT INTO dance_tracks (
            system_id,
            external_id,
            title,
            artist,
            dancer,
            player_count,
            group_name,
            major
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(system_id, external_id) DO UPDATE SET
            title = COALESCE(NULLIF(excluded.title, ''), dance_tracks.title),
            artist = COALESCE(NULLIF(excluded.artist, ''), dance_tracks.artist),
            dancer = COALESCE(NULLIF(excluded.dancer, ''), dance_tracks.dancer),
            player_count = COALESCE(excluded.player_count, dance_tracks.player_count),
            group_name = COALESCE(NULLIF(excluded.group_name, ''), dance_tracks.group_name),
            major = COALESCE(NULLIF(excluded.major, ''), dance_tracks.major),
            updated_at = datetime('now')
        """,
        (
            system_id,
            external_id_text,
            metadata.get("title") or metadata.get("name"),
            metadata.get("artist"),
            metadata.get("dancer"),
            metadata.get("player_count"),
            metadata.get("group") or metadata.get("group_name"),
            metadata.get("major"),
        ),
    )
    row = conn.execute(
        """
        SELECT id
        FROM dance_tracks
        WHERE system_id = ? AND external_id = ?
        """,
        (system_id, external_id_text),
    ).fetchone()
    return int(row["id"])


def get_dance_track(
    system_key: str,
    external_id: object,
    path: Path | str | None = None,
) -> dict | None:
    """Return one dance track by system key and external id."""
    with connect_db(path) as conn:
        return _get_dance_track(conn, system_key, external_id)


def _get_dance_track(
    conn: sqlite3.Connection,
    system_key: str,
    external_id: object,
) -> dict | None:
    row = conn.execute(
        """
        SELECT
            dt.id,
            ds.key AS system_key,
            ds.name AS system_name,
            dt.external_id,
            dt.title,
            dt.artist,
            dt.dancer,
            dt.player_count,
            dt.group_name AS "group",
            dt.major,
            dt.favorite,
            dt.want_to_learn
        FROM dance_tracks dt
        JOIN dance_systems ds ON ds.id = dt.system_id
        WHERE ds.key = ? AND dt.external_id = ?
        """,
        (system_key.strip().lower(), _external_id_text(external_id)),
    ).fetchone()
    return dict(row) if row else None


def load_dance_tracks(path: Path | str | None = None) -> list[dict]:
    """Load dance tracks in the shape expected by recommendation code."""
    with connect_db(path) as conn:
        rows = conn.execute(
            """
            SELECT
                dt.id,
                ds.key AS system_key,
                ds.name AS system_name,
                dt.external_id,
                dt.title,
                dt.artist,
                dt.dancer,
                dt.player_count,
                dt.group_name AS "group",
                dt.major,
                dt.favorite,
                dt.want_to_learn
            FROM dance_tracks dt
            JOIN dance_systems ds ON ds.id = dt.system_id
            ORDER BY ds.key, CAST(dt.external_id AS INTEGER), dt.external_id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def load_dance_log(path: Path | str | None = None) -> list[dict]:
    """Load dance events in the recommendation/runtime record shape."""
    with connect_db(path) as conn:
        rows = conn.execute(
            """
            SELECT
                de.played_at AS timestamp,
                de.dance_track_id,
                ds.key AS system_key,
                dt.external_id,
                de.source,
                COALESCE(de.note, '') AS note
            FROM dance_events de
            JOIN dance_tracks dt ON dt.id = de.dance_track_id
            JOIN dance_systems ds ON ds.id = dt.system_id
            WHERE de.dance_track_id IS NOT NULL
            ORDER BY de.played_at, de.id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def add_dance_event(
    *,
    system_key: str,
    external_id: object,
    source: str,
    played_at: str,
    note: str = "",
    event_source: str = "manual",
    confidence: float = 1.0,
    video_url: str | None = None,
    video_name: str | None = None,
    requester_display_name: str | None = None,
    requester_user_id: str | None = None,
    location: str | None = None,
    path: Path | str | None = None,
) -> str:
    """Insert a dance event into SQLite and return its event key."""
    with connect_db(path) as conn:
        dance_track_id = ensure_dance_track(conn, system_key, external_id)
        system_external = f"{system_key.strip().lower()}:{_external_id_text(external_id)}"
        base_key = _event_key(event_source, played_at, system_external, source, note)
        event_key = _unique_event_key(conn, base_key)
        conn.execute(
            """
            INSERT INTO dance_events (
                played_at,
                dance_track_id,
                source,
                confidence,
                event_source,
                event_key,
                video_url,
                video_name,
                requester_display_name,
                requester_user_id,
                location,
                note
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                played_at,
                dance_track_id,
                source,
                confidence,
                event_source,
                event_key,
                video_url,
                video_name,
                requester_display_name,
                requester_user_id,
                location,
                note,
            ),
        )
        conn.commit()
        return event_key


def ensure_music_track(conn: sqlite3.Connection, title: str, artist: str | None) -> int:
    """Create or return a canonical music track row."""
    normalized_title = normalize_music_text(title)
    normalized_artist = normalize_music_text(artist or "")
    if not normalized_title:
        raise ValueError("music title must not be empty")
    conn.execute(
        """
        INSERT INTO music_tracks (
            title,
            artist,
            normalized_title,
            normalized_artist
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT(normalized_title, normalized_artist) DO UPDATE SET
            title = COALESCE(NULLIF(excluded.title, ''), music_tracks.title),
            artist = COALESCE(NULLIF(excluded.artist, ''), music_tracks.artist),
            updated_at = datetime('now')
        """,
        (title, artist or "", normalized_title, normalized_artist),
    )
    row = conn.execute(
        """
        SELECT id
        FROM music_tracks
        WHERE normalized_title = ? AND normalized_artist = ?
        """,
        (normalized_title, normalized_artist),
    ).fetchone()
    return int(row["id"])


def link_dance_track_to_music(
    conn: sqlite3.Connection,
    dance_track_id: int,
    music_track_id: int,
    *,
    confidence: float = 0.85,
    match_method: str = "title_artist_auto",
) -> None:
    """Create or update a dance-track to music-track link."""
    conn.execute(
        """
        INSERT INTO dance_track_music_links (
            dance_track_id,
            music_track_id,
            confidence,
            match_method
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT(dance_track_id, music_track_id) DO UPDATE SET
            confidence = excluded.confidence,
            match_method = excluded.match_method,
            updated_at = datetime('now')
        """,
        (dance_track_id, music_track_id, confidence, match_method),
    )


def normalize_music_text(value: str) -> str:
    """Normalize text for conservative title/artist matching."""
    normalized = unicodedata.normalize("NFKC", value or "")
    normalized = normalized.casefold()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _system_display_name(system_key: str) -> str:
    if system_key.strip().lower() == WANNA_SYSTEM_KEY:
        return WANNA_SYSTEM_NAME
    return system_key.strip()


def _external_id_text(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("external id must not be empty")
    return text


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
