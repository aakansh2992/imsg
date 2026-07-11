"""Risk management: sizing, daily limits, circuit breakers, session gating.

This layer exists to make the stated goal — end the day without giving back
the account — enforceable, because it cannot be guaranteed by strategy alone:

  * fixed-fractional sizing: risk a fixed % of equity per trade, ATR stop
  * daily loss limit: breach -> flatten and halt until the next UTC day
  * daily profit lock: hit the target -> flatten and bank the green day
  * loss-streak breaker: N consecutive losers -> no new entries today
  * session gate: enter only in liquid hours, never after the entry cutoff
  * end-of-day flatten: no overnight exposure, ever
"""
from __future__ import annotations

from datetime import date, datetime

from .broker.paper import Trade
from .config import Config
from .sessions import SessionClock

HALT_NONE = ""
HALT_DAILY_LOSS = "daily_loss"
HALT_PROFIT_LOCK = "profit_lock"
HALT_LOSS_STREAK = "loss_streak"

# Halts that also force any open position closed (a streak halt only blocks
# new entries; the open trade may still run to its stop or target).
_FLATTEN_HALTS = {HALT_DAILY_LOSS, HALT_PROFIT_LOCK}


class RiskManager:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.clock = SessionClock(cfg.sessions, cfg.entry_cutoff, cfg.eod_flat)
        self._day: date | None = None
        self._day_start_equity: float = cfg.initial_equity
        self._trades_today = 0
        self._consecutive_losses = 0
        self.halt_reason = HALT_NONE

    # -- lifecycle -----------------------------------------------------------
    def on_bar(self, ts: datetime, equity: float) -> None:
        """Roll the trading day and check equity-based limits (mark-to-market)."""
        d = ts.date()
        if d != self._day:
            self._day = d
            self._day_start_equity = equity
            self._trades_today = 0
            self._consecutive_losses = 0
            self.halt_reason = HALT_NONE
        if self.halt_reason:
            return
        base = self._day_start_equity
        if base <= 0:
            self.halt_reason = HALT_DAILY_LOSS
            return
        day_return = (equity - base) / base
        if day_return <= -self.cfg.daily_loss_limit_pct:
            self.halt_reason = HALT_DAILY_LOSS
        elif day_return >= self.cfg.daily_profit_lock_pct:
            self.halt_reason = HALT_PROFIT_LOCK

    def on_trade_closed(self, trade: Trade) -> None:
        if trade.pnl < 0:
            self._consecutive_losses += 1
            if (
                self._consecutive_losses >= self.cfg.max_consecutive_losses
                and not self.halt_reason
            ):
                self.halt_reason = HALT_LOSS_STREAK
        else:
            self._consecutive_losses = 0

    def on_trade_opened(self) -> None:
        self._trades_today += 1

    # -- gates ---------------------------------------------------------------
    def flatten_reason(self, ts: datetime) -> str:
        """Non-empty when any open position must be closed right now."""
        if self.clock.past_eod(ts):
            return "eod"
        if self.halt_reason in _FLATTEN_HALTS:
            return self.halt_reason
        return ""

    def can_open(self, ts: datetime) -> bool:
        return (
            not self.halt_reason
            and self.clock.can_enter(ts)
            and self._trades_today < self.cfg.max_trades_per_day
        )

    # -- sizing ---------------------------------------------------------------
    def stop_distance(self, atr: float) -> float:
        return self.cfg.sl_atr_mult * atr

    def size(self, equity: float, atr: float) -> float:
        """Units (ounces) so that a stop-out loses ~risk_per_trade_pct of equity."""
        dist = self.stop_distance(atr)
        if dist <= 0 or equity <= 0:
            return 0.0
        units = (equity * self.cfg.risk_per_trade_pct) / dist
        units = min(max(units, self.cfg.min_units), self.cfg.max_units)
        step = self.cfg.unit_step
        if step > 0:
            units = int(units / step) * step
        return round(units, 6)
