"""Web dashboard: one endpoint for humans, one for machines.

The bot runs as a single always-on process; any device with a browser —
phone, tablet, laptop — is a viewer. GET / serves a responsive, theme-aware
page that polls GET /api/status (JSON) every few seconds. Stdlib only.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>algotrader</title>
<style>
  :root { color-scheme: light dark;
    --bg:#f6f7f9; --card:#fff; --ink:#1a1d21; --dim:#67707c; --line:#e3e6ea;
    --green:#0a7f4f; --red:#c23934; }
  @media (prefers-color-scheme: dark) { :root {
    --bg:#101215; --card:#191c20; --ink:#e8eaed; --dim:#9aa3ad; --line:#2a2e34; } }
  * { box-sizing:border-box; margin:0; }
  body { font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
         background:var(--bg); color:var(--ink); padding:16px; }
  h1 { font-size:18px; margin-bottom:2px; }
  .sub { color:var(--dim); font-size:13px; margin-bottom:14px; }
  .row { display:flex; flex-wrap:wrap; gap:12px; margin-bottom:14px; }
  .card { background:var(--card); border:1px solid var(--line);
          border-radius:10px; padding:12px 14px; flex:1 1 150px; min-width:150px; }
  .k { color:var(--dim); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
  .v { font-size:20px; font-weight:600; margin-top:2px; font-variant-numeric:tabular-nums; }
  .pos { color:var(--green); } .neg { color:var(--red); }
  .sym { flex:1 1 220px; }
  .badge { display:inline-block; font-size:11px; padding:1px 8px; border-radius:99px;
           border:1px solid var(--line); color:var(--dim); margin-left:6px; }
  .badge.open { color:var(--green); border-color:var(--green); }
  table { width:100%; border-collapse:collapse; font-size:13px;
          font-variant-numeric:tabular-nums; }
  th,td { text-align:right; padding:5px 8px; border-bottom:1px solid var(--line); }
  th:first-child, td:first-child { text-align:left; }
  th { color:var(--dim); font-weight:500; }
  .scroll { overflow-x:auto; }
</style>
</head>
<body>
<h1>algotrader <span class="badge">paper</span></h1>
<div class="sub" id="ts">connecting…</div>
<div class="row" id="account"></div>
<div class="row" id="symbols"></div>
<div class="card"><div class="k">recent trades</div>
  <div class="scroll"><table id="trades"><thead>
    <tr><th>symbol</th><th>side</th><th>units</th><th>entry</th><th>exit</th><th>P&amp;L</th><th>why</th></tr>
  </thead><tbody></tbody></table></div>
</div>
<script>
const fmt = (x, d=2) => x == null ? "—" :
  Number(x).toLocaleString(undefined, {minimumFractionDigits:d, maximumFractionDigits:d});
const cls = x => x > 0 ? "pos" : x < 0 ? "neg" : "";
function card(k, v, c) {
  return `<div class="card"><div class="k">${k}</div><div class="v ${c||""}">${v}</div></div>`;
}
async function tick() {
  try {
    const s = await (await fetch("/api/status")).json();
    document.getElementById("ts").textContent =
      "sim time " + (s.sim_time || "—") + " · open risk $" + fmt(s.open_risk_usd);
    document.getElementById("account").innerHTML =
      card("equity", fmt(s.equity)) +
      card("day P&L", fmt(s.day_pnl), cls(s.day_pnl)) +
      card("cash", fmt(s.cash)) +
      card("open positions", s.open_positions, "");
    let sy = "";
    for (const [sym, d] of Object.entries(s.symbols || {})) {
      const p = d.position;
      sy += `<div class="card sym"><div class="k">${sym}
        <span class="badge ${d.in_session ? "open" : ""}">${d.in_session ? "session open" : "closed"}</span>
        ${d.halt ? `<span class="badge neg">${d.halt}</span>` : ""}</div>
        <div class="v">${fmt(d.last_price)}</div>
        <div class="sub">today ${fmt(d.pnl_today)} · ${d.trades_closed} trades</div>
        <div class="sub">${p ? p.direction + " " + fmt(p.units) + " @ " + fmt(p.entry) +
          " (upl " + fmt(p.unrealized) + ")" : "flat"}</div></div>`;
    }
    document.getElementById("symbols").innerHTML = sy;
    const tb = document.querySelector("#trades tbody");
    tb.innerHTML = (s.recent_trades || []).slice().reverse().map(t =>
      `<tr><td>${t.symbol}</td><td>${t.side}</td><td>${fmt(t.units)}</td>
       <td>${fmt(t.entry)}</td><td>${fmt(t.exit)}</td>
       <td class="${cls(t.pnl)}">${fmt(t.pnl)}</td><td>${t.reason}</td></tr>`).join("");
  } catch (e) {
    document.getElementById("ts").textContent = "disconnected — retrying…";
  }
}
tick(); setInterval(tick, 3000);
</script>
</body>
</html>
"""


def start_server(port: int, status_fn: Callable[[], dict]) -> ThreadingHTTPServer:
    """Serve the dashboard on 0.0.0.0:port in a daemon thread."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            if self.path.startswith("/api/status"):
                body = json.dumps(status_fn()).encode()
                ctype = "application/json"
            elif self.path in ("/", "/index.html"):
                body = DASHBOARD_HTML.encode()
                ctype = "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:  # keep the trading log clean
            pass

    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd
