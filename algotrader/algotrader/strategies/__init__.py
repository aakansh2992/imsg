"""Strategy registry."""
from __future__ import annotations

from ..config import Config
from .base import MarketContext, Signal, Strategy
from .donchian_breakout import DonchianBreakout
from .macd_momentum import MACDMomentum
from .rsi_reversion import RSIReversion
from .structure import BOSCHoCH, LiquiditySweep
from .trend_ema import TrendEMA
from .vwap_deviation import VWAPDeviation

__all__ = [
    "MarketContext",
    "Signal",
    "Strategy",
    "build_strategies",
    "TrendEMA",
    "MACDMomentum",
    "RSIReversion",
    "DonchianBreakout",
    "VWAPDeviation",
    "LiquiditySweep",
    "BOSCHoCH",
]


def build_strategies(cfg: Config) -> list[Strategy]:
    strategies: list[Strategy] = [
        TrendEMA(cfg.ema_fast, cfg.ema_slow),
        MACDMomentum(cfg.macd_fast, cfg.macd_slow, cfg.macd_signal),
        RSIReversion(cfg.rsi_period, cfg.rsi_oversold, cfg.rsi_overbought, cfg.boll_period, cfg.boll_k),
        DonchianBreakout(cfg.donchian_period),
        VWAPDeviation(cfg.vwap_dev_threshold),
    ]
    if cfg.enable_liquidity_sweep:
        strategies.append(LiquiditySweep(cfg.swing_k))
    if cfg.enable_bos_choch:
        strategies.append(BOSCHoCH(cfg.swing_k))
    return strategies
