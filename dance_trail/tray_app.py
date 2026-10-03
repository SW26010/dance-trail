"""Desktop tray launcher for the local Web UI."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import sys
import threading
import time

from dance_trail.desktop_instance import (
    EXISTING_WEBUI_POLL_SECONDS,
    EXISTING_WEBUI_PROBE_TIMEOUT_SECONDS,
    EXISTING_WEBUI_WAIT_SECONDS,
    ExistingWebUiActivation,
)
from dance_trail.live_app_session import LiveAppSessionRuntime, WatchVrcLogsFunc
from dance_trail.webui_assets import WEBUI_ROUTE_BY_VIEW
from dance_trail.webui_server import DEFAULT_WEBUI_PORT, WEBUI_HOST, WebUiServer


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

    def close(self, *, deadline: float | None = None) -> None:
        if deadline is None:
            self.session.close()
        else:
            self.session.close(deadline=deadline)


class TrayShutdownCoordinator:
    """Own and idempotently close one desktop app's acquired resources."""

    def __init__(self, instance) -> None:
        self._instance = instance
        self._runtime: TrayRuntime | None = None
        self._server: WebUiServer | None = None
        self._close_lock = threading.RLock()
        self._closed = False
        self._cleanup_errors: tuple[BaseException, ...] = ()

    def own_runtime(self, runtime: TrayRuntime) -> None:
        with self._close_lock:
            self._ensure_open()
            if self._runtime is not None:
                raise RuntimeError("shutdown coordinator already owns a tray runtime")
            self._runtime = runtime

    def own_server(self, server: WebUiServer) -> None:
        with self._close_lock:
            self._ensure_open()
            if self._server is not None:
                raise RuntimeError("shutdown coordinator already owns a Web UI server")
            self._server = server

    def close(
        self,
        *,
        primary: BaseException | None = None,
        deadline: float | None = None,
    ) -> None:
        """Close each acquired resource once and replay the complete result."""
        with self._close_lock:
            if not self._closed:
                self._closed = True
                cleanup_errors: list[BaseException] = []
                actions: list[tuple[Callable[..., object], bool]] = []
                if self._server is not None:
                    actions.append((self._server.stop, True))
                if self._runtime is not None:
                    actions.append((self._runtime.close, True))
                actions.append((self._instance.close, False))
                for action, accepts_deadline in actions:
                    try:
                        if deadline is not None and accepts_deadline:
                            action(deadline=deadline)
                        else:
                            action()
                    except BaseException as exc:
                        cleanup_errors.append(exc)
                self._cleanup_errors = tuple(cleanup_errors)
            recorded_errors = self._cleanup_errors

        if primary is not None and recorded_errors:
            raise BaseExceptionGroup(
                f"tray app failed with {primary}; cleanup also failed",
                [primary, *recorded_errors],
            ) from None
        if len(recorded_errors) == 1:
            raise recorded_errors[0]
        if recorded_errors:
            raise BaseExceptionGroup("tray app shutdown failed", list(recorded_errors))

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("shutdown coordinator is already closed")


def run_tray_webui_app(
    *,
    port: int = DEFAULT_WEBUI_PORT,
    open_browser: bool = True,
    app_root: Path | str | None = None,
) -> None:
    """Start the Web UI and expose its lifetime through a Windows tray icon."""
    if sys.platform != "win32":
        from dance_trail.webui_server import run_webui_server

        run_webui_server(port=port, open_browser=open_browser, app_root=app_root)
        return
    if port != DEFAULT_WEBUI_PORT:
        raise ValueError(
            "Windows Desktop Tray Entry requires the canonical port "
            f"{DEFAULT_WEBUI_PORT}; use the standalone webui command for a "
            "custom port."
        )

    instance = _acquire_or_activate_windows_desktop_instance(
        open_browser=open_browser
    )
    if instance is None:
        return
    shutdown = TrayShutdownCoordinator(instance)
    try:
        from dance_trail._win_tray import WindowsTrayApp

        runtime = TrayRuntime(app_root=app_root)
        shutdown.own_runtime(runtime)
        server = WebUiServer(port=port, app_root=app_root, session_runtime=runtime.session)
        shutdown.own_server(server)
        server.start()
        WindowsTrayApp(server, runtime, shutdown=shutdown.close).run(
            open_browser=open_browser
        )
    except BaseException as primary:
        shutdown.close(primary=primary)
        raise
    else:
        shutdown.close()


def _acquire_windows_desktop_instance():
    from dance_trail.desktop_instance import WindowsDesktopInstanceLease

    return WindowsDesktopInstanceLease.acquire()


def _acquire_or_activate_windows_desktop_instance(*, open_browser: bool):
    """Elect one owner or activate the owner that becomes ready before timeout."""
    home_url = _desktop_home_url()
    deadline = time.monotonic() + EXISTING_WEBUI_WAIT_SECONDS
    while True:
        instance = _acquire_windows_desktop_instance()
        if instance is not None:
            return instance

        remaining = max(deadline - time.monotonic(), 0.0)
        activation = _try_activate_existing_webui(
            home_url,
            open_browser=open_browser,
            timeout=max(
                min(remaining, EXISTING_WEBUI_PROBE_TIMEOUT_SECONDS),
                EXISTING_WEBUI_POLL_SECONDS,
            ),
        )
        if activation is ExistingWebUiActivation.READY:
            return None
        if activation is ExistingWebUiActivation.FAILED:
            _show_existing_webui_activation_failure(home_url)
            return None
        if time.monotonic() >= deadline:
            instance = _acquire_windows_desktop_instance()
            if instance is not None:
                return instance
            _show_existing_webui_activation_failure(home_url)
            return None
        time.sleep(min(EXISTING_WEBUI_POLL_SECONDS, remaining))


def _try_activate_existing_webui(
    home_url: str,
    *,
    open_browser: bool,
    timeout: float,
) -> ExistingWebUiActivation:
    from dance_trail.desktop_instance import try_activate_existing_webui

    return try_activate_existing_webui(
        home_url,
        open_browser=open_browser,
        timeout=timeout,
    )


def _show_existing_webui_activation_failure(home_url: str) -> None:
    from dance_trail._win_tray import show_error_message

    show_error_message(
        "DanceTrail could not activate an existing instance or become the "
        f"desktop owner at {home_url}."
    )


def _desktop_home_url() -> str:
    return f"http://{WEBUI_HOST}:{DEFAULT_WEBUI_PORT}{WEBUI_ROUTE_BY_VIEW['home']}"
