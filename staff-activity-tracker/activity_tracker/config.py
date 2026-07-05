"""Configuration loading and defaults."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


def default_data_dir() -> Path:
    """Return a per-user data directory that works on all three platforms."""
    if os.name == "nt":  # Windows
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "StaffActivityTracker"
    if sys.platform == "darwin":  # macOS
        return Path.home() / "Library" / "Application Support" / "StaffActivityTracker"
    # Linux / other unix
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "staff-activity-tracker"


@dataclass
class Config:
    # How often (seconds) to sample the foreground window / activity counters.
    sample_interval: float = 5.0

    # Seconds without keyboard/mouse input before the user is considered idle.
    idle_threshold: float = 60.0

    # Which signals to collect. Each can be disabled independently.
    collect_active_window: bool = True
    collect_input_activity: bool = True   # counts only — never key content
    collect_urls: bool = True

    # Where to store the local SQLite database.
    data_dir: str = field(default_factory=lambda: str(default_data_dir()))
    db_filename: str = "activity.sqlite3"

    # Transparency: require an explicit consent acknowledgement before the first
    # run, and show a visible indicator while running.
    require_consent: bool = True
    show_tray_indicator: bool = True

    # Optional: forward aggregated records to a central endpoint (HTTPS POST).
    # Leave empty to keep everything local. See report.py / agent.py.
    upload_url: str = ""
    upload_token: str = ""
    upload_interval: float = 300.0

    # Human-friendly labels for context in reports.
    organization: str = ""
    device_label: str = ""

    @property
    def db_path(self) -> Path:
        return Path(self.data_dir) / self.db_filename

    @classmethod
    def load(cls, path: str | os.PathLike[str] | None = None) -> "Config":
        """Load config from JSON. Missing file -> defaults. Unknown keys ignored."""
        cfg = cls()
        if path:
            p = Path(path)
            if p.exists():
                data: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
                known = {f for f in cfg.__dataclass_fields__}
                for k, v in data.items():
                    if k in known:
                        setattr(cfg, k, v)
        # An empty/missing data_dir means "use the platform default".
        if not cfg.data_dir:
            cfg.data_dir = str(default_data_dir())
        return cfg

    def save(self, path: str | os.PathLike[str]) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
