"""Configuration loading.

Uses a tiny hand-rolled YAML-ish loader for the common flat/nested case so the
package has zero required third-party dependencies. If PyYAML is installed it is
used instead (more robust). Config is optional: sensible defaults live in code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

from .risk.manager import RiskConfig
from .strategy.sniper_scalper import SniperScalperConfig


@dataclass
class EngineConfig:
    symbol: str = "XAUUSD"
    starting_equity: float = 10_000.0
    broker: str = "simulated"          # "simulated" | "mt5"
    allow_live: bool = False
    spread: float = 0.20
    slippage: float = 0.05
    commission_per_lot: float = 0.0
    strategy: SniperScalperConfig = field(default_factory=SniperScalperConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EngineConfig":
        d = dict(d or {})
        strat = SniperScalperConfig(**(d.pop("strategy", {}) or {}))
        risk = RiskConfig(**(d.pop("risk", {}) or {}))
        known = {f for f in cls.__dataclass_fields__ if f not in ("strategy", "risk")}
        base = {k: v for k, v in d.items() if k in known}
        return cls(strategy=strat, risk=risk, **base)


def load_config(path: str) -> EngineConfig:
    try:
        import yaml  # type: ignore
        with open(path) as fh:
            data = yaml.safe_load(fh) or {}
    except ImportError:
        data = _load_simple_yaml(path)
    return EngineConfig.from_dict(data)


def _load_simple_yaml(path: str) -> Dict[str, Any]:
    """Minimal nested-YAML parser for two-level configs (no lists)."""
    root: Dict[str, Any] = {}
    stack = [(-1, root)]
    with open(path) as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line.strip() or line.strip().startswith("#"):
                continue
            indent = len(line) - len(line.lstrip(" "))
            key, _, val = line.strip().partition(":")
            key = key.strip()
            val = val.strip()
            while stack and stack[-1][0] >= indent:
                stack.pop()
            parent = stack[-1][1]
            if val == "":
                child: Dict[str, Any] = {}
                parent[key] = child
                stack.append((indent, child))
            else:
                parent[key] = _coerce(val)
    return root


def _coerce(val: str) -> Any:
    low = val.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "none", "~"):
        return None
    try:
        if "." in val or "e" in low:
            return float(val)
        return int(val)
    except ValueError:
        return val.strip('"\'')
