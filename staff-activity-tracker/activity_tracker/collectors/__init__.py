"""Collectors for foreground window, browser URL, and input activity."""

from .base import WindowInfo, get_active_window
from .input_activity import InputActivityMonitor, InputSnapshot

__all__ = [
    "WindowInfo",
    "get_active_window",
    "InputActivityMonitor",
    "InputSnapshot",
]
