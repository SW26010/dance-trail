"""One-time legacy database merge/cleanup described by ADR 0004.

The source databases are read-only inputs. The target database receives
playback_records plus minimal catalog rows needed by those records.
This script is an audit artifact for the current old databases, not a
productized merge command or supported import entrypoint.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import traceback
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dancing_log.playback_evidence import init_playback_records_schema  # noqa: E402
from dancing_log.storage import ensure_dance_system, ensure_dance_track  # noqa: E402
from dancing_log.wanna_catalog import load_cache_songs  # noqa: E402


LOCAL_TZ = timezone(timedelta(hours=8))
UTC = timezone.utc
DEFAULT_TARGET_DB = PROJECT_ROOT / "data" / "dancing_log.sqlite3"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "data" / "legacy_playback_cleanup_reports"
DEFAULT_WANNA_CACHE = Path(r"path/to/catalog-snapshot")
NEAR_MATCH_SECONDS = 600


@dataclass(frozen=True)
class LegacyRoot:
    key: str
    root: Path
    db_path: Path


@dataclass
class PlaybackCandidate:
    source_kind: str
    source_root_key: str
    source_root_path: str
    source_table: str
    source_row_id: int
    source_event_key: str | None
    source_fingerprint: str
    played_at: str
    original_played_at: str
    dance_system_key: str
    dance_external_id: str
    dance_track_id: int | None
    playback_status: str
    counts_in_history: int
    status_reason: str
    source_priority: int
    confidence: float | None
    event_source: str | None
    source_type: str | None
    source_display_name: str | None
    video_url: str | None
    video_name: str | None
    requester_display_name: str | None
    requester_user_id: str | None
    location: str | None
    completion_status: str | None
    completion_reason: str | None
    catalog_status: str = "unresolved"
    catalog_attention: int = 0
    provenance: dict[str, Any] | None = None


def main() -> int:
    args = parse_args()
    target_db = args.target_db.resolve()
    report_dir = args.report_dir.resolve()
    if args.execute and args.no_report:
        raise SystemExit("--no-report is only allowed with --preview-only")
    if not args.no_report:
        report_dir.mkdir(parents=True, exist_ok=True)
    roots = default_roots(target_db)

    started_at = utc_now_text()
    batch_id = datetime.now(UTC).strftime("legacy-cleanup-%Y%m%d-%H%M%S")
    report_base = report_dir / batch_id
    backup_path: Path | None = None
    summary: dict[str, Any] = {
        "batch_id": batch_id,
        "started_at": started_at,
        "mode": "execute" if args.execute else "preview",
        "target_db": str(target_db),
        "source_roots": {root.key: str(root.root) for root in roots},
        "wanna_cache_dir": str(args.wanna_cache_dir),
        "time_normalization": "UTC ISO-8601 with Z; VRC log timestamps treated as Asia/Shanghai local time",
    }

    try:
        preview = build_preview(roots, target_db, args.wanna_cache_dir)
        summary.update(preview["summary"])

        if args.execute:
            backup_path = backup_database(target_db, report_dir, batch_id)
            summary["backup_path"] = str(backup_path)
            execution = execute_cleanup(
                target_db=target_db,
                candidates=preview["candidates"],
                wanna_cache=preview["wanna_cache"],
                batch_id=batch_id,
            )
            summary.update(execution)
            summary["status"] = "success"
        else:
            summary["status"] = "preview"

        summary["finished_at"] = utc_now_text()
        if not args.no_report:
            write_reports(report_base, summary)
        print_summary(summary, report_base)
        return 0
    except Exception as exc:  # pragma: no cover - failure path is operational.
        summary["status"] = "failed"
        summary["finished_at"] = utc_now_text()
        summary["error"] = str(exc)
        summary["traceback"] = traceback.format_exc()
        if backup_path is not None:
            summary["backup_path"] = str(backup_path)
        if not args.no_report:
            write_reports(report_base, summary)
        print_summary(summary, report_base)
        return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preview-only", action="store_true", help="Read sources and print a preview only")
    mode.add_argument("--execute", action="store_true", help="Write the target database")
    parser.add_argument("--target-db", type=Path, default=DEFAULT_TARGET_DB)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--wanna-cache-dir", type=Path, default=DEFAULT_WANNA_CACHE)
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Do not write report files; intended for preview-only safety checks",
    )
    return parser.parse_args()


def default_roots(target_db: Path) -> list[LegacyRoot]:
    return [
        LegacyRoot("project", PROJECT_ROOT, target_db),
        LegacyRoot(
            "portable_v0.1.0",
            Path(r"path/to/portable-snapshot"),
            Path(r"path/to/portable-snapshot/data/dancing_log.sqlite3"),
        ),
        LegacyRoot(
            "watch_vrc_log",
            Path(r"path/to/watcher-snapshot-a"),
            Path(r"path/to/watcher-snapshot-a/data/dancing_log.sqlite3"),
        ),
        LegacyRoot(
            "watch_vrc_log_v2",
            Path(r"path/to/watcher-snapshot-b"),
            Path(r"path/to/watcher-snapshot-b/data/dancing_log.sqlite3"),
        ),
    ]


def build_preview(
    roots: list[LegacyRoot],
    target_db: Path,
    wanna_cache_dir: Path,
) -> dict[str, Any]:
    source_summary = inspect_sources(roots)
    target_catalog = load_target_catalog(target_db)
    wanna_cache = load_wanna_cache(wanna_cache_dir)
    vrcx_rows = fetch_project_vrcx_rows(target_db)
    live_rows = [row for root in roots for row in fetch_live_rows(root)]

    candidates: list[PlaybackCandidate] = []
    excluded_live: list[dict[str, Any]] = []
    for row in vrcx_rows:
        candidate = vrcx_candidate(row)
        if candidate is not None:
            candidates.append(candidate)

    live_candidates = 0
    live_auto_accepted = 0
    live_needs_attention = 0
    for row in live_rows:
        candidate, excluded = live_candidate(row)
        if excluded is not None:
            excluded_live.append(excluded)
            continue
        if candidate is None:
            continue
        live_candidates += 1
        if candidate.playback_status == "accepted":
            live_auto_accepted += 1
        else:
            live_needs_attention += 1
        candidates.append(candidate)

    catalog_preview = preview_catalog_actions(candidates, target_catalog, wanna_cache)
    for candidate in candidates:
        action = catalog_preview["action_by_key"].get(
            (candidate.dance_system_key, candidate.dance_external_id)
        )
        if action:
            candidate.catalog_status = action["action"]
            candidate.catalog_attention = 1 if action.get("attention") else 0
        else:
            candidate.catalog_status = "existing"
            candidate.catalog_attention = 0

    near_matches = find_near_matches(candidates)
    live_occurrence_duplicates = count_live_occurrence_duplicates(candidates)
    playback_counts = Counter(candidate.playback_status for candidate in candidates)
    source_kind_counts = Counter(candidate.source_kind for candidate in candidates)
    source_root_counts = Counter(candidate.source_root_key for candidate in candidates)

    summary = {
        "source_summary": source_summary,
        "target_catalog_count": len(target_catalog),
        "wanna_cache_metadata_count": len(wanna_cache),
        "candidate_records": len(candidates),
        "vrcx_records_from_project_dance_events": len(
            [candidate for candidate in candidates if candidate.source_kind == "vrcx_history"]
        ),
        "live_total_rows": len(live_rows),
        "live_import_candidates": live_candidates,
        "live_auto_accepted": live_auto_accepted,
        "live_needs_attention": live_needs_attention,
        "live_excluded": len(excluded_live),
        "live_excluded_reasons": dict(Counter(row["reason"] for row in excluded_live)),
        "candidate_counts_by_playback_status": dict(playback_counts),
        "candidate_counts_by_source_kind": dict(source_kind_counts),
        "candidate_counts_by_source_root": dict(source_root_counts),
        "live_candidates_by_source_root": dict(
            Counter(
                candidate.source_root_key
                for candidate in candidates
                if candidate.source_kind == "live_watcher"
            )
        ),
        "live_auto_accepted_by_source_root": dict(
            Counter(
                candidate.source_root_key
                for candidate in candidates
                if candidate.source_kind == "live_watcher"
                and candidate.playback_status == "accepted"
            )
        ),
        "live_needs_attention_by_source_root": dict(
            Counter(
                candidate.source_root_key
                for candidate in candidates
                if candidate.source_kind == "live_watcher"
                and candidate.playback_status == "needs_attention"
            )
        ),
        "live_excluded_by_source_root": dict(Counter(row["source_root_key"] for row in excluded_live)),
        "live_candidates_by_system": dict(
            Counter(
                candidate.dance_system_key
                for candidate in candidates
                if candidate.source_kind == "live_watcher"
            )
        ),
        "live_needs_attention_by_reason": dict(
            Counter(
                candidate.status_reason
                for candidate in candidates
                if candidate.source_kind == "live_watcher"
                and candidate.playback_status == "needs_attention"
            )
        ),
        "catalog_actions": catalog_preview["summary"],
        "near_vrcx_live_matches_10min": {
            "count": len(near_matches),
            "sample": near_matches[:25],
        },
        "live_exact_occurrence_duplicate_extra_count": live_occurrence_duplicates,
        "samples": {
            "live_needs_attention": [
                sample_candidate(candidate)
                for candidate in candidates
                if candidate.source_kind == "live_watcher"
                and candidate.playback_status == "needs_attention"
            ][:20],
            "live_excluded": excluded_live[:20],
            "catalog_attention": [
                sample_candidate(candidate)
                for candidate in candidates
                if candidate.catalog_attention
            ][:20],
        },
    }
    return {"summary": summary, "candidates": candidates, "wanna_cache": wanna_cache}


def inspect_sources(roots: list[LegacyRoot]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for root in roots:
        item: dict[str, Any] = {
            "root": str(root.root),
            "db_path": str(root.db_path),
            "exists": root.db_path.exists(),
        }
        if root.db_path.exists():
            item["db_size_bytes"] = root.db_path.stat().st_size
            with readonly_db(root.db_path) as conn:
                item["quick_check"] = conn.execute("PRAGMA quick_check").fetchone()[0]
                tables = [
                    row["name"]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                    )
                ]
                item["tables"] = tables
                item["counts"] = {
                    table: conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
                    for table in tables
                }
        summary[root.key] = item
    return summary


def readonly_db(path: Path):
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return closing(conn)


def load_target_catalog(target_db: Path) -> dict[tuple[str, str], dict[str, Any]]:
    catalog: dict[tuple[str, str], dict[str, Any]] = {}
    with readonly_db(target_db) as conn:
        for row in conn.execute(
            """
            SELECT
                dt.id,
                ds.key AS system_key,
                dt.external_id,
                dt.title,
                dt.artist,
                dt.dancer,
                dt.player_count,
                dt.group_name,
                dt.major
            FROM dance_tracks dt
            JOIN dance_systems ds ON ds.id = dt.system_id
            """
        ):
            catalog[(row["system_key"], str(row["external_id"]))] = dict(row)
    return catalog


def load_wanna_cache(cache_dir: Path) -> dict[str, dict[str, Any]]:
    songs: dict[str, dict[str, Any]] = {}
    for row in load_cache_songs(cache_dir):
        songs[str(row["id"])] = row
    return songs


def fetch_project_vrcx_rows(target_db: Path) -> list[dict[str, Any]]:
    with readonly_db(target_db) as conn:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    de.id,
                    de.played_at,
                    de.dance_track_id,
                    de.source,
                    de.confidence,
                    de.event_source,
                    de.event_key,
                    de.video_url,
                    de.video_name,
                    de.requester_display_name,
                    de.requester_user_id,
                    de.location,
                    de.note,
                    de.imported_at,
                    ds.key AS system_key,
                    dt.external_id,
                    dt.title,
                    vi.id AS vrcx_import_id,
                    vi.vrcx_rowid,
                    vi.created_at AS vrcx_created_at,
                    vi.video_url AS vrcx_video_url,
                    vi.video_name AS vrcx_video_name,
                    vi.video_id AS vrcx_video_id,
                    vi.display_name AS vrcx_display_name,
                    vi.user_id AS vrcx_user_id,
                    vi.location AS vrcx_location,
                    vi.inferred_source AS vrcx_inferred_source,
                    vi.imported_at AS vrcx_imported_at
                FROM dance_events de
                LEFT JOIN dance_tracks dt ON dt.id = de.dance_track_id
                LEFT JOIN dance_systems ds ON ds.id = dt.system_id
                LEFT JOIN vrcx_import_events vi ON vi.event_key = de.event_key
                ORDER BY de.id
                """
            )
        ]


def fetch_live_rows(root: LegacyRoot) -> list[dict[str, Any]]:
    if not root.db_path.exists():
        return []
    with readonly_db(root.db_path) as conn:
        rows = []
        for row in conn.execute("SELECT * FROM live_playback_events ORDER BY id"):
            item = dict(row)
            item["_source_root_key"] = root.key
            item["_source_root_path"] = str(root.root)
            rows.append(item)
        return rows


def vrcx_candidate(row: dict[str, Any]) -> PlaybackCandidate | None:
    if not row.get("system_key") or not row.get("external_id") or not row.get("played_at"):
        return None
    normalized_time = normalize_time(row["played_at"])
    fingerprint = source_fingerprint("project", "dance_events", row["id"], row["event_key"])
    provenance = {
        "dance_event": compact_dict(
            row,
            [
                "id",
                "played_at",
                "dance_track_id",
                "source",
                "confidence",
                "event_source",
                "event_key",
                "video_url",
                "video_name",
                "requester_display_name",
                "requester_user_id",
                "location",
                "note",
                "imported_at",
            ],
        ),
        "vrcx_import_event": compact_dict(
            row,
            [
                "vrcx_import_id",
                "vrcx_rowid",
                "vrcx_created_at",
                "vrcx_video_url",
                "vrcx_video_name",
                "vrcx_video_id",
                "vrcx_display_name",
                "vrcx_user_id",
                "vrcx_location",
                "vrcx_inferred_source",
                "vrcx_imported_at",
            ],
        ),
    }
    return PlaybackCandidate(
        source_kind="vrcx_history",
        source_root_key="project",
        source_root_path=str(PROJECT_ROOT),
        source_table="dance_events",
        source_row_id=int(row["id"]),
        source_event_key=row.get("event_key"),
        source_fingerprint=fingerprint,
        played_at=normalized_time,
        original_played_at=row["played_at"],
        dance_system_key=str(row["system_key"]).strip().lower(),
        dance_external_id=str(row["external_id"]),
        dance_track_id=int(row["dance_track_id"]) if row.get("dance_track_id") else None,
        playback_status="accepted",
        counts_in_history=1,
        status_reason="legacy_vrcx_history",
        source_priority=10,
        confidence=float(row["confidence"]) if row.get("confidence") is not None else None,
        event_source=row.get("event_source"),
        source_type=row.get("source"),
        source_display_name=row.get("requester_display_name"),
        video_url=row.get("video_url"),
        video_name=row.get("video_name"),
        requester_display_name=row.get("requester_display_name"),
        requester_user_id=row.get("requester_user_id"),
        location=row.get("location"),
        completion_status=None,
        completion_reason=None,
        provenance=provenance,
    )


def live_candidate(
    row: dict[str, Any],
) -> tuple[PlaybackCandidate | None, dict[str, Any] | None]:
    has_actual = bool(clean_text(row.get("actual_play_at")))
    has_identity = bool(clean_text(row.get("dance_system_key")) and clean_text(row.get("dance_external_id")))
    if not has_actual or not has_identity:
        reasons: list[str] = []
        if not has_actual:
            reasons.append("missing_actual_play")
        if not has_identity:
            reasons.append("missing_identity")
        return None, {
            "source_root_key": row["_source_root_key"],
            "source_row_id": row.get("id"),
            "event_key": row.get("event_key"),
            "reason": "+".join(reasons),
            "actual_play_at": row.get("actual_play_at"),
            "dance_system_key": row.get("dance_system_key"),
            "dance_external_id": row.get("dance_external_id"),
            "video_name": row.get("video_name"),
        }

    normalized_time = normalize_time(row["actual_play_at"])
    completed = (
        row.get("completion_status") == "completed"
        and row.get("completion_reason") == "observed_completion_threshold"
    )
    if completed:
        playback_status = "accepted"
        counts_in_history = 1
        status_reason = "observed_completion_threshold"
        source_priority = 30
    else:
        playback_status = "needs_attention"
        counts_in_history = 0
        status_reason = f"{row.get('completion_status') or 'unknown'}:{row.get('completion_reason') or 'none'}"
        source_priority = 20

    fingerprint = source_fingerprint(
        row["_source_root_key"],
        "live_playback_events",
        row["id"],
        row.get("event_key"),
    )
    video_url = row.get("video_url") or row.get("resolved_url") or row.get("routed_url")
    display_name = row.get("source_display_name") or row.get("display_name")
    return PlaybackCandidate(
        source_kind="live_watcher",
        source_root_key=row["_source_root_key"],
        source_root_path=row["_source_root_path"],
        source_table="live_playback_events",
        source_row_id=int(row["id"]),
        source_event_key=row.get("event_key"),
        source_fingerprint=fingerprint,
        played_at=normalized_time,
        original_played_at=row["actual_play_at"],
        dance_system_key=str(row["dance_system_key"]).strip().lower(),
        dance_external_id=str(row["dance_external_id"]).strip(),
        dance_track_id=None,
        playback_status=playback_status,
        counts_in_history=counts_in_history,
        status_reason=status_reason,
        source_priority=source_priority,
        confidence=1.0 if completed else 0.6,
        event_source="vrc_log_live",
        source_type=row.get("source_type"),
        source_display_name=display_name,
        video_url=video_url,
        video_name=row.get("video_name"),
        requester_display_name=display_name,
        requester_user_id=None,
        location=None,
        completion_status=row.get("completion_status"),
        completion_reason=row.get("completion_reason"),
        provenance={
            "live_playback_event": {
                key: value
                for key, value in row.items()
                if not key.startswith("_")
            }
        },
    ), None


def preview_catalog_actions(
    candidates: list[PlaybackCandidate],
    target_catalog: dict[tuple[str, str], dict[str, Any]],
    wanna_cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    action_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    missing_counts: dict[str, Counter[str]] = defaultdict(Counter)
    missing_distinct: dict[str, set[str]] = defaultdict(set)
    title_hint: dict[tuple[str, str], str] = {}

    for candidate in candidates:
        key = (candidate.dance_system_key, candidate.dance_external_id)
        if key in target_catalog:
            continue
        missing_counts[candidate.dance_system_key][candidate.source_kind] += 1
        missing_distinct[candidate.dance_system_key].add(candidate.dance_external_id)
        if candidate.video_name and key not in title_hint:
            title_hint[key] = candidate.video_name

    for system_key, ids in missing_distinct.items():
        for external_id in ids:
            key = (system_key, external_id)
            if system_key == "wannadance":
                if external_id in wanna_cache:
                    action = "create_wannadance_from_supplemental_cache"
                    attention = False
                else:
                    action = "create_minimal_wannadance_stub"
                    attention = True
            elif system_key == "pypydance":
                action = "create_minimal_pypydance_stub"
                attention = True
            else:
                action = "create_minimal_unknown_system_stub"
                attention = True
            action_by_key[key] = {
                "system_key": system_key,
                "external_id": external_id,
                "action": action,
                "attention": attention,
                "title_hint": title_hint.get(key),
            }

    by_action = Counter(action["action"] for action in action_by_key.values())
    summary = {
        "missing_record_counts": {key: dict(value) for key, value in missing_counts.items()},
        "missing_distinct_ids": {key: len(value) for key, value in missing_distinct.items()},
        "actions_by_type": dict(by_action),
        "samples": sorted(action_by_key.values(), key=lambda item: (item["system_key"], numeric_key(item["external_id"])))[:30],
    }
    return {"action_by_key": action_by_key, "summary": summary}


def execute_cleanup(
    *,
    target_db: Path,
    candidates: list[PlaybackCandidate],
    wanna_cache: dict[str, dict[str, Any]],
    batch_id: str,
) -> dict[str, Any]:
    inserted = 0
    updated = 0
    catalog_actions: Counter[str] = Counter()
    with sqlite3.connect(target_db) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute("BEGIN")
            init_playback_records_schema(conn)
            for candidate in candidates:
                action = ensure_candidate_catalog(conn, candidate, wanna_cache)
                if action:
                    catalog_actions[action] += 1
                existing = conn.execute(
                    "SELECT id FROM playback_records WHERE source_fingerprint = ?",
                    (candidate.source_fingerprint,),
                ).fetchone()
                upsert_playback_record(conn, candidate, batch_id)
                if existing is None:
                    inserted += 1
                else:
                    updated += 1
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return {
        "execution": {
            "playback_records_inserted": inserted,
            "playback_records_updated": updated,
            "catalog_actions_applied": dict(catalog_actions),
        }
    }


def ensure_candidate_catalog(
    conn: sqlite3.Connection,
    candidate: PlaybackCandidate,
    wanna_cache: dict[str, dict[str, Any]],
) -> str | None:
    existing = lookup_track_id(conn, candidate.dance_system_key, candidate.dance_external_id)
    if existing is not None:
        candidate.dance_track_id = existing
        if candidate.catalog_status == "unresolved":
            candidate.catalog_status = "existing"
        return None

    if candidate.dance_system_key == "wannadance":
        song = wanna_cache.get(candidate.dance_external_id)
        if song is not None:
            candidate.dance_track_id = upsert_wannadance_cache_song(conn, song)
            candidate.catalog_status = "create_wannadance_from_supplemental_cache"
            candidate.catalog_attention = 0
            return "create_wannadance_from_supplemental_cache"
        candidate.dance_track_id = ensure_dance_track(
            conn,
            "wannadance",
            candidate.dance_external_id,
            {"title": candidate.video_name},
        )
        candidate.catalog_status = "create_minimal_wannadance_stub"
        candidate.catalog_attention = 1
        return "create_minimal_wannadance_stub"

    if candidate.dance_system_key == "pypydance":
        ensure_dance_system(conn, "pypydance", "PyPyDance")
        candidate.dance_track_id = ensure_dance_track(
            conn,
            "pypydance",
            candidate.dance_external_id,
            {"title": candidate.video_name},
        )
        candidate.catalog_status = "create_minimal_pypydance_stub"
        candidate.catalog_attention = 1
        return "create_minimal_pypydance_stub"

    ensure_dance_system(conn, candidate.dance_system_key, candidate.dance_system_key)
    candidate.dance_track_id = ensure_dance_track(
        conn,
        candidate.dance_system_key,
        candidate.dance_external_id,
        {"title": candidate.video_name},
    )
    candidate.catalog_status = "create_minimal_unknown_system_stub"
    candidate.catalog_attention = 1
    return "create_minimal_unknown_system_stub"


def lookup_track_id(conn: sqlite3.Connection, system_key: str, external_id: str) -> int | None:
    row = conn.execute(
        """
        SELECT dt.id
        FROM dance_tracks dt
        JOIN dance_systems ds ON ds.id = dt.system_id
        WHERE ds.key = ? AND dt.external_id = ?
        """,
        (system_key, str(external_id)),
    ).fetchone()
    return int(row["id"]) if row else None


def upsert_wannadance_cache_song(conn: sqlite3.Connection, song: dict[str, Any]) -> int:
    dance_track_id = ensure_dance_track(
        conn,
        "wannadance",
        song["id"],
        {
            "title": song.get("name") or song.get("cache_title"),
            "artist": song.get("artist") or "",
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
            int(song["id"]),
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
    return dance_track_id


def upsert_playback_record(
    conn: sqlite3.Connection,
    candidate: PlaybackCandidate,
    batch_id: str,
) -> None:
    conn.execute(
        """
        INSERT INTO playback_records (
            cleanup_batch_id,
            played_at,
            original_played_at,
            dance_track_id,
            dance_system_key,
            dance_external_id,
            source_kind,
            source_root_key,
            source_root_path,
            source_table,
            source_row_id,
            source_event_key,
            source_fingerprint,
            playback_status,
            counts_in_history,
            status_reason,
            source_priority,
            confidence,
            event_source,
            source_type,
            source_display_name,
            video_url,
            video_name,
            requester_display_name,
            requester_user_id,
            location,
            completion_status,
            completion_reason,
            catalog_status,
            catalog_attention,
            provenance_json,
            imported_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_fingerprint) DO UPDATE SET
            cleanup_batch_id = excluded.cleanup_batch_id,
            played_at = excluded.played_at,
            original_played_at = excluded.original_played_at,
            dance_track_id = excluded.dance_track_id,
            dance_system_key = excluded.dance_system_key,
            dance_external_id = excluded.dance_external_id,
            source_kind = excluded.source_kind,
            source_root_key = excluded.source_root_key,
            source_root_path = excluded.source_root_path,
            source_table = excluded.source_table,
            source_row_id = excluded.source_row_id,
            source_event_key = excluded.source_event_key,
            playback_status = excluded.playback_status,
            counts_in_history = excluded.counts_in_history,
            status_reason = excluded.status_reason,
            source_priority = excluded.source_priority,
            confidence = excluded.confidence,
            event_source = excluded.event_source,
            source_type = excluded.source_type,
            source_display_name = excluded.source_display_name,
            video_url = excluded.video_url,
            video_name = excluded.video_name,
            requester_display_name = excluded.requester_display_name,
            requester_user_id = excluded.requester_user_id,
            location = excluded.location,
            completion_status = excluded.completion_status,
            completion_reason = excluded.completion_reason,
            catalog_status = excluded.catalog_status,
            catalog_attention = excluded.catalog_attention,
            provenance_json = excluded.provenance_json
        """,
        (
            batch_id,
            candidate.played_at,
            candidate.original_played_at,
            candidate.dance_track_id,
            candidate.dance_system_key,
            candidate.dance_external_id,
            candidate.source_kind,
            candidate.source_root_key,
            candidate.source_root_path,
            candidate.source_table,
            candidate.source_row_id,
            candidate.source_event_key,
            candidate.source_fingerprint,
            candidate.playback_status,
            candidate.counts_in_history,
            candidate.status_reason,
            candidate.source_priority,
            candidate.confidence,
            candidate.event_source,
            candidate.source_type,
            candidate.source_display_name,
            candidate.video_url,
            candidate.video_name,
            candidate.requester_display_name,
            candidate.requester_user_id,
            candidate.location,
            candidate.completion_status,
            candidate.completion_reason,
            candidate.catalog_status,
            candidate.catalog_attention,
            json.dumps(candidate.provenance or {}, ensure_ascii=False, sort_keys=True),
            utc_now_text(),
        ),
    )


def find_near_matches(candidates: list[PlaybackCandidate]) -> list[dict[str, Any]]:
    vrcx_by_key: dict[tuple[str, str], list[PlaybackCandidate]] = defaultdict(list)
    for candidate in candidates:
        if candidate.source_kind == "vrcx_history":
            vrcx_by_key[(candidate.dance_system_key, candidate.dance_external_id)].append(candidate)

    matches: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate.source_kind != "live_watcher":
            continue
        live_time = parse_normalized_time(candidate.played_at)
        for vrcx in vrcx_by_key.get((candidate.dance_system_key, candidate.dance_external_id), []):
            delta = abs((live_time - parse_normalized_time(vrcx.played_at)).total_seconds())
            if delta <= NEAR_MATCH_SECONDS:
                matches.append(
                    {
                        "system": candidate.dance_system_key,
                        "external_id": candidate.dance_external_id,
                        "delta_seconds": round(delta, 3),
                        "live_source_root": candidate.source_root_key,
                        "live_source_row_id": candidate.source_row_id,
                        "live_original_time": candidate.original_played_at,
                        "vrcx_source_row_id": vrcx.source_row_id,
                        "vrcx_original_time": vrcx.original_played_at,
                        "title": candidate.video_name or vrcx.video_name,
                    }
                )
    return matches


def count_live_occurrence_duplicates(candidates: list[PlaybackCandidate]) -> int:
    occurrences: Counter[tuple[str, str, str]] = Counter()
    for candidate in candidates:
        if candidate.source_kind != "live_watcher":
            continue
        occurrences[
            (
                candidate.dance_system_key,
                candidate.dance_external_id,
                candidate.played_at,
            )
        ] += 1
    return sum(count - 1 for count in occurrences.values() if count > 1)


def backup_database(target_db: Path, report_dir: Path, batch_id: str) -> Path:
    backup_path = report_dir / f"{batch_id}.target-backup.sqlite3"
    with sqlite3.connect(target_db) as src, sqlite3.connect(backup_path) as dst:
        src.backup(dst)
    shutil.copystat(target_db, backup_path)
    return backup_path


def write_reports(report_base: Path, summary: dict[str, Any]) -> None:
    json_path = report_base.with_suffix(".json")
    md_path = report_base.with_suffix(".md")
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    md_path.write_text(render_markdown(summary, json_path), encoding="utf-8")


def render_markdown(summary: dict[str, Any], json_path: Path) -> str:
    lines = [
        "# Legacy playback cleanup report",
        "",
        f"- Status: `{summary.get('status')}`",
        f"- Mode: `{summary.get('mode')}`",
        f"- Batch: `{summary.get('batch_id')}`",
        f"- Target DB: `{summary.get('target_db')}`",
    ]
    if summary.get("backup_path"):
        lines.append(f"- Backup: `{summary['backup_path']}`")
    lines.append(f"- JSON detail: `{json_path}`")
    lines.append("")
    lines.append("## Import summary")
    lines.extend(
        [
            f"- Candidate playback records: {summary.get('candidate_records', 0)}",
            f"- VRCX records from project dance_events: {summary.get('vrcx_records_from_project_dance_events', 0)}",
            f"- Live rows scanned: {summary.get('live_total_rows', 0)}",
            f"- Live import candidates: {summary.get('live_import_candidates', 0)}",
            f"- Live auto accepted: {summary.get('live_auto_accepted', 0)}",
            f"- Live needs attention: {summary.get('live_needs_attention', 0)}",
            f"- Live excluded: {summary.get('live_excluded', 0)}",
        ]
    )
    if "execution" in summary:
        execution = summary["execution"]
        lines.extend(
            [
                "",
                "## Execution",
                f"- Inserted playback_records: {execution.get('playback_records_inserted', 0)}",
                f"- Updated playback_records: {execution.get('playback_records_updated', 0)}",
                f"- Catalog actions: `{json.dumps(execution.get('catalog_actions_applied', {}), ensure_ascii=False)}`",
            ]
        )
    lines.append("")
    lines.append("## Catalog")
    lines.append(f"- Target catalog before cleanup: {summary.get('target_catalog_count', 0)}")
    lines.append(f"- Supplemental WannaDance cache metadata rows: {summary.get('wanna_cache_metadata_count', 0)}")
    lines.append(
        f"- Catalog action summary: `{json.dumps(summary.get('catalog_actions', {}).get('actions_by_type', {}), ensure_ascii=False)}`"
    )
    lines.append("")
    lines.append("## Review")
    lines.append(
        f"- Near VRCX/live matches within {NEAR_MATCH_SECONDS} seconds: {summary.get('near_vrcx_live_matches_10min', {}).get('count', 0)}"
    )
    lines.append(
        f"- Live exact occurrence duplicate extras: {summary.get('live_exact_occurrence_duplicate_extra_count', 0)}"
    )
    lines.append("")
    lines.append("## Follow-up")
    lines.append(
        "- Timeline and Insights code paths still need a separate product change to read playback_records instead of the legacy tables."
    )
    if summary.get("error"):
        lines.extend(["", "## Error", "```", summary["error"], "```"])
    return "\n".join(lines) + "\n"


def print_summary(summary: dict[str, Any], report_base: Path) -> None:
    out = {
        "status": summary.get("status"),
        "mode": summary.get("mode"),
        "candidate_records": summary.get("candidate_records"),
        "live_import_candidates": summary.get("live_import_candidates"),
        "live_auto_accepted": summary.get("live_auto_accepted"),
        "live_needs_attention": summary.get("live_needs_attention"),
        "live_excluded": summary.get("live_excluded"),
        "backup_path": summary.get("backup_path"),
        "json_report": str(report_base.with_suffix(".json")),
        "markdown_report": str(report_base.with_suffix(".md")),
        "execution": summary.get("execution"),
    }
    sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False, indent=2).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


def normalize_time(value: str) -> str:
    text = str(value).strip()
    parsed: datetime | None = None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y.%m.%d %H:%M:%S.%f", "%Y.%m.%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(text, fmt).replace(tzinfo=LOCAL_TZ)
                break
            except ValueError:
                continue
    if parsed is None:
        raise ValueError(f"unsupported timestamp: {value}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TZ)
    utc = parsed.astimezone(UTC)
    return utc.isoformat().replace("+00:00", "Z")


def parse_normalized_time(value: str) -> datetime:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(text)


def source_fingerprint(
    source_root_key: str,
    source_table: str,
    source_row_id: Any,
    source_event_key: Any,
) -> str:
    raw = "\x1f".join(
        [
            "legacy-playback-cleanup",
            str(source_root_key),
            str(source_table),
            str(source_row_id),
            str(source_event_key or ""),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sample_candidate(candidate: PlaybackCandidate) -> dict[str, Any]:
    return {
        "source_kind": candidate.source_kind,
        "source_root_key": candidate.source_root_key,
        "source_row_id": candidate.source_row_id,
        "played_at": candidate.played_at,
        "original_played_at": candidate.original_played_at,
        "system": candidate.dance_system_key,
        "external_id": candidate.dance_external_id,
        "status": candidate.playback_status,
        "counts_in_history": candidate.counts_in_history,
        "reason": candidate.status_reason,
        "catalog_status": candidate.catalog_status,
        "catalog_attention": candidate.catalog_attention,
        "video_name": candidate.video_name,
        "display_name": candidate.source_display_name,
    }


def compact_dict(row: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: row.get(key) for key in keys if row.get(key) is not None}


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def numeric_key(value: str) -> tuple[int, Any]:
    text = str(value)
    if text.isdigit():
        return (0, int(text))
    return (1, text)


def utc_now_text() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
