"""Compare one completed BTCUSD 30m WebSocket candle with Delta REST history.

The WebSocket candle is identified only by Delta's explicit candle-start field
(cst), not by its event/publish timestamp. The script waits for cst to advance,
then compares the completed candle with REST. It writes no files.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from shashi_engine.market_data import MarketDataError, fetch_candles
try:
    from scripts.probe_btcusd_websocket import CHANNEL, PUBLIC_WS_URL, SYMBOL, parse_candle_message
except ModuleNotFoundError:
    # When executed as "python scripts/...", the scripts directory is sys.path[0].
    from probe_btcusd_websocket import CHANNEL, PUBLIC_WS_URL, SYMBOL, parse_candle_message

INTERVAL_SECONDS = 30 * 60
MAX_WAIT_SECONDS = 40 * 60
REST_RETRY_COUNT = 4
REST_RETRY_DELAY_SECONDS = 2


def candle_start_epoch(candle_start_time_utc: str) -> int:
    """Parse Delta's explicit candle-start timestamp; never infer it from event time."""
    if candle_start_time_utc == "not_provided":
        raise ValueError("Delta WebSocket message is missing explicit candle start (cst)")
    candle_start = datetime.fromisoformat(candle_start_time_utc.replace("Z", "+00:00"))
    if candle_start.tzinfo is None:
        candle_start = candle_start.replace(tzinfo=timezone.utc)
    epoch = int(candle_start.astimezone(timezone.utc).timestamp())
    if epoch % INTERVAL_SECONDS:
        raise ValueError("Delta WebSocket candle start is not aligned to a UTC 30m boundary")
    return epoch


def compare_ohlcv(websocket_candle: dict[str, str], rest_candle: Any) -> dict[str, bool]:
    """Compare normalized WebSocket values against a REST OHLCVCandle."""
    return {
        "open": Decimal(websocket_candle["open"]) == rest_candle.open,
        "high": Decimal(websocket_candle["high"]) == rest_candle.high,
        "low": Decimal(websocket_candle["low"]) == rest_candle.low,
        "close": Decimal(websocket_candle["close"]) == rest_candle.close,
        "volume": (
            websocket_candle["volume"] != "not_provided"
            and Decimal(websocket_candle["volume"]) == rest_candle.volume
        ),
    }


def _candle_json(candle: Any) -> dict[str, str]:
    return {
        "start_time_utc": candle.start_time.isoformat(),
        "open": str(candle.open),
        "high": str(candle.high),
        "low": str(candle.low),
        "close": str(candle.close),
        "volume": str(candle.volume),
    }


def main() -> int:
    try:
        import websocket
    except ImportError:
        print("Missing optional dependency. Install with: pip install -e '.[market-data]'")
        return 2

    latest: dict[str, str] | None = None
    active_bucket: int | None = None
    completed_ws: dict[str, str] | None = None
    completed_bucket: int | None = None
    errors: list[str] = []
    done = threading.Event()

    def on_open(ws: Any) -> None:
        ws.send(json.dumps({
            "type": "subscribe",
            "payload": {"channels": [{"name": CHANNEL, "symbols": [SYMBOL]}]},
        }))

    def on_message(ws: Any, raw: str) -> None:
        nonlocal latest, active_bucket, completed_ws, completed_bucket
        try:
            decoded = json.loads(raw)
            if not isinstance(decoded, dict):
                return
            parsed = parse_candle_message(decoded)
            if parsed is None:
                return
            bucket = candle_start_epoch(parsed["candle_start_time_utc"])
            if active_bucket is None:
                active_bucket = bucket
                latest = parsed
                return
            if bucket < active_bucket:
                return
            if bucket == active_bucket:
                latest = parsed
                return

            # A newer bucket proves the previous bucket has rolled over.
            if bucket != active_bucket + INTERVAL_SECONDS:
                errors.append("WebSocket skipped one or more 30m candle buckets")
                done.set()
                ws.close()
                return
            completed_ws = latest
            completed_bucket = active_bucket
            done.set()
            ws.close()
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            errors.append(str(exc))
            done.set()
            ws.close()

    def on_error(ws: Any, error: Any) -> None:
        errors.append(str(error))
        done.set()
        ws.close()

    def on_close(ws: Any, status: Any, message: Any) -> None:
        done.set()

    app = websocket.WebSocketApp(
        PUBLIC_WS_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
    timer = threading.Timer(MAX_WAIT_SECONDS, lambda: (errors.append("Timed out waiting for candle rollover"), done.set(), app.close()))
    timer.daemon = True
    timer.start()
    try:
        app.run_forever(ping_interval=30, ping_timeout=5)
    finally:
        timer.cancel()

    if errors or completed_ws is None or completed_bucket is None:
        print(json.dumps({
            "mode": "public_read_only",
            "result": "INCONCLUSIVE",
            "errors": errors or ["No completed WebSocket candle captured"],
            "safety": {"authenticated": False, "orders_submitted": False, "private_account_data_accessed": False, "files_written": False},
        }, indent=2))
        return 1

    # Give the REST history endpoint a moment to publish the closed interval.
    rest_candles = []
    rest_error = None
    for attempt in range(REST_RETRY_COUNT):
        try:
            rest_candles = fetch_candles(completed_bucket, completed_bucket + INTERVAL_SECONDS, resolution="30m")
            match = next((c for c in rest_candles if int(c.start_time.timestamp()) == completed_bucket), None)
            if match is not None:
                break
        except (MarketDataError, ValueError) as exc:
            rest_error = str(exc)
        if attempt < REST_RETRY_COUNT - 1:
            time.sleep(REST_RETRY_DELAY_SECONDS)
    else:
        match = None

    if match is None:
        print(json.dumps({
            "mode": "public_read_only",
            "result": "INCONCLUSIVE",
            "candle_start_utc": datetime.fromtimestamp(completed_bucket, timezone.utc).isoformat(),
            "rest_error": rest_error,
            "errors": ["Completed candle was not returned by REST after bounded retries"],
            "safety": {"authenticated": False, "orders_submitted": False, "private_account_data_accessed": False, "files_written": False},
        }, indent=2))
        return 1

    field_matches = compare_ohlcv(completed_ws, match)
    report = {
        "mode": "public_read_only",
        "result": "MATCH" if all(field_matches.values()) else "MISMATCH",
        "symbol": SYMBOL,
        "resolution": "30m",
        "candle_start_utc": datetime.fromtimestamp(completed_bucket, timezone.utc).isoformat(),
        "websocket_final_update": completed_ws,
        "rest_completed_candle": _candle_json(match),
        "field_matches": field_matches,
        "safety": {"authenticated": False, "orders_submitted": False, "private_account_data_accessed": False, "files_written": False},
    }
    print(json.dumps(report, indent=2))
    return 0 if all(field_matches.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
