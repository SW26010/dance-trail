"""Read-only local snapshots for Web UI and report surfaces."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from pathlib import Path
import re
import sqlite3

from dancing_log.app_paths import AppRuntimeConfig
from dancing_log.models import generate_daily_playlist


REVIEW_STATUS_UNCHECKED = "unchecked"
REVIEW_STATUS_USER_CONFIRMED = "user confirmed"
REVIEW_STATUS_USER_DISCARDED = "user discarded"


@dataclass(frozen=True)
class DailyDance:
    """One dance event rendered for a local-day report."""

    event_id: int
    played_at_local: datetime
    display_name: str


@dataclass(frozen=True)
class LocalReadSnapshots:
    """Read model for local, read-only user-facing snapshots."""

    app_root: Path | str | None = None

    @property
    def config(self) -> AppRuntimeConfig:
        return AppRuntimeConfig.load(app_root=self.app_root)

    def home(self, *, config_warnings: list[str] | None = None) -> dict:
        config = self.config
        db_path = config.app_db_path
        summary = {
            "database_path": str(db_path),
            "database_exists": db_path.exists(),
            "counts": {},
            "recent": [],
            "current_live": None,
            "config_warnings": list(config_warnings or []),
        }
        if not db_path.exists():
            return summary

        try:
            with _open_readonly_db(db_path) as conn:
                summary["counts"] = {
                    "dance_tracks": _table_count(conn, "dance_tracks"),
                    "dance_events": _table_count(conn, "dance_events"),
                    "live_playback_events": _table_count(conn, "live_playback_events"),
                    "vrcx_import_events": _table_count(conn, "vrcx_import_events"),
                }
                summary["recent"] = _recent_official_events(conn)
                summary["current_live"] = _current_live_event(conn)
        except sqlite3.Error as exc:
            summary["database_error"] = str(exc)
        return summary

    def timeline(self, query: dict[str, list[str]]) -> dict:
        selected_date = _query_value(query, "date", date.today().isoformat())
        source = _timeline_source(_query_value(query, "source", "official"))
        db_path = self.config.app_db_path
        if not db_path.exists():
            return {
                "date": selected_date,
                "source": source,
                "records": [],
                "database_exists": False,
            }

        try:
            target = date.fromisoformat(selected_date)
        except ValueError:
            target = date.today()
            selected_date = target.isoformat()

        try:
            with _open_readonly_db(db_path) as conn:
                dances = _readonly_daily_dances(conn, target, source)
        except sqlite3.Error as exc:
            return {
                "date": selected_date,
                "source": source,
                "records": [],
                "database_exists": True,
                "error": str(exc),
            }
        return {
            "date": selected_date,
            "source": source,
            "records": [
                {
                    "id": dance.event_id,
                    "time": dance.played_at_local.strftime("%H:%M:%S"),
                    "played_at": dance.played_at_local.isoformat(),
                    "display": dance.display_name,
                    "line": format_daily_dance_line(dance),
                    "review_status": _timeline_review_status(source),
                }
                for dance in dances
            ],
            "database_exists": True,
        }

    def catalog(self, query: dict[str, list[str]]) -> dict:
        db_path = self.config.app_db_path
        search = _query_value(query, "q", "").strip().casefold()
        try:
            limit = min(max(int(_query_value(query, "limit", "100")), 1), 500)
        except ValueError:
            limit = 100
        if not db_path.exists():
            return {"tracks": [], "database_exists": False, "query": search}
        try:
            with _open_readonly_db(db_path) as conn:
                tracks = _catalog_tracks(conn, search, limit)
        except sqlite3.Error as exc:
            return {"tracks": [], "database_exists": True, "query": search, "error": str(exc)}
        return {"tracks": tracks[:limit], "database_exists": True, "query": search}

    def lists(self) -> dict:
        config = self.config
        queued_dir = config.queued_self_dir
        manifests = []
        if queued_dir.exists() and queued_dir.is_dir():
            for path in sorted(queued_dir.glob("*"))[:100]:
                if not path.is_file():
                    continue
                if path.suffix.lower() not in {"", ".md", ".txt"}:
                    continue
                try:
                    lines = [
                        line.strip()
                        for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
                        if line.strip()
                    ][:6]
                    size = path.stat().st_size
                except OSError:
                    lines = []
                    size = 0
                manifests.append(
                    {
                        "name": path.name,
                        "path": str(path),
                        "size": size,
                        "preview": lines,
                    }
                )
        return {
            "queued_self_dir": str(queued_dir),
            "exists": queued_dir.exists(),
            "manifests": manifests,
        }

    def insights(self) -> dict:
        db_path = self.config.app_db_path
        if not db_path.exists():
            return {
                "database_exists": False,
                "source_distribution": [],
                "top_tracks": [],
                "recommendations": [],
            }
        try:
            with _open_readonly_db(db_path) as conn:
                source_distribution = _source_distribution(conn)
                top_tracks = _top_tracks(conn)
                tracks = _readonly_dance_tracks(conn)
                dance_log = _readonly_dance_log(conn)
            recommendations = generate_daily_playlist(
                tracks,
                dance_log,
                count=10,
            )
        except (sqlite3.Error, ValueError) as exc:
            return {
                "database_exists": True,
                "source_distribution": [],
                "top_tracks": [],
                "recommendations": [],
                "error": str(exc),
            }
        return {
            "database_exists": True,
            "source_distribution": source_distribution,
            "top_tracks": top_tracks,
            "recommendations": recommendations,
        }


def load_home_snapshot(
    app_root: Path | str | None = None,
    *,
    config_warnings: list[str] | None = None,
) -> dict:
    return LocalReadSnapshots(app_root).home(config_warnings=config_warnings)


def load_timeline_snapshot(
    app_root: Path | str | None,
    query: dict[str, list[str]],
) -> dict:
    return LocalReadSnapshots(app_root).timeline(query)


def load_catalog_snapshot(
    app_root: Path | str | None,
    query: dict[str, list[str]],
) -> dict:
    return LocalReadSnapshots(app_root).catalog(query)


def load_lists_snapshot(app_root: Path | str | None = None) -> dict:
    return LocalReadSnapshots(app_root).lists()


def load_insights_snapshot(app_root: Path | str | None = None) -> dict:
    return LocalReadSnapshots(app_root).insights()


def load_daily_dances(
    target_date: date,
    path: Path | str | None = None,
    *,
    local_tz: tzinfo | None = None,
) -> list[DailyDance]:
    """Return official dance events that fall on the requested local date."""
    db_path = _daily_db_path(path)
    if not db_path.exists():
        return []
    with _open_readonly_db(db_path) as conn:
        rows = _readonly_daily_official_rows(conn)
    return _daily_dances_from_rows(rows, target_date, local_tz=local_tz)


def load_daily_live_dances(
    target_date: date,
    path: Path | str | None = None,
    *,
    local_tz: tzinfo | None = None,
) -> list[DailyDance]:
    """Return live playback rows observed on the requested local date."""
    db_path = _daily_db_path(path)
    if not db_path.exists():
        return []
    with _open_readonly_db(db_path) as conn:
        rows = _readonly_daily_live_rows(conn)
    return _daily_dances_from_rows(rows, target_date, local_tz=local_tz)


def format_daily_dance_line(dance: DailyDance) -> str:
    """Format one daily report row as `HH:MM:SS song id song name`."""
    return f"{dance.played_at_local:%H:%M:%S} {dance.display_name}"


def parse_played_at_local(
    value: str | None,
    *,
    local_tz: tzinfo | None = None,
) -> datetime | None:
    """Parse supported stored timestamps and return local time."""
    text = (value or "").strip()
    if not text:
        return None

    iso_text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(iso_text)
    except ValueError:
        parsed = _parse_vrc_local_timestamp(text)
    if parsed is None:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(local_tz)
    return parsed


def _daily_db_path(path: Path | str | None) -> Path:
    if path is not None:
        return Path(path)
    return AppRuntimeConfig.load().app_db_path


def _query_value(query: dict[str, list[str]], key: str, default: str) -> str:
    values = query.get(key) or [default]
    return str(values[0] if values else default)


def _timeline_source(value: str) -> str:
    return "live" if value == "live" else "official"


def _timeline_review_status(source: str) -> str:
    return REVIEW_STATUS_UNCHECKED if source == "live" else REVIEW_STATUS_USER_CONFIRMED


@contextmanager
def _open_readonly_db(path: Path):
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _table_count(conn: sqlite3.Connection, table: str) -> int:
    if not _table_exists(conn, table):
        return 0
    row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    return int(row["count"])


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _tables_exist(conn: sqlite3.Connection, *tables: str) -> bool:
    return all(_table_exists(conn, table) for table in tables)


def _catalog_tracks(conn: sqlite3.Connection, search: str, limit: int) -> list[dict]:
    if not _tables_exist(conn, "dance_tracks", "dance_systems"):
        return []
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
    tracks = [dict(row) for row in rows]
    if search:
        tracks = [
            track
            for track in tracks
            if search in " ".join(
                str(track.get(key) or "")
                for key in ("system_key", "external_id", "title", "artist", "dancer", "group", "major")
            ).casefold()
        ]
    return tracks[:limit]


def _readonly_dance_tracks(conn: sqlite3.Connection) -> list[dict]:
    if not _tables_exist(conn, "dance_tracks", "dance_systems"):
        return []
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


def _readonly_dance_log(conn: sqlite3.Connection) -> list[dict]:
    if not _tables_exist(conn, "dance_events", "dance_tracks", "dance_systems"):
        return []
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


def _readonly_daily_dances(conn: sqlite3.Connection, target_date: date, source: str) -> list[DailyDance]:
    rows = _readonly_daily_live_rows(conn) if source == "live" else _readonly_daily_official_rows(conn)
    return _daily_dances_from_rows(rows, target_date)


def _readonly_daily_official_rows(conn: sqlite3.Connection) -> list[dict]:
    if not _tables_exist(conn, "dance_events", "dance_tracks"):
        return []
    rows = conn.execute(
        """
        SELECT
            de.id AS event_id,
            de.played_at,
            de.video_name,
            dt.external_id,
            dt.title,
            dt.artist,
            dt.dancer,
            dt.group_name,
            dt.major
        FROM dance_events de
        JOIN dance_tracks dt ON dt.id = de.dance_track_id
        ORDER BY de.played_at, de.id
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _readonly_daily_live_rows(conn: sqlite3.Connection) -> list[dict]:
    if not _table_exists(conn, "live_playback_events"):
        return []
    rows = conn.execute(
        """
        SELECT
            id AS event_id,
            actual_play_at AS played_at,
            video_name,
            dance_external_id AS external_id,
            NULL AS title,
            NULL AS artist,
            NULL AS dancer,
            NULL AS group_name,
            NULL AS major
        FROM live_playback_events
        WHERE actual_play_at IS NOT NULL
            AND dance_external_id IS NOT NULL
            AND COALESCE(observed_mid_play, 0) = 0
        ORDER BY actual_play_at, id
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _daily_dances_from_rows(
    rows: list[dict],
    target_date: date,
    *,
    local_tz: tzinfo | None = None,
) -> list[DailyDance]:
    dances = []
    for row in rows:
        played_at_local = parse_played_at_local(row.get("played_at"), local_tz=local_tz)
        if played_at_local is None or played_at_local.date() != target_date:
            continue
        dances.append(
            DailyDance(
                event_id=int(row["event_id"]),
                played_at_local=played_at_local,
                display_name=_format_display_name(row),
            )
        )
    dances.sort(key=lambda dance: (dance.played_at_local, dance.event_id))
    return dances


def _format_display_name(row: dict) -> str:
    external_id = str(row.get("external_id") or "").strip()
    video_name = str(row.get("video_name") or "").strip()
    if video_name and _has_external_id_prefix(video_name, external_id):
        return video_name

    title = str(row.get("title") or video_name or "(untitled)").strip()
    artist = str(row.get("artist") or "").strip()
    variant = str(
        row.get("dancer")
        or row.get("group_name")
        or row.get("major")
        or ""
    ).strip()

    display = title
    if artist:
        display = f"{display} - {artist}"
    if variant:
        display = f"{display} | {variant}"
    if external_id:
        return f"{external_id}. {display}"
    return display


def _has_external_id_prefix(value: str, external_id: str) -> bool:
    if not external_id:
        return False
    return bool(re.match(rf"^{re.escape(external_id)}(?:\.|\s)", value))


def _parse_vrc_local_timestamp(value: str) -> datetime | None:
    for fmt in ("%Y.%m.%d %H:%M:%S.%f", "%Y.%m.%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def _recent_official_events(conn: sqlite3.Connection) -> list[dict]:
    if not _tables_exist(conn, "dance_events", "dance_tracks"):
        return []
    rows = conn.execute(
        """
        SELECT
            de.id,
            de.played_at,
            de.source,
            de.video_name,
            dt.external_id,
            dt.title,
            dt.artist,
            dt.dancer
        FROM dance_events de
        LEFT JOIN dance_tracks dt ON dt.id = de.dance_track_id
        ORDER BY de.played_at DESC, de.id DESC
        LIMIT 8
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _current_live_event(conn: sqlite3.Connection) -> dict | None:
    if not _table_exists(conn, "live_playback_events"):
        return None
    row = conn.execute(
        """
        SELECT *
        FROM live_playback_events
        ORDER BY COALESCE(actual_play_at, first_seen_at, last_updated_at) DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    return dict(row) if row else None


def _source_distribution(conn: sqlite3.Connection) -> list[dict]:
    if not _table_exists(conn, "dance_events"):
        return []
    rows = conn.execute(
        """
        SELECT source, COUNT(*) AS count
        FROM dance_events
        GROUP BY source
        ORDER BY count DESC, source
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _top_tracks(conn: sqlite3.Connection) -> list[dict]:
    if not _tables_exist(conn, "dance_events", "dance_tracks"):
        return []
    rows = conn.execute(
        """
        SELECT
            dt.external_id,
            dt.title,
            dt.artist,
            COUNT(*) AS count
        FROM dance_events de
        JOIN dance_tracks dt ON dt.id = de.dance_track_id
        GROUP BY dt.id
        ORDER BY count DESC, MAX(de.played_at) DESC
        LIMIT 10
        """
    ).fetchall()
    return [dict(row) for row in rows]
