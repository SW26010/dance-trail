"""Desktop tray launcher for the local Web UI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

from dancing_log.live_app_session import LiveAppSessionRuntime, WatchVrcLogsFunc
from dancing_log.webui_server import DEFAULT_WEBUI_PORT, WebUiServer


IDM_OPEN_WEBUI = 1001
IDM_TOGGLE_WATCHER = 1002
IDM_TOGGLE_OVERLAY = 1003
IDM_EXIT = 1004


@dataclass(frozen=True)
class TrayMenuItem:
    command_id: int | None
    label: str = ""


def _is_separator(item: TrayMenuItem) -> bool:
    return item.command_id is None


class TrayRuntime:
    """Desktop tray adapter for live app session controls."""

    def __init__(
        self,
        *,
        app_root: Path | str | None = None,
        watch_vrc_logs_func: WatchVrcLogsFunc | None = None,
    ) -> None:
        self.app_root = Path(app_root).resolve() if app_root is not None else None
        self.session = LiveAppSessionRuntime(
            app_root=self.app_root,
            watch_vrc_logs_func=watch_vrc_logs_func,
        )

    @property
    def watcher_running(self) -> bool:
        return self.session.watcher_running

    @property
    def overlay_running(self) -> bool:
        return self.session.overlay_running

    @property
    def last_error(self) -> str | None:
        return self.session.last_error

    @property
    def last_watcher_stats(self) -> object | None:
        return self.session.last_watcher_stats

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
            self.start_watcher()

    def toggle_overlay(self) -> None:
        if self.overlay_running:
            self.stop_overlay()
        else:
            self.start_overlay()

    def start_watcher(self, *, overlay: bool = False) -> None:
        self.session.start_watcher(overlay=overlay)

    def start_overlay(self) -> None:
        self.session.start_overlay()

    def stop_watcher(self) -> None:
        self.session.stop_watcher()

    def stop_overlay(self) -> None:
        self.session.stop_overlay()

    def close(self) -> None:
        self.session.close()


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

    runtime = TrayRuntime(app_root=app_root)
    server = WebUiServer(port=port, app_root=app_root, session_runtime=runtime.session)
    server.start()
    try:
        WindowsTrayApp(server, runtime).run(open_browser=open_browser)
    finally:
        runtime.close()
        server.stop()
