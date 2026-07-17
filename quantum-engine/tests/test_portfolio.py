"""Tests for the 5-market whiteboard build: strategies, resampler, correlation
filter, hard 1% stop, multi-symbol broker accounting, and the full backtest."""

from datetime import datetime, timedelta, timezone

from quantum_engine.brokers.portfolio_sim import InstrumentSpec, PortfolioSimBroker
from quantum_engine.data.feed import SyntheticBarFeed
from quantum_engine.data.resample import BarResampler
from quantum_engine.engine.portfolio import (
    HARD_STOP_FRAC,
    MarketSpec,
    PortfolioEngine,
    default_markets,
)
from quantum_engine.strategy.mean_reversion import MeanReversion, MeanReversionConfig
from quantum_engine.strategy.momentum_breakout import (
    MomentumBreakout,
    MomentumBreakoutConfig,
)
from quantum_engine.strategy.trend_following import TrendFollowing
from quantum_engine.types import Bar, Order, Side


def _bar(minutes, close, high=None, low=None, volume=100.0, open_=None):
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minutes)
    o = open_ if open_ is not None else close
    return Bar(timestamp=ts, open=o, high=high if high is not None else close + 0.1,
               low=low if low is not None else close - 0.1, close=close,
               volume=volume)


# --- resampler -------------------------------------------------------------

def test_resampler_aggregates_15m():
    rs = BarResampler(15 * 60)
    out = []
    for i in range(31):  # 31 one-minute bars -> two completed 15m buckets
        b = rs.add(_bar(i, 100 + i, high=100 + i + 0.5, low=100 + i - 0.5))
        if b:
            out.append(b)
    assert len(out) == 2
    assert out[0].open == 100
    assert out[0].close == 114
    assert out[0].high >= 114
    assert out[0].volume == 100.0 * 15


# --- strategies ------------------------------------------------------------

def test_mean_reversion_buys_stretch_down():
    strat = MeanReversion(MeanReversionConfig(period=10, entry_z=2.0))
    sig = None
    for i in range(10):
        sig = strat.on_bar(_bar(i, 100.0 + (i % 2) * 0.2))
    sig = strat.on_bar(_bar(11, 95.0))  # sharp stretch below the band
    assert sig.side is Side.BUY
    assert sig.take_profit is not None and sig.take_profit > 95.0


def test_mean_reversion_flat_inside_band():
    strat = MeanReversion(MeanReversionConfig(period=10, entry_z=2.0))
    sig = None
    for i in range(15):
        sig = strat.on_bar(_bar(i, 100.0 + (i % 3) * 0.1))
    assert sig.is_flat


def test_breakout_requires_heavy_volume():
    cfg = MomentumBreakoutConfig(lookback=5, volume_mult=2.0)
    quiet = MomentumBreakout(cfg)
    for i in range(6):
        quiet.on_bar(_bar(i, 100.0, high=101.0, low=99.0, volume=100.0))
    sig = quiet.on_bar(_bar(7, 103.0, high=103.5, low=100.0, volume=100.0))
    assert sig.is_flat and sig.reason == "breakout_no_volume"

    loud = MomentumBreakout(cfg)
    for i in range(6):
        loud.on_bar(_bar(i, 100.0, high=101.0, low=99.0, volume=100.0))
    sig = loud.on_bar(_bar(7, 103.0, high=103.5, low=100.0, volume=300.0))
    assert sig.side is Side.BUY
    assert sig.take_profit is not None and sig.take_profit > 103.0


def test_trend_following_flips_with_trend():
    strat = TrendFollowing()
    sig = None
    for i in range(60):
        sig = strat.on_bar(_bar(i * 240, 100.0 + i))  # steady uptrend
    first_dir = None
    for i in range(60, 130):
        sig = strat.on_bar(_bar(i * 240, 160.0 - (i - 60) * 1.5))  # reversal
        if sig.side is not None and first_dir is None:
            first_dir = sig.side
    assert first_dir is Side.SELL  # downtrend flip produced a sell signal


# --- portfolio broker ------------------------------------------------------

def test_portfolio_broker_pnl_uses_contract_size():
    spec = InstrumentSpec("XAU", contract_size=100.0, spread=0.0, slippage=0.0)
    b = PortfolioSimBroker({"XAU": spec}, starting_balance=10_000.0)
    b.set_price("XAU", 2400.0)
    b.open(Order(symbol="XAU", side=Side.BUY, size=0.5))
    b.set_price("XAU", 2402.0)
    assert abs(b.equity() - (10_000.0 + 2.0 * 0.5 * 100.0)) < 1e-9
    trade = b.close("XAU")
    assert abs(trade.pnl - 100.0) < 1e-9
    assert abs(b.balance - 10_100.0) < 1e-9


def test_portfolio_broker_one_position_per_symbol():
    spec = InstrumentSpec("BTC")
    b = PortfolioSimBroker({"BTC": spec})
    b.set_price("BTC", 65_000.0)
    b.open(Order(symbol="BTC", side=Side.BUY, size=0.1))
    try:
        b.open(Order(symbol="BTC", side=Side.BUY, size=0.1))
        assert False, "second open should raise"
    except RuntimeError:
        pass


# --- engine rules ----------------------------------------------------------

def _engine():
    return PortfolioEngine(default_markets(), starting_equity=10_000.0)


def test_correlation_filter_blocks_double_index_long():
    eng = _engine()
    eng.broker.set_price("SPX", 560.0)
    eng.broker.open(Order(symbol="SPX", side=Side.BUY, size=1.0))
    assert eng._blocked_by_correlation("NDX", Side.BUY) is True
    assert eng._blocked_by_correlation("NDX", Side.SELL) is False
    assert eng._blocked_by_correlation("BTC", Side.BUY) is False


def test_correlation_filter_allows_long_when_other_flat_or_short():
    eng = _engine()
    assert eng._blocked_by_correlation("NDX", Side.BUY) is False
    eng.broker.set_price("SPX", 560.0)
    eng.broker.open(Order(symbol="SPX", side=Side.SELL, size=1.0))
    assert eng._blocked_by_correlation("NDX", Side.BUY) is False


def test_hard_one_percent_stop_cap():
    eng = _engine()
    state = eng.states["BTC"]
    # Feed huge-range bars so the ATR-based stop would exceed 1%.
    for i in range(20):
        state.atr.update(66_000.0, 60_000.0, 63_000.0)
    stop = eng._stop_for(state, Side.BUY, 65_000.0)
    dist = 65_000.0 - stop
    assert dist <= 65_000.0 * HARD_STOP_FRAC + 1e-6  # never wider than 1%

    # And with tiny ranges the volatility component tightens it below 1%.
    state2 = eng.states["SPX"]
    for i in range(20):
        state2.atr.update(560.2, 560.0, 560.1)
    stop2 = eng._stop_for(state2, Side.BUY, 560.0)
    assert (560.0 - stop2) < 560.0 * HARD_STOP_FRAC


def test_portfolio_backtest_runs_end_to_end():
    eng = _engine()
    bars = {m.symbol: SyntheticBarFeed(
                n_bars=3000,
                start_price={"SPX": 560, "NDX": 480, "BTC": 65_000,
                             "XAU": 2_400, "OIL": 80}[m.symbol],
                seed=7 + i)
            for i, m in enumerate(default_markets())}
    result = eng.run_backtest(bars)
    assert result.equity_curve
    assert result.starting_equity == 10_000.0
    assert 0.0 <= result.win_rate <= 100.0
    assert isinstance(result.summary(), str)
    # Invariant: no SPX+NDX simultaneous longs ever existed at close of run
    # (structural check happens in the filter tests; here we just ensure the
    # engine finished and accounted coherently).
    assert abs(result.ending_equity -
               (result.starting_equity + sum(t.pnl for t in result.trades))) < 1.0
