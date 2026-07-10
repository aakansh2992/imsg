import unittest

from algotrader.config import Config
from algotrader.confluence import Confluence
from algotrader.strategies.base import Signal


def sig(direction, conf):
    return Signal(direction, conf)


class TestConfluence(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()
        self.c = Confluence(self.cfg)

    def test_agreement_opens_trade(self):
        items = [
            ("a", "trend", sig(1, 0.9)),
            ("b", "trend", sig(1, 0.8)),
            ("c", "trend", sig(0, 0.0)),
            ("d", "reversion", sig(0, 0.0)),
            ("e", "reversion", sig(0, 0.0)),
        ]
        d = self.c.decide(items, adx=30.0)  # trending regime, trend strategies weighted 1.0
        self.assertEqual(d.direction, 1)
        self.assertGreaterEqual(d.agreeing, 2)

    def test_single_signal_is_not_enough(self):
        items = [
            ("a", "trend", sig(1, 1.0)),
            ("b", "trend", sig(0, 0.0)),
            ("c", "trend", sig(0, 0.0)),
            ("d", "reversion", sig(0, 0.0)),
            ("e", "reversion", sig(0, 0.0)),
        ]
        d = self.c.decide(items, adx=30.0)
        self.assertEqual(d.direction, 0)  # min_agree=2 not met

    def test_strong_opposite_signal_vetoes(self):
        items = [
            ("a", "trend", sig(1, 0.9)),
            ("b", "trend", sig(1, 0.9)),
            ("c", "trend", sig(1, 0.4)),
            ("d", "reversion", sig(-1, 0.95)),  # loud disagreement
            ("e", "reversion", sig(0, 0.0)),
        ]
        d = self.c.decide(items, adx=30.0)
        self.assertTrue(d.vetoed)
        self.assertEqual(d.direction, 0)

    def test_regime_weights_reversion_in_range(self):
        items = [
            ("a", "reversion", sig(-1, 0.8)),
            ("b", "reversion", sig(-1, 0.7)),
            ("c", "trend", sig(0, 0.0)),
            ("d", "trend", sig(0, 0.0)),
            ("e", "trend", sig(0, 0.0)),
        ]
        ranging = self.c.decide(items, adx=15.0)
        trending = self.c.decide(items, adx=30.0)
        self.assertEqual(ranging.direction, -1)
        # same signals carry less weight against a trending tape
        self.assertLess(abs(trending.score), abs(ranging.score))

    def test_no_signals_no_trade(self):
        items = [(n, "trend", sig(0, 0.0)) for n in "abcde"]
        d = self.c.decide(items, adx=22.0)
        self.assertEqual(d.direction, 0)


if __name__ == "__main__":
    unittest.main()
