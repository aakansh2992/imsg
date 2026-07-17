"""The two daily messages from the whiteboard spec.

1) Morning message: what's happening in each market today — last price, each
   strategy's current stance, and the account's risk state.
2) Night message: exactly how the portfolio performed — day P&L, per-market
   trades, equity, and any risk halts.

Reports are plain text: printed, and saved under a reports directory so any
delivery channel (Task Scheduler + email, cron + messaging app, etc.) can pick
them up. Generation is here; delivery is deliberately left to the machine the
engine runs on.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Dict, List, Optional

from .engine.portfolio import MarketSpec, PortfolioResult

TF_NAMES = {900: "15m", 3600: "1h", 14400: "4h"}


def _tf_name(seconds: int) -> str:
    return TF_NAMES.get(seconds, f"{seconds}s")


def morning_report(markets: List[MarketSpec],
                   prices: Dict[str, Optional[float]],
                   risk_note: str = "ok",
                   today: Optional[date] = None) -> str:
    today = today or date.today()
    lines = [f"MORNING BRIEFING — {today.isoformat()}", "-" * 40]
    for m in markets:
        px = prices.get(m.symbol)
        px_s = f"{px:,.2f}" if px is not None else "n/a"
        status = {}
        if hasattr(m.strategy, "status"):
            try:
                status = m.strategy.status()
            except Exception:
                status = {}
        stance = ", ".join(f"{k}={v}" for k, v in status.items()) or "no state yet"
        lines.append(f"{m.symbol:<4} {_tf_name(m.timeframe_seconds):>3} "
                     f"{m.strategy.name:<22} last={px_s}")
        lines.append(f"     {stance}")
    lines.append("-" * 40)
    lines.append(f"Risk state: {risk_note}")
    lines.append("Reminder: no strategy guarantees a profitable day.")
    return "\n".join(lines) + "\n"


def night_report(result: PortfolioResult,
                 today: Optional[date] = None) -> str:
    today = today or date.today()
    lines = [f"NIGHT REPORT — {today.isoformat()}", "-" * 40]
    lines.append(f"Equity: {result.starting_equity:,.2f} -> "
                 f"{result.ending_equity:,.2f} "
                 f"({result.return_pct:+.2f}%)")
    lines.append(f"Closed trades: {len(result.trades)}  "
                 f"win rate {result.win_rate:.0f}%  "
                 f"max DD {result.max_drawdown_pct:.2f}%")
    per = result.per_symbol()
    if per:
        for sym, s in sorted(per.items()):
            lines.append(f"  {sym}: {int(s['trades'])} trades, "
                         f"P&L {s['pnl']:+,.2f}")
    else:
        lines.append("  No trades closed this session.")
    if result.halted_reason:
        lines.append(f"RISK HALT ACTIVE: {result.halted_reason}")
    lines.append("-" * 40)
    lines.append("Figures are from paper/backtest execution, including "
                 "modelled spread and slippage.")
    return "\n".join(lines) + "\n"


def save_report(text: str, kind: str, reports_dir: str,
                when: Optional[datetime] = None) -> str:
    when = when or datetime.now()
    os.makedirs(reports_dir, exist_ok=True)
    path = os.path.join(reports_dir,
                        f"{when.strftime('%Y-%m-%d')}-{kind}.txt")
    with open(path, "w") as fh:
        fh.write(text)
    return path
