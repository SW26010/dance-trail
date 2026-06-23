"""Route dispatch for the Local Web UI."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import parse_qs, urlparse

from dancing_log.app_paths import AppPaths
from dancing_log.live_app_session import LiveAppSessionRuntime
from dancing_log.webui_assets import render_webui_html
from dancing_log.webui_endpoints import (
    control_live_overlay_from_payload,
    control_live_watcher_from_payload,
    load_catalog_snapshot,
    load_insights_snapshot,
    load_lists_snapshot,
    load_operations_snapshot,
    load_summary_snapshot,
    load_timeline_snapshot,
    run_operation_from_payload,
    update_playback_review_from_payload,
)
from dancing_log.webui_settings import (
    load_config_snapshot,
    pick_path_from_payload,
    resolve_path_from_payload,
    save_config_from_payload,
)


class WebUiRouteRuntime(Protocol):
    app_root: Path
    csrf_token: str
    session: LiveAppSessionRuntime

    @property
    def paths(self) -> AppPaths: ...


@dataclass(frozen=True)
class WebUiRouteResponse:
    status: int
    content_type: str
    body: bytes


GetRoute = Callable[[WebUiRouteRuntime, dict[str, list[str]]], dict]
PostRoute = Callable[[WebUiRouteRuntime, dict], tuple[dict, int]]


def _get_config(runtime: WebUiRouteRuntime, query: dict[str, list[str]]) -> dict:
    return load_config_snapshot(runtime)


def _get_summary(runtime: WebUiRouteRuntime, query: dict[str, list[str]]) -> dict:
    return load_summary_snapshot(runtime)


def _get_timeline(runtime: WebUiRouteRuntime, query: dict[str, list[str]]) -> dict:
    return load_timeline_snapshot(runtime, query)


def _get_catalog(runtime: WebUiRouteRuntime, query: dict[str, list[str]]) -> dict:
    return load_catalog_snapshot(runtime, query)


def _get_lists(runtime: WebUiRouteRuntime, query: dict[str, list[str]]) -> dict:
    return load_lists_snapshot(runtime)


def _get_insights(runtime: WebUiRouteRuntime, query: dict[str, list[str]]) -> dict:
    return load_insights_snapshot(runtime)


def _get_operations(runtime: WebUiRouteRuntime, query: dict[str, list[str]]) -> dict:
    return load_operations_snapshot()


GET_JSON_ROUTES: dict[str, GetRoute] = {
    "/api/config": _get_config,
    "/api/summary": _get_summary,
    "/api/timeline": _get_timeline,
    "/api/catalog": _get_catalog,
    "/api/lists": _get_lists,
    "/api/insights": _get_insights,
    "/api/operations": _get_operations,
}

POST_JSON_ROUTES: dict[str, PostRoute] = {
    "/api/config": save_config_from_payload,
    "/api/resolve-path": resolve_path_from_payload,
    "/api/pick-path": pick_path_from_payload,
    "/api/live/watcher": control_live_watcher_from_payload,
    "/api/live/overlay": control_live_overlay_from_payload,
    "/api/operations/run": run_operation_from_payload,
    "/api/playback-review": update_playback_review_from_payload,
}


def handle_get_request(runtime: WebUiRouteRuntime, target: str) -> WebUiRouteResponse:
    parsed = urlparse(target)
    path = parsed.path
    if path in {"", "/"}:
        return _html_response(200, render_webui_html(runtime.csrf_token))

    handler = GET_JSON_ROUTES.get(path)
    if handler is None:
        return _json_response(404, {"error": "not found"})
    return _json_response(200, handler(runtime, parse_qs(parsed.query)))


def handle_post_request(
    runtime: WebUiRouteRuntime,
    target: str,
    payload: dict,
) -> WebUiRouteResponse:
    handler = POST_JSON_ROUTES.get(urlparse(target).path)
    if handler is None:
        return _json_response(404, {"error": "not found"})
    response, status = handler(runtime, payload)
    return _json_response(status, response)


def _json_response(status: int, payload: dict) -> WebUiRouteResponse:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return WebUiRouteResponse(status, "application/json; charset=utf-8", data)


def _html_response(status: int, html: str) -> WebUiRouteResponse:
    return WebUiRouteResponse(status, "text/html; charset=utf-8", html.encode("utf-8"))
