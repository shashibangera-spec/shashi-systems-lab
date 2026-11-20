"""Typed domain models for public market data.

These models intentionally contain no exchange credentials or order-submission logic.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Instrument:
    product_id: int
    symbol: str
    contract_type: str
    state: str
    trading_status: str
    contract_value: Decimal
    contract_value_asset: str
    tick_size: Decimal
    quote_asset: str
    settlement_asset: str
    funding_interval_seconds: int


@dataclass(frozen=True, slots=True)
class Ticker:
    symbol: str
    observed_at: datetime
    last_price: Decimal | None
    mark_price: Decimal | None
    best_bid: Decimal | None
    best_ask: Decimal | None


@dataclass(frozen=True, slots=True)
class FundingObservation:
    symbol: str
    observed_at: datetime
    funding_rate: Decimal
    next_funding_at: datetime | None
