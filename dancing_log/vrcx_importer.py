"""Import dance playback events from a local VRCX SQLite database."""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import closing
from pathlib import Path
import hashlib
import re
import sqlite3
from urllib.parse import parse_qs, urlparse

from dancing_log.storage import (
    WANNA_SYSTEM_KEY,
    connect_db,
    ensure_dance_system,
    ensure_dance_track,
)


SOURCE_SELF = "self"
SOURCE_OTHER = "other"
SOURCE_RANDOM = "random"
SOURCE_UNKNOWN = "unknown"

SOURCE_PRIORITY_SQL = """
    CASE {column}
        WHEN 'queued_self' THEN 6
        WHEN 'recommend' THEN 5
        WHEN 'self' THEN 4
        WHEN 'other' THEN 3
        WHEN 'random' THEN 2
        WHEN 'unknown' THEN 1
        ELSE 0
    END
"""


@dataclass(frozen=True)
class ImportStats:
    scanned: int = 0
    candidate_events: int = 0
    staging_changed: int = 0
    dance_events_changed: int = 0
    skipped_unsupported: int = 0


@dataclass(frozen=True)
class DanceUrlParseResult:
    system_key: str | None
    external_id: str | None
    url_kind: str
    method: str


WANNA_API_HOSTS_DOCUMENTED = frozenset({
    "api.udon.dance",
})
WANNA_API_HOSTS_OBSERVED = frozenset({
    "api.wannadance.online",
    "139.196.46.195:51886",
})
WANNA_API_HOSTS_UPSTREAM = frozenset({
    "ud-orig.kiva.moe",
})
WANNA_API_HOSTS = (
    WANNA_API_HOSTS_DOCUMENTED
    | WANNA_API_HOSTS_OBSERVED
    | WANNA_API_HOSTS_UPSTREAM
)

WANNA_CDN_HOSTS_DOCUMENTED = frozenset({
    "play.udon.dance",
    "nya.xin.moe",
})
WANNA_CDN_HOSTS_UPSTREAM = frozenset({
    "ud-play.kiva.moe",
    "ud-nya.kiva.moe",
})
WANNA_CDN_HOSTS = WANNA_CDN_HOSTS_DOCUMENTED | WANNA_CDN_HOSTS_UPSTREAM

WANNA_API_PATH = "/api/songs/play"
WANNA_CDN_FILE_RE = re.compile(r"^/files/[^/]+/(?P<song_id>\d+)-[^/]+\.mp4$", re.IGNORECASE)


def parse_dance_url(video_url: str | None) -> DanceUrlParseResult:
    """Classify a playback URL and extract a supported dance-system id."""
    if not video_url:
        return DanceUrlParseResult(None, None, "empty", "none")

    parsed = urlparse(video_url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()

    if host in WANNA_API_HOSTS and path == WANNA_API_PATH:
        raw_id = parse_qs(parsed.query).get("id", [None])[0]
        if raw_id and raw_id.isdigit():
            return DanceUrlParseResult(WANNA_SYSTEM_KEY, raw_id, "wanna_api", "api_query_id")

        match = re.search(r"[?&]id=(\d+)", video_url)
        if match:
            return DanceUrlParseResult(
                WANNA_SYSTEM_KEY,
                match.group(1),
                "wanna_api",
                "api_query_id_fallback",
            )

        return DanceUrlParseResult(None, None, "wanna_api", "missing_query_id")

    if host in WANNA_CDN_HOSTS:
        match = WANNA_CDN_FILE_RE.match(parsed.path)
        if match:
            return DanceUrlParseResult(
                WANNA_SYSTEM_KEY,
                match.group("song_id"),
                "wanna_cdn",
                "cdn_file_path",
            )
        return DanceUrlParseResult(None, None, "wanna_cdn", "unrecognized_cdn_path")

    if "pypy" in host:
        return DanceUrlParseResult(None, None, "pypydance", "unsupported_system")
    if "dudu" in host:
        return DanceUrlParseResult(None, None, "dudu", "unsupported_system")
    return DanceUrlParseResult(None, None, "other", "unsupported")


def parse_wanna_song_id(video_url: str | None) -> int | None:
    """Extract a WannaDance song id from a supported WannaDance URL."""
    result = parse_dance_url(video_url)
    if result.system_key != WANNA_SYSTEM_KEY or result.external_id is None:
        return None
    return int(result.external_id)


def infer_source(
    display_name: str | None,
    user_id: str | None,
    self_user_id: str | None = None,
    blank_requester_source: str = SOURCE_RANDOM,
) -> tuple[str, float]:
    """Infer source semantics conservatively from VRCX requester fields."""
    normalized_user_id = (user_id or "").strip()
    normalized_self_id = (self_user_id or "").strip()
    normalized_name = (display_name or "").strip().lower()

    if normalized_name == "random":
        return SOURCE_RANDOM, 0.8
    if normalized_self_id and normalized_user_id == normalized_self_id:
        return SOURCE_SELF, 0.95
    if normalized_self_id and normalized_user_id:
        return SOURCE_OTHER, 0.9
    if not normalized_name and not normalized_user_id:
        if blank_requester_source == SOURCE_RANDOM:
            return SOURCE_RANDOM, 0.7
    return SOURCE_UNKNOWN, 0.5


def _event_key(row: sqlite3.Row) -> str:
    parts = [
        str(row["vrcx_rowid"]),
        str(row["created_at"] or ""),
        str(row["video_url"] or ""),
        str(row["display_name"] or ""),
        str(row["user_id"] or ""),
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _fetch_vrcx_rows(conn: sqlite3.Connection, limit: int | None = None) -> list[sqlite3.Row]:
    query = """
        SELECT
            rowid AS vrcx_rowid,
            created_at,
            video_url,
            video_name,
            video_id,
            location,
            display_name,
            user_id
        FROM gamelog_video_play
        WHERE video_url IS NOT NULL AND video_url != ''
        ORDER BY created_at
    """
    params: tuple[int, ...] = ()
    if limit is not None:
        query += " LIMIT ?"
        params = (limit,)
    return list(conn.execute(query, params))


def import_vrcx_database(
    vrcx_db_path: Path | str,
    app_db_path: Path | str | None = None,
    self_user_id: str | None = None,
    blank_requester_source: str = SOURCE_RANDOM,
    limit: int | None = None,
    dry_run: bool = False,
) -> ImportStats:
    """Import VRCX video play rows into the local dancing-log database."""
    if blank_requester_source not in {SOURCE_RANDOM, SOURCE_UNKNOWN}:
        raise ValueError("blank_requester_source must be 'random' or 'unknown'")

    vrcx_path = Path(vrcx_db_path)
    if not vrcx_path.exists():
        raise FileNotFoundError(f"VRCX database not found: {vrcx_path}")

    with closing(sqlite3.connect(f"file:{vrcx_path}?mode=ro", uri=True)) as vrcx_conn:
        vrcx_conn.row_factory = sqlite3.Row
        rows = _fetch_vrcx_rows(vrcx_conn, limit=limit)

    stats = ImportStats(scanned=len(rows), candidate_events=len(rows))
    if dry_run:
        skipped = sum(1 for row in rows if not _is_supported(parse_dance_url(row["video_url"])))
        return ImportStats(
            scanned=stats.scanned,
            candidate_events=stats.candidate_events,
            skipped_unsupported=skipped,
        )

    with connect_db(app_db_path) as app_conn:
        staging_changed = 0
        dance_events_changed = 0
        skipped_unsupported = 0

        for row in rows:
            parsed = parse_dance_url(row["video_url"])
            if not _is_supported(parsed):
                skipped_unsupported += 1
                continue

            source, confidence = infer_source(
                row["display_name"],
                row["user_id"],
                self_user_id=self_user_id,
                blank_requester_source=blank_requester_source,
            )
            event_key = _event_key(row)
            system_id = ensure_dance_system(app_conn, parsed.system_key, _system_name(parsed.system_key))
            dance_track_id = ensure_dance_track(app_conn, parsed.system_key, parsed.external_id)

            if parsed.system_key == WANNA_SYSTEM_KEY:
                app_conn.execute(
                    """
                    INSERT OR IGNORE INTO wannadance_songs (dance_track_id, wanna_id)
                    VALUES (?, ?)
                    """,
                    (dance_track_id, int(parsed.external_id)),
                )

            staging_cursor = app_conn.execute(
                """
                INSERT INTO vrcx_import_events (
                    vrcx_rowid,
                    created_at,
                    video_url,
                    video_name,
                    video_id,
                    location,
                    display_name,
                    user_id,
                    parsed_system_id,
                    parsed_external_id,
                    parsed_dance_track_id,
                    inferred_source,
                    confidence,
                    event_key
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_key) DO UPDATE SET
                    parsed_system_id = excluded.parsed_system_id,
                    parsed_external_id = excluded.parsed_external_id,
                    parsed_dance_track_id = excluded.parsed_dance_track_id,
                    inferred_source = excluded.inferred_source,
                    confidence = excluded.confidence
                WHERE
                    """ + SOURCE_PRIORITY_SQL.format(column="excluded.inferred_source") + """
                    > """ + SOURCE_PRIORITY_SQL.format(column="vrcx_import_events.inferred_source") + """
                    OR (
                        """ + SOURCE_PRIORITY_SQL.format(column="excluded.inferred_source") + """
                        = """ + SOURCE_PRIORITY_SQL.format(column="vrcx_import_events.inferred_source") + """
                        AND excluded.confidence > vrcx_import_events.confidence
                    )
                """,
                (
                    row["vrcx_rowid"],
                    row["created_at"],
                    row["video_url"],
                    row["video_name"],
                    row["video_id"],
                    row["location"],
                    row["display_name"],
                    row["user_id"],
                    system_id,
                    parsed.external_id,
                    dance_track_id,
                    source,
                    confidence,
                    event_key,
                ),
            )
            staging_changed += staging_cursor.rowcount

            event_cursor = app_conn.execute(
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
                    location
                )
                VALUES (?, ?, ?, ?, 'vrcx', ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_key) DO UPDATE SET
                    dance_track_id = excluded.dance_track_id,
                    source = excluded.source,
                    confidence = excluded.confidence
                WHERE
                    """ + SOURCE_PRIORITY_SQL.format(column="excluded.source") + """
                    > """ + SOURCE_PRIORITY_SQL.format(column="dance_events.source") + """
                    OR (
                        """ + SOURCE_PRIORITY_SQL.format(column="excluded.source") + """
                        = """ + SOURCE_PRIORITY_SQL.format(column="dance_events.source") + """
                        AND excluded.confidence > dance_events.confidence
                    )
                """,
                (
                    row["created_at"],
                    dance_track_id,
                    source,
                    confidence,
                    event_key,
                    row["video_url"],
                    row["video_name"],
                    row["display_name"],
                    row["user_id"],
                    row["location"],
                ),
            )
            dance_events_changed += event_cursor.rowcount

        app_conn.commit()

    return ImportStats(
        scanned=stats.scanned,
        candidate_events=stats.candidate_events,
        staging_changed=staging_changed,
        dance_events_changed=dance_events_changed,
        skipped_unsupported=skipped_unsupported,
    )


def _is_supported(parsed: DanceUrlParseResult) -> bool:
    return bool(parsed.system_key and parsed.external_id)


def _system_name(system_key: str | None) -> str:
    if system_key == WANNA_SYSTEM_KEY:
        return "WannaDance"
    return system_key or "Unknown"
