# Quantum Engine

An **honest** algorithmic trading research framework for gold (XAUUSD). Pure
Python, zero required dependencies, broker-agnostic, paper-trading by default.

> This project was requested as a bot that would "double capital every day and
> always end the day in profit." **That is not possible — for anyone, with any
> engine.** This README explains why, up front, and then gives you a genuinely
> useful framework that doesn't lie to you.

---

## Read this before anything else

**No strategy can guarantee daily profit, let alone doubling capital daily.**

- Doubling $1,000 every trading day is ~$1M in 10 days and larger than the
  entire gold market within a month. The market cannot fill those orders. The
  math refutes the premise.
- "Always green by end of day" is impossible. XAUUSD gaps and spikes on news
  (CPI, FOMC, geopolitics). Any system that appears never to lose is either
  curve-fit to the past or is silently taking unbounded risk that eventually
  blows up the account on a single tick.
- Every product marketed as a "sniper scalper that doubles daily" is a scam.
  This framework is deliberately **not** marketed that way.

What good algorithmic trading actually looks like: a defined edge, ruthless
risk control, honest backtesting with realistic costs, walk-forward validation,
and the humility to expect losing days. That is what this repo gives you.
Trading leveraged gold can lose you more than you deposit. **You are
responsible for your own money.** See [LICENSE](LICENSE) — no warranty.

---

## What's in the box

```
quantum_engine/
├── types.py                 Domain types (Bar, Order, Position, Signal, ...)
├── config.py                Optional YAML config (built-in fallback parser)
├── cli.py                   `backtest`, `paper`, `gen-data` commands
├── strategy/
│   ├── indicators.py        Streaming EMA / SMA / RSI / ATR / RollingVWAP
│   └── sniper_scalper.py    Confluence scalping strategy (trend+momentum+regime)
├── risk/
│   └── manager.py           Position sizing, daily loss limit, drawdown kill-switch
├── brokers/
│   ├── base.py              BrokerAdapter interface — implement for ANY broker
│   ├── simulated.py         Paper broker with spread/slippage/commission (default)
│   └── mt5.py               MetaTrader 5 live adapter (optional, gated)
├── data/
│   └── feed.py              CSV feed + synthetic data generator
└── engine/
    ├── backtester.py        Event-driven backtester + metrics
    └── live.py              Live/paper trading loop (same logic as backtest)
```

The strategy, risk manager, and broker objects are **shared** between the
backtester and the live loop, so a passing backtest exercises the real
execution code path — not a separate toy.

## Quick start

No installation needed for the core (standard library only):

```bash
cd quantum-engine

# Run the full pipeline on synthetic data (proves plumbing, NOT profitability)
PYTHONPATH=. python -m quantum_engine.cli backtest --synthetic 5000

# Generate a synthetic CSV you can inspect
PYTHONPATH=. python -m quantum_engine.cli gen-data --out sample.csv --bars 5000

# Backtest on your own real OHLCV data
PYTHONPATH=. python -m quantum_engine.cli backtest --data your_xauusd_1m.csv

# Paper-trade the same logic through the simulated broker
PYTHONPATH=. python -m quantum_engine.cli paper --synthetic 3000
```

CSV format expected by `--data`:

```
timestamp,open,high,low,close,volume
2024-01-02T13:30:00,2062.10,2062.80,2061.90,2062.40,1234
```

Run the tests:

```bash
pip install pytest
PYTHONPATH=. python -m pytest -q
```

## The SniperScalper strategy

It only enters when three independent conditions agree — this filtering is what
separates a survivable scalper from a gambler:

1. **Trend** — fast EMA above/below slow EMA, and price on the correct side of
   a rolling VWAP.
2. **Momentum** — RSI pulling back into the trend (buy dips in uptrends, sell
   pops in downtrends), not chasing extremes.
3. **Regime** — ATR inside a tradable band. Too quiet → spreads dominate; too
   wild → news chaos. Stand aside in both.

Stops and targets are **volatility-scaled** (ATR multiples), default reward:risk
of 1.5:1. Because the filters are strict, it trades infrequently — that is by
design, not a bug. Tune the parameters in `SniperScalperConfig` and, critically,
**validate on real data with walk-forward testing** before trusting anything.

Want a different strategy? Subclass `Strategy` and implement `on_bar`. The rest
of the framework is unchanged.

## Risk management (the part that actually matters)

`RiskManager` enforces:

- **Fixed-fractional sizing** — each trade risks a set % of equity given its
  stop distance. The strategy never picks size; risk does.
- **Daily loss limit** — a per-day kill switch; no new trades after the day's
  realised loss crosses the threshold. Resets next session.
- **Max-drawdown circuit breaker** — a hard, sticky halt from peak equity that a
  new day does *not* clear.
- **Position caps** — absolute lot ceiling and broker-minimum flooring.

None of this makes trading safe. It makes ruin *less likely and bounded*.

## Connecting a broker ("any broker")

Implement the six methods of `BrokerAdapter` (`connect`, `disconnect`,
`account`, `position`, `submit`, `close`) for your venue and the engine works
unchanged. A MetaTrader 5 adapter ships in `brokers/mt5.py` as a reference.

### ⚠️ Going live (real money)

Live execution is **off by default** and gated:

- `MT5Broker` refuses to initialise unless you pass `allow_live=True`.
- The CLI never routes to a live broker — you must write your own script.
- Start on a **demo account**. Paper-trade for weeks. Expect losing days.

```python
from quantum_engine.brokers.mt5 import MT5Broker  # Windows + MT5 terminal only
broker = MT5Broker(symbol="XAUUSD", allow_live=True)  # deliberate, explicit
```

You accept all risk. The authors accept none.

## License

MIT — see [LICENSE](LICENSE). Provided "as is", with no warranty and no
liability for trading losses.
