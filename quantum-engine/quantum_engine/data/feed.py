"""Market data feeds.

A feed is just an iterable of Bars. The CSV feed reads the common OHLCV export
format; the synthetic feed generates plausible XAUUSD-like data for demos and
tests without any external dependency.
"""

from __future__ import annotations

import csv
import math
import random
from datetime import datetime, timedelta
from typing import Iterator, Optional

from ..types import Bar


class CSVBarFeed:
    """Reads bars from a CSV with columns:

    timestamp,open,high,low,close,volume

    ``timestamp`` may be ISO-8601 or a unix epoch (seconds).
    """

    def __init__(self, path: str):
        self.path = path

    def __iter__(self) -> Iterator[Bar]:
        with open(self.path, newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                yield Bar(
                    timestamp=self._parse_ts(row["timestamp"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume", 0) or 0),
                )

    @staticmethod
    def _parse_ts(raw: str) -> datetime:
        raw = raw.strip()
        try:
            return datetime.fromtimestamp(float(raw))
        except ValueError:
            return datetime.fromisoformat(raw)


class SyntheticBarFeed:
    """Generates GBM-with-regimes XAUUSD-like 1-minute bars.

    Purely for demos and tests. It is NOT market data and any backtest result
    on it is meaningless for real performance — it only proves the plumbing
    works end to end.
    """

    def __init__(
        self,
        n_bars: int = 2000,
        start_price: float = 2000.0,
        start: Optional[datetime] = None,
        seed: Optional[int] = 42,
        annual_vol: float = 0.15,
    ):
        self.n_bars = n_bars
        self.start_price = start_price
        self.start = start or datetime(2024, 1, 1, 0, 0, 0)
        self.seed = seed
        self.annual_vol = annual_vol

    def __iter__(self) -> Iterator[Bar]:
        rng = random.Random(self.seed)
        price = self.start_price
        # per-minute vol from annualised (minutes in a trading year ~ 372,000)
        minute_vol = self.annual_vol / math.sqrt(372_000)
        drift = 0.0
        t = self.start
        for i in range(self.n_bars):
            # Occasionally flip a gentle trend regime.
            if i % 200 == 0:
                drift = rng.uniform(-1.0, 1.0) * minute_vol * 0.5
            ret = drift + rng.gauss(0.0, minute_vol)
            new_price = price * math.exp(ret)
            high = max(price, new_price) * (1 + abs(rng.gauss(0, minute_vol / 2)))
            low = min(price, new_price) * (1 - abs(rng.gauss(0, minute_vol / 2)))
            volume = abs(rng.gauss(500, 150))
            yield Bar(timestamp=t, open=price, high=high, low=low,
                      close=new_price, volume=volume)
            price = new_price
            t = t + timedelta(minutes=1)


def write_synthetic_csv(path: str, **kwargs) -> int:
    feed = SyntheticBarFeed(**kwargs)
    count = 0
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for bar in feed:
            writer.writerow([bar.timestamp.isoformat(), f"{bar.open:.3f}",
                             f"{bar.high:.3f}", f"{bar.low:.3f}",
                             f"{bar.close:.3f}", f"{bar.volume:.1f}"])
            count += 1
    return count
