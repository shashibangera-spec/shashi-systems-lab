"""Pure, non-executing BTCUSD scenario accounting.

This module performs deterministic Decimal calculations only. It has no network,
filesystem, account, persistence, order, margin, or execution integrations.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import Literal

from .models import Instrument
from .risk_controls import RiskContext, RiskDecision, RiskGate, RiskIntent

PositionSide = Literal["long", "short"]
Liquidity = Literal["maker", "taker"]
FxStatus = Literal["verified", "synthetic"]


def _finite(value: Decimal, field: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field} must be a finite Decimal")


def _positive(value: Decimal, field: str) -> None:
    _finite(value, field)
    if value <= 0:
        raise ValueError(f"{field} must be positive")


def _utc(value: datetime, field: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must be timezone-aware UTC")


@dataclass(frozen=True, slots=True)
class FxObservation:
    base: str
    quote: str
    rate: Decimal
    observed_at: datetime
    source: str
    status: FxStatus

    def __post_init__(self) -> None:
        if self.base != "USD" or self.quote != "INR":
            raise ValueError("FX pair must be USD/INR")
        _positive(self.rate, "FX rate")
        _utc(self.observed_at, "FX observed_at")
        if not self.source.strip():
            raise ValueError("FX source/provenance is required")
        if self.status not in ("verified", "synthetic"):
            raise ValueError("FX status must be verified or synthetic")


@dataclass(frozen=True, slots=True)
class FeeSchedule:
    maker_rate: Decimal
    taker_rate: Decimal
    gst_rate: Decimal
    settlement_fee_rate: Decimal | None = None

    def __post_init__(self) -> None:
        for name in ("maker_rate", "taker_rate", "gst_rate"):
            value = getattr(self, name)
            _finite(value, name)
            if value < 0:
                raise ValueError(f"{name} must not be negative")
        if self.settlement_fee_rate is not None:
            _finite(self.settlement_fee_rate, "settlement_fee_rate")
            if self.settlement_fee_rate < 0:
                raise ValueError("settlement_fee_rate must not be negative")


@dataclass(frozen=True, slots=True)
class AccountingPolicy:
    max_fx_age: timedelta
    reporting_decimal_places: int = 2
    rounding: str = ROUND_HALF_UP
    fee_currency_assumption: str = "USD"
    gst_currency_assumption: str = "USD"

    def __post_init__(self) -> None:
        if self.max_fx_age < timedelta(0):
            raise ValueError("max_fx_age must be explicitly configured and non-negative")
        if self.reporting_decimal_places < 0 or self.reporting_decimal_places > 12:
            raise ValueError("reporting_decimal_places must be between 0 and 12")
        if self.rounding != ROUND_HALF_UP:
            raise ValueError("only explicitly supported ROUND_HALF_UP reporting is currently supported")
        if self.fee_currency_assumption != "USD" or self.gst_currency_assumption != "USD":
            raise ValueError("Phase 1E fee and GST scenario denomination must be explicitly USD")


@dataclass(frozen=True, slots=True)
class FundingEvent:
    rate: Decimal
    position_side: PositionSide
    lots: int
    mark_price: Decimal
    event_at: datetime
    interval_seconds: int

    def __post_init__(self) -> None:
        _finite(self.rate, "funding rate")
        if self.position_side not in ("long", "short"):
            raise ValueError("position_side must be long or short")
        if not isinstance(self.lots, int) or isinstance(self.lots, bool) or self.lots <= 0:
            raise ValueError("funding lots must be a positive whole number")
        _positive(self.mark_price, "mark_price")
        _utc(self.event_at, "funding event_at")
        if self.interval_seconds <= 0:
            raise ValueError("funding interval_seconds must be positive")


@dataclass(frozen=True, slots=True)
class AccountingScenario:
    instrument: Instrument
    lots: int
    position_side: PositionSide
    entry_price: Decimal
    entry_liquidity: Liquidity
    entry_at: datetime
    fee_schedule: FeeSchedule
    policy: AccountingPolicy
    as_of: datetime
    exit_price: Decimal | None = None
    exit_liquidity: Liquidity | None = None
    exit_at: datetime | None = None
    held_through_settlement: bool = False
    settlement_notional_usd: Decimal | None = None
    funding_events: tuple[FundingEvent, ...] = ()
    fx_observation: FxObservation | None = None

    def __post_init__(self) -> None:
        if self.instrument.contract_type != "perpetual_futures":
            raise ValueError("only perpetual_futures instruments are supported")
        if self.instrument.quote_asset != "USD":
            raise ValueError("Phase 1E scenario requires USD-quoted contract")
        if self.instrument.contract_value_asset != "BTC":
            raise ValueError("contract value asset must be BTC")
        if not isinstance(self.lots, int) or isinstance(self.lots, bool) or self.lots < self.instrument.minimum_order_lots:
            raise ValueError("lots must be a whole number at or above contract minimum")
        if self.position_side not in ("long", "short"):
            raise ValueError("position_side must be long or short")
        if self.entry_liquidity not in ("maker", "taker"):
            raise ValueError("entry_liquidity must be maker or taker")
        _positive(self.entry_price, "entry_price")
        _utc(self.entry_at, "entry_at")
        _utc(self.as_of, "as_of")
        if self.entry_at > self.as_of:
            raise ValueError("entry_at cannot be in the future")
        if self.exit_price is None:
            if self.exit_liquidity is not None or self.exit_at is not None:
                raise ValueError("exit liquidity/time require an exit price")
        else:
            _positive(self.exit_price, "exit_price")
            if self.exit_liquidity not in ("maker", "taker") or self.exit_at is None:
                raise ValueError("exit price requires exit liquidity and timestamp")
            _utc(self.exit_at, "exit_at")
            if self.exit_at < self.entry_at or self.exit_at > self.as_of:
                raise ValueError("exit_at must be between entry_at and as_of")
        if self.held_through_settlement:
            if self.settlement_notional_usd is None:
                raise ValueError("settlement notional is required when held through settlement")
            _positive(self.settlement_notional_usd, "settlement_notional_usd")
            if self.fee_schedule.settlement_fee_rate is None:
                raise ValueError("settlement fee rate is required when held through settlement")
        elif self.settlement_notional_usd is not None:
            raise ValueError("settlement notional supplied but scenario is not held through settlement")
        for event in self.funding_events:
            if event.interval_seconds != self.instrument.funding_interval_seconds:
                raise ValueError("funding interval must match contract metadata")
            if event.event_at > self.as_of:
                raise ValueError("funding event cannot be in the future")


@dataclass(frozen=True, slots=True)
class AccountingBreakdown:
    currency: str
    lots: int
    btc_quantity: Decimal
    entry_notional_usd: Decimal
    exit_notional_usd: Decimal | None
    entry_fee_usd: Decimal
    entry_gst_usd: Decimal
    exit_fee_usd: Decimal
    exit_gst_usd: Decimal
    settlement_fee_usd: Decimal
    funding_cashflow_usd: Decimal
    gross_scenario_pnl_usd: Decimal | None
    net_scenario_result_usd: Decimal | None
    inr_equivalents: dict[str, Decimal] | None
    fx_status: str | None
    fx_source: str | None
    fx_observed_at: datetime | None
    exchange_reconciled: bool
    warnings: tuple[str, ...]


def _fee(notional: Decimal, liquidity: Liquidity, schedule: FeeSchedule) -> tuple[Decimal, Decimal]:
    rate = schedule.maker_rate if liquidity == "maker" else schedule.taker_rate
    amount = notional * rate
    return amount, amount * schedule.gst_rate


def _inr_view(
    amounts: dict[str, Decimal], observation: FxObservation | None,
    policy: AccountingPolicy, as_of: datetime,
) -> tuple[dict[str, Decimal] | None, str | None, str | None, datetime | None]:
    if observation is None:
        return None, None, None, None
    age = as_of - observation.observed_at
    if age < timedelta(0) or age > policy.max_fx_age:
        return None, None, None, None
    converted = {key: value * observation.rate for key, value in amounts.items()}
    return converted, observation.status, observation.source, observation.observed_at


def _calculation_precision(scenario: AccountingScenario) -> int:
    """Choose enough Decimal context precision for all finite products and sums."""
    values = [
        scenario.instrument.contract_value, scenario.entry_price,
        scenario.fee_schedule.maker_rate, scenario.fee_schedule.taker_rate,
        scenario.fee_schedule.gst_rate,
    ]
    if scenario.exit_price is not None:
        values.append(scenario.exit_price)
    if scenario.settlement_notional_usd is not None:
        values.append(scenario.settlement_notional_usd)
    if scenario.fee_schedule.settlement_fee_rate is not None:
        values.append(scenario.fee_schedule.settlement_fee_rate)
    if scenario.fx_observation is not None:
        values.append(scenario.fx_observation.rate)
    for event in scenario.funding_events:
        values.extend((event.rate, event.mark_price, scenario.instrument.contract_value))
    return max(50, sum(len(value.as_tuple().digits) for value in values) + len(scenario.funding_events) + 20)


def calculate_accounting(scenario: AccountingScenario) -> AccountingBreakdown:
    """Calculate a synthetic scenario; never contacts an exchange or account."""
    instrument = scenario.instrument
    with localcontext() as ctx:
        ctx.prec = max(ctx.prec, _calculation_precision(scenario))
        btc_qty = Decimal(scenario.lots) * instrument.contract_value
        entry_notional = btc_qty * scenario.entry_price
        entry_fee, entry_gst = _fee(entry_notional, scenario.entry_liquidity, scenario.fee_schedule)

        exit_notional: Decimal | None = None
        exit_fee = Decimal("0")
        exit_gst = Decimal("0")
        gross_pnl: Decimal | None = None
        if scenario.exit_price is not None:
            exit_notional = btc_qty * scenario.exit_price
            assert scenario.exit_liquidity is not None
            exit_fee, exit_gst = _fee(exit_notional, scenario.exit_liquidity, scenario.fee_schedule)
            price_delta = scenario.exit_price - scenario.entry_price
            gross_pnl = btc_qty * price_delta
            if scenario.position_side == "short":
                gross_pnl = -gross_pnl

        settlement_fee = Decimal("0")
        if scenario.held_through_settlement:
            assert scenario.settlement_notional_usd is not None
            assert scenario.fee_schedule.settlement_fee_rate is not None
            settlement_fee = scenario.settlement_notional_usd * scenario.fee_schedule.settlement_fee_rate

        funding_cashflow = Decimal("0")
        for event in scenario.funding_events:
            mark_notional = Decimal(event.lots) * instrument.contract_value * event.mark_price
            long_cashflow = -(mark_notional * event.rate)
            funding_cashflow += long_cashflow if event.position_side == "long" else -long_cashflow

        total_fees = entry_fee + entry_gst + exit_fee + exit_gst + settlement_fee
        net_result = None if gross_pnl is None else gross_pnl - total_fees + funding_cashflow
        usd_components = {
            "entry_fee": entry_fee, "entry_gst": entry_gst,
            "exit_fee": exit_fee, "exit_gst": exit_gst,
            "settlement_fee": settlement_fee, "funding_cashflow": funding_cashflow,
            "entry_notional": entry_notional,
        }
        if exit_notional is not None:
            usd_components["exit_notional"] = exit_notional
        if gross_pnl is not None:
            usd_components["gross_scenario_pnl"] = gross_pnl
        if net_result is not None:
            usd_components["net_scenario_result"] = net_result
        inr, fx_status, fx_source, fx_at = _inr_view(
            usd_components, scenario.fx_observation, scenario.policy, scenario.as_of
        )
        warnings = [
            "Scenario estimates only; not exchange-reconciled account PnL.",
            "Fee/GST denomination and exchange rounding remain explicit USD scenario assumptions.",
            "No margin, liquidation, collateral, tax, or execution calculation is performed.",
        ]
        if inr is None:
            warnings.append("INR equivalents omitted: no valid, fresh explicit USD/INR observation.")
        elif fx_status == "synthetic":
            warnings.append("INR equivalents use a synthetic FX observation; not a live conversion.")
        return AccountingBreakdown(
            currency="USD", lots=scenario.lots, btc_quantity=btc_qty,
            entry_notional_usd=entry_notional, exit_notional_usd=exit_notional,
            entry_fee_usd=entry_fee, entry_gst_usd=entry_gst,
            exit_fee_usd=exit_fee, exit_gst_usd=exit_gst,
            settlement_fee_usd=settlement_fee, funding_cashflow_usd=funding_cashflow,
            gross_scenario_pnl_usd=gross_pnl, net_scenario_result_usd=net_result,
            inr_equivalents=inr, fx_status=fx_status, fx_source=fx_source,
            fx_observed_at=fx_at, exchange_reconciled=False, warnings=tuple(warnings),
        )


def reporting_amount(value: Decimal, policy: AccountingPolicy) -> Decimal:
    """Round only when producing a reporting/ledger boundary value."""
    _finite(value, "reporting value")
    quantum = Decimal(1).scaleb(-policy.reporting_decimal_places)
    with localcontext() as ctx:
        ctx.prec = max(ctx.prec, len(value.as_tuple().digits) + policy.reporting_decimal_places + 4)
        return value.quantize(quantum, rounding=policy.rounding)


def evaluate_usd_risk_gate(
    gate: RiskGate, intent: RiskIntent, context: RiskContext,
) -> RiskDecision:
    """Call the existing gate only when every monetary input is explicitly USD."""
    if intent.currency != "USD" or context.currency != "USD":
        raise ValueError("Phase 1E RiskGate integration is USD-only")
    return gate.evaluate(intent, context)
