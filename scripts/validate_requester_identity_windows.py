"""Validate requester identity enrichment against random source-log windows.

This is intentionally a local validation script, not a default unit test. It
depends on private/local VRChat source logs under logs/source-vrc-logs.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
import random
import sqlite3
import sys
import tempfile
import threading
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dancing_log.storage import connect_db  # noqa: E402
from dancing_log.vrc_log_utils import extract_timestamp, parse_vrc_timestamp  # noqa: E402
from dancing_log.vrc_log_watcher import replay_vrc_log_files, watch_vrc_logs  # noqa: E402


DEFAULT_SEED = 20260624
DEFAULT_WINDOWS = 20
DEFAULT_MIN_MINUTES = 10
DEFAULT_MAX_MINUTES = 45
DEFAULT_CONTEXT_BYTES = 4 * 1024 * 1024
WATCHER_SOURCE_TABLE = "watcher_playback_events"

ALLOWED_WARNING_CATEGORIES = {
    "display_name_user_id_changed",
    "expired_backfill",
    "expired_lookup",
    "missing_room_context",
    "preread",
    "unpaired_player_left",
}


@dataclass(frozen=True)
class SourceLine:
    source_file: Path
    line_number: int
    timestamp: datetime
    text: str
    byte_length: int


@dataclass(frozen=True)
class WindowSpec:
    index: int
    start: datetime
    end: datetime
    lines: list[SourceLine]
    context_lines: list[SourceLine]

    @property
    def source_files(self) -> list[str]:
        return sorted({line.source_file.name for line in self.lines})


@dataclass(frozen=True)
class RunSummary:
    mode: str
    stats: dict
    playback_events: int
    playback_events_with_id: int
    event_source_counts: dict[str, int]
    records: int
    records_with_id: int
    pending_records: int
    id_preservation_failures: int
    warning_categories: dict[str, int]
    unknown_warnings: list[str]
    coverage: float


@dataclass(frozen=True)
class WindowResult:
    window: WindowSpec
    replay: RunSummary
    tail: RunSummary
    failures: list[str]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.long:
        args.windows = 100
        args.min_minutes = 30
        args.max_minutes = 180

    log_dir = Path(args.log_dir)
    if not log_dir.exists():
        print(f"source log directory not found: {log_dir}", file=sys.stderr)
        return 2

    source_lines = load_source_lines(log_dir)
    if not source_lines:
        print(f"no timestamped source-log lines found in {log_dir}", file=sys.stderr)
        return 2

    rng = random.Random(args.seed)
    windows = sample_windows(
        source_lines,
        rng=rng,
        count=args.windows,
        min_minutes=args.min_minutes,
        max_minutes=args.max_minutes,
        context_bytes=args.context_bytes,
    )

    failures: list[WindowResult] = []
    for window in windows:
        result = validate_window(window, idle_seconds=args.idle_seconds)
        print(window_report(result))
        if result.failures:
            failures.append(result)

    if failures:
        print(f"\nFAILED seed={args.seed} failures={len(failures)}/{len(windows)}")
        for result in failures:
            print(failure_report(result))
        return 1

    print(f"\nOK seed={args.seed} windows={len(windows)}")
    return 0


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--windows", type=int, default=DEFAULT_WINDOWS)
    parser.add_argument("--min-minutes", type=int, default=DEFAULT_MIN_MINUTES)
    parser.add_argument("--max-minutes", type=int, default=DEFAULT_MAX_MINUTES)
    parser.add_argument("--context-bytes", type=int, default=DEFAULT_CONTEXT_BYTES)
    parser.add_argument("--idle-seconds", type=float, default=1.0)
    parser.add_argument("--log-dir", default=str(ROOT / "logs" / "source-vrc-logs"))
    parser.add_argument(
        "--long",
        action="store_true",
        help="Run 100 windows of 30-180 minutes each.",
    )
    return parser.parse_args(argv)


def load_source_lines(log_dir: Path) -> list[SourceLine]:
    lines: list[SourceLine] = []
    for path in sorted(log_dir.glob("output_log_*.txt")):
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_number, text in enumerate(handle, start=1):
                timestamp_text = extract_timestamp(text)
                timestamp = parse_vrc_timestamp(timestamp_text)
                if timestamp is None:
                    continue
                lines.append(
                    SourceLine(
                        source_file=path,
                        line_number=line_number,
                        timestamp=timestamp,
                        text=text,
                        byte_length=len(text.encode("utf-8")),
                    )
                )
    return sorted(lines, key=lambda line: (line.timestamp, line.source_file.name, line.line_number))


def sample_windows(
    source_lines: list[SourceLine],
    *,
    rng: random.Random,
    count: int,
    min_minutes: int,
    max_minutes: int,
    context_bytes: int,
) -> list[WindowSpec]:
    windows: list[WindowSpec] = []
    max_start_index = max(0, len(source_lines) - 1)
    for index in range(max(0, count)):
        start_index = rng.randint(0, max_start_index)
        start = source_lines[start_index].timestamp
        duration = timedelta(minutes=rng.randint(min_minutes, max_minutes))
        end = start + duration
        window_lines = [
            line for line in source_lines[start_index:] if start <= line.timestamp < end
        ]
        context_lines = context_before(source_lines, start_index, max_bytes=context_bytes)
        windows.append(
            WindowSpec(
                index=index,
                start=start,
                end=end,
                lines=window_lines,
                context_lines=context_lines,
            )
        )
    return windows


def context_before(
    source_lines: list[SourceLine],
    start_index: int,
    *,
    max_bytes: int,
) -> list[SourceLine]:
    selected: list[SourceLine] = []
    total_bytes = 0
    for line in reversed(source_lines[:start_index]):
        if total_bytes + line.byte_length > max_bytes:
            break
        selected.append(line)
        total_bytes += line.byte_length
    return list(reversed(selected))


def validate_window(window: WindowSpec, *, idle_seconds: float) -> WindowResult:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        replay = run_replay(window, tmp_path / "replay")
        tail = run_tail(window, tmp_path / "tail", idle_seconds=idle_seconds)

    failures = invariants(window, replay, tail)
    return WindowResult(window=window, replay=replay, tail=tail, failures=failures)


def run_replay(window: WindowSpec, output_root: Path) -> RunSummary:
    log_dir = output_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"window_{window.index:04d}.txt"
    write_lines(log_path, window.lines)
    db_path = output_root / "app.sqlite3"
    stats = replay_vrc_log_files(
        log_files=[log_path],
        output_dir=output_root / "capture",
        app_db_path=db_path,
        include_raw=False,
        live_db=False,
        record_playback=True,
    )
    return summarize_run("replay", stats.session_dir, db_path, stats.to_dict())


def run_tail(window: WindowSpec, output_root: Path, *, idle_seconds: float) -> RunSummary:
    log_dir = output_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "output_log_0001.txt"
    write_lines(log_path, window.context_lines)
    db_path = output_root / "app.sqlite3"
    result: dict[str, object] = {}
    stop_event = threading.Event()
    tail_ready_event = threading.Event()

    def watch() -> None:
        result["stats"] = watch_vrc_logs(
            log_dir=log_dir,
            output_dir=output_root / "capture",
            session_name=f"tail_window_{window.index:04d}",
            app_db_path=db_path,
            from_start=False,
            include_raw=False,
            live_db=False,
            record_playback=True,
            archive_source_logs=False,
            poll_seconds=0.01,
            stop_after_idle_seconds=idle_seconds,
            stop_event=stop_event,
            tail_ready_event=tail_ready_event,
        )

    thread = threading.Thread(target=watch)
    thread.start()
    if not tail_ready_event.wait(timeout=5.0):
        stop_event.set()
        thread.join(timeout=5.0)
        raise RuntimeError(f"tail watcher did not reach EOF before append for window {window.index}")
    append_lines(log_path, window.lines)
    thread.join(timeout=max(10.0, idle_seconds + 5.0))
    if thread.is_alive():
        stop_event.set()
        thread.join(timeout=5.0)
    if thread.is_alive():
        raise RuntimeError(f"tail watcher did not stop for window {window.index}")
    stats = result["stats"]
    return summarize_run("tail", stats.session_dir, db_path, stats.to_dict())


def summarize_run(mode: str, session_dir: Path, db_path: Path, stats: dict) -> RunSummary:
    playback_path = session_dir / "playback_events.jsonl"
    playback_events = read_jsonl(playback_path)
    event_source_counts = Counter(
        str(event.get("requester_user_id_source") or "none") for event in playback_events
    )
    playback_events_with_id = sum(1 for event in playback_events if event.get("requester_user_id"))
    db_summary = summarize_db(db_path)
    records = db_summary["records"]
    records_with_id = db_summary["records_with_id"]
    coverage = records_with_id / records if records else 1.0
    warnings = [str(warning) for warning in stats.get("warnings") or []]
    warning_categories = Counter(warning_category(warning) for warning in warnings)
    unknown_warnings = [
        warning for warning in warnings if warning_category(warning) not in ALLOWED_WARNING_CATEGORIES
    ]
    return RunSummary(
        mode=mode,
        stats=stats,
        playback_events=len(playback_events),
        playback_events_with_id=playback_events_with_id,
        event_source_counts=dict(sorted(event_source_counts.items())),
        records=records,
        records_with_id=records_with_id,
        pending_records=db_summary["pending_records"],
        id_preservation_failures=db_summary["id_preservation_failures"],
        warning_categories=dict(sorted(warning_categories.items())),
        unknown_warnings=unknown_warnings,
        coverage=coverage,
    )


def summarize_db(db_path: Path) -> dict[str, int]:
    with connect_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                pr.id,
                pr.requester_user_id,
                pr.default_acceptance_status,
                pro.origin_json
            FROM playback_records pr
            JOIN playback_record_origins pro
                ON pro.playback_record_id = pr.id
            WHERE pr.evidence_source = ?
                AND pro.origin_table = ?
            ORDER BY pr.id, pro.id
            """,
            ("vrc_log_live", WATCHER_SOURCE_TABLE),
        ).fetchall()

    records_by_id: dict[int, sqlite3.Row] = {}
    origin_user_ids_by_record_id: dict[int, set[str]] = {}
    for row in rows:
        record_id = int(row["id"])
        records_by_id.setdefault(record_id, row)
        origin_user_id = requester_user_id_from_origin_json(row["origin_json"])
        if origin_user_id:
            origin_user_ids_by_record_id.setdefault(record_id, set()).add(origin_user_id)

    id_preservation_failures = 0
    for record_id, row in records_by_id.items():
        main_user_id = normalized_user_id(row["requester_user_id"])
        origin_user_ids = origin_user_ids_by_record_id.get(record_id, set())
        if origin_user_ids and main_user_id not in origin_user_ids:
            id_preservation_failures += 1
    return {
        "records": len(records_by_id),
        "records_with_id": sum(1 for row in records_by_id.values() if row["requester_user_id"]),
        "pending_records": sum(
            1
            for row in records_by_id.values()
            if row["default_acceptance_status"] == "pending"
        ),
        "id_preservation_failures": id_preservation_failures,
    }


def requester_user_id_from_origin_json(origin_json: object) -> str | None:
    try:
        origin = json.loads(str(origin_json or "{}"))
    except json.JSONDecodeError:
        return None
    event = origin.get("watcher_playback_event")
    if not isinstance(event, dict):
        return None
    value = str(event.get("requester_user_id") or "").strip()
    return value or None


def normalized_user_id(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def invariants(window: WindowSpec, replay: RunSummary, tail: RunSummary) -> list[str]:
    failures: list[str] = []
    for summary in (replay, tail):
        errors = summary.stats.get("errors") or []
        if errors:
            failures.append(f"{summary.mode}: errors={errors}")
        if summary.pending_records:
            failures.append(f"{summary.mode}: pending_records={summary.pending_records}")
        if summary.unknown_warnings:
            failures.append(f"{summary.mode}: unknown_warnings={summary.unknown_warnings}")
        if summary.id_preservation_failures:
            failures.append(
                f"{summary.mode}: id_preservation_failures={summary.id_preservation_failures}"
            )

    tail_against_replay_coverage = (
        tail.records_with_id / replay.records if replay.records else 1.0
    )
    if tail.records != replay.records:
        failures.append(
            "tail record count differs from replay: "
            f"tail_records={tail.records} replay_records={replay.records}"
        )
    if tail_against_replay_coverage + 1e-9 < replay.coverage:
        failures.append(
            "tail coverage below replay coverage: "
            f"tail_vs_replay={tail_against_replay_coverage:.3f} "
            f"replay={replay.coverage:.3f}"
        )
    if not window.lines:
        failures.append("empty window")
    return failures


def warning_category(warning: str) -> str:
    if "used expired mapping" in warning:
        return "expired_lookup"
    if "backfilled" in warning and "expired mapping" in warning:
        return "expired_backfill"
    if "could not resolve" in warning:
        return "missing_room_context"
    if "changed for" in warning:
        return "display_name_user_id_changed"
    if "OnPlayerLeft without active mapping" in warning:
        return "unpaired_player_left"
    if "preread" in warning:
        return "preread"
    return "unknown"


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def write_lines(path: Path, lines: Iterable[SourceLine]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        for line in lines:
            handle.write(line.text)


def append_lines(path: Path, lines: Iterable[SourceLine]) -> None:
    with path.open("a", encoding="utf-8", newline="") as handle:
        for line in lines:
            handle.write(line.text)


def window_report(result: WindowResult) -> str:
    window = result.window
    status = "FAIL" if result.failures else "OK"
    return (
        f"{status} window={window.index} "
        f"{format_time(window.start)}..{format_time(window.end)} "
        f"lines={len(window.lines)} files={','.join(window.source_files)} "
        f"replay_records={result.replay.records} replay_cov={result.replay.coverage:.3f} "
        f"tail_records={result.tail.records} tail_cov={result.tail.coverage:.3f} "
        f"tail_vs_replay_cov={tail_vs_replay_coverage(result):.3f} "
        f"tail_warnings={result.tail.warning_categories}"
    )


def failure_report(result: WindowResult) -> str:
    window = result.window
    return (
        f"- window={window.index} {format_time(window.start)}..{format_time(window.end)} "
        f"files={','.join(window.source_files)} failures={result.failures} "
        f"replay_sources={result.replay.event_source_counts} "
        f"tail_sources={result.tail.event_source_counts} "
        f"replay_warnings={result.replay.warning_categories} "
        f"tail_warnings={result.tail.warning_categories}"
    )


def tail_vs_replay_coverage(result: WindowResult) -> float:
    if not result.replay.records:
        return 1.0
    return result.tail.records_with_id / result.replay.records


def format_time(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S")


if __name__ == "__main__":
    raise SystemExit(main())
