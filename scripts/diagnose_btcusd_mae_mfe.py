"""Diagnostic-only MAE/MFE study for a frozen Phase 1I BTCUSD backtest.

Replays the supplied backtest report's exact window and frozen configuration,
verifies all trade identities against that report, then measures OHLC excursions.
This script does not alter strategy rules, source data, or the original report.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shashi_engine.amt_pa_backtest import BacktestConfig, _atr, run_backtest
from shashi_engine.accounting import AccountingPolicy, FeeSchedule
from shashi_engine.contract_verification import fetch_btcusd_product, parse_product
from shashi_engine.market_data import MarketDataError, fetch_candles
from shashi_engine.models import Candle, Instrument

UTC = timezone.utc
BAR_SECONDS = 1800
CHUNK_BARS = 48
EXPECTED_START = datetime(2026, 8, 23, 0, 0, tzinfo=UTC)
EXPECTED_END = datetime(2026, 11, 21, 0, 0, tzinfo=UTC)
ATR_THRESHOLDS = (Decimal("0.25"), Decimal("0.50"))


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"Timestamp must include UTC offset: {value}")
    return parsed.astimezone(UTC)


def fetch_exact_window(start: datetime, end: datetime) -> list[Candle]:
    if start != EXPECTED_START or end != EXPECTED_END:
        raise ValueError(
            "This approved diagnostic is locked to 2026-08-23T00:00:00Z "
            "through 2026-11-21T00:00:00Z"
        )
    start_epoch, end_epoch = int(start.timestamp()), int(end.timestamp())
    candles: list[Candle] = []
    cursor = start_epoch
    chunk_seconds = CHUNK_BARS * BAR_SECONDS
    while cursor < end_epoch:
        stop = min(cursor + chunk_seconds, end_epoch)
        rows = fetch_candles(cursor, stop, resolution="30m")
        candles.extend(
            candle for candle in rows
            if cursor <= int(candle.start_time.timestamp()) < stop
        )
        cursor = stop
    candles.sort(key=lambda item: item.start_time)
    expected = [start_epoch + i * BAR_SECONDS for i in range(90 * 48)]
    actual = [int(item.start_time.timestamp()) for item in candles]
    if len(actual) != len(set(actual)):
        raise MarketDataError("Duplicate timestamps in diagnostic candle fetch")
    if actual != expected:
        missing = len(set(expected) - set(actual))
        extra = len(set(actual) - set(expected))
        raise MarketDataError(
            f"Exact-window coverage failed: expected 4320 candles, received "
            f"{len(actual)}, missing={missing}, out_of_range={extra}"
        )
    return candles


def instrument_from_public_metadata() -> Instrument:
    verified = parse_product(fetch_btcusd_product())
    instrument = Instrument(
        product_id=verified.product_id, symbol=verified.symbol,
        contract_type=verified.contract_type, state=verified.state,
        trading_status=verified.trading_status, contract_value=verified.contract_value,
        contract_value_asset=verified.contract_unit_currency, tick_size=verified.tick_size,
        quote_asset=verified.quoting_asset, api_settlement_asset=verified.api_settling_asset,
        funding_interval_seconds=verified.funding_interval_seconds,
        minimum_order_lots=verified.minimum_order_lots,
    )
    if instrument.product_id != 27:
        raise ValueError("Verified instrument is not Delta India BTCUSD product_id 27")
    return instrument


def verify_report_matches(replay_trades: list[Any], reference: dict[str, Any]) -> None:
    expected_trades = reference.get("trades")
    if not isinstance(expected_trades, list) or len(expected_trades) != 28:
        raise ValueError("Reference JSON must contain the exact approved 28-trade report")
    if len(replay_trades) != len(expected_trades):
        raise ValueError(
            f"Frozen-rule replay produced {len(replay_trades)} trades; reference has "
            f"{len(expected_trades)}. Diagnostic stopped; no comparison was made."
        )
    fields = (
        "trade_id", "setup", "direction", "signal_candle_start_time", "entry_time",
        "entry_price", "stop_price", "first_target", "target_source",
        "final_exit_time", "final_exit_reason",
    )
    for number, (actual, expected) in enumerate(zip(replay_trades, expected_trades), 1):
        for field in fields:
            actual_value = getattr(actual, field)
            if isinstance(actual_value, datetime):
                actual_value = actual_value.isoformat()
            elif isinstance(actual_value, Decimal):
                actual_value = str(actual_value)
            expected_value = expected[field]
            if actual_value != expected_value:
                raise ValueError(
                    f"Trade {number} mismatch in {field}: replay={actual_value!r}, "
                    f"reference={expected_value!r}. Diagnostic stopped."
                )


def favorable_excursion(direction: str, entry: Decimal, candle: Candle) -> Decimal:
    return candle.high - entry if direction == "long" else entry - candle.low


def adverse_excursion(direction: str, entry: Decimal, candle: Candle) -> Decimal:
    return entry - candle.low if direction == "long" else candle.high - entry


def stop_breach(direction: str, stop: Decimal, candle: Candle) -> Decimal:
    return max(Decimal(0), stop - candle.low) if direction == "long" else max(
        Decimal(0), candle.high - stop
    )


def measure_trade(trade: Any, candles: list[Candle], index_by_time: dict[datetime, int]) -> dict[str, Any]:
    entry_idx = index_by_time[trade.entry_time]
    if trade.final_exit_reason == "END_OF_DATA":
        exit_idx = len(candles) - 1
    else:
        exit_idx = index_by_time[trade.final_exit_time]
    if exit_idx < entry_idx:
        raise ValueError(f"Trade {trade.trade_id}: exit precedes entry")

    in_trade = candles[entry_idx:exit_idx + 1]
    mae = max(adverse_excursion(trade.direction, trade.entry_price, bar) for bar in in_trade)
    mfe = max(favorable_excursion(trade.direction, trade.entry_price, bar) for bar in in_trade)
    signal_idx = index_by_time[trade.signal_candle_start_time]
    atr = _atr(candles, signal_idx, 14)
    if atr is None or atr <= 0:
        raise ValueError(f"Trade {trade.trade_id}: signal ATR unavailable")
    stop_bar = candles[exit_idx] if trade.final_exit_reason == "INITIAL_PROTECTIVE_STOP" else None
    breach = stop_breach(trade.direction, trade.stop_price, stop_bar) if stop_bar else None
    risk = abs(trade.entry_price - trade.stop_price)
    target_distance = abs(trade.first_target - trade.entry_price)

    row: dict[str, Any] = {
        "trade_id": trade.trade_id,
        "setup": trade.setup,
        "direction": trade.direction,
        "entry_time_utc": trade.entry_time.isoformat(),
        "exit_time_utc": trade.final_exit_time.isoformat(),
        "exit_reason": trade.final_exit_reason,
        "entry_price": str(trade.entry_price),
        "initial_stop": str(trade.stop_price),
        "first_target": str(trade.first_target),
        "signal_atr_14": str(atr),
        "initial_risk_points": str(risk),
        "first_target_distance_points": str(target_distance),
        "in_trade_mae_points": str(mae),
        "in_trade_mae_atr": str(mae / atr),
        "in_trade_mae_R": str(mae / risk) if risk else None,
        "in_trade_mfe_points": str(mfe),
        "in_trade_mfe_atr": str(mfe / atr),
        "in_trade_mfe_first_target_fraction": str(mfe / target_distance) if target_distance else None,
        "stop_candle_worst_breach_beyond_stop_points": str(breach) if breach is not None else None,
        "stop_candle_breach_atr": str(breach / atr) if breach is not None else None,
    }

    if stop_bar is not None:
        post_bars = candles[exit_idx + 1:]
        post_mfe = max(
            (favorable_excursion(trade.direction, trade.entry_price, bar) for bar in post_bars),
            default=Decimal(0),
        )
        target_idx = next((
            i for i, bar in enumerate(post_bars)
            if (bar.high >= trade.first_target if trade.direction == "long"
                else bar.low <= trade.first_target)
        ), None)
        row.update({
            "post_stop_candle_count_observed": len(post_bars),
            "post_stop_mfe_points_from_original_entry": str(post_mfe),
            "post_stop_mfe_atr": str(post_mfe / atr),
            "post_stop_mfe_first_target_fraction": (
                str(post_mfe / target_distance) if target_distance else None
            ),
            "original_first_target_reached_after_stop": target_idx is not None,
            "candles_after_stop_until_first_target": target_idx + 1 if target_idx is not None else None,
            "post_stop_observation_end_utc": (
                post_bars[target_idx].end_time.isoformat()
                if target_idx is not None else (post_bars[-1].end_time.isoformat() if post_bars else None)
            ),
            "post_stop_target_status": (
                "TARGET_REACHED_AFTER_STOP" if target_idx is not None
                else "TARGET_NOT_REACHED_WITHIN_REMAINDER_OF_WINDOW"
            ),
            "stop_breach_bucket": (
                "WITHIN_0_25_ATR" if breach <= ATR_THRESHOLDS[0] * atr
                else "WITHIN_0_50_ATR" if breach <= ATR_THRESHOLDS[1] * atr
                else "OVER_0_50_ATR"
            ),
        })
    else:
        row.update({
            "post_stop_candle_count_observed": None,
            "post_stop_mfe_points_from_original_entry": None,
            "post_stop_mfe_atr": None,
            "post_stop_mfe_first_target_fraction": None,
            "original_first_target_reached_after_stop": None,
            "candles_after_stop_until_first_target": None,
            "post_stop_observation_end_utc": None,
            "post_stop_target_status": "NOT_APPLICABLE_NOT_STOPPED_AT_INITIAL_STOP",
            "stop_breach_bucket": None,
        })
    return row


def build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    stopped = [r for r in rows if r["exit_reason"] == "INITIAL_PROTECTIVE_STOP"]
    summary: dict[str, Any] = {
        "trade_count": len(rows),
        "initial_protective_stop_count": len(stopped),
        "other_exit_count": len(rows) - len(stopped),
        "stopped_trades_reaching_original_first_target_after_stop": sum(
            r["original_first_target_reached_after_stop"] is True for r in stopped
        ),
        "stopped_trades_not_reaching_original_first_target_in_remaining_window": sum(
            r["original_first_target_reached_after_stop"] is False for r in stopped
        ),
        "stop_breach_buckets": {},
        "small_breach_then_target_counts": {},
        "interpretation_note": (
            "A target reached after stop-out is evidence of post-stop recovery, not proof "
            "that a wider stop would have survived or that the original trade should be "
            "re-entered. OHLC candles do not reveal intrabar path. No target after stop "
            "within this finite window is not proof of permanent directional failure."
        ),
    }
    for threshold in ATR_THRESHOLDS:
        label = f"at_most_{threshold}_ATR"
        qualifying = [r for r in stopped if Decimal(r["stop_candle_breach_atr"]) <= threshold]
        summary["small_breach_then_target_counts"][label] = {
            "stopouts_with_breach_at_or_below_threshold": len(qualifying),
            "then_reached_original_first_target": sum(
                r["original_first_target_reached_after_stop"] is True for r in qualifying
            ),
            "did_not_reach_target_within_window": sum(
                r["original_first_target_reached_after_stop"] is False for r in qualifying
            ),
        }
    for label in ("WITHIN_0_25_ATR", "WITHIN_0_50_ATR", "OVER_0_50_ATR"):
        summary["stop_breach_buckets"][label] = sum(
            r["stop_breach_bucket"] == label for r in stopped
        )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-report", required=True, type=Path,
                        help="the exact 90-day Phase 1I JSON report used as the frozen reference")
    parser.add_argument("--output", type=Path,
                        default=Path("data/reports/phase1i_90d_mae_mfe_diagnostic.json"))
    args = parser.parse_args()
    try:
        reference = json.loads(args.reference_report.read_text(encoding="utf-8"))
        window = reference.get("historical_fetch_window", {})
        start = parse_utc(window.get("start_utc", ""))
        end = parse_utc(window.get("end_exclusive_utc", ""))
        if start != EXPECTED_START or end != EXPECTED_END:
            raise ValueError("Reference report does not match the approved exact 90-day window")
        if reference.get("candles_used") != 4320 or reference.get("complete_profiles") != 90:
            raise ValueError("Reference report is not the validated 4,320-candle / 90-profile run")

        print("Fetching exact 4,320-candle public Delta window...")
        candles = fetch_exact_window(start, end)
        instrument = instrument_from_public_metadata()
        fees = FeeSchedule(Decimal("0.0002"), Decimal("0.0005"), Decimal("0.18"))
        replay = run_backtest(
            candles, instrument, fees, AccountingPolicy(max_fx_age=timedelta(minutes=10)),
            config=BacktestConfig(
                position_lots=2, runner_breakeven=True,
                runner_breakeven_min_rr=Decimal("1.0"),
                min_first_target_rr=Decimal("1.0"),
            ),
        )
        verify_report_matches(replay.trades, reference)
        index_by_time = {c.start_time: i for i, c in enumerate(candles)}
        rows = [measure_trade(trade, candles, index_by_time) for trade in replay.trades]
        payload = {
            "mode": "diagnostic_only_offline_research",
            "window_utc": {"start_inclusive": start.isoformat(), "end_exclusive": end.isoformat()},
            "market_data": {
                "venue": "Delta Exchange India public unauthenticated REST",
                "symbol": "BTCUSD", "resolution": "30m", "candles": len(candles),
                "complete_ist_sessions": 90, "session_reset": "05:30 IST",
            },
            "frozen_rule_verification": {
                "reference_trade_count": len(reference["trades"]),
                "replayed_trade_count": len(replay.trades),
                "all_trade_identity_fields_match": True,
                "runner_breakeven": True,
                "runner_breakeven_min_rr": "1.0",
                "minimum_first_target_rr": "1.0",
                "position_lots": 2,
                "strategy_rules_modified": False,
            },
            "measurement_definitions": {
                "mae": "Maximum adverse entry-to-OHLC excursion from entry candle through exit candle, inclusive",
                "mfe": "Maximum favorable entry-to-OHLC excursion from entry candle through exit candle, inclusive",
                "stop_breach": "Worst OHLC extreme beyond the initial protective stop on the stop-out candle",
                "post_stop": "Candles strictly after the stop-out candle; measured until first original target touch or end of fixed window",
                "atr": "14-period simple mean true range at the signal candle, matching the strategy's signal-time ATR convention",
                "intrabar_limitation": "OHLC cannot determine whether stop or target occurred first inside a candle; the stop-out candle is excluded from post-stop recovery credit",
            },
            "summary": build_summary(rows),
            "trades": rows,
            "safety": {
                "authenticated": False, "private_account_accessed": False,
                "orders_submitted": False, "execution_adapter": False,
            },
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"MAE/MFE DIAGNOSTIC COMPLETE: {len(rows)} verified trades")
        print(json.dumps(payload["summary"], indent=2))
        print(f"REPORT: {args.output}")
        return 0
    except (MarketDataError, ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"MAE/MFE DIAGNOSTIC ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
