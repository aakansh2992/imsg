import unittest
from datetime import datetime, timedelta, timezone

from algotrader.config import Config
from algotrader.data.bar import Bar
from algotrader.engine import Engine
from algotrader.strategies.base import LONG, Signal, Strategy


class AlwaysLong(Strategy):
    """Test double: unconditional high-confidence long vote."""

    def __init__(self, name, kind):
        self.name, self.kind = name, kind

    def on_bar(self, bar, ctx):
        return Signal(LONG, 1.0, "test")


def bars(prices, start=None):
    t0 = start or datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)
    out = []
    for i, p in enumerate(prices):
        out.append(Bar(ts=t0 + timedelta(minutes=5 * i),
                       open=p, high=p + 0.5, low=p - 0.5, close=p, volume=10))
    return out


class TestEmaTrigger(unittest.TestCase):
    def _engine(self, use_trigger):
        cfg = Config(use_ema_trigger=use_trigger, min_agree=2, min_score=0.4)
        strategies = [AlwaysLong("a", "trend"), AlwaysLong("b", "reversion")]
        return Engine(cfg, strategies=strategies)

    def test_falling_tape_blocks_long_entry(self):
        # steadily falling prices: EMA5 < EMA9, so longs must be filtered out
        eng = self._engine(use_trigger=True)
        for b in bars([3400 - i * 2.0 for i in range(60)]):
            eng.on_bar(b)
        self.assertIsNone(eng.broker.position)
        self.assertEqual(len(eng.broker.trades), 0)

    def test_same_tape_without_trigger_does_enter(self):
        eng = self._engine(use_trigger=False)
        for b in bars([3400 - i * 2.0 for i in range(60)]):
            eng.on_bar(b)
        opened = (eng.broker.position is not None) or len(eng.broker.trades) > 0
        self.assertTrue(opened, "control case should have traded")


if __name__ == "__main__":
    unittest.main()
