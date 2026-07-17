"""SniperScalper — a confluence-based scalping strategy for XAUUSD.

Design philosophy
-----------------
There is no secret indicator that prints money. What separates a survivable
scalper from a gambler is *filtering*: only taking trades where several
independent conditions agree, and defining risk before entry. This strategy
requires agreement across three orthogonal dimensions:

1. Trend    — fast EMA vs slow EMA, and price on the correct side of VWAP.
2. Momentum — RSI leaving an extreme in the trend direction (pullback entry).
3. Regime   — ATR within a tradable band: enough range to profit, not so much
              that spreads/whipsaws dominate.

Stops and targets are volatility-scaled (multiples of ATR) so the strategy
adapts to changing conditions rather than using fixed pip distances.

This is a *reasonable* starting point for research and backtesting — not a
guarantee. Tune and validate on your own data with walk-forward testing before
trusting it with anything.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..types import Bar, Side, Signal
from .base import Strategy
from .indicators import ATR, EMA, RSI, RollingVWAP


@dataclass
class SniperScalperConfig:
    fast_ema: int = 9
    slow_ema: int = 21
    rsi_period: int = 14
    rsi_pullback_long: float = 45.0   # buy when RSI dips to/below this in an uptrend
    rsi_pullback_short: float = 55.0  # sell when RSI pops to/above this in a downtrend
    atr_period: int = 14
    vwap_window: int = 20
    min_atr: float = 0.10   # in price units (USD for XAUUSD). Below this = too quiet.
    max_atr: float = 5.00   # above this = news chaos, stand aside.
    stop_atr_mult: float = 1.2
    target_atr_mult: float = 1.8  # reward:risk = 1.8/1.2 = 1.5:1


class SniperScalper(Strategy):
    name = "sniper_scalper"

    def __init__(self, config: SniperScalperConfig | None = None):
        self.cfg = config or SniperScalperConfig()
        self.fast = EMA(self.cfg.fast_ema)
        self.slow = EMA(self.cfg.slow_ema)
        self.rsi = RSI(self.cfg.rsi_period)
        self.atr = ATR(self.cfg.atr_period)
        self.vwap = RollingVWAP(self.cfg.vwap_window)

    def warmup_bars(self) -> int:
        return max(self.cfg.slow_ema, self.cfg.rsi_period, self.cfg.atr_period,
                   self.cfg.vwap_window) + 2

    def on_bar(self, bar: Bar) -> Signal:
        fast = self.fast.update(bar.close)
        slow = self.slow.update(bar.close)
        rsi = self.rsi.update(bar.close)
        atr = self.atr.update(bar.high, bar.low, bar.close)
        vwap = self.vwap.update(bar.typical, bar.volume)

        if None in (fast, slow, rsi, atr, vwap):
            return Signal(side=None, reason="warmup")

        # Regime filter: only trade in a sane volatility band.
        if atr < self.cfg.min_atr:
            return Signal(side=None, strength=0.0, reason="atr_too_low")
        if atr > self.cfg.max_atr:
            return Signal(side=None, strength=0.0, reason="atr_too_high")

        uptrend = fast > slow and bar.close > vwap
        downtrend = fast < slow and bar.close < vwap

        if uptrend and rsi <= self.cfg.rsi_pullback_long:
            stop = bar.close - self.cfg.stop_atr_mult * atr
            target = bar.close + self.cfg.target_atr_mult * atr
            strength = min(1.0, (self.cfg.rsi_pullback_long - rsi) / 20.0 + 0.5)
            return Signal(side=Side.BUY, strength=strength, stop_loss=stop,
                          take_profit=target, reason="uptrend_pullback")

        if downtrend and rsi >= self.cfg.rsi_pullback_short:
            stop = bar.close + self.cfg.stop_atr_mult * atr
            target = bar.close - self.cfg.target_atr_mult * atr
            strength = min(1.0, (rsi - self.cfg.rsi_pullback_short) / 20.0 + 0.5)
            return Signal(side=Side.SELL, strength=strength, stop_loss=stop,
                          take_profit=target, reason="downtrend_pullback")

        return Signal(side=None, reason="no_confluence")
