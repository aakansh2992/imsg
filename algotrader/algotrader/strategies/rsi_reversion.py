"""RSI + Bollinger mean reversion — fade extremes only when both agree:
oversold RSI *and* a close beyond the lower band (and vice versa)."""
from __future__ import annotations

from ..data.bar import Bar
from ..indicators import RSI, Bollinger
from .base import LONG, NO_SIGNAL, SHORT, MarketContext, Signal, Strategy


class RSIReversion(Strategy):
    name = "rsi_reversion"
    kind = "reversion"

    def __init__(
        self,
        rsi_period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        boll_period: int = 20,
        boll_k: float = 2.0,
    ) -> None:
        self._rsi = RSI(rsi_period)
        self._boll = Bollinger(boll_period, boll_k)
        self._oversold = oversold
        self._overbought = overbought

    def on_bar(self, bar: Bar, ctx: MarketContext) -> Signal:
        rsi = self._rsi.update(bar.close)
        self._boll.update(bar.close)
        if rsi is None or not self._boll.ready:
            return NO_SIGNAL
        if rsi <= self._oversold and bar.close <= self._boll.lower:
            confidence = min(1.0, 0.5 + (self._oversold - rsi) / self._oversold)
            return Signal(LONG, confidence, f"rsi {rsi:.0f} below band")
        if rsi >= self._overbought and bar.close >= self._boll.upper:
            confidence = min(1.0, 0.5 + (rsi - self._overbought) / (100.0 - self._overbought))
            return Signal(SHORT, confidence, f"rsi {rsi:.0f} above band")
        return NO_SIGNAL
