"""Walk-forward validation and strategy ablation.

A single backtest over one stretch of history is how people fool
themselves: parameters quietly overfit to that stretch. Walk-forward is the
honest protocol — optimize on a training window, evaluate on the unseen
window that follows, roll forward, and only trust the *stitched
out-of-sample* result:

    |── train 30d ──|─ test 10d ─|
                    |── train 30d ──|─ test 10d ─|
                                    |── train 30d ──|─ test 10d ─|

If the out-of-sample expectancy is negative, or the chosen parameters jump
around wildly between windows, the edge is not real — no matter how good
the in-sample numbers look.

Ablation answers a different question: which strategies earn their seat?
It re-runs the same data with each voter removed and reports the delta.

Each test window starts with cold indicators (~1 trading hour of warmup on
5-minute bars); this is identical across all candidates, so comparisons
stay fair.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from itertools import product
from typing import Iterator, Sequence

from .backtest import run
from .config import Config
from .data.bar import Bar
from .strategies import build_strategies

# Deliberately small: every added dimension multiplies the ways to overfit.
DEFAULT_GRID: dict[str, list] = {
    "min_score": [0.4, 0.5, 0.6],
    "sl_atr_mult": [1.0, 1.5, 2.0],
}


def split_windows(
    bars: Sequence[Bar], train_days: int, test_days: int
) -> Iterator[tuple[list[Bar], list[Bar]]]:
    """Roll (train, test) windows over the distinct trading dates in `bars`."""
    if train_days < 1 or test_days < 1:
        raise ValueError("train_days and test_days must be >= 1")
    dates = sorted({b.ts.date() for b in bars})
    i = 0
    while i + train_days + test_days <= len(dates):
        train_set = set(dates[i:i + train_days])
        test_set = set(dates[i + train_days:i + train_days + test_days])
        yield (
            [b for b in bars if b.ts.date() in train_set],
            [b for b in bars if b.ts.date() in test_set],
        )
        i += test_days


def _combos(grid: dict[str, list]) -> list[dict]:
    keys = sorted(grid)
    return [dict(zip(keys, vals)) for vals in product(*(grid[k] for k in keys))]


@dataclass(frozen=True)
class WindowResult:
    index: int
    params: dict
    train_pnl: float
    test_pnl: float
    test_trades: int
    test_win_rate: float


@dataclass
class WalkforwardResult:
    windows: list[WindowResult]
    oos_pnl: float          # stitched out-of-sample P&L — the number that matters
    oos_trades: int
    oos_win_rate: float
    oos_expectancy: float
    param_counts: Counter   # parameter stability across windows

    @property
    def survives(self) -> bool:
        """The bar to clear before anything goes near real money."""
        return self.oos_pnl > 0 and self.oos_trades >= 10


def run_walkforward(
    cfg: Config,
    bars: Sequence[Bar],
    train_days: int = 30,
    test_days: int = 10,
    grid: dict[str, list] | None = None,
) -> WalkforwardResult:
    grid = grid if grid is not None else DEFAULT_GRID
    combos = _combos(grid) or [{}]
    windows: list[WindowResult] = []
    wins = 0

    for idx, (train, test) in enumerate(split_windows(bars, train_days, test_days)):
        best_params, best_pnl = combos[0], float("-inf")
        for params in combos:
            r = run(replace(cfg, **params), train)
            if r.report.net_pnl > best_pnl:
                best_pnl, best_params = r.report.net_pnl, params
        t = run(replace(cfg, **best_params), test)
        windows.append(WindowResult(
            index=idx,
            params=best_params,
            train_pnl=round(best_pnl, 2),
            test_pnl=round(t.report.net_pnl, 2),
            test_trades=t.report.n_trades,
            test_win_rate=round(t.report.win_rate, 1),
        ))
        wins += sum(1 for tr in t.trades if tr.pnl > 0)

    oos_pnl = sum(w.test_pnl for w in windows)
    oos_trades = sum(w.test_trades for w in windows)
    return WalkforwardResult(
        windows=windows,
        oos_pnl=round(oos_pnl, 2),
        oos_trades=oos_trades,
        oos_win_rate=round(wins / oos_trades * 100, 1) if oos_trades else 0.0,
        oos_expectancy=round(oos_pnl / oos_trades, 2) if oos_trades else 0.0,
        param_counts=Counter(tuple(sorted(w.params.items())) for w in windows),
    )


@dataclass(frozen=True)
class AblationRow:
    removed: str            # "" for the baseline
    net_pnl: float
    n_trades: int
    delta_vs_baseline: float


def run_ablation(cfg: Config, bars: Sequence[Bar]) -> list[AblationRow]:
    """Baseline plus one run per strategy with that voter removed.

    A *negative* delta means the ensemble did worse without the strategy
    (it was pulling its weight); a positive delta says the ensemble is
    better off without it.
    """
    names = [s.name for s in build_strategies(cfg)]
    baseline = run(cfg, bars).report
    base = baseline.net_pnl
    rows = [AblationRow("", round(base, 2), baseline.n_trades, 0.0)]
    for name in names:
        strategies = [s for s in build_strategies(cfg) if s.name != name]
        r = run(cfg, bars, strategies=strategies)
        rows.append(AblationRow(
            removed=name,
            net_pnl=round(r.report.net_pnl, 2),
            n_trades=r.report.n_trades,
            delta_vs_baseline=round(r.report.net_pnl - base, 2),
        ))
    return rows
