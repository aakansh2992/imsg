"""Market-structure (SMC/ICT-style) strategies, expressed as testable rules.

These are deliberately mechanical translations of the discretionary concepts:

* Swing points: fractal pivots — a bar whose high is strictly above the k
  bars on each side is a swing high (confirmed k bars late, no lookahead).
* Liquidity sweep: price wicks through the last swing high (where stops
  cluster) but closes back below it — fade the stop-hunt. Reversion family.
* BOS (break of structure): close beyond the last swing in the direction of
  the prevailing structure — continuation. CHoCH (change of character):
  close beyond the last opposite swing against the prevailing structure —
  early reversal, taken at lower confidence. Trend family.

They only vote; confluence and risk still gate everything. Note that these
patterns exploit the behaviour of *other traders'* stops — synthetic
random-walk data contains no traders, so only real market data can say
whether they add edge (see README).
"""
from __future__ import annotations

from collections import deque

from ..data.bar import Bar
from .base import LONG, NO_SIGNAL, SHORT, MarketContext, Signal, Strategy


class SwingDetector:
    """Confirms fractal swing highs/lows k bars after they form."""

    def __init__(self, k: int = 3) -> None:
        self.k = k
        self._highs: deque[float] = deque(maxlen=2 * k + 1)
        self._lows: deque[float] = deque(maxlen=2 * k + 1)
        self.swing_high: float | None = None
        self.swing_low: float | None = None

    def update(self, high: float, low: float) -> None:
        self._highs.append(high)
        self._lows.append(low)
        if len(self._highs) < self._highs.maxlen:
            return
        k = self.k
        hs, ls = list(self._highs), list(self._lows)
        h, lo = hs[k], ls[k]
        if all(h > hs[j] for j in range(len(hs)) if j != k):
            self.swing_high = h
        if all(lo < ls[j] for j in range(len(ls)) if j != k):
            self.swing_low = lo


class LiquiditySweep(Strategy):
    name = "liquidity_sweep"
    kind = "reversion"

    def __init__(self, k: int = 3, min_pierce_atr: float = 0.1) -> None:
        self._swings = SwingDetector(k)
        self._min_pierce = min_pierce_atr

    def on_bar(self, bar: Bar, ctx: MarketContext) -> Signal:
        sw = self._swings
        signal = NO_SIGNAL
        if ctx.atr:
            if (
                sw.swing_high is not None
                and bar.high > sw.swing_high
                and bar.close < sw.swing_high
            ):
                pierce = (bar.high - sw.swing_high) / ctx.atr
                if pierce >= self._min_pierce:
                    signal = Signal(SHORT, min(1.0, 0.5 + pierce / 1.0),
                                    f"swept high, pierce {pierce:.2f} ATR")
                    sw.swing_high = None  # consumed — don't re-fire on this level
            elif (
                sw.swing_low is not None
                and bar.low < sw.swing_low
                and bar.close > sw.swing_low
            ):
                pierce = (sw.swing_low - bar.low) / ctx.atr
                if pierce >= self._min_pierce:
                    signal = Signal(LONG, min(1.0, 0.5 + pierce / 1.0),
                                    f"swept low, pierce {pierce:.2f} ATR")
                    sw.swing_low = None
        self._swings.update(bar.high, bar.low)
        return signal


class BOSCHoCH(Strategy):
    name = "bos_choch"
    kind = "trend"

    def __init__(self, k: int = 3) -> None:
        self._swings = SwingDetector(k)
        self._trend = 0  # prevailing structure: +1 up, -1 down, 0 unknown

    def on_bar(self, bar: Bar, ctx: MarketContext) -> Signal:
        sw = self._swings
        signal = NO_SIGNAL
        if ctx.atr:
            broke_high = sw.swing_high is not None and bar.close > sw.swing_high
            broke_low = sw.swing_low is not None and bar.close < sw.swing_low
            if broke_high:
                margin = (bar.close - sw.swing_high) / ctx.atr
                if self._trend >= 0:  # BOS: continuation (or first break)
                    signal = Signal(LONG, min(1.0, 0.4 + margin / 0.5), "BOS up")
                else:  # CHoCH: structure flips — early, lower conviction
                    signal = Signal(LONG, min(0.6, 0.3 + margin / 0.5), "CHoCH up")
                self._trend = 1
                sw.swing_high = None
            elif broke_low:
                margin = (sw.swing_low - bar.close) / ctx.atr
                if self._trend <= 0:
                    signal = Signal(SHORT, min(1.0, 0.4 + margin / 0.5), "BOS down")
                else:
                    signal = Signal(SHORT, min(0.6, 0.3 + margin / 0.5), "CHoCH down")
                self._trend = -1
                sw.swing_low = None
        self._swings.update(bar.high, bar.low)
        return signal
