"""Run the Phase 1I offline BTCUSD AMT + Price Action backtest."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shashi_engine.amt_pa_backtest import BacktestConfig, run_backtest
from shashi_engine.accounting import AccountingPolicy, FeeSchedule, FundingEvent
from shashi_engine.contract_verification import fetch_btcusd_product, parse_product
from shashi_engine.market_data import MarketDataError, fetch_candles, fetch_historical_candles
from shashi_engine.models import Candle, Instrument


def parse_utc(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include UTC offset/Z")
    return result.astimezone(timezone.utc)


def load_jsonl(path: Path) -> list[Candle]:
    candles: list[Candle] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        record = json.loads(line)
        if record.get("record_type") not in ("completed_candle", "rest_recovery"):
            continue
        row = record.get("candle", record)
        stamp_value = row.get("start_time", row.get("candle_start_time", row.get("cst")))
        if stamp_value is None:
            raise ValueError(f"JSONL line {line_no} has no canonical candle start")
        stamp = parse_utc(str(stamp_value))
        candles.append(Candle(
            "BTCUSD", "30m", stamp, Decimal(str(row["open"])), Decimal(str(row["high"])),
            Decimal(str(row["low"])), Decimal(str(row["close"])), Decimal(str(row.get("volume", "0"))),
        ))
    return candles


def load_funding(path: Path | None) -> list[FundingEvent]:
    if path is None:
        return []
    events: list[FundingEvent] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            events.append(FundingEvent(
                Decimal(row["rate"]), "long", 1, Decimal(row["mark_price"]),
                parse_utc(row["timestamp_utc"]), 28_800,
            ))
    return sorted(events, key=lambda event: event.event_at)


def json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    return value


def summary_for(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize all closed trades and distinguish strategy exits from EOD marks."""
    def summarize(group: list[dict[str, Any]]) -> dict[str, Any]:
        gross = sum((Decimal(t["gross_pnl_usd"]) for t in group), Decimal(0))
        fees = sum((Decimal(t["fees_and_gst_usd"]) for t in group), Decimal(0))
        net_ex = sum((Decimal(t["net_ex_funding_usd"]) for t in group), Decimal(0))
        funding_complete = bool(group) and all(bool(t["funding_complete"]) for t in group)
        net_funding = (
            sum((Decimal(t["net_including_funding_usd"]) for t in group), Decimal(0))
            if group and funding_complete else None
        )
        wins = [Decimal(t["net_ex_funding_usd"]) for t in group if Decimal(t["net_ex_funding_usd"]) > 0]
        losses = [Decimal(t["net_ex_funding_usd"]) for t in group if Decimal(t["net_ex_funding_usd"]) < 0]
        profit_factor = sum(wins, Decimal(0)) / abs(sum(losses, Decimal(0))) if losses else None
        equity = peak = drawdown = Decimal(0)
        for trade in group:
            equity += Decimal(trade["net_ex_funding_usd"])
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
        return {
            "trade_count": len(group), "gross_pnl_usd": str(gross),
            "fees_and_gst_usd": str(fees), "net_ex_funding_usd": str(net_ex),
            "net_including_funding_usd": str(net_funding) if net_funding is not None else None,
            "funding_complete_for_all_trades": funding_complete,
            "win_rate_ex_funding": (str(Decimal(len(wins)) / Decimal(len(group))) if group else None),
            "profit_factor_ex_funding": str(profit_factor) if profit_factor is not None else None,
            "max_drawdown_ex_funding_usd": str(drawdown),
        }

    strategy_exits = [t for t in trades if t["final_exit_reason"] != "END_OF_DATA"]
    end_of_data = [t for t in trades if t["final_exit_reason"] == "END_OF_DATA"]
    all_trades = summarize(trades)
    return {
        **all_trades,
        "strategy_exits_excluding_end_of_data": summarize(strategy_exits),
        "end_of_data_liquidations": summarize(end_of_data),
        "all_trades_including_end_of_data": all_trades,
    }

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--start-utc", type=parse_utc)
    source.add_argument("--input-jsonl", type=Path)
    source.add_argument("--fetch-days", type=int, metavar="DAYS", help="fetch exact complete 05:30 IST sessions from public Delta REST (1–90 days)")
    parser.add_argument("--end-utc", type=parse_utc)
    parser.add_argument("--funding-csv", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/reports/phase1i_backtest.json"))
    parser.add_argument("--position-lots", type=int, default=2)
    parser.add_argument(
        "--runner-breakeven", action="store_true",
        help="after a confirmed 50% target partial, move the remaining runner stop to fee-adjusted breakeven from the next candle",
    )
    args = parser.parse_args()

    try:
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
            raise ValueError("verified Delta product is not product_id 27")

        fetch_window = None
        if args.input_jsonl:
            candles = load_jsonl(args.input_jsonl)
        elif args.fetch_days is not None:
            candles = fetch_historical_candles(days=args.fetch_days)
            if candles:
                fetch_window = {"start_utc": candles[0].start_time.isoformat(), "end_exclusive_utc": candles[-1].end_time.isoformat(), "complete_ist_sessions": args.fetch_days}
        else:
            if args.end_utc is None or args.end_utc <= args.start_utc:
                parser.error("--end-utc must be later than --start-utc")
            if int(args.start_utc.timestamp()) % 1800 or int(args.end_utc.timestamp()) % 1800:
                parser.error("--start-utc and --end-utc must align to UTC half-hours")
            candles = []
            cursor = int(args.start_utc.timestamp())
            end_epoch = int(args.end_utc.timestamp())
            while cursor < end_epoch:
                stop = min(cursor + 48 * 1800, end_epoch)
                chunk = fetch_candles(cursor, stop, resolution="30m")
                # Treat each request as a half-open interval; ignore an adjacent boundary row.
                candles.extend(c for c in chunk if cursor <= int(c.start_time.timestamp()) < stop)
                cursor = stop
            candles.sort(key=lambda candle: candle.start_time)
            now = datetime.now(timezone.utc)
            candles = [c for c in candles if c.end_time <= now]

        funding = load_funding(args.funding_csv)
        fee_schedule = FeeSchedule(
            maker_rate=Decimal("0.0002"), taker_rate=Decimal("0.0005"),
            gst_rate=Decimal("0.18"),
        )
        result = run_backtest(
            candles, instrument, fee_schedule,
            AccountingPolicy(max_fx_age=timedelta(minutes=10)),
            funding_events=funding,
            config=BacktestConfig(
                position_lots=args.position_lots,
                runner_breakeven=args.runner_breakeven,
            ),
            metadata_source="Delta India public product verifier",
        )
        trades = [json_value(asdict(trade)) for trade in result.trades]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "mode": "offline_research_only",
            "instrument": {
                "venue": "Delta Exchange India", "symbol": instrument.symbol,
                "product_id": instrument.product_id, "contract_value_btc": str(instrument.contract_value),
                "tick_size_usd": str(instrument.tick_size), "quote_asset": instrument.quote_asset,
                "api_settlement_asset": instrument.api_settlement_asset,
                "funding_interval_seconds": instrument.funding_interval_seconds,
            },
            "session": "05:30 IST to 05:30 IST",
            "profile_method": {"tpo_row_usd": "50", "value_area_fraction": "0.70",
                               "complete_session_bars": 48},
            "assumptions": {
                "position_lots": args.position_lots, "partial_close_fraction": "0.50",
                "entry_and_exit_liquidity": "taker", "maker_fee": "0.0002",
                "taker_fee": "0.0005", "gst_on_fee": "0.18",
                "fee_gst_currency_and_exchange_rounding": "Phase 1E explicit USD scenario assumptions; not exchange-reconciled",
                "funding_file_supplied": args.funding_csv is not None,
                "runner_breakeven_enabled": args.runner_breakeven,
                "runner_breakeven_activation": "next candle after completed-candle partial confirmation",
                "runner_breakeven_fee_basis": "remaining runner entry taker fee + exit taker fee, both including GST",
            },
            "candles_used": result.candles_used,
            "historical_fetch_window": fetch_window,
            "complete_profiles": len(result.profiles),
            "skipped_no_reference": result.skipped_no_reference,
            "skipped_invalid_stop": result.skipped_invalid_stop,
            "summary": summary_for(trades),
            "trades": trades,
            "safety": {"authenticated": False, "private_account_accessed": False,
                       "orders_submitted": False, "execution_adapter": False},
        }
        args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"PHASE 1I COMPLETE: {len(result.trades)} trades; report={args.output}")
        print(json.dumps(payload["summary"], indent=2))
        return 0
    except (MarketDataError, ValueError, OSError, KeyError) as exc:
        print(f"PHASE 1I ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
