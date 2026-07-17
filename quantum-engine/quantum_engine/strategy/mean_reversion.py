"""Mean reversion for index markets (S&P 500 / NASDAQ), 15-minute candles.

Whiteboard spec: "When price stretches too far in one direction, the bot
catches the snapback. Small moves. Consistent returns."

Implementation: rolling mean and standard deviation of closes; when the close
stretches beyond `entry_z` standard deviations from the mean, enter against the
stretch with the take-profit at the mean (the snapback target). The hard 1%
stop from the risk spec is applied by the portfolio engine on top of this.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import sqrt

from ..types import Bar, Side, Signal
from .base import Strategy


@dataclass
class MeanReversionConfig:
    period: int = 20        # rolling window of closes
    entry_z: float = 2.0    # stretch (in std devs) required to enter
    min_std: float = 1e-9   # guard against flat series


class MeanReversion(Strategy):
    name = "mean_reversion_15m"

    def __init__(self, config: MeanReversionConfig | None = None):
        self.cfg = config or MeanReversionConfig()
        self._closes: deque[float] = deque(maxlen=self.cfg.period)

    def warmup_bars(self) -> int:
        return self.cfg.period + 1

    def status(self) -> dict:
        if len(self._closes) < self.cfg.period:
            return {"state": "warming_up"}
        mean, std = self._mean_std()
        last = self._closes[-1]
        z = (last - mean) / std if std > self.cfg.min_std else 0.0
        return {"state": "watching", "mean": round(mean, 2), "z": round(z, 2),
                "entry_z": self.cfg.entry_z}

    def _mean_std(self) -> tuple[float, float]:
        n = len(self._closes)
        mean = sum(self._closes) / n
        var = sum((c - mean) ** 2 for c in self._closes) / n
        return mean, sqrt(var)

    def on_bar(self, bar: Bar) -> Signal:
        self._closes.append(bar.close)
        if len(self._closes) < self.cfg.period:
            return Signal(side=None, reason="warmup")
        mean, std = self._mean_std()
        if std <= self.cfg.min_std:
            return Signal(side=None, reason="flat_market")
        z = (bar.close - mean) / std

        if z <= -self.cfg.entry_z:
            # Stretched down -> buy the snapback toward the mean.
            return Signal(side=Side.BUY, strength=min(1.0, abs(z) / 4.0),
                          take_profit=mean, reason=f"stretch_down z={z:.2f}")
        if z >= self.cfg.entry_z:
            return Signal(side=Side.SELL, strength=min(1.0, abs(z) / 4.0),
                          take_profit=mean, reason=f"stretch_up z={z:.2f}")
        return Signal(side=None, reason="inside_band")
