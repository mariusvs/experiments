"""Windows foreground-window and browser-URL collection.

Uses ctypes against user32/kernel32 so it works with only the standard library
plus optional psutil for a nicer process name. Browser URL extraction on Windows
requires the UI Automation stack; we attempt it via `uiautomation` if installed,
otherwise we fall back to the window title (which usually contains the page name).
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Optional

from .base import WindowInfo

try:
    import psutil
    _HAVE_PSUTIL = True
except Exception:
    _HAVE_PSUTIL = False

try:
    import uiautomation as _uia
    _HAVE_UIA = True
except Exception:
    _HAVE_UIA = False

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

_BROWSER_PROCS = {
    "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe",
}


def _foreground_hwnd():
    return _user32.GetForegroundWindow()


def _window_title(hwnd) -> str:
    length = _user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _process_name(hwnd) -> str:
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if _HAVE_PSUTIL:
        try:
            return psutil.Process(pid.value).name()
        except Exception:
            return ""
    return ""


def _browser_url(hwnd, proc_name: str) -> Optional[str]:
    """Best-effort URL read from the focused browser's address bar via UIA."""
    if not (_HAVE_UIA and proc_name.lower() in _BROWSER_PROCS):
        return None
    try:
        control = _uia.ControlFromHandle(hwnd)
        if control is None:
            return None
        # Address/search bar is an Edit control exposing ValuePattern.
        edit = control.EditControl(searchDepth=20)
        if edit.Exists(0, 0):
            value = edit.GetValuePattern().Value
            if value:
                return value
    except Exception:
        return None
    return None


def get_active_window() -> WindowInfo:
    hwnd = _foreground_hwnd()
    if not hwnd:
        return WindowInfo(app="", title="", url=None)
    title = _window_title(hwnd)
    proc = _process_name(hwnd)
    url = _browser_url(hwnd, proc)
    return WindowInfo(app=proc or "unknown", title=title, url=url)
