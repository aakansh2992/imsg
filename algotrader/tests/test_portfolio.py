import json
import unittest
import urllib.request

from algotrader.config import Config
from algotrader.feed import synthetic_feed
from algotrader.instruments import DEFAULT_SYMBOLS, REGISTRY, config_for
from algotrader.portfolio import PortfolioEngine
from algotrader.server import start_server


def run_portfolio(days=8, seed=11, symbols=None, cfg=None):
    cfg = cfg or Config()
    symbols = symbols or DEFAULT_SYMBOLS
    pf = PortfolioEngine(cfg, symbols)
    for sym, bar in synthetic_feed(symbols, days=days, seed=seed, speed=0):
        pf.on_bar(sym, bar)
    pf.finish()
    return pf


class TestPortfolio(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = Config()
        cls.pf = run_portfolio(cfg=cls.cfg)

    def test_accounting_balances_across_instruments(self):
        trades = self.pf.all_trades()
        self.assertGreater(len(trades), 0, "expected the portfolio to trade")
        expected = self.cfg.initial_equity + sum(t.pnl for t in trades)
        self.assertAlmostEqual(self.pf.account.cash, expected, places=6)
        self.assertEqual(self.pf.open_positions(), 0, "must end flat")

    def test_concurrency_cap_respected(self):
        self.assertLessEqual(
            self.pf.max_concurrent_seen, self.cfg.max_concurrent_positions
        )

    def test_no_instrument_holds_overnight(self):
        for t in self.pf.all_trades():
            if t.reason == "end":  # final flatten at stream end is exempt
                continue
            self.assertEqual(t.entry_ts.date(), t.exit_ts.date(), f"overnight: {t}")

    def test_entries_respect_each_instruments_sessions(self):
        for t in self.pf.all_trades():
            clock = self.pf.engines[t.symbol].risk.clock
            self.assertTrue(clock.can_enter(t.entry_ts),
                            f"{t.symbol} entry outside session: {t.entry_ts}")

    def test_status_snapshot_is_json_safe(self):
        payload = json.dumps(self.pf.status())
        parsed = json.loads(payload)
        self.assertIn("equity", parsed)
        self.assertEqual(set(parsed["symbols"]), set(DEFAULT_SYMBOLS))


class TestInstrumentConfig(unittest.TestCase):
    def test_config_for_overrides_costs_and_sessions(self):
        base = Config()
        btc = config_for("BTCUSD", base)
        self.assertEqual(btc.symbol, "BTCUSD")
        self.assertEqual(btc.spread, REGISTRY["BTCUSD"].spread)
        self.assertEqual(btc.eod_flat, "23:45")
        # the base config is untouched
        self.assertEqual(base.symbol, "XAUUSD")


class TestServer(unittest.TestCase):
    def test_dashboard_and_status_endpoints(self):
        httpd = start_server(0, lambda: {"equity": 1.0, "symbols": {}})
        port = httpd.server_address[1]
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(f"http://127.0.0.1:{port}/api/status", timeout=5) as r:
                self.assertEqual(json.loads(r.read())["equity"], 1.0)
            with opener.open(f"http://127.0.0.1:{port}/", timeout=5) as r:
                self.assertIn(b"algotrader", r.read())
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
