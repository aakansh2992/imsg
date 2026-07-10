import unittest
from datetime import datetime, timezone

from algotrader.backtest import run
from algotrader.broker.paper import PaperBroker
from algotrader.config import Config
from algotrader.data.bar import Bar
from algotrader.data.synthetic import generate
from algotrader.sessions import SessionClock


def bar(ts, o, h, lo, c, v=100.0):
    return Bar(ts=ts, open=o, high=h, low=lo, close=c, volume=v)


class TestPaperBroker(unittest.TestCase):
    def setUp(self):
        self.t = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)

    def test_costs_applied_both_sides(self):
        b = PaperBroker(10_000.0, spread=0.30, slippage=0.05)
        b.open(1, 10.0, bar(self.t, 100, 100, 100, 100), sl=95.0, tp=110.0)
        self.assertAlmostEqual(b.position.entry, 100.20)
        t = b.close(bar(self.t, 101, 101, 101, 101), "flip")
        self.assertAlmostEqual(t.exit, 100.80)
        self.assertAlmostEqual(t.pnl, 6.0)
        self.assertAlmostEqual(b.cash, 10_006.0)

    def test_stop_beats_target_in_same_bar(self):
        b = PaperBroker(10_000.0)
        b.open(1, 1.0, bar(self.t, 100, 100, 100, 100), sl=98.0, tp=102.0)
        trades = b.mark(bar(self.t, 100, 103, 97, 100))  # bar spans both levels
        self.assertEqual(trades[0].reason, "sl")

    def test_gap_fills_at_open(self):
        b = PaperBroker(10_000.0)
        b.open(1, 1.0, bar(self.t, 100, 100, 100, 100), sl=98.0, tp=102.0)
        trades = b.mark(bar(self.t, 95, 96, 94, 95))  # gapped through the stop
        self.assertEqual(trades[0].exit, 95.0)  # filled at the open, not the stop


class TestBacktestEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = Config()
        cls.result = run(cls.cfg, generate(days=15, seed=7))

    def test_engine_trades_and_accounting_balances(self):
        r = self.result
        self.assertGreater(len(r.trades), 0, "expected the engine to trade")
        self.assertIsNone(r.engine.broker.position, "must end flat")
        expected = self.cfg.initial_equity + sum(t.pnl for t in r.trades)
        self.assertAlmostEqual(r.report.final_equity, expected, places=6)

    def test_never_holds_overnight(self):
        for t in self.result.trades:
            self.assertEqual(
                t.entry_ts.date(), t.exit_ts.date(),
                f"trade held overnight: {t}",
            )

    def test_entries_respect_session_and_cutoff(self):
        clock = SessionClock(self.cfg.sessions, self.cfg.entry_cutoff, self.cfg.eod_flat)
        for t in self.result.trades:
            self.assertTrue(clock.can_enter(t.entry_ts), f"entry outside session: {t.entry_ts}")

    def test_deterministic(self):
        again = run(self.cfg, generate(days=15, seed=7))
        self.assertEqual(len(again.trades), len(self.result.trades))
        self.assertAlmostEqual(again.report.final_equity, self.result.report.final_equity)

    def test_daily_loss_never_exceeded_materially(self):
        # daily mark-to-market loss should not blow far past the 2% limit
        # (small overshoot allowed: the halt fires on the bar after the breach)
        for d, pnl in self.result.report.daily_pnl.items():
            self.assertGreater(pnl, -0.04 * self.cfg.initial_equity,
                               f"day {d} lost more than plausible with the halt")


if __name__ == "__main__":
    unittest.main()
