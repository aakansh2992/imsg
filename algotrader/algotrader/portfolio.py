"""Multi-market portfolio engine.

One always-on process runs an Engine per instrument off a merged bar feed.
Whichever markets are in session get scanned and traded; everything shares
one account, and the portfolio layer adds the cross-instrument limits a
single-market engine cannot see:

  * every position is sized off total account equity (cash + all unrealized)
  * at most ``max_concurrent_positions`` open at once
  * the sum of open initial risks stays under ``max_total_open_risk_pct``
  * the daily loss limit / profit lock apply to the account as a whole
    (each engine's risk manager is fed account equity, not its own slice)

Thread-safe status snapshots feed the web dashboard.
"""
from __future__ import annotations

import threading
from datetime import date, datetime

from .broker.paper import Account, PaperBroker, Trade
from .config import Config
from .data.bar import Bar
from .engine import Engine
from .instruments import REGISTRY, config_for
from .metrics import Report, compute


class PortfolioEngine:
    def __init__(self, base_cfg: Config, symbols: list[str]) -> None:
        unknown = [s for s in symbols if s not in REGISTRY]
        if unknown:
            raise ValueError(f"unknown symbols: {unknown} (have {sorted(REGISTRY)})")
        self.base_cfg = base_cfg
        self.account = Account(base_cfg.initial_equity)
        self.symbols = list(symbols)
        self._lock = threading.Lock()
        self._marks: dict[str, float] = {}
        self._sim_ts: datetime | None = None
        self._day: date | None = None
        self._day_start_equity = base_cfg.initial_equity
        self.max_concurrent_seen = 0
        self.curve: list[tuple[datetime, float]] = []  # account equity per bar

        self.engines: dict[str, Engine] = {}
        for sym in symbols:
            cfg = config_for(sym, base_cfg)
            broker = PaperBroker(
                cfg.initial_equity, cfg.spread, cfg.slippage,
                cfg.commission_per_trade, symbol=sym, account=self.account,
            )
            self.engines[sym] = Engine(
                cfg,
                broker=broker,
                equity_fn=lambda price, _s=sym: self.equity(),
                entry_gate=self._entry_gate,
            )

    # -- account-level state ---------------------------------------------------
    def equity(self) -> float:
        eq = self.account.cash
        for sym, engine in self.engines.items():
            mark = self._marks.get(sym)
            if mark is not None:
                eq += engine.broker.unrealized(mark)
        return eq

    def open_positions(self) -> int:
        return sum(1 for e in self.engines.values() if e.broker.position is not None)

    def open_risk_usd(self) -> float:
        total = 0.0
        for e in self.engines.values():
            pos = e.broker.position
            if pos is not None:
                total += pos.units * pos.r_distance
        return total

    def _entry_gate(self, symbol: str, new_risk_usd: float) -> bool:
        if self.open_positions() >= self.base_cfg.max_concurrent_positions:
            return False
        eq = self.equity()
        if eq <= 0:
            return False
        total = self.open_risk_usd() + new_risk_usd
        return total / eq <= self.base_cfg.max_total_open_risk_pct

    # -- event loop --------------------------------------------------------------
    def on_bar(self, symbol: str, bar: Bar) -> None:
        # Bars from different markets can interleave slightly out of order
        # around session gaps (the aggregator completes a bar only when the
        # next tick arrives), so the day roll and sim clock only move forward.
        with self._lock:
            self._marks[symbol] = bar.close
            if self._sim_ts is None or bar.ts > self._sim_ts:
                self._sim_ts = bar.ts
            if self._day is None or bar.ts.date() > self._day:
                self._day = bar.ts.date()
                self._day_start_equity = self.equity()
            self.engines[symbol].on_bar(bar)
            self.max_concurrent_seen = max(self.max_concurrent_seen, self.open_positions())
            self.curve.append((bar.ts, self.equity()))

    def finish(self, last_bars: dict[str, Bar] | None = None) -> None:
        """Close anything still open using each symbol's last seen price."""
        with self._lock:
            for sym, engine in self.engines.items():
                bar = (last_bars or {}).get(sym) or self._last_bar_guess(sym)
                if bar is not None:
                    engine.finish(bar)

    def _last_bar_guess(self, sym: str) -> Bar | None:
        mark = self._marks.get(sym)
        if mark is None or self._sim_ts is None:
            return None
        return Bar(ts=self._sim_ts, open=mark, high=mark, low=mark, close=mark, volume=0.0)

    # -- reporting ---------------------------------------------------------------
    def curve_snapshot(self, max_points: int = 600) -> list[tuple[float, float]]:
        """Downsampled account equity curve as (epoch_seconds, equity)."""
        with self._lock:
            pts = sorted(self.curve, key=lambda p: p[0])
        if len(pts) > max_points:
            stride = len(pts) // max_points + 1
            tail = pts[-1]
            pts = pts[::stride]
            if pts[-1] is not tail:
                pts.append(tail)
        return [(ts.timestamp(), round(eq, 2)) for ts, eq in pts]

    def all_trades(self) -> list[Trade]:
        trades: list[Trade] = []
        for e in self.engines.values():
            trades.extend(e.broker.trades)
        trades.sort(key=lambda t: t.exit_ts)
        return trades

    def account_report(self) -> Report:
        curve: list[tuple[datetime, float]] = []
        for e in self.engines.values():
            curve.extend(e.equity_curve)
        curve.sort(key=lambda p: p[0])
        return compute(self.base_cfg.initial_equity, curve, self.all_trades())

    def status(self) -> dict:
        """JSON-safe snapshot for the dashboard/API."""
        with self._lock:
            eq = self.equity()
            per_symbol = {}
            for sym, e in self.engines.items():
                pos = e.broker.position
                today = self._day
                pnl_today = sum(
                    t.pnl for t in e.broker.trades if today and t.exit_ts.date() == today
                )
                per_symbol[sym] = {
                    "last_price": self._marks.get(sym),
                    "in_session": (
                        e.risk.clock.in_session(self._sim_ts) if self._sim_ts else False
                    ),
                    "halt": e.risk.halt_reason or None,
                    "trades_closed": len(e.broker.trades),
                    "pnl_today": round(pnl_today, 2),
                    "position": None if pos is None else {
                        "direction": "long" if pos.direction == 1 else "short",
                        "units": pos.units,
                        "entry": pos.entry,
                        "sl": pos.sl,
                        "tp": pos.tp,
                        "unrealized": round(
                            e.broker.unrealized(self._marks.get(sym, pos.entry)), 2
                        ),
                    },
                }
            recent = [
                {
                    "symbol": t.symbol,
                    "side": "long" if t.direction == 1 else "short",
                    "units": t.units,
                    "entry": t.entry,
                    "exit": t.exit,
                    "pnl": round(t.pnl, 2),
                    "reason": t.reason,
                    "exit_ts": t.exit_ts.isoformat(),
                }
                for t in self.all_trades()[-100:]
            ]
            return {
                "sim_time": self._sim_ts.isoformat() if self._sim_ts else None,
                "equity": round(eq, 2),
                "cash": round(self.account.cash, 2),
                "day_pnl": round(eq - self._day_start_equity, 2),
                "open_positions": self.open_positions(),
                "open_risk_usd": round(self.open_risk_usd(), 2),
                "symbols": per_symbol,
                "recent_trades": recent,
            }
