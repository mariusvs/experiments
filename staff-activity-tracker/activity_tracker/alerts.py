"""Threshold-based alerts derived from the activity data.

Rules (each disabled when its config threshold is 0):
  - score_drop      : week-over-week efficiency score fell by >= threshold
  - low_active      : most-recent-week active/tracked ratio below threshold
  - high_distracting: most-recent-week distracting/active ratio above threshold
  - low_hours       : most-recent-week active hours below threshold

Alerts are meant to prompt a *human to look*, not to trigger automatic action.
A single low week is usually noise (illness, leave, a research-heavy sprint);
treat alerts as a question, not a conclusion.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from . import analytics, efficiency
from .config import Config
from .storage import Storage

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def evaluate(
    storage: Storage,
    config: Config,
    categories_path: Optional[str] = None,
    period_days: int = 7,
    anchor: Optional[datetime] = None,
) -> list[dict]:
    """Return a list of alert dicts, most severe first."""
    cats_path = categories_path or config.categories_file or None
    cats = efficiency.load_categories(cats_path)

    # Two most recent periods for score-drop; latest for level checks.
    bounds = analytics.period_bounds(2, period_days, anchor=anchor)
    (_, prev_start, prev_end) = bounds[0]
    (_, cur_start, cur_end) = bounds[1]

    alerts: list[dict] = []
    users = storage.distinct_users(since=prev_start)

    for user in users:
        cur_rows = [r for r in storage.query(since=cur_start, until=cur_end)
                    if (r["user"] or "unknown") == user]
        prev_rows = [r for r in storage.query(since=prev_start, until=prev_end)
                     if (r["user"] or "unknown") == user]
        if not cur_rows:
            continue
        cur = efficiency.compute_user_metrics(cur_rows, cats)
        prev = efficiency.compute_user_metrics(prev_rows, cats) if prev_rows else None

        active_hours = cur["active"] / 3600.0
        distracting = cur["cat_time"].get("distracting", 0.0)
        distracting_ratio = (distracting / cur["active"]) if cur["active"] else 0.0

        # score drop
        if config.alert_weekly_score_drop and prev:
            drop = prev["score"] - cur["score"]
            if drop >= config.alert_weekly_score_drop:
                alerts.append(_mk(
                    user, "score_drop",
                    "high" if drop >= 2 * config.alert_weekly_score_drop else "medium",
                    f"efficiency score fell {round(drop,1)} pts "
                    f"({prev['score']} → {cur['score']}) week over week",
                    {"previous": prev["score"], "current": cur["score"],
                     "drop": round(drop, 1)}))

        # low active ratio
        if config.alert_min_active_ratio and cur["active_ratio"] < config.alert_min_active_ratio:
            alerts.append(_mk(
                user, "low_active", "medium",
                f"active time {round(cur['active_ratio']*100)}% of tracked, "
                f"below {round(config.alert_min_active_ratio*100)}% threshold",
                {"active_ratio": round(cur["active_ratio"], 3)}))

        # high distracting ratio
        if config.alert_max_distracting_ratio and distracting_ratio > config.alert_max_distracting_ratio:
            alerts.append(_mk(
                user, "high_distracting", "medium",
                f"{round(distracting_ratio*100)}% of active time on distracting "
                f"apps/sites, above {round(config.alert_max_distracting_ratio*100)}% threshold",
                {"distracting_ratio": round(distracting_ratio, 3)}))

        # low active hours
        if config.alert_min_active_hours and active_hours < config.alert_min_active_hours:
            alerts.append(_mk(
                user, "low_hours", "low",
                f"only {round(active_hours,1)}h active this period, "
                f"below {config.alert_min_active_hours}h threshold",
                {"active_hours": round(active_hours, 2)}))

    alerts.sort(key=lambda a: SEVERITY_ORDER.get(a["severity"], 9))
    return alerts


def _mk(user: str, rule: str, severity: str, message: str, data: dict) -> dict:
    return {"user": user, "rule": rule, "severity": severity,
            "message": message, "data": data}


def render_text(alerts: list[dict]) -> str:
    if not alerts:
        return "No alerts. (Either all metrics are within thresholds, or thresholds are disabled.)"
    icon = {"high": "🔴", "medium": "🟡", "low": "⚪"}
    lines = ["=" * 64, f"ALERTS ({len(alerts)})", "=" * 64]
    for a in alerts:
        lines.append(f"{icon.get(a['severity'],'•')} [{a['severity']}] {a['user']}: {a['message']}")
    lines.append("")
    lines.append("-" * 64)
    lines.append("An alert is a prompt to look, not a verdict. A low week is often")
    lines.append("leave, illness, or heads-down work that doesn't show at the desktop.")
    lines.append("Ask before you assume.")
    return "\n".join(lines)


def post_webhook(alerts: list[dict], config: Config) -> bool:
    """POST alerts to config.alert_webhook_url if set. Returns True on 2xx."""
    if not config.alert_webhook_url or not alerts:
        return False
    import json
    import urllib.request
    body = json.dumps({
        "organization": config.organization,
        "device_label": config.device_label,
        "alerts": alerts,
    }).encode("utf-8")
    req = urllib.request.Request(
        config.alert_webhook_url, data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return 200 <= resp.status < 300
