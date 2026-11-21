from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from shashi_engine.amt_pa_backtest import (
    BacktestConfig, _expected_funding_times, _target,
    compute_session_profile, run_backtest, session_date_for,
)
from shashi_engine.accounting import AccountingPolicy, FeeSchedule
from shashi_engine.models import Candle, Instrument

UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))


def instrument(product_id: int = 27) -> Instrument:
    return Instrument(
        product_id, "BTCUSD", "perpetual_futures", "live", "operational",
        Decimal("0.001"), "BTC", Decimal("0.50"), "USD", "USD", 28800,
    )


def session_candles(day: date, base: Decimal = Decimal("60000")) -> list[Candle]:
    start = datetime.combine(day, datetime.min.time(), tzinfo=IST) + timedelta(hours=5, minutes=30)
    result = []
    for i in range(48):
        stamp = (start + timedelta(minutes=30 * i)).astimezone(UTC)
        result.append(Candle(
            "BTCUSD", "30m", stamp, base, base + Decimal("60"),
            base - Decimal("40"), base + Decimal("10"), Decimal("1"),
        ))
    return result


def test_session_reset_is_0530_ist():
    bars = session_candles(date(2026, 11, 20))
    assert session_date_for(bars[0]) == date(2026, 11, 20)
    assert session_date_for(bars[-1]) == date(2026, 11, 20)


def test_profile_requires_exact_complete_session():
    bars = session_candles(date(2026, 11, 20))
    cfg = BacktestConfig()
    assert compute_session_profile(bars[:-1], cfg) is None
    assert compute_session_profile(bars, cfg) is not None


def test_profile_is_deterministic_and_has_valid_value_area():
    bars = session_candles(date(2026, 11, 20))
    cfg = BacktestConfig()
    first = compute_session_profile(bars, cfg)
    second = compute_session_profile(list(reversed(bars)), cfg)
    assert first == second
    assert first is not None
    assert first.vah >= first.poc >= first.val
    assert first.tpo_count > 0


def test_profile_rejects_missing_bar_inside_session():
    bars = session_candles(date(2026, 11, 20))
    assert compute_session_profile(bars[:20] + bars[21:], BacktestConfig()) is None


def test_target_uses_nearest_prior_fixed_level_in_direction():
    from shashi_engine.amt_pa_backtest import SessionProfile
    history = [
        SessionProfile(date(2026, 11, 20), Decimal("61000"), Decimal("60500"), Decimal("60000"), 100, 48),
        SessionProfile(date(2026, 11, 19), Decimal("62000"), Decimal("61500"), Decimal("61000"), 100, 48),
    ]
    assert _target("long", Decimal("60600"), history) == (Decimal("61000"), "2026-11-20_VAH")
    assert _target("short", Decimal("60400"), history) == (Decimal("60000"), "2026-11-20_VAL")


def test_funding_schedule_uses_strictly_future_8h_boundaries():
    start = datetime(2026, 11, 20, 7, 30, tzinfo=UTC)
    end = datetime(2026, 11, 20, 17, 0, tzinfo=UTC)
    assert _expected_funding_times(start, end) == (
        datetime(2026, 11, 20, 8, 0, tzinfo=UTC),
        datetime(2026, 11, 20, 16, 0, tzinfo=UTC),
    )


def test_engine_rejects_wrong_product():
    bars = session_candles(date(2026, 11, 20)) * 2
    with pytest.raises(ValueError, match="product_id 27"):
        run_backtest(
            bars, instrument(28), FeeSchedule(Decimal(".0002"), Decimal(".0005"), Decimal(".18")),
            AccountingPolicy(timedelta(minutes=10)),
        )


def test_engine_rejects_gaps():
    bars = session_candles(date(2026, 11, 20))
    with pytest.raises(ValueError, match="missing 30m"):
        run_backtest(
            bars[:10] + bars[11:], instrument(),
            FeeSchedule(Decimal(".0002"), Decimal(".0005"), Decimal(".18")),
            AccountingPolicy(timedelta(minutes=10)),
        )


def test_engine_rejects_duplicates_and_out_of_order():
    bars = session_candles(date(2026, 11, 20))
    with pytest.raises(ValueError, match="unique and chronological"):
        run_backtest(
            bars[:10] + [bars[9]] + bars[10:], instrument(),
            FeeSchedule(Decimal(".0002"), Decimal(".0005"), Decimal(".18")),
            AccountingPolicy(timedelta(minutes=10)),
        )


def test_even_lot_requirement_for_partial():
    with pytest.raises(ValueError, match="even whole-number"):
        BacktestConfig(position_lots=1)
