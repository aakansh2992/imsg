"""Strategy interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..types import Bar, Signal


class Strategy(ABC):
    """A strategy consumes bars one at a time and emits a Signal.

    Implementations must be causal: they may only use information from the
    current and prior bars. The backtester relies on this to avoid look-ahead.
    """

    name: str = "strategy"

    @abstractmethod
    def on_bar(self, bar: Bar) -> Signal:
        """Process one bar and return the desired signal."""

    def warmup_bars(self) -> int:
        """Number of leading bars needed before signals are trustworthy."""
        return 0
