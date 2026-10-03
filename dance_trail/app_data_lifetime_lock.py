"""Cross-process ownership for one application-data resource scope."""

from __future__ import annotations

from dataclasses import dataclass
import errno
import os
from pathlib import Path
import threading
from typing import BinaryIO

from dance_trail.app_paths import AppPaths


# Preserve the original locator names so current releases remain mutually
# exclusive with older watcher-only releases.
APP_DATA_LOCK_FILENAME = ".dance-trail-watcher.lock"
_DATABASE_LOCK_SUFFIX = "watcher.lock"
_PROCESS_LOCK = threading.Lock()
_PROCESS_OWNED_PATHS: set[str] = set()
_LOCK_CONFLICT_ERRNOS = {errno.EACCES, errno.EAGAIN, errno.EDEADLK}


class AppDataLifetimeLockUnavailable(RuntimeError):
    """Raised when another writer owns the app or database scope."""


@dataclass
class _LockedFile:
    path: Path
    key: str
    handle: BinaryIO
    released: bool = False

    @classmethod
    def acquire(cls, path: Path) -> "_LockedFile":
        resolved = path.resolve()
        key = os.path.normcase(str(resolved))
        resolved.parent.mkdir(parents=True, exist_ok=True)
        with _PROCESS_LOCK:
            if key in _PROCESS_OWNED_PATHS:
                raise AppDataLifetimeLockUnavailable(
                    f"app data lifetime is already active for {resolved}"
                )
            handle = resolved.open("a+b")
            try:
                _ensure_lock_byte(handle)
                _lock_first_byte(handle)
            except OSError as exc:
                handle.close()
                if exc.errno in _LOCK_CONFLICT_ERRNOS:
                    raise AppDataLifetimeLockUnavailable(
                        f"app data lifetime is already active for {resolved}"
                    ) from exc
                raise
            _PROCESS_OWNED_PATHS.add(key)
        return cls(resolved, key, handle)

    def release(self) -> None:
        if self.released:
            return
        self.released = True
        errors: list[BaseException] = []
        with _PROCESS_LOCK:
            try:
                _unlock_first_byte(self.handle)
            except BaseException as exc:
                errors.append(exc)
            try:
                self.handle.close()
            except BaseException as exc:
                errors.append(exc)
            finally:
                _PROCESS_OWNED_PATHS.discard(self.key)
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise BaseExceptionGroup(
                f"app data lifetime unlock failed for {self.path}",
                errors,
            )


class AppDataLifetimeLease:
    """Exclusive app and database locks held for one complete write lifetime."""

    def __init__(self, locks: list[_LockedFile]) -> None:
        self._locks = locks
        self._closed = False

    @classmethod
    def acquire(
        cls,
        *,
        app_root: Path | str | None,
        app_db_path: Path | str,
    ) -> "AppDataLifetimeLease":
        paths = app_data_lifetime_lock_paths(
            app_root=app_root,
            app_db_path=app_db_path,
        )
        locks: list[_LockedFile] = []
        try:
            for path in paths:
                locks.append(_LockedFile.acquire(path))
        except BaseException as primary:
            cleanup_errors = _release_locks(locks)
            if cleanup_errors:
                raise BaseExceptionGroup(
                    f"app data lifetime lock failed after {primary}",
                    [primary, *cleanup_errors],
                ) from None
            raise
        return cls(locks)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        errors = _release_locks(self._locks)
        self._locks = []
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise BaseExceptionGroup("app data lifetime unlock failed", errors)

    def verify_scope(
        self,
        *,
        app_root: Path | str | None,
        app_db_path: Path | str,
    ) -> None:
        """Reject an internal handoff that does not own this exact scope."""
        expected = {
            os.path.normcase(str(path.resolve()))
            for path in app_data_lifetime_lock_paths(
                app_root=app_root,
                app_db_path=app_db_path,
            )
        }
        owned = {lock.key for lock in self._locks}
        if self._closed or owned != expected:
            raise RuntimeError("app data lifetime lease does not own the requested scope")

    def __enter__(self) -> "AppDataLifetimeLease":
        return self

    def __exit__(self, _exc_type, primary, _traceback) -> bool:
        try:
            self.close()
        except BaseException as cleanup:
            if primary is not None:
                raise BaseExceptionGroup(
                    f"app data write failed with {primary}; lifetime unlock failed with {cleanup}",
                    [primary, cleanup],
                ) from None
            raise
        return False


def app_data_lifetime_lock_paths(
    *,
    app_root: Path | str | None,
    app_db_path: Path | str,
) -> tuple[Path, ...]:
    """Return deterministic app and database lock paths."""
    paths = AppPaths.from_root(app_root)
    database = Path(app_db_path).resolve()
    candidates = {
        (paths.data_dir / APP_DATA_LOCK_FILENAME).resolve(),
        (database.parent / f".{database.name}.{_DATABASE_LOCK_SUFFIX}").resolve(),
    }
    return tuple(sorted(candidates, key=lambda path: os.path.normcase(str(path))))


def _release_locks(locks: list[_LockedFile]) -> list[BaseException]:
    errors: list[BaseException] = []
    for lock in reversed(locks):
        try:
            lock.release()
        except BaseException as exc:
            errors.append(exc)
    return errors


def _ensure_lock_byte(handle: BinaryIO) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)


if os.name == "nt":
    import msvcrt

    def _lock_first_byte(handle: BinaryIO) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock_first_byte(handle: BinaryIO) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock_first_byte(handle: BinaryIO) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock_first_byte(handle: BinaryIO) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
