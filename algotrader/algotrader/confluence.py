"""Confluence engine — combines strategy signals into one trade decision.

The rules:
  1. Detect the regime from ADX (trending / ranging / mixed) and weight each
     strategy by whether its style fits the regime (trend followers get more
     say in trends, mean-reverters in ranges).
  2. Compute a weighted score = sum(weight * direction * confidence).
  3. Trade only if the score clears ``min_score``, at least ``min_agree``
     strategies independently agree with the direction, and no strategy
     issues a high-confidence veto in the opposite direction.

No single indicator can open a position on its own.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .config import Config
from .strategies.base import Signal

REGIME_TREND = "trend"
REGIME_RANGE = "range"
REGIME_MIXED = "mixed"


@dataclass(frozen=True)
class Decision:
    direction: int  # -1, 0, +1
    score: float
    agreeing: int
    regime: str
    vetoed: bool
    notes: str = ""


class Confluence:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def regime(self, adx: float) -> str:
        if adx >= self.cfg.trend_adx:
            return REGIME_TREND
        if adx <= self.cfg.range_adx:
            return REGIME_RANGE
        return REGIME_MIXED

    def _weight(self, kind: str, regime: str) -> float:
        if regime == REGIME_MIXED:
            return self.cfg.weight_mixed
        aligned = (regime == REGIME_TREND and kind == "trend") or (
            regime == REGIME_RANGE and kind == "reversion"
        )
        return self.cfg.weight_aligned if aligned else self.cfg.weight_counter

    def decide(self, items: Sequence[tuple[str, str, Signal]], adx: float) -> Decision:
        """items: (strategy_name, strategy_kind, signal) per strategy."""
        regime = self.regime(adx)
        score = 0.0
        for _, kind, sig in items:
            score += self._weight(kind, regime) * sig.direction * sig.confidence

        candidate = 1 if score > 0 else -1 if score < 0 else 0
        if candidate == 0:
            return Decision(0, 0.0, 0, regime, False, "no net score")

        agreeing = sum(
            1
            for _, _, sig in items
            if sig.direction == candidate and sig.confidence >= self.cfg.min_signal_conf
        )
        vetoed = any(
            sig.direction == -candidate and sig.confidence >= self.cfg.veto_confidence
            for _, _, sig in items
        )
        ok = abs(score) >= self.cfg.min_score and agreeing >= self.cfg.min_agree and not vetoed
        direction = candidate if ok else 0
        notes = f"score={score:+.2f} agree={agreeing} regime={regime}" + (
            " VETO" if vetoed else ""
        )
        return Decision(direction, score, agreeing, regime, vetoed, notes)
