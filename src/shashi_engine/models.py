"""Immutable, validated domain models for read-only market data."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal


def _require_utc(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must be expressed in UTC")


def _require_positive(value: Decimal, field: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise ValueError(f"{field} must be a positive finite Decimal")


def _require_finite(value: Decimal, field: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field} must be a finite Decimal")


def is_increment_aligned(value: Decimal, increment: Decimal) -> bool:
    """Return whether a finite Decimal is an exact multiple of a positive increment."""
    _require_finite(value, "value")
    _require_positive(increment, "increment")
    return value % increment == 0


@dataclass(frozen=True, slots=True)
class Instrument:
    """Contract metadata; API settlement and documented margin fields stay distinct."""

    product_id: int
    symbol: str
    contract_type: str
    state: str
    trading_status: str
    contract_value: Decimal
    contract_value_asset: str
    tick_size: Decimal
    quote_asset: str
    api_settlement_asset: str
    funding_interval_seconds: int
    minimum_order_lots: int = 1
    documented_margin_currency: str | None = None
    documented_effective_settlement_currency: str | None = None

    def __post_init__(self) -> None:
        if self.product_id <= 0 or not self.symbol.strip():
            raise ValueError("instrument identity must be valid")
        _require_positive(self.contract_value, "contract_value")
        _require_positive(self.tick_size, "tick_size")
        if self.funding_interval_seconds <= 0:
            raise ValueError("funding_interval_seconds must be positive")
        if self.minimum_order_lots <= 0:
            raise ValueError("minimum_order_lots must be positive")
        for field in ("contract_value_asset", "quote_asset", "api_settlement_asset"):
            if not getattr(self, field).strip():
                raise ValueError(f"{field} must not be empty")


@dataclass(frozen=True, slots=True)
class Ticker:
    symbol: str
    observed_at: datetime
    last_price: Decimal | None
    mark_price: Decimal | None
    best_bid: Decimal | None
    best_ask: Decimal | None

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol must not be empty")
        _require_utc(self.observed_at, "observed_at")
        for field in ("last_price", "mark_price", "best_bid", "best_ask"):
            value = getattr(self, field)
            if value is not None:
                _require_positive(value, field)
        if self.best_bid is not None and self.best_ask is not None:
            if self.best_bid > self.best_ask:
                raise ValueError("best_bid must not exceed best_ask")


@dataclass(frozen=True, slots=True)
class FundingObservation:
    symbol: str
    observed_at: datetime
    funding_rate: Decimal
    next_funding_at: datetime | None

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol must not be empty")
        _require_utc(self.observed_at, "observed_at")
        _require_finite(self.funding_rate, "funding_rate")
        if self.next_funding_at is not None:
            _require_utc(self.next_funding_at, "next_funding_at")


@dataclass(frozen=True, slots=True)
class Candle:
    """A UTC 30-minute OHLCV interval; start_time is not the publish timestamp."""

    symbol: str
    resolution: str
    start_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol must not be empty")
        if self.resolution != "30m":
            raise ValueError("only 30m candles are supported in Phase 1C")
        _require_utc(self.start_time, "start_time")
        if self.start_time.minute not in (0, 30) or self.start_time.second or self.start_time.microsecond:
            raise ValueError("30m candle start_time must align to a UTC half-hour boundary")
        for field in ("open", "high", "low", "close"):
            _require_positive(getattr(self, field), field)
        _require_finite(self.volume, "volume")
        if self.volume < 0:
            raise ValueError("volume must not be negative")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high must be >= open, close and low")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low must be <= open, close and high")

    @property
    def end_time(self) -> datetime:
        return self.start_time + timedelta(minutes=30)
