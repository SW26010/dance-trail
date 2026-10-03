"""Read-only local snapshots for Web UI and report surfaces."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
import re
import sqlite3

from dance_trail.app_paths import AppRuntimeConfig
from dance_trail.local_dance_day import LocalDanceDayBoundary
from dance_trail.models import generate_daily_playlist
from dance_trail.playback_evidence import (
    count_playback_records,
    read_accepted_playback_history,
    read_attention_counts,
    read_daily_playback_rows,
    read_recent_playback_records,
    read_source_distribution,
    read_top_tracks,
    read_timeline_playback_rows,
)
from dance_trail.playback_projection import EFFECTIVE_PLAYBACK_ACCEPTED


@dataclass(frozen=True)
class DailyDance:
    """One dance event rendered for a local-day report."""

    event_id: int
    played_at_local: datetime
    display_name: str
    review_status: str = EFFECTIVE_PLAYBACK_ACCEPTED
    default_playback_status: str = EFFECTIVE_PLAYBACK_ACCEPTED
    manual_decision_status: str | None = None
    dance_system_key: str | None = None
    dance_system_name: str | None = None
    source_type: str | None = None
    source_display_name: str | None = None
    requester_display_name: str | None = None
    requester_user_id: str | None = None


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
                    **count_playback_records(conn),
                    "legacy_dance_events": _table_count(conn, "dance_events"),
                    "legacy_live_playback_events": _table_count(conn, "live_playback_events"),
                    "legacy_vrcx_import_events": _table_count(conn, "vrcx_import_events"),
                }
                summary["recent"] = read_recent_playback_records(conn)
        except sqlite3.Error as exc:
            summary["database_error"] = str(exc)
        return summary

    def timeline(self, query: dict[str, list[str]]) -> dict:
        config = self.config
        dance_day_boundary = config.dance_day_boundary
        current_dance_date = dance_day_boundary.current_date()
        requested_date = _query_optional_value(query, "date")
        selected_date = requested_date or current_dance_date.isoformat()
        source = _timeline_source(_query_value(query, "source", "all"))
        db_path = config.app_db_path
        if not db_path.exists():
            return {
                "date": selected_date,
                "source": source,
                "records": [],
                "database_exists": False,
            }

        target: date | None
        if requested_date is None:
            target = None
        else:
            try:
                target = date.fromisoformat(requested_date)
                selected_date = target.isoformat()
            except ValueError:
                target = current_dance_date
                selected_date = target.isoformat()

        if target is None:
            selected_date = current_dance_date.isoformat()

        try:
            with _open_readonly_db(db_path) as conn:
                rows = read_timeline_playback_rows(conn, source=source)
                if target is None:
                    target = (
                        _latest_playback_local_date(rows, dance_day_boundary)
                        or current_dance_date
                    )
                    selected_date = target.isoformat()
                dances = _daily_dances_from_rows(
                    rows,
                    target,
                    dance_day_boundary=dance_day_boundary,
                )
        except sqlite3.Error as exc:
            target = current_dance_date
            selected_date = target.isoformat()
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
                    "review_status": dance.review_status,
                    "default_playback_status": dance.default_playback_status,
                    "manual_decision_status": dance.manual_decision_status,
                    "effective_playback_status": dance.review_status,
                    "has_manual_decision": dance.manual_decision_status is not None,
                    "dance_system_key": dance.dance_system_key,
                    "dance_system_name": dance.dance_system_name,
                    "source_type": dance.source_type,
                    "source_display_name": dance.source_display_name,
                    "requester_display_name": dance.requester_display_name,
                    "requester_user_id": dance.requester_user_id,
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
        config = self.config
        db_path = config.app_db_path
        if not db_path.exists():
            return {
                "database_exists": False,
                "source_distribution": [],
                "top_tracks": [],
                "attention_counts": {"needs_attention": 0, "catalog_attention": 0},
                "recommendations": [],
            }
        try:
            with _open_readonly_db(db_path) as conn:
                source_distribution = _source_distribution(conn)
                top_tracks = _top_tracks(conn)
                tracks = _readonly_dance_tracks(conn)
                dance_log = _readonly_dance_log(conn)
                attention_counts = read_attention_counts(conn)
            recommendations = generate_daily_playlist(
                tracks,
                dance_log,
                count=10,
                target_date=config.dance_day_boundary.current_date(),
            )
        except (sqlite3.Error, ValueError) as exc:
            return {
                "database_exists": True,
                "source_distribution": [],
                "top_tracks": [],
                "attention_counts": {"needs_attention": 0, "catalog_attention": 0},
                "recommendations": [],
                "error": str(exc),
            }
        return {
            "database_exists": True,
            "source_distribution": source_distribution,
            "top_tracks": top_tracks,
            "attention_counts": attention_counts,
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
    dance_day_boundary: LocalDanceDayBoundary | None = None,
) -> list[DailyDance]:
    """Return accepted playback records for the requested Local Dance Day."""
    db_path = _daily_db_path(path)
    if not db_path.exists():
        return []
    with _open_readonly_db(db_path) as conn:
        rows = _readonly_daily_accepted_rows(conn)
    return _daily_dances_from_rows(
        rows,
        target_date,
        dance_day_boundary=dance_day_boundary,
    )


def load_daily_live_dances(
    target_date: date,
    path: Path | str | None = None,
    *,
    dance_day_boundary: LocalDanceDayBoundary | None = None,
) -> list[DailyDance]:
    """Return live playback rows observed on the requested Local Dance Day."""
    db_path = _daily_db_path(path)
    if not db_path.exists():
        return []
    with _open_readonly_db(db_path) as conn:
        rows = _readonly_daily_live_rows(conn)
    return _daily_dances_from_rows(
        rows,
        target_date,
        dance_day_boundary=dance_day_boundary,
    )


def format_daily_dance_line(dance: DailyDance) -> str:
    """Format one daily report row as `HH:MM:SS song id song name`."""
    return f"{dance.played_at_local:%H:%M:%S} {dance.display_name}"


def parse_played_at_local(
    value: str | None,
    *,
    dance_day_boundary: LocalDanceDayBoundary | None = None,
) -> datetime | None:
    """Parse supported stored timestamps and return local time."""
    text = (value or "").strip()
    if not text:
        return None
    boundary = dance_day_boundary or LocalDanceDayBoundary.from_config({})
    try:
        return boundary.local_datetime(text)
    except ValueError:
        return None


def _daily_db_path(path: Path | str | None) -> Path:
    if path is not None:
        return Path(path)
    return AppRuntimeConfig.load().app_db_path


def _query_value(query: dict[str, list[str]], key: str, default: str) -> str:
    values = query.get(key) or [default]
    return str(values[0] if values else default)


def _query_optional_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key) or []
    if not values:
        return None
    value = str(values[0]).strip()
    return value or None


def _timeline_source(value: str) -> str:
    return "live" if value == "live" else "all"


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
    return read_accepted_playback_history(conn)


def _latest_playback_local_date(
    rows: list[dict],
    dance_day_boundary: LocalDanceDayBoundary,
) -> date | None:
    latest: datetime | None = None
    for row in rows:
        played_at_local = parse_played_at_local(
            row.get("played_at"),
            dance_day_boundary=dance_day_boundary,
        )
        if played_at_local is None:
            continue
        if latest is None or played_at_local.astimezone(UTC) > latest.astimezone(UTC):
            latest = played_at_local
    return dance_day_boundary.date_for(latest) if latest is not None else None


def _readonly_daily_accepted_rows(conn: sqlite3.Connection) -> list[dict]:
    return read_daily_playback_rows(conn, source="accepted")


def _readonly_daily_live_rows(conn: sqlite3.Connection) -> list[dict]:
    return read_daily_playback_rows(conn, source="live")


def _daily_dances_from_rows(
    rows: list[dict],
    target_date: date,
    *,
    dance_day_boundary: LocalDanceDayBoundary | None = None,
) -> list[DailyDance]:
    boundary = dance_day_boundary or LocalDanceDayBoundary.from_config({})
    target_range = boundary.range_for(target_date)
    dances = []
    for row in rows:
        played_at_local = parse_played_at_local(
            row.get("played_at"),
            dance_day_boundary=boundary,
        )
        if played_at_local is None or not target_range.contains(played_at_local):
            continue
        review_status = str(
            row.get("effective_playback_status")
            or row.get("review_status")
            or EFFECTIVE_PLAYBACK_ACCEPTED
        )
        default_status = str(row.get("default_playback_status") or review_status)
        manual_status = row.get("manual_decision_status")
        dances.append(
            DailyDance(
                event_id=int(row["event_id"]),
                played_at_local=played_at_local,
                display_name=_format_display_name(row),
                review_status=review_status,
                default_playback_status=default_status,
                manual_decision_status=str(manual_status) if manual_status is not None else None,
                dance_system_key=_optional_text(row.get("dance_system_key")),
                dance_system_name=_optional_text(row.get("dance_system_name")),
                source_type=_optional_text(row.get("source_type")),
                source_display_name=_optional_text(row.get("source_display_name")),
                requester_display_name=_optional_text(row.get("requester_display_name")),
                requester_user_id=_optional_text(row.get("requester_user_id")),
            )
        )
    dances.sort(key=lambda dance: (dance.played_at_local.astimezone(UTC), dance.event_id))
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


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _has_external_id_prefix(value: str, external_id: str) -> bool:
    if not external_id:
        return False
    return bool(re.match(rf"^{re.escape(external_id)}(?:\.|\s)", value))
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
    return read_source_distribution(conn)


def _top_tracks(conn: sqlite3.Connection) -> list[dict]:
    return read_top_tracks(conn)
