import unittest
from datetime import datetime, timezone

from algotrader.broker.paper import Trade
from algotrader.config import Config
from algotrader.risk import HALT_DAILY_LOSS, HALT_LOSS_STREAK, HALT_PROFIT_LOCK, RiskManager


def ts(day, hh, mm=0):
    return datetime(2026, 1, day, hh, mm, tzinfo=timezone.utc)


def losing_trade(pnl=-100.0):
    t = ts(5, 10)
    return Trade(t, t, 1, 1.0, 3300.0, 3200.0, pnl, "sl")


class TestSizing(unittest.TestCase):
    def test_fixed_fractional(self):
        cfg = Config(risk_per_trade_pct=0.005, sl_atr_mult=1.5, max_units=1000.0)
        rm = RiskManager(cfg)
        # equity 100k, ATR 4.0 -> stop 6.0 -> risk 500 -> 83.33 oz, stepped to 0.01
        self.assertAlmostEqual(rm.size(100_000.0, 4.0), 83.33)

    def test_zero_atr_means_no_trade(self):
        rm = RiskManager(Config())
        self.assertEqual(rm.size(100_000.0, 0.0), 0.0)

    def test_max_units_clamp(self):
        cfg = Config(max_units=10.0)
        rm = RiskManager(cfg)
        self.assertEqual(rm.size(1_000_000.0, 1.0), 10.0)


class TestSessionGate(unittest.TestCase):
    def test_only_liquid_hours(self):
        rm = RiskManager(Config())
        rm.on_bar(ts(5, 8), 100_000.0)
        self.assertTrue(rm.can_open(ts(5, 8)))       # London
        self.assertFalse(rm.can_open(ts(5, 3)))      # Asia — closed
        self.assertFalse(rm.can_open(ts(5, 11, 30)))  # between sessions
        self.assertTrue(rm.can_open(ts(5, 14)))      # NY
        self.assertFalse(rm.can_open(ts(5, 19, 15)))  # after entry cutoff

    def test_eod_flatten(self):
        rm = RiskManager(Config())
        rm.on_bar(ts(5, 20), 100_000.0)
        self.assertEqual(rm.flatten_reason(ts(5, 20, 15)), "")
        self.assertEqual(rm.flatten_reason(ts(5, 20, 30)), "eod")


class TestDailyLimits(unittest.TestCase):
    def test_daily_loss_halts_and_flattens(self):
        rm = RiskManager(Config(daily_loss_limit_pct=0.02))
        rm.on_bar(ts(5, 8), 100_000.0)
        rm.on_bar(ts(5, 9), 97_900.0)  # -2.1% on the day
        self.assertEqual(rm.halt_reason, HALT_DAILY_LOSS)
        self.assertEqual(rm.flatten_reason(ts(5, 9)), HALT_DAILY_LOSS)
        self.assertFalse(rm.can_open(ts(5, 9)))
        # next day resets
        rm.on_bar(ts(6, 8), 97_900.0)
        self.assertTrue(rm.can_open(ts(6, 8)))

    def test_profit_lock_banks_the_day(self):
        rm = RiskManager(Config(daily_profit_lock_pct=0.03))
        rm.on_bar(ts(5, 8), 100_000.0)
        rm.on_bar(ts(5, 12), 103_100.0)  # +3.1%
        self.assertEqual(rm.halt_reason, HALT_PROFIT_LOCK)
        self.assertEqual(rm.flatten_reason(ts(5, 12)), HALT_PROFIT_LOCK)
        self.assertFalse(rm.can_open(ts(5, 13)))

    def test_loss_streak_blocks_entries_but_does_not_flatten(self):
        rm = RiskManager(Config(max_consecutive_losses=3))
        rm.on_bar(ts(5, 8), 100_000.0)
        for _ in range(3):
            rm.on_trade_closed(losing_trade())
        self.assertEqual(rm.halt_reason, HALT_LOSS_STREAK)
        self.assertFalse(rm.can_open(ts(5, 9)))
        self.assertEqual(rm.flatten_reason(ts(5, 9)), "")  # open trade may run

    def test_max_trades_per_day(self):
        rm = RiskManager(Config(max_trades_per_day=2))
        rm.on_bar(ts(5, 8), 100_000.0)
        rm.on_trade_opened()
        rm.on_trade_opened()
        self.assertFalse(rm.can_open(ts(5, 9)))


if __name__ == "__main__":
    unittest.main()
