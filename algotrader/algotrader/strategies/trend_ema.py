"""EMA crossover trend following — long when the fast EMA is meaningfully
above the slow EMA (separation measured in ATRs so it adapts to volatility)."""
from __future__ import annotations

from ..data.bar import Bar
from ..indicators import EMA
from .base import LONG, NO_SIGNAL, SHORT, MarketContext, Signal, Strategy


class TrendEMA(Strategy):
    name = "trend_ema"
    kind = "trend"

    def __init__(self, fast: int = 21, slow: int = 55, min_sep_atr: float = 0.10) -> None:
        self._fast = EMA(fast)
        self._slow = EMA(slow)
        self._min_sep_atr = min_sep_atr

    def on_bar(self, bar: Bar, ctx: MarketContext) -> Signal:
        f = self._fast.update(bar.close)
        s = self._slow.update(bar.close)
        if f is None or s is None or not ctx.atr:
            return NO_SIGNAL
        sep_atr = (f - s) / ctx.atr
        if abs(sep_atr) < self._min_sep_atr:
            return NO_SIGNAL
        direction = LONG if sep_atr > 0 else SHORT
        confidence = min(1.0, abs(sep_atr) / 0.75)
        return Signal(direction, confidence, f"ema sep {sep_atr:+.2f} ATR")
