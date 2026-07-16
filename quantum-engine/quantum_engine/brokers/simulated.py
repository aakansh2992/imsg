"""SimulatedBroker — a paper-trading backend.

Models the frictions that destroy naive backtests: bid/ask spread, slippage,
and per-lot commission. It is deliberately conservative so that paper results
lean pessimistic rather than optimistic. This is the DEFAULT backend; nothing
here touches real money.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from ..types import AccountState, Fill, Order, Position, Side
from .base import BrokerAdapter


class SimulatedBroker(BrokerAdapter):
    def __init__(
        self,
        symbol: str = "XAUUSD",
        starting_balance: float = 10_000.0,
        spread: float = 0.20,          # price units (USD) between bid and ask
        slippage: float = 0.05,        # extra adverse fill, price units
        commission_per_lot: float = 0.0,
        contract_size: float = 100.0,
    ):
        self.symbol = symbol
        self.balance = starting_balance
        self.spread = spread
        self.slippage = slippage
        self.commission_per_lot = commission_per_lot
        self.contract_size = contract_size
        self._position: Optional[Position] = None
        self._last_price: float = 0.0

    # --- price feed hook ---------------------------------------------------

    def set_price(self, price: float) -> None:
        """The engine pushes the latest mid price here each bar/tick."""
        self._last_price = price

    def _bid(self) -> float:
        return self._last_price - self.spread / 2.0

    def _ask(self) -> float:
        return self._last_price + self.spread / 2.0

    # --- BrokerAdapter -----------------------------------------------------

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def account(self) -> AccountState:
        return AccountState(
            balance=self.balance,
            equity=self.equity(),
            positions=[self._position] if self._position else [],
        )

    def equity(self) -> float:
        if self._position is None:
            return self.balance
        return self.balance + self._position.unrealized_pnl(
            self._last_price, self.contract_size
        )

    def position(self) -> Optional[Position]:
        return self._position

    def submit(self, order: Order) -> Fill:
        if self._position is not None:
            raise RuntimeError("SimulatedBroker holds one position at a time; "
                               "close before opening a new one.")
        fill_price = self._fill_price(order.side)
        commission = self.commission_per_lot * order.size
        self.balance -= commission
        self._position = Position(
            symbol=self.symbol,
            side=order.side,
            size=order.size,
            entry_price=fill_price,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            opened_at=datetime.utcnow(),
        )
        return Fill(order=order, price=fill_price, timestamp=datetime.utcnow(),
                    commission=commission)

    def close(self, price: Optional[float] = None) -> Optional[Fill]:
        if self._position is None:
            return None
        pos = self._position
        # Exit crosses the spread in the adverse direction.
        exit_side = pos.side.opposite
        fill_price = price if price is not None else self._fill_price(exit_side)
        pnl = (fill_price - pos.entry_price) * pos.side.sign * pos.size * self.contract_size
        commission = self.commission_per_lot * pos.size
        self.balance += pnl - commission
        self._position = None
        close_order = Order(symbol=self.symbol, side=exit_side, size=pos.size)
        return Fill(order=close_order, price=fill_price,
                    timestamp=datetime.utcnow(), commission=commission)

    def _fill_price(self, side: Side) -> float:
        # Buy pays the ask + slippage; sell hits the bid - slippage.
        if side is Side.BUY:
            return self._ask() + self.slippage
        return self._bid() - self.slippage
