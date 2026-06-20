"""Native Windows file/folder picker adapter for the Web UI."""

from __future__ import annotations

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from pathlib import Path
import threading
from typing import Any
from uuid import UUID


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


def pick_windows_path(field: dict[str, Any], initial: str | None) -> str | None:
    """Open a field-driven native Windows file/folder picker."""
    return _run_windows_picker(field, initial)


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


