"""Windows work area and movement for the frameless pet window."""

from ctypes import POINTER, Structure, WinDLL, byref, c_int, c_void_p, create_unicode_buffer, sizeof
from ctypes.wintypes import BOOL, DWORD, HMONITOR, HWND, POINT, RECT, UINT

_user32 = WinDLL("user32", use_last_error=True)
_GA_ROOT = 2
_MONITOR_DEFAULTTONEAREST = 2
_SWP_NOSIZE = 0x0001
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_GWL_EXSTYLE = -20
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_NOACTIVATE = 0x08000000


class _MonitorInfo(Structure):
    _fields_ = [("size", DWORD), ("monitor", RECT), ("work", RECT), ("flags", DWORD)]


_user32.GetAncestor.argtypes = (HWND, UINT)
_user32.GetAncestor.restype = HWND
_user32.GetWindowRect.argtypes = (HWND, POINTER(RECT))
_user32.GetWindowRect.restype = BOOL
_user32.MonitorFromWindow.argtypes = (HWND, DWORD)
_user32.MonitorFromWindow.restype = HMONITOR
_user32.MonitorFromPoint.argtypes = (POINT, DWORD)
_user32.MonitorFromPoint.restype = HMONITOR
_user32.GetMonitorInfoW.argtypes = (HMONITOR, POINTER(_MonitorInfo))
_user32.GetMonitorInfoW.restype = BOOL
_user32.GetCursorPos.argtypes = (POINTER(POINT),)
_user32.GetCursorPos.restype = BOOL
_user32.SetWindowPos.argtypes = (HWND, HWND, c_int, c_int, c_int, c_int, UINT)
_user32.SetWindowPos.restype = BOOL
_user32.GetWindowLongW.argtypes = (HWND, c_int)
_user32.GetWindowLongW.restype = c_int
_user32.SetWindowLongW.argtypes = (HWND, c_int, c_int)
_user32.SetWindowLongW.restype = c_int
_user32.OpenInputDesktop.argtypes = (DWORD, BOOL, DWORD)
_user32.OpenInputDesktop.restype = c_void_p
_user32.GetUserObjectInformationW.argtypes = (c_void_p, c_int, c_void_p, DWORD, POINTER(DWORD))
_user32.GetUserObjectInformationW.restype = BOOL
_user32.CloseDesktop.argtypes = (c_void_p,)
_user32.CloseDesktop.restype = BOOL


def desktop_unlocked() -> bool:
    """Only accrue time while this session has the normal input desktop."""
    desktop = _user32.OpenInputDesktop(0, False, 0x0001)
    if not desktop:
        return False
    try:
        name = create_unicode_buffer(256)
        needed = DWORD()
        return bool(_user32.GetUserObjectInformationW(desktop, 2, name, sizeof(name), byref(needed))
                    and name.value.casefold() == "default")
    finally:
        _user32.CloseDesktop(desktop)


def pet_window(widget):
    """Return the native window, its bounds, and the current monitor's work area."""
    hwnd = _user32.GetAncestor(widget.winfo_id(), _GA_ROOT)
    rect = RECT()
    if not hwnd or not _user32.GetWindowRect(hwnd, byref(rect)):
        return None
    monitor = _user32.MonitorFromWindow(hwnd, _MONITOR_DEFAULTTONEAREST)
    info = _MonitorInfo(size=sizeof(_MonitorInfo))
    if not _user32.GetMonitorInfoW(monitor, byref(info)):
        return None
    return hwnd, rect, info.work


def pointer_over(rect: RECT) -> bool:
    cursor = POINT()
    return bool(_user32.GetCursorPos(byref(cursor))
                and rect.left <= cursor.x < rect.right
                and rect.top <= cursor.y < rect.bottom)


def pointer_work_area() -> RECT | None:
    cursor = POINT()
    _user32.GetCursorPos(byref(cursor))
    monitor = _user32.MonitorFromPoint(cursor, _MONITOR_DEFAULTTONEAREST)
    info = _MonitorInfo(size=sizeof(_MonitorInfo))
    return info.work if _user32.GetMonitorInfoW(monitor, byref(info)) else None


def prevent_activation(window) -> None:
    """Keep a draggable desktop visitor from activating on a click."""
    hwnd = _user32.GetAncestor(window.winfo_id(), _GA_ROOT)
    if hwnd:
        flags = _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        flags |= _WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE
        _user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, flags & ~_WS_EX_TRANSPARENT)


def move_window(hwnd: HWND, x: int, y: int) -> bool:
    """Preserve focus and work with negative desktop coordinates."""
    return bool(_user32.SetWindowPos(hwnd, None, x, y, 0, 0,
                                    _SWP_NOSIZE | _SWP_NOZORDER | _SWP_NOACTIVATE))
