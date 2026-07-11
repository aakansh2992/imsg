import unittest

from algotrader.data.synthetic import generate
from algotrader.feed import BarAggregator, synthetic_feed, ticks_from_bar


class TestBarAggregator(unittest.TestCase):
    def test_round_trips_bars_through_ticks(self):
        bars = list(generate(days=1, seed=3))
        agg = BarAggregator(5)
        rebuilt = []
        for b in bars:
            for tick in ticks_from_bar("XAUUSD", b):
                done = agg.add(tick)
                if done:
                    rebuilt.append(done)
        tail = agg.flush()
        if tail:
            rebuilt.append(tail)
        self.assertEqual(len(rebuilt), len(bars))
        for orig, re in zip(bars, rebuilt):
            self.assertEqual(orig.ts, re.ts)
            self.assertEqual(orig.open, re.open)
            self.assertEqual(orig.high, re.high)
            self.assertEqual(orig.low, re.low)
            self.assertEqual(orig.close, re.close)
            self.assertAlmostEqual(orig.volume, re.volume, places=6)


class TestSyntheticFeed(unittest.TestCase):
    def test_multi_symbol_stream_is_time_ordered_per_symbol(self):
        last_ts = {}
        symbols_seen = set()
        for sym, bar in synthetic_feed(["XAUUSD", "BTCUSD"], days=2, seed=5, speed=0):
            symbols_seen.add(sym)
            if sym in last_ts:
                self.assertGreater(bar.ts, last_ts[sym])
            last_ts[sym] = bar.ts
        self.assertEqual(symbols_seen, {"XAUUSD", "BTCUSD"})

    def test_crypto_covers_the_weekend(self):
        # start Monday, stream 7 calendar days for BTC -> Sat/Sun bars exist
        weekend = [
            bar.ts.weekday()
            for sym, bar in synthetic_feed(["BTCUSD"], days=7, seed=5, speed=0)
            if bar.ts.weekday() >= 5
        ]
        self.assertTrue(weekend, "expected BTC bars on the weekend")


if __name__ == "__main__":
    unittest.main()
