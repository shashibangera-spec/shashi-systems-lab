"""Fetch and summarize a read-only 48-hour BTCUSD 30m candle sample."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from shashi_engine.market_data import MarketDataError, fetch_candles

INTERVAL_SECONDS = 30 * 60
LOOKBACK_SECONDS = 48 * 60 * 60


def main() -> int:
    now = datetime.now(timezone.utc)
    now_epoch = int(now.timestamp())
    end_epoch = (now_epoch // INTERVAL_SECONDS) * INTERVAL_SECONDS
    start_epoch = end_epoch - LOOKBACK_SECONDS

    try:
        candles = fetch_candles(start_epoch, end_epoch, resolution="30m")
    except (MarketDataError, ValueError) as exc:
        print(f"MARKET DATA ERROR: {exc}")
        return 1

    times = [int(c.start_time.timestamp()) for c in candles]
    duplicates = len(times) - len(set(times))
    unaligned = [stamp for stamp in times if stamp % INTERVAL_SECONDS != 0]
    gaps = []
    for previous, current in zip(times, times[1:]):
        if current - previous > INTERVAL_SECONDS:
            gaps.append({
                "after": datetime.fromtimestamp(previous, timezone.utc).isoformat(),
                "before": datetime.fromtimestamp(current, timezone.utc).isoformat(),
                "missing_intervals": (current - previous) // INTERVAL_SECONDS - 1,
            })

    completed = [
        c for c in candles
        if int(c.start_time.timestamp()) + INTERVAL_SECONDS <= now_epoch
    ]
    latest = candles[-1] if candles else None
    latest_complete = bool(
        latest and int(latest.start_time.timestamp()) + INTERVAL_SECONDS <= now_epoch
    )

    report = {
        "mode": "public_read_only",
        "symbol": "BTCUSD",
        "resolution": "30m",
        "window_start_utc": datetime.fromtimestamp(start_epoch, timezone.utc).isoformat(),
        "window_end_utc": datetime.fromtimestamp(end_epoch, timezone.utc).isoformat(),
        "observed_at_utc": now.isoformat(),
        "returned_candles": len(candles),
        "completed_candles": len(completed),
        "latest_candle_complete": latest_complete,
        "duplicate_timestamps": duplicates,
        "unaligned_timestamps": len(unaligned),
        "gaps": gaps,
        "first_candle": (
            {
                "start_time": candles[0].start_time.isoformat(),
                "open": str(candles[0].open),
                "high": str(candles[0].high),
                "low": str(candles[0].low),
                "close": str(candles[0].close),
                "volume": str(candles[0].volume),
            } if candles else None
        ),
        "latest_candle": (
            {
                "start_time": latest.start_time.isoformat(),
                "open": str(latest.open),
                "high": str(latest.high),
                "low": str(latest.low),
                "close": str(latest.close),
                "volume": str(latest.volume),
            } if latest else None
        ),
        "safety": {
            "authenticated": False,
            "orders_submitted": False,
            "private_account_data_accessed": False,
        },
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
