"""Session-VWAP deviation fade — when price stretches multiple ATRs away
from the session VWAP, expect a snap back toward it."""
from __future__ import annotations

from ..data.bar import Bar
from .base import LONG, NO_SIGNAL, SHORT, MarketContext, Signal, Strategy


class VWAPDeviation(Strategy):
    name = "vwap_deviation"
    kind = "reversion"

    def __init__(self, dev_threshold_atr: float = 2.0) -> None:
        self._threshold = dev_threshold_atr

    def on_bar(self, bar: Bar, ctx: MarketContext) -> Signal:
        if ctx.vwap is None or not ctx.atr:
            return NO_SIGNAL
        dev = (bar.close - ctx.vwap) / ctx.atr
        if dev >= self._threshold:
            confidence = min(1.0, 0.5 + (dev - self._threshold) / self._threshold)
            return Signal(SHORT, confidence, f"{dev:+.2f} ATR above vwap")
        if dev <= -self._threshold:
            confidence = min(1.0, 0.5 + (-dev - self._threshold) / self._threshold)
            return Signal(LONG, confidence, f"{dev:+.2f} ATR below vwap")
        return NO_SIGNAL
