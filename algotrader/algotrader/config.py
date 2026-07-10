"""Central configuration with sane defaults for intraday XAUUSD.

Every knob can be overridden from a JSON file (see ``config/default.json``);
unknown keys are rejected so typos fail loudly.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass
class Config:
    symbol: str = "XAUUSD"
    timeframe_min: int = 5

    # Shared indicators
    atr_period: int = 14
    adx_period: int = 14

    # Strategy parameters
    ema_fast: int = 21
    ema_slow: int = 55
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    boll_period: int = 20
    boll_k: float = 2.0
    donchian_period: int = 20
    vwap_dev_threshold: float = 2.0  # in ATRs from session VWAP

    # Confluence / regime
    trend_adx: float = 25.0   # ADX >= this -> trending regime
    range_adx: float = 20.0   # ADX <= this -> ranging regime
    weight_aligned: float = 1.0   # strategy kind matches regime
    weight_counter: float = 0.4   # strategy kind opposes regime
    weight_mixed: float = 0.7     # neutral regime
    min_score: float = 0.9        # |weighted score| needed to trade
    min_agree: int = 2            # strategies agreeing with the trade direction
    min_signal_conf: float = 0.25  # confidence needed to count as "agreeing"
    veto_confidence: float = 0.85  # a strong opposite signal vetoes the trade
    exit_score: float = 0.6       # opposite score that flips us out of a position

    # Risk management
    risk_per_trade_pct: float = 0.005   # 0.5% of equity risked per trade
    sl_atr_mult: float = 1.5            # stop distance in ATRs
    tp_r_multiple: float = 2.0          # take profit at 2R
    breakeven_at_r: float = 1.0         # move stop to entry after +1R
    daily_loss_limit_pct: float = 0.02  # -2% on the day -> flatten and halt
    daily_profit_lock_pct: float = 0.03  # +3% on the day -> flatten and lock it in
    max_trades_per_day: int = 6
    max_consecutive_losses: int = 4     # streak halt (no new entries that day)
    min_units: float = 0.0
    max_units: float = 100.0            # ounces
    unit_step: float = 0.01

    # Trading hours (UTC). XAUUSD is liquid through London and New York.
    sessions: list[list[str]] = field(
        default_factory=lambda: [["07:00", "11:00"], ["12:30", "19:30"]]
    )
    entry_cutoff: str = "19:00"  # no new positions after this
    eod_flat: str = "20:30"      # everything closed by this — end the day flat

    # Account and costs
    initial_equity: float = 100_000.0
    spread: float = 0.30          # full spread in USD/oz, applied half per side
    slippage: float = 0.05        # USD/oz per fill
    commission_per_trade: float = 0.0

    @classmethod
    def from_json(cls, path: str | Path) -> "Config":
        raw = json.loads(Path(path).read_text())
        known = {f.name for f in fields(cls)}
        unknown = set(raw) - known
        if unknown:
            raise ValueError(f"unknown config keys: {sorted(unknown)}")
        return cls(**raw)
