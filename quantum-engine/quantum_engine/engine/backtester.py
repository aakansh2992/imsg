"""Event-driven backtester.

Walks bars in order, feeds each to the strategy, sizes via the RiskManager, and
executes against the SimulatedBroker (spread + slippage + commission). Exits are
handled bar-by-bar: if a bar's range touches the stop or target, the position is
closed at that level (conservatively assuming the stop is hit first when a bar
straddles both — the pessimistic assumption).

Because the strategy, risk manager and broker here are the SAME objects used in
live/paper trading, a passing backtest exercises the real code path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Optional

from ..brokers.simulated import SimulatedBroker
from ..risk.manager import RiskConfig, RiskManager
from ..strategy.base import Strategy
from ..types import Bar, Order, Side


@dataclass
class Trade:
    entry_time: object
    exit_time: object
    side: Side
    size: float
    entry: float
    exit: float
    pnl: float
    reason: str


@dataclass
class BacktestResult:
    starting_equity: float
    ending_equity: float
    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)  # (timestamp, equity)
    halted_reason: str = ""

    @property
    def net_pnl(self) -> float:
        return self.ending_equity - self.starting_equity

    @property
    def return_pct(self) -> float:
        if self.starting_equity == 0:
            return 0.0
        return self.net_pnl / self.starting_equity * 100.0

    @property
    def num_trades(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if t.pnl > 0)
        return wins / len(self.trades) * 100.0

    @property
    def profit_factor(self) -> float:
        gross_win = sum(t.pnl for t in self.trades if t.pnl > 0)
        gross_loss = -sum(t.pnl for t in self.trades if t.pnl < 0)
        if gross_loss == 0:
            return float("inf") if gross_win > 0 else 0.0
        return gross_win / gross_loss

    @property
    def max_drawdown_pct(self) -> float:
        peak = self.starting_equity
        max_dd = 0.0
        for _, eq in self.equity_curve:
            peak = max(peak, eq)
            if peak > 0:
                max_dd = max(max_dd, 1.0 - eq / peak)
        return max_dd * 100.0

    def summary(self) -> str:
        return (
            f"Trades:        {self.num_trades}\n"
            f"Win rate:      {self.win_rate:.1f}%\n"
            f"Profit factor: {self.profit_factor:.2f}\n"
            f"Net P&L:       {self.net_pnl:,.2f}\n"
            f"Return:        {self.return_pct:+.2f}%\n"
            f"Max drawdown:  {self.max_drawdown_pct:.2f}%\n"
            f"Start equity:  {self.starting_equity:,.2f}\n"
            f"End equity:    {self.ending_equity:,.2f}\n"
            + (f"Halted:        {self.halted_reason}\n" if self.halted_reason else "")
        )


class Backtester:
    def __init__(
        self,
        strategy: Strategy,
        broker: Optional[SimulatedBroker] = None,
        risk: Optional[RiskManager] = None,
        risk_config: Optional[RiskConfig] = None,
        starting_equity: float = 10_000.0,
    ):
        self.strategy = strategy
        self.broker = broker or SimulatedBroker(starting_balance=starting_equity)
        self.starting_equity = self.broker.balance
        self.risk = risk or RiskManager(
            risk_config or RiskConfig(contract_size=self.broker.contract_size),
            self.starting_equity,
        )

    def run(self, bars: Iterable[Bar]) -> BacktestResult:
        result = BacktestResult(
            starting_equity=self.starting_equity,
            ending_equity=self.starting_equity,
        )

        for bar in bars:
            self.broker.set_price(bar.close)
            equity = self.broker.equity()
            self.risk.roll_day(_bar_date(bar), equity)

            pos = self.broker.position()
            if pos is not None:
                closed = self._maybe_exit(bar, result)
                if closed:
                    pos = None

            # Only look for new entries when flat and allowed to trade.
            signal = self.strategy.on_bar(bar)
            if pos is None and not signal.is_flat:
                allowed, _reason = self.risk.can_trade(self.broker.equity())
                if allowed and signal.stop_loss is not None:
                    size = self.risk.position_size(
                        self.broker.equity(), bar.close, signal.stop_loss
                    )
                    if size > 0:
                        self.broker.submit(Order(
                            symbol=self.broker.symbol,
                            side=signal.side,
                            size=size,
                            stop_loss=signal.stop_loss,
                            take_profit=signal.take_profit,
                        ))

            result.equity_curve.append((bar.timestamp, self.broker.equity()))

        # Flatten any open position at the final close.
        final = self.broker.close()
        if final is not None:
            self._record_close(final.price, "end_of_data", result)

        result.ending_equity = self.broker.equity()
        result.halted_reason = self.risk.state.halted_reason
        return result

    def _maybe_exit(self, bar: Bar, result: BacktestResult) -> bool:
        pos = self.broker.position()
        if pos is None:
            return False
        hit_stop = hit_target = False
        if pos.side is Side.BUY:
            if pos.stop_loss is not None and bar.low <= pos.stop_loss:
                hit_stop = True
            if pos.take_profit is not None and bar.high >= pos.take_profit:
                hit_target = True
        else:  # SELL
            if pos.stop_loss is not None and bar.high >= pos.stop_loss:
                hit_stop = True
            if pos.take_profit is not None and bar.low <= pos.take_profit:
                hit_target = True

        # Pessimistic: if a single bar straddles both, assume the stop first.
        if hit_stop:
            self._record_close(pos.stop_loss, "stop_loss", result)
            return True
        if hit_target:
            self._record_close(pos.take_profit, "take_profit", result)
            return True
        return False

    def _record_close(self, price: float, reason: str, result: BacktestResult) -> None:
        pos = self.broker.position()
        if pos is None:
            return
        entry = pos.entry_price
        side = pos.side
        size = pos.size
        entry_time = pos.opened_at
        balance_before = self.broker.balance
        fill = self.broker.close(price=price)
        pnl = self.broker.balance - balance_before
        self.risk.record_realized(pnl, self.broker.equity())
        result.trades.append(Trade(
            entry_time=entry_time,
            exit_time=fill.timestamp if fill else None,
            side=side, size=size, entry=entry,
            exit=price, pnl=pnl, reason=reason,
        ))


def _bar_date(bar: Bar) -> date:
    return bar.timestamp.date()
