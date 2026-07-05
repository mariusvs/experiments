"""Tests for the efficiency analytics layer (headless)."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from activity_tracker.storage import Storage
from activity_tracker import efficiency as eff


CATS = {
    "productive": {"apps": ["code"], "domains": ["github.com"]},
    "neutral": {"apps": ["finder"], "domains": ["google.com"]},
    "distracting": {"apps": ["steam"], "domains": ["youtube.com"]},
}


def _write_cats(d):
    p = Path(d) / "cats.json"
    p.write_text(json.dumps(CATS), encoding="utf-8")
    return str(p)


def test_categorize_precedence():
    cats = eff.load_categories(None)  # empty defaults
    assert eff.categorize("code.exe", None, CATS) == "productive"
    assert eff.categorize("chrome.exe", "https://youtube.com/watch", CATS) == "distracting"
    # URL wins over app: a distracting site in an otherwise-'productive' app name
    assert eff.categorize("code-browser", "https://youtube.com", CATS) == "distracting"
    assert eff.categorize("randomapp", None, CATS) == "uncategorized"


def test_efficiency_score_and_breakdown():
    with tempfile.TemporaryDirectory() as d:
        s = Storage(Path(d) / "a.sqlite3")
        # alice: 3 productive samples (active), 1 distracting (active), 1 idle
        base = "2026-07-05T09:00:0{}+00:00"
        rows = [
            ("code.exe", None, 0),
            ("code.exe", None, 0),
            ("code.exe", None, 0),
            ("chrome.exe", "https://youtube.com/x", 0),
            ("code.exe", None, 1),  # idle
        ]
        for i, (app, url, idle) in enumerate(rows):
            s.insert_sample(
                ts=base.format(i), duration=10.0, user="alice", host="h",
                device_label="pc", app=app, window_title="w", url=url,
                idle=idle, key_count=0, mouse_count=0, mouse_dist=0.0,
            )
        cats_path = _write_cats(d)
        rep = eff.build_efficiency(s, categories_path=cats_path)
        assert len(rep["users"]) == 1
        u = rep["users"][0]
        assert u["user"] == "alice"
        # 40s active out of 50s tracked
        assert u["active_ratio"] == 0.8
        # productive 30s of 40s active
        assert u["productive_ratio"] == 0.75
        assert u["category_time"]["productive"] == "0h 00m 30s"
        assert u["category_time"]["distracting"] == "0h 00m 10s"
        assert 0 <= u["efficiency_score"] <= 100
        # There is a context switch code->chrome->(idle) : count switches among active
        assert u["focus"]["context_switches"] >= 1
        s.close()


def test_focus_stats_no_active():
    with tempfile.TemporaryDirectory() as d:
        s = Storage(Path(d) / "b.sqlite3")
        s.insert_sample(
            ts="2026-07-05T09:00:00+00:00", duration=10.0, user="bob", host="h",
            device_label="pc", app="code.exe", window_title="w", url=None,
            idle=1, key_count=0, mouse_count=0, mouse_dist=0.0,
        )
        rep = eff.build_efficiency(s, categories_path=None)
        u = rep["users"][0]
        assert u["active_ratio"] == 0.0
        assert u["efficiency_score"] == 0.0  # nothing active -> zero on all fronts
        s.close()


def test_score_excludes_input_counts():
    """Two users with identical time/focus but wildly different keystroke counts
    must get the SAME score — proving input volume does not affect efficiency."""
    with tempfile.TemporaryDirectory() as d:
        s = Storage(Path(d) / "c.sqlite3")
        for user, keys in (("quiet", 1), ("masher", 9999)):
            for i in range(3):
                s.insert_sample(
                    ts=f"2026-07-05T09:0{i}:00+00:00", duration=10.0, user=user,
                    host="h", device_label="pc", app="code.exe", window_title="w",
                    url=None, idle=0, key_count=keys, mouse_count=keys, mouse_dist=keys,
                )
        rep = eff.build_efficiency(s, categories_path=_write_cats(d))
        scores = {u["user"]: u["efficiency_score"] for u in rep["users"]}
        assert scores["quiet"] == scores["masher"]
        s.close()


if __name__ == "__main__":
    test_categorize_precedence()
    test_efficiency_score_and_breakdown()
    test_focus_stats_no_active()
    test_score_excludes_input_counts()
    print("All efficiency tests passed.")
