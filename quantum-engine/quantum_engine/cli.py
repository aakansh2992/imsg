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

import os

from .config import EngineConfig, load_config
from .brokers.simulated import SimulatedBroker
from .data.feed import (CSVBarFeed, SyntheticBarFeed, write_bars_csv,
                        write_synthetic_csv)
from .data.providers import get_provider
from .data.ticker import live_bars
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


def _make_provider(args):
    kwargs = {}
    if args.provider == "twelvedata":
        api_key = args.api_key or os.environ.get("TWELVEDATA_API_KEY", "")
        kwargs["api_key"] = api_key
    if args.provider == "mt5":
        kwargs["symbol"] = args.symbol
    return get_provider(args.provider, **kwargs)


def cmd_fetch(args) -> int:
    provider = _make_provider(args)
    print(f"Fetching {args.symbol} {args.interval} ({args.lookback}) "
          f"from {args.provider}...")
    bars = provider.history(args.symbol, interval=args.interval,
                            lookback=args.lookback)
    if not bars:
        print("No bars returned. Check the symbol/interval/lookback and that "
              "the market has traded in that window.")
        return 1
    n = write_bars_csv(args.out, bars)
    print(f"Wrote {n} real bars to {args.out} "
          f"({bars[0].timestamp.isoformat()} -> {bars[-1].timestamp.isoformat()})")
    return 0


def cmd_live(args) -> int:
    cfg = _build_config(args)
    provider = _make_provider(args)
    strategy = SniperScalper(cfg.strategy)
    broker = SimulatedBroker(
        symbol=cfg.symbol, starting_balance=cfg.starting_equity,
        spread=cfg.spread, slippage=cfg.slippage,
        commission_per_lot=cfg.commission_per_lot,
        contract_size=cfg.risk.contract_size,
    )
    risk = RiskManager(cfg.risk, cfg.starting_equity)
    trader = LiveTrader(strategy, broker, risk, symbol=cfg.symbol)
    print(f"Live PAPER trading {args.symbol} via {args.provider}, "
          f"{args.timeframe}s bars, polling every {args.poll}s. Ctrl-C to stop.")
    stream = live_bars(provider, args.symbol, timeframe_seconds=args.timeframe,
                       poll_seconds=args.poll, max_bars=args.max_bars)
    try:
        trader.run(stream)
    except KeyboardInterrupt:
        print("\nStopped by user.")
    acct = broker.account()
    print(f"Session equity: {acct.equity:,.2f} (started {cfg.starting_equity:,.2f})")
    return 0


def _add_provider_args(p):
    p.add_argument("--provider", default="yahoo",
                   choices=["yahoo", "stooq", "twelvedata", "mt5"],
                   help="Market-data source (default: yahoo, keyless)")
    p.add_argument("--symbol", default="XAUUSD")
    p.add_argument("--api-key", default="",
                   help="API key (twelvedata). Falls back to $TWELVEDATA_API_KEY")


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

    ft = sub.add_parser("fetch", help="Download REAL historical bars to CSV")
    _add_provider_args(ft)
    ft.add_argument("--interval", default="1m",
                    help="Timeframe: 1m/5m/15m/1h/1d (provider-dependent)")
    ft.add_argument("--lookback", default="5d",
                    help="Range hint: 1d/5d/1mo/3mo/1y/max")
    ft.add_argument("--out", required=True)
    ft.set_defaults(func=cmd_fetch)

    lv = sub.add_parser("live", help="Live PAPER trade on a real-time quote feed")
    _add_provider_args(lv)
    lv.add_argument("--poll", type=float, default=5.0,
                    help="Seconds between quote polls (respect provider limits)")
    lv.add_argument("--timeframe", type=int, default=60,
                    help="Bar size in seconds built from polled quotes")
    lv.add_argument("--max-bars", type=int, default=None,
                    help="Stop after this many bars (default: run until Ctrl-C)")
    lv.set_defaults(func=cmd_live)
    return p


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except (RuntimeError, ValueError, OSError) as exc:
        # Network blocks, missing API keys, bad symbols: report cleanly.
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
