import unittest
from datetime import datetime, timedelta, timezone

from algotrader.indicators import ADX, ATR, EMA, MACD, RSI, Bollinger, Donchian, SessionVWAP


class TestEMA(unittest.TestCase):
    def test_seed_and_smoothing(self):
        ema = EMA(3)
        self.assertIsNone(ema.update(1))
        self.assertIsNone(ema.update(2))
        self.assertEqual(ema.update(3), 2.0)  # SMA seed
        # k = 2/(3+1) = 0.5
        self.assertEqual(ema.update(4), 3.0)
        self.assertEqual(ema.update(5), 4.0)


class TestRSI(unittest.TestCase):
    def test_all_gains_is_100(self):
        rsi = RSI(5)
        v = None
        for x in range(1, 10):
            v = rsi.update(float(x))
        self.assertEqual(v, 100.0)

    def test_mixed_range(self):
        rsi = RSI(3)
        for x in [10.0, 11.0, 10.5, 11.5, 10.8]:
            rsi.update(x)
        self.assertTrue(0.0 < rsi.value < 100.0)


class TestATR(unittest.TestCase):
    def test_constant_range(self):
        atr = ATR(3)
        v = None
        for _ in range(5):
            v = atr.update(11.0, 10.0, 10.5)  # TR is always 1.0
        self.assertAlmostEqual(v, 1.0)


class TestBollinger(unittest.TestCase):
    def test_constant_series_collapses(self):
        b = Bollinger(4, 2.0)
        for _ in range(4):
            b.update(100.0)
        self.assertEqual(b.mid, 100.0)
        self.assertEqual(b.upper, 100.0)
        self.assertEqual(b.lower, 100.0)


class TestDonchian(unittest.TestCase):
    def test_excludes_current_bar(self):
        d = Donchian(3)
        d.update(10, 9)
        d.update(11, 8)
        d.update(12, 7)
        self.assertFalse(d.ready)
        d.update(100, 1)  # channel must reflect the prior three bars only
        self.assertEqual(d.upper, 12)
        self.assertEqual(d.lower, 7)


class TestVWAP(unittest.TestCase):
    def test_resets_on_new_day(self):
        vwap = SessionVWAP()
        t0 = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
        vwap.update(t0, 101, 99, 100, 10)
        v1 = vwap.update(t0 + timedelta(minutes=5), 201, 199, 200, 10)
        self.assertAlmostEqual(v1, 150.0)
        v2 = vwap.update(t0 + timedelta(days=1), 301, 299, 300, 10)
        self.assertAlmostEqual(v2, 300.0)  # fresh session


class TestWarmups(unittest.TestCase):
    def test_macd_and_adx_become_ready(self):
        macd, adx = MACD(3, 5, 2), ADX(3)
        price = 100.0
        for i in range(30):
            price += 0.5 if i % 3 else -0.2
            macd.update(price)
            adx.update(price + 0.5, price - 0.5, price)
        self.assertTrue(macd.ready)
        self.assertTrue(adx.ready)
        self.assertTrue(0.0 <= adx.value <= 100.0)


if __name__ == "__main__":
    unittest.main()
