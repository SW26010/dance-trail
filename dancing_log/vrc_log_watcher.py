"""Lightweight VRChat output log watcher for playback forensics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from functools import wraps
from pathlib import Path
import json
import os
import threading
import time
from typing import ParamSpec, TypeVar, cast

from dancing_log.app_paths import AppPaths
from dancing_log.time_utils import now_utc_iso
from dancing_log.live_playback_folding import (
    PREVIEW_SUPPRESSION_SECONDS,
    RETRY_MERGE_SECONDS,
    PlaybackEventBuilder,
    playback_delay_metrics,
)
from dancing_log.live_playback_runtime import LivePlaybackOverlay, LivePlaybackRuntime
from dancing_log.live_playback_settlement import (
    COMPLETION_EPSILON_SECONDS,
    PROMOTION_COMPLETION_RATIO,
)
from dancing_log.requester_identity_enrichment import RequesterIdentityEnricher
from dancing_log.vrc_log_utils import (
    extract_timestamp,
    timestamp_before,
    trim_newline,
)
from dancing_log.vrc_log_parser import (
    ParsedVrcLogEvent,
    is_identity_candidate_line,
    is_lifecycle_candidate_line,
    is_video_candidate_line,
    parse_vrc_identity_event,
    parse_vrc_lifecycle_event,
    parse_vrc_log_line,
)
from dancing_log.watcher_lifetime_lock import WatcherLifetimeLease


LOG_FILE_PATTERN = "output_log_*.txt"
SOURCE_LOG_COPY_CHUNK_BYTES = 4 * 1024 * 1024
REQUESTER_IDENTITY_PREREAD_MAX_BYTES = 4 * 1024 * 1024
_WatchArgs = ParamSpec("_WatchArgs")
_WatchResult = TypeVar("_WatchResult")

__all__ = [
    "COMPLETION_EPSILON_SECONDS",
    "LOG_FILE_PATTERN",
    "PROMOTION_COMPLETION_RATIO",
    "PREVIEW_SUPPRESSION_SECONDS",
    "RETRY_MERGE_SECONDS",
    "ParsedVrcLogEvent",
    "PlaybackEventBuilder",
    "WatchStats",
    "default_vrc_log_dir",
    "is_identity_candidate_line",
    "is_lifecycle_candidate_line",
    "is_video_candidate_line",
    "parse_vrc_identity_event",
    "parse_vrc_lifecycle_event",
    "parse_vrc_log_line",
    "replay_vrc_log_files",
    "watch_vrc_logs",
]


@dataclass
class WatchStats:
    """Summary of one watcher session."""

    session_dir: Path
    started_at: str
    ended_at: str | None = None
    raw_lines: int = 0
    candidate_lines: int = 0
    parsed_events: int = 0
    lifecycle_events: int = 0
    identity_events: int = 0
    playback_events: int = 0
    delay_metrics: dict[str, float | int | None] = field(default_factory=dict)
    parser_counts: dict[str, int] = field(default_factory=dict)
    requester_identity: dict[str, int | str] = field(default_factory=dict)
    last_file: str | None = None
    last_offset: int = 0
    last_log_timestamp: str | None = None
    idle_stopped: bool = False
    live_session_id: str | None = None
    live_db_updates: int = 0
    live_promotions: int = 0
    playback_record_updates: int = 0
    overlay_url: str | None = None
    stop_requested: bool = False
    replayed_files: list[str] = field(default_factory=list)
    source_log_dir: str | None = None
    source_log_bytes: int = 0
    source_log_files: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "session_dir": str(self.session_dir),
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "raw_lines": self.raw_lines,
            "candidate_lines": self.candidate_lines,
            "parsed_events": self.parsed_events,
            "lifecycle_events": self.lifecycle_events,
            "identity_events": self.identity_events,
            "playback_events": self.playback_events,
            "delay_metrics": self.delay_metrics,
            "parser_counts": dict(sorted(self.parser_counts.items())),
            "requester_identity": dict(sorted(self.requester_identity.items())),
            "last_file": self.last_file,
            "last_offset": self.last_offset,
            "last_log_timestamp": self.last_log_timestamp,
            "idle_stopped": self.idle_stopped,
            "live_session_id": self.live_session_id,
            "live_db_updates": self.live_db_updates,
            "live_promotions": self.live_promotions,
            "playback_record_updates": self.playback_record_updates,
            "overlay_url": self.overlay_url,
            "stop_requested": self.stop_requested,
            "replayed_files": self.replayed_files,
            "source_log_dir": self.source_log_dir,
            "source_log_bytes": self.source_log_bytes,
            "source_log_files": self.source_log_files,
            "warnings": self.warnings,
            "errors": self.errors,
        }


class _SourceLogMirror:
    """Incrementally mirror source VRChat log bytes without involving parsers."""

    def __init__(
        self,
        *,
        archive_dir: Path,
        errors: list[str],
        max_bytes_per_tick: int = SOURCE_LOG_COPY_CHUNK_BYTES,
    ) -> None:
        self.archive_dir = archive_dir
        self.errors = errors
        self.max_bytes_per_tick = max(1, int(max_bytes_per_tick))
        self.bytes_copied = 0
        self._files: dict[str, dict] = {}

    def mirror_file(self, source_path: Path, *, final: bool = False) -> bool:
        source = Path(source_path)
        try:
            source_size = source.stat().st_size
        except OSError as exc:
            _record_error(self.errors, f"source log stat failed for {source}: {exc}")
            return False

        destination = self.archive_dir / source.name
        entry = self._entry(source, destination)
        entry["source_size"] = source_size

        try:
            destination_size = destination.stat().st_size if destination.exists() else 0
        except OSError as exc:
            _record_error(self.errors, f"source log archive stat failed for {destination}: {exc}")
            return False

        if destination_size > source_size:
            entry["archived_bytes"] = destination_size
            entry["complete"] = False
            _record_error(
                self.errors,
                f"source log archive is larger than source for {source.name}; not appending",
            )
            return False

        bytes_to_copy = source_size - destination_size
        if bytes_to_copy <= 0:
            entry["archived_bytes"] = destination_size
            entry["complete"] = True
            if final and destination.exists():
                try:
                    with destination.open("ab") as dest_handle:
                        dest_handle.flush()
                        os.fsync(dest_handle.fileno())
                except OSError as exc:
                    _record_error(
                        self.errors,
                        f"source log archive sync failed for {destination}: {exc}",
                    )
            return False

        limit = None if final else min(bytes_to_copy, self.max_bytes_per_tick)
        copied = 0
        try:
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            with source.open("rb") as source_handle, destination.open("ab") as dest_handle:
                source_handle.seek(destination_size)
                while limit is None or copied < limit:
                    read_size = 1024 * 1024
                    if limit is not None:
                        read_size = min(read_size, limit - copied)
                    if read_size <= 0:
                        break
                    chunk = source_handle.read(read_size)
                    if not chunk:
                        break
                    dest_handle.write(chunk)
                    copied += len(chunk)
                if final:
                    dest_handle.flush()
                    os.fsync(dest_handle.fileno())
        except OSError as exc:
            _record_error(self.errors, f"source log archive failed for {source}: {exc}")
            return False

        self.bytes_copied += copied
        archived_bytes = destination_size + copied
        entry["archived_bytes"] = archived_bytes
        try:
            entry["source_size"] = source.stat().st_size
        except OSError:
            pass
        entry["complete"] = archived_bytes >= int(entry["source_size"])
        return copied > 0

    def to_summary(self) -> list[dict]:
        return [self._files[key] for key in sorted(self._files)]

    def _entry(self, source: Path, destination: Path) -> dict:
        key = str(source)
        if key not in self._files:
            self._files[key] = {
                "source_file": str(source),
                "archived_file": str(destination),
                "source_size": 0,
                "archived_bytes": 0,
                "complete": False,
            }
        return self._files[key]


def default_vrc_log_dir() -> Path:
    """Return VRChat's default Windows output log directory."""
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        local_path = Path(local_appdata)
        if local_path.name.lower() == "local":
            return local_path.with_name("LocalLow") / "VRChat" / "VRChat"
        return Path(f"{local_appdata}Low") / "VRChat" / "VRChat"
    return Path.home() / "AppData" / "LocalLow" / "VRChat" / "VRChat"


def _owns_watcher_lifetime(
    watch: Callable[_WatchArgs, _WatchResult],
) -> Callable[_WatchArgs, _WatchResult]:
    """Make the public watcher seam enforce app/database lifetime ownership."""

    @wraps(watch)
    def owned(*args: _WatchArgs.args, **kwargs: _WatchArgs.kwargs) -> _WatchResult:
        app_root = cast(Path | str | None, kwargs.get("app_root"))
        app_paths = AppPaths.from_root(app_root)
        app_db_path = cast(Path | str | None, kwargs.get("app_db_path")) or app_paths.db_file
        supplied = cast(
            WatcherLifetimeLease | None,
            kwargs.pop("_watcher_lifetime_lease", None),
        )
        if supplied is not None:
            supplied.verify_scope(
                app_root=app_paths.app_root,
                app_db_path=app_db_path,
            )
            return watch(*args, **kwargs)
        with WatcherLifetimeLease.acquire(
            app_root=app_paths.app_root,
            app_db_path=app_db_path,
        ):
            return watch(*args, **kwargs)

    return owned


@_owns_watcher_lifetime
def watch_vrc_logs(
    *,
    app_root: Path | str | None = None,
    log_dir: Path | str | None = None,
    output_dir: Path | str | None = None,
    session_name: str | None = None,
    app_db_path: Path | str | None = None,
    from_start: bool = False,
    include_raw: bool = True,
    live_db: bool = False,
    record_playback: bool = False,
    overlay_port: int | None = None,
    overlay: LivePlaybackOverlay | None = None,
    poll_seconds: float = 0.25,
    stop_after_idle_seconds: float | None = None,
    stop_event: threading.Event | None = None,
    archive_source_logs: bool = True,
    source_log_dir: Path | str | None = None,
    source_log_copy_bytes_per_tick: int = SOURCE_LOG_COPY_CHUNK_BYTES,
    tail_ready_event: threading.Event | None = None,
) -> WatchStats:
    """Tail VRChat output logs and write raw/candidate/parsed capture artifacts."""
    resolved_log_dir = Path(log_dir) if log_dir is not None else default_vrc_log_dir()
    _validate_log_dir(resolved_log_dir)
    app_paths = AppPaths.from_root(app_root)
    capture_root = Path(output_dir) if output_dir is not None else app_paths.capture_dir
    resolved_source_log_dir = _resolve_source_log_dir(
        source_log_dir=source_log_dir,
        output_dir=output_dir,
        capture_root=capture_root,
        default_source_log_dir=app_paths.source_vrc_log_dir,
    )
    session_dir = capture_root / (session_name or datetime.now().strftime("%Y-%m-%d_%H%M%S"))
    session_dir.mkdir(parents=True, exist_ok=True)

    stats = WatchStats(session_dir=session_dir, started_at=_utc_now())
    stats.live_session_id = _live_session_id(session_dir, stats.started_at)
    if record_playback:
        _repair_stale_watcher_pending_records(app_db_path, stats.errors)
    if archive_source_logs:
        stats.source_log_dir = str(resolved_source_log_dir)
    initial_latest = _latest_log_file(resolved_log_dir, stats.errors)
    opened_any_file = False
    current_path: Path | None = None
    current_handle = None
    current_line_number = 0
    idle_since = time.monotonic()
    runtime = LivePlaybackRuntime(
        stats=stats,
        app_db_path=app_db_path,
        live_db=live_db,
        record_playback=record_playback,
        overlay_port=overlay_port,
        overlay=overlay,
    )
    playback_builder = runtime.create_playback_builder()
    identity_enricher = RequesterIdentityEnricher(warnings=stats.warnings)

    raw_handle = None
    candidates_handle = None
    parsed_handle = None
    source_mirror = (
        _SourceLogMirror(
            archive_dir=resolved_source_log_dir,
            errors=stats.errors,
            max_bytes_per_tick=source_log_copy_bytes_per_tick,
        )
        if archive_source_logs
        else None
    )
    ended_normally = False
    primary_error: BaseException | None = None

    try:
        if include_raw:
            raw_handle = open(
                session_dir / "raw_output_log.txt",
                "a",
                encoding="utf-8",
                errors="replace",
                buffering=1,
            )
        candidates_handle = open(
            session_dir / "candidates.jsonl",
            "a",
            encoding="utf-8",
            buffering=1,
        )
        parsed_handle = open(
            session_dir / "parsed_events.jsonl",
            "a",
            encoding="utf-8",
            buffering=1,
        )

        while True:
            if stop_event is not None and stop_event.is_set():
                stats.stop_requested = True
                break
            latest_path = _latest_log_file(resolved_log_dir, stats.errors)
            if source_mirror is not None and latest_path is not None:
                source_mirror.mirror_file(latest_path)
            if latest_path and latest_path != current_path:
                if current_path is None or _is_newer_log(latest_path, current_path):
                    if current_handle is not None:
                        current_handle.close()
                    if source_mirror is not None and current_path is not None:
                        source_mirror.mirror_file(current_path, final=True)
                    current_path = latest_path
                    current_line_number = 0
                    start_offset = _start_offset(
                        latest_path,
                        initial_latest=initial_latest,
                        opened_any_file=opened_any_file,
                        from_start=from_start,
                    )
                    if not opened_any_file and start_offset > 0:
                        _prime_requester_identity_from_log(
                            path=latest_path,
                            end_offset=start_offset,
                            identity_enricher=identity_enricher,
                            stats=stats,
                        )
                    current_handle = open(
                        latest_path,
                        "r",
                        encoding="utf-8",
                        errors="replace",
                    )
                    current_handle.seek(start_offset)
                    if tail_ready_event is not None:
                        tail_ready_event.set()
                    stats.last_file = str(latest_path)
                    stats.last_offset = start_offset
                    opened_any_file = True
                    idle_since = time.monotonic()

            made_progress = False
            if current_handle is not None and current_path is not None:
                made_progress, current_line_number = _drain_handle(
                    current_handle=current_handle,
                    current_path=current_path,
                    raw_handle=raw_handle,
                    candidates_handle=candidates_handle,
                    parsed_handle=parsed_handle,
                    stats=stats,
                    playback_builder=playback_builder,
                    identity_enricher=identity_enricher,
                    line_number=current_line_number,
                    lifecycle_event_callback=runtime.observe_lifecycle_event,
                )

                try:
                    if current_path.stat().st_size < stats.last_offset:
                        current_handle.close()
                        current_handle = None
                        current_path = None
                        current_line_number = 0
                except OSError as exc:
                    _record_error(stats.errors, f"stat failed for {current_path}: {exc}")

            if made_progress:
                idle_since = time.monotonic()
            else:
                if (
                    stop_after_idle_seconds is not None
                    and time.monotonic() - idle_since >= stop_after_idle_seconds
                ):
                    stats.idle_stopped = True
                    break
                time.sleep(max(poll_seconds, 0.01))
        ended_normally = True
    except KeyboardInterrupt:
        # Ctrl-C is an explicit operator stop, not an unexpected watcher crash.
        ended_normally = True
    except BaseException as exc:
        primary_error = exc
    finally:
        cleanup_errors: list[Exception] = []
        stats.ended_at = _utc_now()
        if current_handle is not None:
            _attempt_cleanup(cleanup_errors, current_handle.close)
        if source_mirror is not None and current_path is not None:
            def finish_source_mirror() -> None:
                source_mirror.mirror_file(current_path, final=True)
                stats.source_log_bytes = source_mirror.bytes_copied
                stats.source_log_files = source_mirror.to_summary()

            _attempt_cleanup(cleanup_errors, finish_source_mirror)
        for handle in (raw_handle, candidates_handle, parsed_handle):
            if handle is not None:
                _attempt_cleanup(cleanup_errors, handle.close)
        _finalize_watcher_artifacts(
            stats=stats,
            runtime=runtime,
            playback_builder=playback_builder,
            identity_enricher=identity_enricher,
            session_dir=session_dir,
            ended_normally=ended_normally,
            cleanup_errors=cleanup_errors,
        )
        _raise_finalization_errors(
            "watcher finalization failed",
            primary_error,
            cleanup_errors,
        )

    if primary_error is not None:
        raise primary_error

    return stats


def replay_vrc_log_files(
    *,
    log_files: list[Path | str],
    output_dir: Path | str,
    session_name: str | None = None,
    app_db_path: Path | str | None = None,
    started_at: str | None = None,
    live_session_id: str | None = None,
    include_raw: bool = True,
    live_db: bool = True,
    record_playback: bool = False,
) -> WatchStats:
    """Replay a fixed sequence of VRChat logs into capture artifacts."""
    replay_files = sorted((Path(path) for path in log_files), key=lambda path: path.name)
    capture_root = Path(output_dir)
    session_dir = capture_root / session_name if session_name else capture_root
    session_dir.mkdir(parents=True, exist_ok=True)

    default_db_path: Path | None = None
    if (live_db or record_playback) and app_db_path is None:
        default_db_path = session_dir / "live.sqlite3"
        if default_db_path.exists():
            default_db_path.unlink()
        app_db_path = default_db_path

    stats = WatchStats(session_dir=session_dir, started_at=started_at or _utc_now())
    stats.live_session_id = live_session_id or _live_session_id(session_dir, stats.started_at)
    stats.replayed_files = [str(path) for path in replay_files]
    if record_playback:
        _repair_stale_watcher_pending_records(app_db_path, stats.errors)
    runtime = LivePlaybackRuntime(
        stats=stats,
        app_db_path=app_db_path,
        live_db=live_db,
        record_playback=record_playback,
        overlay_port=None,
    )
    playback_builder = runtime.create_playback_builder()
    identity_enricher = RequesterIdentityEnricher(warnings=stats.warnings)

    raw_handle = None
    candidates_handle = None
    parsed_handle = None
    ended_normally = False
    primary_error: BaseException | None = None

    try:
        if include_raw:
            raw_handle = open(
                session_dir / "raw_output_log.txt",
                "w",
                encoding="utf-8",
                errors="replace",
                buffering=1,
            )
        candidates_handle = open(
            session_dir / "candidates.jsonl",
            "w",
            encoding="utf-8",
            buffering=1,
        )
        parsed_handle = open(
            session_dir / "parsed_events.jsonl",
            "w",
            encoding="utf-8",
            buffering=1,
        )

        for path in replay_files:
            with open(path, "r", encoding="utf-8", errors="replace") as current_handle:
                _drain_handle(
                    current_handle=current_handle,
                    current_path=path,
                    raw_handle=raw_handle,
                    candidates_handle=candidates_handle,
                    parsed_handle=parsed_handle,
                    stats=stats,
                    playback_builder=playback_builder,
                    identity_enricher=identity_enricher,
                    line_number=0,
                    lifecycle_event_callback=runtime.observe_lifecycle_event,
                )
        ended_normally = True
    except BaseException as exc:
        primary_error = exc
    finally:
        cleanup_errors: list[Exception] = []
        stats.ended_at = _utc_now()
        for handle in (raw_handle, candidates_handle, parsed_handle):
            if handle is not None:
                _attempt_cleanup(cleanup_errors, handle.close)
        _finalize_watcher_artifacts(
            stats=stats,
            runtime=runtime,
            playback_builder=playback_builder,
            identity_enricher=identity_enricher,
            session_dir=session_dir,
            ended_normally=ended_normally,
            cleanup_errors=cleanup_errors,
        )
        _raise_finalization_errors(
            "replay finalization failed",
            primary_error,
            cleanup_errors,
        )

    if primary_error is not None:
        raise primary_error

    return stats


def _repair_stale_watcher_pending_records(
    app_db_path: Path | str | None,
    errors: list[str],
) -> None:
    try:
        from dancing_log.storage import connect_db, repair_stale_watcher_pending_records

        with connect_db(app_db_path) as conn:
            repair_stale_watcher_pending_records(conn)
            conn.commit()
    except Exception as exc:
        _record_error(errors, f"watcher startup maintenance failed: {exc}")


def _drain_handle(
    *,
    current_handle,
    current_path: Path,
    raw_handle,
    candidates_handle,
    parsed_handle,
    stats: WatchStats,
    playback_builder: PlaybackEventBuilder,
    identity_enricher: RequesterIdentityEnricher,
    line_number: int,
    lifecycle_event_callback: Callable[[dict], None] | None = None,
) -> tuple[bool, int]:
    made_progress = False
    while True:
        byte_offset = current_handle.tell()
        line = current_handle.readline()
        if not line:
            break

        made_progress = True
        line_number += 1
        stats.raw_lines += 1
        stats.last_file = str(current_path)
        stats.last_offset = current_handle.tell()
        timestamp = extract_timestamp(line)
        timestamp_for_settlement = timestamp
        if timestamp and not timestamp_before(timestamp, stats.last_log_timestamp):
            stats.last_log_timestamp = timestamp
        elif timestamp:
            timestamp_for_settlement = None
        release_deferred_expired = timestamp_for_settlement is not None
        if timestamp_for_settlement is not None:
            if lifecycle_event_callback is not None:
                lifecycle_event_callback(
                    {
                        "event_type": "log-progress",
                        "observed_at": timestamp_for_settlement,
                        "timestamp": timestamp_for_settlement,
                    }
                )

        if raw_handle is not None:
            raw_handle.write(line)

        lifecycle_event = parse_vrc_lifecycle_event(line)
        if lifecycle_event is not None:
            stats.lifecycle_events += 1
            lifecycle_event["source_file"] = str(current_path)
            lifecycle_event["line_number"] = line_number
            lifecycle_event["byte_offset"] = byte_offset
            identity_enricher.observe_lifecycle(lifecycle_event)
            if lifecycle_event_callback is not None:
                lifecycle_event_callback(lifecycle_event)

        identity_event = parse_vrc_identity_event(line)
        if identity_event is not None:
            stats.identity_events += 1
            identity_event["source_file"] = str(current_path)
            identity_event["line_number"] = line_number
            identity_event["byte_offset"] = byte_offset
            _apply_identity_backfills(
                playback_builder,
                identity_enricher.observe_identity(identity_event),
            )

        if release_deferred_expired:
            _apply_identity_backfills(
                playback_builder,
                identity_enricher.release_deferred_expired(timestamp_for_settlement),
            )

        if not is_video_candidate_line(line):
            continue

        stats.candidate_lines += 1
        _write_jsonl(
            candidates_handle,
            {
                "captured_at": _utc_now(),
                "source_file": str(current_path),
                "line_number": line_number,
                "byte_offset": byte_offset,
                "raw_line": trim_newline(line),
            },
        )

        for event in parse_vrc_log_line(line):
            stats.parsed_events += 1
            stats.parser_counts[event.parser_name] = (
                stats.parser_counts.get(event.parser_name, 0) + 1
            )
            record = event.to_capture_record(
                source_file=current_path,
                line_number=line_number,
                byte_offset=byte_offset,
            )
            record = identity_enricher.enrich_record(record)
            _write_jsonl(
                parsed_handle,
                record,
            )
            folded_event = playback_builder.observe(record)
            identity_enricher.remember_pending(record, folded_event)
    return made_progress, line_number


def _apply_identity_backfills(
    playback_builder: PlaybackEventBuilder,
    backfills,
) -> None:
    for backfill in backfills:
        playback_builder.backfill_requester_user_id(
            backfill.event_key,
            backfill.requester_user_id,
            source=backfill.source,
        )


def _prime_requester_identity_from_log(
    *,
    path: Path,
    end_offset: int,
    identity_enricher: RequesterIdentityEnricher,
    stats: WatchStats,
    max_bytes: int = REQUESTER_IDENTITY_PREREAD_MAX_BYTES,
) -> None:
    read_size = min(max(0, int(end_offset)), max(1, int(max_bytes)))
    if read_size <= 0:
        return
    start_offset = max(0, int(end_offset) - read_size)
    try:
        with path.open("rb") as handle:
            handle.seek(start_offset)
            text = handle.read(read_size).decode("utf-8", errors="replace")
    except OSError as exc:
        _record_warning(stats.warnings, f"requester identity preread failed for {path}: {exc}")
        return

    lines = text.splitlines()
    if start_offset > 0 and lines:
        lines = lines[1:]

    room_start_index = None
    for index, line in enumerate(lines):
        event = parse_vrc_lifecycle_event(line)
        if event is not None and event.get("event_type") == "room-entering":
            room_start_index = index

    identity_enricher.counts["preread_bytes"] += read_size
    identity_enricher.counts["preread_lines"] += len(lines)
    if room_start_index is None:
        identity_enricher.counts["preread_no_room_context"] += 1
        if start_offset > 0:
            _record_warning(
                stats.warnings,
                "requester identity preread reached byte limit without finding a room boundary",
            )
        return

    identity_enricher.counts["preread_room_contexts"] += 1
    for line in lines[room_start_index:]:
        lifecycle_event = parse_vrc_lifecycle_event(line)
        if lifecycle_event is not None:
            identity_enricher.observe_lifecycle(lifecycle_event)

        identity_event = parse_vrc_identity_event(line)
        if identity_event is not None:
            identity_enricher.observe_identity(identity_event, warn=False)


def _latest_log_file(log_dir: Path, errors: list[str]) -> Path | None:
    try:
        candidates = [path for path in log_dir.glob(LOG_FILE_PATTERN) if path.is_file()]
    except OSError as exc:
        _record_error(errors, f"cannot list {log_dir}: {exc}")
        return None
    if not candidates:
        return None
    return max(candidates, key=lambda path: (_mtime_ns(path), path.name))


def _validate_log_dir(log_dir: Path) -> None:
    if not log_dir.exists():
        raise FileNotFoundError(f"VRChat log directory is missing: {log_dir}")
    if not log_dir.is_dir():
        raise NotADirectoryError(f"VRChat log path is not a directory: {log_dir}")
    try:
        with os.scandir(log_dir):
            pass
    except OSError as exc:
        raise OSError(f"VRChat log directory is inaccessible: {log_dir}: {exc}") from exc


def _is_newer_log(candidate: Path, current: Path) -> bool:
    return (_mtime_ns(candidate), candidate.name) > (_mtime_ns(current), current.name)


def _mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _start_offset(
    path: Path,
    *,
    initial_latest: Path | None,
    opened_any_file: bool,
    from_start: bool,
) -> int:
    if from_start:
        return 0
    if not opened_any_file and initial_latest is not None and path == initial_latest:
        try:
            return path.stat().st_size
        except OSError:
            return 0
    return 0


def _resolve_source_log_dir(
    *,
    source_log_dir: Path | str | None,
    output_dir: Path | str | None,
    capture_root: Path,
    default_source_log_dir: Path,
) -> Path:
    if source_log_dir is not None:
        return Path(source_log_dir)
    if output_dir is not None:
        return capture_root.parent / "source-vrc-logs"
    return default_source_log_dir


def _write_json(path: Path, value: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _write_jsonl(handle, value: dict) -> None:
    json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
    handle.write("\n")


def _write_jsonl_file(path: Path, values: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for value in values:
            _write_jsonl(handle, value)


def _finalize_watcher_artifacts(
    *,
    stats: WatchStats,
    runtime: LivePlaybackRuntime,
    playback_builder: PlaybackEventBuilder,
    identity_enricher: RequesterIdentityEnricher,
    session_dir: Path,
    ended_normally: bool,
    cleanup_errors: list[Exception],
) -> None:
    """Finish settlement, artifacts, and owned resources independently."""
    if ended_normally:
        _attempt_cleanup(
            cleanup_errors,
            lambda: _apply_identity_backfills(
                playback_builder,
                identity_enricher.release_session_end_expired(),
            ),
        )
        _attempt_cleanup(cleanup_errors, runtime.settle_graceful_stop)

    playback_records: list[dict] | None = None
    try:
        playback_records = playback_builder.records()
        stats.playback_events = len(playback_records)
        stats.delay_metrics = playback_delay_metrics(playback_records)
    except Exception as exc:
        cleanup_errors.append(exc)
    try:
        stats.requester_identity = identity_enricher.summary()
    except Exception as exc:
        cleanup_errors.append(exc)
    if playback_records is not None:
        _attempt_cleanup(
            cleanup_errors,
            lambda: _write_jsonl_file(
                session_dir / "playback_events.jsonl",
                playback_records,
            ),
        )
    _attempt_cleanup(
        cleanup_errors,
        lambda: _write_json(session_dir / "summary.json", stats.to_dict()),
    )
    _attempt_cleanup(cleanup_errors, runtime.close)


def _attempt_cleanup(errors: list[Exception], action: Callable[[], object]) -> None:
    try:
        action()
    except Exception as exc:
        errors.append(exc)


def _raise_cleanup_errors(label: str, errors: list[Exception]) -> None:
    if len(errors) == 1:
        raise errors[0]
    if errors:
        raise ExceptionGroup(label, errors)


def _raise_finalization_errors(
    label: str,
    primary_error: BaseException | None,
    cleanup_errors: list[Exception],
) -> None:
    if primary_error is None:
        _raise_cleanup_errors(label, cleanup_errors)
        return
    if cleanup_errors:
        cleanup_summary = "; ".join(str(error) for error in cleanup_errors)
        raise BaseExceptionGroup(
            f"{label} after {primary_error}; cleanup errors: {cleanup_summary}",
            [primary_error, *cleanup_errors],
        ) from None


def _record_error(errors: list[str], message: str) -> None:
    if not errors or errors[-1] != message:
        errors.append(message)


def _record_warning(warnings: list[str], message: str) -> None:
    if not warnings or warnings[-1] != message:
        warnings.append(message)


def _live_session_id(session_dir: Path, started_at: str) -> str:
    return f"{session_dir.name}:{started_at}"


def _utc_now() -> str:
    return now_utc_iso()
