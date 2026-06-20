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
MANUAL_GT_DATE = (2026, 5, 17)
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
        f"- live promotions: {stats.live_promotions}",
        f"- promotion threshold: {_promotion_threshold_label()} of known duration",
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
        f"- live promotions: {stats.live_promotions}",
        f"- promotion threshold: {_promotion_threshold_label()} of known duration",
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

    dance_section, dance_failed = _dance_events_diff_section(baseline, output)
    report.extend(dance_section)
    if dance_failed:
        failed_sections.append("live.sqlite3:dance_events")

    if args.manual_gt:
        report.extend(_manual_gt_section(Path(args.manual_gt), output / "live.sqlite3"))
    if args.vrcx_db:
        report.extend(_vrcx_section(Path(args.vrcx_db), args.manual_gt))

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
    from dancing_log.vrc_log_watcher import replay_vrc_log_files

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
        promote_live=True,
    )


def _promotion_threshold_label() -> str:
    from dancing_log.vrc_log_watcher import PROMOTION_COMPLETION_RATIO

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


def _dance_events_diff_section(baseline: Path, output: Path) -> tuple[list[str], bool]:
    return _sqlite_indexed_diff_section(
        label="Promoted Dance Events SQLite Diff",
        baseline=baseline,
        output=output,
        rows_reader=_read_dance_event_rows,
        key_field="event_key",
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


def _read_dance_event_rows(db_path: Path) -> list[dict]:
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                de.event_key,
                de.played_at,
                ds.key AS dance_system_key,
                dt.external_id AS dance_external_id,
                de.source,
                de.confidence,
                de.event_source,
                de.video_url,
                de.video_name,
                de.requester_display_name,
                de.requester_user_id,
                de.location,
                de.note,
                de.recording_id,
                de.recording_offset_seconds
            FROM dance_events de
            LEFT JOIN dance_tracks dt ON dt.id = de.dance_track_id
            LEFT JOIN dance_systems ds ON ds.id = dt.system_id
            ORDER BY de.event_key
            """
        ).fetchall()
    return [dict(row) for row in rows]


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
        promoted = conn.execute(
            """
            SELECT de.played_at, ds.key AS system_key, dt.external_id
            FROM dance_events de
            JOIN dance_tracks dt ON dt.id = de.dance_track_id
            JOIN dance_systems ds ON ds.id = dt.system_id
            ORDER BY de.played_at
            """
        ).fetchall()
        live = conn.execute(
            """
            SELECT actual_play_at, dance_system_key, dance_external_id,
                   completion_status, completion_reason,
                   played_seconds, required_played_seconds
            FROM live_playback_events
            ORDER BY actual_play_at, first_seen_at
            """
        ).fetchall()

    should_promote = [row for row in expected if row["expected_completed"]]
    should_not_promote = [row for row in expected if not row["expected_completed"]]
    missing = [
        row
        for row in should_promote
        if not _matches_manual_row(
            promoted,
            row,
            system_field="system_key",
            external_id_field="external_id",
            time_field="played_at",
        )
    ]
    unexpected = [
        row
        for row in should_not_promote
        if _matches_manual_row(
            promoted,
            row,
            system_field="system_key",
            external_id_field="external_id",
            time_field="played_at",
        )
    ]
    interrupted_ok = [
        row
        for row in should_not_promote
        if _matches_manual_row(
            live,
            row,
            system_field="dance_system_key",
            external_id_field="dance_external_id",
            time_field="actual_play_at",
            status_field="completion_status",
            status="interrupted",
        )
    ]

    lines = [
        "## Manual GT",
        "",
        f"- manual rows: {len(expected)}",
        f"- expected promotions: {len(should_promote)}",
        f"- missing expected promotions: {len(missing)}",
        f"- unexpected promotions: {len(unexpected)}",
        f"- expected non-promotions interrupted: {len(interrupted_ok)}/{len(should_not_promote)}",
    ]
    if missing:
        lines.append("- missing: " + ", ".join(f"{row['time']} {row['external_id']}" for row in missing))
        diagnostics = _missing_manual_diagnostics(missing, live)
        if diagnostics:
            lines.append("- needs_human_confirmation:")
            lines.extend(f"  - {line}" for line in diagnostics)
    if unexpected:
        lines.append("- unexpected: " + ", ".join(f"{row['time']} {row['external_id']}" for row in unexpected))
    lines.append("")
    return lines


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
    local_tz = timezone(timedelta(hours=8))
    times = [
        datetime(2026, 5, 17, int(row["time"][:2]), int(row["time"][3:]), tzinfo=local_tz)
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


def _missing_manual_diagnostics(missing: list[dict], live_rows: list[sqlite3.Row]) -> list[str]:
    diagnostics: list[str] = []
    for expected in missing:
        live_row, delta_seconds = _nearest_manual_row(
            live_rows,
            expected,
            system_field="dance_system_key",
            external_id_field="dance_external_id",
            time_field="actual_play_at",
        )
        if live_row is None:
            diagnostics.append(
                f"{expected['time']} {expected['external_id']}: no matching live playback row"
            )
            continue
        diagnostics.append(
            f"{expected['time']} {expected['external_id']}: "
            f"live={live_row['completion_status'] or 'pending'}, "
            f"reason={live_row['completion_reason'] or 'none'}, "
            f"played={_display_number(live_row['played_seconds'])}/"
            f"{_display_number(live_row['required_played_seconds'])}s, "
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
        return datetime(*MANUAL_GT_DATE, int(hour), int(minute))
    except (KeyError, TypeError, ValueError):
        return None


def _parse_vrc_local_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y.%m.%d %H:%M:%S.%f", "%Y.%m.%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
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
