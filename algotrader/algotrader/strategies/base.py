"""Strategy interface.

A strategy looks at each completed bar plus shared market context (ATR, ADX,
session VWAP) and emits a Signal: a direction in {-1, 0, +1} with a
confidence in [0, 1]. Strategies never trade — the confluence engine and the
risk manager decide whether anything actually happens.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..data.bar import Bar

FLAT = 0
LONG = 1
SHORT = -1


@dataclass(frozen=True)
class Signal:
    direction: int  # -1, 0, +1
    confidence: float  # 0..1
    reason: str = ""

    def __post_init__(self) -> None:
        if self.direction not in (-1, 0, 1):
            raise ValueError("direction must be -1, 0 or 1")
        object.__setattr__(self, "confidence", max(0.0, min(1.0, self.confidence)))


NO_SIGNAL = Signal(FLAT, 0.0, "no signal")


@dataclass(frozen=True)
class MarketContext:
    atr: float | None
    adx: float | None
    vwap: float | None

    @property
    def ready(self) -> bool:
        return self.atr is not None and self.adx is not None and self.vwap is not None


class Strategy(ABC):
    name: str = "strategy"
    kind: str = "trend"  # "trend" or "reversion" — used for regime weighting

    @abstractmethod
    def on_bar(self, bar: Bar, ctx: MarketContext) -> Signal:
        """Consume one completed bar and return the current signal."""
