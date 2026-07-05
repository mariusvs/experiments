"""Tests for retention, alerts, export (CSV/PDF), and per-user drill-down."""

import csv
import json
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from activity_tracker.storage import Storage
from activity_tracker.config import Config
from activity_tracker import retention, alerts, export, pdf, analytics, dashboard

CATS = {
    "productive": {"apps": ["code"], "domains": ["github.com"]},
    "neutral": {"apps": [], "domains": []},
    "distracting": {"apps": ["steam"], "domains": ["youtube.com"]},
}


def _cats(d):
    p = Path(d) / "cats.json"
    p.write_text(json.dumps(CATS), encoding="utf-8")
    return str(p)


def _sample(s, **kw):
    base = dict(duration=60.0, host="h", device_label="pc", window_title="w",
                url=None, idle=0, key_count=1, mouse_count=1, mouse_dist=1.0)
    base.update(kw)
    s.insert_sample(**base)


# ---------------------------------------------------------------- retention
def test_retention_purges_old_only():
    with tempfile.TemporaryDirectory() as d:
        s = Storage(Path(d) / "a.sqlite3")
        now = datetime(2026, 7, 5, tzinfo=timezone.utc)
        _sample(s, ts=(now - timedelta(days=200)).isoformat(), user="a", app="code.exe")
        _sample(s, ts=(now - timedelta(days=5)).isoformat(), user="a", app="code.exe")
        removed = retention.purge(s, 90, now=now)
        assert removed == 1
        assert len(s.query()) == 1  # the recent one survives
        # disabled retention removes nothing
        assert retention.purge(s, 0, now=now) == 0
        s.close()


# ------------------------------------------------------------------- alerts
def test_alerts_score_drop_and_distracting():
    with tempfile.TemporaryDirectory() as d:
        s = Storage(Path(d) / "b.sqlite3")
        anchor = datetime(2026, 7, 5, 12, tzinfo=timezone.utc)
        # previous week: productive (high score)
        prev = anchor - timedelta(days=9)
        for i in range(8):
            _sample(s, ts=(prev + timedelta(minutes=i)).isoformat(), user="alice",
                    app="code.exe", url="https://github.com/x")
        # current week: distracting (low score)
        cur = anchor - timedelta(days=2)
        for i in range(8):
            _sample(s, ts=(cur + timedelta(minutes=i)).isoformat(), user="alice",
                    app="chrome.exe", url="https://youtube.com/x")
        cfg = Config(alert_weekly_score_drop=20.0, alert_max_distracting_ratio=0.5)
        found = alerts.evaluate(s, cfg, categories_path=_cats(d), anchor=anchor)
        rules = {a["rule"] for a in found}
        assert "score_drop" in rules
        assert "high_distracting" in rules
        # sorted most-severe first
        assert found[0]["severity"] in ("high", "medium")
        s.close()


def test_alerts_disabled_thresholds():
    with tempfile.TemporaryDirectory() as d:
        s = Storage(Path(d) / "c.sqlite3")
        anchor = datetime(2026, 7, 5, tzinfo=timezone.utc)
        _sample(s, ts=(anchor - timedelta(days=1)).isoformat(), user="a",
                app="chrome.exe", url="https://youtube.com/x")
        cfg = Config(alert_weekly_score_drop=0, alert_min_active_ratio=0,
                     alert_max_distracting_ratio=0, alert_min_active_hours=0)
        assert alerts.evaluate(s, cfg, categories_path=_cats(d), anchor=anchor) == []
        s.close()


# ------------------------------------------------------------------- export
def test_export_samples_csv():
    with tempfile.TemporaryDirectory() as d:
        s = Storage(Path(d) / "e.sqlite3")
        _sample(s, ts="2026-07-05T09:00:00+00:00", user="a", app="code.exe",
                url="https://github.com/x")
        out = Path(d) / "samples.csv"
        n = export.export_samples_csv(s, str(out))
        assert n == 1
        rows = list(csv.DictReader(out.open()))
        assert rows[0]["user"] == "a"
        assert rows[0]["app"] == "code.exe"
        # no keystroke-content column ever
        assert "key_count" in rows[0] and not any(
            k in rows[0] for k in ("key_text", "content", "typed"))
        s.close()


def test_export_pdf_is_valid():
    with tempfile.TemporaryDirectory() as d:
        s = Storage(Path(d) / "p.sqlite3")
        now = datetime.now(timezone.utc)
        for i in range(5):
            _sample(s, ts=(now - timedelta(minutes=i)).isoformat(), user="alice",
                    app="code.exe", url="https://github.com/x")
        cfg = Config(categories_file=_cats(d), organization="Acme")
        out = Path(d) / "report.pdf"
        export.export_pdf(s, str(out), cfg, days=30)
        data = out.read_bytes()
        assert data.startswith(b"%PDF-1.")
        assert data.rstrip().endswith(b"%%EOF")
        assert b"xref" in data and b"trailer" in data
        assert len(data) > 400
        s.close()


def test_pdf_paginates_and_escapes():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "multi.pdf"
        lines = [f"line {i} with (parens) and \\backslash" for i in range(200)]
        pdf.text_to_pdf(lines, str(out), title="Big Report")
        data = out.read_bytes()
        # more than one page object for 200 lines
        assert data.count(b"/Type /Page ") >= 2
        assert data.startswith(b"%PDF")
        # unicode is sanitized, file stays valid latin-1 bytes
        pdf.text_to_pdf(["sparkline ▁█▅ here"], str(out))
        assert (Path(d) / "multi.pdf").read_bytes().startswith(b"%PDF")


# --------------------------------------------------------- per-user drill-down
def test_user_detail_and_page():
    with tempfile.TemporaryDirectory() as d:
        cfg = Config(data_dir=d, categories_file=_cats(d))
        s = Storage(cfg.db_path)
        now = datetime.now(timezone.utc)
        for day in range(3):
            for i in range(6):
                _sample(s, ts=(now - timedelta(days=day, minutes=i)).isoformat(),
                        user="alice", app="code.exe", url="https://github.com/x")
        s.close()
        detail = dashboard.collect_user_data(cfg, "alice", days=30, weeks=4, period_days=7)
        assert detail["user"] == "alice"
        assert detail["summary"]["efficiency_score"] > 0
        assert len(detail["daily"]) == 3
        assert detail["top_productive"]  # github.com should be there
        html = dashboard.render_user_page(detail)
        assert "<!doctype html>" in html
        assert "alice" in html
        # self-contained
        for bad in ('src="http', "<link", "cdn", "@import"):
            assert bad not in html.lower()
        payload = html.split('type="application/json">', 1)[1].split("</script>", 1)[0]
        json.loads(payload)


if __name__ == "__main__":
    test_retention_purges_old_only()
    test_alerts_score_drop_and_distracting()
    test_alerts_disabled_thresholds()
    test_export_samples_csv()
    test_export_pdf_is_valid()
    test_pdf_paginates_and_escapes()
    test_user_detail_and_page()
    print("All feature tests passed.")
