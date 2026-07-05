"""Period-over-period trends and team roll-ups.

Built on ``efficiency.compute_user_metrics`` so trends, team aggregates, and the
dashboard all share exactly one definition of the metrics.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import efficiency as eff
from .storage import Storage


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fmt_hms(seconds: float) -> str:
    return eff._fmt_hms(seconds)


# --------------------------------------------------------------------- periods
def period_bounds(num_periods: int, period_days: int, anchor: Optional[datetime] = None):
    """Return a list of (label, start_iso, end_iso) oldest-first.

    Period 0 is the most recent [anchor - period_days, anchor); each earlier
    period steps back one window.
    """
    anchor = anchor or _now()
    bounds = []
    for p in range(num_periods):
        end = anchor - timedelta(days=period_days * p)
        start = end - timedelta(days=period_days)
        label = start.date().isoformat()
        bounds.append((label, start.isoformat(), end.isoformat()))
    bounds.reverse()  # oldest first for time-series plotting
    return bounds


def weekly_series(
    storage: Storage,
    categories_path: Optional[str] = None,
    num_periods: int = 8,
    period_days: int = 7,
    weights: Optional[dict] = None,
    anchor: Optional[datetime] = None,
) -> dict:
    """Compute per-user efficiency metrics for each period.

    Returns {"periods": [...labels...], "series": {user: [per-period metrics]}}.
    Users with no samples in a period get a zeroed entry so lines stay aligned.
    """
    cats = eff.load_categories(categories_path)
    weights = weights or eff.DEFAULT_WEIGHTS
    bounds = period_bounds(num_periods, period_days, anchor)

    # Discover the full set of users across all periods first.
    all_rows = storage.query(since=bounds[0][1], until=bounds[-1][2])
    users = sorted({r["user"] or "unknown" for r in all_rows})

    series: dict[str, list] = {u: [] for u in users}
    labels = [b[0] for b in bounds]

    for label, start, end in bounds:
        rows = storage.query(since=start, until=end)
        by_user: dict[str, list] = defaultdict(list)
        for r in rows:
            by_user[r["user"] or "unknown"].append(r)
        for u in users:
            samples = by_user.get(u, [])
            if samples:
                m = eff.compute_user_metrics(samples, cats, weights)
                series[u].append({
                    "period": label,
                    "score": m["score"],
                    "active_ratio": round(m["active_ratio"], 3),
                    "productive_ratio": round(m["productive_ratio"], 3),
                    "active_hours": round(m["active"] / 3600, 2),
                })
            else:
                series[u].append({
                    "period": label, "score": 0.0, "active_ratio": 0.0,
                    "productive_ratio": 0.0, "active_hours": 0.0,
                })
    return {"periods": labels, "period_days": period_days, "series": series}


def build_trends(
    storage: Storage,
    categories_path: Optional[str] = None,
    num_periods: int = 8,
    period_days: int = 7,
    weights: Optional[dict] = None,
    anchor: Optional[datetime] = None,
) -> dict:
    """Latest vs. previous period deltas per user, plus the full series."""
    ws = weekly_series(storage, categories_path, num_periods, period_days, weights, anchor)
    trends = []
    for user, points in ws["series"].items():
        latest = points[-1] if points else None
        prev = points[-2] if len(points) >= 2 else None
        if not latest:
            continue
        delta = None
        if prev:
            delta = {
                "score": round(latest["score"] - prev["score"], 1),
                "active_ratio": round(latest["active_ratio"] - prev["active_ratio"], 3),
                "productive_ratio": round(
                    latest["productive_ratio"] - prev["productive_ratio"], 3),
                "active_hours": round(latest["active_hours"] - prev["active_hours"], 2),
            }
        trends.append({
            "user": user,
            "latest": latest,
            "previous": prev,
            "delta": delta,
            "sparkline": [p["score"] for p in points],
        })
    trends.sort(key=lambda t: (t["delta"]["score"] if t["delta"] else 0), reverse=True)
    return {"periods": ws["periods"], "period_days": period_days, "trends": trends}


# ------------------------------------------------------------------ team rollup
def team_rollup(
    storage: Storage,
    categories_path: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    weights: Optional[dict] = None,
) -> dict:
    """Aggregate metrics across the whole team for a range.

    Reports team totals and *aggregate* ratios (from summed times), plus the mean
    of individual scores. Aggregate ratios describe the team as one unit; the mean
    score describes the typical individual. Both are shown because they answer
    different questions.
    """
    cats = eff.load_categories(categories_path)
    weights = weights or eff.DEFAULT_WEIGHTS
    rows = storage.query(since=since, until=until)

    by_user: dict[str, list] = defaultdict(list)
    for r in rows:
        by_user[r["user"] or "unknown"].append(r)

    total_tracked = total_active = total_idle = 0.0
    cat_totals: dict[str, float] = defaultdict(float)
    scores = []
    per_user_summary = []

    for user, samples in sorted(by_user.items()):
        m = eff.compute_user_metrics(samples, cats, weights)
        total_tracked += m["tracked"]
        total_active += m["active"]
        total_idle += m["idle"]
        for c, v in m["cat_time"].items():
            cat_totals[c] += v
        scores.append(m["score"])
        per_user_summary.append({
            "user": user,
            "score": m["score"],
            "active_hours": round(m["active"] / 3600, 2),
            "productive_ratio": round(m["productive_ratio"], 3),
        })

    agg_active_ratio = (total_active / total_tracked) if total_tracked else 0.0
    productive = cat_totals.get("productive", 0.0)
    agg_productive_ratio = (productive / total_active) if total_active else 0.0
    mean_score = round(sum(scores) / len(scores), 1) if scores else 0.0

    per_user_summary.sort(key=lambda u: u["score"], reverse=True)
    return {
        "range": {"since": since, "until": until, "samples": len(rows)},
        "headcount": len(by_user),
        "team_totals": {
            "tracked": _fmt_hms(total_tracked),
            "active": _fmt_hms(total_active),
            "idle": _fmt_hms(total_idle),
            "tracked_hours": round(total_tracked / 3600, 2),
            "active_hours": round(total_active / 3600, 2),
        },
        "aggregate_active_ratio": round(agg_active_ratio, 3),
        "aggregate_productive_ratio": round(agg_productive_ratio, 3),
        "mean_individual_score": mean_score,
        "category_totals": {k: _fmt_hms(v) for k, v in sorted(cat_totals.items())},
        "category_hours": {k: round(v / 3600, 2) for k, v in sorted(cat_totals.items())},
        "members": per_user_summary,
    }


# -------------------------------------------------------------- per-user detail
def user_detail(
    storage: Storage,
    user: str,
    categories_path: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    num_periods: int = 8,
    period_days: int = 7,
    weights: Optional[dict] = None,
    anchor: Optional[datetime] = None,
) -> dict:
    """Full drill-down for one user: summary, weekly series, category split,
    top apps/sites, and a per-day breakdown."""
    cats = eff.load_categories(categories_path)
    weights = weights or eff.DEFAULT_WEIGHTS
    rows = [r for r in storage.query(since=since, until=until)
            if (r["user"] or "unknown") == user]

    summary = None
    category_hours: dict = {}
    top_productive: list = []
    top_distracting: list = []
    if rows:
        m = eff.compute_user_metrics(rows, cats, weights)
        summary = eff._format_user(m)
        category_hours = {k: round(v / 3600, 2) for k, v in sorted(m["cat_time"].items())}
        top_productive = eff._top_labels(m["app_by_cat"], "productive")
        top_distracting = eff._top_labels(m["app_by_cat"], "distracting")

    # weekly series for just this user
    ws = weekly_series(storage, categories_path, num_periods, period_days, weights, anchor)
    series = ws["series"].get(user, [])

    # per-day breakdown
    by_day: dict[str, list] = defaultdict(list)
    for r in rows:
        by_day[(r["ts"] or "")[:10]].append(r)
    daily = []
    for day in sorted(by_day):
        dm = eff.compute_user_metrics(by_day[day], cats, weights)
        daily.append({
            "date": day,
            "active_hours": round(dm["active"] / 3600, 2),
            "productive_ratio": round(dm["productive_ratio"], 3),
            "score": dm["score"],
        })

    return {
        "user": user,
        "range": {"since": since, "until": until, "samples": len(rows)},
        "summary": summary,
        "periods": ws["periods"],
        "series": series,
        "category_hours": category_hours,
        "top_productive": top_productive,
        "top_distracting": top_distracting,
        "daily": daily,
    }


# --------------------------------------------------------------- text rendering
def render_trends_text(report: dict) -> str:
    lines = ["=" * 64, "STAFF EFFICIENCY TRENDS "
             f"(period = {report['period_days']} days)", "=" * 64]
    lines.append("periods: " + " → ".join(report["periods"]))
    if not report["trends"]:
        lines.append("No data.")
        return "\n".join(lines)
    for t in report["trends"]:
        latest = t["latest"]
        d = t["delta"]
        arrow = ""
        if d:
            s = d["score"]
            arrow = f"  ({'+' if s >= 0 else ''}{s} vs prev)"
        lines.append("")
        lines.append(f"● {t['user']}: score {latest['score']}/100{arrow}")
        spark = _sparkline(t["sparkline"])
        lines.append(f"    trend {spark}  ({report['periods'][0]} → {report['periods'][-1]})")
        if d:
            lines.append(
                f"    Δ active {_pct_delta(d['active_ratio'])}, "
                f"Δ productive {_pct_delta(d['productive_ratio'])}, "
                f"Δ active-hours {d['active_hours']:+.2f}")
    return "\n".join(lines)


def render_team_text(report: dict) -> str:
    rng = report["range"]
    lines = ["=" * 64, "TEAM ROLL-UP", "=" * 64]
    lines.append(f"range     : {rng['since'] or 'beginning'} → {rng['until'] or 'now'}")
    lines.append(f"headcount : {report['headcount']}")
    tt = report["team_totals"]
    lines.append(f"team time : tracked {tt['tracked']} | active {tt['active']} | idle {tt['idle']}")
    lines.append(f"aggregate active ratio     : {_pct(report['aggregate_active_ratio'])}")
    lines.append(f"aggregate productive ratio : {_pct(report['aggregate_productive_ratio'])}")
    lines.append(f"mean individual score      : {report['mean_individual_score']}/100")
    if report["category_totals"]:
        lines.append("team time by category: " + ", ".join(
            f"{k}={v}" for k, v in report["category_totals"].items()))
    lines.append("")
    lines.append("members (by score):")
    for m in report["members"]:
        lines.append(f"  {m['score']:>5}/100  {m['user']:<16} "
                     f"active {m['active_hours']}h, productive {_pct(m['productive_ratio'])}")
    lines.append("")
    lines.append("-" * 64)
    lines.append("Team roll-ups are the safer lens: they surface workload imbalance and")
    lines.append("tooling problems without turning individuals into a leaderboard. Prefer")
    lines.append("acting at this level over ranking people against each other.")
    return "\n".join(lines)


# ------------------------------------------------------------------- tiny utils
_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def _sparkline(values: list) -> str:
    if not values:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    out = []
    for v in values:
        idx = int((v - lo) / span * (len(_SPARK_CHARS) - 1))
        out.append(_SPARK_CHARS[idx])
    return "".join(out)


def _pct(ratio: float) -> str:
    return f"{ratio * 100:.1f}%"


def _pct_delta(ratio: float) -> str:
    return f"{ratio * 100:+.1f}%"
