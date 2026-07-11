import threading
import unittest
from datetime import datetime, timezone

from algotrader.config import Config
from algotrader.data.live_crypto import (
    BinanceSource,
    CoinbaseSource,
    KrakenSource,
    LiveCryptoFeed,
    pick_source,
)
from algotrader.data.synthetic import generate
from algotrader.portfolio import PortfolioEngine

NOW = 1_780_000_000  # fixed "current time" for candle-cutoff checks
BUCKET = NOW - NOW % 300  # start of the in-progress 5-min candle


def binance_fetch(url):
    if "klines" in url:
        # two closed candles and one in-progress (open time == current bucket)
        return [
            [(BUCKET - 600) * 1000, "100.0", "110.0", "95.0", "105.0", "12.5", 0],
            [(BUCKET - 300) * 1000, "105.0", "108.0", "101.0", "102.0", "8.0", 0],
            [BUCKET * 1000, "102.0", "103.0", "99.0", "100.5", "3.0", 0],
        ]
    if "ticker/price" in url:
        return {"symbol": "BTCUSDT", "price": "101.25"}
    raise AssertionError(url)


def coinbase_fetch(url):
    if "candles" in url:
        # newest first, layout [time, low, high, open, close, volume]
        return [
            [BUCKET, 99.0, 103.0, 102.0, 100.5, 3.0],
            [BUCKET - 300, 101.0, 108.0, 105.0, 102.0, 8.0],
            [BUCKET - 600, 95.0, 110.0, 100.0, 105.0, 12.5],
        ]
    if "ticker" in url:
        return {"price": "101.25"}
    raise AssertionError(url)


def kraken_fetch(url):
    if "OHLC" in url:
        return {"result": {"XXBTZUSD": [
            [BUCKET - 600, "100.0", "110.0", "95.0", "105.0", "104", "12.5", 3],
            [BUCKET - 300, "105.0", "108.0", "101.0", "102.0", "104", "8.0", 2],
            [BUCKET, "102.0", "103.0", "99.0", "100.5", "101", "3.0", 1],
        ], "last": BUCKET - 300}}
    if "Ticker" in url:
        return {"result": {"XXBTZUSD": {"c": ["101.25", "1.0"]}}}
    raise AssertionError(url)


class TestSources(unittest.TestCase):
    def _check(self, src):
        bars = src.recent_bars("BTCUSD", 5, 10)
        self.assertEqual(len(bars), 2, "in-progress candle must be dropped")
        self.assertEqual(bars[0].open, 100.0)
        self.assertEqual(bars[0].high, 110.0)
        self.assertEqual(bars[0].low, 95.0)
        self.assertEqual(bars[0].close, 105.0)
        self.assertEqual(bars[0].volume, 12.5)
        self.assertLess(bars[0].ts, bars[1].ts)
        self.assertEqual(bars[1].ts,
                         datetime.fromtimestamp(BUCKET - 300, tz=timezone.utc))
        self.assertEqual(src.last_price("BTCUSD"), 101.25)

    def test_binance_parsing(self):
        self._check(BinanceSource(binance_fetch, now=lambda: NOW))

    def test_coinbase_parsing_reverses_and_maps_columns(self):
        self._check(CoinbaseSource(coinbase_fetch, now=lambda: NOW))

    def test_kraken_parsing(self):
        self._check(KrakenSource(kraken_fetch, now=lambda: NOW))

    def test_pick_source_falls_back(self):
        def failing_then_kraken(url):
            if "binance" in url or "coinbase" in url:
                raise ConnectionError("blocked")
            return kraken_fetch(url)
        src = pick_source("BTCUSD", failing_then_kraken)
        self.assertEqual(src.name, "kraken")

    def test_pick_source_raises_when_all_blocked(self):
        def blocked(url):
            raise ConnectionError("403")
        with self.assertRaises(ConnectionError):
            pick_source("BTCUSD", blocked)


class TestLiveFeedStream(unittest.TestCase):
    def test_yields_only_new_closed_bars_and_marks_prices(self):
        src = BinanceSource(binance_fetch, now=lambda: NOW)
        marks = []
        stop = threading.Event()
        polls = {"n": 0}

        def clock():
            return NOW + polls["n"]

        def sleep(_):
            polls["n"] += 20
            if polls["n"] > 60:
                stop.set()

        feed = LiveCryptoFeed(
            ["BTCUSD"], source=src, poll_seconds=5,
            on_mark=lambda s, p, t: marks.append((s, p)),
            clock=clock, sleep=sleep,
        )
        warm = feed.warmup_bars(10)
        self.assertEqual(len(warm["BTCUSD"]), 2)
        got = list(feed.stream(stop))
        # warmup already consumed both closed candles -> stream yields nothing new
        self.assertEqual(got, [])
        self.assertGreater(len(marks), 0)
        self.assertEqual(marks[0], ("BTCUSD", 101.25))

    def test_rejects_non_crypto_symbols(self):
        with self.assertRaises(ValueError):
            LiveCryptoFeed(["XAUUSD"], source=BinanceSource(binance_fetch))


class TestWarmup(unittest.TestCase):
    def test_warmup_trains_indicators_without_trading(self):
        pf = PortfolioEngine(Config(), ["BTCUSD"])
        history = list(generate(days=3, seed=6, include_weekends=True,
                                maintenance_break=False))
        pf.warmup({"BTCUSD": history})
        engine = pf.engines["BTCUSD"]
        self.assertTrue(engine._atr.ready, "indicators must be warm")
        self.assertTrue(engine.trading, "trading re-enabled after warmup")
        self.assertEqual(len(engine.broker.trades), 0, "no trades during warmup")
        self.assertEqual(len(pf.curve), 0, "warmup must not pollute the curve")
        self.assertEqual(pf.account.cash, Config().initial_equity)


if __name__ == "__main__":
    unittest.main()
