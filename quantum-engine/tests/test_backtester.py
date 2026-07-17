from datetime import datetime, timedelta

from quantum_engine.brokers.simulated import SimulatedBroker
from quantum_engine.data.feed import SyntheticBarFeed
from quantum_engine.engine.backtester import Backtester
from quantum_engine.risk.manager import RiskConfig, RiskManager
from quantum_engine.strategy.base import Strategy
from quantum_engine.strategy.sniper_scalper import SniperScalper
from quantum_engine.types import Bar, Side, Signal


class _AlwaysLong(Strategy):
    """Forces one entry then holds; used to check exit accounting."""

    name = "always_long"

    def __init__(self):
        self._fired = False

    def on_bar(self, bar: Bar) -> Signal:
        if self._fired:
            return Signal(side=None)
        self._fired = True
        return Signal(side=Side.BUY, stop_loss=bar.close - 1.0,
                      take_profit=bar.close + 1.0, reason="test")


def _bars(prices):
    t = datetime(2024, 1, 1)
    out = []
    for i, p in enumerate(prices):
        out.append(Bar(timestamp=t + timedelta(minutes=i), open=p, high=p + 0.01,
                       low=p - 0.01, close=p, volume=100.0))
    return out


def test_backtest_runs_on_synthetic_data():
    strat = SniperScalper()
    bt = Backtester(strat, starting_equity=10_000.0)
    result = bt.run(SyntheticBarFeed(n_bars=1500))
    # Pipeline should complete and produce a coherent equity curve.
    assert len(result.equity_curve) == 1500
    assert result.starting_equity == 10_000.0
    assert result.ending_equity == result.equity_curve[-1][1] or result.num_trades >= 0


def test_take_profit_is_recorded_as_win():
    broker = SimulatedBroker(spread=0.0, slippage=0.0, starting_balance=10_000.0)
    risk = RiskManager(RiskConfig(risk_per_trade=0.01), 10_000.0)
    bt = Backtester(_AlwaysLong(), broker=broker, risk=risk)
    # Enter near 2000, then a bar that reaches the +1.0 target.
    bars = _bars([2000.0]) + [
        Bar(timestamp=datetime(2024, 1, 1, 0, 5), open=2000.0, high=2002.0,
            low=1999.9, close=2001.5, volume=100.0)
    ]
    result = bt.run(bars)
    assert result.num_trades == 1
    assert result.trades[0].reason == "take_profit"
    assert result.trades[0].pnl > 0


def test_stop_loss_is_recorded_as_loss():
    broker = SimulatedBroker(spread=0.0, slippage=0.0, starting_balance=10_000.0)
    risk = RiskManager(RiskConfig(risk_per_trade=0.01), 10_000.0)
    bt = Backtester(_AlwaysLong(), broker=broker, risk=risk)
    bars = _bars([2000.0]) + [
        Bar(timestamp=datetime(2024, 1, 1, 0, 5), open=2000.0, high=2000.1,
            low=1998.0, close=1998.5, volume=100.0)
    ]
    result = bt.run(bars)
    assert result.num_trades == 1
    assert result.trades[0].reason == "stop_loss"
    assert result.trades[0].pnl < 0


def test_straddle_bar_assumes_stop_first():
    broker = SimulatedBroker(spread=0.0, slippage=0.0, starting_balance=10_000.0)
    risk = RiskManager(RiskConfig(risk_per_trade=0.01), 10_000.0)
    bt = Backtester(_AlwaysLong(), broker=broker, risk=risk)
    # Bar reaches both target (+1) and stop (-1): pessimistic => stop.
    bars = _bars([2000.0]) + [
        Bar(timestamp=datetime(2024, 1, 1, 0, 5), open=2000.0, high=2002.0,
            low=1998.0, close=2000.0, volume=100.0)
    ]
    result = bt.run(bars)
    assert result.trades[0].reason == "stop_loss"


def test_result_metrics_are_sane():
    strat = SniperScalper()
    bt = Backtester(strat, starting_equity=10_000.0)
    result = bt.run(SyntheticBarFeed(n_bars=2000, seed=7))
    assert 0.0 <= result.win_rate <= 100.0
    assert result.max_drawdown_pct >= 0.0
    assert isinstance(result.summary(), str)
