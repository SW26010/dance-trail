"""Import dance playback events from a local VRCX SQLite database."""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import closing
from pathlib import Path
import hashlib
import re
import sqlite3
from typing import TypedDict
from urllib.parse import parse_qs, urlparse

from dancing_log.storage import (
    DUDU_SYSTEM_KEY,
    WANNA_SYSTEM_KEY,
    connect_db,
    ensure_dance_system,
    ensure_dance_track,
)
from dancing_log.playback_evidence import PLAYBACK_STATUS_ACCEPTED
from dancing_log.playback_request_type import (
    REQUEST_TYPE_PRECEDENCE,
    REQUEST_TYPE_PRECEDENCE_SQL,
)
from dancing_log.playback_record_writer import (
    PROJECT_SOURCE_ROOT_KEY,
    PROJECT_SOURCE_ROOT_PATH,
    PlaybackRecordOriginWrite,
    PlaybackRecordWrite,
    origin_key,
    playback_evidence_key,
    upsert_evidence_record,
)
from dancing_log.time_utils import SQLITE_UTC_NOW, normalize_timestamp


class PlaybackSourceIdentity(TypedDict):
    source_root_key: str
    source_root_path: str
    source_table: str
    source_row_id: int
    source_event_key: str


SOURCE_SELF = "self"
SOURCE_OTHER = "other"
SOURCE_RANDOM = "random"
SOURCE_UNKNOWN = "unknown"

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
DUDU_API_HOSTS = frozenset({
    "api.dudufit.dance",
})
DUDU_CDN_HOSTS = frozenset({
    "api-ddfd.imkiva.com",
    "global-cdn.dudufit.dance",
})

WANNA_API_PATH = "/api/songs/play"
WANNA_CDN_FILE_RE = re.compile(r"^/files/[^/]+/(?P<song_id>\d+)-[^/]+\.mp4$", re.IGNORECASE)
PYPY_VIDEO_FILE_RE = re.compile(r"^/api/v1/videos/(?P<video_id>\d+)\.mp4$", re.IGNORECASE)
DUDU_API_VIDEO_RE = re.compile(r"^/api/v1/videos/(?P<video_id>\d+)$", re.IGNORECASE)
DUDU_CDN_VIDEO_RE = re.compile(r"^/videos/(?P<video_id>\d+)-[^/]+\.mp4$", re.IGNORECASE)
DUDU_WEB_VIDEO_RE = re.compile(
    r"^/(?:[a-z]{2}(?:-[a-z]{2})?/)?videos/(?P<video_id>\d+)/?$",
    re.IGNORECASE,
)


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

    if host in DUDU_API_HOSTS:
        match = DUDU_API_VIDEO_RE.match(parsed.path)
        if match:
            return DanceUrlParseResult(
                DUDU_SYSTEM_KEY,
                match.group("video_id"),
                "dudu",
                "api_video_path",
            )
        return DanceUrlParseResult(None, None, "dudu", "missing_video_id")

    if host in DUDU_CDN_HOSTS:
        match = DUDU_CDN_VIDEO_RE.match(parsed.path)
        if match:
            return DanceUrlParseResult(
                DUDU_SYSTEM_KEY,
                match.group("video_id"),
                "dudu",
                "cdn_file_path",
            )
        return DanceUrlParseResult(None, None, "dudu", "unrecognized_cdn_path")

    if host == "www.dudufit.dance":
        match = DUDU_WEB_VIDEO_RE.match(parsed.path)
        if match:
            return DanceUrlParseResult(
                DUDU_SYSTEM_KEY,
                match.group("video_id"),
                "dudu",
                "web_video_path",
            )
        return DanceUrlParseResult(None, None, "dudu", "missing_video_id")

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


def _requester_fields_for_import(
    row: sqlite3.Row,
) -> tuple[str | None, str | None]:
    return _text_or_none(row["display_name"]), _text_or_none(row["user_id"])


def _event_key(row: sqlite3.Row) -> str:
    parts = [
        str(row["vrcx_rowid"]),
        str(row["created_at"] or ""),
        str(row["video_url"] or ""),
        str(row["display_name"] or ""),
        str(row["user_id"] or ""),
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _text_or_none(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


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
            system_key = parsed.system_key
            external_id = parsed.external_id
            assert system_key is not None
            assert external_id is not None
            raw_created_at = row["created_at"]
            created_at = normalize_timestamp(raw_created_at)
            display_name, user_id = _requester_fields_for_import(row)

            source, confidence = infer_source(
                display_name,
                user_id,
                self_user_id=self_user_id,
                blank_requester_source=blank_requester_source,
            )
            event_key = _event_key(row)
            system_id = ensure_dance_system(app_conn, system_key, _system_name(system_key))
            dance_track_id = ensure_dance_track(app_conn, system_key, external_id)

            if system_key == WANNA_SYSTEM_KEY:
                app_conn.execute(
                    """
                    INSERT OR IGNORE INTO wannadance_songs (dance_track_id, wanna_id)
                    VALUES (?, ?)
                    """,
                    (dance_track_id, int(external_id)),
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
                    """ + REQUEST_TYPE_PRECEDENCE_SQL.format(column="excluded.inferred_source") + """
                    > """ + REQUEST_TYPE_PRECEDENCE_SQL.format(column="vrcx_import_events.inferred_source") + """
                    OR (
                        """ + REQUEST_TYPE_PRECEDENCE_SQL.format(column="excluded.inferred_source") + """
                        = """ + REQUEST_TYPE_PRECEDENCE_SQL.format(column="vrcx_import_events.inferred_source") + """
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
                    display_name,
                    user_id,
                    system_id,
                    external_id,
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
            request_type, request_confidence = _playback_request_type_for_vrcx_write(
                app_conn,
                source_identity=source_identity,
                incoming_request_type=staging_row["inferred_source"],
                incoming_confidence=staging_row["confidence"],
            )
            write_result = upsert_evidence_record(
                app_conn,
                PlaybackRecordWrite(
                    evidence_key=playback_evidence_key(
                        str(source_identity["source_root_key"]),
                        str(source_identity["source_table"]),
                        source_identity["source_row_id"],
                        source_identity["source_event_key"],
                    ),
                    evidence_source="vrcx_history",
                    played_at=staging_row["created_at"],
                    dance_track_id=staging_row["parsed_dance_track_id"],
                    dance_system_key=system_key,
                    dance_external_id=staging_row["parsed_external_id"],
                    request_type=request_type,
                    default_acceptance_status=PLAYBACK_STATUS_ACCEPTED,
                    video_url=staging_row["video_url"],
                    video_name=staging_row["video_name"],
                    requester_display_name=staging_row["display_name"],
                    requester_user_id=staging_row["user_id"],
                    origins=(
                        PlaybackRecordOriginWrite(
                            origin_key=origin_key(
                                str(source_identity["source_root_key"]),
                                str(source_identity["source_table"]),
                                source_identity["source_row_id"],
                                source_identity["source_event_key"],
                            ),
                            origin_source="vrcx_database",
                            origin_root_key=str(source_identity["source_root_key"]),
                            origin_root_path=str(source_identity["source_root_path"]),
                            origin_table=str(source_identity["source_table"]),
                            origin_row_id=int(source_identity["source_row_id"]),
                            origin_event_key=str(source_identity["source_event_key"]),
                            origin_json={
                                "original_played_at": raw_created_at,
                                "vrcx_location": staging_row["location"],
                                "source_display_name": staging_row["display_name"],
                                "legacy_status_reason": "vrcx_import",
                                "legacy_source_priority": 10,
                                "legacy_confidence": request_confidence,
                                "legacy_catalog_status": "existing",
                                "vrcx_db_path": str(vrcx_path.resolve()),
                                "source_created_at": raw_created_at,
                                "vrcx_import_event": {
                                    key: staging_row[key]
                                    for key in staging_row.keys()
                                },
                            },
                        ),
                    ),
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


def _playback_request_type_for_vrcx_write(
    conn: sqlite3.Connection,
    *,
    source_identity: PlaybackSourceIdentity,
    incoming_request_type: str | None,
    incoming_confidence: float | None,
) -> tuple[str | None, float | None]:
    """Keep VRCX reimports from downgrading stronger request_type decisions."""
    fingerprint = playback_evidence_key(
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
        return incoming_request_type, incoming_confidence

    existing_request_type = existing["request_type"]
    existing_rank = _request_type_precedence(existing_request_type)
    incoming_rank = _request_type_precedence(incoming_request_type)
    if existing_rank > incoming_rank:
        return existing_request_type, incoming_confidence
    if existing_rank == incoming_rank and existing_request_type:
        return existing_request_type, incoming_confidence
    return incoming_request_type, incoming_confidence


def _request_type_precedence(request_type: str | None) -> int:
    return REQUEST_TYPE_PRECEDENCE.get((request_type or "").strip(), 0)


def _vrcx_playback_source_identity(
    conn: sqlite3.Connection,
    *,
    event_key: str,
    staging_row_id: int,
) -> PlaybackSourceIdentity:
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
        return {
            "source_root_key": str(existing["source_root_key"]),
            "source_root_path": str(existing["source_root_path"]),
            "source_table": str(existing["source_table"]),
            "source_row_id": int(existing["source_row_id"]),
            "source_event_key": str(existing["source_event_key"]),
        }

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
    if system_key == DUDU_SYSTEM_KEY:
        return "DuDu FitDance"
    return system_key or "Unknown"
