"""Resample bars into larger timeframes (1m -> 15m/1h/4h, etc.).

Streaming, causal: feed bars oldest-first; a completed higher-timeframe bar is
emitted only when the clock crosses a bucket boundary, so strategies running on
resampled bars can never peek into an unfinished bucket.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from ..types import Bar


def epoch_utc(ts: datetime) -> float:
    """Seconds since epoch; naive timestamps are treated as UTC."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.timestamp()


class BarResampler:
    """Aggregate incoming bars into fixed-width buckets of `timeframe_seconds`."""

    def __init__(self, timeframe_seconds: int):
        if timeframe_seconds < 1:
            raise ValueError("timeframe_seconds must be >= 1")
        self.tf = timeframe_seconds
        self._bucket: Optional[int] = None
        self._o = self._h = self._l = self._c = 0.0
        self._v = 0.0

    def add(self, bar: Bar) -> Optional[Bar]:
        """Feed one base bar; returns a completed higher-TF bar or None."""
        bucket = int(epoch_utc(bar.timestamp) // self.tf)
        completed: Optional[Bar] = None
        if self._bucket is None:
            self._start(bucket, bar)
        elif bucket != self._bucket:
            completed = self._emit()
            self._start(bucket, bar)
        else:
            self._h = max(self._h, bar.high)
            self._l = min(self._l, bar.low)
            self._c = bar.close
            self._v += bar.volume
        return completed

    def flush(self) -> Optional[Bar]:
        if self._bucket is None:
            return None
        bar = self._emit()
        self._bucket = None
        return bar

    def _start(self, bucket: int, bar: Bar) -> None:
        self._bucket = bucket
        self._o, self._h = bar.open, bar.high
        self._l, self._c = bar.low, bar.close
        self._v = bar.volume

    def _emit(self) -> Bar:
        ts = datetime.fromtimestamp(self._bucket * self.tf, tz=timezone.utc)
        return Bar(timestamp=ts, open=self._o, high=self._h, low=self._l,
                   close=self._c, volume=self._v)
