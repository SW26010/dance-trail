"""Built React assets for the Local Web UI."""

from __future__ import annotations

import json
from pathlib import Path


BOOTSTRAP_PLACEHOLDER = "__DANCING_LOG_BOOTSTRAP__"
WEBUI_ASSET_ROOT = Path(__file__).with_name("webui_dist")
WEBUI_ROUTE_BY_VIEW = {
    "home": "/home",
    "timeline": "/timeline",
    "catalog": "/catalog",
    "lists": "/lists",
    "insights": "/insights",
    "operations": "/data-operations",
    "settings": "/settings",
}
WEBUI_ASSET_CONTENT_TYPES = {
    "/assets/app.js": "text/javascript; charset=utf-8",
}


def render_webui_html(csrf_token: str) -> str:
    """Render the built application shell with a request-local bootstrap payload."""
    html = _read_text_asset("index.html")
    bootstrap = json.dumps(
        {"csrfToken": csrf_token, "routes": WEBUI_ROUTE_BY_VIEW},
        ensure_ascii=True,
        separators=(",", ":"),
    ).replace("<", "\\u003c")
    if BOOTSTRAP_PLACEHOLDER not in html:
        raise RuntimeError("Web UI build is missing its bootstrap placeholder")
    return html.replace(BOOTSTRAP_PLACEHOLDER, bootstrap)


def load_webui_asset(path: str) -> tuple[str, bytes] | None:
    """Load one allow-listed, fingerprint-stable Web UI build asset."""
    content_type = WEBUI_ASSET_CONTENT_TYPES.get(path)
    if content_type is None:
        return None
    filename = path.removeprefix("/assets/")
    return content_type, (WEBUI_ASSET_ROOT / filename).read_bytes()


def _read_text_asset(filename: str) -> str:
    try:
        return (WEBUI_ASSET_ROOT / filename).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Web UI build is missing; run `pnpm build:webui` before starting dancing-log"
        ) from exc
