"""Live ticker: turn a stream of real-time quotes into a stream of bars.

Two pieces:

* ``PollingTicker`` repeatedly calls ``provider.quote(symbol)`` on an interval and
  yields ``Tick``s. This works with any provider that exposes a quote endpoint
  (Yahoo, Twelve Data, MT5). For venues with a native websocket you would write a
  push-based ticker instead — the rest of the pipeline is unchanged.

* ``BarAggregator`` buckets ticks into fixed-timeframe OHLCV ``Bar``s (e.g. 60s),
  emitting a completed bar when the clock crosses a bucket boundary.

``live_bars(...)`` wires them together into an iterable of Bars that drops
straight into ``LiveTrader`` / the engine — the exact same object the backtester
consumes, so live and historical use one code path.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Iterator, Optional

from ..types import Bar, Tick
from .providers import DataProvider

logger = logging.getLogger("quantum_engine.ticker")


class PollingTicker:
    def __init__(self, provider: DataProvider, symbol: str,
                 poll_seconds: float = 5.0, sleep=time.sleep):
        self.provider = provider
        self.symbol = symbol
        self.poll_seconds = poll_seconds
        self._sleep = sleep
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def stream(self, max_ticks: Optional[int] = None) -> Iterator[Tick]:
        n = 0
        while not self._stop:
            if max_ticks is not None and n >= max_ticks:
                return
            try:
                tick = self.provider.quote(self.symbol)
                n += 1
                yield tick
            except Exception as exc:  # keep the ticker alive on transient errors
                logger.warning("quote failed (%s); retrying next poll", exc)
            if self._stop:
                return
            self._sleep(self.poll_seconds)


class BarAggregator:
    """Aggregate ticks into fixed-width time bars using the tick mid price."""

    def __init__(self, timeframe_seconds: int = 60):
        if timeframe_seconds < 1:
            raise ValueError("timeframe_seconds must be >= 1")
        self.tf = timeframe_seconds
        self._bucket: Optional[int] = None
        self._o = self._h = self._l = self._c = 0.0
        self._count = 0

    def _bucket_of(self, ts: datetime) -> int:
        epoch = ts.replace(tzinfo=ts.tzinfo or timezone.utc).timestamp()
        return int(epoch // self.tf)

    def add(self, tick: Tick) -> Optional[Bar]:
        """Feed a tick. Returns a completed Bar when a bucket boundary is crossed."""
        price = tick.mid
        bucket = self._bucket_of(tick.timestamp)
        completed: Optional[Bar] = None
        if self._bucket is None:
            self._start(bucket, price)
        elif bucket != self._bucket:
            completed = self._emit()
            self._start(bucket, price)
        else:
            self._h = max(self._h, price)
            self._l = min(self._l, price)
            self._c = price
            self._count += 1
        return completed

    def flush(self) -> Optional[Bar]:
        """Emit the in-progress bar (call at shutdown). Resets state."""
        if self._bucket is None:
            return None
        bar = self._emit()
        self._bucket = None
        return bar

    def _start(self, bucket: int, price: float) -> None:
        self._bucket = bucket
        self._o = self._h = self._l = self._c = price
        self._count = 1

    def _emit(self) -> Bar:
        ts = datetime.fromtimestamp(self._bucket * self.tf, tz=timezone.utc)
        return Bar(timestamp=ts, open=self._o, high=self._h, low=self._l,
                   close=self._c, volume=float(self._count))


def live_bars(provider: DataProvider, symbol: str, timeframe_seconds: int = 60,
              poll_seconds: float = 5.0, max_bars: Optional[int] = None,
              sleep=time.sleep) -> Iterator[Bar]:
    """Yield completed live bars built from polled quotes.

    ``poll_seconds`` should be well below ``timeframe_seconds`` so each bar is
    built from several ticks. Free endpoints are delayed/rate-limited — respect
    their limits (Twelve Data free tier is ~8 requests/min).
    """
    ticker = PollingTicker(provider, symbol, poll_seconds=poll_seconds, sleep=sleep)
    agg = BarAggregator(timeframe_seconds)
    emitted = 0
    for tick in ticker.stream():
        bar = agg.add(tick)
        if bar is not None:
            yield bar
            emitted += 1
            if max_bars is not None and emitted >= max_bars:
                ticker.stop()
                return
