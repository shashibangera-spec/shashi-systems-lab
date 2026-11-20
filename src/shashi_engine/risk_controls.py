"""Pure, non-executing risk checks for proposed trade intents.

No exchange client, order route, account access, persistence, or sizing logic.
All monetary inputs must already use the policy's explicitly selected currency.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from threading import Lock


def _utc(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must be timezone-aware UTC")


def _positive(value: Decimal, field: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise ValueError(f"{field} must be a positive finite Decimal")


def _finite(value: Decimal, field: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field} must be a finite Decimal")


@dataclass(frozen=True, slots=True)
class RiskPolicy:
    """Hard limits in one explicitly declared accounting currency."""

    currency: str
    max_total_exposure: Decimal
    max_single_trade_loss: Decimal
    max_daily_loss: Decimal
    max_intent_age: timedelta = timedelta(seconds=30)

    def __post_init__(self) -> None:
        if not self.currency.strip():
            raise ValueError("currency must not be empty")
        _positive(self.max_total_exposure, "max_total_exposure")
        _positive(self.max_single_trade_loss, "max_single_trade_loss")
        _positive(self.max_daily_loss, "max_daily_loss")
        if self.max_intent_age < timedelta(0):
            raise ValueError("max_intent_age must not be negative")


@dataclass(frozen=True, slots=True)
class RiskContext:
    """Caller-supplied, same-currency state; no account data is fetched."""

    currency: str
    current_exposure: Decimal
    daily_net_pnl: Decimal
    as_of: datetime
    kill_switch_active: bool = False

    def __post_init__(self) -> None:
        if not self.currency.strip():
            raise ValueError("currency must not be empty")
        _finite(self.current_exposure, "current_exposure")
        _finite(self.daily_net_pnl, "daily_net_pnl")
        if self.current_exposure < 0:
            raise ValueError("current_exposure must not be negative")
        _utc(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class RiskIntent:
    """A proposed intent description only; it is not an exchange order."""

    intent_id: str
    currency: str
    proposed_notional: Decimal
    worst_case_loss: Decimal
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.intent_id.strip():
            raise ValueError("intent_id must not be empty")
        if not self.currency.strip():
            raise ValueError("currency must not be empty")
        _positive(self.proposed_notional, "proposed_notional")
        _finite(self.worst_case_loss, "worst_case_loss")
        if self.worst_case_loss < 0:
            raise ValueError("worst_case_loss must not be negative")
        _utc(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class RiskDecision:
    approved: bool
    reason_code: str
    intent_id: str


class RiskGate:
    """Deterministic process-local gate. First evaluation consumes an intent ID."""

    def __init__(self, policy: RiskPolicy) -> None:
        self._policy = policy
        self._seen_intent_ids: set[str] = set()
        self._lock = Lock()

    def evaluate(self, intent: RiskIntent, context: RiskContext) -> RiskDecision:
        """Evaluate once and remember the ID, including when the intent is rejected."""
        with self._lock:
            if intent.intent_id in self._seen_intent_ids:
                return RiskDecision(False, "DUPLICATE_INTENT", intent.intent_id)
            self._seen_intent_ids.add(intent.intent_id)

        if intent.currency != self._policy.currency or context.currency != self._policy.currency:
            return RiskDecision(False, "CURRENCY_MISMATCH", intent.intent_id)
        if context.kill_switch_active:
            return RiskDecision(False, "KILL_SWITCH_ACTIVE", intent.intent_id)
        age = context.as_of - intent.created_at
        if age < timedelta(0) or age > self._policy.max_intent_age:
            return RiskDecision(False, "STALE_OR_FUTURE_INTENT", intent.intent_id)
        if context.daily_net_pnl <= -self._policy.max_daily_loss:
            return RiskDecision(False, "DAILY_LOSS_LIMIT_REACHED", intent.intent_id)
        if intent.worst_case_loss > self._policy.max_single_trade_loss:
            return RiskDecision(False, "SINGLE_TRADE_RISK_EXCEEDED", intent.intent_id)
        if context.current_exposure + intent.proposed_notional > self._policy.max_total_exposure:
            return RiskDecision(False, "MAX_TOTAL_EXPOSURE_EXCEEDED", intent.intent_id)
        return RiskDecision(True, "APPROVED_FOR_RESEARCH_ONLY", intent.intent_id)
