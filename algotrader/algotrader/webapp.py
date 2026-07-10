"""Web control panel for demo paper trading and backtest replays.

One always-on process; every device with a browser is a control surface:

  GET  /               responsive control panel (light/dark, no external libs)
  GET  /api/status     live JSON: state, equity curve, positions, trades
  POST /api/run        start a session {equity, symbols, days, speed, seed}
  POST /api/stop       stop the running session (flattens and reports)
  GET  /api/report     final metrics report as JSON (when finished)
  GET  /api/trades.csv full trade list as a CSV download

``speed`` 0 replays instantly (a backtest); any positive value paces
sim-time against the wall clock for a watchable demo session. Data is the
bundled synthetic feed — machinery demo, not an edge claim.
"""
from __future__ import annotations

import dataclasses
import io
import json
import math
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import Config
from .feed import synthetic_feed
from .instruments import DEFAULT_SYMBOLS, REGISTRY
from .metrics import Report
from .portfolio import PortfolioEngine

IDLE, RUNNING, STOPPING, DONE, ERROR = "idle", "running", "stopping", "done", "error"


class SessionManager:
    """Owns at most one paper session at a time, run in a daemon thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.state = IDLE
        self.error = ""
        self.params: dict = {}
        self.portfolio: PortfolioEngine | None = None
        self.report: Report | None = None

    # -- control -----------------------------------------------------------------
    def start(self, params: dict) -> str:
        """Validate and launch; returns an error message or ''."""
        try:
            equity = float(params.get("equity", 100_000.0))
            days = int(params.get("days", 5))
            speed = float(params.get("speed", 300.0))
            seed = int(params.get("seed", 42))
            symbols = list(params.get("symbols") or DEFAULT_SYMBOLS)
        except (TypeError, ValueError) as e:
            return f"bad parameters: {e}"
        if equity <= 0:
            return "equity must be positive"
        if not 1 <= days <= 365:
            return "days must be 1..365"
        if speed < 0:
            return "speed must be >= 0"
        unknown = [s for s in symbols if s not in REGISTRY]
        if unknown:
            return f"unknown symbols: {unknown}"
        if not symbols:
            return "pick at least one market"

        with self._lock:
            if self.state in (RUNNING, STOPPING):
                return "a session is already running"
            cfg = Config(initial_equity=equity)
            self.portfolio = PortfolioEngine(cfg, symbols)
            self.params = {"equity": equity, "days": days, "speed": speed,
                           "seed": seed, "symbols": symbols}
            self.report = None
            self.error = ""
            self.state = RUNNING
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return ""

    def stop(self) -> None:
        with self._lock:
            if self.state == RUNNING:
                self.state = STOPPING
                self._stop.set()

    def _run(self) -> None:
        pf = self.portfolio
        p = self.params
        try:
            feed = synthetic_feed(p["symbols"], days=p["days"], seed=p["seed"],
                                  speed=p["speed"])
            for sym, bar in feed:
                if self._stop.is_set():
                    break
                pf.on_bar(sym, bar)
            pf.finish()
            with self._lock:
                self.report = pf.account_report()
                self.state = DONE
        except Exception as e:  # surface, don't die silently
            with self._lock:
                self.error = f"{type(e).__name__}: {e}"
                self.state = ERROR

    # -- views -------------------------------------------------------------------
    def status(self) -> dict:
        with self._lock:
            state, error, params = self.state, self.error, dict(self.params)
            pf, report = self.portfolio, self.report
        out: dict = {"state": state, "error": error, "params": params}
        if pf is not None:
            out.update(pf.status())
            out["initial_equity"] = pf.base_cfg.initial_equity
            out["total_pnl"] = round(out["equity"] - pf.base_cfg.initial_equity, 2)
            out["curve"] = pf.curve_snapshot()
            out["per_symbol_pnl"] = {
                sym: round(sum(t.pnl for t in e.broker.trades), 2)
                for sym, e in pf.engines.items()
            }
        if report is not None:
            rep = dataclasses.asdict(report)
            if math.isinf(rep.get("profit_factor", 0.0)):
                rep["profit_factor"] = None  # JSON has no Infinity
            out["report"] = rep
        return out

    def trades_csv(self) -> str:
        pf = self.portfolio
        if pf is None:
            return "symbol,side,units,entry_ts,entry,exit_ts,exit,pnl,reason\n"
        buf = io.StringIO()
        buf.write("symbol,side,units,entry_ts,entry,exit_ts,exit,pnl,reason\n")
        for t in pf.all_trades():
            side = "long" if t.direction == 1 else "short"
            buf.write(f"{t.symbol},{side},{t.units},{t.entry_ts.isoformat()},"
                      f"{t.entry},{t.exit_ts.isoformat()},{t.exit},"
                      f"{round(t.pnl, 2)},{t.reason}\n")
        return buf.getvalue()


def start_webapp(port: int, manager: SessionManager | None = None) -> ThreadingHTTPServer:
    mgr = manager or SessionManager()

    class Handler(BaseHTTPRequestHandler):
        def _send(self, body: bytes, ctype: str, status: int = 200,
                  extra: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj: dict, status: int = 200) -> None:
            self._send(json.dumps(obj).encode(), "application/json", status)

        def do_GET(self) -> None:  # noqa: N802
            if self.path in ("/", "/index.html"):
                self._send(PANEL_HTML.encode(), "text/html; charset=utf-8")
            elif self.path.startswith("/api/status"):
                self._json(mgr.status())
            elif self.path.startswith("/api/report"):
                st = mgr.status()
                if "report" in st:
                    self._json(st["report"])
                else:
                    self._json({"error": "no finished report yet"}, 404)
            elif self.path.startswith("/api/trades.csv"):
                self._send(mgr.trades_csv().encode(), "text/csv",
                           extra={"Content-Disposition":
                                  "attachment; filename=trades.csv"})
            else:
                self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                self._json({"error": "invalid JSON"}, 400)
                return
            if self.path.startswith("/api/run"):
                err = mgr.start(payload)
                self._json({"error": err} if err else {"ok": True},
                           400 if err else 200)
            elif self.path.startswith("/api/stop"):
                mgr.stop()
                self._json({"ok": True})
            else:
                self.send_error(404)

        def log_message(self, *args) -> None:
            pass

    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    httpd.manager = mgr  # type: ignore[attr-defined]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


# ---------------------------------------------------------------------------
# Front end. Design tokens follow the validated reference dataviz palette:
# single-series line in categorical blue, status text reserved for P&L signs,
# recessive hairline grid, tabular figures only where columns must align.
# ---------------------------------------------------------------------------
PANEL_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>algotrader control panel</title>
<style>
  :root { color-scheme: light dark;
    --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e;
    --muted:#898781; --grid:#e1e0d9; --axis:#c3c2b7;
    --series:#2a78d6; --good:#006300; --bad:#d03b3b;
    --ring:rgba(11,11,11,0.10); }
  @media (prefers-color-scheme: dark) { :root {
    --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7;
    --muted:#898781; --grid:#2c2c2a; --axis:#383835;
    --series:#3987e5; --good:#0ca30c; --bad:#e66767;
    --ring:rgba(255,255,255,0.10); } }
  * { box-sizing:border-box; margin:0; }
  body { font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
         background:var(--page); color:var(--ink); padding:16px; max-width:1100px;
         margin:0 auto; }
  h1 { font-size:18px; display:inline; }
  .badge { display:inline-block; font-size:12px; padding:2px 10px; border-radius:99px;
           border:1px solid var(--ring); color:var(--ink2); margin-left:8px;
           vertical-align:2px; }
  .badge.running { color:var(--good); border-color:var(--good); }
  .badge.error { color:var(--bad); border-color:var(--bad); }
  .sub { color:var(--muted); font-size:13px; margin:4px 0 14px; }
  .row { display:flex; flex-wrap:wrap; gap:12px; margin-bottom:14px; }
  .card { background:var(--surface); border:1px solid var(--ring);
          border-radius:10px; padding:12px 14px; }
  .tile { flex:1 1 140px; min-width:140px; }
  .k { color:var(--muted); font-size:12px; text-transform:uppercase;
       letter-spacing:.04em; }
  .v { font-size:22px; font-weight:600; margin-top:2px; }
  .good { color:var(--good); } .bad { color:var(--bad); }
  .controls { width:100%; }
  .controls .fields { display:flex; flex-wrap:wrap; gap:14px; align-items:flex-end; }
  label { display:block; font-size:12px; color:var(--ink2); margin-bottom:3px; }
  input, select { font:inherit; color:var(--ink); background:var(--page);
    border:1px solid var(--ring); border-radius:7px; padding:6px 9px; width:120px; }
  .syms { display:flex; gap:10px; flex-wrap:wrap; padding-bottom:2px; }
  .syms label { display:flex; gap:5px; align-items:center; font-size:14px;
                color:var(--ink); margin:0; }
  .syms input { width:auto; }
  button { font:inherit; font-weight:600; border-radius:8px; padding:8px 18px;
           border:1px solid var(--ring); cursor:pointer; }
  #start { background:var(--series); color:#fff; border-color:transparent; }
  #stop  { background:transparent; color:var(--bad); border-color:var(--bad); }
  button:disabled { opacity:.45; cursor:not-allowed; }
  .err { color:var(--bad); font-size:13px; margin-top:6px; min-height:1em; }
  .chartcard { width:100%; }
  .charthead { display:flex; justify-content:space-between; align-items:baseline; }
  #tip { position:fixed; pointer-events:none; display:none; background:var(--surface);
         border:1px solid var(--ring); border-radius:8px; padding:6px 10px;
         font-size:13px; box-shadow:0 2px 8px rgba(0,0,0,.12); z-index:5; }
  #tip .t { color:var(--muted); font-size:12px; }
  svg text { fill:var(--muted); font:11px system-ui,sans-serif;
             font-variant-numeric:tabular-nums; }
  .sym { flex:1 1 210px; }
  table { width:100%; border-collapse:collapse; font-size:13px;
          font-variant-numeric:tabular-nums; }
  th,td { text-align:right; padding:5px 8px; border-bottom:1px solid var(--grid); }
  th:first-child, td:first-child { text-align:left; }
  th { color:var(--muted); font-weight:500; }
  .scroll { overflow-x:auto; max-height:340px; overflow-y:auto; }
  a { color:var(--series); font-size:13px; }
  .grid2 { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
           gap:8px 18px; font-size:14px; }
  .grid2 b { font-variant-numeric:tabular-nums; }
</style>
</head>
<body>
<h1>algotrader</h1><span class="badge" id="state">connecting…</span>
<span class="badge">synthetic demo feed</span>
<div class="sub">paper trading control panel — no real orders, no edge claims;
results on synthetic data validate machinery only</div>

<div class="row"><div class="card controls">
  <div class="fields">
    <div><label for="equity">capital (USD)</label>
      <input id="equity" type="number" value="100000" min="1000" step="1000"></div>
    <div><label>markets</label><div class="syms" id="syms"></div></div>
    <div><label for="days">days</label>
      <input id="days" type="number" value="5" min="1" max="365"></div>
    <div><label for="speed">mode / speed</label>
      <select id="speed">
        <option value="0">backtest (instant)</option>
        <option value="60">demo ×60</option>
        <option value="300" selected>demo ×300</option>
        <option value="1800">demo ×1800</option>
      </select></div>
    <div><label for="seed">seed</label>
      <input id="seed" type="number" value="42"></div>
    <button id="start">Start</button>
    <button id="stop" disabled>Stop</button>
  </div>
  <div class="err" id="err"></div>
</div></div>

<div class="row" id="tiles"></div>

<div class="row"><div class="card chartcard">
  <div class="charthead"><div class="k">account equity</div>
    <div class="k" id="curveinfo"></div></div>
  <div id="chart" style="position:relative"></div>
</div></div>

<div class="row" id="symbols"></div>

<div class="row" id="reportwrap" style="display:none"><div class="card" style="width:100%">
  <div class="k">final report</div>
  <div class="grid2" id="report" style="margin-top:8px"></div>
  <div class="k" style="margin-top:14px">daily P&amp;L</div>
  <div class="scroll"><table id="daily"><thead>
    <tr><th>date</th><th>P&amp;L</th></tr></thead><tbody></tbody></table></div>
</div></div>

<div class="row"><div class="card" style="width:100%">
  <div class="charthead"><div class="k">trades</div>
    <a href="/api/trades.csv" download>download CSV</a></div>
  <div class="scroll"><table id="trades"><thead>
    <tr><th>exit time</th><th>symbol</th><th>side</th><th>units</th>
        <th>entry</th><th>exit</th><th>P&amp;L</th><th>why</th></tr>
  </thead><tbody></tbody></table></div>
</div></div>

<div id="tip"></div>

<script>
const SYMBOLS = ["XAUUSD","XAGUSD","WTIUSD","BTCUSD"];
const $ = id => document.getElementById(id);
const fmt = (x, d=2) => x == null ? "—" :
  Number(x).toLocaleString(undefined,{minimumFractionDigits:d,maximumFractionDigits:d});
const cls = x => x > 0 ? "good" : x < 0 ? "bad" : "";
const sign = x => (x > 0 ? "+" : "") + fmt(x);

$("syms").innerHTML = SYMBOLS.map(s =>
  `<label><input type="checkbox" value="${s}" checked>${s}</label>`).join("");

$("start").onclick = async () => {
  $("err").textContent = "";
  const symbols = [...document.querySelectorAll("#syms input:checked")].map(c => c.value);
  const body = { equity:+$("equity").value, days:+$("days").value,
                 speed:+$("speed").value, seed:+$("seed").value, symbols };
  const r = await fetch("/api/run", {method:"POST", body: JSON.stringify(body)});
  const j = await r.json();
  if (j.error) $("err").textContent = j.error;
};
$("stop").onclick = () => fetch("/api/stop", {method:"POST", body:"{}"});

let curve = [], initial = 0;

function tiles(s) {
  const total = s.total_pnl, day = s.day_pnl;
  $("tiles").innerHTML =
    t("equity", fmt(s.equity)) +
    t("total P&L", sign(total), cls(total)) +
    t("day P&L", sign(day), cls(day)) +
    t("open positions", s.open_positions ?? "—") +
    t("open risk", "$" + fmt(s.open_risk_usd));
  function t(k, v, c) {
    return `<div class="card tile"><div class="k">${k}</div>
            <div class="v ${c||""}">${v}</div></div>`;
  }
}

function drawChart() {
  const box = $("chart"), W = box.clientWidth || 800, H = 260;
  const P = {l:56, r:12, t:10, b:22};
  if (curve.length < 2) { box.innerHTML =
    `<div class="sub" style="padding:30px 0">no data yet — start a session</div>`; return; }
  const xs = curve.map(p => p[0]), ys = curve.map(p => p[1]);
  let lo = Math.min(...ys, initial), hi = Math.max(...ys, initial);
  if (hi - lo < 1e-9) { hi += 1; lo -= 1; }
  const pad = (hi - lo) * 0.06; lo -= pad; hi += pad;
  const x = t => P.l + (t - xs[0]) / (xs[xs.length-1] - xs[0] || 1) * (W - P.l - P.r);
  const y = v => P.t + (hi - v) / (hi - lo) * (H - P.t - P.b);
  const path = curve.map((p,i) => (i ? "L" : "M") + x(p[0]).toFixed(1) + "," +
                                   y(p[1]).toFixed(1)).join("");
  const ticks = 4, grid = [], labels = [];
  for (let i = 0; i <= ticks; i++) {
    const v = lo + (hi - lo) * i / ticks, yy = y(v);
    grid.push(`<line x1="${P.l}" x2="${W-P.r}" y1="${yy}" y2="${yy}"
               stroke="var(--grid)" stroke-width="1"/>`);
    labels.push(`<text x="${P.l-6}" y="${yy+4}" text-anchor="end">${fmt(v,0)}</text>`);
  }
  const d0 = new Date(xs[0]*1000), d1 = new Date(xs[xs.length-1]*1000);
  const dfmt = d => d.toISOString().slice(5,16).replace("T"," ");
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}"
      role="img" aria-label="account equity over time">
    ${grid.join("")}
    <line x1="${P.l}" x2="${W-P.r}" y1="${y(initial)}" y2="${y(initial)}"
      stroke="var(--axis)" stroke-width="1" stroke-dasharray="4 4"/>
    <path d="${path}" fill="none" stroke="var(--series)" stroke-width="2"
      stroke-linejoin="round" stroke-linecap="round"/>
    <line id="xh" y1="${P.t}" y2="${H-P.b}" stroke="var(--axis)"
      stroke-width="1" visibility="hidden"/>
    <circle id="dot" r="4" fill="var(--series)" stroke="var(--surface)"
      stroke-width="2" visibility="hidden"/>
    ${labels.join("")}
    <text x="${P.l}" y="${H-6}">${dfmt(d0)}</text>
    <text x="${W-P.r}" y="${H-6}" text-anchor="end">${dfmt(d1)}</text>
  </svg>`;
  $("curveinfo").textContent = "start " + fmt(initial, 0) + " (dashed)";
  const svg = box.querySelector("svg"), tip = $("tip");
  svg.addEventListener("mousemove", ev => {
    const r = svg.getBoundingClientRect();
    const mx = (ev.clientX - r.left) * (W / r.width);
    let best = 0, bd = 1e18;
    for (let i = 0; i < curve.length; i++) {
      const d = Math.abs(x(curve[i][0]) - mx);
      if (d < bd) { bd = d; best = i; }
    }
    const p = curve[best], px = x(p[0]), py = y(p[1]);
    const xh = svg.querySelector("#xh"), dot = svg.querySelector("#dot");
    xh.setAttribute("x1", px); xh.setAttribute("x2", px);
    xh.setAttribute("visibility", "visible");
    dot.setAttribute("cx", px); dot.setAttribute("cy", py);
    dot.setAttribute("visibility", "visible");
    const dpl = p[1] - initial;
    tip.innerHTML = `<div class="t">${new Date(p[0]*1000).toISOString()
      .slice(0,16).replace("T"," ")} UTC</div>
      <b>${fmt(p[1])}</b> <span class="${cls(dpl)}">${sign(dpl)}</span>`;
    tip.style.display = "block";
    tip.style.left = Math.min(ev.clientX + 14, innerWidth - 180) + "px";
    tip.style.top = (ev.clientY + 14) + "px";
  });
  svg.addEventListener("mouseleave", () => {
    tip.style.display = "none";
    svg.querySelector("#xh").setAttribute("visibility", "hidden");
    svg.querySelector("#dot").setAttribute("visibility", "hidden");
  });
}

function markets(s) {
  let out = "";
  for (const [sym, d] of Object.entries(s.symbols || {})) {
    const p = d.position;
    out += `<div class="card sym"><div class="k">${sym}
      <span class="badge ${d.in_session ? "running" : ""}">
        ${d.in_session ? "session open" : "closed"}</span>
      ${d.halt ? `<span class="badge error">${d.halt}</span>` : ""}</div>
      <div class="v">${fmt(d.last_price)}</div>
      <div class="sub" style="margin:2px 0 0">
        today <span class="${cls(d.pnl_today)}">${sign(d.pnl_today)}</span>
        · total <span class="${cls((s.per_symbol_pnl||{})[sym])}">
          ${sign((s.per_symbol_pnl||{})[sym] ?? 0)}</span>
        · ${d.trades_closed} trades<br>
        ${p ? p.direction + " " + fmt(p.units,3) + " @ " + fmt(p.entry) +
          " (upl <span class='" + cls(p.unrealized) + "'>" + sign(p.unrealized) +
          "</span>)" : "flat"}</div></div>`;
  }
  $("symbols").innerHTML = out;
}

function report(s) {
  const r = s.report;
  $("reportwrap").style.display = r ? "" : "none";
  if (!r) return;
  const pf = r.profit_factor === null ? "—" :
    (isFinite(r.profit_factor) ? fmt(r.profit_factor) : "inf");
  $("report").innerHTML = [
    ["net P&L", `<b class="${cls(r.net_pnl)}">${sign(r.net_pnl)}</b>`],
    ["return", `<b class="${cls(r.return_pct)}">${sign(r.return_pct)}%</b>`],
    ["trades", `<b>${r.n_trades}</b>`],
    ["win rate", `<b>${fmt(r.win_rate,1)}%</b>`],
    ["profit factor", `<b>${pf}</b>`],
    ["expectancy/trade", `<b class="${cls(r.expectancy)}">${sign(r.expectancy)}</b>`],
    ["max drawdown", `<b>${fmt(r.max_drawdown_pct)}%</b>`],
    ["sharpe (ann.)", `<b>${fmt(r.sharpe)}</b>`],
    ["green days", `<b>${r.green_days}/${r.days}</b>`],
  ].map(([k,v]) => `<div><div class="k">${k}</div>${v}</div>`).join("");
  const tb = document.querySelector("#daily tbody");
  tb.innerHTML = Object.entries(r.daily_pnl || {}).map(([d,v]) =>
    `<tr><td>${d}</td><td class="${cls(v)}">${sign(v)}</td></tr>`).join("");
}

function trades(s) {
  const tb = document.querySelector("#trades tbody");
  tb.innerHTML = (s.recent_trades || []).slice().reverse().map(t =>
    `<tr><td>${(t.exit_ts||"").slice(0,16).replace("T"," ")}</td>
     <td>${t.symbol}</td><td>${t.side}</td><td>${fmt(t.units,3)}</td>
     <td>${fmt(t.entry)}</td><td>${fmt(t.exit)}</td>
     <td class="${cls(t.pnl)}">${sign(t.pnl)}</td><td>${t.reason}</td></tr>`).join("");
}

async function poll() {
  try {
    const s = await (await fetch("/api/status")).json();
    const st = $("state");
    st.textContent = s.state + (s.error ? ": " + s.error : "");
    st.className = "badge " + (s.state === "running" ? "running" :
                               s.state === "error" ? "error" : "");
    $("start").disabled = s.state === "running" || s.state === "stopping";
    $("stop").disabled = !(s.state === "running");
    if (s.equity != null) tiles(s);
    initial = s.initial_equity || initial;
    curve = s.curve || curve;
    drawChart(); markets(s); report(s); trades(s);
  } catch (e) { $("state").textContent = "disconnected"; }
}
poll(); setInterval(poll, 2000);
addEventListener("resize", drawChart);
</script>
</body>
</html>
"""
