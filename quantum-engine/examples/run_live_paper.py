"""Live PAPER trading on a REAL-TIME quote feed.

Runs the engine against a live market-data provider, building bars from polled
quotes and trading them through the paper broker (no real money). This is the
"run it on my system with real data" path.

Usage (on your machine, with internet):

    # Keyless (Yahoo, gold futures GC=F as the XAUUSD proxy, ~10-15m delayed):
    python examples/run_live_paper.py

    # Real spot XAU/USD, real-time (free key from twelvedata.com):
    TWELVEDATA_API_KEY=xxxx python examples/run_live_paper.py twelvedata

Ctrl-C to stop. Nothing here can place a real order.
"""

import os
import sys

from quantum_engine.brokers.simulated import SimulatedBroker
from quantum_engine.data.providers import get_provider
from quantum_engine.data.ticker import live_bars
from quantum_engine.engine.live import LiveTrader
from quantum_engine.risk.manager import RiskConfig, RiskManager
from quantum_engine.strategy.sniper_scalper import SniperScalper


def main() -> None:
    provider_name = sys.argv[1] if len(sys.argv) > 1 else "yahoo"
    symbol = "XAUUSD"

    kwargs = {}
    if provider_name == "twelvedata":
        kwargs["api_key"] = os.environ.get("TWELVEDATA_API_KEY", "")
    provider = get_provider(provider_name, **kwargs)

    strategy = SniperScalper()
    broker = SimulatedBroker(symbol=symbol, starting_balance=10_000.0)
    risk = RiskManager(RiskConfig(), starting_equity=10_000.0)
    trader = LiveTrader(strategy, broker, risk, symbol=symbol)

    print(f"Live PAPER trading {symbol} via {provider_name}. Ctrl-C to stop.")
    # 60s bars built from quotes polled every 5s. Free tiers are rate-limited,
    # so keep poll intervals sane.
    stream = live_bars(provider, symbol, timeframe_seconds=60, poll_seconds=5.0)
    try:
        trader.run(stream)
    except KeyboardInterrupt:
        print("\nStopped.")
    print(f"Equity: {broker.account().equity:,.2f}")


if __name__ == "__main__":
    main()
