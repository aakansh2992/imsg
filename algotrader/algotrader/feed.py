"""Live data plumbing: ticks, tick→bar aggregation, and feed sources.

A real broker adapter only has to emit ``Tick`` objects; ``BarAggregator``
turns them into the completed bars the engine consumes. The synthetic feed
exercises exactly that path (bars are split into ticks and re-aggregated),
so swapping in a real WebSocket/FIX price stream changes nothing downstream.
"""
from __future__ import annotations

import heapq
import time as _time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Iterator

from .data.bar import Bar
from .data.synthetic import generate
from .instruments import REGISTRY


@dataclass(frozen=True)
class Tick:
    ts: datetime
    symbol: str
    price: float
    volume: float = 0.0


class BarAggregator:
    """Buckets ticks into fixed timeframe bars; returns a bar when complete."""

    def __init__(self, tf_minutes: int = 5) -> None:
        if 60 % tf_minutes != 0:
            raise ValueError("tf_minutes must divide 60")
        self.tf = tf_minutes
        self._bucket: datetime | None = None
        self._o = self._h = self._l = self._c = 0.0
        self._v = 0.0

    def _bucket_of(self, ts: datetime) -> datetime:
        return ts.replace(minute=(ts.minute // self.tf) * self.tf, second=0, microsecond=0)

    def add(self, tick: Tick) -> Bar | None:
        """Feed one tick; returns the previous bar when a new bucket opens."""
        bucket = self._bucket_of(tick.ts)
        completed: Bar | None = None
        if self._bucket is None:
            self._bucket = bucket
            self._o = self._h = self._l = self._c = tick.price
            self._v = tick.volume
            return None
        if bucket != self._bucket:
            completed = self.flush()
            self._bucket = bucket
            self._o = self._h = self._l = self._c = tick.price
            self._v = tick.volume
            return completed
        self._h = max(self._h, tick.price)
        self._l = min(self._l, tick.price)
        self._c = tick.price
        self._v += tick.volume
        return completed

    def flush(self) -> Bar | None:
        """Emit whatever is buffered (end of stream)."""
        if self._bucket is None:
            return None
        bar = Bar(ts=self._bucket, open=self._o, high=self._h, low=self._l,
                  close=self._c, volume=self._v)
        self._bucket = None
        return bar


def ticks_from_bar(symbol: str, bar: Bar) -> list[Tick]:
    """Decompose a bar into an O-H-L-C tick sequence (volume split evenly)."""
    step = bar.ts
    v = bar.volume / 4.0
    return [
        Tick(step, symbol, bar.open, v),
        Tick(step + timedelta(seconds=60), symbol, bar.high, v),
        Tick(step + timedelta(seconds=120), symbol, bar.low, v),
        Tick(step + timedelta(seconds=180), symbol, bar.close, v),
    ]


def synthetic_feed(
    symbols: list[str],
    days: int = 5,
    seed: int = 42,
    tf_minutes: int = 5,
    speed: float = 0.0,
    start: datetime | None = None,
) -> Iterator[tuple[str, Bar]]:
    """Multi-symbol synthetic feed, run through the tick→bar path.

    ``days`` is one shared calendar window for every instrument (weekday-only
    markets simply skip their closed days inside it), so all streams start
    and end together. ``speed`` scales simulated time to wall-clock: 300
    plays a 5-minute bar per second, 0 runs flat out (backtest-style).
    Crypto instruments include weekends and skip the maintenance break,
    matching their real calendars.
    """
    def _labeled(sym: str, bars: Iterable[Bar]) -> Iterator[tuple[datetime, str, Bar]]:
        for b in bars:
            yield b.ts, sym, b

    window_start = start or datetime(2026, 1, 5, tzinfo=timezone.utc)  # a Monday
    weekdays = sum(
        1 for i in range(days) if (window_start + timedelta(days=i)).weekday() < 5
    )

    streams: list[Iterator[tuple[datetime, str, Bar]]] = []
    for i, sym in enumerate(symbols):
        inst = REGISTRY[sym]
        bars = generate(
            days=days if inst.weekend else weekdays,
            tf_minutes=tf_minutes,
            seed=seed + i * 1009,
            start_price=inst.start_price,
            base_sigma=inst.base_sigma,
            include_weekends=inst.weekend,
            maintenance_break=inst.kind != "crypto",
            start=window_start,
        )
        streams.append(_labeled(sym, bars))

    aggs = {sym: BarAggregator(tf_minutes) for sym in symbols}
    prev_ts: datetime | None = None
    for ts, sym, bar in heapq.merge(*streams, key=lambda t: t[0]):
        if speed > 0 and prev_ts is not None:
            gap = (ts - prev_ts).total_seconds() / speed
            if gap > 0:
                _time.sleep(min(gap, 5.0))
        prev_ts = ts
        for tick in ticks_from_bar(sym, bar):
            done = aggs[sym].add(tick)
            if done is not None:
                yield sym, done
    for sym in symbols:
        tail = aggs[sym].flush()
        if tail is not None:
            yield sym, tail
