"""Unauthenticated Delta India BTCUSD public REST market-data adapter.

Read-only by construction: this module exposes GET requests only and has no
credential, private-account, or order-submission code.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import Ticker

BASE_URL = "https://api.india.delta.exchange"
USER_AGENT = "shashi-systems-lab/0.1"


class MarketDataError(RuntimeError):
    """Raised when a public market-data request or payload is invalid."""


@dataclass(frozen=True, slots=True)
class OHLCVCandle:
    symbol: str
    resolution: str
    start_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


def _decimal(value: Any, field: str, *, optional: bool = False) -> Decimal | None:
    if value is None and optional:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        if optional:
            return None
        raise MarketDataError(f"Invalid or missing numeric field: {field}") from exc
    if not result.is_finite():
        if optional:
            return None
        raise MarketDataError(f"Non-finite numeric field: {field}")
    return result


def _timestamp(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        numeric = float(value)
        if numeric > 10_000_000_000:
            numeric /= 1000
        result = datetime.fromtimestamp(numeric, tz=timezone.utc)
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise MarketDataError(f"Invalid timestamp field: {field}") from exc
    else:
        raise MarketDataError(f"Missing or invalid timestamp field: {field}")
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _request_json(path: str, params: dict[str, str] | None = None, timeout: int = 10) -> Any:
    query = f"?{urlencode(params)}" if params else ""
    request = Request(
        f"{BASE_URL}{path}{query}",
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MarketDataError(f"Public market-data request failed: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise MarketDataError("Delta returned an unsuccessful or malformed API response")
    return payload.get("result")


def parse_ticker(payload: dict[str, Any], received_at: datetime | None = None) -> Ticker:
    """Normalize a ticker result object; source time is preferred when provided."""
    if str(payload.get("symbol", "BTCUSD")).upper() != "BTCUSD":
        raise MarketDataError("Ticker payload is not BTCUSD")
    received_at = received_at or datetime.now(timezone.utc)
    source_time = payload.get("timestamp") or payload.get("time")
    observed_at = _timestamp(source_time, "timestamp") if source_time is not None else received_at
    quotes = payload.get("quotes") if isinstance(payload.get("quotes"), dict) else {}
    return Ticker(
        symbol="BTCUSD",
        observed_at=observed_at,
        last_price=_decimal(payload.get("close") or payload.get("last_price"), "close", optional=True),
        mark_price=_decimal(payload.get("mark_price"), "mark_price", optional=True),
        best_bid=_decimal(payload.get("best_bid") or quotes.get("best_bid"), "best_bid", optional=True),
        best_ask=_decimal(payload.get("best_ask") or quotes.get("best_ask"), "best_ask", optional=True),
    )


def parse_candles(payload: Any, resolution: str = "30m") -> list[OHLCVCandle]:
    """Normalize candle rows and reject malformed or internally inconsistent OHLC."""
    if not isinstance(payload, list):
        raise MarketDataError("Candle result must be a list")
    candles: list[OHLCVCandle] = []
    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            raise MarketDataError(f"Candle row {index} is not an object")
        stamp = row.get("time") or row.get("timestamp") or row.get("start")
        if stamp is None:
            raise MarketDataError(f"Candle row {index} has no timestamp")
        opening = _decimal(row.get("open"), f"candles[{index}].open")
        high = _decimal(row.get("high"), f"candles[{index}].high")
        low = _decimal(row.get("low"), f"candles[{index}].low")
        close = _decimal(row.get("close"), f"candles[{index}].close")
        volume = _decimal(row.get("volume", 0), f"candles[{index}].volume")
        assert opening is not None and high is not None and low is not None
        assert close is not None and volume is not None
        if high < max(opening, close, low) or low > min(opening, close, high) or volume < 0:
            raise MarketDataError(f"Candle row {index} has invalid OHLCV relationships")
        candles.append(
            OHLCVCandle(
                symbol="BTCUSD",
                resolution=resolution,
                start_time=_timestamp(stamp, f"candles[{index}].time"),
                open=opening,
                high=high,
                low=low,
                close=close,
                volume=volume,
            )
        )
    return sorted(candles, key=lambda candle: candle.start_time)


def fetch_ticker(timeout: int = 10) -> Ticker:
    result = _request_json("/v2/tickers/BTCUSD", timeout=timeout)
    if not isinstance(result, dict):
        raise MarketDataError("Ticker API result must be an object")
    return parse_ticker(result)


def fetch_candles(
    start_epoch: int,
    end_epoch: int,
    resolution: str = "30m",
    timeout: int = 10,
) -> list[OHLCVCandle]:
    if start_epoch <= 0 or end_epoch <= start_epoch:
        raise ValueError("Require positive start_epoch and end_epoch > start_epoch")
    if resolution != "30m":
        raise ValueError("Phase 1B currently permits only 30m candles")
    result = _request_json(
        "/v2/history/candles",
        {"resolution": resolution, "symbol": "BTCUSD", "start": str(start_epoch), "end": str(end_epoch)},
        timeout=timeout,
    )
    return parse_candles(result, resolution=resolution)


def ticker_to_json(ticker: Ticker) -> dict[str, Any]:
    result = asdict(ticker)
    result["observed_at"] = ticker.observed_at.isoformat()
    for key in ("last_price", "mark_price", "best_bid", "best_ask"):
        value = result[key]
        result[key] = str(value) if value is not None else None
    return result
