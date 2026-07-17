from datetime import datetime, timedelta, timezone

from quantum_engine.data.providers import DataProvider
from quantum_engine.data.ticker import BarAggregator, PollingTicker, live_bars
from quantum_engine.types import Tick


def _tick(second, price, spread=0.2):
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=second)
    return Tick(timestamp=ts, bid=price - spread / 2, ask=price + spread / 2)


def test_aggregator_emits_on_bucket_boundary():
    agg = BarAggregator(timeframe_seconds=60)
    assert agg.add(_tick(0, 2000)) is None
    assert agg.add(_tick(30, 2005)) is None
    # Crossing into the next minute emits the completed 00:00 bar.
    bar = agg.add(_tick(60, 1998))
    assert bar is not None
    assert bar.open == 2000
    assert bar.high == 2005
    assert bar.low == 2000
    assert bar.close == 2005  # last tick of the closed bucket


def test_aggregator_tracks_high_low_within_bucket():
    agg = BarAggregator(60)
    agg.add(_tick(0, 2000))
    agg.add(_tick(10, 2010))
    agg.add(_tick(20, 1990))
    agg.add(_tick(30, 2005))
    bar = agg.flush()
    assert bar.high == 2010
    assert bar.low == 1990
    assert bar.close == 2005


def test_aggregator_flush_returns_partial_then_none():
    agg = BarAggregator(60)
    agg.add(_tick(0, 2000))
    assert agg.flush() is not None
    assert agg.flush() is None


class _ScriptedProvider(DataProvider):
    name = "scripted"

    def __init__(self, ticks):
        self._ticks = list(ticks)
        self._i = 0

    def history(self, symbol, interval, lookback):
        return []

    def quote(self, symbol):
        if self._i >= len(self._ticks):
            raise StopIteration
        t = self._ticks[self._i]
        self._i += 1
        return t


def test_polling_ticker_yields_ticks_without_sleeping():
    ticks = [_tick(0, 2000), _tick(1, 2001), _tick(2, 2002)]
    provider = _ScriptedProvider(ticks)
    ticker = PollingTicker(provider, "XAUUSD", poll_seconds=0,
                           sleep=lambda s: None)
    out = list(ticker.stream(max_ticks=3))
    assert len(out) == 3
    assert out[1].mid == 2001


def test_live_bars_builds_bars_from_polled_quotes():
    # Ticks spanning three minutes -> two completed bars before max_bars stops.
    ticks = [_tick(0, 2000), _tick(30, 2004), _tick(60, 2002),
             _tick(90, 2006), _tick(120, 2001)]
    provider = _ScriptedProvider(ticks)
    bars = list(live_bars(provider, "XAUUSD", timeframe_seconds=60,
                          poll_seconds=0, max_bars=2, sleep=lambda s: None))
    assert len(bars) == 2
    assert bars[0].open == 2000
    assert bars[0].close == 2004
