"""The monitoring agent: samples the foreground window + input activity on a
fixed interval and writes rows to local storage. Optionally uploads batches.
"""

from __future__ import annotations

import getpass
import signal
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .collectors import InputActivityMonitor, get_active_window
from .storage import Storage
from . import consent


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Agent:
    def __init__(self, config: Config):
        self.config = config
        self.storage = Storage(config.db_path)
        self.input_monitor = InputActivityMonitor()
        self.user = getpass.getuser()
        self.host = socket.gethostname()
        self._stop = threading.Event()
        self._uploader_thread: threading.Thread | None = None

    # ------------------------------------------------------------------ run
    def run(self, assume_yes: bool = False) -> int:
        data_dir = Path(self.config.data_dir)
        if self.config.require_consent:
            if not consent.ensure_consent(data_dir, self.config.upload_url, assume_yes):
                print("Consent not given. Exiting without collecting anything.")
                return 1

        input_ok = False
        if self.config.collect_input_activity:
            input_ok = self.input_monitor.start()
            if not input_ok:
                print("Note: input-activity monitoring unavailable "
                      "(pynput not installed or no input access). Continuing without it.")

        self._install_signal_handlers()
        self._maybe_start_uploader()
        self._start_tray_if_enabled()
        self._purge_now()  # enforce retention on startup

        print(f"Staff Activity Tracker running. Data -> {self.config.db_path}")
        print("Press Ctrl+C to stop.")

        interval = max(1.0, float(self.config.sample_interval))
        next_purge = time.monotonic() + 86400.0  # daily
        try:
            while not self._stop.is_set():
                start = time.monotonic()
                self._collect_one(interval)
                if start >= next_purge:
                    self._purge_now()
                    next_purge = start + 86400.0
                elapsed = time.monotonic() - start
                self._stop.wait(max(0.0, interval - elapsed))
        finally:
            self.input_monitor.stop()
            self.storage.close()
        return 0

    def _collect_one(self, interval: float) -> None:
        window = get_active_window() if self.config.collect_active_window else None
        snap = self.input_monitor.snapshot_and_reset()

        idle = 0
        if self.config.collect_input_activity:
            if self.input_monitor.seconds_since_activity() >= self.config.idle_threshold:
                idle = 1

        url = None
        if window and self.config.collect_urls:
            # Prefer the full URL if the platform gave us one, else nothing.
            url = window.url

        self.storage.insert_sample(
            ts=_now_iso(),
            duration=interval,
            user=self.user,
            host=self.host,
            device_label=self.config.device_label,
            app=(window.app if window else None),
            window_title=(window.title if window else None),
            url=url,
            idle=idle,
            key_count=snap.key_count,
            mouse_count=snap.mouse_count,
            mouse_dist=snap.mouse_dist,
        )

    def _purge_now(self) -> None:
        from . import retention
        try:
            removed = retention.purge(self.storage, self.config.retention_days)
            if removed:
                print(f"[retention] purged {removed} sample(s) older than "
                      f"{self.config.retention_days} days")
        except Exception as exc:
            print(f"[retention] purge failed: {exc}")

    # -------------------------------------------------------------- uploader
    def _maybe_start_uploader(self) -> None:
        if not self.config.upload_url:
            return
        self._uploader_thread = threading.Thread(target=self._upload_loop, daemon=True)
        self._uploader_thread.start()

    def _upload_loop(self) -> None:
        from .report import upload_batch  # local import to avoid hard dep at import time
        while not self._stop.is_set():
            self._stop.wait(max(30.0, float(self.config.upload_interval)))
            if self._stop.is_set():
                break
            try:
                upload_batch(self.storage, self.config)
            except Exception as exc:  # never let upload failure kill collection
                print(f"[uploader] batch failed: {exc}")

    # ------------------------------------------------------------------ tray
    def _start_tray_if_enabled(self) -> None:
        if not self.config.show_tray_indicator:
            return
        try:
            from .tray import start_tray
            start_tray(self.config, self.stop)
        except Exception:
            # Tray is a nicety, not a requirement; keep running headless.
            pass

    # --------------------------------------------------------------- signals
    def _install_signal_handlers(self) -> None:
        def handler(signum, frame):
            self.stop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass  # not on main thread / unsupported

    def stop(self) -> None:
        self._stop.set()
