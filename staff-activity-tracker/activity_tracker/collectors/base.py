"""Shared types and the platform dispatch for window collection."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse


@dataclass
class WindowInfo:
    app: str
    title: str
    url: Optional[str] = None

    def url_host(self) -> Optional[str]:
        """Return just scheme+host for the URL, dropping the path/query.

        Storing the host rather than the full URL is a privacy-preserving default
        for reporting; the full URL is still kept in the raw sample if collected.
        """
        if not self.url:
            return None
        try:
            p = urlparse(self.url)
            if p.scheme and p.netloc:
                return f"{p.scheme}://{p.netloc}"
        except Exception:
            return None
        return None


def get_active_window() -> WindowInfo:
    """Dispatch to the platform-specific implementation."""
    if sys.platform == "darwin":
        from . import macos
        return macos.get_active_window()
    if sys.platform.startswith("win"):
        from . import windows
        return windows.get_active_window()
    if sys.platform.startswith("linux"):
        from . import linux
        return linux.get_active_window()
    return WindowInfo(app="unsupported", title="", url=None)
