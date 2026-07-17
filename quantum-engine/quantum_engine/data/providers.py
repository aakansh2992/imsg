"""Real market-data providers for gold (XAUUSD).

Each provider knows how to (a) download historical OHLCV bars and, where the API
allows, (b) fetch a live quote. All parsing is separated from I/O so it can be
unit-tested against recorded response fixtures without network access.

Providers included
------------------
* ``YahooProvider``      — keyless. Uses Yahoo's chart API. Maps XAUUSD -> GC=F
                            (COMEX gold futures, the standard keyless proxy for
                            spot gold). Intraday + daily history and live-ish
                            quotes (delayed ~10-15 min on the free endpoint).
* ``StooqProvider``      — keyless. Daily history for the true XAUUSD spot symbol.
* ``TwelveDataProvider`` — free API key. True XAU/USD spot, real intraday bars and
                            a real-time price endpoint. Best choice for live use.
* ``MT5Provider``        — pulls quotes/bars straight from a connected MetaTrader 5
                            terminal (Windows). Truest broker data.

Pick one with ``get_provider(name, **kwargs)``.
"""

from __future__ import annotations

import csv
import io
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import List, Optional

from ..types import Bar, Tick
from . import http


class DataProvider(ABC):
    name: str = "provider"

    @abstractmethod
    def history(self, symbol: str, interval: str, lookback: str) -> List[Bar]:
        """Return OHLCV bars, oldest first.

        ``interval`` is a provider-normalised timeframe like ``1m``/``5m``/``1h``/
        ``1d``. ``lookback`` is a coarse range hint like ``5d``/``1mo``/``max``.
        """

    def quote(self, symbol: str) -> Tick:  # pragma: no cover - overridden
        raise NotImplementedError(f"{self.name} does not support live quotes")


# --------------------------------------------------------------------------- #
# Yahoo Finance (keyless)
# --------------------------------------------------------------------------- #

class YahooProvider(DataProvider):
    name = "yahoo"
    BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"

    # Yahoo has no clean spot XAUUSD; GC=F (gold futures) is the standard proxy.
    SYMBOL_MAP = {"XAUUSD": "GC=F", "GOLD": "GC=F", "XAU/USD": "GC=F"}

    def _sym(self, symbol: str) -> str:
        return self.SYMBOL_MAP.get(symbol.upper(), symbol)

    def history(self, symbol: str, interval: str = "1m",
                lookback: str = "5d") -> List[Bar]:
        sym = self._sym(symbol)
        url = f"{self.BASE}{sym}?interval={interval}&range={lookback}"
        payload = http.get_json(url)
        return self.parse_history(payload)

    def quote(self, symbol: str) -> Tick:
        sym = self._sym(symbol)
        url = f"{self.BASE}{sym}?interval=1m&range=1d"
        payload = http.get_json(url)
        return self.parse_quote(payload)

    @staticmethod
    def parse_history(payload: dict) -> List[Bar]:
        result = payload["chart"]["result"]
        if not result:
            return []
        node = result[0]
        stamps = node.get("timestamp") or []
        q = node["indicators"]["quote"][0]
        opens, highs = q.get("open", []), q.get("high", [])
        lows, closes = q.get("low", []), q.get("close", [])
        vols = q.get("volume", [])
        bars: List[Bar] = []
        for i, ts in enumerate(stamps):
            o, h, l, c = opens[i], highs[i], lows[i], closes[i]
            if None in (o, h, l, c):
                continue  # Yahoo pads gaps with nulls.
            v = vols[i] if i < len(vols) and vols[i] is not None else 0.0
            bars.append(Bar(
                timestamp=datetime.fromtimestamp(ts, tz=timezone.utc),
                open=float(o), high=float(h), low=float(l),
                close=float(c), volume=float(v),
            ))
        return bars

    @staticmethod
    def parse_quote(payload: dict) -> Tick:
        node = payload["chart"]["result"][0]
        meta = node.get("meta", {})
        price = meta.get("regularMarketPrice")
        if price is None:
            # Fall back to the last non-null close.
            closes = node["indicators"]["quote"][0].get("close", [])
            price = next((c for c in reversed(closes) if c is not None), None)
        if price is None:
            raise http.HTTPError("Yahoo quote: no price in payload")
        ts = meta.get("regularMarketTime")
        when = (datetime.fromtimestamp(ts, tz=timezone.utc)
                if ts else datetime.now(tz=timezone.utc))
        price = float(price)
        # Yahoo gives a single price; synthesise a tiny symmetric spread.
        spread = max(price * 0.00005, 0.02)
        return Tick(timestamp=when, bid=price - spread / 2, ask=price + spread / 2)


# --------------------------------------------------------------------------- #
# Stooq (keyless, daily)
# --------------------------------------------------------------------------- #

class StooqProvider(DataProvider):
    name = "stooq"
    BASE = "https://stooq.com/q/d/l/"

    _INTERVAL = {"1d": "d", "1w": "w", "1mo": "m", "d": "d", "w": "w", "m": "m"}

    def history(self, symbol: str, interval: str = "1d",
                lookback: str = "max") -> List[Bar]:
        i = self._INTERVAL.get(interval, "d")
        sym = symbol.lower().replace("/", "")
        url = f"{self.BASE}?s={sym}&i={i}"
        text = http.get_text(url)
        return self.parse_history(text)

    @staticmethod
    def parse_history(text: str) -> List[Bar]:
        bars: List[Bar] = []
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            if not row.get("Date") or row.get("Open") in (None, "", "N/A"):
                continue
            bars.append(Bar(
                timestamp=datetime.strptime(row["Date"], "%Y-%m-%d").replace(
                    tzinfo=timezone.utc),
                open=float(row["Open"]), high=float(row["High"]),
                low=float(row["Low"]), close=float(row["Close"]),
                volume=float(row.get("Volume") or 0.0),
            ))
        return bars


# --------------------------------------------------------------------------- #
# Twelve Data (API key — true XAU/USD spot, real-time)
# --------------------------------------------------------------------------- #

class TwelveDataProvider(DataProvider):
    name = "twelvedata"
    BASE = "https://api.twelvedata.com"

    _INTERVAL = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
                 "1h": "1h", "4h": "4h", "1d": "1day"}

    def __init__(self, api_key: str, symbol_fmt: str = "XAU/USD"):
        if not api_key:
            raise ValueError("TwelveDataProvider requires an api_key "
                             "(free tier at twelvedata.com)")
        self.api_key = api_key
        self.symbol_fmt = symbol_fmt

    def _sym(self, symbol: str) -> str:
        if symbol.upper() in ("XAUUSD", "XAU/USD", "GOLD"):
            return self.symbol_fmt
        return symbol

    def history(self, symbol: str, interval: str = "1m",
                lookback: str = "5d") -> List[Bar]:
        iv = self._INTERVAL.get(interval, "1min")
        size = _lookback_to_outputsize(lookback, iv)
        sym = self._sym(symbol).replace("/", "%2F")
        url = (f"{self.BASE}/time_series?symbol={sym}&interval={iv}"
               f"&outputsize={size}&apikey={self.api_key}&order=ASC")
        payload = http.get_json(url)
        return self.parse_history(payload)

    def quote(self, symbol: str) -> Tick:
        sym = self._sym(symbol).replace("/", "%2F")
        url = f"{self.BASE}/quote?symbol={sym}&apikey={self.api_key}"
        payload = http.get_json(url)
        return self.parse_quote(payload)

    @staticmethod
    def parse_history(payload: dict) -> List[Bar]:
        if payload.get("status") == "error":
            raise http.HTTPError(f"TwelveData error: {payload.get('message')}")
        values = payload.get("values", [])
        bars: List[Bar] = []
        for row in values:
            bars.append(Bar(
                timestamp=_parse_td_time(row["datetime"]),
                open=float(row["open"]), high=float(row["high"]),
                low=float(row["low"]), close=float(row["close"]),
                volume=float(row.get("volume") or 0.0),
            ))
        bars.sort(key=lambda b: b.timestamp)
        return bars

    @staticmethod
    def parse_quote(payload: dict) -> Tick:
        if payload.get("status") == "error":
            raise http.HTTPError(f"TwelveData error: {payload.get('message')}")
        bid = payload.get("bid")
        ask = payload.get("ask")
        if bid is not None and ask is not None:
            price_ts = _parse_td_time(str(payload.get("timestamp") or ""))
            return Tick(timestamp=price_ts, bid=float(bid), ask=float(ask))
        close = float(payload["close"])
        ts = payload.get("timestamp")
        when = (datetime.fromtimestamp(int(ts), tz=timezone.utc)
                if ts else datetime.now(tz=timezone.utc))
        spread = max(close * 0.00005, 0.02)
        return Tick(timestamp=when, bid=close - spread / 2, ask=close + spread / 2)


# --------------------------------------------------------------------------- #
# MetaTrader 5 (broker-native)
# --------------------------------------------------------------------------- #

class MT5Provider(DataProvider):
    name = "mt5"

    def __init__(self, symbol: str = "XAUUSD"):
        try:  # pragma: no cover - environment dependent
            import MetaTrader5 as mt5  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "MetaTrader5 package not installed (Windows + MT5 terminal "
                "required). Use YahooProvider or TwelveDataProvider instead."
            ) from exc
        self._mt5 = mt5
        self.symbol = symbol
        if not mt5.initialize():
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")

    _TF = None  # resolved lazily to avoid importing mt5 at module load

    def history(self, symbol: str, interval: str = "1m",
                lookback: str = "5d") -> List[Bar]:  # pragma: no cover
        mt5 = self._mt5
        tf_map = {"1m": mt5.TIMEFRAME_M1, "5m": mt5.TIMEFRAME_M5,
                  "15m": mt5.TIMEFRAME_M15, "1h": mt5.TIMEFRAME_H1,
                  "1d": mt5.TIMEFRAME_D1}
        tf = tf_map.get(interval, mt5.TIMEFRAME_M1)
        count = _lookback_to_outputsize(lookback, interval)
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
        bars = []
        for r in rates or []:
            bars.append(Bar(
                timestamp=datetime.fromtimestamp(int(r["time"]), tz=timezone.utc),
                open=float(r["open"]), high=float(r["high"]),
                low=float(r["low"]), close=float(r["close"]),
                volume=float(r["tick_volume"]),
            ))
        return bars

    def quote(self, symbol: str) -> Tick:  # pragma: no cover
        t = self._mt5.symbol_info_tick(symbol)
        return Tick(timestamp=datetime.now(tz=timezone.utc),
                    bid=float(t.bid), ask=float(t.ask))


# --------------------------------------------------------------------------- #
# Helpers + factory
# --------------------------------------------------------------------------- #

def _parse_td_time(raw: str) -> datetime:
    raw = raw.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        return datetime.fromtimestamp(int(raw), tz=timezone.utc)
    except (ValueError, OSError):
        return datetime.now(tz=timezone.utc)


_MINUTES = {"1min": 1, "5min": 5, "15min": 15, "30min": 30, "1h": 60,
            "4h": 240, "1day": 1440, "1m": 1, "5m": 5, "15m": 15, "1d": 1440}


def _lookback_to_outputsize(lookback: str, interval: str) -> int:
    """Rough conversion from a range hint to a bar count (capped)."""
    days = {"1d": 1, "5d": 5, "1mo": 22, "3mo": 66, "6mo": 132,
            "1y": 264, "max": 500}.get(lookback, 5)
    per_day = int(1440 / _MINUTES.get(interval, 1)) if _MINUTES.get(interval, 1) < 1440 else 1
    return max(1, min(5000, days * per_day))


_PROVIDERS = {
    "yahoo": YahooProvider,
    "stooq": StooqProvider,
    "twelvedata": TwelveDataProvider,
    "mt5": MT5Provider,
}


def get_provider(name: str, **kwargs) -> DataProvider:
    name = name.lower()
    if name not in _PROVIDERS:
        raise ValueError(f"Unknown provider '{name}'. "
                         f"Choose from: {', '.join(_PROVIDERS)}")
    return _PROVIDERS[name](**kwargs)
