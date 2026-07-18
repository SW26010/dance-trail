"""Route dispatch for the Local Web UI."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import parse_qs, urlparse

from dancing_log.app_paths import AppPaths
from dancing_log.live_app_session import LiveAppSessionRuntime
from dancing_log.overlay_server import (
    OVERLAY_PAGE_PATH,
    OVERLAY_STATE_PATH,
    OverlayState,
    render_overlay_html,
)
from dancing_log.webui_assets import (
    WEBUI_ROUTE_BY_VIEW,
    load_webui_asset,
    render_webui_html,
)
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
    overlay_state: OverlayState
    live_state: OverlayState
    startup_warnings: tuple[str, ...]

    @property
    def paths(self) -> AppPaths: ...


@dataclass(frozen=True)
class WebUiRouteResponse:
    status: int
    content_type: str
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()


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


def _get_overlay_state(runtime: WebUiRouteRuntime, query: dict[str, list[str]]) -> dict:
    return runtime.overlay_state.snapshot()


WEBUI_PAGE_PATHS = frozenset(WEBUI_ROUTE_BY_VIEW.values())


GET_JSON_ROUTES: dict[str, GetRoute] = {
    "/api/config": _get_config,
    "/api/summary": _get_summary,
    "/api/timeline": _get_timeline,
    "/api/catalog": _get_catalog,
    "/api/lists": _get_lists,
    "/api/insights": _get_insights,
    "/api/operations": _get_operations,
    OVERLAY_STATE_PATH: _get_overlay_state,
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
        return _redirect_response(_with_query(WEBUI_ROUTE_BY_VIEW["home"], parsed.query))
    if path == "/operations":
        return _redirect_response(
            _with_query(WEBUI_ROUTE_BY_VIEW["operations"], parsed.query)
        )
    if path.endswith("/") and path[:-1] in WEBUI_PAGE_PATHS:
        return _redirect_response(_with_query(path[:-1], parsed.query))
    if path in WEBUI_PAGE_PATHS:
        return _html_response(200, render_webui_html(runtime.csrf_token))
    webui_asset = load_webui_asset(path)
    if webui_asset is not None:
        content_type, body = webui_asset
        return WebUiRouteResponse(200, content_type, body)
    if path == OVERLAY_PAGE_PATH:
        return _html_response(200, render_overlay_html())

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


def _redirect_response(location: str) -> WebUiRouteResponse:
    return WebUiRouteResponse(
        302,
        "text/plain; charset=utf-8",
        f"Found: {location}\n".encode("utf-8"),
        (("Location", location),),
    )


def _with_query(path: str, query: str) -> str:
    return f"{path}?{query}" if query else path
