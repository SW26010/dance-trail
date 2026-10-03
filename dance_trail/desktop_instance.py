"""Windows desktop-instance ownership and existing Web UI activation."""

from __future__ import annotations

import ctypes
from contextlib import contextmanager
from ctypes import wintypes
from enum import Enum
from http.client import HTTPException
import mmap
import threading
import time
from urllib.request import ProxyHandler, build_opener
import webbrowser


DESKTOP_INSTANCE_MUTEX_NAME = "Local\\DanceTrail.DesktopTray.v1"
ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0x00000000
WAIT_ABANDONED = 0x00000080
WAIT_TIMEOUT = 0x00000102
WAIT_FAILED = 0xFFFFFFFF
EXISTING_WEBUI_WAIT_SECONDS = 5.0
EXISTING_WEBUI_POLL_SECONDS = 0.05
EXISTING_WEBUI_PROBE_TIMEOUT_SECONDS = 0.5
WEBUI_IDENTITY_MARKER = b"<title>DanceTrail</title>"
_DIRECT_HTTP_OPENER = build_opener(ProxyHandler({}))


@contextmanager
def publish_desktop_port(port: int, *, name: str = DESKTOP_INSTANCE_MUTEX_NAME):
    """Advertise the listener within this Windows session for the owner's lifetime."""
    with mmap.mmap(-1, 4, tagname=f"{name}.Port") as mapping:
        mapping[:] = port.to_bytes(4, "little")
        yield


def read_desktop_port(*, name: str = DESKTOP_INSTANCE_MUTEX_NAME) -> int | None:
    with mmap.mmap(-1, 4, tagname=f"{name}.Port") as mapping:
        port = int.from_bytes(mapping[:], "little")
    return port if 1 <= port <= 65535 else None


class ExistingWebUiActivation(Enum):
    """Result of one identity probe and optional browser activation attempt."""

    NOT_READY = "not-ready"
    READY = "ready"
    FAILED = "failed"


class WindowsDesktopInstanceLease:
    """Own the named mutex that represents the current tray app instance."""

    _local_names: set[str] = set()
    _local_names_lock = threading.Lock()

    def __init__(self, handle: int, kernel32, name: str) -> None:
        self._handle = handle
        self._kernel32 = kernel32
        self._name = name

    @classmethod
    def acquire(
        cls,
        name: str = DESKTOP_INSTANCE_MUTEX_NAME,
    ) -> "WindowsDesktopInstanceLease | None":
        """Return a lease for the first instance, or ``None`` for a later one."""
        with cls._local_names_lock:
            if name in cls._local_names:
                return None
            lease = cls._acquire_os_mutex(name)
            if lease is not None:
                cls._local_names.add(name)
            return lease

    @classmethod
    def _acquire_os_mutex(
        cls,
        name: str,
    ) -> "WindowsDesktopInstanceLease | None":
        kernel32 = _load_kernel32()
        ctypes.set_last_error(0)
        handle = kernel32.CreateMutexW(None, True, name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            wait_result = kernel32.WaitForSingleObject(handle, 0)
            if wait_result in (WAIT_OBJECT_0, WAIT_ABANDONED):
                return cls(handle, kernel32, name)
            if wait_result == WAIT_TIMEOUT:
                if not kernel32.CloseHandle(handle):
                    raise ctypes.WinError(ctypes.get_last_error())
                return None
            primary = (
                ctypes.WinError(ctypes.get_last_error())
                if wait_result == WAIT_FAILED
                else OSError(f"unexpected mutex wait result: {wait_result:#x}")
            )
            if not kernel32.CloseHandle(handle):
                raise ExceptionGroup(
                    "desktop instance acquisition and handle cleanup failed",
                    [primary, ctypes.WinError(ctypes.get_last_error())],
                ) from None
            raise primary
        return cls(handle, kernel32, name)

    def close(self) -> None:
        """Release instance ownership and close the underlying kernel handle."""
        if self._handle is None:
            return
        handle = self._handle
        self._handle = None
        errors: list[OSError] = []
        if not self._kernel32.ReleaseMutex(handle):
            errors.append(ctypes.WinError(ctypes.get_last_error()))
        if not self._kernel32.CloseHandle(handle):
            errors.append(ctypes.WinError(ctypes.get_last_error()))
        with self._local_names_lock:
            self._local_names.discard(self._name)
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise ExceptionGroup("desktop instance release failed", errors)

    def __enter__(self) -> "WindowsDesktopInstanceLease":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()


def open_existing_webui(
    home_url: str,
    *,
    wait_seconds: float = EXISTING_WEBUI_WAIT_SECONDS,
) -> bool:
    """Wait for the owned Web UI, then open it in the default browser."""
    deadline = time.monotonic() + wait_seconds
    while True:
        remaining = max(deadline - time.monotonic(), 0.0)
        activation = try_activate_existing_webui(
            home_url,
            open_browser=True,
            timeout=max(
                min(remaining, EXISTING_WEBUI_PROBE_TIMEOUT_SECONDS),
                EXISTING_WEBUI_POLL_SECONDS,
            ),
        )
        if activation is ExistingWebUiActivation.READY:
            return True
        if activation is ExistingWebUiActivation.FAILED:
            return False
        if time.monotonic() >= deadline:
            return False
        time.sleep(min(EXISTING_WEBUI_POLL_SECONDS, remaining))


def try_activate_existing_webui(
    home_url: str,
    *,
    open_browser: bool,
    timeout: float,
) -> ExistingWebUiActivation:
    """Probe one existing owner and optionally issue one browser activation."""
    try:
        with _DIRECT_HTTP_OPENER.open(home_url, timeout=timeout) as response:
            prefix = response.read(4096)
            if response.status != 200 or WEBUI_IDENTITY_MARKER not in prefix:
                return ExistingWebUiActivation.NOT_READY
    except (OSError, HTTPException):
        return ExistingWebUiActivation.NOT_READY

    if not open_browser:
        return ExistingWebUiActivation.READY
    try:
        opened = webbrowser.open(home_url)
    except (OSError, webbrowser.Error):
        return ExistingWebUiActivation.FAILED
    return (
        ExistingWebUiActivation.READY
        if opened
        else ExistingWebUiActivation.FAILED
    )


def _load_kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel32.ReleaseMutex.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32
