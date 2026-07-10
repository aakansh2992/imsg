"""Event loop: bar in -> indicators -> signals -> confluence -> risk -> broker.

Per-bar order of operations matters and is fixed:
  1. mark the open position against this bar (stop/target fills)
  2. roll the trading day and check equity limits (mark-to-market)
  3. update shared indicators and collect strategy signals
  4. forced flatten (end of day, daily-loss halt, profit lock)
  5. breakeven stop management on the open position
  6. exit on a confluence flip against the position
  7. new entry if confluence and every risk gate agree
Entries happen at the close of the signal bar; protective levels are first
checked on the following bar, never the same one.
"""
from __future__ import annotations

from .broker.paper import PaperBroker, Trade
from .config import Config
from .confluence import Confluence, Decision
from .data.bar import Bar
from .indicators import ADX, ATR, SessionVWAP
from .risk import RiskManager
from .strategies import build_strategies
from .strategies.base import MarketContext, Strategy


class Engine:
    def __init__(
        self,
        cfg: Config,
        broker: PaperBroker | None = None,
        strategies: list[Strategy] | None = None,
    ) -> None:
        self.cfg = cfg
        self.broker = broker or PaperBroker(
            cfg.initial_equity, cfg.spread, cfg.slippage, cfg.commission_per_trade
        )
        self.strategies = strategies or build_strategies(cfg)
        self.confluence = Confluence(cfg)
        self.risk = RiskManager(cfg)
        self._atr = ATR(cfg.atr_period)
        self._adx = ADX(cfg.adx_period)
        self._vwap = SessionVWAP()
        self.equity_curve: list[tuple] = []  # (ts, equity)
        self.decisions: list[tuple] = []     # (ts, Decision) for entries taken

    def _close(self, bar: Bar, reason: str) -> Trade:
        trade = self.broker.close(bar, reason)
        self.risk.on_trade_closed(trade)
        return trade

    def on_bar(self, bar: Bar) -> None:
        # 1. protective fills for the position carried into this bar
        for trade in self.broker.mark(bar):
            self.risk.on_trade_closed(trade)

        # 2. day roll + equity limits (uses mark-to-market equity)
        self.risk.on_bar(bar.ts, self.broker.equity(bar.close))

        # 3. shared indicators and signals (strategies must see every bar
        #    to stay warm, even when trading is halted)
        self._atr.update(bar.high, bar.low, bar.close)
        self._adx.update(bar.high, bar.low, bar.close)
        self._vwap.update(bar.ts, bar.high, bar.low, bar.close, bar.volume)
        ctx = MarketContext(atr=self._atr.value, adx=self._adx.value, vwap=self._vwap.value)
        signals = [(s.name, s.kind, s.on_bar(bar, ctx)) for s in self.strategies]

        # 4. forced flatten beats everything else
        flatten = self.risk.flatten_reason(bar.ts)
        if flatten:
            if self.broker.position is not None:
                self._close(bar, flatten)
            self.equity_curve.append((bar.ts, self.broker.equity(bar.close)))
            return

        if not ctx.ready:
            self.equity_curve.append((bar.ts, self.broker.equity(bar.close)))
            return

        decision: Decision = self.confluence.decide(signals, ctx.adx)
        pos = self.broker.position

        # 5. move the stop to breakeven once the trade is +1R
        if pos is not None and not pos.breakeven_moved and self.cfg.breakeven_at_r > 0:
            favorable = pos.direction * (bar.close - pos.entry)
            if favorable >= self.cfg.breakeven_at_r * pos.r_distance:
                pos.sl = pos.entry
                pos.breakeven_moved = True

        # 6. confluence flipped hard against us -> get out
        if (
            pos is not None
            and decision.score * pos.direction < 0
            and abs(decision.score) >= self.cfg.exit_score
        ):
            self._close(bar, "flip")
            pos = None

        # 7. entry
        if pos is None and decision.direction != 0 and self.risk.can_open(bar.ts):
            units = self.risk.size(self.broker.equity(bar.close), ctx.atr)
            if units > 0:
                dist = self.risk.stop_distance(ctx.atr)
                sl = bar.close - decision.direction * dist
                tp = bar.close + decision.direction * dist * self.cfg.tp_r_multiple
                self.broker.open(decision.direction, units, bar, sl, tp)
                self.risk.on_trade_opened()
                self.decisions.append((bar.ts, decision))

        self.equity_curve.append((bar.ts, self.broker.equity(bar.close)))

    def finish(self, last_bar: Bar | None) -> None:
        """Close anything still open at the end of the data."""
        if last_bar is not None and self.broker.position is not None:
            self._close(last_bar, "end")
            self.equity_curve.append((last_bar.ts, self.broker.equity(last_bar.close)))
