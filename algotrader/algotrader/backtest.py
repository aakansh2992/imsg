"""Bar-replay backtest runner."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .broker.paper import Trade
from .config import Config
from .data.bar import Bar
from .engine import Engine
from .metrics import Report, compute


@dataclass
class BacktestResult:
    report: Report
    trades: list[Trade]
    engine: Engine


def run(cfg: Config, bars: Iterable[Bar]) -> BacktestResult:
    engine = Engine(cfg)
    last: Bar | None = None
    for bar in bars:
        engine.on_bar(bar)
        last = bar
    engine.finish(last)
    report = compute(cfg.initial_equity, engine.equity_curve, engine.broker.trades)
    return BacktestResult(report=report, trades=engine.broker.trades, engine=engine)
