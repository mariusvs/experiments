"""Optional system-tray indicator so monitoring is visible, not covert.

Uses `pystray` + `Pillow` if installed. If they are not available the agent runs
without a tray icon (still transparent via the startup notice and consent record).
"""

from __future__ import annotations

from typing import Callable

from . import consent
from .config import Config


def _make_image():
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (64, 64), (30, 30, 30))
    d = ImageDraw.Draw(img)
    d.ellipse((10, 10, 54, 54), outline=(0, 200, 120), width=5)
    d.ellipse((26, 26, 38, 38), fill=(0, 200, 120))
    return img


def start_tray(config: Config, on_quit: Callable[[], None]) -> None:
    """Start a tray icon in a background thread. Raises if deps are missing."""
    import threading
    import pystray

    def _run():
        def quit_action(icon, item):
            on_quit()
            icon.stop()

        menu = pystray.Menu(
            pystray.MenuItem("Monitoring is ACTIVE", None, enabled=False),
            pystray.MenuItem(
                "What is recorded…",
                lambda icon, item: print(consent.notice_text(config.upload_url)),
            ),
            pystray.MenuItem("Stop monitoring", quit_action),
        )
        icon = pystray.Icon(
            "staff-activity-tracker",
            _make_image(),
            "Staff Activity Tracker (active)",
            menu,
        )
        icon.run()

    threading.Thread(target=_run, daemon=True).start()
