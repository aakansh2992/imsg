"""Donchian channel breakout — close beyond the high/low of the previous N
bars, confidence scaled by how far past the channel the close is (in ATRs)."""
from __future__ import annotations

from ..data.bar import Bar
from ..indicators import Donchian
from .base import LONG, NO_SIGNAL, SHORT, MarketContext, Signal, Strategy


class DonchianBreakout(Strategy):
    name = "donchian_breakout"
    kind = "trend"

    def __init__(self, period: int = 20) -> None:
        self._channel = Donchian(period)

    def on_bar(self, bar: Bar, ctx: MarketContext) -> Signal:
        # Read the channel of the *prior* N bars before feeding the current one.
        self._channel.update(bar.high, bar.low)
        ch = self._channel
        if not ch.ready or not ctx.atr:
            return NO_SIGNAL
        if bar.close > ch.upper:
            dist = (bar.close - ch.upper) / ctx.atr
            return Signal(LONG, min(1.0, 0.4 + dist / 0.5), f"breakout +{dist:.2f} ATR")
        if bar.close < ch.lower:
            dist = (ch.lower - bar.close) / ctx.atr
            return Signal(SHORT, min(1.0, 0.4 + dist / 0.5), f"breakdown -{dist:.2f} ATR")
        return NO_SIGNAL
