"""Compatibility names for the shared application-data lifetime lease."""

from dancing_log.app_data_lifetime_lock import (
    APP_DATA_LOCK_FILENAME,
    AppDataLifetimeLease,
    AppDataLifetimeLockUnavailable,
    app_data_lifetime_lock_paths,
)


APP_WATCHER_LOCK_FILENAME = APP_DATA_LOCK_FILENAME
WatcherLifetimeLease = AppDataLifetimeLease
WatcherLifetimeLockUnavailable = AppDataLifetimeLockUnavailable
watcher_lifetime_lock_paths = app_data_lifetime_lock_paths


__all__ = [
    "APP_WATCHER_LOCK_FILENAME",
    "WatcherLifetimeLease",
    "WatcherLifetimeLockUnavailable",
    "watcher_lifetime_lock_paths",
]
