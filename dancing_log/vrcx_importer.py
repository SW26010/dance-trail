"""Import dance playback events from a local VRCX SQLite database."""

from dataclasses import dataclass
from pathlib import Path
import hashlib
import re
import sqlite3
from urllib.parse import parse_qs, urlparse

from dancing_log.storage import connect_db, sync_songs_from_csv


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
    skipped_without_song_id: int = 0


@dataclass(frozen=True)
class WannaUrlParseResult:
    song_id: int | None
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


def parse_wanna_url(video_url: str | None) -> WannaUrlParseResult:
    """Classify a Wanna Dance playback URL and extract its song id when possible."""
    if not video_url:
        return WannaUrlParseResult(None, "empty", "none")

    parsed = urlparse(video_url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()

    if host in WANNA_API_HOSTS and path == WANNA_API_PATH:
        raw_id = parse_qs(parsed.query).get("id", [None])[0]
        if raw_id and raw_id.isdigit():
            return WannaUrlParseResult(int(raw_id), "wanna_api", "api_query_id")

        match = re.search(r"[?&]id=(\d+)", video_url)
        if match:
            return WannaUrlParseResult(int(match.group(1)), "wanna_api", "api_query_id_fallback")

        return WannaUrlParseResult(None, "wanna_api", "missing_query_id")

    if host in WANNA_CDN_HOSTS:
        match = WANNA_CDN_FILE_RE.match(parsed.path)
        if match:
            return WannaUrlParseResult(int(match.group("song_id")), "wanna_cdn", "cdn_file_path")
        return WannaUrlParseResult(None, "wanna_cdn", "unrecognized_cdn_path")

    return WannaUrlParseResult(None, "other", "none")


def parse_wanna_song_id(video_url: str | None) -> int | None:
    """Extract the Wanna Dance song id from a recognized Wanna Dance URL."""
    return parse_wanna_url(video_url).song_id


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
        WHERE
            video_url LIKE '%/Api/Songs/play%'
            OR video_url LIKE '%play.udon.dance/files/%'
            OR video_url LIKE '%nya.xin.moe/files/%'
            OR video_url LIKE '%ud-play.kiva.moe/files/%'
            OR video_url LIKE '%ud-nya.kiva.moe/files/%'
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

    with sqlite3.connect(f"file:{vrcx_path}?mode=ro", uri=True) as vrcx_conn:
        vrcx_conn.row_factory = sqlite3.Row
        rows = _fetch_vrcx_rows(vrcx_conn, limit=limit)

    stats = ImportStats(scanned=len(rows), candidate_events=len(rows))
    if dry_run:
        skipped = sum(1 for row in rows if parse_wanna_song_id(row["video_url"]) is None)
        return ImportStats(
            scanned=stats.scanned,
            candidate_events=stats.candidate_events,
            skipped_without_song_id=skipped,
        )

    with connect_db(app_db_path) as app_conn:
        sync_songs_from_csv(app_conn)

        staging_changed = 0
        dance_events_changed = 0
        skipped_without_song_id = 0

        for row in rows:
            song_id = parse_wanna_song_id(row["video_url"])
            if song_id is None:
                skipped_without_song_id += 1
                continue

            source, confidence = infer_source(
                row["display_name"],
                row["user_id"],
                self_user_id=self_user_id,
                blank_requester_source=blank_requester_source,
            )
            event_key = _event_key(row)

            app_conn.execute(
                "INSERT OR IGNORE INTO songs (id) VALUES (?)",
                (song_id,),
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
                    parsed_song_id,
                    inferred_source,
                    confidence,
                    event_key
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_key) DO UPDATE SET
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
                    song_id,
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
                    song_id,
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
                    song_id,
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
        skipped_without_song_id=skipped_without_song_id,
    )
