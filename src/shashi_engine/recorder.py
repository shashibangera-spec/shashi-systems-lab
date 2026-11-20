"""Append-only local JSONL recorder and bounded REST candle-gap recovery.

This module writes only caller-selected local files. It never truncates, edits,
or silently repairs prior records. No credentials or private account data are used.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from .models import Candle

INTERVAL_SECONDS = 30 * 60


class RecorderError(RuntimeError):
    """Raised when the local append-only log is invalid or cannot be written."""


def _utc(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must be timezone-aware UTC")


def candle_record(candle: Candle, *, record_type: str, source: str) -> dict[str, Any]:
    if record_type not in ("completed_candle", "rest_recovery"):
        raise ValueError("unsupported canonical candle record type")
    if source not in ("websocket", "rest"):
        raise ValueError("candle source must be websocket or rest")
    if (record_type, source) not in (("completed_candle", "websocket"), ("rest_recovery", "rest")):
        raise ValueError("canonical record type and source do not match")
    return {
        "record_type": record_type,
        "source": source,
        "symbol": candle.symbol,
        "resolution": candle.resolution,
        "candle_start_utc": candle.start_time.isoformat(),
        "candle_end_utc": candle.end_time.isoformat(),
        "open": str(candle.open),
        "high": str(candle.high),
        "low": str(candle.low),
        "close": str(candle.close),
        "volume": str(candle.volume),
    }


class AppendOnlyJsonlRecorder:
    """Thread-safe JSONL append writer; validates existing history before appending."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._known_starts: set[str] = set()
        self._latest_start: datetime | None = None
        if self.path.exists():
            self._load_existing()

    def _load_existing(self) -> None:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        raise RecorderError(f"blank line in append-only log at line {line_number}")
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise RecorderError(f"invalid JSON at line {line_number}") from exc
                    if not isinstance(record, dict) or not isinstance(record.get("record_type"), str):
                        raise RecorderError(f"invalid record structure at line {line_number}")
                    stamp = record.get("candle_start_utc")
                    if record["record_type"] in ("completed_candle", "rest_recovery"):
                        if not isinstance(stamp, str):
                            raise RecorderError(f"canonical candle missing start at line {line_number}")
                        try:
                            parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                            _utc(parsed, "candle_start_utc")
                            if parsed.minute not in (0, 30) or parsed.second or parsed.microsecond:
                                raise ValueError("canonical candle start is not UTC half-hour aligned")
                        except (ValueError, TypeError) as exc:
                            raise RecorderError(f"invalid candle start at line {line_number}") from exc
                        self._known_starts.add(parsed.isoformat())
                        if self._latest_start is None or parsed > self._latest_start:
                            self._latest_start = parsed
        except OSError as exc:
            raise RecorderError(f"cannot read existing append-only log: {exc}") from exc

    def append(self, record: dict[str, Any]) -> None:
        if not isinstance(record, dict) or not isinstance(record.get("record_type"), str):
            raise ValueError("record must be an object with record_type")
        if record["record_type"] in ("completed_candle", "rest_recovery"):
            raise ValueError("use append_candle for canonical candle records")
        payload = dict(record)
        payload.setdefault("recorded_at_utc", datetime.now(timezone.utc).isoformat())
        try:
            line = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"record is not JSON-safe: {exc}") from exc
        with self._lock:
            try:
                with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(line + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError as exc:
                raise RecorderError(f"cannot append local record: {exc}") from exc

    def append_candle(self, candle: Candle, *, record_type: str, source: str) -> bool:
        """Append a canonical candle once; return False when already recorded."""
        payload = candle_record(candle, record_type=record_type, source=source)
        stamp = candle.start_time.isoformat()
        with self._lock:
            if stamp in self._known_starts:
                return False
            # Keep the lock through append to make the check-and-append atomic.
            payload.setdefault("recorded_at_utc", datetime.now(timezone.utc).isoformat())
            line = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
            try:
                with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(line + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError as exc:
                raise RecorderError(f"cannot append candle: {exc}") from exc
            self._known_starts.add(stamp)
            if self._latest_start is None or candle.start_time > self._latest_start:
                self._latest_start = candle.start_time
            return True

    @property
    def latest_candle_start(self) -> datetime | None:
        with self._lock:
            return self._latest_start

    def has_candle(self, start_time: datetime) -> bool:
        _utc(start_time, "start_time")
        with self._lock:
            return start_time.astimezone(timezone.utc).isoformat() in self._known_starts


def recover_missing_candles(
    recorder: AppendOnlyJsonlRecorder,
    *,
    start_epoch: int,
    end_epoch: int,
    fetcher: Callable[[int, int, str], Sequence[Candle]],
    max_intervals: int = 48,
) -> dict[str, Any]:
    """Recover [start_epoch, end_epoch) using REST; report every unresolved interval."""
    if start_epoch <= 0 or end_epoch < start_epoch:
        raise ValueError("recovery window must have positive start and end >= start")
    if start_epoch % INTERVAL_SECONDS or end_epoch % INTERVAL_SECONDS:
        raise ValueError("recovery window must align to UTC 30m boundaries")
    if max_intervals <= 0:
        raise ValueError("max_intervals must be positive")
    expected_count = (end_epoch - start_epoch) // INTERVAL_SECONDS
    if expected_count == 0:
        return {"requested_intervals": 0, "recovered": [], "unresolved": []}
    if expected_count > max_intervals:
        raise ValueError("recovery window exceeds configured max_intervals")

    candles = list(fetcher(start_epoch, end_epoch, "30m"))
    expected = set(range(start_epoch, end_epoch, INTERVAL_SECONDS))
    seen: set[int] = set()
    previous: int | None = None
    for candle in candles:
        if not isinstance(candle, Candle) or candle.symbol != "BTCUSD" or candle.resolution != "30m":
            raise RecorderError("REST recovery returned an unsupported candle")
        stamp = int(candle.start_time.timestamp())
        if stamp not in expected:
            raise RecorderError("REST recovery returned a candle outside the requested gap")
        if stamp in seen:
            raise RecorderError("REST recovery returned duplicate candle timestamps")
        if previous is not None and stamp < previous:
            raise RecorderError("REST recovery returned out-of-order candles")
        seen.add(stamp)
        previous = stamp

    recovered: list[str] = []
    for candle in candles:
        if recorder.append_candle(candle, record_type="rest_recovery", source="rest"):
            recovered.append(candle.start_time.isoformat())
    unresolved = [
        datetime.fromtimestamp(stamp, timezone.utc).isoformat()
        for stamp in sorted(expected - seen)
    ]
    recorder.append({
        "record_type": "recovery_report",
        "source": "rest",
        "requested_start_utc": datetime.fromtimestamp(start_epoch, timezone.utc).isoformat(),
        "requested_end_utc_exclusive": datetime.fromtimestamp(end_epoch, timezone.utc).isoformat(),
        "requested_intervals": expected_count,
        "recovered_count": len(recovered),
        "unresolved": unresolved,
    })
    return {"requested_intervals": expected_count, "recovered": recovered, "unresolved": unresolved}
