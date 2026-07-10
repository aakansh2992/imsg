"""OHLCV bar model and CSV I/O."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator


@dataclass(frozen=True)
class Bar:
    ts: datetime  # bar open time, UTC
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        if self.ts.tzinfo is None:
            object.__setattr__(self, "ts", self.ts.replace(tzinfo=timezone.utc))


CSV_HEADER = ["ts", "open", "high", "low", "close", "volume"]


def write_csv(path: str | Path, bars: Iterable[Bar]) -> int:
    n = 0
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        for b in bars:
            w.writerow(
                [
                    b.ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    f"{b.open:.2f}",
                    f"{b.high:.2f}",
                    f"{b.low:.2f}",
                    f"{b.close:.2f}",
                    f"{b.volume:.0f}",
                ]
            )
            n += 1
    return n


def read_csv(path: str | Path) -> Iterator[Bar]:
    with open(path, newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            ts = datetime.strptime(row["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            yield Bar(
                ts=ts,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
