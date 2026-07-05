# Staff Activity Tracker

A transparent, consent-based activity tracker for **company-owned** devices,
running on **macOS, Linux, and Windows**. It records the signals most teams
actually need for productivity, security, and compliance:

- **Application in focus** and **time spent** per app
- **Browser URLs / page titles** visited
- **Input activity level** — counts of keystrokes and mouse movement, used to
  distinguish *active* from *idle* time
- **Active vs. idle time** per user and per device

It stores everything locally in SQLite and can optionally forward batches to a
central endpoint you control.

---

## ⚠️ Important: what this tool does and does not do

This is an **activity monitor**, not a **keylogger**, and that distinction is
deliberate:

| Recorded | Not recorded |
| --- | --- |
| How many keystrokes per interval (a number) | **Which keys / what text was typed** |
| Mouse movement distance and click counts | Screen contents / screenshots |
| Foreground app name + window title | Camera / microphone |
| Browser URL or host | Clipboard contents, passwords, message bodies |

**Why counts and not content?** Capturing the actual text someone types means
capturing their passwords, private messages, 2FA codes, and banking details.
That specific capability is what turns monitoring software into spyware, and in
most jurisdictions it is treated as unlawful interception/wiretapping **even on
company equipment**. The database schema has no column that can hold typed
content, and there is a test (`test_no_keystroke_content_stored`) that enforces
this. If you need keystroke *content* capture, this tool is intentionally not
that, and you should get written legal advice before pursuing it.

### Your legal & ethical responsibilities before deploying

Monitoring employees is lawful in many places **only if** you do it correctly.
You are responsible for meeting the rules in your jurisdiction, which commonly
include:

1. **Notice & consent.** Tell staff clearly, in writing, what is monitored and
   why (an acceptable-use / monitoring policy). Several regions (EU/UK under
   GDPR, parts of the US, and others) require this; some require explicit
   consent. This tool shows a notice and records an acknowledgement on each
   device to help — but that does not replace your own policy and legal review.
2. **Company-owned devices and work accounts only.** Do not deploy on personal
   devices.
3. **Legitimate purpose & proportionality.** Collect only what you need, keep it
   only as long as you need it, and restrict who can see it.
4. **Transparency, not stealth.** This tool ships a visible tray indicator and a
   startup notice on purpose. Do not attempt to hide it.

This README is not legal advice. Get sign-off from someone qualified before
rolling it out.

---

## Install

Requires Python 3.9+.

```bash
# core (all platforms)
pip install psutil pynput

# optional visible tray indicator
pip install pystray Pillow

# then install the block for the device's OS:
# macOS:
pip install pyobjc-framework-Cocoa pyobjc-framework-Quartz
# Linux (X11):
pip install python-xlib          # or install system pkgs: xdotool, x11-utils
# Windows:
pip install pywin32 uiautomation
```

Or, from this directory:

```bash
pip install .            # core
pip install ".[macos]"   # or .[linux] / .[windows] / .[tray]
```

### Platform notes

- **Windows** — Foreground app/title work out of the box. Reading the exact
  browser **URL** from the address bar needs `uiautomation`; without it you
  still get the browser window title (usually the page name).
- **macOS** — Grant the running terminal/app **Accessibility** and
  **Automation** permissions (System Settings → Privacy & Security). URL reads
  from Safari/Chrome/Edge/Brave use AppleScript, which prompts the user the
  first time — keeping it transparent. `pynput` also needs Input Monitoring
  permission.
- **Linux** — Full window/title support under **X11**. Under **Wayland**,
  cross-window inspection is blocked by design; the tracker reports
  `wayland-restricted` for the window and still records input activity. URLs are
  parsed from the window title where the browser includes them.

---

## Usage

```bash
# 1. Create a config file and edit it
python -m activity_tracker init-config myconfig.json

# 2. Show exactly what will be recorded (share this with staff)
python -m activity_tracker notice --config myconfig.json

# 3. Start monitoring (prompts for consent on first run)
python -m activity_tracker run --config myconfig.json

# In a centrally-managed rollout where consent is handled by signed policy:
python -m activity_tracker run --config myconfig.json --yes

# 4. See a report from the locally collected data
python -m activity_tracker report --config myconfig.json --days 1
python -m activity_tracker report --config myconfig.json --days 7 --json
```

If installed as a package, the same commands are available via the
`staff-activity-tracker` console script.

### Running it as a background service

- **Windows** — wrap `python -m activity_tracker run --config C:\path\myconfig.json --yes`
  in a Scheduled Task (at logon) or a service via NSSM.
- **macOS** — a per-user LaunchAgent plist calling the same command.
- **Linux** — a systemd **user** service (`systemctl --user`).

Keep it a *user* session service so it runs inside the logged-in desktop session
(needed to read the foreground window).

---

## Configuration

`init-config` writes a JSON file; see `config.example.json`. Key options:

| Key | Meaning |
| --- | --- |
| `sample_interval` | Seconds between samples (default 5) |
| `idle_threshold` | Seconds of no input before "idle" (default 60) |
| `collect_active_window` / `collect_input_activity` / `collect_urls` | Toggle each signal independently |
| `data_dir` | Where the SQLite DB lives (blank = per-user default) |
| `require_consent` | Enforce the consent gate before collecting |
| `show_tray_indicator` | Show the visible "monitoring active" tray icon |
| `upload_url` / `upload_token` / `upload_interval` | Optional central collection endpoint (HTTPS POST, Bearer auth) |
| `organization` / `device_label` | Labels attached to records/reports |

### Central collection (optional)

Set `upload_url` to an HTTPS endpoint you run. The agent POSTs un-uploaded rows
as JSON:

```json
{
  "organization": "Acme",
  "device_label": "reception-pc-01",
  "records": [ { "ts": "...", "app": "chrome.exe", "url": "https://...", "key_count": 12, ... } ]
}
```

Rows are marked uploaded once the endpoint returns 2xx. Build the receiving
server to your own retention and access-control requirements.

---

## How it's structured

```
activity_tracker/
  __main__.py            CLI: run / report / notice / init-config
  config.py              config dataclass + platform data dirs
  consent.py             notice text + one-time acknowledgement gate
  storage.py             SQLite schema + queries (no key-content column)
  agent.py               sampling loop + optional uploader
  report.py              aggregation, text/JSON rendering, upload
  tray.py                optional visible tray indicator
  collectors/
    base.py              WindowInfo + platform dispatch
    windows.py           foreground window + UIA browser URL
    macos.py             frontmost app + AppleScript browser URL
    linux.py             X11 active window (Wayland-aware)
    input_activity.py    keystroke/mouse COUNTS only (never content)
tests/test_core.py       headless tests (incl. the no-content guard)
```

## Tests

```bash
python tests/test_core.py      # or: pytest tests/
```

The tests run headless (no display or input device required) and include a guard
that fails if anyone ever adds a column capable of storing typed content.

## License

MIT. Use of this software to monitor people is governed by the laws of your
jurisdiction; complying with them is your responsibility, not the software's.
