"""Run a bounded public BTCUSD 30m WebSocket recorder with REST gap recovery.

Default output is a local JSONL file under data/; it is not committed by this tool.
Only public market data is used. No authentication or order endpoints exist here.
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from shashi_engine.feed_health import FeedHealthMonitor
from shashi_engine.market_data import MarketDataError, fetch_candles
from shashi_engine.models import Candle
from shashi_engine.recorder import AppendOnlyJsonlRecorder, candle_record, recover_missing_candles

try:
    from scripts.probe_btcusd_websocket import CHANNEL, PUBLIC_WS_URL, SYMBOL, parse_candle_message
except ModuleNotFoundError:
    from probe_btcusd_websocket import CHANNEL, PUBLIC_WS_URL, SYMBOL, parse_candle_message

INTERVAL_SECONDS = 30 * 60


def _to_candle(update: dict[str, str]) -> Candle:
    start = datetime.fromisoformat(update["candle_start_time_utc"].replace("Z", "+00:00"))
    if start.tzinfo is None:
        raise ValueError("WebSocket candle start must include UTC timezone")
    from decimal import Decimal
    if update["volume"] == "not_provided":
        raise ValueError("WebSocket update is missing volume")
    return Candle(
        symbol=SYMBOL, resolution="30m", start_time=start.astimezone(timezone.utc),
        open=Decimal(update["open"]), high=Decimal(update["high"]),
        low=Decimal(update["low"]), close=Decimal(update["close"]),
        volume=Decimal(update["volume"]),
    )


def run_recorder(
    *,
    output_path: str,
    duration_seconds: int = 3600,
    stale_after_seconds: int = 120,
    max_recovery_intervals: int = 48,
    reconnect_delay_seconds: int = 5,
) -> int:
    try:
        import websocket
    except ImportError:
        print("Missing optional dependency. Install with: pip install -e '.[market-data]'")
        return 2
    if duration_seconds <= 0 or stale_after_seconds <= 0 or max_recovery_intervals <= 0:
        raise ValueError("duration, stale threshold and recovery limit must be positive")

    recorder = AppendOnlyJsonlRecorder(output_path)
    stop_at = time.monotonic() + duration_seconds
    monitor_stop = threading.Event()
    latest_update: dict[str, str] | None = None
    active_bucket: int | None = None
    state_lock = threading.Lock()
    errors: list[str] = []

    def on_health(state: str, at: datetime, last_message: datetime | None) -> None:
        recorder.append({
            "record_type": "feed_health",
            "state": state,
            "observed_at_utc": at.isoformat(),
            "last_message_at_utc": last_message.isoformat() if last_message else None,
        })

    monitor = FeedHealthMonitor(
        stale_after=timedelta(seconds=stale_after_seconds),
        on_transition=on_health,
    )

    def monitor_loop() -> None:
        while not monitor_stop.wait(2):
            monitor.check(datetime.now(timezone.utc))

    health_thread = threading.Thread(target=monitor_loop, name="feed-health-monitor", daemon=True)
    health_thread.start()

    def on_open(ws: Any) -> None:
        monitor.connected(datetime.now(timezone.utc))
        ws.send(json.dumps({
            "type": "subscribe",
            "payload": {"channels": [{"name": CHANNEL, "symbols": [SYMBOL]}]},
        }))

    def on_message(ws: Any, raw: str) -> None:
        nonlocal latest_update, active_bucket
        try:
            decoded = json.loads(raw)
            if not isinstance(decoded, dict):
                return
            update = parse_candle_message(decoded)
            if update is None:
                return
            was_stale = monitor.state == "STALE"
            if update["candle_start_time_utc"] == "not_provided":
                raise ValueError("WebSocket candle is missing explicit cst candle-start timestamp")
            candle = _to_candle(update)
            bucket = int(candle.start_time.timestamp())
            monitor.message_received(datetime.now(timezone.utc))
            recorder.append({
                "record_type": "websocket_update",
                "source": "websocket",
                **update,
            })
            with state_lock:
                previous_bucket = active_bucket
                previous_update = latest_update
                if previous_bucket is not None and bucket < previous_bucket:
                    raise ValueError("WebSocket candle start moved backwards")
                if previous_bucket is not None and bucket == previous_bucket:
                    latest_update = update
                    return
                if previous_bucket is not None and previous_update is not None and not was_stale:
                    final_candle = _to_candle(previous_update)
                    recorder.append_candle(final_candle, record_type="completed_candle", source="websocket")
                last = recorder.latest_candle_start
                if last is not None:
                    gap_start = int(last.timestamp()) + INTERVAL_SECONDS
                    if gap_start < bucket:
                        result = recover_missing_candles(
                            recorder,
                            start_epoch=gap_start,
                            end_epoch=bucket,
                            fetcher=fetch_candles,
                            max_intervals=max_recovery_intervals,
                        )
                        if result["unresolved"]:
                            errors.append(f"REST recovery unresolved: {len(result['unresolved'])} intervals")
                active_bucket = bucket
                latest_update = update
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, MarketDataError) as exc:
            errors.append(str(exc))
            recorder.append({"record_type": "feed_error", "message": str(exc)})
            ws.close()

    def on_error(ws: Any, error: Any) -> None:
        nonlocal latest_update, active_bucket
        errors.append(str(error))
        monitor.disconnected(datetime.now(timezone.utc))
        with state_lock:
            latest_update = None
            active_bucket = None

    def on_close(ws: Any, status: Any, message: Any) -> None:
        nonlocal latest_update, active_bucket
        monitor.disconnected(datetime.now(timezone.utc))
        with state_lock:
            latest_update = None
            active_bucket = None

    try:
        while time.monotonic() < stop_at:
            app = websocket.WebSocketApp(
                PUBLIC_WS_URL,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )
            remaining = max(1, int(stop_at - time.monotonic()))
            timer = threading.Timer(remaining, app.close)
            timer.daemon = True
            timer.start()
            try:
                app.run_forever(ping_interval=30, ping_timeout=10)
            finally:
                timer.cancel()
            if time.monotonic() < stop_at:
                time.sleep(min(reconnect_delay_seconds, max(0, stop_at - time.monotonic())))
        recorder.append({
            "record_type": "recorder_session_end",
            "observed_at_utc": datetime.now(timezone.utc).isoformat(),
            "errors": errors,
            "last_completed_candle_start_utc": (
                recorder.latest_candle_start.isoformat() if recorder.latest_candle_start else None
            ),
            "safety": {"authenticated": False, "orders_submitted": False, "private_account_data_accessed": False},
        })
    finally:
        monitor_stop.set()
        health_thread.join(timeout=5)
    print(json.dumps({
        "mode": "public_read_only",
        "output_path": output_path,
        "duration_seconds": duration_seconds,
        "last_completed_candle_start_utc": (
            recorder.latest_candle_start.isoformat() if recorder.latest_candle_start else None
        ),
        "errors": errors,
        "safety": {"authenticated": False, "orders_submitted": False, "private_account_data_accessed": False},
    }, indent=2))
    return 0 if not errors else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/market_data/btcusd_30m.jsonl")
    parser.add_argument("--duration-seconds", type=int, default=3600)
    parser.add_argument("--stale-after-seconds", type=int, default=120)
    parser.add_argument("--max-recovery-intervals", type=int, default=48)
    args = parser.parse_args()
    return run_recorder(
        output_path=args.output,
        duration_seconds=args.duration_seconds,
        stale_after_seconds=args.stale_after_seconds,
        max_recovery_intervals=args.max_recovery_intervals,
    )


if __name__ == "__main__":
    raise SystemExit(main())
