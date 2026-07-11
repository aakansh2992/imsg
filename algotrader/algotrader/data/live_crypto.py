"""Live crypto market data from public exchange REST APIs — no API key.

Crypto trades 24/7, which makes it the one market a weekend paper-trading
demo can run against real prices. Three interchangeable sources are
implemented (Binance, Coinbase, Kraken); ``pick_source`` probes them in
order and uses the first that responds, so a regional block on one exchange
doesn't stop the feed.

Design:
  * warmup_bars()   — recent *closed* 5-minute candles to warm indicators
  * stream()        — polls the exchange's own closed candles (accurate
                      OHLCV) and yields them to the engine; polls the live
                      ticker between candles purely for real-time display
  * fetch injection — every HTTP call goes through a supplied fetch(url)
                      callable, so tests run on recorded payloads and CI
                      never touches the network
"""
from __future__ import annotations

import json
import threading
import time as _time
import urllib.request
from datetime import datetime, timezone
from typing import Callable, Iterator, Protocol, Sequence

from ..instruments import REGISTRY
from .bar import Bar

Fetch = Callable[[str], object]  # url -> parsed JSON

_CRYPTO_BASES = {s: s[:-3] for s, inst in REGISTRY.items() if inst.kind == "crypto"}
# exchange-specific asset codes that differ from the common ticker
_KRAKEN_CODES = {"BTC": "XBT", "DOGE": "XDG"}

BINANCE_PAIRS = {s: f"{b}USDT" for s, b in _CRYPTO_BASES.items()}
COINBASE_PAIRS = {s: f"{b}-USD" for s, b in _CRYPTO_BASES.items()}
KRAKEN_PAIRS = {s: f"{_KRAKEN_CODES.get(b, b)}USD" for s, b in _CRYPTO_BASES.items()}


def default_fetch(url: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": "algotrader/0.1"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _bucket_start(ts: float, tf_minutes: int) -> int:
    step = tf_minutes * 60
    return int(ts // step) * step


class Source(Protocol):
    name: str

    def recent_bars(self, symbol: str, tf_minutes: int, limit: int) -> list[Bar]: ...
    def last_price(self, symbol: str) -> float: ...


class BinanceSource:
    name = "binance"
    BASE = "https://api.binance.com"
    PAIRS = BINANCE_PAIRS

    def __init__(self, fetch: Fetch = default_fetch, now: Callable[[], float] = _time.time):
        self._fetch, self._now = fetch, now

    def recent_bars(self, symbol: str, tf_minutes: int, limit: int) -> list[Bar]:
        pair = self.PAIRS[symbol]
        rows = self._fetch(f"{self.BASE}/api/v3/klines?symbol={pair}"
                           f"&interval={tf_minutes}m&limit={limit}")
        cutoff = _bucket_start(self._now(), tf_minutes)
        bars = []
        for r in rows:
            open_s = int(r[0]) // 1000
            if open_s >= cutoff:  # in-progress candle
                continue
            bars.append(Bar(
                ts=datetime.fromtimestamp(open_s, tz=timezone.utc),
                open=float(r[1]), high=float(r[2]), low=float(r[3]),
                close=float(r[4]), volume=float(r[5]),
            ))
        return bars

    def last_price(self, symbol: str) -> float:
        pair = self.PAIRS[symbol]
        data = self._fetch(f"{self.BASE}/api/v3/ticker/price?symbol={pair}")
        return float(data["price"])


class CoinbaseSource:
    name = "coinbase"
    BASE = "https://api.exchange.coinbase.com"
    PAIRS = COINBASE_PAIRS

    def __init__(self, fetch: Fetch = default_fetch, now: Callable[[], float] = _time.time):
        self._fetch, self._now = fetch, now

    def recent_bars(self, symbol: str, tf_minutes: int, limit: int) -> list[Bar]:
        pair = self.PAIRS[symbol]
        rows = self._fetch(f"{self.BASE}/products/{pair}/candles"
                           f"?granularity={tf_minutes * 60}")
        cutoff = _bucket_start(self._now(), tf_minutes)
        bars = []
        for r in sorted(rows, key=lambda r: r[0]):  # API returns newest first
            open_s = int(r[0])
            if open_s >= cutoff:
                continue
            # coinbase candle layout: [time, low, high, open, close, volume]
            bars.append(Bar(
                ts=datetime.fromtimestamp(open_s, tz=timezone.utc),
                open=float(r[3]), high=float(r[2]), low=float(r[1]),
                close=float(r[4]), volume=float(r[5]),
            ))
        return bars[-limit:]

    def last_price(self, symbol: str) -> float:
        pair = self.PAIRS[symbol]
        data = self._fetch(f"{self.BASE}/products/{pair}/ticker")
        return float(data["price"])


class KrakenSource:
    name = "kraken"
    BASE = "https://api.kraken.com"
    PAIRS = KRAKEN_PAIRS

    def __init__(self, fetch: Fetch = default_fetch, now: Callable[[], float] = _time.time):
        self._fetch, self._now = fetch, now

    def recent_bars(self, symbol: str, tf_minutes: int, limit: int) -> list[Bar]:
        pair = self.PAIRS[symbol]
        data = self._fetch(f"{self.BASE}/0/public/OHLC?pair={pair}&interval={tf_minutes}")
        result = data["result"]
        rows = next(v for k, v in result.items() if k != "last")
        cutoff = _bucket_start(self._now(), tf_minutes)
        bars = []
        for r in rows:
            open_s = int(r[0])
            if open_s >= cutoff:  # kraken includes the uncommitted frame
                continue
            bars.append(Bar(
                ts=datetime.fromtimestamp(open_s, tz=timezone.utc),
                open=float(r[1]), high=float(r[2]), low=float(r[3]),
                close=float(r[4]), volume=float(r[6]),
            ))
        return bars[-limit:]

    def last_price(self, symbol: str) -> float:
        pair = self.PAIRS[symbol]
        data = self._fetch(f"{self.BASE}/0/public/Ticker?pair={pair}")
        ticker = next(iter(data["result"].values()))
        return float(ticker["c"][0])


ALL_SOURCES = (BinanceSource, CoinbaseSource, KrakenSource)


def pick_source(
    probe_symbol: str = "BTCUSD",
    fetch: Fetch = default_fetch,
    sources: Sequence[type] = ALL_SOURCES,
) -> Source:
    """First exchange that answers a ticker probe wins."""
    errors = []
    for cls in sources:
        src = cls(fetch)
        try:
            src.last_price(probe_symbol)
            return src
        except Exception as e:  # blocked region, outage, network policy...
            errors.append(f"{cls.name}: {type(e).__name__}")
    raise ConnectionError("no crypto data source reachable — " + "; ".join(errors))


class LiveCryptoFeed:
    """Streams closed candles from a live exchange; marks prices in between.

    ``on_mark(symbol, price, ts)`` fires on every ticker poll so a dashboard
    can show the moving price; completed bars are yielded for the engine.
    """

    def __init__(
        self,
        symbols: Sequence[str],
        tf_minutes: int = 5,
        poll_seconds: float = 5.0,
        source: Source | None = None,
        fetch: Fetch = default_fetch,
        on_mark: Callable[[str, float, datetime], None] | None = None,
        clock: Callable[[], float] = _time.time,
        sleep: Callable[[float], None] = _time.sleep,
        max_consecutive_errors: int = 30,
    ) -> None:
        unknown = [s for s in symbols if s not in BinanceSource.PAIRS]
        if unknown:
            raise ValueError(f"not crypto symbols: {unknown}")
        self.symbols = list(symbols)
        self.tf = tf_minutes
        self.poll_seconds = poll_seconds
        self.source = source or pick_source(self.symbols[0], fetch)
        self.on_mark = on_mark or (lambda s, p, t: None)
        self._clock, self._sleep = clock, sleep
        self._max_errors = max_consecutive_errors
        self._last_ts: dict[str, datetime | None] = {s: None for s in self.symbols}

    def warmup_bars(self, limit: int = 300) -> dict[str, list[Bar]]:
        out = {}
        for sym in self.symbols:
            bars = self.source.recent_bars(sym, self.tf, limit)
            out[sym] = bars
            if bars:
                self._last_ts[sym] = bars[-1].ts
        return out

    def stream(self, stop: threading.Event) -> Iterator[tuple[str, Bar]]:
        errors = 0
        candle_every = max(self.poll_seconds, 10.0)
        next_candle_check = 0.0
        while not stop.is_set():
            try:
                now = self._clock()
                for sym in self.symbols:
                    price = self.source.last_price(sym)
                    self.on_mark(sym, price,
                                 datetime.fromtimestamp(now, tz=timezone.utc))
                if now >= next_candle_check:
                    next_candle_check = now + candle_every
                    for sym in self.symbols:
                        for bar in self.source.recent_bars(sym, self.tf, 5):
                            last = self._last_ts[sym]
                            if last is None or bar.ts > last:
                                self._last_ts[sym] = bar.ts
                                yield sym, bar
                errors = 0
            except Exception:
                errors += 1
                if errors >= self._max_errors:
                    raise
            if not stop.is_set():
                self._sleep(self.poll_seconds)
