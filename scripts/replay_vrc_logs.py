"""Replay fixed VRChat log corpora and compare watcher outputs."""

from __future__ import annotations

import argparse
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
    report.extend(_playback_diff_section(baseline, output))

    if args.manual_gt:
        report.extend(_manual_gt_section(Path(args.manual_gt), output / "live.sqlite3"))
    if args.vrcx_db:
        report.extend(_vrcx_section(Path(args.vrcx_db), args.manual_gt))

    (output / "diff_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "diff_report": str(output / "diff_report.md")}))


def _run_replay(*, log_dir: Path, pattern: str, output: Path):
    from dancing_log.vrc_log_watcher import replay_vrc_log_files

    log_files = sorted(log_dir.glob(pattern), key=lambda path: path.name)
    if not log_files:
        raise SystemExit(f"No logs matched {pattern} in {log_dir}")
    return replay_vrc_log_files(
        log_files=log_files,
        output_dir=output,
        app_db_path=output / "live.sqlite3",
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


def _playback_diff_section(baseline: Path, output: Path) -> list[str]:
    base_path = baseline / "playback_events.jsonl"
    run_path = output / "playback_events.jsonl"
    if not base_path.exists():
        return ["## Playback Diff", "", f"- baseline missing: {base_path}", ""]

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
            field_summary = ", ".join(
                f"{name}={count}" for name, count in changed_field_counts[:12]
            )
            lines.append(f"- changed field counts: {field_summary}")
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
    return lines


def _manual_gt_section(manual_gt: Path, db_path: Path) -> list[str]:
    expected = _parse_manual_gt(manual_gt)
    if not expected:
        return ["## Manual GT", "", f"- no manual GT rows parsed from {manual_gt}", ""]
    if not db_path.exists():
        return ["## Manual GT", "", f"- live DB missing: {db_path}", ""]

    with sqlite3.connect(db_path) as conn:
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
        with sqlite3.connect(f"file:{vrcx_db}?mode=ro", uri=True) as conn:
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


def _stable_event(event: dict) -> dict:
    ignored = {"captured_at", "received_at"}
    return {key: value for key, value in event.items() if key not in ignored}


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


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    main()
