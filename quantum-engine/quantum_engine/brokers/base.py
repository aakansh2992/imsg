"""Broker adapter interface.

The whole point of this layer is that the engine never knows which broker it is
talking to. Implement these six methods for any venue — MetaTrader 5, OANDA,
a crypto exchange via ccxt, or the built-in simulator — and the rest of the
framework works unchanged.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..types import AccountState, Fill, Order, Position


class BrokerAdapter(ABC):
    """Minimal contract every broker backend must satisfy."""

    symbol: str

    @abstractmethod
    def connect(self) -> None:
        """Establish a session. Raise on failure."""

    @abstractmethod
    def disconnect(self) -> None:
        ...

    @abstractmethod
    def account(self) -> AccountState:
        """Current balance, equity and open positions."""

    @abstractmethod
    def position(self) -> Optional[Position]:
        """The open position for this symbol, if any (single-position model)."""

    @abstractmethod
    def submit(self, order: Order) -> Fill:
        """Send an order and return the resulting fill."""

    @abstractmethod
    def close(self, price: Optional[float] = None) -> Optional[Fill]:
        """Flatten the open position for this symbol. No-op if flat."""
