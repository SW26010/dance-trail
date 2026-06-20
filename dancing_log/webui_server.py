"""Local-only Web UI server for dancing-log."""

from __future__ import annotations

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from dataclasses import asdict, dataclass, is_dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import time
from typing import Any
from urllib.parse import parse_qs, urlparse, urlsplit
from uuid import UUID
import webbrowser

from dancing_log.app_paths import (
    AppRuntimeConfig,
    AppPaths,
    CONFIG_FIELD_BY_KEY,
    CONFIG_FIELDS,
    CONFIG_KEYS,
    default_app_root,
    resolve_config_path,
    save_app_config,
    validate_supported_config,
)
from dancing_log.live_app_session import (
    LiveAppSessionRuntime,
    LiveAppSessionStatus,
    WatchVrcLogsFunc,
)
from dancing_log.read_snapshots import LocalReadSnapshots
from dancing_log.vrc_log_watcher import default_vrc_log_dir


WEBUI_HOST = "127.0.0.1"
DEFAULT_WEBUI_PORT = 8787
LOCAL_WEBUI_HOSTS = {"127.0.0.1", "localhost"}
CSRF_HEADER = "X-Dancing-Log-CSRF"

S_OK = 0
S_FALSE = 1
COINIT_APARTMENTTHREADED = 0x2
CLSCTX_INPROC_SERVER = 0x1
ERROR_CANCELLED = 1223
HRESULT_ERROR_CANCELLED = 0x800704C7
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
SIGDN_FILESYSPATH = 0x80058000
FOS_PICKFOLDERS = 0x20
FOS_FORCEFILESYSTEM = 0x40
FOS_PATHMUSTEXIST = 0x800
FOS_FILEMUSTEXIST = 0x1000


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    def __init__(self, value: str) -> None:
        super().__init__()
        parsed = UUID(value)
        self.Data1 = parsed.time_low
        self.Data2 = parsed.time_mid
        self.Data3 = parsed.time_hi_version
        self.Data4 = (ctypes.c_ubyte * 8).from_buffer_copy(parsed.bytes[8:])


class COMDLG_FILTERSPEC(ctypes.Structure):
    _fields_ = [
        ("pszName", wintypes.LPCWSTR),
        ("pszSpec", wintypes.LPCWSTR),
    ]


CLSID_FileOpenDialog = GUID("{DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7}")
IID_IFileOpenDialog = GUID("{D57C7288-D4AD-4768-BE02-9D969532D960}")
IID_IShellItem = GUID("{43826D1E-E718-42EE-BC55-A1E261C37BFE}")

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
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            if path in {"", "/"}:
                html = _WEBUI_HTML.replace("__DANCING_LOG_CSRF_TOKEN__", self.server.runtime.csrf_token)
                self._send_bytes(200, "text/html; charset=utf-8", html.encode("utf-8"))
            elif path == "/api/config":
                self._send_json(200, load_config_snapshot(self.server.runtime))
            elif path == "/api/summary":
                self._send_json(200, load_summary_snapshot(self.server.runtime))
            elif path == "/api/timeline":
                self._send_json(200, load_timeline_snapshot(self.server.runtime, query))
            elif path == "/api/catalog":
                self._send_json(200, load_catalog_snapshot(self.server.runtime, query))
            elif path == "/api/lists":
                self._send_json(200, load_lists_snapshot(self.server.runtime))
            elif path == "/api/insights":
                self._send_json(200, load_insights_snapshot(self.server.runtime))
            elif path == "/api/operations":
                self._send_json(200, load_operations_snapshot())
            else:
                self._send_json(404, {"error": "not found"})
        except Exception as exc:  # pragma: no cover - kept visible to local UI users.
            self._send_json(500, {"error": str(exc)})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            self._validate_post_request()
            payload = self._read_json_body()
            if parsed.path == "/api/config":
                response, status = save_config_from_payload(self.server.runtime, payload)
                self._send_json(status, response)
            elif parsed.path == "/api/resolve-path":
                response, status = resolve_path_from_payload(self.server.runtime, payload)
                self._send_json(status, response)
            elif parsed.path == "/api/pick-path":
                response, status = pick_path_from_payload(self.server.runtime, payload)
                self._send_json(status, response)
            elif parsed.path == "/api/live/watcher":
                response, status = control_live_watcher_from_payload(self.server.runtime, payload)
                self._send_json(status, response)
            elif parsed.path == "/api/live/overlay":
                response, status = control_live_overlay_from_payload(self.server.runtime, payload)
                self._send_json(status, response)
            else:
                self._send_json(404, {"error": "not found"})
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


def load_config_snapshot(runtime: WebUiRuntime) -> dict:
    """Return saved configuration plus editor metadata."""
    raw = _read_saved_config(runtime)
    config = AppRuntimeConfig.load(app_root=runtime.app_root)
    unsupported = {
        key: value
        for key, value in raw.items()
        if key not in CONFIG_KEYS
    }
    warnings = []
    if unsupported:
        warnings.append("Unsupported keys are preserved as read-only values.")

    return {
        "app_root": str(runtime.app_root),
        "config_path": str(runtime.paths.local_config_file),
        "config": config.supported_values(),
        "fields": [_field_snapshot(field, config.get(field["key"]), runtime) for field in CONFIG_FIELDS],
        "unsupported": unsupported,
        "detected_sources": _detected_source_paths(),
        "warnings": warnings,
    }


def save_config_from_payload(runtime: WebUiRuntime, payload: dict) -> tuple[dict, int]:
    """Validate and save supported config fields while preserving unsupported keys."""
    draft = payload.get("config")
    if not isinstance(draft, dict):
        return {"errors": {"config": "config must be a JSON object"}}, 400

    supported, errors = validate_supported_config(draft)
    if errors:
        return {"errors": errors, "snapshot": load_config_snapshot(runtime)}, 400

    existing = _read_saved_config(runtime)
    merged = dict(existing)
    for key in CONFIG_KEYS:
        merged[key] = supported[key]
    save_app_config(merged, app_root=runtime.app_root)
    return {"saved": True, "snapshot": load_config_snapshot(runtime)}, 200


def pick_path_from_payload(runtime: WebUiRuntime, payload: dict) -> tuple[dict, int]:
    """Open a field-driven native Windows file/folder picker."""
    field_key = str(payload.get("field") or "")
    field = CONFIG_FIELD_BY_KEY.get(field_key)
    if not field or field.get("type") != "path":
        return {"error": "unsupported path field"}, 400
    if os.name != "nt":
        return {"error": "native picker is only available on Windows"}, 501

    current_value = payload.get("current_value")
    initial = _path_value_preview(field, current_value, runtime).get("resolved")
    selected = _run_windows_picker(field, initial)
    if selected is None:
        return {"cancelled": True}, 200
    path = Path(selected)
    if not path.exists():
        return {"error": "selected path does not exist"}, 400
    if field.get("picker") == "directory" and not path.is_dir():
        return {"error": "selected path is not a directory"}, 400
    if field.get("picker") == "file" and not path.is_file():
        return {"error": "selected path is not a file"}, 400
    return {"field": field_key, "value": str(path)}, 200


def resolve_path_from_payload(runtime: WebUiRuntime, payload: dict) -> tuple[dict, int]:
    """Resolve a draft path value for Settings preview without saving it."""
    field_key = str(payload.get("field") or "")
    field = CONFIG_FIELD_BY_KEY.get(field_key)
    if not field or field.get("type") != "path":
        return {"error": "unsupported path field"}, 400
    return {
        "field": field_key,
        "path": _path_value_preview(field, payload.get("current_value"), runtime),
    }, 200


def load_summary_snapshot(runtime: WebUiRuntime) -> dict:
    snapshot = LocalReadSnapshots(runtime.app_root).home(
        config_warnings=load_config_snapshot(runtime).get("warnings", []),
    )
    snapshot["session"] = live_session_status_snapshot(runtime.session.status())
    return snapshot


def control_live_watcher_from_payload(runtime: WebUiRuntime, payload: dict) -> tuple[dict, int]:
    action = str(payload.get("action") or "").strip().lower()
    if action == "start":
        runtime.session.start_watcher()
    elif action == "stop":
        runtime.session.stop_watcher()
    else:
        return {"error": "action must be start or stop"}, 400
    return {"session": live_session_status_snapshot(runtime.session.status())}, 200


def control_live_overlay_from_payload(runtime: WebUiRuntime, payload: dict) -> tuple[dict, int]:
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


def load_timeline_snapshot(runtime: WebUiRuntime, query: dict[str, list[str]]) -> dict:
    return LocalReadSnapshots(runtime.app_root).timeline(query)


def load_catalog_snapshot(runtime: WebUiRuntime, query: dict[str, list[str]]) -> dict:
    return LocalReadSnapshots(runtime.app_root).catalog(query)


def load_lists_snapshot(runtime: WebUiRuntime) -> dict:
    return LocalReadSnapshots(runtime.app_root).lists()


def load_insights_snapshot(runtime: WebUiRuntime) -> dict:
    return LocalReadSnapshots(runtime.app_root).insights()


def load_operations_snapshot() -> dict:
    return {
        "operations": [
            {
                "key": "import-vrcx",
                "title": "Import VRCX history",
                "command": "uv run python main.py import-vrcx",
                "risk": "writes playback history",
            },
            {
                "key": "sync-wanna",
                "title": "Sync WannaDance catalog",
                "command": "uv run python main.py sync-wanna",
                "risk": "updates catalog rows",
            },
            {
                "key": "sync-queued-self",
                "title": "Sync queued-self manifests",
                "command": "uv run python main.py sync-queued-self --system wannadance",
                "risk": "updates planned-list derived rows",
            },
            {
                "key": "rebuild-data",
                "title": "Rebuild generated data",
                "command": "uv run python main.py rebuild-data --archive-existing",
                "risk": "archives and recreates generated database state",
            },
        ]
    }


def _field_snapshot(field: dict[str, Any], value: Any, runtime: WebUiRuntime) -> dict:
    snapshot = dict(field)
    snapshot["value"] = value
    if field.get("type") == "path":
        snapshot["path"] = _path_value_preview(field, value, runtime)
    return snapshot


def _path_value_preview(field: dict[str, Any], value: Any, runtime: WebUiRuntime) -> dict:
    resolved = resolve_config_path(field["key"], value, app_root=runtime.app_root)
    if resolved is None:
        return {"resolved": None, "exists": None}
    return _safe_path_preview(resolved)


def _read_saved_config(runtime: WebUiRuntime) -> dict:
    paths = runtime.paths
    config_path = paths.local_config_file
    if config_path.exists():
        return _read_json_file(config_path)
    legacy_path = paths.legacy_local_config_file
    if legacy_path.exists():
        return _read_json_file(legacy_path)
    return {}


def _read_json_file(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError(f"config file must contain a JSON object: {path}")
    return raw


def _detected_source_paths() -> list[dict[str, Any]]:
    candidates = []
    try:
        vrc_log_dir = default_vrc_log_dir()
        preview = _safe_path_preview(vrc_log_dir)
        candidates.append(
            {
                "field": "vrc_log_dir",
                "label": "Default VRChat log directory",
                "value": str(vrc_log_dir),
                "exists": preview["exists"],
                "kind": preview["kind"],
                "error": preview.get("error"),
            }
        )
    except Exception:
        pass
    return candidates


def _safe_path_preview(path: Path) -> dict:
    try:
        exists = path.exists()
        if path.is_dir():
            kind = "directory"
        elif path.is_file():
            kind = "file"
        else:
            kind = "missing"
        return {"resolved": str(path), "exists": exists, "kind": kind}
    except OSError as exc:
        return {
            "resolved": str(path),
            "exists": False,
            "kind": "inaccessible",
            "error": str(exc),
        }


def _run_windows_picker(field: dict[str, Any], initial: str | None) -> str | None:
    mode = "directory" if field.get("picker") == "directory" else "file"
    return _show_windows_file_open_dialog(
        mode=mode,
        title=str(field.get("label") or "Select path"),
        initial=initial,
    )


def _show_windows_file_open_dialog(*, mode: str, title: str, initial: str | None) -> str | None:
    result: dict[str, Any] = {}

    def worker() -> None:
        try:
            result["value"] = _show_windows_file_open_dialog_sta(
                mode=mode,
                title=title,
                initial=initial,
            )
        except BaseException as exc:  # pragma: no cover - surfaced through the request.
            result["error"] = exc

    thread = threading.Thread(target=worker, name="dancing-log-picker")
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


def _show_windows_file_open_dialog_sta(*, mode: str, title: str, initial: str | None) -> str | None:
    ole32 = ctypes.WinDLL("ole32")
    shell32 = ctypes.WinDLL("shell32")
    coinit_hr = _co_initialize_sta(ole32)
    try:
        with _picker_dpi_context():
            dialog = _create_file_open_dialog(ole32)
            try:
                _configure_file_open_dialog(dialog, shell32, mode=mode, title=title, initial=initial)
                show = _com_method(dialog, 3, ctypes.c_long, wintypes.HWND)
                hr = show(dialog, _foreground_window_handle())
                if _is_cancelled_hresult(hr):
                    return None
                _check_hresult(hr, "show native picker")
                return _file_dialog_result_path(dialog, ole32)
            finally:
                _com_release(dialog)
    finally:
        if coinit_hr in {S_OK, S_FALSE}:
            ole32.CoUninitialize()


def _co_initialize_sta(ole32) -> int:
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = ctypes.c_long
    hr = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    _check_hresult(hr, "initialize COM apartment")
    return hr


@contextmanager
def _picker_dpi_context():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    set_context = getattr(user32, "SetThreadDpiAwarenessContext", None)
    if set_context is None:
        yield
        return
    set_context.argtypes = [ctypes.c_void_p]
    set_context.restype = ctypes.c_void_p
    previous = set_context(_signed_handle(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2))
    try:
        yield
    finally:
        if previous:
            set_context(previous)


def _signed_handle(value: int) -> ctypes.c_void_p:
    bits = ctypes.sizeof(ctypes.c_void_p) * 8
    return ctypes.c_void_p(value & ((1 << bits) - 1))


def _create_file_open_dialog(ole32) -> ctypes.c_void_p:
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(GUID),
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ole32.CoCreateInstance.restype = ctypes.c_long
    dialog = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(
        ctypes.byref(CLSID_FileOpenDialog),
        None,
        CLSCTX_INPROC_SERVER,
        ctypes.byref(IID_IFileOpenDialog),
        ctypes.byref(dialog),
    )
    _check_hresult(hr, "create IFileOpenDialog")
    return dialog


def _configure_file_open_dialog(
    dialog: ctypes.c_void_p,
    shell32,
    *,
    mode: str,
    title: str,
    initial: str | None,
) -> None:
    options = wintypes.DWORD()
    get_options = _com_method(dialog, 10, ctypes.c_long, ctypes.POINTER(wintypes.DWORD))
    hr = get_options(dialog, ctypes.byref(options))
    _check_hresult(hr, "read native picker options")

    set_options = _com_method(dialog, 9, ctypes.c_long, wintypes.DWORD)
    hr = set_options(dialog, _file_dialog_options(mode, int(options.value)))
    _check_hresult(hr, "set native picker options")

    set_title = _com_method(dialog, 17, ctypes.c_long, wintypes.LPCWSTR)
    hr = set_title(dialog, title)
    _check_hresult(hr, "set native picker title")

    if mode == "file":
        _set_sqlite_file_filters(dialog)
    _set_initial_folder(dialog, shell32, mode=mode, initial=initial)


def _file_dialog_options(mode: str, existing: int) -> int:
    options = existing | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST
    if mode == "directory":
        return options | FOS_PICKFOLDERS
    return options | FOS_FILEMUSTEXIST


def _set_sqlite_file_filters(dialog: ctypes.c_void_p) -> None:
    filters = (COMDLG_FILTERSPEC * 2)(
        COMDLG_FILTERSPEC("SQLite databases (*.sqlite;*.sqlite3;*.db)", "*.sqlite;*.sqlite3;*.db"),
        COMDLG_FILTERSPEC("All files (*.*)", "*.*"),
    )
    set_file_types = _com_method(
        dialog,
        4,
        ctypes.c_long,
        ctypes.c_uint,
        ctypes.POINTER(COMDLG_FILTERSPEC),
    )
    hr = set_file_types(dialog, len(filters), filters)
    _check_hresult(hr, "set native picker file filters")
    set_file_type_index = _com_method(dialog, 5, ctypes.c_long, ctypes.c_uint)
    hr = set_file_type_index(dialog, 1)
    _check_hresult(hr, "set native picker file filter index")


def _set_initial_folder(dialog: ctypes.c_void_p, shell32, *, mode: str, initial: str | None) -> None:
    folder = _initial_dialog_folder(mode, initial)
    if folder is None:
        return
    shell_item = _shell_item_from_path(shell32, folder)
    if not shell_item:
        return
    try:
        set_folder = _com_method(dialog, 12, ctypes.c_long, ctypes.c_void_p)
        hr = set_folder(dialog, shell_item)
        _check_hresult(hr, "set native picker folder")
        if mode == "file" and initial:
            path = Path(initial)
            try:
                if path.is_file():
                    set_file_name = _com_method(dialog, 15, ctypes.c_long, wintypes.LPCWSTR)
                    hr = set_file_name(dialog, path.name)
                    _check_hresult(hr, "set native picker file name")
            except OSError:
                pass
    finally:
        _com_release(shell_item)


def _initial_dialog_folder(mode: str, initial: str | None) -> Path | None:
    if not initial:
        return None
    path = Path(initial)
    try:
        if path.is_dir():
            return path
        if mode == "file" and path.is_file():
            return path.parent
        parent = path.parent
        if parent and parent.exists():
            return parent
    except OSError:
        return None
    return None


def _shell_item_from_path(shell32, path: Path) -> ctypes.c_void_p | None:
    shell32.SHCreateItemFromParsingName.argtypes = [
        wintypes.LPCWSTR,
        ctypes.c_void_p,
        ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    shell32.SHCreateItemFromParsingName.restype = ctypes.c_long
    shell_item = ctypes.c_void_p()
    hr = shell32.SHCreateItemFromParsingName(
        str(path),
        None,
        ctypes.byref(IID_IShellItem),
        ctypes.byref(shell_item),
    )
    if hr < 0:
        return None
    return shell_item


def _file_dialog_result_path(dialog: ctypes.c_void_p, ole32) -> str | None:
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole32.CoTaskMemFree.restype = None
    get_result = _com_method(dialog, 20, ctypes.c_long, ctypes.POINTER(ctypes.c_void_p))
    shell_item = ctypes.c_void_p()
    hr = get_result(dialog, ctypes.byref(shell_item))
    _check_hresult(hr, "read native picker result")
    try:
        get_display_name = _com_method(
            shell_item,
            5,
            ctypes.c_long,
            ctypes.c_uint,
            ctypes.POINTER(wintypes.LPWSTR),
        )
        raw_path = wintypes.LPWSTR()
        hr = get_display_name(shell_item, SIGDN_FILESYSPATH, ctypes.byref(raw_path))
        _check_hresult(hr, "read native picker result path")
        try:
            return raw_path.value
        finally:
            if raw_path:
                ole32.CoTaskMemFree(ctypes.cast(raw_path, ctypes.c_void_p))
    finally:
        _com_release(shell_item)


def _foreground_window_handle() -> wintypes.HWND:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    return user32.GetForegroundWindow()


def _com_method(interface: ctypes.c_void_p, index: int, restype, *argtypes):
    vtable = ctypes.cast(interface, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    prototype = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return prototype(vtable[index])


def _com_release(interface: ctypes.c_void_p | None) -> None:
    if not interface:
        return
    release = _com_method(interface, 2, wintypes.ULONG)
    release(interface)


def _is_cancelled_hresult(hr: int) -> bool:
    return (hr & 0xFFFFFFFF) in {HRESULT_ERROR_CANCELLED, _hresult_from_win32(ERROR_CANCELLED)}


def _hresult_from_win32(error_code: int) -> int:
    return 0x80070000 | error_code


def _check_hresult(hr: int, action: str) -> None:
    if hr < 0:
        raise RuntimeError(f"{action} failed with HRESULT 0x{hr & 0xFFFFFFFF:08X}")


_WEBUI_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>dancing-log</title>
<style>
:root {
  color-scheme: light;
  --bg: #f6f7f9;
  --panel: #ffffff;
  --panel-alt: #fbfbfc;
  --line: #d8dde5;
  --line-strong: #b8c0cc;
  --text: #18212f;
  --muted: #657083;
  --blue: #256fc4;
  --green: #187758;
  --orange: #a95716;
  --red: #b33131;
  --violet: #6c5a9a;
  --shadow: 0 10px 26px rgba(24, 33, 47, 0.08);
  --sidebar: #111820;
  --sidebar-text: #edf2f7;
  --sidebar-muted: #aeb8c6;
  --sidebar-hover: #182333;
  --sidebar-hover-line: #344154;
  --nav-active-bg: #eef4ff;
  --nav-active-text: #132033;
  --input-bg: #ffffff;
  --input-readonly: #eef1f5;
  --primary-text: #ffffff;
  --code-bg: #111820;
  --code-text: #e7edf6;
  --green-line: #98d6c1;
  --green-bg: #eef9f5;
  --orange-line: #e5bf96;
  --orange-bg: #fff7ed;
  --red-line: #e8abab;
  --red-bg: #fff1f1;
  --violet-line: #c9bee5;
  --violet-bg: #f7f3ff;
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --bg: #0f1319;
    --panel: #171d25;
    --panel-alt: #1e2630;
    --line: #303948;
    --line-strong: #4a5668;
    --text: #e7edf4;
    --muted: #a3adbd;
    --blue: #78adf3;
    --green: #74c7a6;
    --orange: #e8a45d;
    --red: #f07b7b;
    --violet: #ada3e8;
    --shadow: 0 12px 30px rgba(0, 0, 0, 0.28);
    --sidebar: #0b1016;
    --sidebar-text: #edf2f7;
    --sidebar-muted: #9ca8b8;
    --sidebar-hover: #17202b;
    --sidebar-hover-line: #344052;
    --nav-active-bg: #d9e7ff;
    --nav-active-text: #08111d;
    --input-bg: #101820;
    --input-readonly: #202936;
    --primary-text: #08111d;
    --code-bg: #0b1016;
    --code-text: #e7edf4;
    --green-line: rgba(116, 199, 166, 0.55);
    --green-bg: rgba(30, 92, 72, 0.28);
    --orange-line: rgba(232, 164, 93, 0.58);
    --orange-bg: rgba(118, 76, 30, 0.28);
    --red-line: rgba(240, 123, 123, 0.58);
    --red-bg: rgba(117, 42, 48, 0.28);
    --violet-line: rgba(173, 163, 232, 0.58);
    --violet-bg: rgba(75, 64, 128, 0.28);
  }
}
* { box-sizing: border-box; }
html, body { margin: 0; min-height: 100%; background: var(--bg); color: var(--text); }
body { font-family: "Segoe UI", system-ui, sans-serif; font-size: 14px; letter-spacing: 0; }
button, input, select { font: inherit; letter-spacing: 0; }
button { cursor: pointer; }
.app {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 232px minmax(0, 1fr);
}
.sidebar {
  background: var(--sidebar);
  color: var(--sidebar-text);
  padding: 18px 14px;
  display: grid;
  grid-template-rows: auto 1fr auto;
  gap: 18px;
}
.brand { display: grid; gap: 3px; padding: 0 8px; }
.brand strong { font-size: 18px; font-weight: 700; }
.brand span { color: var(--sidebar-muted); font-size: 12px; }
.nav { display: grid; align-content: start; gap: 4px; }
.nav button {
  min-height: 40px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: var(--sidebar-text);
  text-align: left;
  padding: 0 12px;
}
.nav button:hover { border-color: var(--sidebar-hover-line); background: var(--sidebar-hover); }
.nav button.active { background: var(--nav-active-bg); color: var(--nav-active-text); }
.sidebar-foot { color: var(--sidebar-muted); font-size: 12px; padding: 0 8px; overflow-wrap: anywhere; }
.main { min-width: 0; padding: 22px; display: grid; gap: 16px; align-content: start; }
.topbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.title-block { min-width: 0; }
h1 { margin: 0; font-size: 24px; line-height: 1.2; }
.subtitle { margin-top: 4px; color: var(--muted); overflow-wrap: anywhere; }
.top-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}
.toolbar { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.language-switch {
  display: inline-grid;
  grid-template-columns: repeat(2, minmax(44px, auto));
  border: 1px solid var(--line-strong);
  border-radius: 7px;
  overflow: hidden;
  background: var(--panel);
}
.language-switch button {
  min-height: 34px;
  border: 0;
  border-right: 1px solid var(--line-strong);
  background: transparent;
  color: var(--muted);
  padding: 0 10px;
}
.language-switch button:last-child { border-right: 0; }
.language-switch button.active {
  background: var(--blue);
  color: var(--primary-text);
}
.button {
  min-height: 36px;
  border-radius: 7px;
  border: 1px solid var(--line-strong);
  background: var(--panel);
  color: var(--text);
  padding: 0 12px;
}
.button.primary { background: var(--blue); border-color: var(--blue); color: var(--primary-text); }
.button.danger { color: var(--red); border-color: var(--red-line); }
.button:disabled { opacity: 0.55; cursor: default; }
.view { display: none; gap: 16px; align-content: start; }
.view.active { display: grid; }
.grid { display: grid; gap: 14px; }
.summary-grid { grid-template-columns: repeat(4, minmax(150px, 1fr)); }
.two-col { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  box-shadow: var(--shadow);
  min-width: 0;
}
.panel-head {
  min-height: 48px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.panel-head h2 { margin: 0; font-size: 15px; }
.panel-body { padding: 14px; display: grid; gap: 12px; min-width: 0; }
.metric { display: grid; gap: 4px; padding: 14px; }
.metric span { color: var(--muted); font-size: 12px; }
.metric strong { font-size: 24px; line-height: 1.1; }
.status-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.status-item {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel-alt);
  padding: 10px;
  display: grid;
  gap: 8px;
}
.status-item span { color: var(--muted); font-size: 12px; }
.pill-row { display: flex; flex-wrap: wrap; gap: 6px; }
.pill {
  min-height: 24px;
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--panel-alt);
  padding: 0 9px;
  color: var(--muted);
  font-size: 12px;
}
.pill.green { color: var(--green); border-color: var(--green-line); background: var(--green-bg); }
.pill.orange { color: var(--orange); border-color: var(--orange-line); background: var(--orange-bg); }
.pill.red { color: var(--red); border-color: var(--red-line); background: var(--red-bg); }
.pill.violet { color: var(--violet); border-color: var(--violet-line); background: var(--violet-bg); }
.settings-grid { display: grid; gap: 14px; }
.field-row {
  display: grid;
  grid-template-columns: minmax(160px, 230px) minmax(0, 1fr);
  gap: 12px;
  align-items: start;
  padding: 12px 0;
  border-bottom: 1px solid var(--line);
}
.field-row:last-child { border-bottom: 0; }
.field-label { display: grid; gap: 4px; }
.field-label strong { font-weight: 650; }
.field-label code { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
.field-summary { color: var(--muted); font-size: 12px; line-height: 1.35; }
.field-control { display: grid; gap: 7px; min-width: 0; }
.input-line { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; }
input[type="text"], input[type="number"], input[type="date"], select {
  width: 100%;
  min-height: 36px;
  border-radius: 7px;
  border: 1px solid var(--line-strong);
  background: var(--input-bg);
  color: var(--text);
  padding: 0 10px;
}
input[type="checkbox"] { accent-color: var(--blue); }
input[readonly] { background: var(--input-readonly); color: var(--muted); }
.toggle-line {
  min-height: 36px;
  display: inline-flex;
  align-items: center;
  gap: 9px;
}
.toggle-line input { width: 18px; height: 18px; }
.resolved { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
.resolved.ok { color: var(--green); }
.resolved.missing { color: var(--orange); }
.message {
  display: none;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: var(--panel-alt);
  padding: 10px 12px;
  color: var(--muted);
}
.message.show { display: block; }
.message.error { color: var(--red); border-color: var(--red-line); background: var(--red-bg); }
.message.success { color: var(--green); border-color: var(--green-line); background: var(--green-bg); }
.readonly-json {
  margin: 0;
  overflow: auto;
  background: var(--code-bg);
  color: var(--code-text);
  border-radius: 7px;
  padding: 12px;
  max-height: 240px;
}
table { width: 100%; border-collapse: collapse; table-layout: fixed; }
th, td {
  text-align: left;
  padding: 10px;
  border-bottom: 1px solid var(--line);
  vertical-align: top;
  overflow-wrap: anywhere;
}
th { color: var(--muted); font-size: 12px; font-weight: 650; background: var(--panel-alt); }
tr:last-child td { border-bottom: 0; }
.empty { color: var(--muted); padding: 14px; }
.list-stack { display: grid; gap: 8px; }
.list-item {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 10px;
  display: grid;
  gap: 5px;
  background: var(--panel-alt);
}
.list-item strong { overflow-wrap: anywhere; }
.list-item code { color: var(--muted); overflow-wrap: anywhere; }
@media (max-width: 980px) {
  .app { grid-template-columns: 1fr; }
  .sidebar { position: sticky; top: 0; z-index: 2; grid-template-rows: auto auto; }
  .nav { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .sidebar-foot { display: none; }
  .summary-grid, .two-col, .status-grid { grid-template-columns: 1fr; }
}
@media (max-width: 680px) {
  .main { padding: 14px; }
  .topbar { align-items: stretch; flex-direction: column; }
  .top-actions { justify-content: flex-start; }
  .toolbar { justify-content: flex-start; }
  .field-row { grid-template-columns: 1fr; }
  .input-line { grid-template-columns: 1fr; }
  .nav { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<div class="app">
  <aside class="sidebar">
    <div class="brand"><strong>dancing-log</strong><span id="brand-subtitle">Local Web UI</span></div>
    <nav class="nav" id="nav"></nav>
    <div class="sidebar-foot" id="sidebar-path"></div>
  </aside>
  <main class="main">
    <div class="topbar">
      <div class="title-block">
        <h1 id="view-title">Settings</h1>
        <div class="subtitle" id="view-subtitle"></div>
      </div>
      <div class="top-actions">
        <div class="language-switch" id="language-switch" role="group" aria-label="Language"></div>
        <div class="toolbar" id="view-toolbar"></div>
      </div>
    </div>
    <section class="view" id="view-home"></section>
    <section class="view" id="view-timeline"></section>
    <section class="view" id="view-catalog"></section>
    <section class="view" id="view-lists"></section>
    <section class="view" id="view-insights"></section>
    <section class="view" id="view-operations"></section>
    <section class="view active" id="view-settings"></section>
  </main>
</div>
<script>
const LANGUAGE_KEY = "dancing-log.language";
const CSRF_TOKEN = "__DANCING_LOG_CSRF_TOKEN__";
const NAV = ["home", "timeline", "catalog", "lists", "insights", "operations", "settings"];
const TEXT = {
  en: {
    brandSubtitle: "Local Web UI",
    languageLabel: "Language",
    nav_home: "Home",
    nav_timeline: "Timeline",
    nav_catalog: "Catalog",
    nav_lists: "Lists",
    nav_insights: "Insights",
    nav_operations: "Data Operations",
    nav_settings: "Settings",
    title_home: "Home",
    subtitle_home: "Runtime status and recent activity",
    title_timeline: "Timeline",
    subtitle_timeline: "Chronological playback records",
    title_catalog: "Catalog",
    subtitle_catalog: "Dance tracks and local preferences",
    title_lists: "Lists",
    subtitle_lists: "Planned dance lists",
    title_insights: "Insights",
    subtitle_insights: "Confirmed-history summaries",
    title_operations: "Data Operations",
    subtitle_operations: "Controlled bulk workflows",
    title_settings: "Settings",
    subtitle_settings: "Saved local configuration",
    reset: "Reset",
    resetTitle: "Reload saved configuration",
    save: "Save",
    saveTitle: "Save configuration",
    browse: "Browse",
    browseTitle: "Open native {kind} picker",
    enabled: "Enabled",
    disabled: "Disabled",
    loadingConfig: "Loading configuration...",
    saved: "Saved",
    saveFailed: "Save failed",
    savedNull: "Saved as null",
    exists: "exists",
    missing: "missing",
    inaccessible: "inaccessible",
    detectedSources: "Detected source paths",
    defaultVrcLogDir: "Default VRChat log directory",
    unsupportedKeys: "Unsupported configuration keys",
    preserved: "Preserved",
    loading: "Loading...",
    danceTracks: "Dance tracks",
    officialRecords: "Official records",
    liveRows: "Live rows",
    vrcxRows: "VRCX rows",
    runtimeState: "Runtime state",
    dbFound: "DB found",
    noDb: "No DB",
    noLiveRow: "No live playback row",
    recentOfficial: "Recent official records",
    local: "local",
    noRecords: "No records",
    time: "Time",
    track: "Track",
    source: "Source",
    official: "Official",
    live: "Live",
    load: "Load",
    noTimelineRecords: "No timeline records",
    record: "Record",
    reviewStatus: "Review status",
    status_unchecked: "unchecked",
    status_user_confirmed: "user confirmed",
    status_user_discarded: "user discarded",
    searchCatalog: "Search catalog",
    search: "Search",
    noTracks: "No tracks",
    title: "Title",
    artist: "Artist",
    preferences: "Preferences",
    favorite: "favorite",
    wantToLearn: "want to learn",
    queuedSelfManifests: "Queued-self manifests",
    found: "found",
    noManifests: "No manifests",
    sourceDistribution: "Source distribution",
    topTracks: "Top tracks",
    recommendations: "Recommendations",
    noData: "No data",
    name: "Name",
    count: "Count",
    liveStatus: "Live status",
    watcher: "Watcher",
    overlay: "Overlay",
    running: "Running",
    stopped: "Stopped",
    refresh: "Refresh",
    startWatcher: "Start watcher",
    stopWatcher: "Stop watcher",
    startOverlay: "Start overlay",
    stopOverlay: "Stop overlay",
    databaseState: "Database state",
    currentLiveRow: "Current live row",
    lastRuntimeError: "Last runtime error",
    lastWatcherStats: "Last watcher stats",
    noWatcherStats: "No watcher stats yet",
    liveControlFailed: "Live control failed"
  },
  zh: {
    brandSubtitle: "本地 Web UI",
    languageLabel: "语言",
    nav_home: "首页",
    nav_timeline: "时间线",
    nav_catalog: "目录",
    nav_lists: "清单",
    nav_insights: "洞察",
    nav_operations: "数据操作",
    nav_settings: "设置",
    title_home: "首页",
    subtitle_home: "运行状态和最近活动",
    title_timeline: "时间线",
    subtitle_timeline: "按时间顺序查看播放记录",
    title_catalog: "目录",
    subtitle_catalog: "舞蹈条目和本地偏好",
    title_lists: "清单",
    subtitle_lists: "计划中的舞蹈清单",
    title_insights: "洞察",
    subtitle_insights: "基于已确认历史的汇总",
    title_operations: "数据操作",
    subtitle_operations: "受控的批量工作流",
    title_settings: "设置",
    subtitle_settings: "已保存的本地配置",
    reset: "重置",
    resetTitle: "重新载入已保存配置",
    save: "保存",
    saveTitle: "保存配置",
    browse: "浏览",
    browseTitle: "打开原生{kind}选择器",
    enabled: "已启用",
    disabled: "已禁用",
    loadingConfig: "正在加载配置...",
    saved: "已保存",
    saveFailed: "保存失败",
    savedNull: "保存为空值",
    exists: "存在",
    missing: "缺失",
    inaccessible: "不可访问",
    detectedSources: "检测到的来源路径",
    defaultVrcLogDir: "默认 VRChat 日志目录",
    unsupportedKeys: "不支持的配置键",
    preserved: "已保留",
    loading: "正在加载...",
    danceTracks: "舞蹈条目",
    officialRecords: "正式记录",
    liveRows: "实时记录",
    vrcxRows: "VRCX 记录",
    runtimeState: "运行状态",
    dbFound: "数据库已找到",
    noDb: "无数据库",
    noLiveRow: "没有实时播放记录",
    recentOfficial: "最近正式记录",
    local: "本地",
    noRecords: "没有记录",
    time: "时间",
    track: "条目",
    source: "来源",
    official: "正式",
    live: "实时",
    load: "加载",
    noTimelineRecords: "没有时间线记录",
    record: "记录",
    reviewStatus: "审核状态",
    status_unchecked: "未检查",
    status_user_confirmed: "用户已确认",
    status_user_discarded: "用户已丢弃",
    searchCatalog: "搜索目录",
    search: "搜索",
    noTracks: "没有条目",
    title: "标题",
    artist: "艺人",
    preferences: "偏好",
    favorite: "收藏",
    wantToLearn: "想学",
    queuedSelfManifests: "自选队列清单",
    found: "已找到",
    noManifests: "没有清单",
    sourceDistribution: "来源分布",
    topTracks: "常跳条目",
    recommendations: "推荐",
    noData: "没有数据",
    name: "名称",
    count: "数量",
    liveStatus: "\u5b9e\u65f6\u72b6\u6001",
    watcher: "Watcher",
    overlay: "Overlay",
    running: "\u8fd0\u884c\u4e2d",
    stopped: "\u5df2\u505c\u6b62",
    refresh: "\u5237\u65b0",
    startWatcher: "\u542f\u52a8 watcher",
    stopWatcher: "\u505c\u6b62 watcher",
    startOverlay: "\u542f\u52a8 overlay",
    stopOverlay: "\u505c\u6b62 overlay",
    databaseState: "\u6570\u636e\u5e93\u72b6\u6001",
    currentLiveRow: "\u5f53\u524d\u5b9e\u65f6\u64ad\u653e\u8bb0\u5f55",
    lastRuntimeError: "\u6700\u8fd1\u8fd0\u884c\u9519\u8bef",
    lastWatcherStats: "\u6700\u8fd1 watcher \u7edf\u8ba1",
    noWatcherStats: "\u5c1a\u65e0 watcher \u7edf\u8ba1",
    liveControlFailed: "\u5b9e\u65f6\u63a7\u5236\u5931\u8d25"
  }
};
const FIELD_TEXT = {
  config_version: { zh: { label: "配置版本", group: "系统", summary: "本地配置结构版本。" } },
  app_db: { zh: { label: "应用数据库", group: "应用内部路径", summary: "SQLite 运行状态。" } },
  queued_self_dir: { zh: { label: "自选队列目录", group: "应用内部路径", summary: "计划自选舞蹈的 Markdown 清单。" } },
  capture_dir: { zh: { label: "捕获目录", group: "应用内部路径", summary: "实时 watcher 捕获输出。" } },
  run_log_dir: { zh: { label: "运行日志目录", group: "应用内部路径", summary: "常规应用运行日志。" } },
  source_vrc_log_dir: { zh: { label: "VRChat 源日志归档", group: "应用内部路径", summary: "逐字节归档的源 output_log 文件。" } },
  recording_frames_dir: { zh: { label: "录像帧目录", group: "应用内部路径", summary: "用于分析的顶部裁剪帧样本。" } },
  self_user_id: { zh: { label: "本机 VRChat 用户 ID", group: "外部数据源", summary: "用于判断 VRCX 历史点歌人是否为自己。" } },
  vrcx_db_path: { zh: { label: "VRCX 数据库", group: "外部数据源", summary: "VRCX 播放历史 SQLite 文件。" } },
  vrc_log_dir: { zh: { label: "VRChat 日志目录", group: "外部数据源", summary: "包含 VRChat output_log 文件的目录。" } },
  wanna_cache_dir: { zh: { label: "WannaDance 缓存", group: "外部数据源", summary: "用于离线目录同步的本地 WannaDance 缓存。" } },
  recordings_dir: { zh: { label: "录像目录", group: "外部数据源", summary: "sample-frame 工具使用的录像文件。" } },
  auto_start_watcher: { zh: { label: "自动启动 watcher", group: "运行默认值", summary: "应用工作流启动实时捕获时使用的默认偏好。" } },
  auto_start_overlay: { zh: { label: "自动启动 overlay", group: "运行默认值", summary: "启用后会同步启用 watcher 自动启动。" } },
  overlay_port: { zh: { label: "Overlay 端口", group: "运行默认值", summary: "本地 OBS overlay 端口。" } }
};
const OPERATION_TEXT = {
  "import-vrcx": { zh: { title: "导入 VRCX 历史", risk: "写入播放历史" } },
  "sync-wanna": { zh: { title: "同步 WannaDance 目录", risk: "更新目录记录" } },
  "sync-queued-self": { zh: { title: "同步自选队列清单", risk: "更新清单派生记录" } },
  "rebuild-data": { zh: { title: "重建生成数据", risk: "归档并重建生成的数据库状态" } }
};
const state = {
  active: "settings",
  lang: initialLanguage(),
  configSnapshot: null,
  draft: {},
  fieldErrors: {},
  pathPreviews: {},
  previewTimers: {}
};

const brandSubtitleNode = document.getElementById("brand-subtitle");
const navNode = document.getElementById("nav");
const languageNode = document.getElementById("language-switch");
const toolbarNode = document.getElementById("view-toolbar");
const titleNode = document.getElementById("view-title");
const subtitleNode = document.getElementById("view-subtitle");
const sidebarPathNode = document.getElementById("sidebar-path");

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  }[char]));
}

function initialLanguage() {
  const saved = localStorage.getItem(LANGUAGE_KEY);
  if (saved === "en" || saved === "zh") return saved;
  return navigator.language && navigator.language.toLowerCase().startsWith("zh") ? "zh" : "en";
}

function ui(key) {
  return TEXT[state.lang]?.[key] ?? TEXT.en[key] ?? key;
}

function navLabel(key) {
  return ui(`nav_${key}`);
}

function viewTitle(key) {
  return [ui(`title_${key}`), ui(`subtitle_${key}`)];
}

function fieldText(field, part) {
  return FIELD_TEXT[field.key]?.[state.lang]?.[part] || field[part] || "";
}

function operationText(operation, part) {
  return OPERATION_TEXT[operation.key]?.[state.lang]?.[part] || operation[part] || "";
}

function pickerKind(kind) {
  if (state.lang !== "zh") return kind;
  return kind === "directory" ? "文件夹" : "文件";
}

function pathStatusLabel(resolved) {
  if (resolved.error) return ui("inaccessible");
  return resolved.exists ? ui("exists") : ui("missing");
}

function reviewStatusLabel(value) {
  const key = `status_${String(value || "").replaceAll(" ", "_")}`;
  return ui(key);
}

function translatedError(message) {
  if (state.lang !== "zh") return message;
  if (message === "path is required") return "路径不能为空";
  if (message === "value must be true or false") return "值必须为 true 或 false";
  if (message === "value must be an integer") return "值必须是整数";
  const range = String(message || "").match(/^value must be between (\d+) and (\d+)$/);
  if (range) return `值必须在 ${range[1]} 到 ${range[2]} 之间`;
  return message;
}

function api(path, options = {}) {
  const init = { ...options };
  init.headers = { ...(options.headers || {}) };
  if (init.body && typeof init.body !== "string") {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(init.body);
  }
  if ((init.method || "GET").toUpperCase() !== "GET") {
    init.headers["X-Dancing-Log-CSRF"] = CSRF_TOKEN;
  }
  return fetch(path, init).then(async response => {
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(data.error || "request failed");
      error.data = data;
      throw error;
    }
    return data;
  });
}

function setView(next) {
  state.active = next;
  for (const key of NAV) {
    document.getElementById(`view-${key}`).classList.toggle("active", key === next);
  }
  for (const button of navNode.querySelectorAll("button")) {
    button.classList.toggle("active", button.dataset.view === next);
  }
  const [title, subtitle] = viewTitle(next);
  titleNode.textContent = title;
  subtitleNode.textContent = subtitle;
  toolbarNode.innerHTML = "";
  renderActive();
}

function renderNav() {
  navNode.innerHTML = NAV.map(key => `
    <button type="button" data-view="${key}" class="${key === state.active ? "active" : ""}">${esc(navLabel(key))}</button>
  `).join("");
  for (const button of navNode.querySelectorAll("button[data-view]")) {
    button.onclick = () => setView(button.dataset.view);
  }
}

function renderLanguageSwitch() {
  document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
  brandSubtitleNode.textContent = ui("brandSubtitle");
  languageNode.setAttribute("aria-label", ui("languageLabel"));
  languageNode.innerHTML = `
    <button type="button" data-lang="en" class="${state.lang === "en" ? "active" : ""}" aria-pressed="${state.lang === "en"}">EN</button>
    <button type="button" data-lang="zh" class="${state.lang === "zh" ? "active" : ""}" aria-pressed="${state.lang === "zh"}">中文</button>
  `;
  for (const button of languageNode.querySelectorAll("button[data-lang]")) {
    button.onclick = () => setLanguage(button.dataset.lang);
  }
}

function setLanguage(lang) {
  if (lang !== "en" && lang !== "zh") return;
  state.lang = lang;
  localStorage.setItem(LANGUAGE_KEY, lang);
  renderLanguageSwitch();
  renderNav();
  const [title, subtitle] = viewTitle(state.active);
  titleNode.textContent = title;
  subtitleNode.textContent = subtitle;
  renderActive();
}

function showMessage(id, message, kind = "") {
  const node = document.getElementById(id);
  if (!node) return;
  node.textContent = message || "";
  node.className = `message ${message ? "show" : ""} ${kind}`;
}

function renderActive() {
  if (state.active === "settings") return renderSettings();
  if (state.active === "home") return renderHome();
  if (state.active === "timeline") return renderTimeline();
  if (state.active === "catalog") return renderCatalog();
  if (state.active === "lists") return renderLists();
  if (state.active === "insights") return renderInsights();
  if (state.active === "operations") return renderOperations();
}

async function loadConfig() {
  const snapshot = await api("/api/config");
  state.configSnapshot = snapshot;
  state.draft = { ...snapshot.config };
  state.fieldErrors = {};
  updatePathPreviewsFromSnapshot(snapshot);
  sidebarPathNode.textContent = snapshot.config_path;
}

function updatePathPreviewsFromSnapshot(snapshot) {
  state.pathPreviews = {};
  for (const field of snapshot.fields || []) {
    if (field.path) state.pathPreviews[field.key] = field.path;
  }
}

function groupedFields(fields) {
  const groups = [];
  for (const field of fields) {
    const groupName = fieldText(field, "group");
    let group = groups.find(item => item.name === groupName);
    if (!group) {
      group = { name: groupName, fields: [] };
      groups.push(group);
    }
    group.fields.push(field);
  }
  return groups;
}

function renderSettings() {
  toolbarNode.innerHTML = `
    <button class="button" type="button" id="settings-reset" title="${esc(ui("resetTitle"))}">${esc(ui("reset"))}</button>
    <button class="button primary" type="button" id="settings-save" title="${esc(ui("saveTitle"))}">${esc(ui("save"))}</button>
  `;
  const node = document.getElementById("view-settings");
  if (!state.configSnapshot) {
    node.innerHTML = `<div class="panel"><div class="empty">${esc(ui("loadingConfig"))}</div></div>`;
    loadConfig().then(renderSettings).catch(error => {
      node.innerHTML = `<div class="message show error">${esc(error.message)}</div>`;
    });
    return;
  }
  const snapshot = state.configSnapshot;
  const groups = groupedFields(snapshot.fields);
  node.innerHTML = `
    <div class="message" id="settings-message"></div>
    <div class="settings-grid">
      ${groups.map(group => renderSettingsGroup(group)).join("")}
      ${renderDetectedSources(snapshot.detected_sources || [])}
      ${renderUnsupported(snapshot.unsupported || {})}
    </div>
  `;
  document.getElementById("settings-save").onclick = saveSettings;
  document.getElementById("settings-reset").onclick = () => {
    state.configSnapshot = null;
    renderSettings();
  };
  bindFieldControls();
}

function renderSettingsGroup(group) {
  return `
    <section class="panel">
      <div class="panel-head"><h2>${esc(group.name)}</h2></div>
      <div class="panel-body">
        ${group.fields.map(renderField).join("")}
      </div>
    </section>
  `;
}

function renderField(field) {
  const key = field.key;
  const value = state.draft[key];
  const error = state.fieldErrors[key];
  return `
    <div class="field-row" data-field="${esc(key)}">
      <div class="field-label">
        <strong>${esc(fieldText(field, "label"))}</strong>
        <code>${esc(key)}</code>
        <span class="field-summary">${esc(fieldText(field, "summary"))}</span>
      </div>
      <div class="field-control">
        ${renderFieldControl(field, value)}
        ${field.path ? renderPathPreview(field) : ""}
        ${error ? `<span class="resolved missing">${esc(translatedError(error))}</span>` : ""}
      </div>
    </div>
  `;
}

function renderFieldControl(field, value) {
  if (field.type === "readonly") {
    return `<input type="text" readonly value="${esc(value)}">`;
  }
  if (field.type === "boolean") {
    return `
      <label class="toggle-line">
        <input type="checkbox" data-key="${esc(field.key)}" ${value ? "checked" : ""}>
        <span>${value ? esc(ui("enabled")) : esc(ui("disabled"))}</span>
      </label>
    `;
  }
  if (field.type === "integer") {
    return `
      <input type="number" data-key="${esc(field.key)}" min="${esc(field.min)}" max="${esc(field.max)}" value="${esc(value)}">
    `;
  }
  if (field.type === "path") {
    return `
      <div class="input-line">
        <input type="text" data-key="${esc(field.key)}" placeholder="${field.required ? "" : "null"}" value="${esc(value ?? "")}">
        <button class="button" type="button" data-pick="${esc(field.key)}" title="${esc(ui("browseTitle").replace("{kind}", pickerKind(field.picker)))}">${esc(ui("browse"))}</button>
      </div>
    `;
  }
  return `<input type="text" data-key="${esc(field.key)}" placeholder="${esc(field.placeholder || "")}" value="${esc(value ?? "")}">`;
}

function renderPathPreview(field) {
  const rawValue = state.draft[field.key];
  const preview = state.pathPreviews[field.key] || field.path || {};
  if ((rawValue === null || rawValue === "") && !field.required) {
    return `<span id="${pathPreviewId(field.key)}" class="resolved">${esc(ui("savedNull"))}</span>`;
  }
  if (!preview.resolved) {
    return `<span id="${pathPreviewId(field.key)}" class="resolved">${esc(ui("savedNull"))}</span>`;
  }
  const cls = preview.exists ? "ok" : "missing";
  const suffix = pathStatusLabel(preview);
  return `<span id="${pathPreviewId(field.key)}" class="resolved ${cls}">${esc(preview.resolved)} (${esc(suffix)})</span>`;
}

function pathPreviewId(key) {
  return `path-preview-${String(key).replace(/[^a-zA-Z0-9_-]/g, "_")}`;
}

function updatePathPreviewNode(key) {
  const node = document.getElementById(pathPreviewId(key));
  const field = state.configSnapshot?.fields?.find(item => item.key === key);
  if (!node || !field) return;
  node.outerHTML = renderPathPreview(field);
}

function schedulePathPreview(key, value) {
  const field = state.configSnapshot?.fields?.find(item => item.key === key);
  if (!field || field.type !== "path") return;
  clearTimeout(state.previewTimers[key]);
  if ((value === null || value === "") && !field.required) {
    state.pathPreviews[key] = { resolved: null, exists: null };
    updatePathPreviewNode(key);
    return;
  }
  const requestedValue = value;
  state.previewTimers[key] = setTimeout(async () => {
    try {
      const result = await api("/api/resolve-path", {
        method: "POST",
        body: { field: key, current_value: requestedValue }
      });
      if (state.draft[key] !== requestedValue) return;
      state.pathPreviews[key] = result.path || {};
      updatePathPreviewNode(key);
    } catch (error) {
      if (state.draft[key] !== requestedValue) return;
      state.pathPreviews[key] = {
        resolved: String(requestedValue ?? ""),
        exists: false,
        kind: "inaccessible",
        error: error.message
      };
      updatePathPreviewNode(key);
    }
  }, 250);
}

function renderDetectedSources(candidates) {
  if (!candidates.length) return "";
  return `
    <section class="panel">
      <div class="panel-head"><h2>${esc(ui("detectedSources"))}</h2></div>
      <div class="panel-body">
        <div class="pill-row">
          ${candidates.map(candidate => `
            <button class="button" type="button" data-use-detected="${esc(candidate.field)}" data-value="${esc(candidate.value)}" title="${esc(candidate.value)}">
              ${esc(candidate.field === "vrc_log_dir" ? ui("defaultVrcLogDir") : candidate.label)} ${candidate.exists ? "" : `(${esc(candidate.error ? ui("inaccessible") : ui("missing"))})`}
            </button>
          `).join("")}
        </div>
      </div>
    </section>
  `;
}

function renderUnsupported(unsupported) {
  const keys = Object.keys(unsupported);
  if (!keys.length) return "";
  return `
    <section class="panel">
      <div class="panel-head"><h2>${esc(ui("unsupportedKeys"))}</h2><span class="pill orange">${esc(ui("preserved"))}</span></div>
      <div class="panel-body">
        <pre class="readonly-json">${esc(JSON.stringify(unsupported, null, 2))}</pre>
      </div>
    </section>
  `;
}

function bindFieldControls() {
  for (const control of document.querySelectorAll("[data-key]")) {
    control.oninput = () => updateDraftFromControl(control, false);
    control.onchange = () => updateDraftFromControl(control, control.type === "checkbox");
  }
  for (const button of document.querySelectorAll("[data-pick]")) {
    button.onclick = () => pickPath(button.dataset.pick);
  }
  for (const button of document.querySelectorAll("[data-use-detected]")) {
    button.onclick = () => {
      state.draft[button.dataset.useDetected] = button.dataset.value;
      schedulePathPreview(button.dataset.useDetected, button.dataset.value);
      renderSettings();
    };
  }
}

function updateDraftFromControl(control, redraw) {
  const key = control.dataset.key;
  const field = state.configSnapshot.fields.find(item => item.key === key);
  if (control.type === "checkbox") {
    state.draft[key] = control.checked;
    if (key === "auto_start_overlay" && control.checked) state.draft.auto_start_watcher = true;
  } else if (control.type === "number") {
    state.draft[key] = Number(control.value);
  } else {
    const text = control.value;
    state.draft[key] = field && !field.required && text.trim() === "" ? null : text;
  }
  if (field?.type === "path") schedulePathPreview(key, state.draft[key]);
  if (redraw) renderSettings();
}

async function pickPath(key) {
  showMessage("settings-message", "");
  try {
    const result = await api("/api/pick-path", {
      method: "POST",
      body: { field: key, current_value: state.draft[key] }
    });
    if (result.cancelled) return;
    state.draft[key] = result.value;
    schedulePathPreview(key, result.value);
    renderSettings();
  } catch (error) {
    showMessage("settings-message", error.message, "error");
  }
}

async function saveSettings() {
  showMessage("settings-message", "");
  state.fieldErrors = {};
  try {
    const result = await api("/api/config", {
      method: "POST",
      body: { config: state.draft }
    });
    state.configSnapshot = result.snapshot;
    state.draft = { ...result.snapshot.config };
    updatePathPreviewsFromSnapshot(result.snapshot);
    renderSettings();
    showMessage("settings-message", ui("saved"), "success");
  } catch (error) {
    if (error.data && error.data.errors) state.fieldErrors = error.data.errors;
    if (error.data && error.data.snapshot) state.configSnapshot = error.data.snapshot;
    renderSettings();
    showMessage("settings-message", ui("saveFailed"), "error");
  }
}

async function renderHome() {
  const node = document.getElementById("view-home");
  node.innerHTML = `<div class="panel"><div class="empty">${esc(ui("loading"))}</div></div>`;
  const data = await api("/api/summary").catch(error => ({ error: error.message, counts: {}, recent: [] }));
  if (state.active !== "home") return;
  toolbarNode.innerHTML = renderHomeToolbar(data.session || {});
  node.innerHTML = `
    <div class="message" id="home-message"></div>
    <div class="grid summary-grid">
      ${metric(ui("danceTracks"), data.counts?.dance_tracks ?? 0, "blue")}
      ${metric(ui("officialRecords"), data.counts?.dance_events ?? 0, "green")}
      ${metric(ui("liveRows"), data.counts?.live_playback_events ?? 0, "violet")}
      ${metric(ui("vrcxRows"), data.counts?.vrcx_import_events ?? 0, "orange")}
    </div>
    <div class="grid two-col">
      ${renderLiveStatus(data.session || {})}
      <section class="panel">
        <div class="panel-head"><h2>${esc(ui("currentLiveRow"))}</h2></div>
        <div class="panel-body">
          ${data.current_live ? `<pre class="readonly-json">${esc(JSON.stringify(data.current_live, null, 2))}</pre>` : `<div class="empty">${esc(ui("noLiveRow"))}</div>`}
        </div>
      </section>
    </div>
    <div class="grid two-col">
      <section class="panel">
        <div class="panel-head"><h2>${esc(ui("databaseState"))}</h2>${data.database_exists ? `<span class="pill green">${esc(ui("dbFound"))}</span>` : `<span class="pill orange">${esc(ui("noDb"))}</span>`}</div>
        <div class="panel-body">
          <div class="resolved">${esc(data.database_path || "")}</div>
        </div>
      </section>
      <section class="panel">
        <div class="panel-head"><h2>${esc(ui("recentOfficial"))}</h2></div>
        <div class="panel-body">${renderRecent(data.recent || [])}</div>
      </section>
    </div>
  `;
  bindHomeControls();
}

function renderHomeToolbar(session) {
  const watcherRunning = Boolean(session.watcher_running);
  const overlayRunning = Boolean(session.overlay_running);
  return `
    <button class="button" type="button" id="home-refresh">${esc(ui("refresh"))}</button>
    <button class="button ${watcherRunning ? "danger" : "primary"}" type="button" data-live-control="watcher" data-live-action="${watcherRunning ? "stop" : "start"}">
      ${esc(ui(watcherRunning ? "stopWatcher" : "startWatcher"))}
    </button>
    <button class="button ${overlayRunning ? "danger" : "primary"}" type="button" data-live-control="overlay" data-live-action="${overlayRunning ? "stop" : "start"}">
      ${esc(ui(overlayRunning ? "stopOverlay" : "startOverlay"))}
    </button>
  `;
}

function bindHomeControls() {
  const refresh = document.getElementById("home-refresh");
  if (refresh) refresh.onclick = renderHome;
  for (const button of document.querySelectorAll("[data-live-control]")) {
    button.onclick = () => controlLive(button.dataset.liveControl, button.dataset.liveAction);
  }
}

async function controlLive(kind, action) {
  const controls = [...document.querySelectorAll("[data-live-control], #home-refresh")];
  for (const control of controls) control.disabled = true;
  showMessage("home-message", "");
  try {
    await api(`/api/live/${kind}`, {
      method: "POST",
      body: { action }
    });
    await renderHome();
  } catch (error) {
    showMessage("home-message", `${ui("liveControlFailed")}: ${error.message}`, "error");
  } finally {
    for (const control of controls) control.disabled = false;
  }
}

function renderLiveStatus(session) {
  const stats = session.last_watcher_stats;
  return `
    <section class="panel">
      <div class="panel-head"><h2>${esc(ui("liveStatus"))}</h2></div>
      <div class="panel-body">
        <div class="status-grid">
          ${statusItem(ui("watcher"), Boolean(session.watcher_running))}
          ${statusItem(ui("overlay"), Boolean(session.overlay_running))}
        </div>
        ${session.last_error ? `<div class="message show error"><strong>${esc(ui("lastRuntimeError"))}</strong><br>${esc(session.last_error)}</div>` : ""}
        ${stats ? `<div><div class="resolved">${esc(ui("lastWatcherStats"))}</div><pre class="readonly-json">${esc(JSON.stringify(stats, null, 2))}</pre></div>` : `<div class="empty">${esc(ui("noWatcherStats"))}</div>`}
      </div>
    </section>
  `;
}

function statusItem(label, running) {
  return `
    <div class="status-item">
      <span>${esc(label)}</span>
      <strong><span class="pill ${running ? "green" : "orange"}">${esc(ui(running ? "running" : "stopped"))}</span></strong>
    </div>
  `;
}

function metric(label, value, color) {
  return `<section class="panel metric"><span>${esc(label)}</span><strong>${esc(value)}</strong><div class="pill-row"><span class="pill ${color}">${esc(ui("local"))}</span></div></section>`;
}

function renderRecent(rows) {
  if (!rows.length) return `<div class="empty">${esc(ui("noRecords"))}</div>`;
  return `<table><thead><tr><th>${esc(ui("time"))}</th><th>${esc(ui("track"))}</th><th>${esc(ui("source"))}</th></tr></thead><tbody>
    ${rows.map(row => `<tr><td>${esc(row.played_at)}</td><td>${esc(row.video_name || row.title || row.external_id || "")}</td><td>${esc(row.source || "")}</td></tr>`).join("")}
  </tbody></table>`;
}

async function renderTimeline() {
  toolbarNode.innerHTML = `
    <input type="date" id="timeline-date" value="${new Date().toISOString().slice(0, 10)}">
    <select id="timeline-source"><option value="official">${esc(ui("official"))}</option><option value="live">${esc(ui("live"))}</option></select>
    <button class="button" type="button" id="timeline-load">${esc(ui("load"))}</button>
  `;
  const node = document.getElementById("view-timeline");
  async function load() {
    const selectedDate = document.getElementById("timeline-date").value;
    const source = document.getElementById("timeline-source").value;
    const data = await api(`/api/timeline?date=${encodeURIComponent(selectedDate)}&source=${encodeURIComponent(source)}`);
    node.innerHTML = `<section class="panel"><div class="panel-body">${renderTimelineRows(data.records || [])}</div></section>`;
  }
  document.getElementById("timeline-load").onclick = load;
  await load();
}

function renderTimelineRows(rows) {
  if (!rows.length) return `<div class="empty">${esc(ui("noTimelineRecords"))}</div>`;
  return `<table><thead><tr><th style="width:110px">${esc(ui("time"))}</th><th>${esc(ui("record"))}</th><th style="width:150px">${esc(ui("reviewStatus"))}</th></tr></thead><tbody>
    ${rows.map(row => `<tr><td>${esc(row.time)}</td><td>${esc(row.display)}</td><td><span class="pill ${row.review_status === "unchecked" ? "orange" : "green"}">${esc(reviewStatusLabel(row.review_status))}</span></td></tr>`).join("")}
  </tbody></table>`;
}

async function renderCatalog() {
  toolbarNode.innerHTML = `
    <input type="text" id="catalog-search" placeholder="${esc(ui("searchCatalog"))}">
    <button class="button" type="button" id="catalog-load">${esc(ui("search"))}</button>
  `;
  const node = document.getElementById("view-catalog");
  async function load() {
    const q = document.getElementById("catalog-search").value;
    const data = await api(`/api/catalog?q=${encodeURIComponent(q)}&limit=100`);
    node.innerHTML = `<section class="panel"><div class="panel-body">${renderCatalogRows(data.tracks || [])}</div></section>`;
  }
  document.getElementById("catalog-load").onclick = load;
  await load();
}

function renderCatalogRows(rows) {
  if (!rows.length) return `<div class="empty">${esc(ui("noTracks"))}</div>`;
  return `<table><thead><tr><th style="width:130px">${esc(ui("track"))}</th><th>${esc(ui("title"))}</th><th>${esc(ui("artist"))}</th><th style="width:150px">${esc(ui("preferences"))}</th></tr></thead><tbody>
    ${rows.map(row => `<tr>
      <td>${esc(row.system_key)}:${esc(row.external_id)}</td>
      <td>${esc(row.title || "")}</td>
      <td>${esc(row.artist || "")}</td>
      <td><div class="pill-row">${row.favorite ? `<span class="pill green">${esc(ui("favorite"))}</span>` : ''}${row.want_to_learn ? `<span class="pill violet">${esc(ui("wantToLearn"))}</span>` : ''}</div></td>
    </tr>`).join("")}
  </tbody></table>`;
}

async function renderLists() {
  const node = document.getElementById("view-lists");
  const data = await api("/api/lists");
  node.innerHTML = `
    <section class="panel">
      <div class="panel-head"><h2>${esc(ui("queuedSelfManifests"))}</h2>${data.exists ? `<span class="pill green">${esc(ui("found"))}</span>` : `<span class="pill orange">${esc(ui("missing"))}</span>`}</div>
      <div class="panel-body">
        <div class="resolved">${esc(data.queued_self_dir)}</div>
        ${renderManifests(data.manifests || [])}
      </div>
    </section>
  `;
}

function renderManifests(rows) {
  if (!rows.length) return `<div class="empty">${esc(ui("noManifests"))}</div>`;
  return `<div class="list-stack">${rows.map(row => `
    <div class="list-item">
      <strong>${esc(row.name)}</strong>
      <code>${esc(row.path)}</code>
      ${(row.preview || []).map(line => `<span>${esc(line)}</span>`).join("")}
    </div>
  `).join("")}</div>`;
}

async function renderInsights() {
  const node = document.getElementById("view-insights");
  const data = await api("/api/insights");
  node.innerHTML = `
    <div class="grid two-col">
      <section class="panel"><div class="panel-head"><h2>${esc(ui("sourceDistribution"))}</h2></div><div class="panel-body">${renderKeyCount(data.source_distribution || [], "source")}</div></section>
      <section class="panel"><div class="panel-head"><h2>${esc(ui("topTracks"))}</h2></div><div class="panel-body">${renderKeyCount(data.top_tracks || [], "title")}</div></section>
    </div>
    <section class="panel"><div class="panel-head"><h2>${esc(ui("recommendations"))}</h2></div><div class="panel-body">${renderCatalogRows(data.recommendations || [])}</div></section>
  `;
}

function renderKeyCount(rows, key) {
  if (!rows.length) return `<div class="empty">${esc(ui("noData"))}</div>`;
  return `<table><thead><tr><th>${esc(ui("name"))}</th><th style="width:90px">${esc(ui("count"))}</th></tr></thead><tbody>
    ${rows.map(row => `<tr><td>${esc(row[key] || row.external_id || "(none)")}</td><td>${esc(row.count || 0)}</td></tr>`).join("")}
  </tbody></table>`;
}

async function renderOperations() {
  const node = document.getElementById("view-operations");
  const data = await api("/api/operations");
  node.innerHTML = `<div class="list-stack">${(data.operations || []).map(operation => `
    <section class="panel">
      <div class="panel-head"><h2>${esc(operationText(operation, "title"))}</h2><span class="pill orange">${esc(operationText(operation, "risk"))}</span></div>
      <div class="panel-body"><code>${esc(operation.command)}</code></div>
    </section>
  `).join("")}</div>`;
}

renderLanguageSwitch();
renderNav();
setView("settings");
</script>
</body>
</html>
"""
