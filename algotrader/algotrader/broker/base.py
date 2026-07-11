"""Broker interface.

The engine only talks to this interface, so going live is a matter of
implementing one adapter (OANDA, MT5, IBKR, ...) — the strategy, confluence
and risk layers are untouched. Only the paper broker ships here; wire a real
adapter up to demo/paper credentials first and run it in parallel with
backtests before any real capital is involved.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..data.bar import Bar
from .paper import Position, Trade


class Broker(ABC):
    @property
    @abstractmethod
    def position(self) -> Position | None:
        """The single open position, if any (this engine trades one instrument)."""

    @abstractmethod
    def equity(self, price: float) -> float:
        """Realized cash plus mark-to-market of the open position."""

    @abstractmethod
    def mark(self, bar: Bar) -> list[Trade]:
        """Process a new bar: fill any stop-loss / take-profit that it touched."""

    @abstractmethod
    def open(self, direction: int, units: float, bar: Bar, sl: float, tp: float) -> Position:
        """Market order at the bar close (plus costs)."""

    @abstractmethod
    def close(self, bar: Bar, reason: str) -> Trade:
        """Market-close the open position at the bar close (plus costs)."""
