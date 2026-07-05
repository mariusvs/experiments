"""Consent / transparency gate.

Legitimate workplace monitoring depends on the monitored person being informed.
This module enforces a one-time, recorded acknowledgement on each device before
any data is collected, and exposes the notice text for a tray tooltip / banner.
"""

from __future__ import annotations

import getpass
import json
import socket
from datetime import datetime, timezone
from pathlib import Path

NOTICE = """\
============================================================
 ACTIVITY MONITORING NOTICE
============================================================
This company-owned device runs Staff Activity Tracker.

While it runs, the following is recorded for legitimate
business purposes (productivity, security, compliance):

  - The application currently in focus and how long
  - Browser page titles / URLs you visit
  - Input ACTIVITY LEVEL (counts of keystrokes and mouse
    movement) to gauge active vs. idle time

It does NOT record the text you type, your passwords, the
content of your messages, your screen, camera, or microphone.

Data is stored{destination}. Do not use this device for
private matters you do not want associated with work.
============================================================
"""


def notice_text(upload_url: str = "") -> str:
    dest = " on this device" if not upload_url else " on this device and sent to your organization's server"
    return NOTICE.format(destination=dest)


def consent_marker_path(data_dir: Path) -> Path:
    return Path(data_dir) / "consent.json"


def has_consented(data_dir: Path) -> bool:
    return consent_marker_path(data_dir).exists()


def record_consent(data_dir: Path, method: str) -> dict:
    """Persist a consent record and return it."""
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    record = {
        "user": getpass.getuser(),
        "host": socket.gethostname(),
        "acknowledged_at": datetime.now(timezone.utc).isoformat(),
        "method": method,  # e.g. "interactive", "preapproved-policy"
    }
    consent_marker_path(data_dir).write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def ensure_consent(data_dir: Path, upload_url: str = "", assume_yes: bool = False) -> bool:
    """Show the notice and require acknowledgement. Returns True if we may proceed.

    ``assume_yes`` is for centrally-managed deployments where consent is handled
    out-of-band (e.g. signed acceptable-use policy). It still records the notice
    was displayed, so there is always an audit trail on the device.
    """
    if has_consented(data_dir):
        return True

    print(notice_text(upload_url))

    if assume_yes:
        record_consent(data_dir, method="preapproved-policy")
        return True

    try:
        answer = input("Type 'I AGREE' to acknowledge and continue (or anything else to exit): ").strip()
    except (EOFError, KeyboardInterrupt):
        return False

    if answer.upper() == "I AGREE":
        record_consent(data_dir, method="interactive")
        return True
    return False
