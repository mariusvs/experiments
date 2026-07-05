"""Reporting and (optional) upload helpers.

`build_report` aggregates raw samples into per-app and per-URL-host totals plus
an activity summary. `upload_batch` ships un-uploaded rows to a central endpoint.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

from .config import Config
from .storage import Storage


def _url_host(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    try:
        p = urlparse(url)
        if p.netloc:
            return p.netloc
    except Exception:
        return None
    return None


def _fmt_hms(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}h {m:02d}m {s:02d}s"


def build_report(storage: Storage, since: Optional[str] = None, until: Optional[str] = None) -> dict:
    rows = storage.query(since=since, until=until)

    per_app: dict[str, float] = defaultdict(float)
    per_host: dict[str, float] = defaultdict(float)
    per_user_active: dict[str, float] = defaultdict(float)
    per_user_idle: dict[str, float] = defaultdict(float)
    total_keys = 0
    total_mouse = 0
    total_dist = 0.0
    total_time = 0.0
    active_time = 0.0
    idle_time = 0.0

    for r in rows:
        dur = r["duration"] or 0.0
        total_time += dur
        app = r["app"] or "unknown"
        per_app[app] += dur
        host = _url_host(r["url"])
        if host:
            per_host[host] += dur
        if r["idle"]:
            idle_time += dur
            per_user_idle[r["user"]] += dur
        else:
            active_time += dur
            per_user_active[r["user"]] += dur
        total_keys += r["key_count"] or 0
        total_mouse += r["mouse_count"] or 0
        total_dist += r["mouse_dist"] or 0.0

    def top(d: dict[str, float], n: int = 20) -> list[dict]:
        return [
            {"name": k, "seconds": round(v, 1), "human": _fmt_hms(v)}
            for k, v in sorted(d.items(), key=lambda kv: kv[1], reverse=True)[:n]
        ]

    return {
        "range": {"since": since, "until": until, "samples": len(rows)},
        "totals": {
            "tracked_time": _fmt_hms(total_time),
            "active_time": _fmt_hms(active_time),
            "idle_time": _fmt_hms(idle_time),
            "keystrokes": total_keys,
            "mouse_events": total_mouse,
            "mouse_distance_px": round(total_dist, 1),
        },
        "top_apps": top(per_app),
        "top_sites": top(per_host),
        "per_user_active": {u: _fmt_hms(s) for u, s in per_user_active.items()},
        "per_user_idle": {u: _fmt_hms(s) for u, s in per_user_idle.items()},
    }


def render_text(report: dict) -> str:
    lines = []
    rng = report["range"]
    lines.append("=" * 60)
    lines.append("STAFF ACTIVITY REPORT")
    lines.append(f"  range: {rng['since'] or 'beginning'} -> {rng['until'] or 'now'}")
    lines.append(f"  samples: {rng['samples']}")
    lines.append("=" * 60)
    t = report["totals"]
    lines.append(f"Tracked time : {t['tracked_time']}")
    lines.append(f"  Active     : {t['active_time']}")
    lines.append(f"  Idle       : {t['idle_time']}")
    lines.append(f"Keystrokes   : {t['keystrokes']} (count only — content is never recorded)")
    lines.append(f"Mouse events : {t['mouse_events']}  ({t['mouse_distance_px']} px travelled)")
    lines.append("")
    lines.append("Top applications by time:")
    for a in report["top_apps"]:
        lines.append(f"  {a['human']:>14}  {a['name']}")
    lines.append("")
    lines.append("Top sites by time:")
    for s in report["top_sites"]:
        lines.append(f"  {s['human']:>14}  {s['name']}")
    if report["per_user_active"]:
        lines.append("")
        lines.append("Active time per user:")
        for u, s in report["per_user_active"].items():
            lines.append(f"  {s:>14}  {u}")
    return "\n".join(lines)


def default_since(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def upload_batch(storage: Storage, config: Config, limit: int = 500) -> int:
    """POST un-uploaded rows to config.upload_url. Returns count uploaded.

    Kept dependency-light: uses urllib from the stdlib.
    """
    import urllib.request

    rows = storage.unuploaded(limit=limit)
    if not rows:
        return 0

    payload = {
        "organization": config.organization,
        "device_label": config.device_label,
        "records": [dict(r) for r in rows],
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        config.upload_url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.upload_token}" if config.upload_token else "",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        if 200 <= resp.status < 300:
            storage.mark_uploaded([r["id"] for r in rows])
            return len(rows)
    return 0
