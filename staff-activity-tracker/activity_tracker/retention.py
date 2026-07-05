"""Data-retention helpers.

Minimising how long personal data is kept is a core data-protection principle
(and a legal requirement under regimes like GDPR). This module deletes raw
samples older than the configured window.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from .storage import Storage


def cutoff_iso(retention_days: int, now: Optional[datetime] = None) -> Optional[str]:
    """ISO timestamp before which samples should be deleted, or None if disabled."""
    if not retention_days or retention_days <= 0:
        return None
    now = now or datetime.now(timezone.utc)
    return (now - timedelta(days=retention_days)).isoformat()


def purge(storage: Storage, retention_days: int, now: Optional[datetime] = None) -> int:
    """Delete samples older than the retention window. Returns rows removed."""
    cutoff = cutoff_iso(retention_days, now)
    if cutoff is None:
        return 0
    return storage.purge_older_than(cutoff)
