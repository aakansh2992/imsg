"""Live / paper trading loop.

Same decision logic as the backtester, but driven by a real-time bar stream and
executing against whatever BrokerAdapter you pass (SimulatedBroker for paper,
MT5Broker for live). Exits are managed here in code rather than relying solely
on broker-side SL/TP, so behaviour matches the backtest.

DEFAULT IS PAPER. Passing a live adapter is an explicit, deliberate act that
requires allow_live=True on that adapter. See README risk section.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

from ..brokers.base import BrokerAdapter
from ..brokers.simulated import SimulatedBroker
from ..risk.manager import RiskManager
from ..strategy.base import Strategy
from ..types import Bar, Order, Side

logger = logging.getLogger("quantum_engine.live")


class LiveTrader:
    def __init__(
        self,
        strategy: Strategy,
        broker: BrokerAdapter,
        risk: RiskManager,
        symbol: str = "XAUUSD",
    ):
        self.strategy = strategy
        self.broker = broker
        self.risk = risk
        self.symbol = symbol
        self._is_paper = isinstance(broker, SimulatedBroker)

    def run(self, bar_stream: Iterable[Bar], max_bars: Optional[int] = None) -> None:
        mode = "PAPER" if self._is_paper else "LIVE (REAL MONEY)"
        logger.warning("Starting LiveTrader in %s mode on %s", mode, self.symbol)
        self.broker.connect()
        try:
            for i, bar in enumerate(bar_stream):
                if max_bars is not None and i >= max_bars:
                    break
                self._on_bar(bar)
        finally:
            self.broker.disconnect()

    def _on_bar(self, bar: Bar) -> None:
        if isinstance(self.broker, SimulatedBroker):
            self.broker.set_price(bar.close)

        account = self.broker.account()
        equity = account.equity
        self.risk.roll_day(bar.timestamp.date(), equity)

        pos = self.broker.position()
        if pos is not None:
            self._manage_exit(bar, pos)
            pos = self.broker.position()

        signal = self.strategy.on_bar(bar)
        if pos is None and not signal.is_flat and signal.stop_loss is not None:
            allowed, reason = self.risk.can_trade(equity)
            if not allowed:
                logger.info("Trade blocked by risk manager: %s", reason)
                return
            size = self.risk.position_size(equity, bar.close, signal.stop_loss)
            if size <= 0:
                return
            order = Order(symbol=self.symbol, side=signal.side, size=size,
                          stop_loss=signal.stop_loss, take_profit=signal.take_profit)
            fill = self.broker.submit(order)
            logger.info("Opened %s %.2f lots @ %.3f (%s)", signal.side.value,
                        size, fill.price, signal.reason)

    def _manage_exit(self, bar: Bar, pos) -> None:
        hit = None
        if pos.side is Side.BUY:
            if pos.stop_loss is not None and bar.low <= pos.stop_loss:
                hit = ("stop_loss", pos.stop_loss)
            elif pos.take_profit is not None and bar.high >= pos.take_profit:
                hit = ("take_profit", pos.take_profit)
        else:
            if pos.stop_loss is not None and bar.high >= pos.stop_loss:
                hit = ("stop_loss", pos.stop_loss)
            elif pos.take_profit is not None and bar.low <= pos.take_profit:
                hit = ("take_profit", pos.take_profit)
        if hit is None:
            return
        reason, price = hit
        balance_before = getattr(self.broker, "balance", None)
        fill = self.broker.close(price=price if self._is_paper else None)
        if fill is not None:
            equity = self.broker.account().equity
            if balance_before is not None and hasattr(self.broker, "balance"):
                self.risk.record_realized(self.broker.balance - balance_before, equity)
            logger.info("Closed via %s @ %.3f", reason, fill.price)
