import unittest

from algotrader.config import Config
from algotrader.data.synthetic import generate
from algotrader.walkforward import (
    run_ablation,
    run_walkforward,
    split_windows,
)

TINY_GRID = {"min_score": [0.4, 0.6]}


class TestSplitWindows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bars = list(generate(days=12, seed=2))

    def test_windows_roll_forward_without_overlapping_tests(self):
        windows = list(split_windows(self.bars, train_days=6, test_days=3))
        self.assertEqual(len(windows), 2)
        seen_test_dates = set()
        for train, test in windows:
            train_dates = {b.ts.date() for b in train}
            test_dates = {b.ts.date() for b in test}
            self.assertEqual(len(train_dates), 6)
            self.assertEqual(len(test_dates), 3)
            self.assertFalse(train_dates & test_dates, "train/test leak")
            self.assertFalse(seen_test_dates & test_dates,
                             "test windows must not overlap")
            self.assertLess(max(train_dates), min(test_dates),
                            "test must come after train")
            seen_test_dates |= test_dates

    def test_not_enough_data_yields_nothing(self):
        self.assertEqual(list(split_windows(self.bars, 10, 5)), [])


class TestWalkforward(unittest.TestCase):
    def test_oos_aggregation_and_param_selection(self):
        bars = list(generate(days=12, seed=2))
        result = run_walkforward(Config(), bars, train_days=6, test_days=3,
                                 grid=TINY_GRID)
        self.assertEqual(len(result.windows), 2)
        for w in result.windows:
            self.assertIn(w.params["min_score"], TINY_GRID["min_score"])
        self.assertAlmostEqual(
            result.oos_pnl, sum(w.test_pnl for w in result.windows), places=2
        )
        self.assertEqual(result.oos_trades,
                         sum(w.test_trades for w in result.windows))
        self.assertEqual(sum(result.param_counts.values()), 2)

    def test_survives_requires_positive_oos_and_enough_trades(self):
        from algotrader.walkforward import WalkforwardResult
        from collections import Counter
        good = WalkforwardResult([], 100.0, 20, 50.0, 5.0, Counter())
        thin = WalkforwardResult([], 100.0, 3, 66.0, 33.3, Counter())
        red = WalkforwardResult([], -1.0, 50, 40.0, -0.02, Counter())
        self.assertTrue(good.survives)
        self.assertFalse(thin.survives)
        self.assertFalse(red.survives)


class TestAblation(unittest.TestCase):
    def test_one_row_per_voter_plus_baseline(self):
        bars = list(generate(days=8, seed=4))
        cfg = Config()
        rows = run_ablation(cfg, bars)
        from algotrader.strategies import build_strategies
        names = [s.name for s in build_strategies(cfg)]
        self.assertEqual(len(rows), len(names) + 1)
        self.assertEqual(rows[0].removed, "")
        self.assertEqual(rows[0].delta_vs_baseline, 0.0)
        self.assertEqual({r.removed for r in rows[1:]}, set(names))
        for r in rows[1:]:
            self.assertAlmostEqual(
                r.delta_vs_baseline, round(r.net_pnl - rows[0].net_pnl, 2),
                places=2,
            )


if __name__ == "__main__":
    unittest.main()
