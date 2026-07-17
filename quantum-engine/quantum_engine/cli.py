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


def cmd_portfolio_backtest(args) -> int:
    from .data.feed import CSVBarFeed
    from .engine.portfolio import PortfolioEngine, default_markets
    from .reporting import night_report, save_report

    markets = default_markets()
    engine = PortfolioEngine(markets, starting_equity=args.equity)

    if args.data_dir:
        bars = {}
        for m in markets:
            path = os.path.join(args.data_dir, f"{m.symbol}.csv")
            if not os.path.exists(path):
                print(f"error: missing {path} (need one CSV per market: "
                      f"{', '.join(x.symbol for x in markets)})",
                      file=sys.stderr)
                return 1
            bars[m.symbol] = CSVBarFeed(path)
        resample = not args.no_resample
    else:
        n = args.synthetic or 20_000
        base_prices = {"SPX": 560.0, "NDX": 480.0, "BTC": 65_000.0,
                       "XAU": 2_400.0, "OIL": 80.0}
        bars = {m.symbol: SyntheticBarFeed(n_bars=n,
                                           start_price=base_prices[m.symbol],
                                           seed=101 + i)
                for i, m in enumerate(markets)}
        resample = True

    result = engine.run_backtest(bars, resample=resample)
    print("=" * 48)
    print("  Quantum Engine — 5-market portfolio backtest")
    print("=" * 48)
    print(result.summary())
    report = night_report(result)
    path = save_report(report, "night", args.reports_dir)
    print(f"Night report saved: {path}")
    if not args.data_dir:
        print("NOTE: synthetic data proves the pipeline, not profitability.")
    return 0


def cmd_portfolio_live(args) -> int:
    from .data.ticker import BarAggregator
    from .engine.portfolio import PortfolioEngine, PortfolioResult, default_markets
    from .reporting import morning_report, night_report, save_report
    import time as _time

    provider = _make_provider(args)
    markets = default_markets()
    engine = PortfolioEngine(markets, starting_equity=args.equity)
    aggs = {m.symbol: BarAggregator(60) for m in markets}
    result = PortfolioResult(starting_equity=args.equity,
                             ending_equity=args.equity)

    prices: dict = {m.symbol: None for m in markets}
    print(morning_report(markets, prices))
    print(f"Live PAPER portfolio via {args.provider}; polling "
          f"{len(markets)} markets every {args.poll}s. Ctrl-C to stop.")
    try:
        while True:
            for m in markets:
                try:
                    tick = provider.quote(m.data_symbol)
                except Exception as exc:
                    logging.getLogger("quantum_engine").warning(
                        "%s quote failed: %s", m.symbol, exc)
                    continue
                prices[m.symbol] = tick.mid
                engine.broker.set_price(m.symbol, tick.mid)
                base_bar = aggs[m.symbol].add(tick)
                if base_bar is not None:
                    engine.risk.roll_day(base_bar.timestamp.date(),
                                         engine.broker.equity())
                    state = engine.states[m.symbol]
                    tf_bar = state.resampler.add(base_bar)
                    if tf_bar is not None:
                        engine._on_tf_bar(state, tf_bar, result)
                    result.equity_curve.append(
                        (base_bar.timestamp, engine.broker.equity()))
            _time.sleep(args.poll)
    except KeyboardInterrupt:
        print("\nStopping...")
    result.ending_equity = engine.broker.equity()
    result.halted_reason = engine.risk.state.halted_reason
    report = night_report(result)
    print(report)
    path = save_report(report, "night", args.reports_dir)
    print(f"Night report saved: {path}")
    return 0


def cmd_report(args) -> int:
    from .engine.portfolio import default_markets
    from .reporting import morning_report, save_report

    markets = default_markets()
    prices: dict = {}
    provider = _make_provider(args)
    for m in markets:
        try:
            prices[m.symbol] = provider.quote(m.data_symbol).mid
        except Exception:
            prices[m.symbol] = None
    text = morning_report(markets, prices)
    print(text)
    path = save_report(text, "morning", args.reports_dir)
    print(f"Saved: {path}")
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

    pb = sub.add_parser("portfolio-backtest",
                        help="Backtest the 5-market portfolio bot")
    pb.add_argument("--synthetic", type=int, default=None,
                    help="Synthetic base bars per market (default 20000)")
    pb.add_argument("--data-dir",
                    help="Directory with SPX.csv NDX.csv BTC.csv XAU.csv OIL.csv")
    pb.add_argument("--no-resample", action="store_true",
                    help="CSVs are already at each market's timeframe")
    pb.add_argument("--equity", type=float, default=10_000.0)
    pb.add_argument("--reports-dir", default="reports")
    pb.set_defaults(func=cmd_portfolio_backtest)

    pl = sub.add_parser("portfolio-live",
                        help="Live PAPER trade all 5 markets on real quotes")
    _add_provider_args(pl)
    pl.add_argument("--poll", type=float, default=12.0,
                    help="Seconds per polling cycle across all markets")
    pl.add_argument("--equity", type=float, default=10_000.0)
    pl.add_argument("--reports-dir", default="reports")
    pl.set_defaults(func=cmd_portfolio_live)

    rp = sub.add_parser("report",
                        help="Generate the morning briefing (live quotes)")
    _add_provider_args(rp)
    rp.add_argument("--reports-dir", default="reports")
    rp.set_defaults(func=cmd_report)
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
