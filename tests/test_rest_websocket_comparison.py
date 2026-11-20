from decimal import Decimal
from types import SimpleNamespace

from scripts.compare_btcusd_rest_websocket import candle_start_epoch, compare_ohlcv


def test_explicit_candle_start_maps_to_utc_30m_bucket():
    assert candle_start_epoch("2026-11-20T20:30:00+00:00") == 1795206600


def test_missing_explicit_candle_start_fails_closed():
    try:
        candle_start_epoch("not_provided")
    except ValueError as exc:
        assert "missing explicit candle start" in str(exc)
    else:
        raise AssertionError("Expected missing cst to be rejected")


def test_unaligned_explicit_candle_start_fails_closed():
    try:
        candle_start_epoch("2026-11-20T20:31:00+00:00")
    except ValueError as exc:
        assert "not aligned" in str(exc)
    else:
        raise AssertionError("Expected unaligned cst to be rejected")


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
