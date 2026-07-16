from quantum_engine.strategy.indicators import ATR, EMA, RSI, RollingVWAP, SMA


def test_ema_converges_to_constant():
    ema = EMA(10)
    for _ in range(200):
        ema.update(100.0)
    assert abs(ema.value - 100.0) < 1e-6


def test_ema_seeds_on_first_value():
    ema = EMA(5)
    assert ema.update(42.0) == 42.0


def test_sma_needs_full_window():
    sma = SMA(3)
    assert sma.update(1) is None
    assert sma.update(2) is None
    assert sma.update(3) == 2.0
    assert sma.update(6) == (2 + 3 + 6) / 3


def test_rsi_all_gains_is_high():
    rsi = RSI(14)
    val = None
    for i in range(1, 40):
        val = rsi.update(float(i))
    assert val is not None
    assert val > 90.0


def test_rsi_all_losses_is_low():
    rsi = RSI(14)
    val = None
    for i in range(40, 1, -1):
        val = rsi.update(float(i))
    assert val is not None
    assert val < 10.0


def test_atr_positive_for_ranging_bars():
    atr = ATR(14)
    val = None
    for i in range(30):
        base = 2000 + i
        val = atr.update(base + 2, base - 2, base)
    assert val is not None
    assert val > 0


def test_rolling_vwap_tracks_price():
    vwap = RollingVWAP(5)
    for _ in range(10):
        vwap.update(2000.0, 100.0)
    assert abs(vwap.value - 2000.0) < 1e-6


def test_rolling_vwap_handles_zero_volume():
    vwap = RollingVWAP(3)
    vwap.update(2000.0, 0.0)
    vwap.update(2010.0, 0.0)
    vwap.update(2020.0, 0.0)
    # Falls back to equal weighting.
    assert abs(vwap.value - 2010.0) < 1e-6
