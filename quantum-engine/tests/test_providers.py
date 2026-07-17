"""Parser tests against recorded provider response shapes.

These verify the ingestion logic without touching the network, so they run
anywhere. The fixtures mirror the real JSON/CSV each API returns.
"""

import pytest

from quantum_engine.data.providers import (
    StooqProvider,
    TwelveDataProvider,
    YahooProvider,
    get_provider,
)
from quantum_engine.data.http import HTTPError


YAHOO_FIXTURE = {
    "chart": {
        "result": [
            {
                "meta": {"regularMarketPrice": 2345.6,
                         "regularMarketTime": 1710000600},
                "timestamp": [1710000000, 1710000060, 1710000120],
                "indicators": {
                    "quote": [
                        {
                            "open": [2340.0, 2341.0, None],
                            "high": [2342.0, 2343.0, None],
                            "low": [2339.0, 2340.5, None],
                            "close": [2341.0, 2342.5, None],
                            "volume": [100, 120, None],
                        }
                    ]
                },
            }
        ]
    }
}


def test_yahoo_parse_history_skips_null_padding():
    bars = YahooProvider.parse_history(YAHOO_FIXTURE)
    assert len(bars) == 2  # third (null) row dropped
    assert bars[0].open == 2340.0
    assert bars[1].close == 2342.5
    assert bars[0].timestamp < bars[1].timestamp


def test_yahoo_parse_quote_builds_spread():
    tick = YahooProvider.parse_quote(YAHOO_FIXTURE)
    assert tick.bid < 2345.6 < tick.ask
    assert tick.spread > 0


def test_yahoo_symbol_maps_xauusd_to_gold_future():
    assert YahooProvider()._sym("XAUUSD") == "GC=F"
    assert YahooProvider()._sym("AAPL") == "AAPL"


STOOQ_FIXTURE = (
    "Date,Open,High,Low,Close,Volume\n"
    "2024-01-02,2062.10,2078.40,2059.80,2073.20,0\n"
    "2024-01-03,2073.20,2075.00,2028.50,2035.10,0\n"
)


def test_stooq_parse_history():
    bars = StooqProvider.parse_history(STOOQ_FIXTURE)
    assert len(bars) == 2
    assert bars[0].high == 2078.40
    assert bars[1].close == 2035.10


def test_stooq_skips_bad_rows():
    text = STOOQ_FIXTURE + "2024-01-04,N/A,N/A,N/A,N/A,0\n"
    bars = StooqProvider.parse_history(text)
    assert len(bars) == 2


TD_FIXTURE = {
    "meta": {"symbol": "XAU/USD", "interval": "1min"},
    "values": [
        {"datetime": "2024-01-02 15:31:00", "open": "2062.1", "high": "2062.8",
         "low": "2061.9", "close": "2062.4", "volume": "0"},
        {"datetime": "2024-01-02 15:30:00", "open": "2061.5", "high": "2062.2",
         "low": "2061.4", "close": "2062.1", "volume": "0"},
    ],
    "status": "ok",
}


def test_twelvedata_parse_sorts_ascending():
    bars = TwelveDataProvider.parse_history(TD_FIXTURE)
    assert len(bars) == 2
    assert bars[0].timestamp < bars[1].timestamp  # sorted oldest-first
    assert bars[1].close == 2062.4


def test_twelvedata_error_raises():
    with pytest.raises(HTTPError):
        TwelveDataProvider.parse_history({"status": "error", "message": "bad key"})


def test_twelvedata_quote_uses_bid_ask_when_present():
    tick = TwelveDataProvider.parse_quote(
        {"status": "ok", "bid": "2345.1", "ask": "2345.5", "timestamp": "0"}
    )
    assert tick.bid == 2345.1
    assert tick.ask == 2345.5


def test_twelvedata_requires_api_key():
    with pytest.raises(ValueError):
        TwelveDataProvider(api_key="")


def test_get_provider_factory():
    assert isinstance(get_provider("yahoo"), YahooProvider)
    assert isinstance(get_provider("stooq"), StooqProvider)
    with pytest.raises(ValueError):
        get_provider("nope")
