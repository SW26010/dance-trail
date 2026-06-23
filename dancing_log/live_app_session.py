"""Live watcher and overlay controls for the current app session."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import threading

from dancing_log.app_paths import AppRuntimeConfig
from dancing_log.vrc_log_watcher import default_vrc_log_dir


WatchVrcLogsFunc = Callable[..., object]


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
    watcher_running: bool
    overlay_running: bool
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
    ) -> None:
        self.app_root = Path(app_root).resolve() if app_root is not None else None
        self._watch_vrc_logs_func = watch_vrc_logs_func
        self._migrate_legacy_config = migrate_legacy_config
        self._lock = threading.RLock()
        self._watcher_thread: threading.Thread | None = None
        self._watcher_stop_event: threading.Event | None = None
        self._watcher_overlay = False
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
            watcher_running = self._is_watcher_running_locked()
            return LiveAppSessionStatus(
                watcher_running=watcher_running,
                overlay_running=watcher_running and self._watcher_overlay,
                last_error=self._last_error,
                last_watcher_stats=self._last_watcher_stats,
            )

    def start_watcher(self, *, overlay: bool = False) -> None:
        status = self.status()
        if status.watcher_running:
            if overlay and not status.overlay_running:
                self.stop_watcher()
            else:
                return

        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._watcher_thread_main,
            args=(stop_event, overlay),
            name="DancingLogLiveWatcher",
            daemon=True,
        )
        with self._lock:
            self._watcher_stop_event = stop_event
            self._watcher_overlay = overlay
            self._watcher_thread = thread
            self._last_error = None
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
        if not self.status().overlay_running:
            return
        self.stop_watcher()
        self.start_watcher(overlay=False)

    def close(self) -> None:
        self.stop_watcher()

    def resolved_log_dir(self, options: LiveWatcherRunOptions | None = None) -> Path:
        return self._resolved_watcher_config(
            options or LiveWatcherRunOptions()
        ).log_dir

    def run_watcher(self, options: LiveWatcherRunOptions | None = None) -> object:
        try:
            stats = self._watch_vrc_logs(
                **self._watcher_kwargs(
                    options or LiveWatcherRunOptions(),
                    stop_event=None,
                    use_configured_overlay_port=False,
                )
            )
            with self._lock:
                self._last_error = None
                self._last_watcher_stats = stats
            return stats
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
            raise

    def _watcher_thread_main(self, stop_event: threading.Event, overlay: bool) -> None:
        try:
            stats = self._watch_vrc_logs(
                **self._watcher_kwargs(
                    LiveWatcherRunOptions(record_playback=True),
                    stop_event=stop_event,
                    use_configured_overlay_port=overlay,
                )
            )
            with self._lock:
                self._last_watcher_stats = stats
        except Exception as exc:  # pragma: no cover - surfaced through status().
            with self._lock:
                self._last_error = str(exc)
        finally:
            with self._lock:
                if self._watcher_thread is threading.current_thread():
                    self._watcher_thread = None
                    self._watcher_stop_event = None
                    self._watcher_overlay = False

    def _watcher_kwargs(
        self,
        options: LiveWatcherRunOptions,
        *,
        stop_event: threading.Event | None,
        use_configured_overlay_port: bool,
    ) -> dict:
        watcher_config = self._resolved_watcher_config(options)
        overlay_port = (
            watcher_config.overlay_port
            if use_configured_overlay_port
            else options.overlay_port
        )
        return {
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

    def _watch_vrc_logs(self, **kwargs) -> object:
        watch_vrc_logs = self._watch_vrc_logs_func
        if watch_vrc_logs is None:
            from dancing_log.vrc_log_watcher import watch_vrc_logs
        return watch_vrc_logs(**kwargs)

    def _is_watcher_running_locked(self) -> bool:
        return self._watcher_thread is not None and self._watcher_thread.is_alive()
