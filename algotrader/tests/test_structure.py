import unittest
from datetime import datetime, timedelta, timezone

from algotrader.data.bar import Bar
from algotrader.strategies.base import MarketContext
from algotrader.strategies.structure import BOSCHoCH, LiquiditySweep, SwingDetector

CTX = MarketContext(atr=1.0, adx=25.0, vwap=100.0)
T0 = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)


def bar(i, o, h, lo, c):
    return Bar(ts=T0 + timedelta(minutes=5 * i), open=o, high=h, low=lo, close=c, volume=10)


class TestSwingDetector(unittest.TestCase):
    def test_confirms_fractal_high(self):
        d = SwingDetector(k=2)
        highs = [10, 11, 15, 12, 11]  # peak at index 2, confirmed at the 5th bar
        for h in highs:
            d.update(h, h - 1)
        self.assertEqual(d.swing_high, 15)

    def test_no_swing_in_monotonic_series(self):
        d = SwingDetector(k=2)
        for h in [10, 11, 12, 13, 14, 15]:
            d.update(h, h - 1)
        self.assertIsNone(d.swing_high)


class TestLiquiditySweep(unittest.TestCase):
    def _warm(self, strat):
        # build a confirmed swing high at 110 (k=2)
        pattern = [(100, 105), (100, 107), (105, 110), (100, 107), (100, 105)]
        for i, (lo, hi) in enumerate(pattern):
            strat.on_bar(bar(i, lo + 1, hi, lo, lo + 2), CTX)

    def test_fades_a_swept_high(self):
        strat = LiquiditySweep(k=2)
        self._warm(strat)
        # wick through 110, close back below -> short
        sig = strat.on_bar(bar(9, 108, 111.0, 107, 108.5), CTX)
        self.assertEqual(sig.direction, -1)
        self.assertGreaterEqual(sig.confidence, 0.5)

    def test_clean_breakout_is_not_a_sweep(self):
        strat = LiquiditySweep(k=2)
        self._warm(strat)
        # close ABOVE the level: that's a breakout, not a stop hunt
        sig = strat.on_bar(bar(9, 108, 112.0, 107, 111.5), CTX)
        self.assertEqual(sig.direction, 0)


class TestBOSCHoCH(unittest.TestCase):
    def test_break_of_structure_signals_continuation(self):
        strat = BOSCHoCH(k=2)
        pattern = [(100, 105), (100, 107), (105, 110), (100, 107), (100, 105)]
        for i, (lo, hi) in enumerate(pattern):
            strat.on_bar(bar(i, lo + 1, hi, lo, lo + 2), CTX)
        sig = strat.on_bar(bar(9, 109, 112.0, 108, 111.0), CTX)  # close above 110
        self.assertEqual(sig.direction, 1)
        self.assertIn("BOS", sig.reason)


if __name__ == "__main__":
    unittest.main()
