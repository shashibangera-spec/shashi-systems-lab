from datetime import datetime, timezone
from decimal import Decimal

import pytest

from shashi_engine.market_data import (
    MarketDataError,
    parse_candles,
    parse_ticker,
    ticker_to_json,
)


def test_parse_ticker_normalizes_decimal_prices_and_time():
    ticker = parse_ticker(
        {
            "symbol": "BTCUSD",
            "timestamp": 1795200000,
            "close": "65000.5",
            "mark_price": "65001",
            "best_bid": "65000",
            "best_ask": "65001",
        }
    )
    assert ticker.symbol == "BTCUSD"
    assert ticker.last_price == Decimal("65000.5")
    assert ticker.mark_price == Decimal("65001")
    assert ticker.observed_at.tzinfo == timezone.utc
    assert ticker_to_json(ticker)["last_price"] == "65000.5"


def test_ticker_rejects_wrong_symbol():
    with pytest.raises(MarketDataError, match="not BTCUSD"):
        parse_ticker({"symbol": "ETHUSD"})


def test_parse_candles_sorts_and_checks_ohlcv():
    rows = [
        {"time": 1795201800, "open": "11", "high": "13", "low": "10", "close": "12", "volume": "4"},
        {"time": 1795200000, "open": "10", "high": "12", "low": "9", "close": "11", "volume": "3"},
    ]
    candles = parse_candles(rows)
    assert candles[0].start_time < candles[1].start_time
    assert candles[0].resolution == "30m"
    assert candles[0].volume == Decimal("3")


def test_parse_candles_rejects_invalid_high_low():
    rows = [
        {"time": 1795200000, "open": "10", "high": "8", "low": "9", "close": "11", "volume": "1"}
    ]
    with pytest.raises(MarketDataError, match="OHLCV"):
        parse_candles(rows)


def test_parse_candles_rejects_negative_volume():
    rows = [
        {"time": 1795200000, "open": "10", "high": "12", "low": "9", "close": "11", "volume": "-1"}
    ]
    with pytest.raises(MarketDataError, match="OHLCV"):
        parse_candles(rows)
