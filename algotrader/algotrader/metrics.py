"""Performance metrics from the equity curve and trade list."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from math import sqrt

from .broker.paper import Trade

TRADING_DAYS_PER_YEAR = 252


@dataclass
class Report:
    initial_equity: float
    final_equity: float
    net_pnl: float
    return_pct: float
    n_trades: int
    win_rate: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    expectancy: float
    max_drawdown_pct: float
    sharpe: float
    days: int
    green_days: int
    green_day_rate: float
    daily_pnl: dict[str, float] = field(default_factory=dict)
    exit_reasons: dict[str, int] = field(default_factory=dict)


def compute(
    initial_equity: float,
    equity_curve: list[tuple[datetime, float]],
    trades: list[Trade],
) -> Report:
    final_equity = equity_curve[-1][1] if equity_curve else initial_equity

    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [t.pnl for t in trades if t.pnl <= 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    n = len(trades)

    # max drawdown over the mark-to-market curve
    peak = initial_equity
    max_dd = 0.0
    for _, eq in equity_curve:
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak)

    # daily mark-to-market P&L: last equity of each day vs. the prior day's
    day_last: dict[date, float] = {}
    for ts, eq in equity_curve:
        day_last[ts.date()] = eq
    daily_pnl: dict[str, float] = {}
    prev = initial_equity
    daily_returns: list[float] = []
    for d in sorted(day_last):
        eq = day_last[d]
        daily_pnl[d.isoformat()] = eq - prev
        if prev > 0:
            daily_returns.append(eq / prev - 1.0)
        prev = eq

    sharpe = 0.0
    if len(daily_returns) >= 2:
        mean = sum(daily_returns) / len(daily_returns)
        var = sum((r - mean) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
        std = sqrt(var)
        if std > 0:
            sharpe = mean / std * sqrt(TRADING_DAYS_PER_YEAR)

    green = sum(1 for v in daily_pnl.values() if v > 0)
    days = len(daily_pnl)

    reasons: dict[str, int] = {}
    for t in trades:
        reasons[t.reason] = reasons.get(t.reason, 0) + 1

    return Report(
        initial_equity=initial_equity,
        final_equity=final_equity,
        net_pnl=final_equity - initial_equity,
        return_pct=(final_equity / initial_equity - 1.0) * 100 if initial_equity else 0.0,
        n_trades=n,
        win_rate=len(wins) / n * 100 if n else 0.0,
        profit_factor=gross_win / gross_loss if gross_loss > 0 else float("inf") if gross_win else 0.0,
        avg_win=gross_win / len(wins) if wins else 0.0,
        avg_loss=-gross_loss / len(losses) if losses else 0.0,
        expectancy=(gross_win - gross_loss) / n if n else 0.0,
        max_drawdown_pct=max_dd * 100,
        sharpe=sharpe,
        days=days,
        green_days=green,
        green_day_rate=green / days * 100 if days else 0.0,
        daily_pnl=daily_pnl,
        exit_reasons=reasons,
    )
