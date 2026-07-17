"""Core domain types shared across the engine.

Everything is plain dataclasses so the framework has no hard dependency on a
particular numeric stack. Prices are floats; sizes are in lots unless noted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1

    @property
    def opposite(self) -> "Side":
        return Side.SELL if self is Side.BUY else Side.BUY


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


@dataclass(frozen=True)
class Bar:
    """A single OHLCV candle."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def typical(self) -> float:
        return (self.high + self.low + self.close) / 3.0


@dataclass(frozen=True)
class Tick:
    timestamp: datetime
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return self.ask - self.bid


@dataclass
class Signal:
    """A strategy's intent for the current bar."""

    side: Optional[Side]  # None means "no trade / flat"
    strength: float = 0.0  # 0..1 confidence, informational
    stop_loss: Optional[float] = None  # absolute price
    take_profit: Optional[float] = None  # absolute price
    reason: str = ""

    @property
    def is_flat(self) -> bool:
        return self.side is None


@dataclass
class Order:
    symbol: str
    side: Side
    size: float  # lots
    order_type: OrderType = OrderType.MARKET
    price: Optional[float] = None  # for limit/stop
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    client_id: str = ""


@dataclass
class Position:
    symbol: str
    side: Side
    size: float
    entry_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    opened_at: Optional[datetime] = None

    def unrealized_pnl(self, price: float, contract_size: float) -> float:
        return (price - self.entry_price) * self.side.sign * self.size * contract_size


@dataclass
class Fill:
    order: Order
    price: float
    timestamp: datetime
    commission: float = 0.0


@dataclass
class AccountState:
    balance: float
    equity: float
    positions: list = field(default_factory=list)
