"""Endpoint handlers for the Local Web UI."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
import sqlite3
from typing import Protocol

from dancing_log.app_paths import AppPaths, AppRuntimeConfig
from dancing_log.data_operations import (
    DataOperationError,
    build_data_operation_request_from_payload,
    operation_catalog_snapshot,
    run_data_operation_request,
)
from dancing_log.live_app_session import LiveAppSessionRuntime, LiveAppSessionStatus
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


class WebUiEndpointRuntime(Protocol):
    app_root: Path
    session: LiveAppSessionRuntime

    @property
    def paths(self) -> AppPaths: ...


def load_summary_snapshot(runtime: WebUiEndpointRuntime) -> dict:
    snapshot = LocalReadSnapshots(runtime.app_root).home(
        config_warnings=load_config_snapshot(runtime).get("warnings", []),
    )
    snapshot["session"] = live_session_status_snapshot(runtime.session.status())
    return snapshot


def control_live_watcher_from_payload(
    runtime: WebUiEndpointRuntime,
    payload: dict,
) -> tuple[dict, int]:
    action = str(payload.get("action") or "").strip().lower()
    if action == "start":
        runtime.session.start_watcher()
    elif action == "stop":
        runtime.session.stop_watcher()
    else:
        return {"error": "action must be start or stop"}, 400
    return {"session": live_session_status_snapshot(runtime.session.status())}, 200


def control_live_overlay_from_payload(
    runtime: WebUiEndpointRuntime,
    payload: dict,
) -> tuple[dict, int]:
    action = str(payload.get("action") or "").strip().lower()
    if action == "start":
        runtime.session.start_overlay()
    elif action == "stop":
        runtime.session.stop_overlay()
    else:
        return {"error": "action must be start or stop"}, 400
    return {"session": live_session_status_snapshot(runtime.session.status())}, 200


def live_session_status_snapshot(status: LiveAppSessionStatus) -> dict:
    return {
        "watcher_running": status.watcher_running,
        "overlay_running": status.overlay_running,
        "last_error": status.last_error,
        "last_watcher_stats": _watcher_stats_snapshot(status.last_watcher_stats),
    }


def _watcher_stats_snapshot(stats: object | None) -> object | None:
    if stats is None:
        return None
    if hasattr(stats, "to_dict"):
        return _json_safe_value(stats.to_dict())
    if is_dataclass(stats):
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
    return operation_catalog_snapshot()


def run_operation_from_payload(
    runtime: WebUiEndpointRuntime,
    payload: dict,
) -> tuple[dict, int]:
    try:
        request = build_data_operation_request_from_payload(payload)
        config = AppRuntimeConfig.load(app_root=runtime.app_root, migrate_legacy=True)
        result = run_data_operation_request(request, config=config)
    except DataOperationError as exc:
        return {"error": str(exc)}, 400
    return {"result": result.as_dict()}, 200


def update_playback_review_from_payload(
    runtime: WebUiEndpointRuntime,
    payload: dict,
) -> tuple[dict, int]:
    action = str(payload.get("action") or "").strip().lower()
    playback_record_id = payload.get("playback_record_id")
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
