"""Tests for trends, team roll-ups, and the dashboard page (headless)."""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tempfile
from activity_tracker.storage import Storage
from activity_tracker import analytics, dashboard, efficiency

CATS = {
    "productive": {"apps": ["code"], "domains": ["github.com"]},
    "neutral": {"apps": [], "domains": []},
    "distracting": {"apps": ["steam"], "domains": ["youtube.com"]},
}


def _cats(d):
    p = Path(d) / "cats.json"
    p.write_text(json.dumps(CATS), encoding="utf-8")
    return str(p)


def _seed_two_weeks(s):
    """Week -2: alice mostly productive; Week -1: alice slips to distracting."""
    anchor = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
    # older week (~10 days ago): productive
    old = anchor - timedelta(days=10)
    for i in range(6):
        s.insert_sample(ts=(old + timedelta(minutes=i)).isoformat(), duration=60.0,
                        user="alice", host="h", device_label="pc", app="code.exe",
                        window_title="w", url="https://github.com/x", idle=0,
                        key_count=1, mouse_count=1, mouse_dist=1.0)
    # recent week (~2 days ago): distracting
    recent = anchor - timedelta(days=2)
    for i in range(6):
        app, url = ("chrome.exe", "https://youtube.com/x")
        s.insert_sample(ts=(recent + timedelta(minutes=i)).isoformat(), duration=60.0,
                        user="alice", host="h", device_label="pc", app=app,
                        window_title="w", url=url, idle=0,
                        key_count=1, mouse_count=1, mouse_dist=1.0)
    return anchor


def test_period_bounds_oldest_first():
    anchor = datetime(2026, 7, 5, tzinfo=timezone.utc)
    b = analytics.period_bounds(3, 7, anchor=anchor)
    assert len(b) == 3
    # oldest first: start of first < start of last
    assert b[0][1] < b[-1][1]
    # each window is 7 days
    start = datetime.fromisoformat(b[-1][1])
    end = datetime.fromisoformat(b[-1][2])
    assert (end - start).days == 7


def test_trends_detects_decline():
    with tempfile.TemporaryDirectory() as d:
        s = Storage(Path(d) / "a.sqlite3")
        anchor = _seed_two_weeks(s)
        rep = analytics.build_trends(s, categories_path=_cats(d), num_periods=3,
                                     period_days=7, anchor=anchor)
        alice = [t for t in rep["trends"] if t["user"] == "alice"][0]
        # latest week is distracting -> lower productive_ratio than the older week
        assert alice["delta"] is not None
        assert alice["latest"]["productive_ratio"] <= alice["previous"]["productive_ratio"]
        assert len(alice["sparkline"]) == 3
        s.close()


def test_team_rollup_aggregates():
    with tempfile.TemporaryDirectory() as d:
        s = Storage(Path(d) / "b.sqlite3")
        for user in ("alice", "bob"):
            for i in range(4):
                idle = 1 if (user == "bob" and i >= 2) else 0
                s.insert_sample(ts=f"2026-07-05T09:0{i}:00+00:00", duration=60.0,
                                user=user, host="h", device_label="pc",
                                app="code.exe", window_title="w",
                                url="https://github.com/x", idle=idle,
                                key_count=1, mouse_count=1, mouse_dist=1.0)
        rep = analytics.team_rollup(s, categories_path=_cats(d),
                                    since="2026-07-01T00:00:00+00:00")
        assert rep["headcount"] == 2
        assert len(rep["members"]) == 2
        # 8 samples * 60s = 480s tracked; bob idle 2 -> 120s idle
        assert rep["team_totals"]["tracked_hours"] == round(480/3600, 2)
        assert 0 <= rep["mean_individual_score"] <= 100
        # aggregate active ratio = 360/480 = 0.75
        assert rep["aggregate_active_ratio"] == 0.75
        s.close()


def test_dashboard_page_renders_selfcontained():
    with tempfile.TemporaryDirectory() as d:
        from activity_tracker.config import Config
        cfg = Config(data_dir=d, categories_file=_cats(d))
        s = Storage(cfg.db_path)  # seed the DB the dashboard will actually read
        _seed_two_weeks(s)
        s.close()
        data = dashboard.collect_data(cfg, days=30, weeks=4, period_days=7)
        html = dashboard.render_page(data)
        assert "<!doctype html>" in html
        # data embedded, not fetched
        assert "JSON.parse" in html
        # no external network references (fully self-contained page)
        low = html.lower()
        for bad in ('src="http', "<link", "cdn", "@import", "//fonts"):
            assert bad not in low
        # the payload round-trips
        assert "alice" in html
        # closing-tag safety: no raw "</script" inside the embedded JSON
        payload = html.split('type="application/json">', 1)[1].split("</script>", 1)[0]
        assert "</script" not in payload
        json.loads(payload)


if __name__ == "__main__":
    test_period_bounds_oldest_first()
    test_trends_detects_decline()
    test_team_rollup_aggregates()
    test_dashboard_page_renders_selfcontained()
    print("All analytics/dashboard tests passed.")
