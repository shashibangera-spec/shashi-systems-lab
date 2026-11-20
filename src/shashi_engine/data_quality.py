"""Deterministic data-quality checks; observations are reported, never silently repaired."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from .models import Candle


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    candle_count: int
    duplicate_starts: tuple[datetime, ...]
    out_of_order_pairs: tuple[tuple[datetime, datetime], ...]
    missing_intervals: int
    stale: bool
    future_data: bool
    age_at_check: timedelta | None

    @property
    def acceptable(self) -> bool:
        return (
            self.candle_count > 0
            and not self.duplicate_starts
            and not self.out_of_order_pairs
            and self.missing_intervals == 0
            and not self.stale
            and not self.future_data
        )


def inspect_candle_series(
    candles: Sequence[Candle],
    *,
    as_of: datetime,
    max_age: timedelta = timedelta(minutes=35),
) -> DataQualityReport:
    """Inspect input order, duplicates, gaps and freshness without sorting or filling."""
    if as_of.tzinfo is None or as_of.utcoffset() != timedelta(0):
        raise ValueError("as_of must be timezone-aware UTC")
    if max_age < timedelta(0):
        raise ValueError("max_age must not be negative")
    if not candles:
        return DataQualityReport(0, (), (), 0, True, False, None)

    starts = [candle.start_time for candle in candles]
    seen: set[datetime] = set()
    duplicates: list[datetime] = []
    for stamp in starts:
        if stamp in seen and stamp not in duplicates:
            duplicates.append(stamp)
        seen.add(stamp)

    out_of_order = tuple(
        (previous, current)
        for previous, current in zip(starts, starts[1:])
        if current < previous
    )

    ordered_unique = sorted(seen)
    missing = 0
    for previous, current in zip(ordered_unique, ordered_unique[1:]):
        elapsed = current - previous
        if elapsed.total_seconds() % 1800 != 0:
            # A non-grid interval is a quality defect, not rounded into a gap count.
            missing += 1
        else:
            missing += max(0, int(elapsed.total_seconds() // 1800) - 1)

    latest_end = max(candle.end_time for candle in candles)
    age = as_of - latest_end
    stale = age > max_age
    future_data = age < timedelta(0)
    return DataQualityReport(
        candle_count=len(candles),
        duplicate_starts=tuple(duplicates),
        out_of_order_pairs=out_of_order,
        missing_intervals=missing,
        stale=stale,
        future_data=future_data,
        age_at_check=age,
    )
