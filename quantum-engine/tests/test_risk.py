from datetime import date

from quantum_engine.risk.manager import RiskConfig, RiskManager


def test_position_size_respects_risk_fraction():
    cfg = RiskConfig(risk_per_trade=0.01, contract_size=100.0)
    rm = RiskManager(cfg, starting_equity=10_000.0)
    # Risk 1% of 10k = $100. Stop distance $1 => loss/lot = $100 => 1.0 lot.
    size = rm.position_size(equity=10_000.0, entry=2000.0, stop=1999.0)
    assert abs(size - 1.0) < 1e-9


def test_position_size_scales_with_stop_distance():
    cfg = RiskConfig(risk_per_trade=0.01, contract_size=100.0)
    rm = RiskManager(cfg, 10_000.0)
    tight = rm.position_size(10_000.0, 2000.0, 1999.5)  # $0.50 stop
    wide = rm.position_size(10_000.0, 2000.0, 1998.0)   # $2.00 stop
    assert tight > wide


def test_position_size_zero_when_below_minimum():
    cfg = RiskConfig(risk_per_trade=0.0001, contract_size=100.0,
                     min_position_lots=0.01)
    rm = RiskManager(cfg, 100.0)
    size = rm.position_size(100.0, 2000.0, 1900.0)
    assert size == 0.0


def test_position_size_capped_at_max():
    cfg = RiskConfig(risk_per_trade=0.99, contract_size=100.0,
                     max_position_lots=5.0)
    rm = RiskManager(cfg, 1_000_000.0)
    size = rm.position_size(1_000_000.0, 2000.0, 1999.99)
    assert size == 5.0


def test_daily_loss_limit_halts_trading():
    cfg = RiskConfig(daily_loss_limit=0.05)
    rm = RiskManager(cfg, 10_000.0)
    rm.roll_day(date(2024, 1, 1), 10_000.0)
    assert rm.can_trade(10_000.0)[0] is True
    # Lose 6% of start-of-day equity.
    rm.record_realized(-600.0, 9_400.0)
    ok, reason = rm.can_trade(9_400.0)
    assert ok is False
    assert reason == "daily_loss_limit"


def test_new_day_resets_daily_halt():
    cfg = RiskConfig(daily_loss_limit=0.05)
    rm = RiskManager(cfg, 10_000.0)
    rm.roll_day(date(2024, 1, 1), 10_000.0)
    rm.record_realized(-600.0, 9_400.0)
    assert rm.can_trade(9_400.0)[0] is False
    rm.roll_day(date(2024, 1, 2), 9_400.0)
    assert rm.can_trade(9_400.0)[0] is True


def test_max_drawdown_is_sticky():
    cfg = RiskConfig(max_drawdown=0.20, daily_loss_limit=1.0)
    rm = RiskManager(cfg, 10_000.0)
    rm.roll_day(date(2024, 1, 1), 10_000.0)
    rm.record_realized(-2_500.0, 7_500.0)  # 25% down from peak
    assert rm.can_trade(7_500.0)[0] is False
    # A new day does NOT clear a max-drawdown halt.
    rm.roll_day(date(2024, 1, 2), 7_500.0)
    assert rm.can_trade(7_500.0)[0] is False
