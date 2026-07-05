"""Input activity collector — measures ACTIVITY LEVEL, never content.

Uses `pynput` to attach global keyboard/mouse listeners. We only ever increment
counters and measure cursor travel distance. The identity of which key was
pressed is intentionally discarded immediately and never stored or transmitted.
This is what distinguishes an activity monitor from a keylogger.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass

try:
    from pynput import keyboard, mouse
    _HAVE_PYNPUT = True
except Exception:  # pragma: no cover - optional dependency / headless env
    _HAVE_PYNPUT = False


@dataclass
class InputSnapshot:
    key_count: int
    mouse_count: int
    mouse_dist: float
    last_activity: float  # monotonic timestamp of most recent input


class InputActivityMonitor:
    """Thread-safe counters for keyboard and mouse activity."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._key_count = 0
        self._mouse_count = 0
        self._mouse_dist = 0.0
        self._last_pos: tuple[int, int] | None = None
        self._last_activity = time.monotonic()
        self._kb_listener = None
        self._mouse_listener = None

    # --- event handlers: note we never receive/keep the key value in storage ---
    def _on_key_press(self, _key) -> None:
        # `_key` is deliberately ignored beyond counting. Do NOT log it.
        with self._lock:
            self._key_count += 1
            self._last_activity = time.monotonic()

    def _on_move(self, x: int, y: int) -> None:
        with self._lock:
            if self._last_pos is not None:
                dx = x - self._last_pos[0]
                dy = y - self._last_pos[1]
                self._mouse_dist += math.hypot(dx, dy)
            self._last_pos = (x, y)
            self._mouse_count += 1
            self._last_activity = time.monotonic()

    def _on_click(self, x: int, y: int, button, pressed: bool) -> None:
        if pressed:
            with self._lock:
                self._mouse_count += 1
                self._last_activity = time.monotonic()

    def _on_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        with self._lock:
            self._mouse_count += 1
            self._last_activity = time.monotonic()

    def start(self) -> bool:
        """Begin listening. Returns False if pynput is unavailable."""
        if not _HAVE_PYNPUT:
            return False
        self._kb_listener = keyboard.Listener(on_press=self._on_key_press)
        self._mouse_listener = mouse.Listener(
            on_move=self._on_move, on_click=self._on_click, on_scroll=self._on_scroll
        )
        self._kb_listener.start()
        self._mouse_listener.start()
        return True

    def stop(self) -> None:
        for listener in (self._kb_listener, self._mouse_listener):
            if listener is not None:
                try:
                    listener.stop()
                except Exception:
                    pass

    def snapshot_and_reset(self) -> InputSnapshot:
        """Return counts accumulated since the last call, then reset them."""
        with self._lock:
            snap = InputSnapshot(
                key_count=self._key_count,
                mouse_count=self._mouse_count,
                mouse_dist=round(self._mouse_dist, 1),
                last_activity=self._last_activity,
            )
            self._key_count = 0
            self._mouse_count = 0
            self._mouse_dist = 0.0
        return snap

    def seconds_since_activity(self) -> float:
        with self._lock:
            return time.monotonic() - self._last_activity
