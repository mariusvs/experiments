"""Efficiency / productivity analytics built on top of the raw activity samples.

Design principle: efficiency here is about **how time is allocated and how
focused work is**, NOT about input volume. Keystroke and mouse counts are
deliberately excluded from the score — rewarding them just teaches people to
mash keys and wiggle the mouse. The score is a transparent, tunable heuristic;
treat it as a conversation starter, not an objective verdict on a person.

Metrics per user (over a time range):
  - active_ratio      : active_time / tracked_time
  - productive_ratio  : productive_time / active_time
  - focus_score       : based on average uninterrupted time-on-task
  - efficiency_score  : weighted blend of the three (0-100)
Plus a per-category time breakdown and the top apps/sites driving each category.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from .storage import Storage

# --- default scoring weights (documented; override via categories file) -------
DEFAULT_WEIGHTS = {
    "active": 0.40,       # being at the machine and not idle
    "productive": 0.40,   # time in work apps/sites vs distracting ones
    "focus": 0.20,        # sustained attention vs constant context-switching
}
# Average time-on-task (seconds) at which focus is considered "full marks".
FOCUS_TARGET_SECONDS = 600.0  # 10 minutes


DEFAULT_CATEGORIES = {
    "productive": {"apps": [], "domains": []},
    "neutral": {"apps": [], "domains": []},
    "distracting": {"apps": [], "domains": []},
}


def load_categories(path: Optional[str]) -> dict:
    if not path:
        return DEFAULT_CATEGORIES
    p = Path(path)
    if not p.exists():
        return DEFAULT_CATEGORIES
    raw = json.loads(p.read_text(encoding="utf-8"))
    cats = {}
    for name in ("productive", "neutral", "distracting"):
        block = raw.get(name, {}) or {}
        cats[name] = {
            "apps": [str(a).lower() for a in block.get("apps", [])],
            "domains": [str(d).lower() for d in block.get("domains", [])],
        }
    return cats


def _url_host(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    try:
        host = urlparse(url).netloc
        return host or None
    except Exception:
        return None


def categorize(app: Optional[str], url: Optional[str], cats: dict) -> str:
    """Return 'productive' | 'neutral' | 'distracting' | 'uncategorized'.

    A URL match wins over an app match (the site you're on is more specific than
    'a browser is focused'). Precedence among categories: distracting > productive
    > neutral, so a distracting site inside a 'productive' browser is still
    counted as distracting.
    """
    app_l = (app or "").lower()
    host = (_url_host(url) or "").lower()

    def matches(block: dict) -> bool:
        if host and any(d in host for d in block["domains"]):
            return True
        if app_l and any(a in app_l for a in block["apps"]):
            return True
        return False

    # URL host takes priority if it matches any category.
    if host:
        for name in ("distracting", "productive", "neutral"):
            block = cats.get(name, {"apps": [], "domains": []})
            if any(d in host for d in block["domains"]):
                return name
    for name in ("distracting", "productive", "neutral"):
        if matches(cats.get(name, {"apps": [], "domains": []})):
            return name
    return "uncategorized"


def _fmt_hms(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}h {m:02d}m {s:02d}s"


def _focus_stats(samples: list) -> tuple[float, float, int]:
    """Return (avg_session_seconds, longest_session_seconds, switch_count).

    A 'session' is a maximal run of consecutive samples on the same app while the
    user is active. Idle samples break a session and are not counted as focus.
    """
    sessions: list[float] = []
    current_app = None
    current_len = 0.0
    switches = 0
    prev_app = None

    for r in samples:
        if r["idle"]:
            if current_len > 0:
                sessions.append(current_len)
            current_app, current_len = None, 0.0
            prev_app = None
            continue
        app = r["app"] or "unknown"
        if prev_app is not None and app != prev_app:
            switches += 1
        if app == current_app:
            current_len += r["duration"] or 0.0
        else:
            if current_len > 0:
                sessions.append(current_len)
            current_app = app
            current_len = r["duration"] or 0.0
        prev_app = app

    if current_len > 0:
        sessions.append(current_len)

    if not sessions:
        return 0.0, 0.0, switches
    avg = sum(sessions) / len(sessions)
    return avg, max(sessions), switches


def _score(active_ratio: float, productive_ratio: float, avg_focus: float,
           weights: dict) -> float:
    focus_factor = min(1.0, avg_focus / FOCUS_TARGET_SECONDS) if avg_focus else 0.0
    raw = (
        weights["active"] * active_ratio
        + weights["productive"] * productive_ratio
        + weights["focus"] * focus_factor
    )
    return round(100.0 * raw, 1)


def build_efficiency(
    storage: Storage,
    categories_path: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    weights: Optional[dict] = None,
) -> dict:
    cats = load_categories(categories_path)
    weights = weights or DEFAULT_WEIGHTS
    rows = storage.query(since=since, until=until)

    by_user: dict[str, list] = defaultdict(list)
    for r in rows:
        by_user[r["user"] or "unknown"].append(r)

    users_out = [
        _format_user(compute_user_metrics(samples, cats, weights))
        for _, samples in sorted(by_user.items())
    ]
    users_out.sort(key=lambda u: u["efficiency_score"], reverse=True)
    return {
        "range": {"since": since, "until": until, "samples": len(rows)},
        "weights": weights,
        "focus_target_seconds": FOCUS_TARGET_SECONDS,
        "users": users_out,
    }


def compute_user_metrics(samples: list, cats: dict, weights: Optional[dict] = None) -> dict:
    """Compute NUMERIC efficiency metrics for one user's samples.

    Returns raw numbers (seconds, ratios) so callers can compute deltas and
    aggregates. Use ``_format_user`` to turn this into the human-facing shape.
    """
    weights = weights or DEFAULT_WEIGHTS
    user = samples[0]["user"] if samples else "unknown"
    tracked = active = idle = 0.0
    cat_time: dict[str, float] = defaultdict(float)
    app_by_cat: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for r in samples:
        dur = r["duration"] or 0.0
        tracked += dur
        if r["idle"]:
            idle += dur
            continue  # idle time is not attributed to any app category
        active += dur
        cat = categorize(r["app"], r["url"], cats)
        cat_time[cat] += dur
        label = (_url_host(r["url"]) or r["app"] or "unknown")
        app_by_cat[cat][label] += dur

    productive = cat_time.get("productive", 0.0)
    active_ratio = (active / tracked) if tracked else 0.0
    productive_ratio = (productive / active) if active else 0.0
    avg_focus, longest_focus, switches = _focus_stats(samples)
    score = _score(active_ratio, productive_ratio, avg_focus, weights)
    switches_per_hour = round(switches / (active / 3600), 1) if active else 0.0

    return {
        "user": user,
        "score": score,
        "tracked": tracked,
        "active": active,
        "idle": idle,
        "active_ratio": active_ratio,
        "productive_ratio": productive_ratio,
        "cat_time": dict(cat_time),
        "app_by_cat": {k: dict(v) for k, v in app_by_cat.items()},
        "avg_focus": avg_focus,
        "longest_focus": longest_focus,
        "switches": switches,
        "switches_per_hour": switches_per_hour,
    }


def _top_labels(app_by_cat: dict, cat: str, n: int = 5) -> list:
    items = sorted(app_by_cat.get(cat, {}).items(), key=lambda kv: kv[1], reverse=True)
    return [{"name": k, "human": _fmt_hms(v)} for k, v in items[:n]]


def _format_user(m: dict) -> dict:
    """Turn numeric metrics from ``compute_user_metrics`` into the report shape."""
    return {
        "user": m["user"],
        "efficiency_score": m["score"],
        "tracked_time": _fmt_hms(m["tracked"]),
        "active_time": _fmt_hms(m["active"]),
        "idle_time": _fmt_hms(m["idle"]),
        "active_ratio": round(m["active_ratio"], 3),
        "productive_ratio": round(m["productive_ratio"], 3),
        "category_time": {k: _fmt_hms(v) for k, v in sorted(m["cat_time"].items())},
        "focus": {
            "avg_session": _fmt_hms(m["avg_focus"]),
            "longest_session": _fmt_hms(m["longest_focus"]),
            "context_switches": m["switches"],
            "switches_per_active_hour": m["switches_per_hour"],
        },
        "top_productive": _top_labels(m["app_by_cat"], "productive"),
        "top_distracting": _top_labels(m["app_by_cat"], "distracting"),
    }


def render_text(report: dict) -> str:
    lines = []
    rng = report["range"]
    lines.append("=" * 64)
    lines.append("STAFF EFFICIENCY REPORT")
    lines.append(f"  range   : {rng['since'] or 'beginning'} -> {rng['until'] or 'now'}")
    lines.append(f"  samples : {rng['samples']}")
    w = report["weights"]
    lines.append(f"  score   = 100 x ({w['active']}*active_ratio "
                 f"+ {w['productive']}*productive_ratio + {w['focus']}*focus_factor)")
    lines.append("=" * 64)
    if not report["users"]:
        lines.append("No data in range.")
        return "\n".join(lines)

    for u in report["users"]:
        lines.append("")
        lines.append(f"● {u['user']}   efficiency score: {u['efficiency_score']} / 100")
        lines.append(f"    tracked {u['tracked_time']} | active {u['active_time']} "
                     f"({int(u['active_ratio']*100)}%) | idle {u['idle_time']}")
        lines.append(f"    productive share of active time: {int(u['productive_ratio']*100)}%")
        cats = u["category_time"]
        lines.append("    time by category: " + ", ".join(
            f"{k}={v}" for k, v in cats.items()))
        f = u["focus"]
        lines.append(f"    focus: avg task {f['avg_session']}, longest {f['longest_session']}, "
                     f"{f['switches_per_active_hour']} switches/active-hr")
        if u["top_productive"]:
            lines.append("    top productive: " + ", ".join(
                f"{t['name']} ({t['human']})" for t in u["top_productive"]))
        if u["top_distracting"]:
            lines.append("    top distracting: " + ", ".join(
                f"{t['name']} ({t['human']})" for t in u["top_distracting"]))

    lines.append("")
    lines.append("-" * 64)
    lines.append("Note: this score reflects TIME ALLOCATION and FOCUS, not effort or")
    lines.append("output quality. It cannot see thinking, reading on paper, meetings away")
    lines.append("from the desk, or good work done slowly. Use it to spot patterns worth a")
    lines.append("conversation — not as an automated performance verdict.")
    return "\n".join(lines)
