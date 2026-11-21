"""Read-only integrity audit for Phase 1F BTCUSD JSONL history.

The auditor never sorts, repairs, truncates, or writes to the input recording.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Sequence

from .models import Candle
from .recorder import AppendOnlyJsonlRecorder, INTERVAL_SECONDS, RecorderError

CANONICAL_TYPES = {"completed_candle", "rest_recovery"}
EXPECTED_SYMBOL = "BTCUSD"
EXPECTED_RESOLUTION = "30m"


def _parse_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO-8601 UTC string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} is not a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must be timezone-aware UTC")
    return parsed.astimezone(timezone.utc)


def _canonical_candle(record: dict[str, Any], line_number: int) -> Candle:
    expected = {"completed_candle": "websocket", "rest_recovery": "rest"}
    record_type = record.get("record_type")
    if record_type not in expected or record.get("source") != expected[record_type]:
        raise ValueError(f"line {line_number}: canonical record type/source mismatch")
    if record.get("symbol") != EXPECTED_SYMBOL or record.get("resolution") != EXPECTED_RESOLUTION:
        raise ValueError(f"line {line_number}: unsupported canonical symbol or resolution")
    start = _parse_utc(record.get("candle_start_utc"), "candle_start_utc")
    end = _parse_utc(record.get("candle_end_utc"), "candle_end_utc")
    if end != start + timedelta(seconds=INTERVAL_SECONDS):
        raise ValueError(f"line {line_number}: candle end does not equal start + 30 minutes")
    try:
        return Candle(
            symbol=EXPECTED_SYMBOL, resolution=EXPECTED_RESOLUTION, start_time=start,
            open=Decimal(str(record["open"])), high=Decimal(str(record["high"])),
            low=Decimal(str(record["low"])), close=Decimal(str(record["close"])),
            volume=Decimal(str(record["volume"])),
        )
    except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"line {line_number}: invalid canonical OHLCV: {exc}") from exc


@dataclass(frozen=True, slots=True)
class HistoryAudit:
    path: str
    file_bytes: int
    sha256_before: str
    total_records: int
    canonical_candles: int
    websocket_candles: int
    rest_recovery_candles: int
    duplicate_starts: tuple[str, ...]
    out_of_order_pairs: tuple[tuple[str, str], ...]
    missing_intervals: int
    unresolved_recovery_intervals: int
    malformed_lines: tuple[str, ...]
    structural_issues: tuple[str, ...]
    recovery_report_issues: tuple[str, ...]
    first_candle_start_utc: str | None
    last_candle_start_utc: str | None
    acceptable: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def audit_jsonl_history(path: str | Path) -> HistoryAudit:
    """Audit an existing JSONL file without changing its bytes."""
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"JSONL history does not exist: {target}")
    digest = hashlib.sha256()
    file_bytes = 0
    malformed: list[str] = []
    structural: list[str] = []
    recovery_issues: list[str] = []
    total_records = 0
    candles: list[tuple[datetime, str]] = []
    unresolved_starts: set[datetime] = set()
    recovery_report_index = 0
    with target.open("rb") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            digest.update(raw_line)
            file_bytes += len(raw_line)
            if not raw_line.endswith(b"\n"):
                malformed.append(f"line {line_number}: unterminated JSONL record")
                continue
            try:
                line = raw_line[:-1].decode("utf-8")
            except UnicodeDecodeError as exc:
                malformed.append(f"line {line_number}: invalid UTF-8 ({exc})")
                continue
            if not line.strip():
                malformed.append(f"line {line_number}: blank line")
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                malformed.append(f"line {line_number}: invalid JSON ({exc.msg})")
                continue
            if not isinstance(record, dict) or not isinstance(record.get("record_type"), str):
                structural.append(f"line {line_number}: record must be an object with record_type")
                continue
            total_records += 1
            if "recorded_at_utc" in record:
                try:
                    _parse_utc(record["recorded_at_utc"], "recorded_at_utc")
                except ValueError as exc:
                    structural.append(f"line {line_number}: {exc}")
            if record["record_type"] in CANONICAL_TYPES:
                try:
                    candle = _canonical_candle(record, line_number)
                    candles.append((candle.start_time, record["record_type"]))
                except ValueError as exc:
                    structural.append(str(exc))
            elif record["record_type"] == "recovery_report":
                recovery_report_index += 1
                try:
                    requested = int(record["requested_intervals"])
                    recovered = int(record["recovered_count"])
                    unresolved = record["unresolved"]
                    if not isinstance(unresolved, list) or requested < 0 or recovered < 0:
                        raise ValueError("invalid recovery counts or unresolved list")
                    if recovered + len(unresolved) > requested:
                        raise ValueError("recovered plus unresolved exceeds requested interval count")
                    for stamp in unresolved:
                        parsed = _parse_utc(stamp, "unresolved timestamp")
                        if parsed.minute not in (0, 30) or parsed.second or parsed.microsecond:
                            raise ValueError("unresolved timestamp is not UTC half-hour aligned")
                        unresolved_starts.add(parsed)
                except (KeyError, TypeError, ValueError) as exc:
                    recovery_issues.append(f"recovery report {recovery_report_index}: {exc}")
    sha256_before = digest.hexdigest()

    starts = [item[0] for item in candles]
    seen: set[datetime] = set()
    duplicates: list[str] = []
    for stamp in starts:
        if stamp in seen and stamp.isoformat() not in duplicates:
            duplicates.append(stamp.isoformat())
        seen.add(stamp)
    out_of_order = [
        (left.isoformat(), right.isoformat())
        for left, right in zip(starts, starts[1:]) if right < left
    ]

    unique_sorted = sorted(seen)
    missing = 0
    for left, right in zip(unique_sorted, unique_sorted[1:]):
        elapsed = int((right - left).total_seconds())
        if elapsed % INTERVAL_SECONDS:
            structural.append(
                f"non-grid candle spacing between {left.isoformat()} and {right.isoformat()}"
            )
        else:
            missing += max(0, elapsed // INTERVAL_SECONDS - 1)

    # Historical unresolved reports cease to be outstanding once a later append fills that start.
    unresolved_count = len(unresolved_starts - seen)
    ws_count = sum(kind == "completed_candle" for _, kind in candles)
    rest_count = sum(kind == "rest_recovery" for _, kind in candles)
    first = unique_sorted[0].isoformat() if unique_sorted else None
    last = unique_sorted[-1].isoformat() if unique_sorted else None
    acceptable = bool(candles) and not any((
        malformed, structural, recovery_issues, duplicates, out_of_order, missing, unresolved_count
    ))
    return HistoryAudit(
        path=str(target), file_bytes=file_bytes, sha256_before=sha256_before,
        total_records=total_records, canonical_candles=len(candles),
        websocket_candles=ws_count, rest_recovery_candles=rest_count,
        duplicate_starts=tuple(duplicates), out_of_order_pairs=tuple(out_of_order),
        missing_intervals=missing, unresolved_recovery_intervals=unresolved_count,
        malformed_lines=tuple(malformed), structural_issues=tuple(structural),
        recovery_report_issues=tuple(recovery_issues),
        first_candle_start_utc=first, last_candle_start_utc=last, acceptable=acceptable,
    )


def validate_rest_gap(
    start_epoch: int, end_epoch: int, *,
    fetcher: Callable[[int, int, str], Sequence[Candle]], max_intervals: int = 48,
) -> dict[str, Any]:
    """Read-only REST check for a UTC-aligned gap; does not append returned candles."""
    if start_epoch <= 0 or end_epoch < start_epoch:
        raise ValueError("gap bounds must be positive with end >= start")
    if start_epoch % INTERVAL_SECONDS or end_epoch % INTERVAL_SECONDS:
        raise ValueError("gap bounds must align to UTC 30m boundaries")
    if max_intervals <= 0:
        raise ValueError("max_intervals must be positive")
    expected = list(range(start_epoch, end_epoch, INTERVAL_SECONDS))
    if len(expected) > max_intervals:
        raise ValueError("gap exceeds configured maximum interval count")
    if not expected:
        return {"requested_intervals": 0, "returned": [], "unresolved": [], "valid": True}
    returned_candles = list(fetcher(start_epoch, end_epoch, "30m"))
    seen: set[int] = set()
    previous: int | None = None
    candles: list[Candle] = []
    expected_set = set(expected)
    for candle in returned_candles:
        if not isinstance(candle, Candle) or candle.symbol != EXPECTED_SYMBOL or candle.resolution != EXPECTED_RESOLUTION:
            raise RecorderError("REST gap check returned unsupported symbol or resolution")
        stamp = int(candle.start_time.timestamp())
        if stamp not in expected_set:
            # Ignore only adjacent candles whose intervals touch the requested
            # half-open gap; unrelated out-of-range data remains an error.
            if stamp in (start_epoch - INTERVAL_SECONDS, end_epoch):
                continue
            raise RecorderError("REST gap check returned candle outside requested gap")
        if stamp in seen:
            raise RecorderError("REST gap check returned duplicate timestamps")
        if previous is not None and stamp < previous:
            raise RecorderError("REST gap check returned out-of-order candles")
        seen.add(stamp)
        previous = stamp
        candles.append(candle)
    unresolved = [
        datetime.fromtimestamp(stamp, timezone.utc).isoformat()
        for stamp in expected if stamp not in seen
    ]
    return {
        "requested_intervals": len(expected),
        "returned": [c.start_time.isoformat() for c in candles],
        "unresolved": unresolved, "valid": not unresolved,
    }


def verify_restart_integrity(path: str | Path) -> dict[str, Any]:
    """Reopen an existing log and prove initialization leaves its bytes unchanged."""
    target = Path(path)
    def fingerprint() -> tuple[int, str]:
        digest = hashlib.sha256()
        size = 0
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
        return size, digest.hexdigest()

    bytes_before, before_hash = fingerprint()
    recorder = AppendOnlyJsonlRecorder(target)
    bytes_after, after_hash = fingerprint()
    unchanged = bytes_before == bytes_after and before_hash == after_hash
    return {
        "path": str(target), "bytes_before": bytes_before, "bytes_after": bytes_after,
        "sha256_before": before_hash, "sha256_after": after_hash,
        "history_unchanged": unchanged,
        "latest_candle_start_utc": (
            recorder.latest_candle_start.isoformat() if recorder.latest_candle_start else None
        ),
        "status": "PASS" if unchanged else "FAIL",
    }
