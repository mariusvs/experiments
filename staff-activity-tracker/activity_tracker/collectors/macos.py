"""macOS foreground-app and browser-URL collection.

Foreground app + window title come from the Quartz / AppKit APIs via pyobjc.
Browser URLs are read with AppleScript (osascript), which is the supported,
user-visible way to query Safari/Chrome/Edge tabs — it requires the user to grant
Automation permission, keeping collection transparent.
"""

from __future__ import annotations

import subprocess
from typing import Optional

from .base import WindowInfo

try:
    from AppKit import NSWorkspace
    from Quartz import (
        CGWindowListCopyWindowInfo,
        kCGWindowListOptionOnScreenOnly,
        kCGNullWindowID,
    )
    _HAVE_PYOBJC = True
except Exception:
    _HAVE_PYOBJC = False


_BROWSER_SCRIPTS = {
    "Safari": 'tell application "Safari" to return URL of front document',
    "Google Chrome": 'tell application "Google Chrome" to return URL of active tab of front window',
    "Microsoft Edge": 'tell application "Microsoft Edge" to return URL of active tab of front window',
    "Brave Browser": 'tell application "Brave Browser" to return URL of active tab of front window',
}


def _frontmost_app_name() -> str:
    if not _HAVE_PYOBJC:
        return ""
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    return app.localizedName() if app else ""


def _front_window_title(app_name: str) -> str:
    if not _HAVE_PYOBJC:
        return ""
    options = kCGWindowListOptionOnScreenOnly
    windows = CGWindowListCopyWindowInfo(options, kCGNullWindowID) or []
    for w in windows:
        if w.get("kCGWindowOwnerName") == app_name and w.get("kCGWindowLayer", 1) == 0:
            name = w.get("kCGWindowName")
            if name:
                return name
    return ""


def _browser_url(app_name: str) -> Optional[str]:
    script = _BROWSER_SCRIPTS.get(app_name)
    if not script:
        return None
    try:
        out = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=2,
        )
        url = out.stdout.strip()
        return url or None
    except Exception:
        return None


def get_active_window() -> WindowInfo:
    app = _frontmost_app_name()
    title = _front_window_title(app)
    url = _browser_url(app)
    return WindowInfo(app=app or "unknown", title=title, url=url)
