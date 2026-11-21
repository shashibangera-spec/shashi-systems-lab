from datetime import datetime, timezone
from decimal import Decimal

import pytest

from shashi_engine.models import Candle
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


def test_parse_candles_preserves_source_order_and_checks_ohlcv():
    rows = [
        {"time": 1795203000, "open": "11", "high": "13", "low": "10", "close": "12", "volume": "4"},
        {"time": 1795201200, "open": "10", "high": "12", "low": "9", "close": "11", "volume": "3"},
    ]
    candles = parse_candles(rows)
    assert candles[0].start_time > candles[1].start_time
    assert candles[0].resolution == "30m"
    assert isinstance(candles[0], Candle)
    assert candles[0].volume == Decimal("4")


def test_parse_candles_rejects_invalid_high_low():
    rows = [
        {"time": 1795201200, "open": "10", "high": "8", "low": "9", "close": "11", "volume": "1"}
    ]
    with pytest.raises(MarketDataError, match="OHLCV"):
        parse_candles(rows)


def test_parse_candles_rejects_negative_volume():
    rows = [
        {"time": 1795201200, "open": "10", "high": "12", "low": "9", "close": "11", "volume": "-1"}
    ]
    with pytest.raises(MarketDataError, match="OHLCV"):
        parse_candles(rows)


@pytest.mark.parametrize(
    ("epoch", "expected"),
    [
        (1795200000, "2026-11-20T18:40:00+00:00"),
        (1795200000000, "2026-11-20T18:40:00+00:00"),
        (1795200000000000, "2026-11-20T18:40:00+00:00"),
        (1795200000000000000, "2026-11-20T18:40:00+00:00"),
        ("1795200000000000", "2026-11-20T18:40:00+00:00"),
    ],
)
def test_ticker_accepts_epoch_seconds_milliseconds_microseconds_and_nanoseconds(epoch, expected):
    ticker = parse_ticker({"symbol": "BTCUSD", "timestamp": epoch})
    assert ticker.observed_at.isoformat() == expected


def test_timestamp_rejects_out_of_range_epoch():
    from shashi_engine.market_data import _timestamp

    with pytest.raises(MarketDataError, match="outside the supported range"):
        _timestamp("999999999999999999999999", "timestamp")


def test_fetch_historical_candles_returns_complete_sessions_and_excludes_current_session(monkeypatch):
    from datetime import timedelta
    from shashi_engine import market_data

    start = datetime(2026, 11, 19, 0, 0, tzinfo=timezone.utc)
    all_rows = [
        Candle("BTCUSD", "30m", start + timedelta(minutes=30 * i),
               Decimal("60000"), Decimal("60100"), Decimal("59900"),
               Decimal("60050"), Decimal("1"))
        for i in range(96)
    ]
    calls = []

    def fake_fetch(start_epoch, end_epoch, resolution="30m", timeout=10):
        calls.append((start_epoch, end_epoch))
        return list(reversed([
            candle for candle in all_rows
            if start_epoch <= int(candle.start_time.timestamp()) < end_epoch
        ]))

    monkeypatch.setattr(market_data, "fetch_candles", fake_fetch)
    # 13:00 UTC on Nov 21: most recent completed AMT boundary is 00:00 UTC Nov 21.
    result = market_data.fetch_historical_candles(
        days=2, now=datetime(2026, 11, 21, 13, 0, tzinfo=timezone.utc)
    )
    assert len(result) == 96
    assert result[0].start_time == start
    assert result[-1].end_time == datetime(2026, 11, 21, 0, 0, tzinfo=timezone.utc)
    assert len(calls) == 2
    assert all(end - begin <= 48 * 1800 for begin, end in calls)


def test_fetch_historical_candles_fails_closed_on_missing_bar(monkeypatch):
    from datetime import timedelta
    from shashi_engine import market_data

    start = datetime(2026, 11, 19, 0, 0, tzinfo=timezone.utc)
    rows = [
        Candle("BTCUSD", "30m", start + timedelta(minutes=30 * i),
               Decimal("60000"), Decimal("60100"), Decimal("59900"),
               Decimal("60050"), Decimal("1"))
        for i in range(96) if i != 17
    ]
    monkeypatch.setattr(market_data, "fetch_candles", lambda *args, **kwargs: rows)
    with pytest.raises(MarketDataError, match="coverage is incomplete"):
        market_data.fetch_historical_candles(
            days=2, now=datetime(2026, 11, 21, 13, 0, tzinfo=timezone.utc)
        )


@pytest.mark.parametrize("days", [0, -1, 91, 1.5])
def test_fetch_historical_candles_rejects_invalid_day_range(days):
    from shashi_engine.market_data import fetch_historical_candles

    with pytest.raises(ValueError, match="1 to 90"):
        fetch_historical_candles(days=days)
