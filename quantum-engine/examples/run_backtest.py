"""End-to-end example: backtest the SniperScalper on synthetic data.

Run from the quantum-engine directory:

    python examples/run_backtest.py

Remember: synthetic data is fake. This demonstrates the full pipeline
(strategy -> risk sizing -> simulated execution -> metrics). It tells you
NOTHING about live profitability. Plug in real historical XAUUSD bars via
CSVBarFeed and run walk-forward validation before drawing any conclusions.
"""

from quantum_engine.data.feed import SyntheticBarFeed
from quantum_engine.engine.backtester import Backtester
from quantum_engine.strategy.sniper_scalper import SniperScalper, SniperScalperConfig


def main() -> None:
    strategy = SniperScalper(SniperScalperConfig())
    backtester = Backtester(strategy, starting_equity=10_000.0)
    result = backtester.run(SyntheticBarFeed(n_bars=5000, seed=1))

    print("Quantum Engine — SniperScalper on SYNTHETIC data")
    print("-" * 48)
    print(result.summary())
    print("Reminder: synthetic data is not real. Validate on real bars.")


if __name__ == "__main__":
    main()
