# algotrader — confluence-based intraday XAUUSD trader

A self-contained (pure-stdlib Python ≥ 3.10, zero dependencies) algorithmic
trading system for commodities, tuned for spot gold (XAUUSD) on 5-minute
bars. Five classic strategies vote; a regime-aware confluence engine only
trades when they agree; a risk layer enforces the discipline that makes
"end the day flat and preferably green" an actual rule rather than a hope.

## ⚠️ Honest disclaimer, up front

No algorithm can **guarantee** daily profitability — anyone who promises that
is selling something. What this system does instead is engineer the two
things that are controllable:

1. **Edge selection** — trade only when multiple independent, proven signal
   families agree, weighted by the current market regime.
2. **Loss control** — hard daily loss limit, profit lock, loss-streak
   breaker, session gating, ATR-scaled sizing, and a forced end-of-day
   flatten so no single day or overnight gap can do serious damage.

All results from the bundled synthetic generator validate the *machinery*,
not the edge. Before any real capital: run on real historical data,
walk-forward validate, then paper trade against a demo broker account.
This is not financial advice.

## Architecture

```
bars ──► Engine ──► shared indicators (ATR, ADX, session VWAP)
              │
              ├─► Strategies (each returns direction −1/0/+1 + confidence)
              │     trend_ema           EMA(21/55) crossover        [trend]
              │     macd_momentum       MACD hist + acceleration    [trend]
              │     donchian_breakout   20-bar channel breakout     [trend]
              │     rsi_reversion       RSI(14) + Bollinger fade    [reversion]
              │     vwap_deviation      fade ≥2 ATR from VWAP       [reversion]
              │
              ├─► Confluence: ADX regime detection weights trend vs.
              │   reversion styles; weighted score must clear min_score,
              │   ≥ min_agree strategies must agree, and any high-confidence
              │   opposite signal vetoes the trade.
              │
              ├─► RiskManager: fixed-fractional sizing (0.5%/trade, ATR stop),
              │   daily −2% halt, +3% profit lock, 4-loss streak breaker,
              │   ≤6 trades/day, London+NY session gate, 19:00 entry cutoff,
              │   20:30 UTC forced flatten (never holds overnight).
              │
              └─► Broker: paper broker with spread/slippage/gap-aware fills
                  (stop assumed to fill before target when a bar spans both;
                  breakeven stop move at +1R). Real adapters implement
                  broker/base.py without touching the layers above.
```

## Quick start

```bash
cd algotrader

# run the test suite
python3 -m unittest discover -s tests -v

# generate 60 weekdays of synthetic 5-min XAUUSD bars
python3 -m algotrader synth --out /tmp/xau.csv --days 60 --seed 42

# backtest with default config, show per-day P&L and the trade log
python3 -m algotrader backtest --data /tmp/xau.csv --daily --trades

# custom config
python3 -m algotrader backtest --data /tmp/xau.csv --config config/default.json
```

Real data works the same way — export 5-minute XAUUSD OHLCV bars to CSV with
the header `ts,open,high,low,close,volume` (ISO-8601 UTC timestamps).

## Configuration

Everything lives in `algotrader/config.py` (dataclass defaults) and can be
overridden per-run with `--config file.json`; unknown keys are rejected.
The knobs that matter most:

| key | default | meaning |
|---|---|---|
| `risk_per_trade_pct` | 0.005 | equity fraction risked per trade |
| `sl_atr_mult` / `tp_r_multiple` | 1.5 / 2.0 | stop = 1.5·ATR, target = 2R |
| `daily_loss_limit_pct` | 0.02 | −2% on the day → flatten + halt |
| `daily_profit_lock_pct` | 0.03 | +3% on the day → flatten + bank it |
| `max_consecutive_losses` | 4 | streak breaker (blocks new entries) |
| `min_score` / `min_agree` | 0.9 / 2 | confluence thresholds |
| `sessions` | 07:00–11:00, 12:30–19:30 UTC | London + New York liquidity |
| `eod_flat` | 20:30 UTC | everything closed by here, every day |

## Going live (deliberately not included)

`broker/base.py` defines the adapter interface — implement it against OANDA,
MT5, or IBKR and the strategy/confluence/risk layers run unchanged. The
recommended path: real historical data → walk-forward parameter validation →
demo-account paper trading for weeks → only then small live size.
