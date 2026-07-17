"""Momentum breakouts for Bitcoin, 1-hour candles.

Whiteboard spec: "It waits for price to blast through a key level with heavy
volume behind it. That means it only jumps in when the move looks real. Not a
fakeout."

Implementation: the key levels are the highest high / lowest low of the prior
`lookback` bars. A close beyond the level counts only when the bar's volume is
at least `volume_mult` times the rolling average volume — the "heavy volume"
confirmation. Target is a 2R projection; the hard 1% stop is applied by the
portfolio engine.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from ..types import Bar, Side, Signal
from .base import Strategy


@dataclass
class MomentumBreakoutConfig:
    lookback: int = 20        # bars defining the key level
    volume_mult: float = 1.5  # required volume vs rolling average
    reward_r: float = 2.0     # take-profit at N times the stop distance
    stop_frac: float = 0.01   # provisional stop used for the target projection


class MomentumBreakout(Strategy):
    name = "momentum_breakout_1h"

    def __init__(self, config: MomentumBreakoutConfig | None = None):
        self.cfg = config or MomentumBreakoutConfig()
        self._highs: deque[float] = deque(maxlen=self.cfg.lookback)
        self._lows: deque[float] = deque(maxlen=self.cfg.lookback)
        self._vols: deque[float] = deque(maxlen=self.cfg.lookback)

    def warmup_bars(self) -> int:
        return self.cfg.lookback + 1

    def status(self) -> dict:
        if len(self._highs) < self.cfg.lookback:
            return {"state": "warming_up"}
        return {"state": "watching",
                "breakout_above": round(max(self._highs), 2),
                "breakout_below": round(min(self._lows), 2),
                "volume_needed_x": self.cfg.volume_mult}

    def on_bar(self, bar: Bar) -> Signal:
        if len(self._highs) < self.cfg.lookback:
            self._push(bar)
            return Signal(side=None, reason="warmup")

        key_high = max(self._highs)
        key_low = min(self._lows)
        avg_vol = sum(self._vols) / len(self._vols)
        heavy = avg_vol > 0 and bar.volume >= self.cfg.volume_mult * avg_vol
        self._push(bar)

        stop_dist = bar.close * self.cfg.stop_frac
        if bar.close > key_high:
            if not heavy:
                return Signal(side=None, reason="breakout_no_volume")
            return Signal(side=Side.BUY, strength=0.8,
                          take_profit=bar.close + self.cfg.reward_r * stop_dist,
                          reason=f"breakout_up>{key_high:.2f}")
        if bar.close < key_low:
            if not heavy:
                return Signal(side=None, reason="breakdown_no_volume")
            return Signal(side=Side.SELL, strength=0.8,
                          take_profit=bar.close - self.cfg.reward_r * stop_dist,
                          reason=f"breakout_down<{key_low:.2f}")
        return Signal(side=None, reason="inside_range")

    def _push(self, bar: Bar) -> None:
        self._highs.append(bar.high)
        self._lows.append(bar.low)
        self._vols.append(bar.volume)
