"""Local-only Web UI server for dance-trail."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
import json
from pathlib import Path
import secrets
import time
from urllib.parse import urlsplit
import webbrowser

from dance_trail.app_paths import AppPaths, AppRuntimeConfig, default_app_root
from dance_trail.http_request_lifecycle import (
    AcceptedOperationShutdown,
    HttpShutdownParticipant,
    ManagedLocalHTTPRequestHandler,
    ManagedLocalHTTPServer,
)
from dance_trail.live_app_session import (
    LiveAppSessionRuntime,
    WatchVrcLogsFunc,
)
from dance_trail.overlay_server import (
    EVENT_STREAM_DRAIN_TIMEOUT_SECONDS,
    MountedOverlayAdapter,
    OVERLAY_EVENTS_PATH,
    OVERLAY_PAGE_PATH,
    OverlayEventStreams,
    OverlayState,
    is_allowed_local_http_host,
    is_allowed_local_http_origin,
    send_overlay_events,
)
from dance_trail.webui_assets import WEBUI_ROUTE_BY_VIEW
from dance_trail.webui_routes import (
    WebUiRouteResponse,
    handle_get_request,
    handle_post_request,
)
from dance_trail.watcher_lifetime_lock import (
    WatcherLifetimeLease,
    WatcherLifetimeLockUnavailable,
)


WEBUI_HOST = "127.0.0.1"
DEFAULT_WEBUI_PORT = 8787
CSRF_HEADER = "X-Dance-Trail-CSRF"
MAX_POST_BODY_BYTES = 1024 * 1024
HTTP_REQUEST_READ_DEADLINE_SECONDS = 2.0
HTTP_REQUEST_READ_POLL_SECONDS = 0.25
REJECTED_POST_DRAIN_GRACE_SECONDS = 0.05
CONTROL_PAGE_FRAME_HEADERS = (
    ("Content-Security-Policy", "frame-ancestors 'none'"),
    ("X-Frame-Options", "DENY"),
)


@dataclass(frozen=True)
class WebUiRuntime:
    """Resolved runtime paths used by one Web UI server instance."""

    app_root: Path
    csrf_token: str
    session: LiveAppSessionRuntime
    overlay_state: OverlayState
    live_state: OverlayState
    startup_warnings: tuple[str, ...] = ()

    @classmethod
    def from_root(
        cls,
        app_root: Path | str | None = None,
        *,
        session_runtime: LiveAppSessionRuntime | None = None,
        watch_vrc_logs_func: WatchVrcLogsFunc | None = None,
        overlay_state: OverlayState | None = None,
    ) -> "WebUiRuntime":
        if session_runtime is not None and watch_vrc_logs_func is not None:
            raise ValueError("pass either session_runtime or watch_vrc_logs_func, not both")
        root = Path(app_root) if app_root is not None else default_app_root()
        resolved_root = root.resolve()
        session = session_runtime or LiveAppSessionRuntime(
            app_root=resolved_root,
            watch_vrc_logs_func=watch_vrc_logs_func,
        )
        return cls(
            resolved_root,
            secrets.token_urlsafe(32),
            session,
            overlay_state or OverlayState(enabled=False),
            OverlayState(),
        )

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
        overlay_state: OverlayState | None = None,
    ) -> None:
        if host != WEBUI_HOST:
            raise ValueError("web UI server must bind to 127.0.0.1")
        self.host = host
        self.port = port
        runtime = WebUiRuntime.from_root(
            app_root,
            session_runtime=session_runtime,
            watch_vrc_logs_func=watch_vrc_logs_func,
            overlay_state=overlay_state,
        )
        self.runtime = replace(
            runtime,
            startup_warnings=_run_startup_maintenance(runtime.app_root),
        )
        self._owns_session = session_runtime is None
        self._server: _WebUiHTTPServer | None = None
        self._mounted_overlay: MountedOverlayAdapter | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    @property
    def home_url(self) -> str:
        return f"http://{self.host}:{self.port}{WEBUI_ROUTE_BY_VIEW['home']}"

    @property
    def overlay_url(self) -> str:
        return f"http://{self.host}:{self.port}{OVERLAY_PAGE_PATH}"

    def start(self) -> None:
        server = _WebUiHTTPServer((self.host, self.port), _WebUiHandler, self.runtime)
        self.port = int(server.server_address[1])
        overlay = MountedOverlayAdapter(
            self.runtime.overlay_state,
            url=self.overlay_url,
            live_state=self.runtime.live_state,
        )
        mounted = False
        try:
            self.runtime.session.mount_overlay(overlay)
            mounted = True
            server.start_http(thread_name="DanceTrailWebUiHTTP")
        except BaseException as primary:
            cleanup_errors: list[BaseException] = []
            if mounted:
                try:
                    self.runtime.session.unmount_overlay(overlay)
                except BaseException as exc:
                    cleanup_errors.append(exc)
            try:
                server.stop_http()
            except BaseException as exc:
                cleanup_errors.append(exc)
            self._server = None
            if cleanup_errors:
                raise BaseExceptionGroup(
                    f"Web UI start failed after {primary}",
                    [primary, *cleanup_errors],
                ) from None
            raise
        self._server = server
        self._mounted_overlay = overlay

    def stop(self, *, deadline: float | None = None) -> None:
        cleanup_errors: list[Exception] = []
        if self._server is not None:
            server = self._server
            if deadline is None:
                _attempt_webui_cleanup(cleanup_errors, server.stop_http)
            else:
                _attempt_webui_cleanup(
                    cleanup_errors,
                    lambda: server.stop_http(deadline=deadline),
                )
            self._server = None
        overlay = self._mounted_overlay
        if overlay is not None:
            try:
                if deadline is None:
                    self.runtime.session.unmount_overlay(overlay)
                else:
                    self.runtime.session.unmount_overlay(
                        overlay,
                        deadline=deadline,
                    )
            except Exception as exc:
                cleanup_errors.append(exc)
            finally:
                self._mounted_overlay = None
        if self._owns_session:
            if deadline is None:
                _attempt_webui_cleanup(cleanup_errors, self.runtime.session.close)
            else:
                _attempt_webui_cleanup(
                    cleanup_errors,
                    lambda: self.runtime.session.close(deadline=deadline),
                )
        if len(cleanup_errors) == 1:
            raise cleanup_errors[0]
        if cleanup_errors:
            raise ExceptionGroup("Web UI shutdown failed", cleanup_errors)


def _run_startup_maintenance(app_root: Path) -> tuple[str, ...]:
    try:
        config = AppRuntimeConfig.load(app_root=app_root, )
        app_db_path = config.path("app_db")
        from dance_trail.storage import connect_db, repair_stale_watcher_pending_records

        with WatcherLifetimeLease.acquire(
            app_root=app_root,
            app_db_path=app_db_path,
        ):
            with connect_db(app_db_path) as conn:
                repair_stale_watcher_pending_records(conn)
                conn.commit()
    except WatcherLifetimeLockUnavailable:
        return ()
    except Exception as exc:
        return (f"Startup maintenance failed ({type(exc).__name__}): {exc}",)
    return ()


class _WebUiHTTPServer(ManagedLocalHTTPServer):
    def __init__(self, server_address, request_handler_class, runtime: WebUiRuntime) -> None:
        self.runtime = runtime
        self.event_streams = OverlayEventStreams(runtime.overlay_state)
        super().__init__(
            server_address,
            request_handler_class,
            accepted_operation_shutdown=AcceptedOperationShutdown.DRAIN,
            request_read_deadline_seconds=HTTP_REQUEST_READ_DEADLINE_SECONDS,
            request_read_poll_seconds=HTTP_REQUEST_READ_POLL_SECONDS,
            shutdown_participants=(
                HttpShutdownParticipant(
                    "overlay event streams",
                    self.event_streams,
                    EVENT_STREAM_DRAIN_TIMEOUT_SECONDS,
                ),
            ),
        )


class RequestRejected(ValueError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class _WebUiHandler(ManagedLocalHTTPRequestHandler):
    server: _WebUiHTTPServer

    def do_GET(self) -> None:
        try:
            self._validate_host()
            if urlsplit(self.path).path == OVERLAY_EVENTS_PATH:
                self.perform_operation(
                    lambda: send_overlay_events(self, self.server.event_streams)
                )
                return
            self.perform_operation(
                lambda: self._send_response(
                    handle_get_request(self.server.runtime, self.path)
                )
            )
        except RequestRejected as exc:
            if self._can_send_response():
                self._send_json(exc.status, {"error": exc.message})
        except Exception as exc:  # pragma: no cover - kept visible to local UI users.
            if self._can_send_response():
                self._send_json(500, {"error": str(exc)})

    def do_POST(self) -> None:
        try:
            self._validate_post_headers()
            content_length = self._validated_content_length()
            raw_body = self._read_request_body(content_length)
            payload = self._parse_json_body(raw_body)
            self.perform_operation(
                lambda: self._send_response(
                    handle_post_request(self.server.runtime, self.path, payload)
                )
            )
        except RequestRejected as exc:
            self.close_connection = True
            if not self._can_send_response():
                return
            self._send_json(exc.status, {"error": exc.message})
            writer = getattr(self, "wfile", None)
            if writer is not None:
                try:
                    writer.flush()
                except OSError:
                    pass
            self._discard_available_request_body()
        except ValueError as exc:
            if self._can_send_response():
                self._send_json(400, {"error": str(exc)})
        except Exception as exc:  # pragma: no cover - kept visible to local UI users.
            if self._can_send_response():
                self._send_json(500, {"error": str(exc)})

    def log_message(self, format: str, *args) -> None:
        return

    def _validated_content_length(self) -> int:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError as exc:
            raise RequestRejected(400, "invalid Content-Length") from exc
        if length < 0:
            raise RequestRejected(400, "invalid Content-Length")
        if length > MAX_POST_BODY_BYTES:
            raise RequestRejected(413, "POST body is too large")
        return length

    def _read_request_body(self, length: int) -> bytes:
        if length <= 0:
            return b""
        try:
            raw = self.rfile.read(length)
        except TimeoutError as exc:
            raise RequestRejected(408, "POST body was not received in time") from exc
        if len(raw) != length:
            raise RequestRejected(400, "incomplete request body")
        return raw

    def _discard_available_request_body(self) -> None:
        """Drain a rejected body only within a small, fixed grace period."""
        connection = getattr(self, "connection", None)
        if connection is None:
            return
        try:
            remaining = min(
                max(int(self.headers.get("Content-Length") or 0), 0),
                MAX_POST_BODY_BYTES,
            )
        except ValueError:
            return
        if remaining == 0:
            return

        self.discard_available_body(
            length=remaining,
            grace_seconds=REJECTED_POST_DRAIN_GRACE_SECONDS,
        )

    @staticmethod
    def _parse_json_body(raw: bytes) -> dict:
        if not raw:
            return {}
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def _validate_post_headers(self) -> None:
        self._validate_host()
        content_type = self.headers.get("Content-Type", "")
        media_type = content_type.split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            raise RequestRejected(415, "POST requires application/json")
        origin = self.headers.get("Origin")
        if origin and not self._is_allowed_origin(origin):
            raise RequestRejected(403, "invalid Origin")
        token = self.headers.get(CSRF_HEADER, "")
        if not secrets.compare_digest(token, self.server.runtime.csrf_token):
            raise RequestRejected(403, "invalid CSRF token")

    def _can_send_response(self) -> bool:
        connection = getattr(self, "connection", None)
        if connection is None or not hasattr(connection, "fileno"):
            return True
        return connection.fileno() >= 0

    def _validate_host(self) -> None:
        if not self._is_allowed_host(self.headers.get("Host", "")):
            raise RequestRejected(403, "invalid Host")

    def _is_allowed_host(self, value: str) -> bool:
        return is_allowed_local_http_host(
            value,
            port=int(self.server.server_address[1]),
        )

    def _is_allowed_origin(self, value: str) -> bool:
        return is_allowed_local_http_origin(
            value,
            port=int(self.server.server_address[1]),
        )

    def _send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._send_bytes(status, "application/json; charset=utf-8", data)

    def _send_response(self, response: WebUiRouteResponse) -> None:
        headers = response.headers
        if (
            response.content_type.startswith("text/html")
            and urlsplit(self.path).path != OVERLAY_PAGE_PATH
        ):
            headers += CONTROL_PAGE_FRAME_HEADERS
        self._send_bytes(
            response.status,
            response.content_type,
            response.body,
            headers=headers,
        )

    def _send_bytes(
        self,
        status: int,
        content_type: str,
        payload: bytes,
        *,
        headers: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        if self.close_connection:
            self.send_header("Connection", "close")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)


def _attempt_webui_cleanup(
    errors: list[Exception],
    action: Callable[[], object],
) -> None:
    try:
        action()
    except Exception as exc:
        errors.append(exc)


def run_webui_server(
    *,
    port: int = DEFAULT_WEBUI_PORT,
    open_browser: bool = True,
    app_root: Path | str | None = None,
) -> None:
    """Run the local Web UI server until interrupted."""
    server = WebUiServer(port=port, app_root=app_root)
    server.start()
    print(f"dance-trail Web UI: {server.home_url}")
    print(f"dance-trail OBS overlay: {server.overlay_url}")
    if open_browser:
        webbrowser.open(server.home_url)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\nStopping dance-trail Web UI")
    finally:
        server.stop()
