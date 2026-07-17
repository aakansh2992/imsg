"""Pure-Python streaming technical indicators.

Each indicator is an object you feed one value at a time via ``update`` and read
the latest reading from ``value``. Streaming (rather than vectorised) form keeps
the backtester and the live loop using the exact same code path — no look-ahead
bugs from accidentally referencing future bars.
"""

from __future__ import annotations

from collections import deque
from typing import Optional


class EMA:
    """Exponential moving average."""

    def __init__(self, period: int):
        if period < 1:
            raise ValueError("period must be >= 1")
        self.period = period
        self.alpha = 2.0 / (period + 1.0)
        self.value: Optional[float] = None

    def update(self, x: float) -> Optional[float]:
        if self.value is None:
            self.value = x
        else:
            self.value = self.alpha * x + (1.0 - self.alpha) * self.value
        return self.value


class SMA:
    def __init__(self, period: int):
        if period < 1:
            raise ValueError("period must be >= 1")
        self.period = period
        self._buf: deque[float] = deque(maxlen=period)
        self.value: Optional[float] = None

    def update(self, x: float) -> Optional[float]:
        self._buf.append(x)
        if len(self._buf) == self.period:
            self.value = sum(self._buf) / self.period
        return self.value


class RSI:
    """Wilder's RSI on close-to-close changes."""

    def __init__(self, period: int = 14):
        self.period = period
        self._prev: Optional[float] = None
        self._avg_gain: Optional[float] = None
        self._avg_loss: Optional[float] = None
        self._count = 0
        self.value: Optional[float] = None

    def update(self, close: float) -> Optional[float]:
        if self._prev is None:
            self._prev = close
            return None
        change = close - self._prev
        self._prev = close
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        self._count += 1
        if self._avg_gain is None:
            # Seed with simple averages over the first `period` deltas.
            self._avg_gain = gain
            self._avg_loss = loss
        else:
            self._avg_gain = (self._avg_gain * (self.period - 1) + gain) / self.period
            self._avg_loss = (self._avg_loss * (self.period - 1) + loss) / self.period
        if self._count < self.period:
            return None
        if self._avg_loss == 0:
            self.value = 100.0
        else:
            rs = self._avg_gain / self._avg_loss
            self.value = 100.0 - (100.0 / (1.0 + rs))
        return self.value


class ATR:
    """Average True Range (Wilder smoothing). Feed full bars."""

    def __init__(self, period: int = 14):
        self.period = period
        self._prev_close: Optional[float] = None
        self.value: Optional[float] = None
        self._count = 0

    def update(self, high: float, low: float, close: float) -> Optional[float]:
        if self._prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
        self._prev_close = close
        self._count += 1
        if self.value is None:
            self.value = tr
        else:
            self.value = (self.value * (self.period - 1) + tr) / self.period
        if self._count < self.period:
            return None
        return self.value


class RollingVWAP:
    """Rolling volume-weighted average price over a window of N bars.

    Falls back to a simple typical-price average when volume is absent (many
    retail XAUUSD feeds report zero tick volume).
    """

    def __init__(self, window: int = 20):
        self.window = window
        self._pv: deque[float] = deque(maxlen=window)
        self._v: deque[float] = deque(maxlen=window)
        self.value: Optional[float] = None

    def update(self, typical_price: float, volume: float) -> Optional[float]:
        v = volume if volume > 0 else 1.0
        self._pv.append(typical_price * v)
        self._v.append(v)
        total_v = sum(self._v)
        if total_v > 0:
            self.value = sum(self._pv) / total_v
        return self.value
