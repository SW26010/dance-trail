"""Endpoint handlers for the Local Web UI."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
import sqlite3
from typing import Protocol, runtime_checkable

from dancing_log.app_data_lifetime_lock import AppDataLifetimeLockUnavailable
from dancing_log.app_paths import AppPaths, AppRuntimeConfig
from dancing_log.data_operations import (
    DataOperationError,
    build_data_operation_request_from_payload,
    operation_catalog_snapshot,
    run_data_operation_request,
)
from dancing_log.live_app_session import (
    LiveAppSessionRuntime,
    LiveAppSessionStatus,
    LiveSessionUnavailableError,
)
from dancing_log.playback_projection import (
    EFFECTIVE_PLAYBACK_ACCEPTED,
    EFFECTIVE_PLAYBACK_EXCLUDED,
    EFFECTIVE_PLAYBACK_NEEDS_ATTENTION,
)
from dancing_log.playback_review import (
    PlaybackReviewError,
    clear_playback_record_manual_decision,
    set_playback_record_manual_decision,
)
from dancing_log.read_snapshots import LocalReadSnapshots
from dancing_log.storage import connect_db
from dancing_log.webui_settings import load_config_snapshot
from dancing_log.watcher_lifetime_lock import WatcherLifetimeLockUnavailable


WEBUI_DATA_OPERATION_KEYS = frozenset(
    {"import-vrcx", "sync-wanna", "sync-queued-self"}
)


class LiveStateSnapshot(Protocol):
    def snapshot(self) -> dict: ...


@runtime_checkable
class DictSnapshot(Protocol):
    def to_dict(self) -> object: ...


class WebUiEndpointRuntime(Protocol):
    @property
    def app_root(self) -> Path: ...

    @property
    def session(self) -> LiveAppSessionRuntime: ...

    @property
    def live_state(self) -> LiveStateSnapshot: ...

    @property
    def startup_warnings(self) -> tuple[str, ...]: ...

    @property
    def paths(self) -> AppPaths: ...


def load_summary_snapshot(runtime: WebUiEndpointRuntime) -> dict:
    config_warnings = load_config_snapshot(runtime).get("warnings", [])
    snapshot = LocalReadSnapshots(runtime.app_root).home(
        config_warnings=[*config_warnings, *runtime.startup_warnings],
    )
    snapshot["startup_warnings"] = list(runtime.startup_warnings)
    snapshot["current_live"] = runtime.live_state.snapshot()["current"]
    snapshot["session"] = live_session_status_snapshot(runtime.session.status())
    return snapshot


def control_live_watcher_from_payload(
    runtime: WebUiEndpointRuntime,
    payload: dict,
) -> tuple[dict, int]:
    action = str(payload.get("action") or "").strip().lower()
    try:
        if action == "start":
            runtime.session.start_watcher()
        elif action == "stop":
            runtime.session.stop_watcher()
        else:
            return {"error": "action must be start or stop"}, 400
    except (
        TimeoutError,
        LiveSessionUnavailableError,
        WatcherLifetimeLockUnavailable,
    ) as exc:
        return _live_transition_conflict(runtime, exc)
    return {"session": live_session_status_snapshot(runtime.session.status())}, 200


def control_live_overlay_from_payload(
    runtime: WebUiEndpointRuntime,
    payload: dict,
) -> tuple[dict, int]:
    action = str(payload.get("action") or "").strip().lower()
    try:
        if action == "start":
            runtime.session.start_overlay()
        elif action == "stop":
            runtime.session.stop_overlay()
        else:
            return {"error": "action must be start or stop"}, 400
    except (
        TimeoutError,
        LiveSessionUnavailableError,
        WatcherLifetimeLockUnavailable,
    ) as exc:
        return _live_transition_conflict(runtime, exc)
    return {"session": live_session_status_snapshot(runtime.session.status())}, 200


def _live_transition_conflict(
    runtime: WebUiEndpointRuntime,
    error: Exception,
) -> tuple[dict, int]:
    return {
        "error": str(error),
        "session": live_session_status_snapshot(runtime.session.status()),
    }, 409


def live_session_status_snapshot(status: LiveAppSessionStatus) -> dict:
    return {
        "session_state": status.session_state,
        "watcher_running": status.watcher_running,
        "overlay_running": status.overlay_running,
        "watcher_state": status.watcher_state,
        "overlay_state": status.overlay_state,
        "last_error": status.last_error,
        "last_watcher_stats": _watcher_stats_snapshot(status.last_watcher_stats),
    }


def _watcher_stats_snapshot(stats: object | None) -> object | None:
    if stats is None:
        return None
    if isinstance(stats, DictSnapshot):
        return _json_safe_value(stats.to_dict())
    if is_dataclass(stats) and not isinstance(stats, type):
        return _json_safe_value(asdict(stats))
    if isinstance(stats, dict):
        return _json_safe_value(stats)
    if hasattr(stats, "__dict__"):
        return _json_safe_value(vars(stats))
    return str(stats)


def _json_safe_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(item) for item in value]
    return str(value)


def load_timeline_snapshot(
    runtime: WebUiEndpointRuntime,
    query: dict[str, list[str]],
) -> dict:
    return LocalReadSnapshots(runtime.app_root).timeline(query)


def load_catalog_snapshot(
    runtime: WebUiEndpointRuntime,
    query: dict[str, list[str]],
) -> dict:
    return LocalReadSnapshots(runtime.app_root).catalog(query)


def load_lists_snapshot(runtime: WebUiEndpointRuntime) -> dict:
    return LocalReadSnapshots(runtime.app_root).lists()


def load_insights_snapshot(runtime: WebUiEndpointRuntime) -> dict:
    return LocalReadSnapshots(runtime.app_root).insights()


def load_operations_snapshot() -> dict:
    snapshot = operation_catalog_snapshot()
    snapshot["operations"] = [
        operation
        for operation in snapshot["operations"]
        if operation["key"] in WEBUI_DATA_OPERATION_KEYS
    ]
    return snapshot


def run_operation_from_payload(
    runtime: WebUiEndpointRuntime,
    payload: dict,
) -> tuple[dict, int]:
    try:
        requested_key = payload.get("operation")
        if (
            isinstance(requested_key, str)
            and requested_key.strip()
            and requested_key.strip() not in WEBUI_DATA_OPERATION_KEYS
        ):
            raise DataOperationError(
                f"{requested_key.strip()} is not available in the Web UI"
            )
        request = build_data_operation_request_from_payload(payload)
        config = AppRuntimeConfig.load(app_root=runtime.app_root, migrate_legacy=True)
        result = run_data_operation_request(request, config=config)
    except AppDataLifetimeLockUnavailable as exc:
        return {"error": str(exc)}, 409
    except DataOperationError as exc:
        return {"error": str(exc)}, 400
    return {"result": result.as_dict()}, 200


def update_playback_review_from_payload(
    runtime: WebUiEndpointRuntime,
    payload: dict,
) -> tuple[dict, int]:
    action = str(payload.get("action") or "").strip().lower()
    raw_playback_record_id = payload.get("playback_record_id")
    if isinstance(raw_playback_record_id, bool) or not isinstance(
        raw_playback_record_id,
        (int, str),
    ):
        return {"error": "playback_record_id must be an integer"}, 400
    try:
        playback_record_id = int(raw_playback_record_id)
    except (TypeError, ValueError):
        return {"error": "playback_record_id must be an integer"}, 400
    note = str(payload.get("note") or "")
    status_by_action = {
        "accept": EFFECTIVE_PLAYBACK_ACCEPTED,
        "accepted": EFFECTIVE_PLAYBACK_ACCEPTED,
        "exclude": EFFECTIVE_PLAYBACK_EXCLUDED,
        "excluded": EFFECTIVE_PLAYBACK_EXCLUDED,
        "needs_attention": EFFECTIVE_PLAYBACK_NEEDS_ATTENTION,
    }
    restore_actions = {"restore_default", "clear", "default"}

    try:
        config = AppRuntimeConfig.load(app_root=runtime.app_root, migrate_legacy=True)
        db_path = config.app_db_path
        if not db_path.exists():
            return {"error": "database not found"}, 400

        with connect_db(db_path) as conn:
            if action in status_by_action:
                state = set_playback_record_manual_decision(
                    conn,
                    playback_record_id,
                    status_by_action[action],
                    reason=f"webui:{action}",
                    note=note,
                )
            elif action in restore_actions:
                state = clear_playback_record_manual_decision(conn, playback_record_id)
            else:
                return {
                    "error": (
                        "action must be accept, exclude, needs_attention, "
                        "or restore_default"
                    )
                }, 400
            conn.commit()
    except (PlaybackReviewError, ValueError, sqlite3.Error) as exc:
        return {"error": str(exc)}, 400
    return {"review": state.as_dict()}, 200
