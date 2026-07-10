"""Simulated broker with realistic, conservative fill assumptions.

* Entries/exits at the bar close, paying half the spread plus slippage.
* Stops and targets are checked against each bar's high/low; if a bar spans
  both the stop and the target, the stop is assumed to fill first.
* Gaps fill at the worse of the level and the bar open (no free lunches).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..data.bar import Bar


@dataclass
class Position:
    direction: int  # +1 long, -1 short
    units: float    # ounces
    entry: float
    sl: float
    tp: float
    entry_ts: datetime
    r_distance: float          # initial stop distance, for breakeven logic
    breakeven_moved: bool = False


@dataclass(frozen=True)
class Trade:
    entry_ts: datetime
    exit_ts: datetime
    direction: int
    units: float
    entry: float
    exit: float
    pnl: float
    reason: str  # "sl" | "tp" | "flip" | "eod" | "daily_loss" | "profit_lock" | "end"


class PaperBroker:
    def __init__(
        self,
        initial_equity: float,
        spread: float = 0.0,
        slippage: float = 0.0,
        commission_per_trade: float = 0.0,
    ) -> None:
        self.cash = initial_equity
        self.spread = spread
        self.slippage = slippage
        self.commission = commission_per_trade
        self._position: Position | None = None
        self.trades: list[Trade] = []

    # -- state ----------------------------------------------------------------
    @property
    def position(self) -> Position | None:
        return self._position

    def unrealized(self, price: float) -> float:
        p = self._position
        if p is None:
            return 0.0
        return p.direction * p.units * (price - p.entry)

    def equity(self, price: float) -> float:
        return self.cash + self.unrealized(price)

    # -- fills ------------------------------------------------------------------
    def _entry_cost(self) -> float:
        return self.spread / 2.0 + self.slippage

    def open(self, direction: int, units: float, bar: Bar, sl: float, tp: float) -> Position:
        if self._position is not None:
            raise RuntimeError("position already open")
        if direction not in (-1, 1) or units <= 0:
            raise ValueError("invalid order")
        entry = bar.close + direction * self._entry_cost()
        self._position = Position(
            direction=direction,
            units=units,
            entry=entry,
            sl=sl,
            tp=tp,
            entry_ts=bar.ts,
            r_distance=abs(entry - sl),
        )
        return self._position

    def _settle(self, exit_price: float, ts: datetime, reason: str) -> Trade:
        p = self._position
        assert p is not None
        pnl = p.direction * p.units * (exit_price - p.entry) - self.commission
        trade = Trade(p.entry_ts, ts, p.direction, p.units, p.entry, exit_price, pnl, reason)
        self.cash += pnl
        self.trades.append(trade)
        self._position = None
        return trade

    def close(self, bar: Bar, reason: str) -> Trade:
        p = self._position
        if p is None:
            raise RuntimeError("no open position")
        exit_price = bar.close - p.direction * self._entry_cost()
        return self._settle(exit_price, bar.ts, reason)

    def mark(self, bar: Bar) -> list[Trade]:
        """Check protective levels against the bar range. Stop wins ties."""
        p = self._position
        if p is None:
            return []
        cost = self._entry_cost()
        if p.direction == 1:
            hit_sl = bar.low <= p.sl
            hit_tp = bar.high >= p.tp
            if hit_sl:
                fill = min(p.sl, bar.open) - cost
                return [self._settle(fill, bar.ts, "sl")]
            if hit_tp:
                fill = max(p.tp, bar.open) - cost
                return [self._settle(fill, bar.ts, "tp")]
        else:
            hit_sl = bar.high >= p.sl
            hit_tp = bar.low <= p.tp
            if hit_sl:
                fill = max(p.sl, bar.open) + cost
                return [self._settle(fill, bar.ts, "sl")]
            if hit_tp:
                fill = min(p.tp, bar.open) + cost
                return [self._settle(fill, bar.ts, "tp")]
        return []
