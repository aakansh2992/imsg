"""MACD histogram momentum — direction from the histogram sign, but only
when the histogram is also expanding in that direction (accelerating move)."""
from __future__ import annotations

from ..data.bar import Bar
from ..indicators import MACD
from .base import LONG, NO_SIGNAL, SHORT, MarketContext, Signal, Strategy


class MACDMomentum(Strategy):
    name = "macd_momentum"
    kind = "trend"

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9) -> None:
        self._macd = MACD(fast, slow, signal)

    def on_bar(self, bar: Bar, ctx: MarketContext) -> Signal:
        self._macd.update(bar.close)
        m = self._macd
        if m.hist is None or m.prev_hist is None or not ctx.atr:
            return NO_SIGNAL
        if m.hist > 0 and m.hist >= m.prev_hist:
            direction = LONG
        elif m.hist < 0 and m.hist <= m.prev_hist:
            direction = SHORT
        else:
            return NO_SIGNAL
        confidence = min(1.0, abs(m.hist) / (0.5 * ctx.atr))
        return Signal(direction, confidence, f"macd hist {m.hist:+.2f}")
