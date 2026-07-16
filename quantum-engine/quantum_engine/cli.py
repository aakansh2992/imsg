"""Command-line interface.

    python -m quantum_engine.cli backtest --data data.csv
    python -m quantum_engine.cli backtest --synthetic 3000
    python -m quantum_engine.cli gen-data --out data.csv --bars 5000
    python -m quantum_engine.cli paper --synthetic 2000

Live trading is intentionally NOT wired into the CLI. Running real money is a
deliberate act you perform in your own script by constructing an MT5Broker with
allow_live=True — see README.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import EngineConfig, load_config
from .brokers.simulated import SimulatedBroker
from .data.feed import CSVBarFeed, SyntheticBarFeed, write_synthetic_csv
from .engine.backtester import Backtester
from .engine.live import LiveTrader
from .risk.manager import RiskManager
from .strategy.sniper_scalper import SniperScalper


def _build_config(args) -> EngineConfig:
    if getattr(args, "config", None):
        return load_config(args.config)
    return EngineConfig()


def _bars(args):
    if getattr(args, "synthetic", None):
        return SyntheticBarFeed(n_bars=args.synthetic)
    if getattr(args, "data", None):
        return CSVBarFeed(args.data)
    raise SystemExit("Provide --data <csv> or --synthetic <n_bars>")


def cmd_backtest(args) -> int:
    cfg = _build_config(args)
    strategy = SniperScalper(cfg.strategy)
    broker = SimulatedBroker(
        symbol=cfg.symbol, starting_balance=cfg.starting_equity,
        spread=cfg.spread, slippage=cfg.slippage,
        commission_per_lot=cfg.commission_per_lot,
        contract_size=cfg.risk.contract_size,
    )
    risk = RiskManager(cfg.risk, cfg.starting_equity)
    bt = Backtester(strategy, broker=broker, risk=risk)
    result = bt.run(_bars(args))
    print("=" * 48)
    print(f"  Quantum Engine backtest — {strategy.name}")
    print("=" * 48)
    print(result.summary())
    if getattr(args, "synthetic", None):
        print("NOTE: synthetic data is fake. This proves the pipeline runs;\n"
              "it says NOTHING about real-world profitability.")
    return 0


def cmd_paper(args) -> int:
    cfg = _build_config(args)
    strategy = SniperScalper(cfg.strategy)
    broker = SimulatedBroker(
        symbol=cfg.symbol, starting_balance=cfg.starting_equity,
        spread=cfg.spread, slippage=cfg.slippage,
        commission_per_lot=cfg.commission_per_lot,
        contract_size=cfg.risk.contract_size,
    )
    risk = RiskManager(cfg.risk, cfg.starting_equity)
    trader = LiveTrader(strategy, broker, risk, symbol=cfg.symbol)
    trader.run(_bars(args))
    acct = broker.account()
    print(f"Paper session complete. Equity: {acct.equity:,.2f} "
          f"(started {cfg.starting_equity:,.2f})")
    return 0


def cmd_gen_data(args) -> int:
    n = write_synthetic_csv(args.out, n_bars=args.bars)
    print(f"Wrote {n} synthetic bars to {args.out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="quantum_engine", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", help="Path to YAML config (optional)")
    sub = p.add_subparsers(dest="command", required=True)

    bt = sub.add_parser("backtest", help="Run a historical backtest")
    bt.add_argument("--data", help="CSV of OHLCV bars")
    bt.add_argument("--synthetic", type=int, help="Use N synthetic bars instead")
    bt.set_defaults(func=cmd_backtest)

    pa = sub.add_parser("paper", help="Run the live loop against the paper broker")
    pa.add_argument("--data", help="CSV of OHLCV bars")
    pa.add_argument("--synthetic", type=int, help="Use N synthetic bars instead")
    pa.set_defaults(func=cmd_paper)

    gd = sub.add_parser("gen-data", help="Generate a synthetic CSV")
    gd.add_argument("--out", required=True)
    gd.add_argument("--bars", type=int, default=5000)
    gd.set_defaults(func=cmd_gen_data)
    return p


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
