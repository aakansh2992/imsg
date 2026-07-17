"""Multi-symbol paper broker for the 5-market portfolio bot.

One cash balance, at most one open position per symbol, per-instrument
frictions (spread/slippage/commission) and contract sizes. Paper only — this
class has no live counterpart wired in and cannot touch real money.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional

from ..types import Fill, Order, Position, Side


@dataclass
class InstrumentSpec:
    symbol: str
    contract_size: float = 1.0   # account-currency value of a 1.0-lot, 1.0-point move
    spread: float = 0.0          # full bid/ask spread in price units
    slippage: float = 0.0        # extra adverse fill in price units
    commission_per_lot: float = 0.0
    max_lots: float = 100.0
    lot_step: float = 0.01
    min_lots: float = 0.01


@dataclass
class ClosedTrade:
    symbol: str
    side: Side
    size: float
    entry: float
    exit: float
    pnl: float
    reason: str
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None


class PortfolioSimBroker:
    def __init__(self, instruments: Dict[str, InstrumentSpec],
                 starting_balance: float = 10_000.0):
        self.instruments = instruments
        self.balance = starting_balance
        self.positions: Dict[str, Position] = {}
        self.closed: list[ClosedTrade] = []
        self._prices: Dict[str, float] = {}

    # --- market data -------------------------------------------------------

    def set_price(self, symbol: str, price: float) -> None:
        self._prices[symbol] = price

    def price(self, symbol: str) -> Optional[float]:
        return self._prices.get(symbol)

    # --- account -----------------------------------------------------------

    def equity(self) -> float:
        eq = self.balance
        for sym, pos in self.positions.items():
            px = self._prices.get(sym)
            if px is not None:
                eq += pos.unrealized_pnl(px, self.instruments[sym].contract_size)
        return eq

    def position(self, symbol: str) -> Optional[Position]:
        return self.positions.get(symbol)

    # --- trading -----------------------------------------------------------

    def open(self, order: Order, timestamp: Optional[datetime] = None) -> Fill:
        sym = order.symbol
        if sym in self.positions:
            raise RuntimeError(f"{sym}: position already open; close it first")
        spec = self.instruments[sym]
        px = self._prices.get(sym)
        if px is None:
            raise RuntimeError(f"{sym}: no price seen yet")
        fill_price = self._fill_price(spec, px, order.side)
        commission = spec.commission_per_lot * order.size
        self.balance -= commission
        self.positions[sym] = Position(
            symbol=sym, side=order.side, size=order.size,
            entry_price=fill_price, stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            opened_at=timestamp or datetime.utcnow(),
        )
        return Fill(order=order, price=fill_price,
                    timestamp=timestamp or datetime.utcnow(),
                    commission=commission)

    def close(self, symbol: str, price: Optional[float] = None,
              reason: str = "close", timestamp: Optional[datetime] = None
              ) -> Optional[ClosedTrade]:
        pos = self.positions.get(symbol)
        if pos is None:
            return None
        spec = self.instruments[symbol]
        if price is None:
            px = self._prices.get(symbol)
            if px is None:
                raise RuntimeError(f"{symbol}: no price to close at")
            price = self._fill_price(spec, px, pos.side.opposite)
        pnl = ((price - pos.entry_price) * pos.side.sign
               * pos.size * spec.contract_size)
        commission = spec.commission_per_lot * pos.size
        self.balance += pnl - commission
        del self.positions[symbol]
        trade = ClosedTrade(symbol=symbol, side=pos.side, size=pos.size,
                            entry=pos.entry_price, exit=price,
                            pnl=pnl - commission, reason=reason,
                            entry_time=pos.opened_at,
                            exit_time=timestamp or datetime.utcnow())
        self.closed.append(trade)
        return trade

    @staticmethod
    def _fill_price(spec: InstrumentSpec, mid: float, side: Side) -> float:
        half = spec.spread / 2.0
        if side is Side.BUY:
            return mid + half + spec.slippage
        return mid - half - spec.slippage
