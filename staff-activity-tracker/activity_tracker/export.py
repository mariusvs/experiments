"""Export activity data to CSV and PDF for record-keeping and sharing."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

from . import analytics, efficiency, pdf, report as report_mod
from .config import Config
from .storage import Storage

_SAMPLE_COLUMNS = [
    "id", "ts", "duration", "user", "host", "device_label", "app",
    "window_title", "url", "idle", "key_count", "mouse_count", "mouse_dist",
]


def export_samples_csv(storage: Storage, path: str,
                       since: Optional[str] = None, until: Optional[str] = None) -> int:
    """Write raw samples to CSV. Returns the number of rows written."""
    rows = storage.query(since=since, until=until)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(_SAMPLE_COLUMNS)
        for r in rows:
            w.writerow([r[c] for c in _SAMPLE_COLUMNS])
    return len(rows)


def export_efficiency_csv(storage: Storage, path: str, config: Config,
                          since: Optional[str] = None) -> int:
    """Write one row per user with their efficiency summary. Returns row count."""
    cats = config.categories_file or None
    rep = efficiency.build_efficiency(storage, categories_path=cats, since=since)
    fields = ["user", "efficiency_score", "tracked_time", "active_time",
              "idle_time", "active_ratio", "productive_ratio",
              "avg_focus", "context_switches"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(fields)
        for u in rep["users"]:
            w.writerow([
                u["user"], u["efficiency_score"], u["tracked_time"],
                u["active_time"], u["idle_time"], u["active_ratio"],
                u["productive_ratio"], u["focus"]["avg_session"],
                u["focus"]["context_switches"],
            ])
    return len(rep["users"])


def build_report_lines(storage: Storage, config: Config, days: int) -> list[str]:
    """Compose a plain-text report combining team, efficiency, and trends."""
    cats = config.categories_file or None
    since = report_mod.default_since(days)
    lines: list[str] = []
    org = config.organization or "Your organization"
    lines.append(f"{org} — Activity & Efficiency Report")
    lines.append(f"Range: last {days} days")
    lines.append("")

    team = analytics.team_rollup(storage, categories_path=cats, since=since)
    lines.extend(analytics.render_team_text(team).splitlines())
    lines.append("")
    lines.append("")

    eff = efficiency.build_efficiency(storage, categories_path=cats, since=since)
    lines.extend(efficiency.render_text(eff).splitlines())
    lines.append("")
    lines.append("")

    trends = analytics.build_trends(storage, categories_path=cats)
    trend_text = analytics.render_trends_text(trends)
    # Sparkline block chars aren't in Latin-1; swap for ASCII for the PDF.
    for a, b in [("▁", "."), ("▂", ":"), ("▃", "-"), ("▄", "="),
                 ("▅", "+"), ("▆", "*"), ("▇", "#"), ("█", "#")]:
        trend_text = trend_text.replace(a, b)
    lines.extend(trend_text.splitlines())
    return lines


def export_pdf(storage: Storage, path: str, config: Config, days: int = 7) -> str:
    """Render the combined report to a PDF file. Returns the path."""
    lines = build_report_lines(storage, config, days)
    return pdf.text_to_pdf(lines, path, title="")
