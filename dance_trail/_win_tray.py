"""Windows-only tray window implementation."""

from __future__ import annotations

from collections.abc import Callable
import ctypes
from ctypes import wintypes
import time
import webbrowser

from dance_trail.tray_app import (
    IDM_EXIT,
    IDM_OPEN_WEBUI,
    IDM_TOGGLE_OVERLAY,
    IDM_TOGGLE_WATCHER,
    TrayRuntime,
    _is_separator,
)
from dance_trail.webui_server import WebUiServer


HCURSOR = getattr(wintypes, "HCURSOR", wintypes.HANDLE)
HBRUSH = getattr(wintypes, "HBRUSH", wintypes.HANDLE)
HMODULE = getattr(wintypes, "HMODULE", wintypes.HINSTANCE)
ATOM = getattr(wintypes, "ATOM", wintypes.WORD)
UINT_PTR = getattr(wintypes, "UINT_PTR", wintypes.WPARAM)
LPVOID = getattr(wintypes, "LPVOID", ctypes.c_void_p)
LRESULT = getattr(wintypes, "LRESULT", wintypes.LPARAM)

WM_DESTROY = 0x0002
WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
WM_COMMAND = 0x0111
WM_USER = 0x0400
WM_TRAYICON = WM_USER + 1
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205

NIM_ADD = 0x00000000
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004

MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100
MB_OK = 0x00000000
MB_ICONERROR = 0x00000010

IDI_APPLICATION = 32512
SW_HIDE = 0
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
END_SESSION_SHUTDOWN_TIMEOUT_SECONDS = 4.0


class POINT(ctypes.Structure):
    _fields_ = [
        ("x", wintypes.LONG),
        ("y", wintypes.LONG),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", HCURSOR),
        ("hbrBackground", HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
    ]


WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = HMODULE
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = ATOM
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.DefWindowProcW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.DefWindowProcW.restype = LRESULT
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.restype = wintypes.BOOL
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
user32.LoadIconW.restype = wintypes.HICON
user32.GetMessageW.argtypes = [
    ctypes.POINTER(MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
]
user32.GetMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, UINT_PTR, wintypes.LPCWSTR]
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.TrackPopupMenu.argtypes = [
    wintypes.HMENU,
    wintypes.UINT,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    LPVOID,
]
user32.TrackPopupMenu.restype = wintypes.UINT
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.MessageBoxW.argtypes = [
    wintypes.HWND,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.UINT,
]
user32.MessageBoxW.restype = ctypes.c_int
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
shell32.Shell_NotifyIconW.restype = wintypes.BOOL


def _enable_dpi_awareness() -> bool:
    """Use physical screen coordinates for tray menus on high-DPI displays."""
    try:
        set_context = user32.SetProcessDpiAwarenessContext
    except AttributeError:
        return False
    set_context.argtypes = [wintypes.HANDLE]
    set_context.restype = wintypes.BOOL
    return bool(set_context(ctypes.c_void_p(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)))


def show_error_message(message: str) -> None:
    """Show a visible startup error for the windowed executable."""
    user32.MessageBoxW(None, message, "DanceTrail", MB_OK | MB_ICONERROR)


def _int_resource(resource_id: int):
    return ctypes.cast(ctypes.c_void_p(resource_id), wintypes.LPCWSTR)


class WindowsTrayApp:
    """Own the hidden tray window and message loop for one Web UI server."""

    def __init__(
        self,
        server: WebUiServer,
        runtime: TrayRuntime,
        *,
        shutdown: Callable[..., None],
    ) -> None:
        self.server = server
        self.runtime = runtime
        self._shutdown = shutdown
        self._class_name = f"DanceTrailTrayWindow{id(self)}"
        self._wndproc = WNDPROC(self._window_proc)
        self._hinstance = kernel32.GetModuleHandleW(None)
        self._hwnd = None
        self._icon_added = False

    def run(self, *, open_browser: bool) -> None:
        _enable_dpi_awareness()
        self._create_window()
        self._add_tray_icon()
        if open_browser:
            webbrowser.open(self.server.home_url)
        self._message_loop()

    def _create_window(self) -> None:
        window_class = WNDCLASSW()
        window_class.lpfnWndProc = ctypes.cast(self._wndproc, ctypes.c_void_p).value
        window_class.hInstance = self._hinstance
        window_class.hIcon = user32.LoadIconW(None, _int_resource(IDI_APPLICATION))
        window_class.lpszClassName = self._class_name
        if not user32.RegisterClassW(ctypes.byref(window_class)):
            self._raise_last_error("RegisterClassW")

        hwnd = user32.CreateWindowExW(
            0,
            self._class_name,
            "DanceTrail",
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            self._hinstance,
            None,
        )
        if not hwnd:
            self._raise_last_error("CreateWindowExW")
        self._hwnd = hwnd
        user32.ShowWindow(hwnd, SW_HIDE)

    def _add_tray_icon(self) -> None:
        assert self._hwnd is not None
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAYICON
        nid.hIcon = user32.LoadIconW(None, _int_resource(IDI_APPLICATION))
        nid.szTip = f"DanceTrail Web UI - {self.server.url}"[:127]
        if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
            self._raise_last_error("Shell_NotifyIconW(NIM_ADD)")
        self._icon_added = True

    def _remove_tray_icon(self) -> None:
        if not self._icon_added or self._hwnd is None:
            return
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = 1
        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
        self._icon_added = False

    def _message_loop(self) -> None:
        msg = MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except KeyboardInterrupt:
            self._quit()

    def _window_proc(self, hwnd, message, wparam, lparam):
        try:
            return self._dispatch_window_message(hwnd, message, wparam, lparam)
        except BaseException as error:
            if message != WM_ENDSESSION:
                self._show_callback_error(error)
            return 0

    def _dispatch_window_message(self, hwnd, message, wparam, lparam):
        if message == WM_QUERYENDSESSION:
            return 1
        if message == WM_ENDSESSION:
            if bool(wparam):
                try:
                    self._shutdown(
                        deadline=(
                            time.monotonic() + END_SESSION_SHUTDOWN_TIMEOUT_SECONDS
                        )
                    )
                finally:
                    self._remove_tray_icon()
                    user32.PostQuitMessage(0)
            return 0
        if message == WM_TRAYICON:
            if int(lparam) == WM_LBUTTONDBLCLK:
                self._open_webui()
            elif int(lparam) == WM_RBUTTONUP:
                self._show_menu()
            return 0
        if message == WM_COMMAND:
            command_id = int(wparam) & 0xFFFF
            if command_id == IDM_OPEN_WEBUI:
                self._open_webui()
            elif command_id == IDM_TOGGLE_WATCHER:
                self.runtime.toggle_watcher()
            elif command_id == IDM_TOGGLE_OVERLAY:
                self.runtime.toggle_overlay()
            elif command_id == IDM_EXIT:
                self._quit()
            return 0
        if message == WM_DESTROY:
            self._remove_tray_icon()
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _show_callback_error(self, error: BaseException) -> None:
        """Keep Python exceptions inside WNDPROC and provide visible feedback."""
        message = f"{type(error).__name__}: {error}"
        try:
            user32.MessageBoxW(
                self._hwnd,
                message,
                "DanceTrail tray action failed",
                MB_OK | MB_ICONERROR,
            )
        except Exception:
            # A ctypes callback must never leak a second exception while reporting one.
            pass

    def _show_menu(self) -> None:
        assert self._hwnd is not None
        menu = user32.CreatePopupMenu()
        if not menu:
            return
        try:
            for item in self.runtime.menu_items():
                if _is_separator(item):
                    user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
                else:
                    assert item.command_id is not None
                    user32.AppendMenuW(menu, MF_STRING, int(item.command_id), item.label)
            point = POINT()
            user32.GetCursorPos(ctypes.byref(point))
            user32.SetForegroundWindow(self._hwnd)
            command_id = user32.TrackPopupMenu(
                menu,
                TPM_RIGHTBUTTON | TPM_RETURNCMD,
                point.x,
                point.y,
                0,
                self._hwnd,
                None,
            )
            if command_id:
                self._window_proc(self._hwnd, WM_COMMAND, command_id, 0)
        finally:
            user32.DestroyMenu(menu)

    def _open_webui(self) -> None:
        webbrowser.open(self.server.home_url)

    def _quit(self) -> None:
        if self._hwnd is not None:
            user32.DestroyWindow(self._hwnd)

    @staticmethod
    def _raise_last_error(label: str) -> None:
        error = ctypes.get_last_error()
        raise OSError(error, f"{label} failed")
