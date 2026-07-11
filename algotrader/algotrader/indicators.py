"""Streaming technical indicators (stdlib only).

Every indicator is incremental: call ``update()`` exactly once per completed
bar. ``ready`` is False (and values are None) until the warmup window has
been seen, so callers never act on partial data.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from math import sqrt


class EMA:
    """Exponential moving average seeded with an SMA of the first `period` values."""

    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self.period = period
        self._k = 2.0 / (period + 1.0)
        self._seed: list[float] = []
        self.value: float | None = None

    @property
    def ready(self) -> bool:
        return self.value is not None

    def update(self, x: float) -> float | None:
        if self.value is None:
            self._seed.append(x)
            if len(self._seed) == self.period:
                self.value = sum(self._seed) / self.period
                self._seed.clear()
        else:
            self.value += self._k * (x - self.value)
        return self.value


class RSI:
    """Wilder's RSI."""

    def __init__(self, period: int = 14) -> None:
        self.period = period
        self._prev: float | None = None
        self._seed_gains: list[float] = []
        self._seed_losses: list[float] = []
        self._avg_gain: float | None = None
        self._avg_loss: float | None = None
        self.value: float | None = None

    @property
    def ready(self) -> bool:
        return self.value is not None

    def update(self, close: float) -> float | None:
        if self._prev is None:
            self._prev = close
            return None
        change = close - self._prev
        self._prev = close
        gain, loss = max(change, 0.0), max(-change, 0.0)
        if self._avg_gain is None:
            self._seed_gains.append(gain)
            self._seed_losses.append(loss)
            if len(self._seed_gains) == self.period:
                self._avg_gain = sum(self._seed_gains) / self.period
                self._avg_loss = sum(self._seed_losses) / self.period
        else:
            p = self.period
            self._avg_gain = (self._avg_gain * (p - 1) + gain) / p
            self._avg_loss = (self._avg_loss * (p - 1) + loss) / p
        if self._avg_gain is not None:
            if self._avg_loss == 0:
                self.value = 100.0
            else:
                rs = self._avg_gain / self._avg_loss
                self.value = 100.0 - 100.0 / (1.0 + rs)
        return self.value


class ATR:
    """Wilder's average true range."""

    def __init__(self, period: int = 14) -> None:
        self.period = period
        self._prev_close: float | None = None
        self._seed: list[float] = []
        self.value: float | None = None

    @property
    def ready(self) -> bool:
        return self.value is not None

    def update(self, high: float, low: float, close: float) -> float | None:
        if self._prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
        self._prev_close = close
        if self.value is None:
            self._seed.append(tr)
            if len(self._seed) == self.period:
                self.value = sum(self._seed) / self.period
                self._seed.clear()
        else:
            self.value = (self.value * (self.period - 1) + tr) / self.period
        return self.value


class MACD:
    """MACD line, signal line, and histogram (with previous histogram kept)."""

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9) -> None:
        self._fast = EMA(fast)
        self._slow = EMA(slow)
        self._signal = EMA(signal)
        self.macd: float | None = None
        self.signal: float | None = None
        self.hist: float | None = None
        self.prev_hist: float | None = None

    @property
    def ready(self) -> bool:
        return self.hist is not None

    def update(self, close: float) -> None:
        f = self._fast.update(close)
        s = self._slow.update(close)
        if f is None or s is None:
            return
        self.macd = f - s
        sig = self._signal.update(self.macd)
        if sig is None:
            return
        self.signal = sig
        self.prev_hist = self.hist
        self.hist = self.macd - sig


class Bollinger:
    """Simple-MA Bollinger bands over a rolling window."""

    def __init__(self, period: int = 20, k: float = 2.0) -> None:
        self.k = k
        self._win: deque[float] = deque(maxlen=period)
        self.mid: float | None = None
        self.upper: float | None = None
        self.lower: float | None = None

    @property
    def ready(self) -> bool:
        return self.mid is not None

    def update(self, close: float) -> None:
        self._win.append(close)
        if len(self._win) < self._win.maxlen:
            return
        n = len(self._win)
        mean = sum(self._win) / n
        var = sum((x - mean) ** 2 for x in self._win) / n
        std = sqrt(var)
        self.mid = mean
        self.upper = mean + self.k * std
        self.lower = mean - self.k * std


class ADX:
    """Wilder's ADX with DI+ / DI-."""

    def __init__(self, period: int = 14) -> None:
        self.period = period
        self._prev_high: float | None = None
        self._prev_low: float | None = None
        self._prev_close: float | None = None
        self._s_tr: float | None = None  # Wilder-smoothed sums
        self._s_pdm: float | None = None
        self._s_ndm: float | None = None
        self._seed_tr: list[float] = []
        self._seed_pdm: list[float] = []
        self._seed_ndm: list[float] = []
        self._seed_dx: list[float] = []
        self.di_plus: float | None = None
        self.di_minus: float | None = None
        self.value: float | None = None  # the ADX itself

    @property
    def ready(self) -> bool:
        return self.value is not None

    def update(self, high: float, low: float, close: float) -> float | None:
        if self._prev_close is None:
            self._prev_high, self._prev_low, self._prev_close = high, low, close
            return None
        up = high - self._prev_high
        dn = self._prev_low - low
        pdm = up if (up > dn and up > 0) else 0.0
        ndm = dn if (dn > up and dn > 0) else 0.0
        tr = max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
        self._prev_high, self._prev_low, self._prev_close = high, low, close

        p = self.period
        if self._s_tr is None:
            self._seed_tr.append(tr)
            self._seed_pdm.append(pdm)
            self._seed_ndm.append(ndm)
            if len(self._seed_tr) < p:
                return None
            self._s_tr = sum(self._seed_tr)
            self._s_pdm = sum(self._seed_pdm)
            self._s_ndm = sum(self._seed_ndm)
        else:
            self._s_tr = self._s_tr - self._s_tr / p + tr
            self._s_pdm = self._s_pdm - self._s_pdm / p + pdm
            self._s_ndm = self._s_ndm - self._s_ndm / p + ndm

        if self._s_tr <= 0:
            return self.value
        self.di_plus = 100.0 * self._s_pdm / self._s_tr
        self.di_minus = 100.0 * self._s_ndm / self._s_tr
        di_sum = self.di_plus + self.di_minus
        dx = 0.0 if di_sum == 0 else 100.0 * abs(self.di_plus - self.di_minus) / di_sum
        if self.value is None:
            self._seed_dx.append(dx)
            if len(self._seed_dx) == p:
                self.value = sum(self._seed_dx) / p
                self._seed_dx.clear()
        else:
            self.value = (self.value * (p - 1) + dx) / p
        return self.value


class Donchian:
    """Channel over the *previous* `period` bars — the current bar is excluded,
    so a close above ``upper`` is a genuine breakout of prior structure."""

    def __init__(self, period: int = 20) -> None:
        self.period = period
        self._highs: deque[float] = deque(maxlen=period)
        self._lows: deque[float] = deque(maxlen=period)
        self.upper: float | None = None
        self.lower: float | None = None

    @property
    def ready(self) -> bool:
        return self.upper is not None

    def update(self, high: float, low: float) -> None:
        if len(self._highs) == self.period:
            self.upper = max(self._highs)
            self.lower = min(self._lows)
        self._highs.append(high)
        self._lows.append(low)


class SessionVWAP:
    """Volume-weighted average price, reset at each new UTC trading date."""

    def __init__(self) -> None:
        self._date = None
        self._pv = 0.0
        self._vol = 0.0
        self.value: float | None = None

    @property
    def ready(self) -> bool:
        return self.value is not None

    def update(self, ts: datetime, high: float, low: float, close: float, volume: float) -> float | None:
        d = ts.date()
        if d != self._date:
            self._date = d
            self._pv = 0.0
            self._vol = 0.0
        tp = (high + low + close) / 3.0
        v = max(volume, 1e-9)
        self._pv += tp * v
        self._vol += v
        self.value = self._pv / self._vol
        return self.value
