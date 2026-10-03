"""Replay fixed VRChat log corpora and compare watcher outputs."""

from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sqlite3
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dance_trail.time_utils import parse_timestamp  # noqa: E402

KNOWN_OUTPUTS = (
    "raw_output_log.txt",
    "candidates.jsonl",
    "parsed_events.jsonl",
    "playback_events.jsonl",
    "summary.json",
    "diff_report.md",
    "live.sqlite3",
    "live.sqlite3-wal",
    "live.sqlite3-shm",
)
REPLAY_STARTED_AT = "1970-01-01T00:00:00+00:00"
REPLAY_LIVE_SESSION_ID = "vrc-log-replay-parity"
IGNORED_JSON_FIELDS = {"captured_at", "received_at"}
LIVE_PLAYBACK_COLUMNS = (
    "event_key",
    "session_id",
    "playback_event_key",
    "canonical_key",
    "first_seen_at",
    "request_at",
    "load_started_at",
    "resolve_attempt_at",
    "resolved_at",
    "video_loaded_at",
    "expected_ready_at",
    "last_seen_at",
    "actual_play_at",
    "actual_play_signal_at",
    "actual_play_offset_seconds",
    "actual_play_method",
    "on_video_start_at",
    "synced_play_at",
    "observed_mid_play",
    "elapsed_at_first_seen_seconds",
    "delay_to_actual_seconds",
    "load_to_actual_seconds",
    "request_to_resolve_seconds",
    "video_url",
    "routed_url",
    "resolved_url",
    "dance_system_key",
    "dance_external_id",
    "url_kind",
    "video_name",
    "video_id",
    "display_name",
    "requester_marker",
    "source_hint",
    "source_type",
    "source_display_name",
    "world_parser",
    "duration_seconds",
    "duration_source",
    "load_seconds",
    "wait_seconds",
    "source_file",
    "first_line_number",
    "last_line_number",
    "signal_count",
    "parser_names_json",
    "raw_event_types_json",
    "event_json",
    "completion_status",
    "completion_reason",
    "completed_at",
    "interrupted_at",
    "played_seconds",
    "required_played_seconds",
)
PLAYBACK_RECORD_COLUMNS = (
    "evidence_key",
    "evidence_source",
    "played_at",
    "dance_system_key",
    "dance_external_id",
    "request_type",
    "video_url",
    "video_name",
    "requester_display_name",
    "requester_user_id",
    "default_acceptance_status",
    "observation_status",
    "observation_reason",
    "observed_end_at",
    "origin_key",
    "origin_source",
    "origin_root_key",
    "origin_root_path",
    "origin_table",
    "origin_row_id",
    "origin_event_key",
    "origin_json",
)
MANUAL_GT_DATE = (2026, 5, 17)
MANUAL_GT_TIME_ZONE = timezone(timedelta(hours=8))
MANUAL_MATCH_TOLERANCE_SECONDS = 90
MANUAL_DIAGNOSTIC_TOLERANCE_SECONDS = 600


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay fixed VRChat logs")
    subparsers = parser.add_subparsers(dest="command", required=True)

    baseline = subparsers.add_parser("baseline", help="write a replay baseline")
    baseline.add_argument("--log-dir", required=True, help="Directory containing output_log_*.txt")
    baseline.add_argument("--output", required=True, help="Output directory")
    baseline.add_argument("--pattern", default="output_log_*.txt", help="Log glob pattern")

    compare = subparsers.add_parser("compare", help="replay and compare with a baseline")
    compare.add_argument("--baseline", required=True, help="Baseline replay directory")
    compare.add_argument("--output", required=True, help="Output directory for this run")
    compare.add_argument("--log-dir", default="analysis/vrc_logs", help="Directory containing output_log_*.txt")
    compare.add_argument("--pattern", default="output_log_*.txt", help="Log glob pattern")
    compare.add_argument("--manual-gt", default=None, help="Manual ground-truth text file")
    compare.add_argument("--vrcx-db", default=None, help="Optional VRCX.sqlite3 read-only comparison source")
    compare.add_argument("--app-db", default=None, help="Optional app DB for read-only replay-content comparison")

    args = parser.parse_args()
    if args.command == "baseline":
        run_baseline(args)
    elif args.command == "compare":
        run_compare(args)


def run_baseline(args) -> None:
    output = Path(args.output)
    _prepare_output(output)
    stats = _run_replay(
        log_dir=Path(args.log_dir),
        pattern=args.pattern,
        output=output,
    )
    report = [
        "# Replay Baseline",
        "",
        "Generated replay baseline.",
        "",
        f"- log files: {len(stats.replayed_files)}",
        f"- raw lines: {stats.raw_lines}",
        f"- parsed events: {stats.parsed_events}",
        f"- playback events: {stats.playback_events}",
        f"- live DB updates: {stats.live_db_updates}",
        f"- playback record updates: {stats.playback_record_updates}",
        f"- acceptance threshold: {_acceptance_threshold_label()} of known duration",
    ]
    (output / "diff_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "playback_events": stats.playback_events}))


def run_compare(args) -> None:
    output = Path(args.output)
    baseline = Path(args.baseline)
    _prepare_output(output)
    stats = _run_replay(
        log_dir=Path(args.log_dir),
        pattern=args.pattern,
        output=output,
    )

    report = [
        "# Replay Diff Report",
        "",
        "## Replay Summary",
        "",
        f"- log files: {len(stats.replayed_files)}",
        f"- raw lines: {stats.raw_lines}",
        f"- parsed events: {stats.parsed_events}",
        f"- playback events: {stats.playback_events}",
        f"- live DB updates: {stats.live_db_updates}",
        f"- playback record updates: {stats.playback_record_updates}",
        f"- acceptance threshold: {_acceptance_threshold_label()} of known duration",
        "",
    ]
    failed_sections: list[str] = []

    parsed_section, parsed_failed = _ordered_jsonl_diff_section(
        baseline,
        output,
        filename="parsed_events.jsonl",
        label="Parsed Events Diff",
    )
    report.extend(parsed_section)
    if parsed_failed:
        failed_sections.append("parsed_events.jsonl")

    playback_section, playback_failed = _playback_diff_section(baseline, output)
    report.extend(playback_section)
    if playback_failed:
        failed_sections.append("playback_events.jsonl")

    live_section, live_failed = _live_playback_diff_section(baseline, output)
    report.extend(live_section)
    if live_failed:
        failed_sections.append("live.sqlite3:live_playback_events")

    settlement_section, settlement_failed = _playback_records_diff_section(baseline, output)
    report.extend(settlement_section)
    if settlement_failed:
        failed_sections.append("live.sqlite3:playback_records")

    if args.manual_gt:
        report.extend(_manual_gt_section(Path(args.manual_gt), output / "live.sqlite3"))
    if args.vrcx_db:
        report.extend(_vrcx_section(Path(args.vrcx_db), args.manual_gt))
    if args.app_db:
        app_db_section, app_db_failed = _app_db_section(Path(args.app_db), output / "live.sqlite3")
        report.extend(app_db_section)
        if app_db_failed:
            failed_sections.append("app-db")

    (output / "diff_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                "diff_report": str(output / "diff_report.md"),
                "ok": not failed_sections,
                "failed_sections": failed_sections,
            }
        )
    )
    if failed_sections:
        raise SystemExit(1)


def _run_replay(*, log_dir: Path, pattern: str, output: Path):
    from dance_trail.vrc_log_watcher import replay_vrc_log_files

    log_files = sorted(log_dir.glob(pattern), key=lambda path: path.name)
    if not log_files:
        raise SystemExit(f"No logs matched {pattern} in {log_dir}")
    return replay_vrc_log_files(
        log_files=log_files,
        output_dir=output,
        app_db_path=output / "live.sqlite3",
        started_at=REPLAY_STARTED_AT,
        live_session_id=REPLAY_LIVE_SESSION_ID,
        live_db=True,
        record_playback=True,
    )


def _acceptance_threshold_label() -> str:
    from dance_trail.vrc_log_watcher import PROMOTION_COMPLETION_RATIO

    return f"{PROMOTION_COMPLETION_RATIO:.0%}"


def _prepare_output(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for name in KNOWN_OUTPUTS:
        path = output / name
        if path.exists():
            path.unlink()


def _ordered_jsonl_diff_section(
    baseline: Path,
    output: Path,
    *,
    filename: str,
    label: str,
) -> tuple[list[str], bool]:
    base_path = baseline / filename
    run_path = output / filename
    if not base_path.exists():
        return [f"## {label}", "", f"- baseline missing: {base_path}", ""], True
    if not run_path.exists():
        return [f"## {label}", "", f"- replay output missing: {run_path}", ""], True

    base_rows = _read_jsonl(base_path)
    run_rows = _read_jsonl(run_path)
    comparable_count = min(len(base_rows), len(run_rows))
    changed = [
        index
        for index in range(comparable_count)
        if _stable_event(base_rows[index]) != _stable_event(run_rows[index])
    ]
    added = max(0, len(run_rows) - len(base_rows))
    removed = max(0, len(base_rows) - len(run_rows))
    changed_field_counts = _changed_field_counts_for_pairs(
        (base_rows[index], run_rows[index]) for index in changed
    )

    lines = [
        f"## {label}",
        "",
        f"- baseline rows: {len(base_rows)}",
        f"- replay rows: {len(run_rows)}",
        f"- added rows: {added}",
        f"- removed rows: {removed}",
        f"- changed rows: {len(changed)}",
    ]
    if changed:
        display_indexes = ", ".join(str(index + 1) for index in changed[:20])
        lines.append(f"- changed row numbers: {display_indexes}")
        if changed_field_counts:
            lines.append(f"- changed field counts: {_field_count_summary(changed_field_counts)}")
    lines.append("")
    return lines, bool(added or removed or changed)


def _playback_diff_section(baseline: Path, output: Path) -> tuple[list[str], bool]:
    base_path = baseline / "playback_events.jsonl"
    run_path = output / "playback_events.jsonl"
    if not base_path.exists():
        return ["## Playback Diff", "", f"- baseline missing: {base_path}", ""], True
    if not run_path.exists():
        return ["## Playback Diff", "", f"- replay output missing: {run_path}", ""], True

    base_events = _index_events(_read_jsonl(base_path))
    run_events = _index_events(_read_jsonl(run_path))
    added = sorted(set(run_events) - set(base_events))
    removed = sorted(set(base_events) - set(run_events))
    changed = [
        key
        for key in sorted(set(base_events) & set(run_events))
        if _stable_event(base_events[key]) != _stable_event(run_events[key])
    ]
    duration_sources = sum(1 for event in run_events.values() if event.get("duration_source"))
    changed_field_counts = _changed_field_counts(base_events, run_events, changed)

    lines = [
        "## Playback Diff",
        "",
        f"- added events: {len(added)}",
        f"- removed events: {len(removed)}",
        f"- changed events: {len(changed)}",
        f"- events with duration_source: {duration_sources}",
    ]
    if added:
        lines.append(f"- added keys: {', '.join(added[:20])}")
        if all(key.endswith("#2") for key in added):
            lines.append(
                "- explained added events: all added keys are second occurrences "
                "from later real playback/load/resolve signals"
            )
    if removed:
        lines.append(f"- removed keys: {', '.join(removed[:20])}")
    if changed:
        lines.append(f"- changed keys: {', '.join(changed[:20])}")
        if changed_field_counts:
            lines.append(f"- changed field counts: {_field_count_summary(changed_field_counts)}")
        explained = [
            key
            for key in changed
            if not base_events[key].get("duration_source") and run_events[key].get("duration_source")
        ]
        if explained:
            lines.append(
                f"- explained duration metadata changes: {len(explained)} events "
                f"({', '.join(explained[:20])}; duration from VRChat log metadata)"
            )
    lines.append("")
    return lines, bool(added or removed or changed)


def _live_playback_diff_section(baseline: Path, output: Path) -> tuple[list[str], bool]:
    return _sqlite_indexed_diff_section(
        label="Live Playback SQLite Diff",
        baseline=baseline,
        output=output,
        rows_reader=_read_live_playback_rows,
        key_field="event_key",
    )


def _playback_records_diff_section(baseline: Path, output: Path) -> tuple[list[str], bool]:
    return _sqlite_indexed_diff_section(
        label="Playback Records Settlement SQLite Diff",
        baseline=baseline,
        output=output,
        rows_reader=_read_playback_record_rows,
        key_field="evidence_origin_key",
    )


def _sqlite_indexed_diff_section(
    *,
    label: str,
    baseline: Path,
    output: Path,
    rows_reader,
    key_field: str,
) -> tuple[list[str], bool]:
    base_db = baseline / "live.sqlite3"
    run_db = output / "live.sqlite3"
    if not base_db.exists():
        return [f"## {label}", "", f"- baseline DB missing: {base_db}", ""], True
    if not run_db.exists():
        return [f"## {label}", "", f"- replay DB missing: {run_db}", ""], True

    try:
        base_rows = rows_reader(base_db)
        run_rows = rows_reader(run_db)
    except sqlite3.Error as exc:
        return [f"## {label}", "", f"- SQLite read failed: {exc}", ""], True

    base_by_key = _index_rows(base_rows, key_field)
    run_by_key = _index_rows(run_rows, key_field)
    added = sorted(set(run_by_key) - set(base_by_key))
    removed = sorted(set(base_by_key) - set(run_by_key))
    changed = [
        key
        for key in sorted(set(base_by_key) & set(run_by_key))
        if _stable_event(base_by_key[key]) != _stable_event(run_by_key[key])
    ]
    changed_field_counts = _changed_field_counts(base_by_key, run_by_key, changed)

    lines = [
        f"## {label}",
        "",
        f"- baseline rows: {len(base_rows)}",
        f"- replay rows: {len(run_rows)}",
        f"- added rows: {len(added)}",
        f"- removed rows: {len(removed)}",
        f"- changed rows: {len(changed)}",
    ]
    if added:
        lines.append(f"- added keys: {', '.join(added[:20])}")
    if removed:
        lines.append(f"- removed keys: {', '.join(removed[:20])}")
    if changed:
        lines.append(f"- changed keys: {', '.join(changed[:20])}")
        if changed_field_counts:
            lines.append(f"- changed field counts: {_field_count_summary(changed_field_counts)}")
    lines.append("")
    return lines, bool(added or removed or changed)


def _read_live_playback_rows(db_path: Path) -> list[dict]:
    columns = ", ".join(LIVE_PLAYBACK_COLUMNS)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT {columns}
            FROM live_playback_events
            ORDER BY event_key
            """
        ).fetchall()
    return [_decode_sqlite_json_columns(dict(row)) for row in rows]


def _read_playback_record_rows(db_path: Path) -> list[dict]:
    columns = ", ".join(
        (
            *(f"pr.{column}" for column in PLAYBACK_RECORD_COLUMNS if not column.startswith("origin_")),
            "pro.origin_key",
            "pro.origin_source",
            "pro.origin_root_key",
            "pro.origin_root_path",
            "pro.origin_table",
            "pro.origin_row_id",
            "pro.origin_event_key",
            "pro.origin_json",
        )
    )
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT {columns}
            FROM playback_records pr
            JOIN playback_record_origins pro
                ON pro.playback_record_id = pr.id
            WHERE pr.evidence_source = 'vrc_log_live'
                AND pro.origin_table = 'watcher_playback_events'
            ORDER BY pr.evidence_key, pro.origin_key
            """
        ).fetchall()
    return [_decode_playback_record_row(dict(row)) for row in rows]


def _decode_playback_record_row(row: dict) -> dict:
    row["evidence_origin_key"] = f"{row.get('evidence_key') or ''}\x1f{row.get('origin_key') or ''}"
    value = row.get("origin_json")
    if isinstance(value, str):
        try:
            row["origin_json"] = json.loads(value)
        except json.JSONDecodeError:
            pass
    return row


def _decode_sqlite_json_columns(row: dict) -> dict:
    for field_name, default in (
        ("parser_names_json", []),
        ("raw_event_types_json", []),
        ("event_json", {}),
    ):
        value = row.get(field_name)
        if not isinstance(value, str):
            row[field_name] = default
            continue
        try:
            row[field_name] = json.loads(value)
        except json.JSONDecodeError:
            row[field_name] = value
    return row


def _manual_gt_section(manual_gt: Path, db_path: Path) -> list[str]:
    expected = _parse_manual_gt(manual_gt)
    if not expected:
        return ["## Manual GT", "", f"- no manual GT rows parsed from {manual_gt}", ""]
    if not db_path.exists():
        return ["## Manual GT", "", f"- live DB missing: {db_path}", ""]

    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        playback_records = conn.execute(
            """
            SELECT played_at, dance_system_key, dance_external_id,
                   default_acceptance_status AS playback_status,
                   CASE
                       WHEN default_acceptance_status = 'accepted' THEN 1
                       ELSE 0
                   END AS counts_in_history,
                   observation_reason AS status_reason,
                   observation_status AS completion_status,
                   observation_reason AS completion_reason
            FROM playback_records pr
            JOIN playback_record_origins pro
                ON pro.playback_record_id = pr.id
            WHERE pr.evidence_source = 'vrc_log_live'
                AND pro.origin_table = 'watcher_playback_events'
            ORDER BY pr.played_at
            """
        ).fetchall()

    should_accept = [row for row in expected if row["expected_completed"]]
    should_not_accept = [row for row in expected if not row["expected_completed"]]
    missing = [
        row
        for row in should_accept
        if not _matches_manual_row(
            playback_records,
            row,
            system_field="dance_system_key",
            external_id_field="dance_external_id",
            time_field="played_at",
            status_field="playback_status",
            status="accepted",
        )
    ]
    unexpected = [
        row
        for row in should_not_accept
        if _matches_manual_row(
            playback_records,
            row,
            system_field="dance_system_key",
            external_id_field="dance_external_id",
            time_field="played_at",
            status_field="playback_status",
            status="accepted",
        )
    ]
    attention_ok = [
        row
        for row in should_not_accept
        if _matches_manual_row(
            playback_records,
            row,
            system_field="dance_system_key",
            external_id_field="dance_external_id",
            time_field="played_at",
            status_field="playback_status",
            status="needs_attention",
        )
    ]

    lines = [
        "## Manual GT",
        "",
        f"- manual rows: {len(expected)}",
        f"- expected accepted records: {len(should_accept)}",
        f"- missing expected accepted records: {len(missing)}",
        f"- unexpected accepted records: {len(unexpected)}",
        f"- expected non-accepted records needing attention: {len(attention_ok)}/{len(should_not_accept)}",
    ]
    if missing:
        lines.append("- missing: " + ", ".join(f"{row['time']} {row['external_id']}" for row in missing))
        diagnostics = _missing_manual_diagnostics(missing, playback_records)
        if diagnostics:
            lines.append("- needs_human_confirmation:")
            lines.extend(f"  - {line}" for line in diagnostics)
    if unexpected:
        lines.append("- unexpected: " + ", ".join(f"{row['time']} {row['external_id']}" for row in unexpected))
    lines.append("")
    return lines


def _app_db_section(app_db: Path, replay_db: Path) -> tuple[list[str], bool]:
    if not app_db.exists():
        return ["## App DB", "", f"- missing app DB: {app_db}", ""], True
    if not replay_db.exists():
        return ["## App DB", "", f"- replay DB missing: {replay_db}", ""], True

    try:
        with closing(_connect_read_only(app_db)) as app_conn, closing(
            _connect_read_only(replay_db)
        ) as replay_conn:
            app_summary = _playback_db_summary(app_conn)
            replay_summary = _playback_db_summary(replay_conn)
            replay_rows = _read_playback_identity_rows(
                replay_conn,
                evidence_source="vrc_log_live",
                origin_table="watcher_playback_events",
            )
            app_replay_rows = _read_playback_identity_rows(
                app_conn,
                evidence_source="vrc_log_replay",
                origin_table=None,
            )
            app_live_rows = _read_playback_identity_rows(
                app_conn,
                evidence_source="vrc_log_live",
                origin_table="watcher_playback_events",
            )
    except sqlite3.Error as exc:
        return ["## App DB", "", f"- app DB read failed: {exc}", ""], True

    replay_compare = _playback_identity_compare(replay_rows, app_replay_rows)
    live_compare = _playback_identity_compare(replay_rows, app_live_rows)
    failed = app_summary["quick_check"] != "ok" or replay_summary["quick_check"] != "ok"
    if (
        replay_compare["common"] == len(replay_rows)
        and replay_compare["existing_rows"] == len(replay_rows)
        and (
            replay_compare["missing"]
            or replay_compare["extra"]
            or replay_compare["status_mismatches"]
            or replay_compare["requester_regressions"]
        )
    ):
        failed = True

    lines = [
        "## App DB",
        "",
        f"- app DB: {app_db}",
        f"- app quick_check: {app_summary['quick_check']}",
        f"- app playback_records/origins: {app_summary['records']}/{app_summary['origins']}",
        f"- app records without origin: {app_summary['records_without_origin']}",
        f"- replay quick_check: {replay_summary['quick_check']}",
        f"- replay playback_records/origins: {replay_summary['records']}/{replay_summary['origins']}",
        f"- replay records without origin: {replay_summary['records_without_origin']}",
        (
            "- compare replay output to existing vrc_log_replay: "
            + _playback_compare_summary(replay_compare)
        ),
        (
            "- compare replay output to existing vrc_log_live watcher origins: "
            + _playback_compare_summary(live_compare)
        ),
    ]
    for label, compare in (
        ("vrc_log_replay missing samples", replay_compare),
        ("vrc_log_live missing samples", live_compare),
    ):
        if compare["missing_samples"]:
            lines.append(f"- {label}: {_identity_sample_summary(compare['missing_samples'])}")
    lines.append("")
    return lines, failed


def _connect_read_only(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _playback_db_summary(conn: sqlite3.Connection) -> dict[str, object]:
    return {
        "quick_check": conn.execute("PRAGMA quick_check").fetchone()[0],
        "records": conn.execute("SELECT COUNT(*) FROM playback_records").fetchone()[0],
        "origins": conn.execute("SELECT COUNT(*) FROM playback_record_origins").fetchone()[0],
        "records_without_origin": conn.execute(
            """
            SELECT COUNT(*)
            FROM playback_records pr
            WHERE NOT EXISTS (
                SELECT 1
                FROM playback_record_origins pro
                WHERE pro.playback_record_id = pr.id
            )
            """
        ).fetchone()[0],
    }


def _read_playback_identity_rows(
    conn: sqlite3.Connection,
    *,
    evidence_source: str,
    origin_table: str | None,
) -> list[dict]:
    where = ["pr.evidence_source = ?"]
    params: list[object] = [evidence_source]
    if origin_table is not None:
        where.append("pro.origin_table = ?")
        params.append(origin_table)
    rows = conn.execute(
        f"""
        SELECT
            pr.played_at,
            pr.dance_system_key,
            pr.dance_external_id,
            pr.default_acceptance_status,
            pr.observation_status,
            pr.requester_user_id
        FROM playback_records pr
        JOIN playback_record_origins pro
            ON pro.playback_record_id = pr.id
        WHERE {" AND ".join(where)}
        ORDER BY pr.played_at, pr.dance_system_key, pr.dance_external_id
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def _playback_identity_compare(
    replay_rows: list[dict],
    existing_rows: list[dict],
) -> dict[str, object]:
    replay_by_key = {_playback_identity_key(row): row for row in replay_rows}
    existing_by_key = {_playback_identity_key(row): row for row in existing_rows}
    replay_keys = set(replay_by_key)
    existing_keys = set(existing_by_key)
    common = replay_keys & existing_keys
    missing = sorted(replay_keys - existing_keys)
    extra = sorted(existing_keys - replay_keys)
    status_mismatches = 0
    requester_regressions = 0
    for key in common:
        replay = replay_by_key[key]
        existing = existing_by_key[key]
        if (
            replay["default_acceptance_status"],
            replay["observation_status"],
        ) != (
            existing["default_acceptance_status"],
            existing["observation_status"],
        ):
            status_mismatches += 1
        if replay["requester_user_id"] and not existing["requester_user_id"]:
            requester_regressions += 1
    return {
        "replay_rows": len(replay_rows),
        "existing_rows": len(existing_rows),
        "common": len(common),
        "missing": len(missing),
        "extra": len(extra),
        "status_mismatches": status_mismatches,
        "requester_regressions": requester_regressions,
        "missing_samples": missing[:5],
    }


def _playback_identity_key(row: dict) -> tuple[object, object, object]:
    return (row["dance_system_key"], row["dance_external_id"], row["played_at"])


def _playback_compare_summary(compare: dict[str, object]) -> str:
    return (
        f"replay={compare['replay_rows']} existing={compare['existing_rows']} "
        f"common={compare['common']} missing={compare['missing']} extra={compare['extra']} "
        f"status_mismatches={compare['status_mismatches']} "
        f"requester_regressions={compare['requester_regressions']}"
    )


def _identity_sample_summary(samples: list[tuple[object, object, object]]) -> str:
    return ", ".join(f"{system}:{external}@{played_at}" for system, external, played_at in samples)


def _vrcx_section(vrcx_db: Path, manual_gt: str | None) -> list[str]:
    if not vrcx_db.exists():
        return ["## VRCX", "", f"- missing VRCX DB: {vrcx_db}", ""]
    start, end = _manual_window_utc(manual_gt)
    try:
        with closing(sqlite3.connect(f"file:{vrcx_db}?mode=ro", uri=True)) as conn:
            count = conn.execute(
                """
                SELECT count(*)
                FROM gamelog_video_play
                WHERE created_at BETWEEN ? AND ?
                """,
                (start, end),
            ).fetchone()[0]
    except sqlite3.Error as exc:
        return ["## VRCX", "", f"- VRCX read failed: {exc}", ""]
    return ["## VRCX", "", f"- rows in manual window: {count}", ""]


def _manual_window_utc(manual_gt: str | None) -> tuple[str, str]:
    rows = _parse_manual_gt(Path(manual_gt)) if manual_gt else []
    if not rows:
        return "2026-05-17T10:00:00.000Z", "2026-05-17T19:00:00.000Z"
    times = [
        datetime(
            2026,
            5,
            17,
            int(row["time"][:2]),
            int(row["time"][3:]),
            tzinfo=MANUAL_GT_TIME_ZONE,
        )
        for row in rows
    ]
    start = min(times) - timedelta(minutes=10)
    end = max(times) + timedelta(minutes=10)
    return _format_utc(start), _format_utc(end)


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _parse_manual_gt(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^(?P<time>\d{1,2}:\d{2})\s+(?P<id>\d+)(?:\s+\((?P<note>.*)\))?", line.strip())
        if not match:
            continue
        note = match.group("note") or ""
        incomplete = "\u6ca1\u653e\u5b8c" in note or "\u63d0\u524d" in note
        rows.append(
            {
                "time": match.group("time").zfill(5),
                "external_id": match.group("id"),
                "note": note,
                "expected_completed": not incomplete,
            }
        )
    return rows


def _matches_manual_row(
    rows: list[sqlite3.Row],
    expected: dict,
    *,
    system_field: str,
    external_id_field: str,
    time_field: str,
    status_field: str | None = None,
    status: str | None = None,
) -> bool:
    expected_at = _manual_local_datetime(expected)
    if expected_at is None:
        return False
    for row in rows:
        if row[system_field] != "wannadance":
            continue
        if str(row[external_id_field]) != expected["external_id"]:
            continue
        if status_field is not None and row[status_field] != status:
            continue
        observed_at = _parse_vrc_local_datetime(row[time_field])
        if observed_at is None:
            continue
        if abs((observed_at - expected_at).total_seconds()) <= MANUAL_MATCH_TOLERANCE_SECONDS:
            return True
    return False


def _missing_manual_diagnostics(missing: list[dict], records: list[sqlite3.Row]) -> list[str]:
    diagnostics: list[str] = []
    for expected in missing:
        record, delta_seconds = _nearest_manual_row(
            records,
            expected,
            system_field="dance_system_key",
            external_id_field="dance_external_id",
            time_field="played_at",
        )
        if record is None:
            diagnostics.append(
                f"{expected['time']} {expected['external_id']}: no matching watcher playback record"
            )
            continue
        diagnostics.append(
            f"{expected['time']} {expected['external_id']}: "
            f"playback_status={record['playback_status'] or 'unknown'}, "
            f"status_reason={record['status_reason'] or 'none'}, "
            f"completion={record['completion_status'] or 'none'}, "
            f"completion_reason={record['completion_reason'] or 'none'}, "
            f"nearest_delta={int(delta_seconds)}s"
        )
    return diagnostics


def _nearest_manual_row(
    rows: list[sqlite3.Row],
    expected: dict,
    *,
    system_field: str,
    external_id_field: str,
    time_field: str,
) -> tuple[sqlite3.Row | None, float]:
    expected_at = _manual_local_datetime(expected)
    if expected_at is None:
        return None, 0
    best_row = None
    best_delta = float("inf")
    for row in rows:
        if row[system_field] != "wannadance":
            continue
        if str(row[external_id_field]) != expected["external_id"]:
            continue
        observed_at = _parse_vrc_local_datetime(row[time_field])
        if observed_at is None:
            continue
        delta = abs((observed_at - expected_at).total_seconds())
        if delta < best_delta:
            best_row = row
            best_delta = delta
    if best_delta > MANUAL_DIAGNOSTIC_TOLERANCE_SECONDS:
        return None, 0
    return best_row, best_delta


def _display_number(value) -> str:
    if value is None:
        return "?"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.3f}".rstrip("0").rstrip(".")


def _manual_local_datetime(row: dict) -> datetime | None:
    try:
        hour, minute = row["time"].split(":", 1)
        return datetime(*MANUAL_GT_DATE, int(hour), int(minute), tzinfo=MANUAL_GT_TIME_ZONE)
    except (KeyError, TypeError, ValueError):
        return None


def _parse_vrc_local_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parse_timestamp(value, local_tz=MANUAL_GT_TIME_ZONE).astimezone(
            MANUAL_GT_TIME_ZONE
        )
    except ValueError:
        return None


def _index_events(events: list[dict]) -> dict[str, dict]:
    return {str(event.get("event_key")): event for event in events if event.get("event_key")}


def _index_rows(rows: list[dict], key_field: str) -> dict[str, dict]:
    return {str(row.get(key_field)): row for row in rows if row.get(key_field)}


def _stable_event(event: dict) -> dict:
    return _stable_value(event)


def _stable_value(value):
    if isinstance(value, dict):
        return {
            key: _stable_value(item)
            for key, item in value.items()
            if key not in IGNORED_JSON_FIELDS
        }
    if isinstance(value, list):
        return [_stable_value(item) for item in value]
    return value


def _changed_field_counts(
    base_events: dict[str, dict],
    run_events: dict[str, dict],
    changed_keys: list[str],
) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for key in changed_keys:
        base = _stable_event(base_events[key])
        run = _stable_event(run_events[key])
        for field_name in set(base) | set(run):
            if base.get(field_name) != run.get(field_name):
                counts[field_name] = counts.get(field_name, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def _changed_field_counts_for_pairs(pairs) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for base_event, run_event in pairs:
        base = _stable_event(base_event)
        run = _stable_event(run_event)
        if not isinstance(base, dict) or not isinstance(run, dict):
            if base != run:
                counts["<row>"] = counts.get("<row>", 0) + 1
            continue
        for field_name in set(base) | set(run):
            if base.get(field_name) != run.get(field_name):
                counts[field_name] = counts.get(field_name, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def _field_count_summary(changed_field_counts: list[tuple[str, int]]) -> str:
    return ", ".join(f"{name}={count}" for name, count in changed_field_counts[:12])


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    main()
