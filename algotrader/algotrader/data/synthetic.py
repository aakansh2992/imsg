"""Deterministic synthetic XAUUSD bar generator for offline backtesting.

Regime-switching random walk (trend-up / trend-down / range) with an
intraday volatility profile that peaks in the London and New York sessions,
weekday-only bars, and a daily 21:00-22:00 UTC maintenance break — close
enough to spot gold microstructure to exercise every part of the engine.

Synthetic data validates the *machinery*, not the edge. Any performance
number produced from it says nothing about live markets.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from typing import Iterator

from .bar import Bar

REGIMES = ("up", "down", "range")
DRIFT = {"up": 4e-5, "down": -4e-5, "range": 0.0}
STAY_PROB = 0.995  # per-bar probability of staying in the current regime
BASE_SIGMA = 6e-4  # per-5-min-bar log-return stdev (~1% daily vol)


def _vol_profile(hour: int) -> float:
    """Rough intraday volatility multiplier by UTC hour."""
    if 12 <= hour < 17:   # London/NY overlap and NY morning
        return 1.6
    if 7 <= hour < 12:    # London
        return 1.3
    if 17 <= hour < 21:   # NY afternoon
        return 1.0
    return 0.5            # Asia / late


def generate(
    days: int = 60,
    tf_minutes: int = 5,
    seed: int = 42,
    start_price: float = 3300.0,
    start: datetime | None = None,
    base_sigma: float = BASE_SIGMA,
    include_weekends: bool = False,
    maintenance_break: bool = True,
) -> Iterator[Bar]:
    rng = random.Random(seed)
    if start is None:
        start = datetime(2026, 1, 5, tzinfo=timezone.utc)  # a Monday
    price = start_price
    regime = "range"
    produced_days = 0
    day = start

    while produced_days < days:
        if not include_weekends and day.weekday() >= 5:
            day += timedelta(days=1)
            continue
        t = day.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = t + timedelta(days=1)
        while t < end_of_day:
            if maintenance_break and t.hour == 21:  # daily maintenance break
                t += timedelta(minutes=tf_minutes)
                continue
            if rng.random() > STAY_PROB:
                regime = rng.choice([r for r in REGIMES if r != regime])
            sigma = base_sigma * _vol_profile(t.hour) * math.sqrt(tf_minutes / 5.0)
            o = price
            c = o * math.exp(DRIFT[regime] + sigma * rng.gauss(0.0, 1.0))
            wick_hi = abs(rng.gauss(0.0, sigma * 0.5))
            wick_lo = abs(rng.gauss(0.0, sigma * 0.5))
            hi = max(o, c) * (1.0 + wick_hi)
            lo = min(o, c) * (1.0 - wick_lo)
            vol = max(1.0, rng.lognormvariate(4.5, 0.5) * _vol_profile(t.hour))
            yield Bar(ts=t, open=round(o, 2), high=round(hi, 2), low=round(lo, 2),
                      close=round(c, 2), volume=round(vol))
            price = c
            t += timedelta(minutes=tf_minutes)
        produced_days += 1
        day += timedelta(days=1)
