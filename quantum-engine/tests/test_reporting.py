import os

from quantum_engine.engine.portfolio import PortfolioResult, default_markets
from quantum_engine.brokers.portfolio_sim import ClosedTrade
from quantum_engine.reporting import morning_report, night_report, save_report
from quantum_engine.types import Side


def test_morning_report_lists_all_five_markets():
    markets = default_markets()
    prices = {"SPX": 560.0, "NDX": 480.0, "BTC": 65_000.0,
              "XAU": 2_400.0, "OIL": 80.0}
    text = morning_report(markets, prices)
    for sym in ("SPX", "NDX", "BTC", "XAU", "OIL"):
        assert sym in text
    assert "no strategy guarantees" in text.lower()


def test_night_report_shows_pnl_and_per_market():
    result = PortfolioResult(starting_equity=10_000.0, ending_equity=10_150.0)
    result.trades.append(ClosedTrade(symbol="XAU", side=Side.BUY, size=0.1,
                                     entry=2400.0, exit=2410.0, pnl=100.0,
                                     reason="take_profit"))
    result.trades.append(ClosedTrade(symbol="SPX", side=Side.SELL, size=1.0,
                                     entry=560.0, exit=560.5, pnl=-50.0,
                                     reason="stop_loss"))
    text = night_report(result)
    assert "10,000.00 -> 10,150.00" in text
    assert "XAU" in text and "SPX" in text
    assert "+1.50%" in text


def test_save_report_writes_file(tmp_path):
    path = save_report("hello\n", "morning", str(tmp_path))
    assert os.path.exists(path)
    assert path.endswith("-morning.txt")
    with open(path) as fh:
        assert fh.read() == "hello\n"
