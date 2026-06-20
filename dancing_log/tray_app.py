"""Desktop tray launcher for the local Web UI."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import sys
import threading

from dancing_log.app_paths import DEFAULT_CONFIG, load_app_config, resolve_app_path
from dancing_log.vrc_log_watcher import default_vrc_log_dir
from dancing_log.webui_server import DEFAULT_WEBUI_PORT, WebUiServer


IDM_OPEN_WEBUI = 1001
IDM_TOGGLE_WATCHER = 1002
IDM_TOGGLE_OVERLAY = 1003
IDM_EXIT = 1004

WatchVrcLogsFunc = Callable[..., object]


@dataclass(frozen=True)
class TrayMenuItem:
    command_id: int | None
    label: str = ""


def _is_separator(item: TrayMenuItem) -> bool:
    return item.command_id is None


class TrayRuntime:
    """Runtime controls owned by the desktop tray session."""

    def __init__(
        self,
        *,
        app_root: Path | str | None = None,
        watch_vrc_logs_func: WatchVrcLogsFunc | None = None,
    ) -> None:
        self.app_root = Path(app_root).resolve() if app_root is not None else None
        self._watch_vrc_logs_func = watch_vrc_logs_func
        self._lock = threading.RLock()
        self._watcher_thread: threading.Thread | None = None
        self._watcher_stop_event: threading.Event | None = None
        self._watcher_overlay = False
        self.last_error: str | None = None
        self.last_watcher_stats: object | None = None

    @property
    def watcher_running(self) -> bool:
        with self._lock:
            return self._watcher_thread is not None and self._watcher_thread.is_alive()

    @property
    def overlay_running(self) -> bool:
        with self._lock:
            return self.watcher_running and self._watcher_overlay

    def menu_items(self) -> list[TrayMenuItem]:
        watcher_label = "Stop watcher" if self.watcher_running else "Start watcher"
        overlay_label = "Stop overlay" if self.overlay_running else "Start overlay"
        return [
            TrayMenuItem(IDM_OPEN_WEBUI, "Open Web UI"),
            TrayMenuItem(None),
            TrayMenuItem(IDM_TOGGLE_WATCHER, watcher_label),
            TrayMenuItem(IDM_TOGGLE_OVERLAY, overlay_label),
            TrayMenuItem(None),
            TrayMenuItem(IDM_EXIT, "Exit"),
        ]

    def toggle_watcher(self) -> None:
        if self.watcher_running:
            self.stop_watcher()
        else:
            self.start_watcher(overlay=False)

    def toggle_overlay(self) -> None:
        if self.overlay_running:
            self.stop_overlay()
        else:
            self.start_overlay()

    def start_watcher(self, *, overlay: bool) -> None:
        if self.watcher_running:
            if overlay and not self.overlay_running:
                self.stop_watcher()
            else:
                return

        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._watcher_thread_main,
            args=(stop_event, overlay),
            name="DancingLogTrayWatcher",
            daemon=True,
        )
        with self._lock:
            self._watcher_stop_event = stop_event
            self._watcher_overlay = overlay
            self._watcher_thread = thread
            self.last_error = None
        thread.start()

    def start_overlay(self) -> None:
        self.start_watcher(overlay=True)

    def stop_watcher(self) -> None:
        with self._lock:
            stop_event = self._watcher_stop_event
            thread = self._watcher_thread
        if stop_event is not None:
            stop_event.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3.0)

    def stop_overlay(self) -> None:
        if not self.overlay_running:
            return
        self.stop_watcher()
        self.start_watcher(overlay=False)

    def close(self) -> None:
        self.stop_watcher()

    def _watcher_thread_main(self, stop_event: threading.Event, overlay: bool) -> None:
        try:
            watch_vrc_logs = self._watch_vrc_logs_func
            if watch_vrc_logs is None:
                from dancing_log.vrc_log_watcher import watch_vrc_logs
            stats = watch_vrc_logs(**self._watcher_kwargs(stop_event, overlay))
            with self._lock:
                self.last_watcher_stats = stats
        except Exception as exc:  # pragma: no cover - visible through the tray tooltip later.
            with self._lock:
                self.last_error = str(exc)
        finally:
            with self._lock:
                if self._watcher_thread is threading.current_thread():
                    self._watcher_thread = None
                    self._watcher_stop_event = None
                    self._watcher_overlay = False

    def _watcher_kwargs(self, stop_event: threading.Event, overlay: bool) -> dict:
        config = load_app_config(app_root=self.app_root)
        app_root = self.app_root
        configured_log_dir = config.get("vrc_log_dir")
        log_dir = (
            resolve_app_path(configured_log_dir, configured_log_dir, app_root=app_root)
            if configured_log_dir
            else default_vrc_log_dir()
        )
        overlay_port = int(config.get("overlay_port") or DEFAULT_CONFIG["overlay_port"])
        return {
            "log_dir": log_dir,
            "output_dir": resolve_app_path(
                config.get("capture_dir"),
                DEFAULT_CONFIG["capture_dir"],
                app_root=app_root,
            ),
            "app_db_path": resolve_app_path(
                config.get("app_db"),
                DEFAULT_CONFIG["app_db"],
                app_root=app_root,
            ),
            "live_db": True,
            "overlay_port": overlay_port if overlay else None,
            "source_log_dir": resolve_app_path(
                config.get("source_vrc_log_dir"),
                DEFAULT_CONFIG["source_vrc_log_dir"],
                app_root=app_root,
            ),
            "stop_event": stop_event,
        }


def run_tray_webui_app(
    *,
    port: int = DEFAULT_WEBUI_PORT,
    open_browser: bool = True,
    app_root: Path | str | None = None,
) -> None:
    """Start the Web UI and expose its lifetime through a Windows tray icon."""
    if sys.platform != "win32":
        from dancing_log.webui_server import run_webui_server

        run_webui_server(port=port, open_browser=open_browser, app_root=app_root)
        return

    from dancing_log._win_tray import WindowsTrayApp

    server = WebUiServer(port=port, app_root=app_root)
    runtime = TrayRuntime(app_root=app_root)
    server.start()
    try:
        WindowsTrayApp(server, runtime).run(open_browser=open_browser)
    finally:
        runtime.close()
        server.stop()
