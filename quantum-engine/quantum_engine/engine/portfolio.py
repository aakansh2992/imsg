"""Five-market portfolio engine (the whiteboard build).

Markets and strategies, exactly as specified:

  S&P 500  (SPX)  mean reversion,     15-minute candles
  NASDAQ   (NDX)  mean reversion,     15-minute candles
  Bitcoin  (BTC)  momentum breakout,  1-hour candles (volume-confirmed)
  Gold     (XAU)  trend following,    4-hour candles
  Oil      (OIL)  trend following,    4-hour candles

Risk rules, exactly as specified:

  * Every trade carries a hard 1% stop loss (stop distance never exceeds
    1% of the entry price; a strategy may only tighten it, never widen it).
  * Position size adjusts with market volatility: sizing risks a fixed
    fraction of equity against the stop distance, and the stop distance is
    the smaller of an ATR multiple and the 1% cap — higher volatility means
    a wider (capped) stop and a smaller position.
  * A correlation filter prevents the S&P 500 and NASDAQ from being long
    simultaneously.

The account-level RiskManager (daily loss kill switch, max-drawdown breaker)
sits on top of all of it, exactly as in the single-market engine.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from ..brokers.portfolio_sim import ClosedTrade, InstrumentSpec, PortfolioSimBroker
from ..data.resample import BarResampler, epoch_utc
from ..risk.manager import RiskConfig, RiskManager
from ..strategy.base import Strategy
from ..strategy.indicators import ATR
from ..strategy.mean_reversion import MeanReversion
from ..strategy.momentum_breakout import MomentumBreakout
from ..strategy.trend_following import TrendFollowing
from ..types import Bar, Order, Side

HARD_STOP_FRAC = 0.01          # the whiteboard's "hard 1% stop loss"
ATR_STOP_MULT = 1.5            # volatility component of the stop
INDEX_SYMBOLS = ("SPX", "NDX")  # the correlation-filtered pair


@dataclass
class MarketSpec:
    symbol: str
    strategy: Strategy
    timeframe_seconds: int
    instrument: InstrumentSpec
    data_symbol: str = ""      # provider symbol (e.g. Yahoo ticker)

    def __post_init__(self) -> None:
        if not self.data_symbol:
            self.data_symbol = self.symbol


def default_markets() -> List[MarketSpec]:
    """The five whiteboard markets with paper-friendly instrument specs."""
    return [
        MarketSpec("SPX", MeanReversion(), 15 * 60,
                   InstrumentSpec("SPX", contract_size=1.0, spread=0.5,
                                  slippage=0.1, max_lots=100.0),
                   data_symbol="SPY"),
        MarketSpec("NDX", MeanReversion(), 15 * 60,
                   InstrumentSpec("NDX", contract_size=1.0, spread=1.0,
                                  slippage=0.2, max_lots=100.0),
                   data_symbol="QQQ"),
        MarketSpec("BTC", MomentumBreakout(), 60 * 60,
                   InstrumentSpec("BTC", contract_size=1.0, spread=20.0,
                                  slippage=5.0, max_lots=5.0),
                   data_symbol="BTC-USD"),
        MarketSpec("XAU", TrendFollowing(), 4 * 60 * 60,
                   InstrumentSpec("XAU", contract_size=100.0, spread=0.3,
                                  slippage=0.05, max_lots=5.0),
                   data_symbol="GC=F"),
        MarketSpec("OIL", TrendFollowing(), 4 * 60 * 60,
                   InstrumentSpec("OIL", contract_size=100.0, spread=0.04,
                                  slippage=0.01, max_lots=20.0),
                   data_symbol="CL=F"),
    ]


@dataclass
class PortfolioResult:
    starting_equity: float
    ending_equity: float
    trades: List[ClosedTrade] = field(default_factory=list)
    equity_curve: List[Tuple[object, float]] = field(default_factory=list)
    halted_reason: str = ""

    @property
    def net_pnl(self) -> float:
        return self.ending_equity - self.starting_equity

    @property
    def return_pct(self) -> float:
        return (self.net_pnl / self.starting_equity * 100.0
                if self.starting_equity else 0.0)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return sum(1 for t in self.trades if t.pnl > 0) / len(self.trades) * 100.0

    @property
    def max_drawdown_pct(self) -> float:
        peak, max_dd = self.starting_equity, 0.0
        for _, eq in self.equity_curve:
            peak = max(peak, eq)
            if peak > 0:
                max_dd = max(max_dd, 1.0 - eq / peak)
        return max_dd * 100.0

    def per_symbol(self) -> Dict[str, Dict[str, float]]:
        out: Dict[str, Dict[str, float]] = {}
        for t in self.trades:
            s = out.setdefault(t.symbol, {"trades": 0, "wins": 0, "pnl": 0.0})
            s["trades"] += 1
            s["wins"] += 1 if t.pnl > 0 else 0
            s["pnl"] += t.pnl
        return out

    def summary(self) -> str:
        lines = [
            f"Trades:       {len(self.trades)}",
            f"Win rate:     {self.win_rate:.1f}%",
            f"Net P&L:      {self.net_pnl:,.2f}",
            f"Return:       {self.return_pct:+.2f}%",
            f"Max drawdown: {self.max_drawdown_pct:.2f}%",
            f"Start equity: {self.starting_equity:,.2f}",
            f"End equity:   {self.ending_equity:,.2f}",
        ]
        for sym, s in sorted(self.per_symbol().items()):
            wr = s["wins"] / s["trades"] * 100.0 if s["trades"] else 0.0
            lines.append(f"  {sym}: {int(s['trades'])} trades, "
                         f"{wr:.0f}% win, P&L {s['pnl']:+,.2f}")
        if self.halted_reason:
            lines.append(f"Halted:       {self.halted_reason}")
        return "\n".join(lines) + "\n"


class _MarketState:
    def __init__(self, spec: MarketSpec):
        self.spec = spec
        self.resampler = BarResampler(spec.timeframe_seconds)
        self.atr = ATR(14)


class PortfolioEngine:
    """Drives all five markets against one shared account and risk manager."""

    def __init__(
        self,
        markets: Optional[List[MarketSpec]] = None,
        starting_equity: float = 10_000.0,
        risk_config: Optional[RiskConfig] = None,
    ):
        self.markets = markets or default_markets()
        self.states = {m.symbol: _MarketState(m) for m in self.markets}
        self.broker = PortfolioSimBroker(
            {m.symbol: m.instrument for m in self.markets},
            starting_balance=starting_equity,
        )
        self.starting_equity = starting_equity
        self.risk = RiskManager(risk_config or RiskConfig(), starting_equity)

    # --- correlation filter (whiteboard: SPX and NDX never long together) --

    def _blocked_by_correlation(self, symbol: str, side: Side) -> bool:
        if side is not Side.BUY or symbol not in INDEX_SYMBOLS:
            return False
        other = INDEX_SYMBOLS[0] if symbol == INDEX_SYMBOLS[1] else INDEX_SYMBOLS[1]
        pos = self.broker.position(other)
        return pos is not None and pos.side is Side.BUY

    # --- stop construction (hard 1% cap + volatility component) ------------

    def _stop_for(self, state: _MarketState, side: Side, entry: float) -> float:
        hard = entry * HARD_STOP_FRAC
        atr = state.atr.value
        dist = min(hard, ATR_STOP_MULT * atr) if atr else hard
        return entry - dist if side is Side.BUY else entry + dist

    # --- per-bar decision path ---------------------------------------------

    def _on_tf_bar(self, state: _MarketState, bar: Bar,
                   result: PortfolioResult) -> None:
        sym = state.spec.symbol
        state.atr.update(bar.high, bar.low, bar.close)
        self.broker.set_price(sym, bar.close)

        pos = self.broker.position(sym)
        if pos is not None:
            closed = self._check_exits(sym, pos, bar, result)
            if closed:
                pos = None

        signal = state.spec.strategy.on_bar(bar)
        if signal.is_flat:
            return

        # Trend-flip exit: an opposite-direction signal closes the position.
        pos = self.broker.position(sym)
        if pos is not None and signal.side is not pos.side:
            trade = self.broker.close(sym, reason="signal_flip",
                                      timestamp=bar.timestamp)
            self._record(trade, result)
            pos = None
        if pos is not None:
            return  # already positioned in this direction

        if self._blocked_by_correlation(sym, signal.side):
            return
        allowed, _ = self.risk.can_trade(self.broker.equity())
        if not allowed:
            return

        entry = bar.close
        stop = self._stop_for(state, signal.side, entry)
        # A strategy may tighten the stop, never widen past the 1% cap.
        if signal.stop_loss is not None:
            if signal.side is Side.BUY:
                stop = max(stop, signal.stop_loss)
            else:
                stop = min(stop, signal.stop_loss)

        spec = state.spec.instrument
        size = self.risk.position_size(self.broker.equity(), entry, stop,
                                       contract_size=spec.contract_size,
                                       max_lots=spec.max_lots)
        if size <= 0:
            return
        self.broker.open(Order(symbol=sym, side=signal.side, size=size,
                               stop_loss=stop, take_profit=signal.take_profit),
                         timestamp=bar.timestamp)

    def _check_exits(self, sym: str, pos, bar: Bar,
                     result: PortfolioResult) -> bool:
        hit: Optional[Tuple[str, float]] = None
        if pos.side is Side.BUY:
            if pos.stop_loss is not None and bar.low <= pos.stop_loss:
                hit = ("stop_loss", pos.stop_loss)
            elif pos.take_profit is not None and bar.high >= pos.take_profit:
                hit = ("take_profit", pos.take_profit)
        else:
            if pos.stop_loss is not None and bar.high >= pos.stop_loss:
                hit = ("stop_loss", pos.stop_loss)
            elif pos.take_profit is not None and bar.low <= pos.take_profit:
                hit = ("take_profit", pos.take_profit)
        if hit is None:
            return False
        reason, price = hit
        trade = self.broker.close(sym, price=price, reason=reason,
                                  timestamp=bar.timestamp)
        self._record(trade, result)
        return True

    def _record(self, trade: Optional[ClosedTrade],
                result: PortfolioResult) -> None:
        if trade is None:
            return
        self.risk.record_realized(trade.pnl, self.broker.equity())
        result.trades.append(trade)

    # --- backtest over merged multi-symbol history -------------------------

    def run_backtest(self, bars_by_symbol: Dict[str, Iterable[Bar]],
                     resample: bool = True) -> PortfolioResult:
        """Backtest over per-symbol bar streams merged in time order.

        ``bars_by_symbol`` maps engine symbols (SPX/NDX/BTC/XAU/OIL) to bar
        iterables, oldest first. With ``resample=True`` the inputs are base
        bars (e.g. 1m) resampled up to each market's timeframe; with False
        they are assumed to already be at the market's timeframe.
        """
        result = PortfolioResult(starting_equity=self.starting_equity,
                                 ending_equity=self.starting_equity)

        streams = []
        for i, (sym, bars) in enumerate(bars_by_symbol.items()):
            it = iter(bars)
            first = next(it, None)
            if first is not None:
                streams.append((epoch_utc(first.timestamp), i, sym, first, it))
        heapq.heapify(streams)

        while streams:
            _, i, sym, bar, it = heapq.heappop(streams)
            state = self.states[sym]
            self.broker.set_price(sym, bar.close)
            self.risk.roll_day(bar.timestamp.date(), self.broker.equity())

            if resample:
                tf_bar = state.resampler.add(bar)
                if tf_bar is not None:
                    self._on_tf_bar(state, tf_bar, result)
            else:
                self._on_tf_bar(state, bar, result)

            result.equity_curve.append((bar.timestamp, self.broker.equity()))
            nxt = next(it, None)
            if nxt is not None:
                heapq.heappush(streams,
                               (epoch_utc(nxt.timestamp), i, sym, nxt, it))

        for sym in list(self.broker.positions):
            trade = self.broker.close(sym, reason="end_of_data")
            self._record(trade, result)

        result.ending_equity = self.broker.equity()
        result.halted_reason = self.risk.state.halted_reason
        return result
