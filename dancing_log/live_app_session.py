"""Live watcher and overlay controls for the current app session."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import threading
import time
from typing import TYPE_CHECKING, Literal

from dancing_log.app_paths import AppRuntimeConfig
from dancing_log.vrc_log_watcher import default_vrc_log_dir
from dancing_log.watcher_lifetime_lock import (
    WatcherLifetimeLease,
    WatcherLifetimeLockUnavailable,
)

if TYPE_CHECKING:
    from dancing_log.overlay_server import MountedOverlayAdapter


WatchVrcLogsFunc = Callable[..., object]
DEFAULT_WATCHER_STOP_TIMEOUT_SECONDS = 3.0
LiveLifecycleState = Literal["stopped", "running", "stopping"]
LiveSessionState = Literal["open", "closing", "closed"]
WatcherOwnerMode = Literal["background", "synchronous"]


class LiveSessionUnavailableError(RuntimeError):
    """Raised when a terminal app session cannot accept a new lifecycle start."""


@dataclass(frozen=True)
class LiveWatcherRunOptions:
    log_dir: Path | str | None = None
    output_dir: Path | str | None = None
    session_name: str | None = None
    app_db_path: Path | str | None = None
    from_start: bool = False
    include_raw: bool = True
    live_db: bool = False
    record_playback: bool = True
    overlay_port: int | None = None
    poll_seconds: float = 0.25
    stop_after_idle_seconds: float | None = None
    archive_source_logs: bool = True
    source_log_dir: Path | str | None = None


@dataclass(frozen=True)
class LiveAppSessionStatus:
    session_state: LiveSessionState
    watcher_running: bool
    overlay_running: bool
    watcher_state: LiveLifecycleState
    overlay_state: LiveLifecycleState
    last_error: str | None
    last_watcher_stats: object | None


class LiveAppSessionRuntime:
    """Own live watcher and overlay lifecycle rules for one app session."""

    def __init__(
        self,
        *,
        app_root: Path | str | None = None,
        watch_vrc_logs_func: WatchVrcLogsFunc | None = None,
        migrate_legacy_config: bool = False,
        mounted_overlay: "MountedOverlayAdapter | None" = None,
        watcher_stop_timeout_seconds: float = DEFAULT_WATCHER_STOP_TIMEOUT_SECONDS,
    ) -> None:
        if watcher_stop_timeout_seconds <= 0:
            raise ValueError("watcher stop timeout must be positive")
        self.app_root = Path(app_root).resolve() if app_root is not None else None
        self._watch_vrc_logs_func = watch_vrc_logs_func
        self._migrate_legacy_config = migrate_legacy_config
        self._mounted_overlay = mounted_overlay
        self._watcher_stop_timeout_seconds = watcher_stop_timeout_seconds
        self._transition_lock = threading.Lock()
        self._lock = threading.RLock()
        self._watcher_condition = threading.Condition(self._lock)
        self._watcher_owner: object | None = None
        self._watcher_owner_mode: WatcherOwnerMode | None = None
        self._watcher_thread: threading.Thread | None = None
        self._watcher_stop_event: threading.Event | None = None
        self._watcher_overlay = False
        self._watcher_failure: BaseException | None = None
        self._session_state: LiveSessionState = "open"
        self._last_error: str | None = None
        self._last_watcher_stats: object | None = None

    @property
    def watcher_running(self) -> bool:
        return self.status().watcher_running

    @property
    def overlay_running(self) -> bool:
        return self.status().overlay_running

    @property
    def last_error(self) -> str | None:
        return self.status().last_error

    @property
    def last_watcher_stats(self) -> object | None:
        return self.status().last_watcher_stats

    def status(self) -> LiveAppSessionStatus:
        with self._lock:
            watcher_state = self._watcher_state_locked()
            overlay_state = self._overlay_state_locked(watcher_state)
            return LiveAppSessionStatus(
                session_state=self._session_state,
                watcher_running=watcher_state != "stopped",
                overlay_running=overlay_state != "stopped",
                watcher_state=watcher_state,
                overlay_state=overlay_state,
                last_error=self._last_error,
                last_watcher_stats=self._last_watcher_stats,
            )

    def start_watcher(self, *, overlay: bool = False) -> None:
        with self._transition_lock:
            self._start_watcher_transition(overlay=overlay)

    def _start_watcher_transition(self, *, overlay: bool) -> None:
        with self._lock:
            self._ensure_open_locked()
            if self._watcher_owner_mode == "synchronous":
                raise RuntimeError("watcher is already running synchronously")
            watcher_state = self._watcher_state_locked()
            overlay_running = watcher_state == "running" and self._watcher_overlay
            mounted_overlay = self._mounted_overlay
            if watcher_state == "running" and overlay and not overlay_running:
                if mounted_overlay is not None:
                    mounted_overlay.enable()
                    self._watcher_overlay = True
                    self._last_error = None
                    return
            elif watcher_state == "running":
                return
        if watcher_state == "stopping":
            self._stop_watcher_transition()
        elif watcher_state == "running":
            self._stop_watcher_transition()

        stop_event = threading.Event()
        watcher_kwargs = self._watcher_kwargs(
            LiveWatcherRunOptions(record_playback=True),
            stop_event=stop_event,
            use_mounted_overlay=True,
            use_configured_overlay_port=overlay,
        )
        try:
            lifetime = WatcherLifetimeLease.acquire(
                app_root=self.app_root,
                app_db_path=watcher_kwargs["app_db_path"],
            )
        except WatcherLifetimeLockUnavailable as exc:
            with self._lock:
                self._last_error = str(exc)
            raise
        try:
            thread = threading.Thread(
                target=self._watcher_thread_main,
                args=(stop_event, overlay, watcher_kwargs, lifetime),
                name="DancingLogLiveWatcher",
                daemon=False,
            )
        except BaseException as primary:
            try:
                lifetime.close()
            except BaseException as cleanup:
                raise BaseExceptionGroup(
                    f"watcher thread construction failed after {primary}",
                    [primary, cleanup],
                ) from None
            raise
        with self._lock:
            self._ensure_open_locked()
            if self._watcher_owner is not None:
                raise RuntimeError("watcher is already running")
            self._watcher_owner = thread
            self._watcher_owner_mode = "background"
            self._watcher_stop_event = stop_event
            self._watcher_overlay = overlay
            self._watcher_thread = thread
            self._watcher_failure = None
            self._last_error = None
            mounted_overlay = self._mounted_overlay
            try:
                if mounted_overlay is not None:
                    if overlay:
                        mounted_overlay.enable()
                    else:
                        mounted_overlay.disable()
                thread.start()
            except BaseException as primary:
                if self._watcher_thread is thread:
                    self._watcher_owner = None
                    self._watcher_owner_mode = None
                    self._watcher_thread = None
                    self._watcher_stop_event = None
                    self._watcher_overlay = False
                cleanup_errors: list[BaseException] = []
                if mounted_overlay is not None:
                    try:
                        mounted_overlay.close()
                    except BaseException as exc:
                        cleanup_errors.append(exc)
                try:
                    lifetime.close()
                except BaseException as exc:
                    cleanup_errors.append(exc)
                if cleanup_errors:
                    raise BaseExceptionGroup(
                        f"watcher start failed after {primary}",
                        [primary, *cleanup_errors],
                    ) from None
                raise

    def start_overlay(self) -> None:
        self.start_watcher(overlay=True)

    def stop_watcher(self) -> None:
        with self._transition_lock:
            self._stop_watcher_transition()

    def _stop_watcher_transition(
        self,
        *,
        wait_until_stopped: bool = False,
        deadline: float | None = None,
    ) -> None:
        with self._lock:
            if self._watcher_owner_mode == "synchronous":
                raise RuntimeError(
                    "synchronous watcher is running; wait for it to finish"
                )
            stop_event = self._watcher_stop_event
            thread = self._watcher_thread
        if thread is None or not thread.is_alive():
            if wait_until_stopped:
                self._raise_watcher_failure()
            return
        if thread is threading.current_thread():
            raise RuntimeError("watcher lifecycle cannot transition from its own thread")
        if stop_event is not None:
            stop_event.set()
        if wait_until_stopped:
            timeout = _remaining_deadline_seconds(deadline)
        else:
            timeout = self._watcher_stop_timeout_seconds
        thread.join(timeout=timeout)
        if thread.is_alive():
            if wait_until_stopped and deadline is not None:
                message = "watcher did not stop before the shutdown deadline"
            else:
                message = (
                    "watcher did not stop within "
                    f"{self._watcher_stop_timeout_seconds:g} seconds; "
                    "lifecycle transition cancelled"
                )
            with self._lock:
                if self._watcher_thread is thread:
                    self._last_error = message
            raise TimeoutError(message)
        if wait_until_stopped:
            self._raise_watcher_failure()

    def stop_overlay(self) -> None:
        with self._transition_lock:
            with self._lock:
                overlay_running = (
                    self._is_watcher_running_locked() and self._watcher_overlay
                )
                mounted_overlay = self._mounted_overlay
                if not overlay_running:
                    return
                if mounted_overlay is not None:
                    mounted_overlay.disable()
                    self._watcher_overlay = False
                    self._last_error = None
                    return
            self._stop_watcher_transition()
            self._start_watcher_transition(overlay=False)

    def close(self, *, deadline: float | None = None) -> None:
        remaining = _remaining_deadline_seconds(deadline)
        if remaining is None:
            transition_acquired = self._transition_lock.acquire()
        else:
            transition_acquired = self._transition_lock.acquire(timeout=remaining)
        if not transition_acquired:
            raise TimeoutError(
                "live session transition did not finish before the shutdown deadline"
            )
        try:
            with self._lock:
                if self._session_state == "closed":
                    return
                self._session_state = "closing"
            try:
                with self._watcher_condition:
                    while self._watcher_owner_mode == "synchronous":
                        remaining = _remaining_deadline_seconds(deadline)
                        if remaining is not None and remaining <= 0:
                            raise TimeoutError(
                                "synchronous watcher did not stop before the "
                                "shutdown deadline"
                            )
                        self._watcher_condition.wait(timeout=remaining)
                self._stop_watcher_transition(
                    wait_until_stopped=True,
                    deadline=deadline,
                )
            finally:
                with self._lock:
                    self._session_state = "closed"
        finally:
            self._transition_lock.release()

    def mount_overlay(self, overlay: "MountedOverlayAdapter") -> None:
        """Use an overlay route hosted by the owning app HTTP server."""
        with self._transition_lock:
            with self._lock:
                self._ensure_open_locked()
                if self._is_watcher_running_locked():
                    raise RuntimeError("cannot mount overlay while watcher is running")
                self._mounted_overlay = overlay

    def unmount_overlay(
        self,
        overlay: "MountedOverlayAdapter",
        *,
        deadline: float | None = None,
    ) -> None:
        """Detach and deactivate one overlay owned by an external HTTP server."""
        remaining = _remaining_deadline_seconds(deadline)
        if remaining is None:
            transition_acquired = self._transition_lock.acquire()
        else:
            transition_acquired = self._transition_lock.acquire(timeout=remaining)
        if not transition_acquired:
            raise TimeoutError(
                "overlay unmount did not finish before the shutdown deadline"
            )
        try:
            with self._lock:
                if self._mounted_overlay is not overlay:
                    return
                self._mounted_overlay = None
                self._watcher_overlay = False
            overlay.close()
        finally:
            self._transition_lock.release()

    def resolved_log_dir(self, options: LiveWatcherRunOptions | None = None) -> Path:
        return self._resolved_watcher_config(
            options or LiveWatcherRunOptions()
        ).log_dir

    def run_watcher(self, options: LiveWatcherRunOptions | None = None) -> object:
        """Run the CLI watcher synchronously within this session's lifecycle."""
        owner = object()
        with self._transition_lock:
            with self._lock:
                self._ensure_open_locked()
                if self._watcher_owner is not None:
                    raise RuntimeError("watcher is already running")
                self._watcher_owner = owner
                self._watcher_owner_mode = "synchronous"
                self._watcher_failure = None
                self._last_error = None
        try:
            watcher_kwargs = self._watcher_kwargs(
                options or LiveWatcherRunOptions(),
                stop_event=None,
                use_mounted_overlay=False,
                use_configured_overlay_port=False,
            )
            with WatcherLifetimeLease.acquire(
                app_root=self.app_root,
                app_db_path=watcher_kwargs["app_db_path"],
            ) as lifetime:
                stats = self._watch_vrc_logs(
                    lifetime=lifetime,
                    **watcher_kwargs,
                )
            with self._lock:
                self._last_error = None
                self._last_watcher_stats = stats
            return stats
        except BaseException as exc:
            with self._lock:
                self._last_error = str(exc)
            raise
        finally:
            with self._watcher_condition:
                if self._watcher_owner is owner:
                    self._watcher_owner = None
                    self._watcher_owner_mode = None
                    self._watcher_condition.notify_all()

    def _watcher_thread_main(
        self,
        stop_event: threading.Event,
        overlay: bool,
        watcher_kwargs: dict,
        lifetime: WatcherLifetimeLease,
    ) -> None:
        failure: BaseException | None = None
        try:
            stats = self._watch_vrc_logs(
                lifetime=lifetime,
                **watcher_kwargs,
            )
            with self._lock:
                self._last_watcher_stats = stats
        except BaseException as exc:  # surfaced through status() and terminal close.
            failure = exc
        finally:
            current_thread = threading.current_thread()
            with self._lock:
                # Thread identity is this generation's ownership token. A stale
                # finalizer must never reset a replacement watcher's overlay.
                if (
                    self._watcher_thread is current_thread
                    and self._watcher_owner is current_thread
                ):
                    stop_event.set()
                    mounted_overlay = self._mounted_overlay
                else:
                    mounted_overlay = None
            if mounted_overlay is not None:
                try:
                    mounted_overlay.close()
                except BaseException as exc:  # pragma: no cover - status path.
                    failure = _combine_watcher_failures(failure, exc)
            try:
                lifetime.close()
            except BaseException as exc:  # pragma: no cover - status path.
                failure = _combine_watcher_failures(failure, exc)
            with self._watcher_condition:
                if (
                    self._watcher_thread is current_thread
                    and self._watcher_owner is current_thread
                ):
                    self._watcher_failure = failure
                    if failure is not None:
                        self._last_error = str(failure)
                    self._watcher_thread = None
                    self._watcher_stop_event = None
                    self._watcher_overlay = False
                    self._watcher_owner = None
                    self._watcher_owner_mode = None
                    self._watcher_condition.notify_all()

    def _watcher_kwargs(
        self,
        options: LiveWatcherRunOptions,
        *,
        stop_event: threading.Event | None,
        use_mounted_overlay: bool,
        use_configured_overlay_port: bool,
    ) -> dict:
        watcher_config = self._resolved_watcher_config(options)
        mounted_overlay = self._mounted_overlay if use_mounted_overlay else None
        overlay_port = (
            watcher_config.overlay_port
            if use_configured_overlay_port and mounted_overlay is None
            else options.overlay_port
        )
        kwargs = {
            "app_root": self.app_root,
            "log_dir": watcher_config.log_dir,
            "output_dir": watcher_config.output_dir,
            "session_name": options.session_name,
            "app_db_path": watcher_config.app_db_path,
            "from_start": options.from_start,
            "include_raw": options.include_raw,
            "live_db": options.live_db,
            "record_playback": options.record_playback,
            "overlay_port": overlay_port,
            "poll_seconds": options.poll_seconds,
            "stop_after_idle_seconds": options.stop_after_idle_seconds,
            "stop_event": stop_event,
            "archive_source_logs": options.archive_source_logs,
            "source_log_dir": watcher_config.source_log_dir,
        }
        if mounted_overlay is not None:
            kwargs["overlay"] = mounted_overlay.borrow()
        return kwargs

    def _resolved_watcher_config(self, options: LiveWatcherRunOptions):
        config = AppRuntimeConfig.load(
            app_root=self.app_root,
            migrate_legacy=self._migrate_legacy_config,
        )
        return config.watcher_config(
            default_log_dir=default_vrc_log_dir(),
            log_dir=options.log_dir,
            output_dir=options.output_dir,
            source_log_dir=options.source_log_dir,
            app_db_path=options.app_db_path,
        )

    def _watch_vrc_logs(
        self,
        *,
        lifetime: WatcherLifetimeLease,
        **kwargs,
    ) -> object:
        watch_vrc_logs = self._watch_vrc_logs_func
        if watch_vrc_logs is None:
            from dancing_log.vrc_log_watcher import watch_vrc_logs
            kwargs["_watcher_lifetime_lease"] = lifetime
        return watch_vrc_logs(**kwargs)

    def _is_watcher_running_locked(self) -> bool:
        return self._watcher_state_locked() != "stopped"

    def _watcher_state_locked(self) -> LiveLifecycleState:
        if self._watcher_owner_mode == "synchronous":
            return "running"
        thread = self._watcher_thread
        if thread is None or not thread.is_alive():
            return "stopped"
        stop_event = self._watcher_stop_event
        if stop_event is not None and stop_event.is_set():
            return "stopping"
        return "running"

    def _overlay_state_locked(
        self,
        watcher_state: LiveLifecycleState,
    ) -> LiveLifecycleState:
        if not self._watcher_overlay or watcher_state == "stopped":
            return "stopped"
        return watcher_state

    def _ensure_open_locked(self) -> None:
        if self._session_state != "open":
            raise LiveSessionUnavailableError(
                f"live app session is {self._session_state}; it cannot be restarted"
            )

    def _raise_watcher_failure(self) -> None:
        with self._lock:
            failure = self._watcher_failure
        if failure is not None:
            raise failure


def _combine_watcher_failures(
    primary: BaseException | None,
    cleanup: BaseException,
) -> BaseException:
    if primary is None:
        return cleanup
    return BaseExceptionGroup(
        f"watcher failed with {primary}; overlay finalization failed with {cleanup}",
        [primary, cleanup],
    )


def _remaining_deadline_seconds(deadline: float | None) -> float | None:
    if deadline is None:
        return None
    return max(deadline - time.monotonic(), 0.0)
