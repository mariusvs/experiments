"""Self-contained local web dashboard.

Uses only the standard library (`http.server`). The page is fully self-contained:
data is embedded as JSON and charts are drawn with inline SVG + vanilla JS, so it
works offline with no CDN, fonts, or external requests. Intended to be bound to
localhost for a manager to view; put it behind proper auth/VPN before exposing it.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from . import analytics, efficiency
from .config import Config
from .storage import Storage
from . import report as report_mod


def collect_data(config: Config, days: int, weeks: int, period_days: int) -> dict:
    """Build the full payload the dashboard renders."""
    cats = config.categories_file or None
    storage = Storage(config.db_path)
    try:
        since = report_mod.default_since(days)
        eff = efficiency.build_efficiency(storage, categories_path=cats, since=since)
        team = analytics.team_rollup(storage, categories_path=cats, since=since)
        trends = analytics.build_trends(
            storage, categories_path=cats, num_periods=weeks, period_days=period_days)
    finally:
        storage.close()
    return {
        "organization": config.organization,
        "range_days": days,
        "efficiency": eff,
        "team": team,
        "trends": trends,
    }


def render_page(data: dict) -> str:
    payload = json.dumps(data).replace("</", "<\\/")  # avoid closing the script tag
    return _PAGE_TEMPLATE.replace("__DATA__", payload)


class _Handler(BaseHTTPRequestHandler):
    config: Config
    days: int
    weeks: int
    period_days: int

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # Local-only tool; a conservative CSP that permits our inline SVG/JS.
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'unsafe-inline'; "
                         "script-src 'unsafe-inline'; img-src 'self' data:")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 (http.server API)
        if self.path in ("/", "/index.html"):
            data = collect_data(self.config, self.days, self.weeks, self.period_days)
            self._send(200, render_page(data).encode("utf-8"), "text/html; charset=utf-8")
        elif self.path.startswith("/api/data.json"):
            data = collect_data(self.config, self.days, self.weeks, self.period_days)
            self._send(200, json.dumps(data, indent=2).encode("utf-8"),
                       "application/json; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")

    def log_message(self, *args):  # keep the console quiet
        pass


def serve(config: Config, host: str = "127.0.0.1", port: int = 8787,
          days: int = 7, weeks: int = 8, period_days: int = 7) -> int:
    handler = type("Handler", (_Handler,), {
        "config": config, "days": days, "weeks": weeks, "period_days": period_days,
    })
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"Dashboard on http://{host}:{port}  (Ctrl+C to stop)")
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("WARNING: bound to a non-local address. Put this behind auth/VPN — "
              "it exposes staff activity data with no login.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard.")
    finally:
        httpd.server_close()
    return 0


# ---------------------------------------------------------------------- template
# Single self-contained page. `__DATA__` is replaced with the JSON payload.
_PAGE_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Staff Activity Dashboard</title>
<style>
  :root {
    --bg:#0f1216; --panel:#171b21; --ink:#e7edf3; --muted:#8b97a5;
    --line:#252b33; --good:#2ecc71; --warn:#f1c40f; --bad:#e74c3c; --accent:#4aa3ff;
  }
  @media (prefers-color-scheme: light) {
    :root { --bg:#f5f7fa; --panel:#fff; --ink:#1a2028; --muted:#5b6672;
            --line:#e4e9ef; }
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
    font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }
  header { padding:20px 24px; border-bottom:1px solid var(--line); }
  h1 { margin:0; font-size:18px; }
  .sub { color:var(--muted); font-size:12px; margin-top:4px; }
  main { padding:20px 24px; max-width:1100px; margin:0 auto; display:grid; gap:20px; }
  .panel { background:var(--panel); border:1px solid var(--line); border-radius:10px;
    padding:16px 18px; }
  .panel h2 { margin:0 0 12px; font-size:14px; letter-spacing:.02em;
    text-transform:uppercase; color:var(--muted); }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; }
  .card { background:var(--bg); border:1px solid var(--line); border-radius:8px; padding:12px; }
  .card .big { font-size:24px; font-weight:600; }
  .card .lbl { color:var(--muted); font-size:12px; }
  table { width:100%; border-collapse:collapse; }
  th,td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); }
  th { color:var(--muted); font-weight:600; font-size:12px; }
  td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
  .bar { height:8px; border-radius:4px; background:var(--line); overflow:hidden; }
  .bar > span { display:block; height:100%; }
  .delta-up { color:var(--good); } .delta-down { color:var(--bad); }
  .scorepill { display:inline-block; min-width:44px; text-align:center; padding:2px 8px;
    border-radius:999px; font-weight:600; color:#08110a; }
  .muted { color:var(--muted); }
  .note { color:var(--muted); font-size:12px; border-top:1px solid var(--line);
    padding-top:12px; margin-top:8px; }
  .row { overflow-x:auto; }
  svg { display:block; }
</style>
</head>
<body>
<header>
  <h1 id="title">Staff Activity Dashboard</h1>
  <div class="sub" id="subtitle"></div>
</header>
<main>
  <section class="panel">
    <h2>Team roll-up</h2>
    <div class="cards" id="teamCards"></div>
    <div id="catBars" style="margin-top:14px"></div>
  </section>

  <section class="panel">
    <h2>Weekly trend (efficiency score)</h2>
    <div class="row" id="trendChart"></div>
  </section>

  <section class="panel">
    <h2>Per-person — this range</h2>
    <div class="row"><table id="peopleTable"></table></div>
    <div class="note" id="disclaimer"></div>
  </section>
</main>

<script id="payload" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('payload').textContent);
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, c => (
  {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const scoreColor = (s) => s >= 75 ? '#2ecc71' : s >= 50 ? '#f1c40f' : '#e74c3c';

function header() {
  const org = DATA.organization || 'Your organization';
  $('title').textContent = `${org} — Activity Dashboard`;
  $('subtitle').textContent =
    `Last ${DATA.range_days} days · ${DATA.team.headcount} people · `
    + `${DATA.team.range.samples} samples`;
}

function card(big, lbl, color) {
  return `<div class="card"><div class="big" style="color:${color||'inherit'}">`
       + `${esc(big)}</div><div class="lbl">${esc(lbl)}</div></div>`;
}

function teamCards() {
  const t = DATA.team;
  $('teamCards').innerHTML = [
    card(t.mean_individual_score + '/100', 'mean individual score',
         scoreColor(t.mean_individual_score)),
    card((t.aggregate_active_ratio*100).toFixed(0) + '%', 'aggregate active time'),
    card((t.aggregate_productive_ratio*100).toFixed(0) + '%', 'productive share of active'),
    card(t.team_totals.active_hours + 'h', 'total active hours'),
  ].join('');

  const cats = t.category_hours || {};
  const order = ['productive','neutral','uncategorized','distracting'];
  const colors = {productive:'#2ecc71',neutral:'#7f8c8d',
                  uncategorized:'#95a5a6',distracting:'#e74c3c'};
  const total = Object.values(cats).reduce((a,b)=>a+b,0) || 1;
  let html = '<div class="lbl muted" style="margin-bottom:6px">team time by category</div>'
           + '<div class="bar" style="height:14px">';
  order.forEach(k => { if (cats[k]) {
    html += `<span style="width:${(cats[k]/total*100).toFixed(1)}%;`
          + `background:${colors[k]};display:inline-block;height:100%"`
          + ` title="${k}: ${cats[k]}h"></span>`;
  }});
  html += '</div><div class="lbl muted" style="margin-top:6px">' +
    order.filter(k=>cats[k]).map(k =>
      `<span style="color:${colors[k]}">■</span> ${k} ${cats[k]}h`).join(' &nbsp; ')
    + '</div>';
  $('catBars').innerHTML = html;
}

function trendChart() {
  const periods = DATA.trends.periods;
  const trends = DATA.trends.trends;
  if (!trends.length) { $('trendChart').innerHTML = '<p class="muted">No data.</p>'; return; }
  const W = Math.max(520, periods.length * 90), H = 240, padL = 36, padB = 28, padT = 12;
  const plotW = W - padL - 12, plotH = H - padB - padT;
  const x = i => padL + (periods.length === 1 ? plotW/2 : i/(periods.length-1)*plotW);
  const y = v => padT + plotH - (v/100)*plotH;
  const palette = ['#4aa3ff','#2ecc71','#f1c40f','#e67e22','#9b59b6','#1abc9c','#e74c3c'];
  let svg = `<svg width="${W}" height="${H}" role="img" aria-label="weekly score trend">`;
  [0,25,50,75,100].forEach(g => {
    svg += `<line x1="${padL}" y1="${y(g)}" x2="${W-12}" y2="${y(g)}" `
        + `stroke="var(--line)"/><text x="4" y="${y(g)+4}" fill="var(--muted)" `
        + `font-size="10">${g}</text>`;
  });
  periods.forEach((p,i) => {
    svg += `<text x="${x(i)}" y="${H-8}" fill="var(--muted)" font-size="10" `
        + `text-anchor="middle">${esc(p.slice(5))}</text>`;
  });
  trends.forEach((t,ti) => {
    const col = palette[ti % palette.length];
    const pts = t.sparkline.map((v,i)=>`${x(i)},${y(v)}`).join(' ');
    svg += `<polyline points="${pts}" fill="none" stroke="${col}" stroke-width="2"/>`;
    t.sparkline.forEach((v,i)=>{ svg += `<circle cx="${x(i)}" cy="${y(v)}" r="2.5" `
        + `fill="${col}"><title>${esc(t.user)} ${p_label(periods,i)}: ${v}</title></circle>`; });
  });
  svg += '</svg>';
  const legend = trends.map((t,ti)=>`<span style="color:${palette[ti%palette.length]}">■</span> `
      + esc(t.user)).join(' &nbsp; ');
  $('trendChart').innerHTML = svg + `<div class="lbl muted" style="margin-top:8px">${legend}</div>`;
}
function p_label(periods,i){ return periods[i]; }

function peopleTable() {
  const users = DATA.efficiency.users;
  const trendByUser = {};
  DATA.trends.trends.forEach(t => trendByUser[t.user] = t.delta);
  let html = '<thead><tr><th>Person</th><th class="num">Score</th>'
    + '<th>vs prev wk</th><th class="num">Active</th><th class="num">Idle</th>'
    + '<th class="num">Productive</th><th>Focus (avg task)</th></tr></thead><tbody>';
  users.forEach(u => {
    const d = trendByUser[u.user];
    let deltaCell = '<span class="muted">—</span>';
    if (d) {
      const up = d.score >= 0;
      deltaCell = `<span class="${up?'delta-up':'delta-down'}">`
        + `${up?'▲':'▼'} ${Math.abs(d.score)}</span>`;
    }
    html += `<tr><td>${esc(u.user)}</td>`
      + `<td class="num"><span class="scorepill" style="background:${scoreColor(u.efficiency_score)}">`
      + `${u.efficiency_score}</span></td>`
      + `<td>${deltaCell}</td>`
      + `<td class="num">${esc(u.active_time)}</td>`
      + `<td class="num">${esc(u.idle_time)}</td>`
      + `<td class="num">${(u.productive_ratio*100).toFixed(0)}%</td>`
      + `<td>${esc(u.focus.avg_session)}</td></tr>`;
  });
  html += '</tbody>';
  $('peopleTable').innerHTML = html;
}

function disclaimer() {
  $('disclaimer').textContent =
    'These scores reflect desktop time allocation and focus — not effort, thinking, '
    + 'meetings away from the machine, or output quality. Use them to start '
    + 'conversations and spot patterns, not as an automated performance verdict.';
}

header(); teamCards(); trendChart(); peopleTable(); disclaimer();
</script>
</body>
</html>
"""
