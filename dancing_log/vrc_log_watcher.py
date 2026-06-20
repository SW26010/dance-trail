"""Lightweight VRChat output log watcher for playback forensics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import threading
import time

from dancing_log.app_paths import AppPaths
from dancing_log.live_playback_folding import (
    PREVIEW_SUPPRESSION_SECONDS,
    RETRY_MERGE_SECONDS,
    PlaybackEventBuilder,
    playback_delay_metrics,
)
from dancing_log.live_playback_settlement import (
    COMPLETION_EPSILON_SECONDS,
    PROMOTION_COMPLETION_RATIO,
    decide_live_playback_settlement,
)
from dancing_log.vrc_log_utils import (
    extract_timestamp,
    timestamp_before,
    trim_newline,
)
from dancing_log.vrc_log_parser import (
    ParsedVrcLogEvent,
    is_lifecycle_candidate_line,
    is_video_candidate_line,
    parse_vrc_lifecycle_event,
    parse_vrc_log_line,
)


LOG_FILE_PATTERN = "output_log_*.txt"
SOURCE_LOG_COPY_CHUNK_BYTES = 4 * 1024 * 1024

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
    "is_lifecycle_candidate_line",
    "is_video_candidate_line",
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
    playback_events: int = 0
    delay_metrics: dict[str, float | int | None] = field(default_factory=dict)
    parser_counts: dict[str, int] = field(default_factory=dict)
    last_file: str | None = None
    last_offset: int = 0
    last_log_timestamp: str | None = None
    idle_stopped: bool = False
    live_session_id: str | None = None
    live_db_updates: int = 0
    live_promotions: int = 0
    overlay_url: str | None = None
    stop_requested: bool = False
    replayed_files: list[str] = field(default_factory=list)
    source_log_dir: str | None = None
    source_log_bytes: int = 0
    source_log_files: list[dict] = field(default_factory=list)
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
            "playback_events": self.playback_events,
            "delay_metrics": self.delay_metrics,
            "parser_counts": dict(sorted(self.parser_counts.items())),
            "last_file": self.last_file,
            "last_offset": self.last_offset,
            "last_log_timestamp": self.last_log_timestamp,
            "idle_stopped": self.idle_stopped,
            "live_session_id": self.live_session_id,
            "live_db_updates": self.live_db_updates,
            "live_promotions": self.live_promotions,
            "overlay_url": self.overlay_url,
            "stop_requested": self.stop_requested,
            "replayed_files": self.replayed_files,
            "source_log_dir": self.source_log_dir,
            "source_log_bytes": self.source_log_bytes,
            "source_log_files": self.source_log_files,
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


class _LivePlaybackRuntime:
    """Shared live DB and overlay side effects for tailing and offline replay."""

    def __init__(
        self,
        *,
        stats: WatchStats,
        app_db_path: Path | str | None,
        live_db: bool,
        promote_live: bool,
        overlay_port: int | None,
    ) -> None:
        self.stats = stats
        self.promote_live = promote_live
        self.app_conn = None
        self.overlay_server = None
        self.playback_builder = None
        self.live_events: dict[str, dict] = {}
        self.finalized_live_keys: set[str] = set()
        self.promoted_keys: set[str] = set()
        self.current_room_name: str | None = None

        if live_db or promote_live:
            from dancing_log.storage import (
                connect_db,
                mark_live_playback_event_completed,
                mark_live_playback_event_interrupted,
                make_live_playback_event_key,
                promote_live_playback_event,
                upsert_live_playback_event,
            )

            self.app_conn = connect_db(app_db_path)
            self.mark_live_playback_event_completed = mark_live_playback_event_completed
            self.mark_live_playback_event_interrupted = mark_live_playback_event_interrupted
            self.make_live_playback_event_key = make_live_playback_event_key
            self.promote_live_playback_event = promote_live_playback_event
            self.upsert_live_playback_event = upsert_live_playback_event
        else:
            self.mark_live_playback_event_completed = None
            self.mark_live_playback_event_interrupted = None
            self.make_live_playback_event_key = None
            self.promote_live_playback_event = None
            self.upsert_live_playback_event = None

        if overlay_port is not None:
            from dancing_log.overlay_server import OverlayServer

            self.overlay_server = OverlayServer(port=overlay_port)
            self.overlay_server.start()
            self.stats.overlay_url = self.overlay_server.url

    def close(self) -> None:
        if self.overlay_server is not None:
            self.overlay_server.stop()
            self.overlay_server = None
        if self.app_conn is not None:
            self.app_conn.close()
            self.app_conn = None

    def is_stale_observation(self, observed_at: str | None) -> bool:
        return timestamp_before(observed_at, self.stats.last_log_timestamp)

    def promote_completed_event(self, live_event_key: str) -> None:
        if not self.promote_live or self.app_conn is None:
            return
        dance_event_id = self.promote_live_playback_event(self.app_conn, live_event_key)
        if dance_event_id is not None and live_event_key not in self.promoted_keys:
            self.promoted_keys.add(live_event_key)
            self.stats.live_promotions += 1

    def publish_live_settlement(
        self,
        event: dict,
        *,
        completion_status: str,
        observed_at: str,
        played_seconds: float | None,
        required_played_seconds: float | None,
        reason: str,
    ) -> None:
        event["completion_status"] = completion_status
        event["completion_reason"] = reason
        event["played_seconds"] = played_seconds
        event["required_played_seconds"] = required_played_seconds
        if completion_status == "completed":
            event["completed_at"] = observed_at
            event["interrupted_at"] = None
        else:
            event["completed_at"] = None
            event["interrupted_at"] = observed_at
        if self.overlay_server is not None:
            self.overlay_server.publish(event)

    def settle_live_event(
        self,
        event: dict,
        *,
        observed_at: str,
        interrupt_if_incomplete: bool,
        completion_reason: str,
        interrupt_reason: str,
    ) -> bool:
        if self.app_conn is None:
            return False
        live_event_key = event.get("live_event_key")
        if not live_event_key or live_event_key in self.finalized_live_keys:
            return False

        settlement = decide_live_playback_settlement(
            event,
            observed_at=observed_at,
            interrupt_if_incomplete=interrupt_if_incomplete,
            completion_reason=completion_reason,
            interrupt_reason=interrupt_reason,
        )
        if settlement is None:
            return False

        if settlement.completion_status == "completed":
            changed = self.mark_live_playback_event_completed(
                self.app_conn,
                live_event_key,
                completed_at=settlement.observed_at,
                played_seconds=settlement.played_seconds,
                required_played_seconds=settlement.required_played_seconds,
                reason=settlement.reason,
            )
            self.promote_completed_event(live_event_key)
        else:
            changed = self.mark_live_playback_event_interrupted(
                self.app_conn,
                live_event_key,
                interrupted_at=settlement.observed_at,
                played_seconds=settlement.played_seconds,
                required_played_seconds=settlement.required_played_seconds,
                reason=settlement.reason,
            )
        self.finalized_live_keys.add(live_event_key)
        if changed:
            self.publish_live_settlement(
                event,
                completion_status=settlement.completion_status,
                observed_at=settlement.observed_at,
                played_seconds=settlement.played_seconds,
                required_played_seconds=settlement.required_played_seconds,
                reason=settlement.reason,
            )
        return changed

    def settle_pending_events(
        self,
        *,
        observed_at: str,
        current_live_event_key: str | None = None,
        interrupt_others: bool = False,
        interrupt_started_others: bool = False,
        completion_reason: str = "observed_completion_threshold",
        interrupt_reason: str = "superseded_before_completion",
    ) -> bool:
        if self.is_stale_observation(observed_at):
            return False
        changed = False
        for live_event_key, event in list(self.live_events.items()):
            if live_event_key == current_live_event_key:
                continue
            interrupt_if_incomplete = interrupt_others or (
                interrupt_started_others and bool(event.get("actual_play_at"))
            )
            changed = (
                self.settle_live_event(
                    event,
                    observed_at=observed_at,
                    interrupt_if_incomplete=interrupt_if_incomplete,
                    completion_reason=completion_reason,
                    interrupt_reason=interrupt_reason,
                )
                or changed
            )
        return changed

    def handle_log_progress(self, timestamp: str | None) -> None:
        if not timestamp:
            return
        self.stats.last_log_timestamp = timestamp
        if self.app_conn is None:
            return
        try:
            if self.settle_pending_events(observed_at=timestamp):
                self.app_conn.commit()
        except Exception as exc:
            _record_error(self.stats.errors, f"live completion check failed: {exc}")
            self.app_conn.rollback()

    def handle_playback_update(self, event: dict) -> None:
        update = dict(event)
        update["live_session_id"] = self.stats.live_session_id
        if self.app_conn is not None:
            live_event_key = self.make_live_playback_event_key(
                self.stats.live_session_id,
                str(event["event_key"]),
            )
            update["live_event_key"] = live_event_key
            try:
                self.upsert_live_playback_event(
                    self.app_conn,
                    event,
                    session_id=self.stats.live_session_id,
                    event_key=live_event_key,
                )
                self.stats.live_db_updates += 1
                existing_update = self.live_events.get(live_event_key)
                if existing_update is not None and existing_update.get("completion_status"):
                    for field_name in (
                        "completion_status",
                        "completion_reason",
                        "completed_at",
                        "interrupted_at",
                        "played_seconds",
                        "required_played_seconds",
                    ):
                        update[field_name] = existing_update.get(field_name)
                self.live_events[live_event_key] = update
                actual_observed_at = event.get("actual_play_at")
                if actual_observed_at:
                    self.settle_pending_events(
                        observed_at=actual_observed_at,
                        current_live_event_key=live_event_key,
                        interrupt_others=True,
                    )
                else:
                    first_observed_at = event.get("first_seen_at")
                    if first_observed_at:
                        self.settle_pending_events(
                            observed_at=first_observed_at,
                            current_live_event_key=live_event_key,
                            interrupt_started_others=True,
                        )
                current_observed_at = event.get("last_seen_at") or actual_observed_at
                if current_observed_at and not self.is_stale_observation(current_observed_at):
                    self.settle_live_event(
                        update,
                        observed_at=current_observed_at,
                        interrupt_if_incomplete=False,
                        completion_reason="observed_completion_threshold",
                        interrupt_reason="superseded_before_completion",
                    )
                self.app_conn.commit()
            except Exception as exc:
                _record_error(self.stats.errors, f"live DB update failed: {exc}")
                self.app_conn.rollback()
        if self.overlay_server is not None:
            self.overlay_server.publish(update)

    def handle_lifecycle_event(self, event: dict) -> None:
        event_type = event.get("event_type")
        if event.get("room_name"):
            self.current_room_name = event.get("room_name")

        if event_type == "room-entering":
            if self.overlay_server is not None:
                self.overlay_server.publish_status(event)
            return

        if event_type not in {"room-left", "application-quit", "video-shutdown"}:
            return

        if self.playback_builder is not None:
            self.playback_builder.close_open_events()

        observed_at = event.get("observed_at") or event.get("timestamp") or self.stats.last_log_timestamp
        interrupt_reason = {
            "room-left": "room_left",
            "application-quit": "application_quit",
            "video-shutdown": "application_quit",
        }.get(str(event_type), "playback_stopped")

        if observed_at and self.app_conn is not None:
            try:
                if self.settle_pending_events(
                    observed_at=observed_at,
                    interrupt_others=True,
                    completion_reason="observed_completion_threshold",
                    interrupt_reason=interrupt_reason,
                ):
                    self.app_conn.commit()
            except Exception as exc:
                _record_error(self.stats.errors, f"live lifecycle settlement failed: {exc}")
                self.app_conn.rollback()

        if self.overlay_server is not None:
            status = dict(event)
            status["room_name"] = status.get("room_name") or self.current_room_name
            status["clear_current"] = True
            self.overlay_server.publish_status(status)

        if event_type in {"room-left", "application-quit"}:
            self.current_room_name = None


def default_vrc_log_dir() -> Path:
    """Return VRChat's default Windows output log directory."""
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        local_path = Path(local_appdata)
        if local_path.name.lower() == "local":
            return local_path.with_name("LocalLow") / "VRChat" / "VRChat"
        return Path(f"{local_appdata}Low") / "VRChat" / "VRChat"
    return Path.home() / "AppData" / "LocalLow" / "VRChat" / "VRChat"


def watch_vrc_logs(
    *,
    log_dir: Path | str | None = None,
    output_dir: Path | str | None = None,
    session_name: str | None = None,
    app_db_path: Path | str | None = None,
    from_start: bool = False,
    include_raw: bool = True,
    live_db: bool = False,
    promote_live: bool = False,
    overlay_port: int | None = None,
    poll_seconds: float = 0.25,
    stop_after_idle_seconds: float | None = None,
    stop_event: threading.Event | None = None,
    archive_source_logs: bool = True,
    source_log_dir: Path | str | None = None,
    source_log_copy_bytes_per_tick: int = SOURCE_LOG_COPY_CHUNK_BYTES,
) -> WatchStats:
    """Tail VRChat output logs and write raw/candidate/parsed capture artifacts."""
    resolved_log_dir = Path(log_dir) if log_dir is not None else default_vrc_log_dir()
    app_paths = AppPaths.from_root()
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
    if archive_source_logs:
        stats.source_log_dir = str(resolved_source_log_dir)
    initial_latest = _latest_log_file(resolved_log_dir, stats.errors)
    opened_any_file = False
    current_path: Path | None = None
    current_handle = None
    current_line_number = 0
    idle_since = time.monotonic()
    runtime = _LivePlaybackRuntime(
        stats=stats,
        app_db_path=app_db_path,
        live_db=live_db,
        promote_live=promote_live,
        overlay_port=overlay_port,
    )
    playback_builder = PlaybackEventBuilder(update_callback=runtime.handle_playback_update)
    runtime.playback_builder = playback_builder

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
                    current_handle = open(
                        latest_path,
                        "r",
                        encoding="utf-8",
                        errors="replace",
                    )
                    current_handle.seek(start_offset)
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
                    line_number=current_line_number,
                    line_timestamp_callback=runtime.handle_log_progress,
                    lifecycle_event_callback=runtime.handle_lifecycle_event,
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
    except KeyboardInterrupt:
        pass
    finally:
        stats.ended_at = _utc_now()
        if current_handle is not None:
            current_handle.close()
        if source_mirror is not None and current_path is not None:
            source_mirror.mirror_file(current_path, final=True)
            stats.source_log_bytes = source_mirror.bytes_copied
            stats.source_log_files = source_mirror.to_summary()
        for handle in (raw_handle, candidates_handle, parsed_handle):
            if handle is not None:
                handle.close()
        playback_records = playback_builder.records()
        stats.playback_events = len(playback_records)
        stats.delay_metrics = playback_delay_metrics(playback_records)
        _write_jsonl_file(session_dir / "playback_events.jsonl", playback_records)
        _write_json(session_dir / "summary.json", stats.to_dict())
        runtime.close()

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
    promote_live: bool = False,
) -> WatchStats:
    """Replay a fixed sequence of VRChat logs into capture artifacts."""
    replay_files = sorted((Path(path) for path in log_files), key=lambda path: path.name)
    capture_root = Path(output_dir)
    session_dir = capture_root / session_name if session_name else capture_root
    session_dir.mkdir(parents=True, exist_ok=True)

    default_db_path: Path | None = None
    if (live_db or promote_live) and app_db_path is None:
        default_db_path = session_dir / "live.sqlite3"
        if default_db_path.exists():
            default_db_path.unlink()
        app_db_path = default_db_path

    stats = WatchStats(session_dir=session_dir, started_at=started_at or _utc_now())
    stats.live_session_id = live_session_id or _live_session_id(session_dir, stats.started_at)
    stats.replayed_files = [str(path) for path in replay_files]
    runtime = _LivePlaybackRuntime(
        stats=stats,
        app_db_path=app_db_path,
        live_db=live_db,
        promote_live=promote_live,
        overlay_port=None,
    )
    playback_builder = PlaybackEventBuilder(update_callback=runtime.handle_playback_update)
    runtime.playback_builder = playback_builder

    raw_handle = None
    candidates_handle = None
    parsed_handle = None

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
                    line_number=0,
                    line_timestamp_callback=runtime.handle_log_progress,
                    lifecycle_event_callback=runtime.handle_lifecycle_event,
                )
    finally:
        stats.ended_at = _utc_now()
        for handle in (raw_handle, candidates_handle, parsed_handle):
            if handle is not None:
                handle.close()
        playback_records = playback_builder.records()
        stats.playback_events = len(playback_records)
        stats.delay_metrics = playback_delay_metrics(playback_records)
        _write_jsonl_file(session_dir / "playback_events.jsonl", playback_records)
        _write_json(session_dir / "summary.json", stats.to_dict())
        runtime.close()

    return stats


def _drain_handle(
    *,
    current_handle,
    current_path: Path,
    raw_handle,
    candidates_handle,
    parsed_handle,
    stats: WatchStats,
    playback_builder: PlaybackEventBuilder,
    line_number: int,
    line_timestamp_callback: Callable[[str | None], None] | None = None,
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
        if line_timestamp_callback is not None:
            line_timestamp_callback(timestamp_for_settlement)

        if raw_handle is not None:
            raw_handle.write(line)

        lifecycle_event = parse_vrc_lifecycle_event(line)
        if lifecycle_event is not None:
            stats.lifecycle_events += 1
            lifecycle_event["source_file"] = str(current_path)
            lifecycle_event["line_number"] = line_number
            lifecycle_event["byte_offset"] = byte_offset
            if lifecycle_event_callback is not None:
                lifecycle_event_callback(lifecycle_event)

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
            _write_jsonl(
                parsed_handle,
                record,
            )
            playback_builder.observe(record)
    return made_progress, line_number


def _latest_log_file(log_dir: Path, errors: list[str]) -> Path | None:
    try:
        candidates = [path for path in log_dir.glob(LOG_FILE_PATTERN) if path.is_file()]
    except OSError as exc:
        _record_error(errors, f"cannot list {log_dir}: {exc}")
        return None
    if not candidates:
        return None
    return max(candidates, key=lambda path: (_mtime_ns(path), path.name))


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


def _record_error(errors: list[str], message: str) -> None:
    if not errors or errors[-1] != message:
        errors.append(message)


def _live_session_id(session_dir: Path, started_at: str) -> str:
    return f"{session_dir.name}:{started_at}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
