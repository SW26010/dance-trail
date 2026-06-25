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
from dancing_log.playback_record_writer import (
    PROJECT_SOURCE_ROOT_KEY,
    PROJECT_SOURCE_ROOT_PATH,
    PlaybackRecordWrite,
    source_fingerprint,
    upsert_playback_record,
)
from dancing_log.time_utils import SQLITE_UTC_NOW, normalize_timestamp


SOURCE_SELF = "self"
SOURCE_OTHER = "other"
SOURCE_RANDOM = "random"
SOURCE_UNKNOWN = "unknown"

SOURCE_TYPE_PRECEDENCE = {
    "queued_self": 6,
    "recommend": 5,
    "self": 4,
    "other": 3,
    "random": 2,
    "unknown": 1,
}

SOURCE_TYPE_PRECEDENCE_SQL = """
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
    playback_records_changed: int = 0
    skipped_unsupported: int = 0

    @property
    def dance_events_changed(self) -> int:
        """Compatibility alias for pre-playback-record import callers."""
        return self.playback_records_changed


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
PYPY_SYSTEM_KEY = "pypydance"

WANNA_API_PATH = "/api/songs/play"
WANNA_CDN_FILE_RE = re.compile(r"^/files/[^/]+/(?P<song_id>\d+)-[^/]+\.mp4$", re.IGNORECASE)
PYPY_VIDEO_FILE_RE = re.compile(r"^/api/v1/videos/(?P<video_id>\d+)\.mp4$", re.IGNORECASE)


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

    if host == "api.pypy.dance" and path == "/video":
        raw_id = parse_qs(parsed.query).get("id", [None])[0]
        if raw_id and raw_id.isdigit():
            return DanceUrlParseResult(PYPY_SYSTEM_KEY, raw_id, "pypydance_api", "api_query_id")
        return DanceUrlParseResult(None, None, "pypydance_api", "missing_query_id")

    if "pypy" in host:
        match = PYPY_VIDEO_FILE_RE.match(parsed.path)
        if match:
            return DanceUrlParseResult(
                PYPY_SYSTEM_KEY,
                match.group("video_id"),
                "pypydance_api",
                "api_video_file_path",
            )
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
        playback_records_changed = 0
        skipped_unsupported = 0

        for row in rows:
            parsed = parse_dance_url(row["video_url"])
            if not _is_supported(parsed):
                skipped_unsupported += 1
                continue
            raw_created_at = row["created_at"]
            created_at = normalize_timestamp(raw_created_at)

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
                f"""
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
                    event_key,
                    imported_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {SQLITE_UTC_NOW})
                ON CONFLICT(event_key) DO UPDATE SET
                    parsed_system_id = excluded.parsed_system_id,
                    parsed_external_id = excluded.parsed_external_id,
                    parsed_dance_track_id = excluded.parsed_dance_track_id,
                    inferred_source = excluded.inferred_source,
                    confidence = excluded.confidence
                WHERE
                    """ + SOURCE_TYPE_PRECEDENCE_SQL.format(column="excluded.inferred_source") + """
                    > """ + SOURCE_TYPE_PRECEDENCE_SQL.format(column="vrcx_import_events.inferred_source") + """
                    OR (
                        """ + SOURCE_TYPE_PRECEDENCE_SQL.format(column="excluded.inferred_source") + """
                        = """ + SOURCE_TYPE_PRECEDENCE_SQL.format(column="vrcx_import_events.inferred_source") + """
                        AND excluded.confidence > vrcx_import_events.confidence
                    )
                """,
                (
                    row["vrcx_rowid"],
                    created_at,
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

            staging_row = app_conn.execute(
                """
                SELECT *
                FROM vrcx_import_events
                WHERE event_key = ?
                """,
                (event_key,),
            ).fetchone()
            source_identity = _vrcx_playback_source_identity(
                app_conn,
                event_key=event_key,
                staging_row_id=int(staging_row["id"]),
            )
            source_type, source_confidence = _playback_source_type_for_vrcx_write(
                app_conn,
                source_identity=source_identity,
                incoming_source_type=staging_row["inferred_source"],
                incoming_confidence=staging_row["confidence"],
            )
            write_result = upsert_playback_record(
                app_conn,
                PlaybackRecordWrite(
                    played_at=staging_row["created_at"],
                    original_played_at=raw_created_at,
                    dance_track_id=staging_row["parsed_dance_track_id"],
                    dance_system_key=parsed.system_key,
                    dance_external_id=staging_row["parsed_external_id"],
                    source_kind="vrcx_history",
                    source_root_key=source_identity["source_root_key"],
                    source_root_path=source_identity["source_root_path"],
                    source_table=source_identity["source_table"],
                    source_row_id=source_identity["source_row_id"],
                    source_event_key=source_identity["source_event_key"],
                    status_reason="vrcx_import",
                    source_priority=10,
                    confidence=source_confidence,
                    event_source="vrcx",
                    source_type=source_type,
                    source_display_name=staging_row["display_name"],
                    video_url=staging_row["video_url"],
                    video_name=staging_row["video_name"],
                    requester_display_name=staging_row["display_name"],
                    requester_user_id=staging_row["user_id"],
                    location=staging_row["location"],
                    provenance={
                        "vrcx_db_path": str(vrcx_path.resolve()),
                        "source_created_at": raw_created_at,
                        "vrcx_import_event": {
                            key: staging_row[key]
                            for key in staging_row.keys()
                        }
                    },
                ),
            )
            playback_records_changed += write_result.changed

        app_conn.commit()

    return ImportStats(
        scanned=stats.scanned,
        candidate_events=stats.candidate_events,
        staging_changed=staging_changed,
        playback_records_changed=playback_records_changed,
        skipped_unsupported=skipped_unsupported,
    )


def _is_supported(parsed: DanceUrlParseResult) -> bool:
    return bool(parsed.system_key and parsed.external_id)


def _playback_source_type_for_vrcx_write(
    conn: sqlite3.Connection,
    *,
    source_identity: dict[str, object],
    incoming_source_type: str | None,
    incoming_confidence: float | None,
) -> tuple[str | None, float | None]:
    """Keep VRCX reimports from downgrading stronger source_type decisions."""
    fingerprint = source_fingerprint(
        source_identity["source_root_key"],
        source_identity["source_table"],
        source_identity["source_row_id"],
        source_identity["source_event_key"],
    )
    existing = conn.execute(
        """
        SELECT request_type
        FROM playback_records
        WHERE evidence_key = ?
        """,
        (fingerprint,),
    ).fetchone()
    if existing is None:
        return incoming_source_type, incoming_confidence

    existing_type = existing["request_type"]
    existing_rank = _source_type_precedence(existing_type)
    incoming_rank = _source_type_precedence(incoming_source_type)
    if existing_rank > incoming_rank:
        return existing_type, incoming_confidence
    if existing_rank == incoming_rank and existing_type:
        return existing_type, incoming_confidence
    return incoming_source_type, incoming_confidence


def _source_type_precedence(source_type: str | None) -> int:
    return SOURCE_TYPE_PRECEDENCE.get((source_type or "").strip(), 0)


def _vrcx_playback_source_identity(
    conn: sqlite3.Connection,
    *,
    event_key: str,
    staging_row_id: int,
) -> dict[str, object]:
    existing = conn.execute(
        """
        SELECT
            pro.origin_root_key AS source_root_key,
            pro.origin_root_path AS source_root_path,
            pro.origin_table AS source_table,
            pro.origin_row_id AS source_row_id,
            pro.origin_event_key AS source_event_key
        FROM playback_records pr
        JOIN playback_record_origins pro
            ON pro.playback_record_id = pr.id
        WHERE pr.evidence_source = 'vrcx_history'
            AND pro.origin_event_key = ?
        ORDER BY
            CASE pro.origin_table WHEN 'dance_events' THEN 0 ELSE 1 END,
            pr.id
        LIMIT 1
        """,
        (event_key,),
    ).fetchone()
    if existing is not None:
        return dict(existing)

    legacy_event = conn.execute(
        "SELECT id FROM dance_events WHERE event_key = ?",
        (event_key,),
    ).fetchone()
    if legacy_event is not None:
        return {
            "source_root_key": PROJECT_SOURCE_ROOT_KEY,
            "source_root_path": PROJECT_SOURCE_ROOT_PATH,
            "source_table": "dance_events",
            "source_row_id": int(legacy_event["id"]),
            "source_event_key": event_key,
        }

    return {
        "source_root_key": PROJECT_SOURCE_ROOT_KEY,
        "source_root_path": PROJECT_SOURCE_ROOT_PATH,
        "source_table": "vrcx_import_events",
        "source_row_id": staging_row_id,
        "source_event_key": event_key,
    }


def _system_name(system_key: str | None) -> str:
    if system_key == WANNA_SYSTEM_KEY:
        return "WannaDance"
    if system_key == PYPY_SYSTEM_KEY:
        return "PyPyDance"
    return system_key or "Unknown"
