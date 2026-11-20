"""Bounded, unauthenticated probe of Delta's public BTCUSD 30m candle stream.

The script runs for at most 90 seconds, subscribes to one public channel and
prints a small summary. It does not authenticate, write files or submit orders.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

PUBLIC_WS_URL = "wss://public-socket.india.delta.exchange"
SYMBOL = "BTCUSD"
CHANNEL = "candlestick_30m"
RUN_SECONDS = 90


def parse_candle_message(message: dict[str, Any]) -> dict[str, str] | None:
    """Validate and normalize one public candlestick event."""
    if message.get("type") != CHANNEL or message.get("sy") != SYMBOL:
        return None

    try:
        raw_ts = Decimal(str(message["ts"]))
        # Delta's compact WebSocket examples use microsecond epoch timestamps.
        if not raw_ts.is_finite() or raw_ts <= 0:
            raise ValueError("invalid event timestamp")
        timestamp = datetime.fromtimestamp(float(raw_ts / Decimal("1e6")), timezone.utc)

        # Delta compact candlestick messages expose candle start in "cst"
        # (Unix microseconds). Accept the descriptive legacy key as well.
        raw_candle_start = message.get("cst", message.get("candle_start_time"))
        if raw_candle_start is None:
            candle_start_time = "not_provided"
        else:
            raw_start = Decimal(str(raw_candle_start))
            if not raw_start.is_finite() or raw_start <= 0:
                raise ValueError("invalid candle start timestamp")
            # Delta's compact "cst" is commonly microseconds; the
            # descriptive candle_start_time form has also appeared as
            # nanoseconds. Infer the epoch unit by magnitude for both.
            if raw_start >= Decimal("1e17"):
                start_seconds = raw_start / Decimal("1e9")
            elif raw_start >= Decimal("1e14"):
                start_seconds = raw_start / Decimal("1e6")
            elif raw_start >= Decimal("1e11"):
                start_seconds = raw_start / Decimal("1e3")
            else:
                start_seconds = raw_start
            candle_start_dt = datetime.fromtimestamp(float(start_seconds), timezone.utc)
            candle_start_time = candle_start_dt.isoformat()

        values = {
            name: Decimal(str(message[key]))
            for name, key in (
                ("open", "o"),
                ("high", "h"),
                ("low", "l"),
                ("close", "c"),
            )
        }
        volume = Decimal(str(message["v"])) if "v" in message else None
        if any(not value.is_finite() for value in values.values()):
            raise ValueError("non-finite OHLC")
        if values["high"] < max(values["open"], values["close"], values["low"]):
            raise ValueError("inconsistent high")
        if values["low"] > min(values["open"], values["close"], values["high"]):
            raise ValueError("inconsistent low")
        if volume is not None and (not volume.is_finite() or volume < 0):
            raise ValueError("invalid volume")
    except (KeyError, InvalidOperation, TypeError, ValueError, OverflowError, OSError) as exc:
        raise ValueError(f"Invalid BTCUSD 30m candle message: {exc}") from exc

    return {
        "symbol": SYMBOL,
        "resolution": str(message.get("res", "30m")),
        "event_time_utc": timestamp.isoformat(),
        "candle_start_time_utc": candle_start_time,
        **{key: str(value) for key, value in values.items()},
        "volume": str(volume) if volume is not None else "not_provided",
    }


def main() -> int:
    try:
        import websocket
    except ImportError:
        print("Missing optional dependency. Install with: pip install -e '.[market-data]'")
        return 2

    received: list[dict[str, str]] = []
    errors: list[str] = []
    done = threading.Event()

    def on_open(ws: Any) -> None:
        ws.send(json.dumps({
            "type": "subscribe",
            "payload": {
                "channels": [{"name": CHANNEL, "symbols": [SYMBOL]}]
            },
        }))

    def on_message(ws: Any, raw: str) -> None:
        try:
            decoded = json.loads(raw)
            if not isinstance(decoded, dict):
                return
            parsed = parse_candle_message(decoded)
            if parsed is not None:
                received.append(parsed)
        except (json.JSONDecodeError, ValueError) as exc:
            errors.append(str(exc))

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
    timer = threading.Timer(RUN_SECONDS, lambda: (done.set(), app.close()))
    timer.daemon = True
    timer.start()
    try:
        app.run_forever(ping_interval=30, ping_timeout=5)
    finally:
        timer.cancel()

    report = {
        "mode": "public_read_only",
        "endpoint": PUBLIC_WS_URL,
        "symbol": SYMBOL,
        "channel": CHANNEL,
        "probe_seconds_max": RUN_SECONDS,
        "received_candle_updates": len(received),
        "first_update": received[0] if received else None,
        "latest_update": received[-1] if received else None,
        "errors": errors,
        "safety": {
            "authenticated": False,
            "orders_submitted": False,
            "private_account_data_accessed": False,
            "files_written": False,
        },
    }
    print(json.dumps(report, indent=2))
    return 0 if received and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
