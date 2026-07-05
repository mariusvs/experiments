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

## Measuring efficiency

The `efficiency` command turns raw samples into a per-user productivity view:

```bash
python -m activity_tracker efficiency --config myconfig.json --days 7
python -m activity_tracker efficiency --config myconfig.json --categories categories.json --json
```

Example output:

```
● alice   efficiency score: 88.5 / 100
    tracked 1h 15m 00s | active 1h 03m 00s (84%) | idle 0h 12m 00s
    productive share of active time: 87%
    time by category: distracting=0h 08m 00s, productive=0h 55m 00s
    focus: avg task 0h 31m 30s, longest 0h 40m 00s, 1.0 switches/active-hr
    top productive: code.exe (0h 40m 00s), github.com (0h 15m 00s)
    top distracting: youtube.com (0h 08m 00s)
```

**What the score measures.** It is a transparent, tunable blend of three ratios:

```
score = 100 × (0.40·active_ratio + 0.40·productive_ratio + 0.20·focus_factor)
```

- `active_ratio` — active time ÷ tracked time (at the machine, not idle)
- `productive_ratio` — time in productive apps/sites ÷ active time
- `focus_factor` — average uninterrupted time-on-task, capped at a target
  (default 10 min = full marks); rewards sustained work over constant
  context-switching

**What it deliberately ignores.** Keystroke and mouse counts are **not** part of
the score. Input volume rewards mashing keys and jiggling the mouse, not doing
good work — a test (`test_score_excludes_input_counts`) asserts that two people
with identical time/focus but 1 vs. 9999 keystrokes get the *same* score.

**Define "productive" for your team.** Edit `categories.example.json` (or point
`categories_file` at your own). Apps/domains are matched case-insensitively; a
URL host match beats an app match, and `distracting` beats `productive` so a
distracting site inside a work browser still counts as distracting. Anything that
matches nothing is `uncategorized` — neither rewarded nor penalized. The defaults
are a starting point, not objective truth: a browser or chat app is productive
for some roles and a distraction for others.

**Please read this before you act on a score.** These numbers reflect *time
allocation and focus at one desktop*, nothing more. They cannot see thinking,
reading on paper, whiteboard sessions, meetings away from the machine, phone
calls, mentoring, or good work done slowly and carefully. A high score is not
proof of value and a low score is not proof of slacking — someone debugging a
hard problem may look "idle," and someone who looks busy may be producing
nothing useful. Use these reports to spot *patterns worth a conversation* (a
sudden change, a team-wide tooling problem, a workload imbalance), not as an
automated performance verdict or a basis for discipline on their own. Tie pay,
promotion, or firing to a dashboard number and you will get gamed metrics, a
culture of fear, and — in several jurisdictions — legal exposure around automated
decision-making. Measure outcomes; use this to inform, not to judge.

## Trends, team roll-ups, and the dashboard

Three commands turn the collected data into something you can act on without
over-focusing on any one person on any one day.

### Trends — week over week, per person

```bash
python -m activity_tracker trends --config myconfig.json --weeks 8 --period-days 7
```

Compares each person's most recent period against the previous one and shows the
direction of travel (a small sparkline plus deltas). Change over time is far more
meaningful than an absolute number — a steady 70 is fine; a drop from 90 to 60 is
the thing worth a conversation.

```
● alice: score 90.8/100  (-9.2 vs prev)
    trend ▁█▅  (2026-06-14 → 2026-06-28)
    Δ active -23.1%, Δ productive +0.0%, Δ active-hours +0.08
```

### Team roll-up — the whole team as one unit

```bash
python -m activity_tracker team --config myconfig.json --days 7
```

Aggregates everyone into team totals, an aggregate active/productive ratio, and
the mean individual score. This is the **safer default lens**: it surfaces
workload imbalance and team-wide tooling problems without ranking individuals
against each other.

### Dashboard — a local web view

```bash
python -m activity_tracker dashboard --config myconfig.json --port 8787
# then open http://127.0.0.1:8787
```

A self-contained web page (team cards, a weekly-trend line chart, and a
per-person table with week-over-week deltas). It uses only the Python standard
library and embeds its data inline — **no external CDN, fonts, or network calls**,
so it works fully offline. A JSON version of the same data is at `/api/data.json`.

Click any person's name (or an alert's **view →**) to open a **per-person
drill-down** at `/user/<name>`: their summary cards, a daily active-hours bar
chart, a weekly score trend, and their top productive/distracting apps and sites.

> **Security:** with `auth_enabled` off (the default), the dashboard has **no
> login** — keep it bound to `127.0.0.1`. To host it for a team, turn on SSO
> (below); access is then limited to signed-in accounts in your domain / allow-list.

### Dashboard SSO (Google or Microsoft)

Let managers sign in with their existing work accounts. The dashboard uses the
OAuth2 authorization-code flow and confirms identity via the provider's
`userinfo` endpoint (no local JWT handling), issues a signed session cookie, and
**fails closed** — nobody is allowed in unless their verified email matches
`auth_allowed_domain` and/or `auth_allowed_emails`.

**1. Register an OAuth client**

- **Google:** [Google Cloud Console](https://console.cloud.google.com/) → APIs &
  Services → Credentials → *Create OAuth client ID* → *Web application*. Add your
  callback URL (e.g. `https://dashboard.example.com/auth/callback`) as an
  authorized redirect URI. Copy the client ID and secret.
- **Microsoft:** [Entra ID](https://entra.microsoft.com/) → App registrations →
  *New registration* → add the same redirect URI as a *Web* platform. Copy the
  Application (client) ID, create a client secret, and note your tenant ID.

**2. Configure**

```json
{
  "auth_enabled": true,
  "auth_provider": "google",
  "oauth_client_id": "…",
  "oauth_client_secret": "…",
  "oauth_redirect_url": "https://dashboard.example.com/auth/callback",
  "oauth_tenant": "organizations",
  "auth_allowed_domain": "scigrow.tech",
  "auth_allowed_emails": ["hr-lead@scigrow.tech"],
  "session_secret": "run: python -c \"import secrets;print(secrets.token_hex(32))\"",
  "session_ttl": 43200
}
```

- `auth_allowed_domain` — anyone with a verified `@domain` email may sign in.
- `auth_allowed_emails` — if set, **only** these exact emails get in (this
  narrows the domain rather than widening it).
- `session_secret` — a long random string; set it so sessions survive restarts.

**3. Front it with HTTPS.** The built-in server is not a hardened public web
server, and OAuth requires an `https` redirect URL (browsers need `Secure`
cookies). Run it behind a TLS reverse proxy (Caddy, nginx, Cloudflare Tunnel)
that forwards to `127.0.0.1:8787`. Then:

```bash
python -m activity_tracker dashboard --config myconfig.json
# sign-in at https://dashboard.example.com  →  /auth/login → provider → back in
```

Routes: `/auth/login`, `/auth/callback`, `/auth/logout`. Every other route
requires a valid session or you're bounced to the provider.

## Alerts

```bash
python -m activity_tracker alerts --config myconfig.json
python -m activity_tracker alerts --config myconfig.json --webhook   # also POST them
```

Flags patterns worth a human look, based on thresholds in your config (each rule
is disabled when its threshold is `0`):

| Config key | Fires when |
| --- | --- |
| `alert_weekly_score_drop` | Efficiency score fell by ≥ this many points week-over-week |
| `alert_min_active_ratio` | Active-of-tracked ratio fell below this (0–1) |
| `alert_max_distracting_ratio` | Distracting-of-active ratio rose above this (0–1) |
| `alert_min_active_hours` | Weekly active hours fell below this |

Alerts also appear as a banner at the top of the dashboard. Set
`alert_webhook_url` to receive them as an HTTPS POST (e.g. into Slack via an
incoming-webhook relay). **An alert is a prompt to look, not a verdict** — a low
week is very often leave, illness, or heads-down work that never touches the
desktop. The tool says so, in the output and on the dashboard, on purpose.

## Exporting data (CSV / PDF)

```bash
# raw samples for a spreadsheet or your own analysis
python -m activity_tracker export samples-csv out.csv --days 30

# one row per person with their efficiency summary
python -m activity_tracker export efficiency-csv team.csv --days 7

# a shareable PDF combining team roll-up, per-person, and trends
python -m activity_tracker export pdf report.pdf --days 7
```

The PDF writer is **pure standard library** (no reportlab/wkhtmltopdf), so exports
work anywhere the tool installs.

## Data retention & auto-purge

Keeping personal data no longer than necessary is a core data-protection
principle (and a legal requirement under GDPR and similar regimes). Set
`retention_days` in your config (default **90**; `0` disables). The agent purges
samples older than the window on startup and once a day, and you can run it
manually:

```bash
python -m activity_tracker purge --config myconfig.json          # uses retention_days
python -m activity_tracker purge --config myconfig.json --days 30
```

Choose the shortest window that meets your actual business need, and document
why in your monitoring policy.

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
| `categories_file` | JSON classifying apps/domains for the efficiency report |
| `retention_days` | Delete samples older than this many days (0 = keep forever) |
| `alert_*` | Alert thresholds (see the Alerts section) |

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
  __main__.py            CLI: run / report / efficiency / notice / init-config
  config.py              config dataclass + platform data dirs
  consent.py             notice text + one-time acknowledgement gate
  storage.py             SQLite schema + queries (no key-content column)
  agent.py               sampling loop + optional uploader
  report.py              aggregation, text/JSON rendering, upload
  efficiency.py          productivity scoring (time + focus, not keystrokes)
  analytics.py           week-over-week trends, team roll-ups, per-user detail
  alerts.py              threshold alerts (score drop, low active, distracting)
  retention.py           delete samples older than retention_days
  export.py              CSV + PDF export
  pdf.py                 minimal pure-stdlib PDF writer
  dashboard.py           self-contained stdlib web dashboard + per-person pages
  auth.py                OAuth2/OIDC SSO gating for the dashboard
  tray.py                optional visible tray indicator
  collectors/
    base.py              WindowInfo + platform dispatch
    windows.py           foreground window + UIA browser URL
    macos.py             frontmost app + AppleScript browser URL
    linux.py             X11 active window (Wayland-aware)
    input_activity.py    keystroke/mouse COUNTS only (never content)
tests/test_core.py       headless tests (incl. the no-content guard)
tests/test_efficiency.py efficiency scoring tests (incl. the input-volume guard)
tests/test_analytics.py  trends, team roll-up, and dashboard-page tests
tests/test_features.py   retention, alerts, CSV/PDF export, per-user drill-down
tests/test_auth.py       SSO token signing, authorization rules, route gating
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
