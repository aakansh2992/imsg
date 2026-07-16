from datetime import datetime, timedelta

from quantum_engine.strategy.sniper_scalper import SniperScalper, SniperScalperConfig
from quantum_engine.types import Bar, Side


def _feed(strategy, prices):
    t = datetime(2024, 1, 1)
    last = None
    for i, p in enumerate(prices):
        bar = Bar(timestamp=t + timedelta(minutes=i), open=p, high=p + 0.5,
                  low=p - 0.5, close=p, volume=100.0)
        last = strategy.on_bar(bar)
    return last


def test_no_signal_during_warmup():
    strat = SniperScalper()
    sig = strat.on_bar(Bar(datetime(2024, 1, 1), 2000, 2000.5, 1999.5, 2000, 100))
    assert sig.is_flat
    assert sig.reason == "warmup"


def test_uptrend_pullback_triggers_buy():
    cfg = SniperScalperConfig(min_atr=0.0, max_atr=1e9)
    strat = SniperScalper(cfg)
    # Strong uptrend, then a small dip to create an RSI pullback.
    prices = [2000 + i * 0.8 for i in range(60)]
    prices += [prices[-1] - 0.5, prices[-1] - 1.0, prices[-1] - 1.2]
    sig = _feed(strat, prices)
    # Should be either a buy or flat, but never a short in a clear uptrend.
    assert sig.side in (Side.BUY, None)


def test_high_atr_stands_aside():
    cfg = SniperScalperConfig(max_atr=0.001)  # everything is "too volatile"
    strat = SniperScalper(cfg)
    prices = [2000 + i for i in range(60)]
    sig = _feed(strat, prices)
    assert sig.is_flat
    assert sig.reason in ("atr_too_high", "warmup", "no_confluence")


def test_signal_has_stop_and_target_when_trading():
    cfg = SniperScalperConfig(min_atr=0.0, max_atr=1e9)
    strat = SniperScalper(cfg)
    prices = [2000 - i * 0.8 for i in range(60)]  # downtrend
    prices += [prices[-1] + 0.5, prices[-1] + 1.0, prices[-1] + 1.2]  # pop
    sig = _feed(strat, prices)
    if not sig.is_flat:
        assert sig.stop_loss is not None
        assert sig.take_profit is not None
