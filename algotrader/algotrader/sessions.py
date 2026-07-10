"""Trading-hours gating in UTC."""
from __future__ import annotations

from datetime import datetime, time


def parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


class SessionClock:
    def __init__(self, sessions: list[list[str]], entry_cutoff: str, eod_flat: str) -> None:
        self.windows = [(parse_hhmm(a), parse_hhmm(b)) for a, b in sessions]
        self.entry_cutoff = parse_hhmm(entry_cutoff)
        self.eod_flat = parse_hhmm(eod_flat)

    def in_session(self, ts: datetime) -> bool:
        t = ts.time()
        return any(a <= t < b for a, b in self.windows)

    def can_enter(self, ts: datetime) -> bool:
        return self.in_session(ts) and ts.time() < self.entry_cutoff

    def past_eod(self, ts: datetime) -> bool:
        return ts.time() >= self.eod_flat
