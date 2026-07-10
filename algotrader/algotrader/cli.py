"""Command-line interface.

    python -m algotrader synth    --out data.csv --days 60 --seed 42
    python -m algotrader backtest --data data.csv [--config cfg.json]
                                  [--trades] [--daily] [--json-report out.json]
    python -m algotrader live     [--symbols XAUUSD,XAGUSD,WTIUSD,BTCUSD]
                                  [--days 5] [--speed 300] [--port 8899]
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys

from .backtest import run
from .config import Config
from .data.bar import read_csv, write_csv
from .data.synthetic import generate
from .feed import synthetic_feed
from .instruments import DEFAULT_SYMBOLS
from .metrics import Report
from .portfolio import PortfolioEngine
from .server import start_server


def _fmt_report(r: Report) -> str:
    pf = f"{r.profit_factor:.2f}" if r.profit_factor != float("inf") else "inf"
    lines = [
        "== Backtest report ==",
        f"equity        : {r.initial_equity:,.2f} -> {r.final_equity:,.2f}"
        f"  ({r.net_pnl:+,.2f} / {r.return_pct:+.2f}%)",
        f"trades        : {r.n_trades}  win rate {r.win_rate:.1f}%  profit factor {pf}",
        f"avg win/loss  : {r.avg_win:+,.2f} / {r.avg_loss:+,.2f}"
        f"  expectancy {r.expectancy:+,.2f}/trade",
        f"max drawdown  : {r.max_drawdown_pct:.2f}%   sharpe (daily, ann.) {r.sharpe:.2f}",
        f"days          : {r.days}  green {r.green_days} ({r.green_day_rate:.0f}%)",
        f"exit reasons  : {r.exit_reasons}",
    ]
    return "\n".join(lines)


def cmd_synth(args: argparse.Namespace) -> int:
    bars = generate(days=args.days, tf_minutes=args.tf_minutes, seed=args.seed,
                    start_price=args.start_price)
    n = write_csv(args.out, bars)
    print(f"wrote {n} bars to {args.out}")
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    cfg = Config.from_json(args.config) if args.config else Config()
    if args.equity is not None:
        cfg.initial_equity = args.equity
    result = run(cfg, read_csv(args.data))
    print(_fmt_report(result.report))

    if args.daily:
        print("\n== Daily P&L ==")
        for d, pnl in result.report.daily_pnl.items():
            print(f"{d}  {pnl:+12,.2f}  {'green' if pnl > 0 else 'red' if pnl < 0 else 'flat'}")

    if args.trades:
        print("\n== Trades ==")
        for t in result.trades:
            side = "LONG " if t.direction == 1 else "SHORT"
            print(
                f"{t.entry_ts:%Y-%m-%d %H:%M} -> {t.exit_ts:%H:%M}  {side}"
                f" {t.units:8.2f} oz  {t.entry:9.2f} -> {t.exit:9.2f}"
                f"  {t.pnl:+10.2f}  [{t.reason}]"
            )

    if args.json_report:
        payload = dataclasses.asdict(result.report)
        with open(args.json_report, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"\nreport written to {args.json_report}")
    return 0


def cmd_live(args: argparse.Namespace) -> int:
    cfg = Config.from_json(args.config) if args.config else Config()
    if args.equity is not None:
        cfg.initial_equity = args.equity
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    portfolio = PortfolioEngine(cfg, symbols)
    httpd = start_server(args.port, portfolio.status)
    host_port = httpd.server_address[1]
    print(f"dashboard: http://localhost:{host_port}/  (any device on this network)")
    print(f"paper trading {', '.join(symbols)} — {args.days} synthetic day(s), "
          f"speed x{args.speed:g} (0 = flat out)\n")

    trades_seen = 0
    feed = synthetic_feed(symbols, days=args.days, seed=args.seed, speed=args.speed)
    try:
        for sym, bar in feed:
            portfolio.on_bar(sym, bar)
            all_trades = portfolio.all_trades()
            for t in all_trades[trades_seen:]:
                side = "LONG " if t.direction == 1 else "SHORT"
                print(f"{t.exit_ts:%Y-%m-%d %H:%M}  {t.symbol:7s} {side}"
                      f" {t.units:10.3f} @ {t.entry:10.2f} -> {t.exit:10.2f}"
                      f"  {t.pnl:+10.2f}  [{t.reason}]")
            trades_seen = len(all_trades)
    except KeyboardInterrupt:
        print("\ninterrupted — flattening")
    finally:
        portfolio.finish()
        httpd.shutdown()
        httpd.server_close()

    r = portfolio.account_report()
    print()
    print(_fmt_report(r))
    per_sym = {
        sym: round(sum(t.pnl for t in e.broker.trades), 2)
        for sym, e in portfolio.engines.items()
    }
    print(f"per-symbol P&L: {per_sym}")
    print(f"max concurrent positions: {portfolio.max_concurrent_seen}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="algotrader",
                                description="Confluence-based intraday XAUUSD algo trader")
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("synth", help="generate synthetic XAUUSD bars to CSV")
    ps.add_argument("--out", required=True)
    ps.add_argument("--days", type=int, default=60)
    ps.add_argument("--tf-minutes", type=int, default=5)
    ps.add_argument("--seed", type=int, default=42)
    ps.add_argument("--start-price", type=float, default=3300.0)
    ps.set_defaults(fn=cmd_synth)

    pb = sub.add_parser("backtest", help="run a backtest over a CSV of bars")
    pb.add_argument("--data", required=True)
    pb.add_argument("--config", help="JSON config overriding defaults")
    pb.add_argument("--equity", type=float, help="override initial equity")
    pb.add_argument("--trades", action="store_true", help="print the trade log")
    pb.add_argument("--daily", action="store_true", help="print per-day P&L")
    pb.add_argument("--json-report", help="write the report as JSON")
    pb.set_defaults(fn=cmd_backtest)

    pl = sub.add_parser("live", help="24x7 multi-market paper trading + web dashboard")
    pl.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS),
                    help="comma-separated instrument symbols")
    pl.add_argument("--days", type=int, default=5, help="synthetic days to stream")
    pl.add_argument("--seed", type=int, default=42)
    pl.add_argument("--speed", type=float, default=300.0,
                    help="sim-time multiplier vs wall clock (0 = as fast as possible)")
    pl.add_argument("--port", type=int, default=8899, help="dashboard port")
    pl.add_argument("--config", help="JSON config overriding defaults")
    pl.add_argument("--equity", type=float, help="override initial equity")
    pl.set_defaults(fn=cmd_live)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
