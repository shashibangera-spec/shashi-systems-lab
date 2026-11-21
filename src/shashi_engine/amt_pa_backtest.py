"""Offline AMT + Price Action backtester for Delta India BTCUSD perpetual 30m data.

The engine is deterministic and network-free. Candle retrieval/reporting are isolated in
the CLI; this module consumes validated Candle models only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Literal, Sequence

from .accounting import AccountingPolicy, AccountingScenario, FeeSchedule, FundingEvent, calculate_accounting
from .models import Candle, Instrument

Direction = Literal["long", "short"]
Setup = Literal["A_FAILED_AUCTION", "B_ACCEPTANCE_RETEST"]
UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))
BAR = timedelta(minutes=30)
FUNDING_INTERVAL = 28_800


@dataclass(frozen=True, slots=True)
class SessionProfile:
    session_date: date
    vah: Decimal
    poc: Decimal
    val: Decimal
    tpo_count: int
    candle_count: int


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    row_size: Decimal = Decimal("50")
    value_area_fraction: Decimal = Decimal("0.70")
    prior_sessions_for_targets: int = 5
    atr_period: int = 14
    acceptance_buffer_atr: Decimal = Decimal("0.10")
    rejection_wick_body_ratio: Decimal = Decimal("1.5")
    rejection_close_fraction: Decimal = Decimal("0.60")
    position_lots: int = 2
    stop_pad_ticks: int = 1

    def __post_init__(self) -> None:
        if not self.row_size.is_finite() or self.row_size <= 0:
            raise ValueError("row_size must be a positive finite Decimal")
        if not Decimal(0) < self.value_area_fraction <= Decimal(1):
            raise ValueError("value_area_fraction must be in (0, 1]")
        if self.prior_sessions_for_targets < 1 or self.atr_period < 1:
            raise ValueError("session lookback and ATR period must be positive")
        if self.acceptance_buffer_atr < 0 or self.rejection_wick_body_ratio < 0:
            raise ValueError("ATR buffer and wick ratio must not be negative")
        if not Decimal("0.5") <= self.rejection_close_fraction <= Decimal(1):
            raise ValueError("rejection_close_fraction must be between 0.5 and 1")
        if self.position_lots < 2 or self.position_lots % 2:
            raise ValueError("position_lots must be an even whole number >= 2 for a 50% partial")
        if self.stop_pad_ticks < 1:
            raise ValueError("stop_pad_ticks must be at least one tick")


@dataclass(frozen=True, slots=True)
class Signal:
    index: int
    setup: Setup
    direction: Direction
    thesis_level: Decimal
    stop_price: Decimal
    target_price: Decimal
    target_source: str
    atr: Decimal


@dataclass(frozen=True, slots=True)
class TradeResult:
    trade_id: int
    setup: Setup
    direction: Direction
    signal_candle_start_time: datetime
    signal_time: datetime
    entry_time: datetime
    entry_price: Decimal
    thesis_level: Decimal
    stop_price: Decimal
    first_target: Decimal
    target_source: str
    partial_exit_time: datetime | None
    partial_exit_price: Decimal | None
    final_exit_time: datetime
    final_exit_price: Decimal
    final_exit_reason: str
    original_lots: int
    partial_lots: int
    runner_lots: int
    gross_pnl_usd: Decimal
    fees_and_gst_usd: Decimal
    funding_cashflow_usd: Decimal
    net_ex_funding_usd: Decimal
    net_including_funding_usd: Decimal | None
    funding_complete: bool
    missing_funding_events: tuple[datetime, ...]


@dataclass(frozen=True, slots=True)
class BacktestResult:
    profiles: tuple[SessionProfile, ...]
    trades: tuple[TradeResult, ...]
    candles_used: int
    skipped_no_reference: int
    skipped_invalid_stop: int


def session_date_for(candle: Candle) -> date:
    """Map UTC candle start to the 05:30–05:30 IST AMT session."""
    local = candle.start_time.astimezone(IST)
    result = local.date()
    if local.time().replace(tzinfo=None) < time(5, 30):
        result -= timedelta(days=1)
    return result


def _row_index(price: Decimal, row_size: Decimal) -> int:
    return int((price / row_size).to_integral_value(rounding="ROUND_FLOOR"))


def compute_session_profile(candles: Sequence[Candle], config: BacktestConfig) -> SessionProfile | None:
    """Compute a 48-bar TPO profile; incomplete or gapped sessions fail closed."""
    if len(candles) != 48:
        return None
    ordered = sorted(candles, key=lambda item: item.start_time)
    key = session_date_for(ordered[0])
    if any(session_date_for(item) != key for item in ordered):
        return None
    if any(b.start_time - a.start_time != BAR for a, b in zip(ordered, ordered[1:])):
        return None
    expected = datetime.combine(key, time(5, 30), tzinfo=IST).astimezone(UTC)
    if ordered[0].start_time != expected:
        return None
    counts: dict[int, int] = {}
    for candle in ordered:
        for row in range(_row_index(candle.low, config.row_size), _row_index(candle.high, config.row_size) + 1):
            counts[row] = counts.get(row, 0) + 1
    if not counts:
        return None
    # Deterministic tie-breaks: POC chooses the higher row; VA expansion ties go upward.
    poc_row = max(counts, key=lambda row: (counts[row], row))
    total = sum(counts.values())
    accumulated = counts[poc_row]
    lower = upper = poc_row
    target = Decimal(total) * config.value_area_fraction
    while Decimal(accumulated) < target:
        lo = counts.get(lower - 1, -1)
        hi = counts.get(upper + 1, -1)
        if hi >= lo and hi >= 0:
            upper += 1
            accumulated += counts[upper]
        elif lo >= 0:
            lower -= 1
            accumulated += counts[lower]
        else:
            break
    half = config.row_size / Decimal(2)
    return SessionProfile(key, Decimal(upper) * config.row_size + half,
                          Decimal(poc_row) * config.row_size + half,
                          Decimal(lower) * config.row_size + half, total, 48)


def _true_range(current: Candle, previous: Candle | None) -> Decimal:
    if previous is None:
        return current.high - current.low
    return max(current.high - current.low, abs(current.high - previous.close),
               abs(current.low - previous.close))


def _atr(candles: Sequence[Candle], index: int, period: int) -> Decimal | None:
    if index + 1 < period:
        return None
    ranges = [_true_range(candles[j], candles[j - 1] if j > 0 else None)
              for j in range(index - period + 1, index + 1)]
    return sum(ranges, Decimal(0)) / Decimal(period)


def _profile_history(profiles: dict[date, SessionProfile], current: date, count: int) -> list[SessionProfile]:
    return sorted((p for d, p in profiles.items() if d < current),
                  key=lambda p: p.session_date, reverse=True)[:count]


def _target(direction: Direction, entry: Decimal, history: Sequence[SessionProfile]) -> tuple[Decimal, str] | None:
    candidates: list[tuple[Decimal, str]] = []
    for profile in history:
        for label, value in (("VAH", profile.vah), ("POC", profile.poc), ("VAL", profile.val)):
            if (direction == "long" and value > entry) or (direction == "short" and value < entry):
                candidates.append((value, f"{profile.session_date.isoformat()}_{label}"))
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[0]) if direction == "long" else max(candidates, key=lambda item: item[0])


def _rejection_ok(candle: Candle, direction: Direction, config: BacktestConfig, tick: Decimal) -> bool:
    span = candle.high - candle.low
    if span <= 0:
        return False
    body = abs(candle.close - candle.open)
    if direction == "long":
        wick = min(candle.open, candle.close) - candle.low
        close_location = (candle.close - candle.low) / span
    else:
        wick = candle.high - max(candle.open, candle.close)
        close_location = (candle.high - candle.close) / span
    return wick >= config.rejection_wick_body_ratio * max(body, tick) and close_location >= config.rejection_close_fraction


def _signal_at(candles: Sequence[Candle], index: int, profiles: dict[date, SessionProfile],
               instrument: Instrument, config: BacktestConfig) -> tuple[Signal | None, bool]:
    candle = candles[index]
    atr = _atr(candles, index, config.atr_period)
    if atr is None:
        return None, False
    session = session_date_for(candle)
    history = _profile_history(profiles, session, config.prior_sessions_for_targets)
    prior = next((p for p in history if p.session_date == session - timedelta(days=1)), None)
    if prior is None:
        return None, False
    buffer = atr * config.acceptance_buffer_atr
    setup: Setup | None = None
    direction: Direction | None = None
    level: Decimal | None = None
    previous_close = candles[index - 1].close

    # Setup A: failed auction/rejection at the previous completed session boundary.
    if (candle.low < prior.val - buffer and candle.close > prior.val + buffer
        and previous_close >= prior.val - buffer and _rejection_ok(candle, "long", config, instrument.tick_size)):
        setup, direction, level = "A_FAILED_AUCTION", "long", prior.val
    elif (candle.high > prior.vah + buffer and candle.close < prior.vah - buffer
          and previous_close <= prior.vah + buffer and _rejection_ok(candle, "short", config, instrument.tick_size)):
        setup, direction, level = "A_FAILED_AUCTION", "short", prior.vah

    # Setup B: two accepted closes, then a retest candle with directional displacement.
    if setup is None and index >= 2:
        two_prior = candles[index - 2:index]
        span = max(candle.high - candle.low, instrument.tick_size)
        if (all(bar.close > prior.vah + buffer for bar in two_prior)
            and candle.low <= prior.vah + buffer and candle.close > prior.vah + buffer
            and candle.close > candles[index - 1].high
            and (candle.close - candle.low) / span >= config.rejection_close_fraction):
            setup, direction, level = "B_ACCEPTANCE_RETEST", "long", prior.vah
        elif (all(bar.close < prior.val - buffer for bar in two_prior)
              and candle.high >= prior.val - buffer and candle.close < prior.val - buffer
              and candle.close < candles[index - 1].low
              and (candle.high - candle.close) / span >= config.rejection_close_fraction):
            setup, direction, level = "B_ACCEPTANCE_RETEST", "short", prior.val

    if setup is None or direction is None or level is None or index + 1 >= len(candles):
        return None, False
    entry = candles[index + 1].open
    target = _target(direction, entry, history)
    if target is None:
        return None, True
    pad = instrument.tick_size * config.stop_pad_ticks
    stop = candle.low - pad if direction == "long" else candle.high + pad
    if (direction == "long" and stop >= entry) or (direction == "short" and stop <= entry):
        return None, False
    return Signal(index, setup, direction, level, stop, target[0], target[1], atr), False


def _expected_funding_times(start: datetime, end: datetime) -> tuple[datetime, ...]:
    if end <= start:
        return ()
    epoch = int(start.timestamp())
    next_epoch = (epoch // FUNDING_INTERVAL + 1) * FUNDING_INTERVAL
    result = []
    while next_epoch <= int(end.timestamp()):
        result.append(datetime.fromtimestamp(next_epoch, UTC))
        next_epoch += FUNDING_INTERVAL
    return tuple(result)


def _funding_for(source: Sequence[FundingEvent], start: datetime, end: datetime,
                 side: Direction, lots: int) -> tuple[FundingEvent, ...]:
    return tuple(FundingEvent(event.rate, side, lots, event.mark_price, event.event_at, FUNDING_INTERVAL)
                 for event in source if start < event.event_at <= end)


def _close_trade(trade_id: int, signal: Signal, signal_candle_start_time: datetime,
                 signal_time: datetime, entry_time: datetime, entry_price: Decimal,
                 partial_time: datetime | None, partial_price: Decimal | None,
                 final_time: datetime, final_price: Decimal, reason: str,
                 config: BacktestConfig, instrument: Instrument, fee_schedule: FeeSchedule,
                 policy: AccountingPolicy, funding: Sequence[FundingEvent],
                 metadata_source: str) -> TradeResult:
    tranche = config.position_lots // 2
    first_exit_time = partial_time or final_time
    first_exit_price = partial_price if partial_price is not None else final_price
    gross = fees = funding_cash = Decimal(0)
    missing: set[datetime] = set()
    all_complete = True
    for idx, (exit_time, exit_price) in enumerate(((first_exit_time, first_exit_price),
                                                   (final_time, final_price))):
        events = _funding_for(funding, entry_time, exit_time, signal.direction, tranche)
        expected = set(_expected_funding_times(entry_time, exit_time))
        observed = {event.event_at for event in events}
        missing.update(expected - observed)
        breakdown = calculate_accounting(AccountingScenario(
            instrument=instrument, scenario_id=f"phase1i-{trade_id}-tranche-{idx + 1}",
            contract_metadata_source=metadata_source, lots=tranche,
            position_side=signal.direction, entry_price=entry_price, entry_liquidity="taker",
            entry_at=entry_time, fee_schedule=fee_schedule, policy=policy, as_of=exit_time,
            exit_price=exit_price, exit_liquidity="taker", exit_at=exit_time,
            funding_events=events,
        ))
        gross += breakdown.gross_scenario_pnl_usd or Decimal(0)
        fees += breakdown.entry_fee_usd + breakdown.entry_gst_usd + breakdown.exit_fee_usd + breakdown.exit_gst_usd
        funding_cash += breakdown.funding_cashflow_usd
        all_complete = all_complete and breakdown.net_scenario_result_usd is not None
    complete = not missing and all_complete
    return TradeResult(
        trade_id, signal.setup, signal.direction, signal_candle_start_time, signal_time, entry_time, entry_price,
        signal.thesis_level, signal.stop_price, signal.target_price, signal.target_source,
        partial_time, partial_price, final_time, final_price, reason,
        config.position_lots, tranche if partial_time else 0,
        config.position_lots - (tranche if partial_time else 0),
        gross, fees, funding_cash, gross - fees,
        gross - fees + funding_cash if complete else None,
        complete, tuple(sorted(missing)),
    )


def run_backtest(candles: Sequence[Candle], instrument: Instrument, fee_schedule: FeeSchedule,
                 accounting_policy: AccountingPolicy, funding_events: Sequence[FundingEvent] = (),
                 config: BacktestConfig = BacktestConfig(),
                 metadata_source: str = "Delta India public product verifier") -> BacktestResult:
    """Run a chronological, completed-candle backtest; no network or file I/O."""
    if instrument.symbol != "BTCUSD" or instrument.product_id != 27:
        raise ValueError("Phase 1I requires Delta India BTCUSD perpetual product_id 27")
    if instrument.contract_type != "perpetual_futures" or instrument.quote_asset != "USD":
        raise ValueError("instrument must be a USD-quoted BTCUSD perpetual")
    if instrument.funding_interval_seconds != FUNDING_INTERVAL:
        raise ValueError("instrument funding interval must be 8 hours")
    if len(candles) < config.atr_period + 3:
        raise ValueError("insufficient 30m candles for ATR and signal confirmation")
    ordered = list(candles)
    if any(c.symbol != "BTCUSD" or c.resolution != "30m" for c in ordered):
        raise ValueError("all candles must be BTCUSD 30m")
    if any(b.start_time <= a.start_time for a, b in zip(ordered, ordered[1:])):
        raise ValueError("candles must be unique and chronological")
    if any(b.start_time - a.start_time != BAR for a, b in zip(ordered, ordered[1:])):
        raise ValueError("input contains missing 30m candles; audit the source before backtesting")

    grouped: dict[date, list[Candle]] = {}
    for candle in ordered:
        grouped.setdefault(session_date_for(candle), []).append(candle)
    profiles = {key: profile for key, rows in grouped.items()
                if (profile := compute_session_profile(rows, config)) is not None}

    active: dict[str, object] | None = None
    trades: list[TradeResult] = []
    skipped_no_reference = skipped_invalid_stop = 0
    next_trade_id = 1

    for i, candle in enumerate(ordered):
        if active is not None:
            signal = active["signal"]
            assert isinstance(signal, Signal)
            if active["pending_exit"]:
                trades.append(_close_trade(
                    int(active["trade_id"]), signal, ordered[signal.index].start_time,
                    ordered[signal.index].end_time, active["entry_time"], active["entry_price"], active["partial_time"],
                    active["partial_price"], candle.start_time, candle.open,
                    str(active["pending_exit"]), config, instrument, fee_schedule,
                    accounting_policy, funding_events, metadata_source,
                ))
                active = None
                continue

            stop_hit = candle.low <= active["stop"] if signal.direction == "long" else candle.high >= active["stop"]
            if stop_hit:
                trades.append(_close_trade(
                    int(active["trade_id"]), signal, ordered[signal.index].start_time,
                    ordered[signal.index].end_time, active["entry_time"], active["entry_price"], active["partial_time"],
                    active["partial_price"], candle.start_time, active["stop"],
                    "INITIAL_PROTECTIVE_STOP", config, instrument, fee_schedule,
                    accounting_policy, funding_events, metadata_source,
                ))
                active = None
                continue

            if active["partial_time"] is None:
                target_hit = candle.high >= active["target"] if signal.direction == "long" else candle.low <= active["target"]
                if target_hit:
                    # Intrabar touch is known only from this completed candle; time is its close.
                    active["partial_time"] = candle.end_time
                    active["partial_price"] = active["target"]

            # Require two completed closes after entry across the original thesis level.
            if i > int(active["entry_index"]):
                atr_now = _atr(ordered, i, config.atr_period) or Decimal(0)
                buffer = atr_now * config.acceptance_buffer_atr
                prev_close, close = ordered[i - 1].close, candle.close
                invalid = (
                    prev_close < signal.thesis_level - buffer and close < signal.thesis_level - buffer
                    if signal.direction == "long"
                    else prev_close > signal.thesis_level + buffer and close > signal.thesis_level + buffer
                )
                if invalid:
                    active["pending_exit"] = "STRUCTURAL_INVALIDATION_OPPOSING_ACCEPTANCE"
                    continue

        if active is None and i < len(ordered) - 1:
            signal, no_reference = _signal_at(ordered, i, profiles, instrument, config)
            skipped_no_reference += int(no_reference)
            if signal is None:
                continue
            entry_candle = ordered[i + 1]
            entry_price = entry_candle.open
            if (signal.direction == "long" and entry_price <= signal.stop_price) or (
                signal.direction == "short" and entry_price >= signal.stop_price
            ):
                skipped_invalid_stop += 1
                continue
            active = {
                "trade_id": next_trade_id, "signal": signal, "entry_index": i + 1,
                "entry_time": entry_candle.start_time, "entry_price": entry_price,
                "stop": signal.stop_price, "target": signal.target_price,
                "partial_time": None, "partial_price": None, "pending_exit": None,
            }
            next_trade_id += 1

    if active is not None:
        signal = active["signal"]
        assert isinstance(signal, Signal)
        last = ordered[-1]
        trades.append(_close_trade(
            int(active["trade_id"]), signal, ordered[signal.index].start_time,
            ordered[signal.index].end_time, active["entry_time"], active["entry_price"], active["partial_time"],
            active["partial_price"], last.end_time, last.close, "END_OF_DATA",
            config, instrument, fee_schedule, accounting_policy, funding_events, metadata_source,
        ))
    return BacktestResult(tuple(profiles[key] for key in sorted(profiles)), tuple(trades),
                          len(ordered), skipped_no_reference, skipped_invalid_stop)
