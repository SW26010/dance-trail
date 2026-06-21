"""Local-only Web UI server for dancing-log."""

from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sys
import threading
import time
from urllib.parse import urlsplit
import webbrowser

from dancing_log.app_paths import AppPaths, default_app_root
from dancing_log.live_app_session import (
    LiveAppSessionRuntime,
    WatchVrcLogsFunc,
)
from dancing_log.webui_routes import (
    WebUiRouteResponse,
    handle_get_request,
    handle_post_request,
)


WEBUI_HOST = "127.0.0.1"
DEFAULT_WEBUI_PORT = 8787
LOCAL_WEBUI_HOSTS = {"127.0.0.1", "localhost"}
CSRF_HEADER = "X-Dancing-Log-CSRF"

@dataclass(frozen=True)
class WebUiRuntime:
    """Resolved runtime paths used by one Web UI server instance."""

    app_root: Path
    csrf_token: str
    session: LiveAppSessionRuntime

    @classmethod
    def from_root(
        cls,
        app_root: Path | str | None = None,
        *,
        session_runtime: LiveAppSessionRuntime | None = None,
        watch_vrc_logs_func: WatchVrcLogsFunc | None = None,
    ) -> "WebUiRuntime":
        if session_runtime is not None and watch_vrc_logs_func is not None:
            raise ValueError("pass either session_runtime or watch_vrc_logs_func, not both")
        root = Path(app_root) if app_root is not None else default_app_root()
        resolved_root = root.resolve()
        session = session_runtime or LiveAppSessionRuntime(
            app_root=resolved_root,
            watch_vrc_logs_func=watch_vrc_logs_func,
        )
        return cls(resolved_root, secrets.token_urlsafe(32), session)

    @property
    def paths(self) -> AppPaths:
        return AppPaths.from_root(self.app_root)


class WebUiServer:
    """Small localhost HTTP server for the main user-facing Web UI."""

    def __init__(
        self,
        *,
        host: str = WEBUI_HOST,
        port: int = DEFAULT_WEBUI_PORT,
        app_root: Path | str | None = None,
        session_runtime: LiveAppSessionRuntime | None = None,
        watch_vrc_logs_func: WatchVrcLogsFunc | None = None,
    ) -> None:
        if host != WEBUI_HOST:
            raise ValueError("web UI server must bind to 127.0.0.1")
        self.host = host
        self.port = port
        self.runtime = WebUiRuntime.from_root(
            app_root,
            session_runtime=session_runtime,
            watch_vrc_logs_func=watch_vrc_logs_func,
        )
        self._owns_session = session_runtime is None
        self._server: _WebUiHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def start(self) -> None:
        self._server = _WebUiHTTPServer((self.host, self.port), _WebUiHandler, self.runtime)
        self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._owns_session:
            self.runtime.session.close()


class _WebUiHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address, request_handler_class, runtime: WebUiRuntime) -> None:
        super().__init__(server_address, request_handler_class)
        self.runtime = runtime

    def handle_error(self, request, client_address) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionAbortedError, ConnectionResetError)):
            return
        if isinstance(exc, OSError) and getattr(exc, "winerror", None) in {10053, 10054}:
            return
        super().handle_error(request, client_address)


class RequestRejected(ValueError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class _WebUiHandler(BaseHTTPRequestHandler):
    server: _WebUiHTTPServer

    def do_GET(self) -> None:
        try:
            self._send_response(handle_get_request(self.server.runtime, self.path))
        except Exception as exc:  # pragma: no cover - kept visible to local UI users.
            self._send_json(500, {"error": str(exc)})

    def do_POST(self) -> None:
        try:
            self._validate_post_request()
            payload = self._read_json_body()
            self._send_response(handle_post_request(self.server.runtime, self.path, payload))
        except RequestRejected as exc:
            self._send_json(exc.status, {"error": exc.message})
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except Exception as exc:  # pragma: no cover - kept visible to local UI users.
            self._send_json(500, {"error": str(exc)})

    def log_message(self, format: str, *args) -> None:
        return

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def _validate_post_request(self) -> None:
        content_type = self.headers.get("Content-Type", "")
        media_type = content_type.split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            raise RequestRejected(415, "POST requires application/json")
        if not self._is_allowed_host(self.headers.get("Host", "")):
            raise RequestRejected(403, "invalid Host")
        origin = self.headers.get("Origin")
        if origin and not self._is_allowed_origin(origin):
            raise RequestRejected(403, "invalid Origin")
        token = self.headers.get(CSRF_HEADER, "")
        if not secrets.compare_digest(token, self.server.runtime.csrf_token):
            raise RequestRejected(403, "invalid CSRF token")

    def _is_allowed_host(self, value: str) -> bool:
        try:
            parsed = urlsplit(f"//{value}")
            port = parsed.port
        except ValueError:
            return False
        hostname = (parsed.hostname or "").lower()
        return hostname in LOCAL_WEBUI_HOSTS and port == int(self.server.server_address[1])

    def _is_allowed_origin(self, value: str) -> bool:
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError:
            return False
        hostname = (parsed.hostname or "").lower()
        return (
            parsed.scheme == "http"
            and hostname in LOCAL_WEBUI_HOSTS
            and port == int(self.server.server_address[1])
        )

    def _send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._send_bytes(status, "application/json; charset=utf-8", data)

    def _send_response(self, response: WebUiRouteResponse) -> None:
        self._send_bytes(response.status, response.content_type, response.body)

    def _send_bytes(self, status: int, content_type: str, payload: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)


def run_webui_server(
    *,
    port: int = DEFAULT_WEBUI_PORT,
    open_browser: bool = True,
    app_root: Path | str | None = None,
) -> None:
    """Run the local Web UI server until interrupted."""
    server = WebUiServer(port=port, app_root=app_root)
    server.start()
    print(f"dancing-log Web UI: {server.url}")
    if open_browser:
        webbrowser.open(server.url)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\nStopping dancing-log Web UI")
    finally:
        server.stop()
