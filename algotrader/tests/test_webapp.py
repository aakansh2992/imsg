import json
import time
import unittest
import urllib.request

from algotrader.webapp import SessionManager, start_webapp

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(port, path):
    with OPENER.open(f"http://127.0.0.1:{port}{path}", timeout=10) as r:
        return r.status, r.read()


def post(port, path, payload):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=json.dumps(payload).encode(),
        method="POST",
    )
    try:
        with OPENER.open(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class TestWebApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = start_webapp(0)
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _wait_done(self, timeout=60):
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, body = get(self.port, "/api/status")
            s = json.loads(body)
            if s["state"] in ("done", "error"):
                return s
            time.sleep(0.2)
        self.fail("session did not finish in time")

    def test_full_lifecycle_with_custom_capital(self):
        status, page = get(self.port, "/")
        self.assertEqual(status, 200)
        self.assertIn(b"control panel", page)

        # bad params are rejected
        code, resp = post(self.port, "/api/run", {"equity": -5})
        self.assertEqual(code, 400)
        self.assertIn("equity", resp["error"])

        # run an instant backtest with custom capital
        code, resp = post(self.port, "/api/run", {
            "equity": 250_000, "days": 6, "speed": 0, "seed": 11,
            "symbols": ["XAUUSD", "BTCUSD"],
        })
        self.assertEqual(code, 200, resp)

        # double-start while running/done is either rejected or already finished
        s = self._wait_done()
        self.assertEqual(s["state"], "done", s.get("error"))
        self.assertEqual(s["initial_equity"], 250_000)
        self.assertIn("report", s)
        self.assertEqual(set(s["symbols"]), {"XAUUSD", "BTCUSD"})
        self.assertGreaterEqual(len(s["curve"]), 2)
        # accounting sanity: equity == initial + total pnl
        self.assertAlmostEqual(s["equity"], 250_000 + s["total_pnl"], places=2)

        code, body = get(self.port, "/api/report")
        self.assertEqual(code, 200)
        report = json.loads(body)
        self.assertEqual(report["initial_equity"], 250_000)
        self.assertIn("daily_pnl", report)

        _, csv_body = get(self.port, "/api/trades.csv")
        lines = csv_body.decode().strip().splitlines()
        self.assertTrue(lines[0].startswith("symbol,side,units"))
        self.assertEqual(len(lines) - 1, report["n_trades"])

        # a finished session can be restarted
        code, resp = post(self.port, "/api/run", {
            "equity": 50_000, "days": 2, "speed": 0, "seed": 3,
            "symbols": ["BTCUSD"],
        })
        self.assertEqual(code, 200, resp)
        s = self._wait_done()
        self.assertEqual(s["initial_equity"], 50_000)

    def test_pwa_assets_served(self):
        code, manifest = get(self.port, "/manifest.webmanifest")
        self.assertEqual(code, 200)
        m = json.loads(manifest)
        self.assertEqual(m["display"], "standalone")
        code, icon = get(self.port, "/icon-192.png")
        self.assertEqual(code, 200)
        self.assertEqual(icon[:8], b"\x89PNG\r\n\x1a\n", "must be a real PNG")
        code, sw = get(self.port, "/sw.js")
        self.assertEqual(code, 200)
        self.assertIn(b"service worker", sw.lower())

    def test_live_crypto_mode_with_injected_feed(self):
        import threading
        from algotrader.data.synthetic import generate

        class FakeFeed:
            def __init__(self, symbols, portfolio):
                self.source = type("S", (), {"name": "fake-exchange"})()
                self._pf = portfolio
                bars = list(generate(days=4, seed=9, include_weekends=True,
                                     maintenance_break=False,
                                     start_price=105_000.0))
                self._history, self._live = bars[:600], bars[600:900]

            def warmup_bars(self, limit=300):
                return {"BTCUSD": self._history}

            def stream(self, stop: threading.Event):
                for bar in self._live:
                    if stop.is_set():
                        return
                    yield "BTCUSD", bar

        mgr = SessionManager(crypto_feed_factory=lambda syms, pf: FakeFeed(syms, pf))
        err = mgr.start({"feed": "crypto", "equity": 75_000,
                         "symbols": ["BTCUSD", "XAUUSD"]})  # XAUUSD filtered out
        self.assertEqual(err, "")
        deadline = time.time() + 60
        while mgr.state not in ("done", "error") and time.time() < deadline:
            time.sleep(0.1)
        self.assertEqual(mgr.state, "done", mgr.error)
        s = mgr.status()
        self.assertEqual(s["feed"], "crypto")
        self.assertEqual(s["source"], "fake-exchange")
        self.assertEqual(list(s["symbols"]), ["BTCUSD"])
        self.assertEqual(s["initial_equity"], 75_000)
        # equity curve covers only the live segment, not the warmup history
        self.assertLessEqual(len(mgr.portfolio.curve), 300)

    def test_stop_interrupts_a_paced_session(self):
        mgr = SessionManager()
        err = mgr.start({"equity": 100_000, "days": 30, "speed": 5,  # very slow
                         "seed": 1, "symbols": ["BTCUSD"]})
        self.assertEqual(err, "")
        self.assertEqual(mgr.start({}), "a session is already running")
        mgr.stop()
        deadline = time.time() + 30
        while mgr.state not in ("done", "error") and time.time() < deadline:
            time.sleep(0.1)
        self.assertEqual(mgr.state, "done")
        self.assertEqual(mgr.portfolio.open_positions(), 0)


if __name__ == "__main__":
    unittest.main()
