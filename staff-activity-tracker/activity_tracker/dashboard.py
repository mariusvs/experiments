"""Self-contained local web dashboard.

Uses only the standard library (`http.server`). The page is fully self-contained:
data is embedded as JSON and charts are drawn with inline SVG + vanilla JS, so it
works offline with no CDN, fonts, or external requests. Intended to be bound to
localhost for a manager to view; put it behind proper auth/VPN before exposing it.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from . import alerts as alerts_mod
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
        alerts = alerts_mod.evaluate(storage, config, categories_path=cats,
                                     period_days=period_days)
    finally:
        storage.close()
    return {
        "organization": config.organization,
        "range_days": days,
        "efficiency": eff,
        "team": team,
        "trends": trends,
        "alerts": alerts,
    }


def collect_user_data(config: Config, user: str, days: int, weeks: int,
                      period_days: int) -> dict:
    cats = config.categories_file or None
    storage = Storage(config.db_path)
    try:
        since = report_mod.default_since(days)
        detail = analytics.user_detail(
            storage, user, categories_path=cats, since=since,
            num_periods=weeks, period_days=period_days)
    finally:
        storage.close()
    detail["organization"] = config.organization
    detail["range_days"] = days
    return detail


def render_page(data: dict) -> str:
    payload = json.dumps(data).replace("</", "<\\/")  # avoid closing the script tag
    return _PAGE_TEMPLATE.replace("__DATA__", payload)


def render_user_page(data: dict) -> str:
    payload = json.dumps(data).replace("</", "<\\/")
    return _USER_TEMPLATE.replace("__DATA__", payload)


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
        route = urlparse(self.path).path
        if route in ("/", "/index.html"):
            data = collect_data(self.config, self.days, self.weeks, self.period_days)
            self._send(200, render_page(data).encode("utf-8"), "text/html; charset=utf-8")
        elif route == "/api/data.json":
            data = collect_data(self.config, self.days, self.weeks, self.period_days)
            self._send(200, json.dumps(data, indent=2).encode("utf-8"),
                       "application/json; charset=utf-8")
        elif route.startswith("/user/"):
            user = unquote(route[len("/user/"):])
            data = collect_user_data(self.config, user, self.days, self.weeks,
                                     self.period_days)
            self._send(200, render_user_page(data).encode("utf-8"),
                       "text/html; charset=utf-8")
        elif route == "/api/user.json":
            from urllib.parse import parse_qs
            q = parse_qs(urlparse(self.path).query)
            user = (q.get("u") or [""])[0]
            data = collect_user_data(self.config, user, self.days, self.weeks,
                                     self.period_days)
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
  <section class="panel" id="alertsPanel" style="display:none">
    <h2>Alerts</h2>
    <div id="alerts"></div>
  </section>

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

function alertsPanel() {
  const alerts = DATA.alerts || [];
  if (!alerts.length) return;
  $('alertsPanel').style.display = '';
  const dot = {high:'#e74c3c', medium:'#f1c40f', low:'#95a5a6'};
  $('alerts').innerHTML = alerts.map(a =>
    `<div style="padding:6px 0;border-bottom:1px solid var(--line)">`
    + `<span style="color:${dot[a.severity]||'#888'}">●</span> `
    + `<b>${esc(a.user)}</b> `
    + `<span class="muted">[${esc(a.severity)}]</span> ${esc(a.message)} `
    + `<a href="/user/${encodeURIComponent(a.user)}">view →</a></div>`
  ).join('')
  + '<div class="note">An alert is a prompt to look, not a verdict — a low week '
  + 'is often leave, illness, or heads-down work that never reaches the desktop.</div>';
}

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
    html += `<tr><td><a href="/user/${encodeURIComponent(u.user)}">${esc(u.user)}</a></td>`
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

header(); alertsPanel(); teamCards(); trendChart(); peopleTable(); disclaimer();
</script>
</body>
</html>
"""

# ----------------------------------------------------------------- user template
_USER_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Activity — person detail</title>
<style>
  :root { --bg:#0f1216; --panel:#171b21; --ink:#e7edf3; --muted:#8b97a5;
    --line:#252b33; }
  @media (prefers-color-scheme: light) {
    :root { --bg:#f5f7fa; --panel:#fff; --ink:#1a2028; --muted:#5b6672; --line:#e4e9ef; }
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
    font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }
  header { padding:20px 24px; border-bottom:1px solid var(--line); }
  h1 { margin:0; font-size:18px; }
  a { color:#4aa3ff; text-decoration:none; }
  .sub { color:var(--muted); font-size:12px; margin-top:4px; }
  main { padding:20px 24px; max-width:1000px; margin:0 auto; display:grid; gap:20px; }
  .panel { background:var(--panel); border:1px solid var(--line); border-radius:10px;
    padding:16px 18px; }
  .panel h2 { margin:0 0 12px; font-size:14px; text-transform:uppercase;
    letter-spacing:.02em; color:var(--muted); }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:12px; }
  .card { background:var(--bg); border:1px solid var(--line); border-radius:8px; padding:12px; }
  .card .big { font-size:22px; font-weight:600; }
  .card .lbl { color:var(--muted); font-size:12px; }
  table { width:100%; border-collapse:collapse; }
  th,td { text-align:left; padding:7px 10px; border-bottom:1px solid var(--line); }
  th { color:var(--muted); font-size:12px; }
  td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
  .cols { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
  .muted { color:var(--muted); }
  .note { color:var(--muted); font-size:12px; border-top:1px solid var(--line);
    padding-top:12px; margin-top:8px; }
  .row { overflow-x:auto; }
  @media (max-width:640px){ .cols{ grid-template-columns:1fr; } }
</style>
</head>
<body>
<header>
  <a href="/">← all staff</a>
  <h1 id="title"></h1>
  <div class="sub" id="subtitle"></div>
</header>
<main>
  <section class="panel"><h2>Summary</h2><div class="cards" id="cards"></div></section>
  <section class="panel"><h2>Daily active hours</h2><div class="row" id="dailyChart"></div></section>
  <section class="panel"><h2>Weekly score trend</h2><div class="row" id="weekChart"></div></section>
  <section class="cols">
    <div class="panel"><h2>Top productive</h2><div id="topProd"></div></div>
    <div class="panel"><h2>Top distracting</h2><div id="topDist"></div></div>
  </section>
  <section class="panel"><div class="note" id="disclaimer"></div></section>
</main>

<script id="payload" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('payload').textContent);
const $ = (id)=>document.getElementById(id);
const esc=(s)=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const scoreColor=(s)=>s>=75?'#2ecc71':s>=50?'#f1c40f':'#e74c3c';

$('title').textContent = D.user;
$('subtitle').textContent = `${D.organization||''}  ·  last ${D.range_days} days  ·  ${D.range.samples} samples`;

function cards() {
  if (!D.summary) { $('cards').innerHTML = '<p class="muted">No data in range.</p>'; return; }
  const s = D.summary;
  const c=(big,lbl,col)=>`<div class="card"><div class="big" style="color:${col||'inherit'}">`
    +`${esc(big)}</div><div class="lbl">${esc(lbl)}</div></div>`;
  $('cards').innerHTML = [
    c(s.efficiency_score+'/100','efficiency score',scoreColor(s.efficiency_score)),
    c(s.active_time,'active'),
    c(s.idle_time,'idle'),
    c((s.productive_ratio*100).toFixed(0)+'%','productive of active'),
    c(s.focus.avg_session,'avg time-on-task'),
  ].join('');
}

function barChart(el, items, valKey, labelKey, color) {
  if (!items.length) { $(el).innerHTML='<p class="muted">No data.</p>'; return; }
  const W=Math.max(480,items.length*54), H=200, padB=34, padT=10, padL=30;
  const plotH=H-padB-padT, plotW=W-padL-10;
  const max=Math.max(...items.map(d=>d[valKey]),0.01);
  const bw=plotW/items.length*0.66;
  let svg=`<svg width="${W}" height="${H}" role="img">`;
  [0,max/2,max].forEach(g=>{const y=padT+plotH-(g/max)*plotH;
    svg+=`<line x1="${padL}" y1="${y}" x2="${W-10}" y2="${y}" stroke="var(--line)"/>`
      +`<text x="2" y="${y+4}" fill="var(--muted)" font-size="9">${g.toFixed(1)}</text>`;});
  items.forEach((d,i)=>{const x=padL+i/items.length*plotW+ (plotW/items.length-bw)/2;
    const h=(d[valKey]/max)*plotH; const y=padT+plotH-h;
    svg+=`<rect x="${x}" y="${y}" width="${bw}" height="${h}" fill="${color}" rx="2">`
      +`<title>${esc(d[labelKey])}: ${d[valKey]}</title></rect>`
      +`<text x="${x+bw/2}" y="${H-8}" fill="var(--muted)" font-size="9" text-anchor="middle">`
      +`${esc(String(d[labelKey]).slice(5))}</text>`;});
  svg+='</svg>'; $(el).innerHTML=svg;
}

function weekChart() {
  const pts=D.series||[];
  if(!pts.length){$('weekChart').innerHTML='<p class="muted">No data.</p>';return;}
  const W=Math.max(480,pts.length*70),H=200,padL=30,padB=28,padT=10;
  const plotW=W-padL-10,plotH=H-padB-padT;
  const x=i=>padL+(pts.length===1?plotW/2:i/(pts.length-1)*plotW);
  const y=v=>padT+plotH-(v/100)*plotH;
  let svg=`<svg width="${W}" height="${H}" role="img">`;
  [0,50,100].forEach(g=>{svg+=`<line x1="${padL}" y1="${y(g)}" x2="${W-10}" y2="${y(g)}" `
    +`stroke="var(--line)"/><text x="4" y="${y(g)+4}" fill="var(--muted)" font-size="9">${g}</text>`;});
  const poly=pts.map((p,i)=>`${x(i)},${y(p.score)}`).join(' ');
  svg+=`<polyline points="${poly}" fill="none" stroke="#4aa3ff" stroke-width="2"/>`;
  pts.forEach((p,i)=>{svg+=`<circle cx="${x(i)}" cy="${y(p.score)}" r="3" fill="${scoreColor(p.score)}">`
    +`<title>${esc(p.period)}: ${p.score}</title></circle>`
    +`<text x="${x(i)}" y="${H-8}" fill="var(--muted)" font-size="9" text-anchor="middle">`
    +`${esc(p.period.slice(5))}</text>`;});
  svg+='</svg>'; $('weekChart').innerHTML=svg;
}

function topList(el, items) {
  if(!items.length){$(el).innerHTML='<p class="muted">None.</p>';return;}
  $(el).innerHTML='<table><tbody>'+items.map(t=>
    `<tr><td>${esc(t.name)}</td><td class="num">${esc(t.human)}</td></tr>`).join('')+'</tbody></table>';
}

cards();
barChart('dailyChart', D.daily||[], 'active_hours', 'date', '#4aa3ff');
weekChart();
topList('topProd', D.top_productive||[]);
topList('topDist', D.top_distracting||[]);
$('disclaimer').textContent =
  'This view shows one person\'s desktop time and focus. It cannot see thinking, '
  + 'meetings away from the machine, or the quality of what was produced. Use it to '
  + 'inform a conversation, never as a standalone performance judgement.';
</script>
</body>
</html>
"""
