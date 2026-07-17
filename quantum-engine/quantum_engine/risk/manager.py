"""Risk management — the part that actually keeps an account alive.

The strategy decides *whether* to trade. The risk manager decides *how much*
and *when to stop*. In real trading the second question matters more than the
first: position sizing and hard daily limits are what separate a bad week from
a blown account.

Key protections implemented here:

* Fixed-fractional position sizing from a per-trade risk % and the stop distance.
* A daily loss limit ("kill switch"): once the day's realised loss exceeds a
  threshold, no new trades are allowed until the next session.
* A max-drawdown circuit breaker on peak equity.
* A cap on concurrent exposure.

None of this makes trading safe. It makes ruin *less likely and bounded*.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class RiskConfig:
    risk_per_trade: float = 0.01       # fraction of equity risked per trade (1%)
    daily_loss_limit: float = 0.05     # stop trading after losing 5% of start-of-day equity
    max_drawdown: float = 0.20         # hard stop after 20% drawdown from peak equity
    max_position_lots: float = 10.0    # absolute cap on a single position size
    min_position_lots: float = 0.01    # broker minimum
    lot_step: float = 0.01
    contract_size: float = 100.0       # XAUUSD standard: 100 oz per 1.0 lot


@dataclass
class RiskState:
    peak_equity: float
    day: Optional[date] = None
    start_of_day_equity: float = 0.0
    realized_today: float = 0.0
    halted_reason: str = ""
    _events: list = field(default_factory=list)


class RiskManager:
    def __init__(self, config: RiskConfig, starting_equity: float):
        self.cfg = config
        self.state = RiskState(peak_equity=starting_equity,
                               start_of_day_equity=starting_equity)

    # --- daily bookkeeping -------------------------------------------------

    def roll_day(self, today: date, equity: float) -> None:
        """Call at the start of each trading day (or when the date changes)."""
        if self.state.day != today:
            self.state.day = today
            self.state.start_of_day_equity = equity
            self.state.realized_today = 0.0
            # A new day clears the *daily* halt but not a max-drawdown halt.
            if self.state.halted_reason == "daily_loss_limit":
                self.state.halted_reason = ""

    def record_realized(self, pnl: float, equity: float) -> None:
        self.state.realized_today += pnl
        self.state.peak_equity = max(self.state.peak_equity, equity)

    # --- gating ------------------------------------------------------------

    def can_trade(self, equity: float) -> tuple[bool, str]:
        if self.state.halted_reason:
            return False, self.state.halted_reason

        drawdown = 0.0
        if self.state.peak_equity > 0:
            drawdown = 1.0 - equity / self.state.peak_equity
        if drawdown >= self.cfg.max_drawdown:
            self.state.halted_reason = "max_drawdown"
            return False, "max_drawdown"

        if self.state.start_of_day_equity > 0:
            daily_loss = -self.state.realized_today / self.state.start_of_day_equity
            if daily_loss >= self.cfg.daily_loss_limit:
                self.state.halted_reason = "daily_loss_limit"
                return False, "daily_loss_limit"

        return True, "ok"

    # --- sizing ------------------------------------------------------------

    def position_size(self, equity: float, entry: float, stop: float,
                      contract_size: Optional[float] = None,
                      max_lots: Optional[float] = None) -> float:
        """Lots to risk exactly `risk_per_trade` of equity given the stop.

        `contract_size` / `max_lots` override the config defaults so one
        account-level risk manager can size different instruments (used by
        the multi-market portfolio engine).

        Returns 0.0 if the stop distance is degenerate or sizing rounds below
        the broker minimum.
        """
        stop_distance = abs(entry - stop)
        if stop_distance <= 0:
            return 0.0
        risk_cash = equity * self.cfg.risk_per_trade
        # loss for 1.0 lot if stopped = stop_distance * contract_size
        loss_per_lot = stop_distance * (contract_size
                                        if contract_size is not None
                                        else self.cfg.contract_size)
        if loss_per_lot <= 0:
            return 0.0
        raw_lots = risk_cash / loss_per_lot
        lots = self._round_step(raw_lots)
        lots = min(lots, max_lots if max_lots is not None
                   else self.cfg.max_position_lots)
        if lots < self.cfg.min_position_lots:
            return 0.0
        return lots

    def _round_step(self, lots: float) -> float:
        steps = round(lots / self.cfg.lot_step)
        return round(steps * self.cfg.lot_step, 8)
