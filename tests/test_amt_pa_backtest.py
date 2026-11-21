from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from shashi_engine.amt_pa_backtest import (
    BacktestConfig, Signal, _expected_funding_times, _target,
    compute_session_profile, run_backtest, session_date_for, _runner_breakeven_stop,
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
    with pytest.raises(ValueError, match="even whole number"):
        BacktestConfig(position_lots=1)


def _run_with_injected_signal(
    monkeypatch, entry_bar, following_bars, config=None,
    target_price=Decimal("60050"), stop_price=Decimal("59999"),
):
    import shashi_engine.amt_pa_backtest as engine

    bars = session_candles(date(2026, 11, 20))[:17]
    bars[14] = entry_bar
    for offset, bar in enumerate(following_bars, start=15):
        bars[offset] = bar
    signal_index = 13
    injected = Signal(
        signal_index, "A_FAILED_AUCTION", "long", Decimal("59000"),
        stop_price, target_price, "2026-11-19_POC", Decimal("100"),
    )

    def fake_signal_at(candles, index, profiles, market_instrument, config):
        return (injected, False) if index == signal_index else (None, False)

    monkeypatch.setattr(engine, "_signal_at", fake_signal_at)
    result = run_backtest(
        bars, instrument(),
        FeeSchedule(Decimal(".0002"), Decimal(".0005"), Decimal(".18")),
        AccountingPolicy(timedelta(minutes=10)),
        config=config or BacktestConfig(),
    )
    assert len(result.trades) == 1
    return result.trades[0], bars


def test_same_candle_stop_and_target_is_strictly_stop_first(monkeypatch):
    bars = session_candles(date(2026, 11, 20))
    entry_bar = Candle(
        "BTCUSD", "30m", bars[14].start_time, Decimal("60000"),
        Decimal("60200"), Decimal("59800"), Decimal("60020"), Decimal("1"),
    )
    trade, ordered = _run_with_injected_signal(monkeypatch, entry_bar, [])
    assert trade.partial_exit_time is None
    assert trade.partial_exit_price is None
    assert trade.final_exit_reason == "INITIAL_PROTECTIVE_STOP"
    assert trade.final_exit_price == Decimal("59999")
    assert trade.partial_lots == 0
    assert trade.runner_lots == 2


def test_signal_close_and_next_open_are_explicit_and_no_lookahead(monkeypatch):
    bars = session_candles(date(2026, 11, 20))
    entry_bar = Candle(
        "BTCUSD", "30m", bars[14].start_time, Decimal("60000"),
        Decimal("60060"), Decimal("59960"), Decimal("60010"), Decimal("1"),
    )
    trade, ordered = _run_with_injected_signal(monkeypatch, entry_bar, [])
    signal_bar = ordered[13]
    next_bar = ordered[14]
    assert trade.signal_candle_start_time == signal_bar.start_time
    assert trade.signal_time == signal_bar.end_time
    assert trade.entry_time == next_bar.start_time
    # A continuous market's signal close and next candle open share the same boundary instant.
    assert trade.signal_time == trade.entry_time
    assert trade.entry_price == next_bar.open


def test_runner_lots_reports_full_position_without_partial_and_one_after_partial(monkeypatch):
    bars = session_candles(date(2026, 11, 20))
    target_only_bar = Candle(
        "BTCUSD", "30m", bars[14].start_time, Decimal("60000"),
        Decimal("60100"), Decimal("60000"), Decimal("60080"), Decimal("1"),
    )
    stop_bar = Candle(
        "BTCUSD", "30m", bars[15].start_time, Decimal("60000"),
        Decimal("60050"), Decimal("59800"), Decimal("59950"), Decimal("1"),
    )
    trade, _ = _run_with_injected_signal(monkeypatch, target_only_bar, [stop_bar])
    assert trade.partial_lots == 1
    assert trade.runner_lots == 1
    assert trade.partial_exit_price == Decimal("60050")



def test_fee_adjusted_runner_breakeven_covers_entry_and_exit_fees_with_gst():
    fees = FeeSchedule(Decimal(".0002"), Decimal(".0005"), Decimal(".18"))
    long_stop = _runner_breakeven_stop(Decimal("60000"), "long", fees, Decimal(".50"))
    short_stop = _runner_breakeven_stop(Decimal("60000"), "short", fees, Decimal(".50"))
    effective = fees.taker_rate * (Decimal(1) + fees.gst_rate)
    assert long_stop >= Decimal("60000") * (Decimal(1) + effective) / (Decimal(1) - effective)
    assert short_stop <= Decimal("60000") * (Decimal(1) - effective) / (Decimal(1) + effective)


def test_runner_breakeven_activates_only_after_partial_confirmation_on_next_candle(monkeypatch):
    bars = session_candles(date(2026, 11, 20))
    # The target is touched in this candle, but its low is below the future
    # fee-adjusted stop while remaining above the original protective stop.
    target_bar = Candle(
        "BTCUSD", "30m", bars[14].start_time, Decimal("60000"),
        Decimal("60100"), Decimal("60000"), Decimal("60080"), Decimal("1"),
    )
    next_bar = Candle(
        "BTCUSD", "30m", bars[15].start_time, Decimal("60000"),
        Decimal("60070"), Decimal("60000"), Decimal("60040"), Decimal("1"),
    )
    trade, _ = _run_with_injected_signal(
        monkeypatch, target_bar, [next_bar], BacktestConfig(runner_breakeven=True)
    )
    fees = FeeSchedule(Decimal(".0002"), Decimal(".0005"), Decimal(".18"))
    expected_stop = _runner_breakeven_stop(
        Decimal("60000"), "long", fees, Decimal(".50")
    )
    assert trade.partial_exit_time == target_bar.end_time
    assert trade.partial_exit_price == Decimal("60050")
    assert trade.final_exit_time == next_bar.start_time
    assert trade.final_exit_reason == "RUNNER_FEE_ADJUSTED_BREAKEVEN"
    assert trade.final_exit_price == expected_stop
    assert trade.final_exit_price > trade.entry_price



def test_runner_breakeven_rr_gate_activates_at_exactly_one_r(monkeypatch):
    bars = session_candles(date(2026, 11, 20))
    target_bar = Candle(
        "BTCUSD", "30m", bars[14].start_time, Decimal("60000"),
        Decimal("60100"), Decimal("60000"), Decimal("60080"), Decimal("1"),
    )
    next_bar = Candle(
        "BTCUSD", "30m", bars[15].start_time, Decimal("60000"),
        Decimal("60070"), Decimal("60000"), Decimal("60040"), Decimal("1"),
    )
    trade, _ = _run_with_injected_signal(
        monkeypatch, target_bar, [next_bar],
        BacktestConfig(runner_breakeven=True, runner_breakeven_min_rr=Decimal("1.0")),
        target_price=Decimal("60001"), stop_price=Decimal("59999"),
    )
    assert abs(Decimal("60001") - Decimal("60000")) / abs(Decimal("60000") - Decimal("59999")) == Decimal("1")
    assert trade.final_exit_reason == "RUNNER_FEE_ADJUSTED_BREAKEVEN"


def test_runner_breakeven_rr_gate_does_not_activate_below_one_r(monkeypatch):
    bars = session_candles(date(2026, 11, 20))
    target_bar = Candle(
        "BTCUSD", "30m", bars[14].start_time, Decimal("60000"),
        Decimal("60100"), Decimal("60000"), Decimal("60080"), Decimal("1"),
    )
    next_bar = Candle(
        "BTCUSD", "30m", bars[15].start_time, Decimal("60000"),
        Decimal("60070"), Decimal("59950"), Decimal("59950"), Decimal("1"),
    )
    trade, _ = _run_with_injected_signal(
        monkeypatch, target_bar, [next_bar],
        BacktestConfig(runner_breakeven=True, runner_breakeven_min_rr=Decimal("1.0")),
        target_price=Decimal("60000.99"), stop_price=Decimal("59999"),
    )
    assert abs(Decimal("60000.99") - Decimal("60000")) / abs(Decimal("60000") - Decimal("59999")) < Decimal("1")
    assert trade.final_exit_reason == "INITIAL_PROTECTIVE_STOP"
    assert trade.final_exit_price == Decimal("59999")


def test_min_first_target_rr_defaults_off_and_preserves_sub_one_r_entries(monkeypatch):
    assert BacktestConfig().min_first_target_rr is None
    bars = session_candles(date(2026, 11, 20))
    entry_bar = Candle(
        "BTCUSD", "30m", bars[14].start_time, Decimal("60000"),
        Decimal("60100"), Decimal("60000"), Decimal("60080"), Decimal("1"),
    )
    trade, _ = _run_with_injected_signal(
        monkeypatch, entry_bar, [],
        target_price=Decimal("60000.5"), stop_price=Decimal("59999"),
    )
    assert trade.first_target == Decimal("60000.5")


def test_min_first_target_rr_skips_low_rr_entry_and_records_setup(monkeypatch):
    import shashi_engine.amt_pa_backtest as engine

    bars = session_candles(date(2026, 11, 20))[:17]
    injected = Signal(
        13, "A_FAILED_AUCTION", "long", Decimal("59000"),
        Decimal("59999"), Decimal("60000.5"), "2026-11-19_POC", Decimal("100"),
    )

    def fake_signal_at(candles, index, profiles, market_instrument, config):
        return (injected, False) if index == 13 else (None, False)

    monkeypatch.setattr(engine, "_signal_at", fake_signal_at)
    result = run_backtest(
        bars, instrument(),
        FeeSchedule(Decimal(".0002"), Decimal(".0005"), Decimal(".18")),
        AccountingPolicy(timedelta(minutes=10)),
        config=BacktestConfig(min_first_target_rr=Decimal("1.0")),
    )
    assert result.trades == ()
    assert len(result.skipped_low_first_target_rr) == 1
    skipped = result.skipped_low_first_target_rr[0]
    assert skipped.setup == "A_FAILED_AUCTION"
    assert skipped.direction == "long"
    assert skipped.signal_candle_start_time == bars[13].start_time
    assert skipped.signal_time == bars[13].end_time
    assert skipped.entry_time == bars[14].start_time
    assert skipped.entry_price == Decimal("60000")
    assert skipped.stop_price == Decimal("59999")
    assert skipped.first_target == Decimal("60000.5")
    assert skipped.target_source == "2026-11-19_POC"
    assert skipped.first_target_rr == Decimal("0.5")
    assert skipped.minimum_first_target_rr == Decimal("1.0")


def test_min_first_target_rr_accepts_exact_threshold(monkeypatch):
    bars = session_candles(date(2026, 11, 20))
    entry_bar = Candle(
        "BTCUSD", "30m", bars[14].start_time, Decimal("60000"),
        Decimal("60100"), Decimal("60000"), Decimal("60080"), Decimal("1"),
    )
    trade, _ = _run_with_injected_signal(
        monkeypatch, entry_bar, [],
        config=BacktestConfig(min_first_target_rr=Decimal("1.0")),
        target_price=Decimal("60001"), stop_price=Decimal("59999"),
    )
    assert trade.first_target == Decimal("60001")


def test_min_first_target_rr_rejects_nonpositive_threshold():
    with pytest.raises(ValueError, match="min_first_target_rr"):
        BacktestConfig(min_first_target_rr=Decimal("0"))


def test_runner_breakeven_without_rr_gate_remains_always_on_after_partial(monkeypatch):
    bars = session_candles(date(2026, 11, 20))
    target_bar = Candle(
        "BTCUSD", "30m", bars[14].start_time, Decimal("60000"),
        Decimal("60100"), Decimal("60000"), Decimal("60080"), Decimal("1"),
    )
    next_bar = Candle(
        "BTCUSD", "30m", bars[15].start_time, Decimal("60000"),
        Decimal("60070"), Decimal("60000"), Decimal("60040"), Decimal("1"),
    )
    trade, _ = _run_with_injected_signal(
        monkeypatch, target_bar, [next_bar],
        BacktestConfig(runner_breakeven=True, runner_breakeven_min_rr=None),
        target_price=Decimal("60000.99"), stop_price=Decimal("59999"),
    )
    assert trade.final_exit_reason == "RUNNER_FEE_ADJUSTED_BREAKEVEN"
