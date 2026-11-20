from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from scripts.compare_btcusd_rest_websocket import candle_start_epoch, compare_ohlcv


def test_event_time_maps_to_utc_30m_bucket():
    assert candle_start_epoch("2026-11-20T20:49:09.267965+00:00") == 1795206600


def test_compare_ohlcv_requires_exact_decimal_match():
    ws = {"open": "10.0", "high": "12", "low": "9", "close": "11.5", "volume": "100"}
    rest = SimpleNamespace(
        open=Decimal("10"), high=Decimal("12.0"), low=Decimal("9.00"),
        close=Decimal("11.5"), volume=Decimal("100.0"),
    )
    assert all(compare_ohlcv(ws, rest).values())


def test_compare_ohlcv_flags_any_field_difference():
    ws = {"open": "10", "high": "12", "low": "9", "close": "11", "volume": "100"}
    rest = SimpleNamespace(
        open=Decimal("10"), high=Decimal("12"), low=Decimal("9"),
        close=Decimal("11.5"), volume=Decimal("100"),
    )
    result = compare_ohlcv(ws, rest)
    assert result["close"] is False
    assert all(value for key, value in result.items() if key != "close")
