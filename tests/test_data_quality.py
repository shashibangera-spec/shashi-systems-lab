from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from shashi_engine.data_quality import inspect_candle_series
from shashi_engine.models import Candle


T0 = datetime(2026, 11, 20, 20, 0, tzinfo=timezone.utc)


def candle(offset_minutes: int) -> Candle:
    return Candle(
        symbol="BTCUSD",
        resolution="30m",
        start_time=T0 + timedelta(minutes=offset_minutes),
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal("105"),
        volume=Decimal("10"),
    )


def test_contiguous_series_is_acceptable() -> None:
    report = inspect_candle_series(
        [candle(0), candle(30), candle(60)],
        as_of=T0 + timedelta(minutes=95),
    )
    assert report.acceptable
    assert report.missing_intervals == 0
    assert not report.stale


def test_duplicate_timestamp_is_reported_and_fails_closed() -> None:
    report = inspect_candle_series(
        [candle(0), candle(30), candle(30)],
        as_of=T0 + timedelta(minutes=65),
    )
    assert report.duplicate_starts == (T0 + timedelta(minutes=30),)
    assert not report.acceptable


def test_out_of_order_input_is_reported_not_silently_sorted() -> None:
    report = inspect_candle_series(
        [candle(30), candle(0), candle(60)],
        as_of=T0 + timedelta(minutes=95),
    )
    assert report.out_of_order_pairs == ((T0 + timedelta(minutes=30), T0),)
    assert not report.acceptable


def test_missing_candle_intervals_are_counted() -> None:
    report = inspect_candle_series(
        [candle(0), candle(90)],
        as_of=T0 + timedelta(minutes=125),
    )
    assert report.missing_intervals == 2
    assert not report.acceptable


def test_stale_series_is_reported() -> None:
    report = inspect_candle_series(
        [candle(0)],
        as_of=T0 + timedelta(hours=3),
        max_age=timedelta(minutes=35),
    )
    assert report.stale
    assert not report.acceptable


def test_empty_series_is_not_acceptable() -> None:
    report = inspect_candle_series([], as_of=T0)
    assert report.candle_count == 0
    assert report.stale
    assert not report.acceptable


def test_quality_checker_requires_utc_as_of() -> None:
    with pytest.raises(ValueError, match="UTC"):
        inspect_candle_series([candle(0)], as_of=datetime(2026, 11, 20, 21, 0))
