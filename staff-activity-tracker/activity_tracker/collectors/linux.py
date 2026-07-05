"""Linux foreground-window and browser-URL collection.

Targets X11 via `python-xlib` when available, with a fallback to the `xdotool`
and `xprop` command-line tools. Wayland deliberately restricts global window
introspection for privacy reasons; under Wayland we degrade gracefully and report
what we can (see notes in README). Browser URLs are parsed from the window title,
since there is no portable, permissioned URL API across Linux browsers.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Optional

from .base import WindowInfo

try:
    from Xlib import display as _xdisplay, X  # type: ignore
    _HAVE_XLIB = True
except Exception:
    _HAVE_XLIB = False

_IS_WAYLAND = bool(os.environ.get("WAYLAND_DISPLAY")) and not os.environ.get("DISPLAY")

_BROWSER_HINTS = ("Mozilla Firefox", "Google Chrome", "Chromium", "Microsoft Edge", "Brave")
# Match a bare URL that some browsers append to the window title.
_URL_RE = re.compile(r"https?://[^\s]+")


def _via_xlib() -> Optional[WindowInfo]:
    if not _HAVE_XLIB:
        return None
    try:
        d = _xdisplay.Display()
        root = d.screen().root
        net_active = d.intern_atom("_NET_ACTIVE_WINDOW")
        net_name = d.intern_atom("_NET_WM_NAME")
        wm_class_atom = d.intern_atom("WM_CLASS")

        active = root.get_full_property(net_active, X.AnyPropertyType)
        if not active or not active.value:
            return None
        win_id = active.value[0]
        win = d.create_resource_object("window", win_id)

        title = ""
        name_prop = win.get_full_property(net_name, 0) or win.get_full_property(
            d.intern_atom("WM_NAME"), 0
        )
        if name_prop and name_prop.value:
            title = (
                name_prop.value.decode("utf-8", "replace")
                if isinstance(name_prop.value, bytes)
                else str(name_prop.value)
            )

        app = ""
        cls = win.get_full_property(wm_class_atom, 0)
        if cls and cls.value:
            raw = cls.value.decode("utf-8", "replace") if isinstance(cls.value, bytes) else str(cls.value)
            parts = [p for p in raw.split("\x00") if p]
            if parts:
                app = parts[-1]
        d.close()
        return WindowInfo(app=app or "unknown", title=title, url=_extract_url(title))
    except Exception:
        return None


def _via_cmdline() -> Optional[WindowInfo]:
    if not shutil.which("xdotool"):
        return None
    try:
        win_id = subprocess.run(
            ["xdotool", "getactivewindow"], capture_output=True, text=True, timeout=2
        ).stdout.strip()
        if not win_id:
            return None
        title = subprocess.run(
            ["xdotool", "getwindowname", win_id], capture_output=True, text=True, timeout=2
        ).stdout.strip()
        app = ""
        if shutil.which("xprop"):
            out = subprocess.run(
                ["xprop", "-id", win_id, "WM_CLASS"], capture_output=True, text=True, timeout=2
            ).stdout
            m = re.findall(r'"([^"]+)"', out)
            if m:
                app = m[-1]
        return WindowInfo(app=app or "unknown", title=title, url=_extract_url(title))
    except Exception:
        return None


def _extract_url(title: str) -> Optional[str]:
    m = _URL_RE.search(title or "")
    return m.group(0) if m else None


def get_active_window() -> WindowInfo:
    if _IS_WAYLAND:
        # Wayland blocks cross-window title reads; report a clear placeholder.
        return WindowInfo(app="wayland-restricted", title="", url=None)
    info = _via_xlib() or _via_cmdline()
    if info is None:
        return WindowInfo(app="unknown", title="", url=None)
    return info
