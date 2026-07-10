# algotrader — confluence-based multi-market algo trader

A self-contained (pure-stdlib Python ≥ 3.10, zero dependencies) algorithmic
trading system built around one idea: independent signal families vote,
regime-aware confluence gates the vote, and a hard risk layer makes "end the
day flat and preferably green" an enforced rule rather than a hope.

It runs as a single always-on process that scans **every configured market
around the clock** — gold, silver and oil through their weekday
London/New-York/Asia hours, crypto through nights and weekends — and serves
a **responsive web dashboard**, so any phone, tablet or laptop on the
network is a live viewer. Devices are windows into the bot, not hosts of
it: the trading loop never depends on someone's screen staying unlocked.

## ⚠️ Honest disclaimer, up front

No algorithm can **guarantee** daily profitability — anyone who promises
that is selling something. What this system engineers is the controllable
part:

1. **Edge selection** — trade only when multiple independent signal
   families agree, weighted by the current market regime.
2. **Loss control** — account-level daily loss limit and profit lock,
   loss-streak breaker, per-market session gating, ATR-scaled sizing,
   portfolio concurrency/risk caps, and a forced end-of-day flatten per
   instrument so no single day or overnight gap can do serious damage.

All results from the bundled synthetic generator validate the *machinery*,
not the edge. On synthetic random-walk data the system loses slowly to
costs — that is the correct, honest baseline. Market-structure strategies
(liquidity sweeps) exploit the behaviour of other traders' stops, which
synthetic data does not contain at all. Before any real capital: run on
real historical data, walk-forward validate, then paper trade against a
demo broker account for weeks. This is not financial advice.

## Architecture

```
ticks ─► BarAggregator ─► merged multi-symbol bar feed
                              │
                    PortfolioEngine (one shared account)
                    │  · sizes every trade off total account equity
                    │  · ≤ max_concurrent_positions across markets
                    │  · Σ open initial risk ≤ max_total_open_risk_pct
                    │  · thread-safe status() for the dashboard
                    │
        ┌───────────┼───────────┬───────────┐
     Engine       Engine      Engine      Engine        (one per market)
     XAUUSD       XAGUSD      WTIUSD      BTCUSD
        │
        ├─► shared indicators (ATR, ADX, session VWAP)
        ├─► Strategies (direction −1/0/+1 + confidence)
        │     trend family:      trend_ema · macd_momentum · donchian_breakout
        │                        bos_choch (BOS/CHoCH, off by default)
        │     reversion family:  rsi_reversion · vwap_deviation · liquidity_sweep
        │
        ├─► Confluence: ADX regime weighting + FAMILY-NORMALIZED scoring
        │   (each strategy's weight is divided by its family size, so three
        │   correlated trend voters can't stack the vote), min_score,
        │   min_agree distinct strategies, high-confidence veto.
        │
        ├─► EMA 5/9 trigger: a timing FILTER on approved entries — never a voter.
        │
        ├─► RiskManager: 0.5%/trade ATR sizing, −2% daily halt, +3% profit
        │   lock, 4-loss streak breaker, ≤6 trades/day, per-market session
        │   gate + entry cutoff, forced end-of-day flatten (never overnight).
        │
        └─► Broker: paper broker, conservative fills (spread/slippage, gaps
            fill at the worse of level/open, stop beats target in one bar,
            breakeven move at +1R). Real adapters implement broker/base.py.

server.py ─► GET /            read-only live dashboard (used by `live`)
             GET /api/status  JSON snapshot (equity, positions, sessions, trades)

webapp.py ─► `python -m algotrader web` — the full control panel:
             set capital / markets / days / mode from the browser, Start/Stop
             sessions, equity-curve chart with hover, per-market cards, final
             report with daily P&L, live trade list, CSV download.
             POST /api/run · POST /api/stop · GET /api/report · /api/trades.csv
```

## Quick start

```bash
cd algotrader

# run the test suite (49 tests)
python3 -m unittest discover -s tests -v

# browser control panel: set capital, pick markets, run backtests or paced
# demo sessions, watch the equity curve, download reports and trades
python3 -m algotrader web
# then open http://<host>:8899/ from any phone/tablet/laptop on the network

# same thing from the terminal instead of the browser
python3 -m algotrader live                       # XAUUSD,XAGUSD,WTIUSD,BTCUSD
python3 -m algotrader live --speed 0 --days 20   # instant replay, full report

# single-market backtest over a CSV of bars
python3 -m algotrader synth --out /tmp/xau.csv --days 60 --seed 42
python3 -m algotrader backtest --data /tmp/xau.csv --daily --trades
```

Real data works the same way — export 5-minute OHLCV bars to CSV with the
header `ts,open,high,low,close,volume` (ISO-8601 UTC timestamps).

## Markets

Per-instrument specs live in `algotrader/instruments.py` (costs, lot steps,
session calendars, synthetic parameters):

| symbol | kind | entry sessions (UTC) | EOD flat | weekends |
|---|---|---|---|---|
| XAUUSD | metal | 01:00–19:30 | 20:30 | no |
| XAGUSD | metal | 01:00–19:30 | 20:30 | no |
| WTIUSD | energy | 03:00–19:30 | 20:15 | no |
| BTCUSD | crypto | 00:00–23:59 | 23:45 | yes |

The union of these calendars keeps the bot scanning essentially 24×7 —
honestly, though: metals and energy are closed on weekends; only crypto
genuinely trades seven days a week.

## Configuration

Account-level defaults live in `algotrader/config.py`; override per run
with `--config file.json` (unknown keys are rejected). Key knobs:

| key | default | meaning |
|---|---|---|
| `risk_per_trade_pct` | 0.005 | equity fraction risked per trade |
| `sl_atr_mult` / `tp_r_multiple` | 1.5 / 2.0 | stop = 1.5·ATR, target = 2R |
| `daily_loss_limit_pct` | 0.02 | −2% on the day → flatten + halt |
| `daily_profit_lock_pct` | 0.03 | +3% on the day → flatten + bank it |
| `max_concurrent_positions` | 3 | across all markets |
| `max_total_open_risk_pct` | 0.015 | Σ open initial risks / equity |
| `min_score` / `min_agree` | 0.5 / 2 | confluence thresholds (family-normalized) |
| `use_ema_trigger` | true | EMA 5/9 timing filter on entries |
| `enable_liquidity_sweep` | true | stop-hunt fade voter (reversion family) |
| `enable_bos_choch` | false | BOS/CHoCH voter — off until it earns a seat on real data |

## Going live (deliberately not included)

`broker/base.py` defines the adapter interface — implement it against
OANDA, MT5, or IBKR and everything above it runs unchanged; `feed.py`'s
`Tick`/`BarAggregator` is the same story for a real price stream. The
recommended path: real historical data → walk-forward parameter validation
→ demo-account paper trading for weeks → only then small live size. Keep
the dashboard as the monitoring surface; run the process on an always-on
machine (a small VPS is ideal), not a phone.
