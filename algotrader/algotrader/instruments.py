"""Instrument registry: contract specs, costs, and per-market trading hours.

The portfolio engine trades whichever markets are currently in session, so
around the clock the union of these calendars keeps the bot busy: metals and
energy cover the London/New York/Asia weekday cycle, crypto covers nights
and weekends. Session windows are UTC. Costs are deliberately conservative.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from .config import Config


@dataclass(frozen=True)
class Instrument:
    symbol: str
    kind: str            # "metal" | "energy" | "crypto"
    start_price: float   # synthetic feed seed price
    base_sigma: float    # synthetic per-5-min-bar log-return stdev
    spread: float        # full spread, USD per unit
    slippage: float      # USD per unit per fill
    unit_step: float     # smallest tradable increment (oz / bbl / coin)
    max_units: float
    sessions: tuple      # ((start, end), ...) UTC entry windows
    entry_cutoff: str    # no new positions after this (UTC)
    eod_flat: str        # forced flat by this (UTC)
    weekend: bool        # instrument trades Saturday/Sunday


REGISTRY: dict[str, Instrument] = {
    inst.symbol: inst
    for inst in [
        Instrument(
            symbol="XAUUSD", kind="metal", start_price=3300.0, base_sigma=6e-4,
            spread=0.30, slippage=0.05, unit_step=0.01, max_units=100.0,
            sessions=(("01:00", "19:30"),), entry_cutoff="19:00", eod_flat="20:30",
            weekend=False,
        ),
        Instrument(
            symbol="XAGUSD", kind="metal", start_price=38.0, base_sigma=9e-4,
            spread=0.03, slippage=0.01, unit_step=1.0, max_units=5000.0,
            sessions=(("01:00", "19:30"),), entry_cutoff="19:00", eod_flat="20:30",
            weekend=False,
        ),
        Instrument(
            symbol="WTIUSD", kind="energy", start_price=78.0, base_sigma=1.2e-3,
            spread=0.04, slippage=0.02, unit_step=1.0, max_units=2000.0,
            sessions=(("03:00", "19:30"),), entry_cutoff="19:00", eod_flat="20:15",
            weekend=False,
        ),
    ]
}


def _crypto(symbol: str, price: float, sigma: float, spread: float,
            slippage: float, step: float, max_units: float) -> Instrument:
    return Instrument(
        symbol=symbol, kind="crypto", start_price=price, base_sigma=sigma,
        spread=spread, slippage=slippage, unit_step=step, max_units=max_units,
        sessions=(("00:00", "23:59"),), entry_cutoff="23:00", eod_flat="23:45",
        weekend=True,
    )


# Majors with liquid USD(T) markets on Binance, Coinbase, and Kraken alike.
for _inst in [
    _crypto("BTCUSD", 105_000.0, 2.5e-3, 25.0, 10.0, 0.001, 5.0),
    _crypto("ETHUSD", 5_200.0, 3e-3, 1.80, 0.80, 0.01, 100.0),
    _crypto("SOLUSD", 220.0, 4e-3, 0.12, 0.05, 0.1, 2_000.0),
    _crypto("XRPUSD", 2.80, 4e-3, 0.002, 0.001, 1.0, 150_000.0),
    _crypto("DOGEUSD", 0.35, 4.5e-3, 0.0004, 0.0002, 10.0, 1_000_000.0),
    _crypto("ADAUSD", 1.10, 4e-3, 0.001, 0.0005, 1.0, 400_000.0),
    _crypto("LTCUSD", 130.0, 3.5e-3, 0.08, 0.04, 0.1, 3_000.0),
    _crypto("LINKUSD", 25.0, 4e-3, 0.02, 0.01, 0.1, 15_000.0),
]:
    REGISTRY[_inst.symbol] = _inst

DEFAULT_SYMBOLS = ["XAUUSD", "XAGUSD", "WTIUSD", "BTCUSD"]
CRYPTO_SYMBOLS = [s for s, inst in REGISTRY.items() if inst.kind == "crypto"]


def config_for(symbol: str, base: Config) -> Config:
    """Derive a per-instrument Config from the account-level base config."""
    inst = REGISTRY[symbol]
    return replace(
        base,
        symbol=inst.symbol,
        spread=inst.spread,
        slippage=inst.slippage,
        unit_step=inst.unit_step,
        max_units=inst.max_units,
        sessions=[list(w) for w in inst.sessions],
        entry_cutoff=inst.entry_cutoff,
        eod_flat=inst.eod_flat,
    )
