"""Core tests that run headless (no display, no input device needed)."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from activity_tracker.config import Config
from activity_tracker.storage import Storage
from activity_tracker import report as report_mod
from activity_tracker.collectors.base import WindowInfo
from activity_tracker.collectors.input_activity import InputActivityMonitor
from activity_tracker import consent


def test_config_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "c.json"
        c = Config(organization="Acme", device_label="pc-1")
        c.save(p)
        loaded = Config.load(p)
        assert loaded.organization == "Acme"
        assert loaded.device_label == "pc-1"
        assert loaded.data_dir  # never empty after load


def test_storage_and_report():
    with tempfile.TemporaryDirectory() as d:
        s = Storage(Path(d) / "activity.sqlite3")
        s.insert_sample(
            ts="2026-07-05T09:00:00+00:00", duration=5.0, user="alice", host="h",
            device_label="pc-1", app="Code.exe", window_title="main.py",
            url="https://docs.python.org/3/library/sqlite3.html", idle=0,
            key_count=12, mouse_count=8, mouse_dist=340.5,
        )
        s.insert_sample(
            ts="2026-07-05T09:00:05+00:00", duration=5.0, user="alice", host="h",
            device_label="pc-1", app="chrome.exe", window_title="Gmail",
            url="https://mail.google.com/mail/u/0", idle=1,
            key_count=0, mouse_count=0, mouse_dist=0.0,
        )
        rep = report_mod.build_report(s)
        assert rep["range"]["samples"] == 2
        assert rep["totals"]["keystrokes"] == 12
        apps = {a["name"] for a in rep["top_apps"]}
        assert {"Code.exe", "chrome.exe"} <= apps
        hosts = {h["name"] for h in rep["top_sites"]}
        assert "docs.python.org" in hosts
        assert "mail.google.com" in hosts
        # Active vs idle split
        assert rep["totals"]["active_time"] == "0h 00m 05s"
        assert rep["totals"]["idle_time"] == "0h 00m 05s"
        s.close()


def test_no_keystroke_content_stored():
    """Guard rail: the schema must not have any column that could hold key text."""
    with tempfile.TemporaryDirectory() as d:
        s = Storage(Path(d) / "a.sqlite3")
        cols = [r[1] for r in s._conn.execute("PRAGMA table_info(samples)").fetchall()]
        for forbidden in ("key_text", "keystrokes_text", "typed", "content", "clipboard"):
            assert forbidden not in cols
        assert "key_count" in cols  # we keep counts only
        s.close()


def test_input_monitor_counts_only():
    m = InputActivityMonitor()
    # Simulate events without a real device.
    m._on_key_press("secret-password-should-be-ignored")
    m._on_key_press("x")
    m._on_move(0, 0)
    m._on_move(3, 4)  # distance 5
    snap = m.snapshot_and_reset()
    assert snap.key_count == 2
    assert snap.mouse_dist == 5.0
    # After reset, counters are clear.
    assert m.snapshot_and_reset().key_count == 0


def test_url_host_helper():
    w = WindowInfo(app="chrome", title="t", url="https://example.com/path?q=1")
    assert w.url_host() == "https://example.com"


def test_consent_gate(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        dd = Path(d)
        assert not consent.has_consented(dd)
        rec = consent.record_consent(dd, method="test")
        assert consent.has_consented(dd)
        assert rec["method"] == "test"


if __name__ == "__main__":
    test_config_roundtrip()
    test_storage_and_report()
    test_no_keystroke_content_stored()
    test_input_monitor_counts_only()
    test_url_host_helper()
    test_consent_gate()
    print("All core tests passed.")
