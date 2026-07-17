"""Slow trend following for commodities (Gold / Oil), 4-hour candles.

Whiteboard spec: "It runs a slower trend-following strategy on the 4-hour
chart. Because commodities move in cleaner waves. So you don't want entry
noise affecting your trades."

Implementation: classic dual-EMA trend definition (fast over slow = uptrend).
A position is opened when the trend flips and held until the trend flips back;
the portfolio engine closes an open position when an opposite-direction signal
arrives, which is how the flip exit works. The hard 1% stop still protects
every individual entry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..types import Bar, Side, Signal
from .base import Strategy
from .indicators import EMA


@dataclass
class TrendFollowingConfig:
    fast_ema: int = 20
    slow_ema: int = 50


class TrendFollowing(Strategy):
    name = "trend_following_4h"

    def __init__(self, config: TrendFollowingConfig | None = None):
        self.cfg = config or TrendFollowingConfig()
        self.fast = EMA(self.cfg.fast_ema)
        self.slow = EMA(self.cfg.slow_ema)
        self._bars_seen = 0
        self._last_trend: Optional[Side] = None

    def warmup_bars(self) -> int:
        return self.cfg.slow_ema + 2

    def status(self) -> dict:
        if self._bars_seen < self.warmup_bars():
            return {"state": "warming_up"}
        trend = self._last_trend.value if self._last_trend else "flat"
        return {"state": "in_trend", "trend": trend,
                "fast_ema": round(self.fast.value or 0.0, 2),
                "slow_ema": round(self.slow.value or 0.0, 2)}

    def on_bar(self, bar: Bar) -> Signal:
        fast = self.fast.update(bar.close)
        slow = self.slow.update(bar.close)
        self._bars_seen += 1
        if self._bars_seen < self.warmup_bars() or fast is None or slow is None:
            return Signal(side=None, reason="warmup")

        trend = Side.BUY if fast > slow else Side.SELL
        if trend != self._last_trend:
            self._last_trend = trend
            # Trend flip: signal in the new direction. The engine closes any
            # opposite position first (the flip exit), then enters.
            return Signal(side=trend, strength=0.7, reason="trend_flip")
        return Signal(side=None, reason="holding_trend")
