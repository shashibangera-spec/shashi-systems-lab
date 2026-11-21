"""Mock-only Phase 1J execution safety model.

This module deliberately contains no HTTP client, websocket client, credentials,
exchange SDK, filesystem persistence, or order-submission adapter. It is a
deterministic in-process model for unit and acceptance testing only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from urllib.parse import urlsplit


DAILY_LOSS_LIMIT_USD = Decimal("2.50")
MAX_POSITION_LOTS = 2
TESTNET_ORIGIN = "https://testnet-api.delta.exchange"
PRODUCTION_HOST = "api.india.delta.exchange"


class SafetyError(RuntimeError):
    """Raised when a requested mock transition violates a safety invariant."""


class State(str, Enum):
    DISARMED = "DISARMED"
    PREFLIGHT = "PREFLIGHT"
    RECONCILING = "RECONCILING"
    READY = "READY"
    SIGNAL_PENDING = "SIGNAL_PENDING"
    ENTRY_WORKING = "ENTRY_WORKING"
    ENTRY_CANCEL_PENDING = "ENTRY_CANCEL_PENDING"
    POSITION_OPEN = "POSITION_OPEN"
    PARTIAL_EXIT_WORKING = "PARTIAL_EXIT_WORKING"
    RUNNER_ACTIVE = "RUNNER_ACTIVE"
    EXIT_PENDING = "EXIT_PENDING"
    FLAT_RECONCILIATION = "FLAT_RECONCILIATION"
    SESSION_LOCKED = "SESSION_LOCKED"
    SUBMISSION_UNKNOWN = "SUBMISSION_UNKNOWN"
    PROTECTION_FAULT = "PROTECTION_FAULT"
    RECONCILIATION_BLOCKED = "RECONCILIATION_BLOCKED"
    FAULT_LOCKED = "FAULT_LOCKED"


def validate_testnet_origin(url: str) -> bool:
    """Accept only the exact HTTPS Testnet origin; reject paths, ports and userinfo."""
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname == "testnet-api.delta.exchange"
            and parsed.port is None
            and parsed.username is None
            and parsed.password is None
            and parsed.path in ("", "/")
            and not parsed.query
            and not parsed.fragment
            and url.rstrip("/") == TESTNET_ORIGIN
        )
    except ValueError:
        return False


@dataclass(frozen=True)
class SessionPnl:
    realized_usd: Decimal | None
    unrealized_usd: Decimal | None
    fees_usd: Decimal | None
    funding_usd: Decimal | None

    def net_usd(self) -> Decimal | None:
        values = (self.realized_usd, self.unrealized_usd, self.fees_usd, self.funding_usd)
        if any(value is None or not value.is_finite() for value in values):
            return None
        assert self.realized_usd is not None
        assert self.unrealized_usd is not None
        assert self.fees_usd is not None
        assert self.funding_usd is not None
        return self.realized_usd + self.unrealized_usd - self.fees_usd + self.funding_usd


@dataclass
class DailyLossLatch:
    """In-memory mock of a persistent session latch; not production persistence."""
    session_id: str
    limit_usd: Decimal = DAILY_LOSS_LIMIT_USD
    latched: bool = False
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("session_id is required")
        if not self.limit_usd.is_finite() or self.limit_usd <= 0:
            raise ValueError("limit_usd must be a positive finite Decimal")
        if self.limit_usd != DAILY_LOSS_LIMIT_USD:
            raise ValueError("Phase 1J approved daily loss limit is fixed at USD 2.50")

    def evaluate(self, pnl: SessionPnl) -> bool:
        net = pnl.net_usd()
        if net is None:
            self.latched = True
            self.reason = "P_AND_L_COMPONENT_MISSING_OR_INVALID"
        elif net <= -self.limit_usd:
            self.latched = True
            self.reason = "DAILY_LOSS_LIMIT_REACHED"
        return self.latched


@dataclass(frozen=True)
class Exposure:
    filled_position_lots: int
    live_entry_lots: int

    @property
    def potential_lots(self) -> int:
        return self.filled_position_lots + self.live_entry_lots

    def permits(self, additional_entry_lots: int = 0) -> bool:
        return (
            self.filled_position_lots >= 0
            and self.live_entry_lots >= 0
            and additional_entry_lots >= 0
            and self.potential_lots + additional_entry_lots <= MAX_POSITION_LOTS
        )


@dataclass
class IntentRegistry:
    """In-memory deterministic-intent guard used only by mocks."""
    seen: set[str] = field(default_factory=set)

    def register(self, intent_id: str) -> bool:
        if not intent_id or intent_id in self.seen:
            return False
        self.seen.add(intent_id)
        return True


@dataclass(frozen=True)
class Reconciliation:
    environment_verified: bool
    product_verified: bool
    local_position_lots: int
    exchange_position_lots: int
    local_open_order_ids: frozenset[str]
    exchange_open_order_ids: frozenset[str]
    fills_complete: bool
    audit_complete: bool
    exchange_live_entry_lots: int = 0

    @property
    def clean(self) -> bool:
        return (
            self.environment_verified
            and self.product_verified
            and self.local_position_lots == self.exchange_position_lots
            and self.local_open_order_ids == self.exchange_open_order_ids
            and self.fills_complete
            and self.audit_complete
            and self.exchange_position_lots >= 0
            and self.exchange_live_entry_lots >= 0
            and self.exchange_position_lots + self.exchange_live_entry_lots <= MAX_POSITION_LOTS
        )


_ALLOWED: dict[State, frozenset[State]] = {
    State.DISARMED: frozenset({State.PREFLIGHT}),
    State.PREFLIGHT: frozenset({State.RECONCILING, State.FAULT_LOCKED}),
    State.RECONCILING: frozenset({State.READY, State.RECONCILIATION_BLOCKED}),
    State.READY: frozenset({State.SIGNAL_PENDING, State.SESSION_LOCKED, State.FAULT_LOCKED}),
    State.SIGNAL_PENDING: frozenset({State.ENTRY_WORKING, State.READY, State.FAULT_LOCKED}),
    State.ENTRY_WORKING: frozenset({State.POSITION_OPEN, State.ENTRY_CANCEL_PENDING, State.SUBMISSION_UNKNOWN, State.FAULT_LOCKED}),
    State.ENTRY_CANCEL_PENDING: frozenset({State.READY, State.POSITION_OPEN, State.SUBMISSION_UNKNOWN, State.FAULT_LOCKED}),
    State.POSITION_OPEN: frozenset({State.PARTIAL_EXIT_WORKING, State.PROTECTION_FAULT, State.EXIT_PENDING}),
    State.PARTIAL_EXIT_WORKING: frozenset({State.RUNNER_ACTIVE, State.POSITION_OPEN, State.SUBMISSION_UNKNOWN, State.FAULT_LOCKED}),
    State.RUNNER_ACTIVE: frozenset({State.EXIT_PENDING, State.PROTECTION_FAULT, State.FAULT_LOCKED}),
    State.EXIT_PENDING: frozenset({State.FLAT_RECONCILIATION, State.POSITION_OPEN, State.SUBMISSION_UNKNOWN}),
    State.FLAT_RECONCILIATION: frozenset({State.READY, State.SESSION_LOCKED, State.RECONCILIATION_BLOCKED}),
    State.SESSION_LOCKED: frozenset({State.RECONCILING}),
    State.SUBMISSION_UNKNOWN: frozenset({State.RECONCILING}),
    State.PROTECTION_FAULT: frozenset({State.FAULT_LOCKED, State.RECONCILIATION_BLOCKED}),
    State.RECONCILIATION_BLOCKED: frozenset({State.RECONCILING}),
    State.FAULT_LOCKED: frozenset({State.PREFLIGHT, State.RECONCILING}),
}


@dataclass
class MockExecutionMachine:
    """State-only model. It cannot communicate with an exchange."""
    state: State = State.DISARMED
    loss_latch: DailyLossLatch | None = None
    intents: IntentRegistry = field(default_factory=IntentRegistry)

    def transition(self, target: State) -> None:
        if self.state in {State.ENTRY_WORKING, State.ENTRY_CANCEL_PENDING} and target is State.POSITION_OPEN:
            raise SafetyError("entry fills require confirm_entry_fill() with verified protection")
        if target not in _ALLOWED.get(self.state, frozenset()):
            raise SafetyError(f"illegal transition: {self.state.value} -> {target.value}")
        self.state = target

    def confirm_entry_fill(self, protective_coverage_confirmed: bool) -> None:
        if self.state not in {State.ENTRY_WORKING, State.ENTRY_CANCEL_PENDING}:
            raise SafetyError("entry fill confirmation requires a working entry")
        self.state = State.POSITION_OPEN if protective_coverage_confirmed else State.PROTECTION_FAULT

    def preflight(self, origin: str, risk_store_writable: bool, audit_writable: bool) -> None:
        if self.state is not State.DISARMED:
            raise SafetyError("preflight is allowed only from DISARMED")
        self.transition(State.PREFLIGHT)
        if not validate_testnet_origin(origin) or not risk_store_writable or not audit_writable:
            self.transition(State.FAULT_LOCKED)
            return
        self.transition(State.RECONCILING)

    def reconcile(self, evidence: Reconciliation) -> None:
        if self.state is not State.RECONCILING:
            raise SafetyError("reconciliation requires RECONCILING state")
        self.transition(State.READY if evidence.clean else State.RECONCILIATION_BLOCKED)

    def permit_entry(
        self,
        intent_id: str,
        exposure: Exposure,
        pnl: SessionPnl,
        data_fresh: bool,
        protective_system_ready: bool,
    ) -> bool:
        if self.state is not State.READY or self.loss_latch is None:
            return False
        if self.loss_latch.evaluate(pnl):
            self.transition(State.SESSION_LOCKED)
            return False
        if (
            not exposure.permits(2)
            or not data_fresh
            or not protective_system_ready
            or not self.intents.register(intent_id)
        ):
            return False
        self.transition(State.SIGNAL_PENDING)
        return True

    def mark_submission_unknown(self) -> None:
        self.transition(State.SUBMISSION_UNKNOWN)

    def apply_global_kill(self, reason: str) -> None:
        if self.state not in {State.SESSION_LOCKED, State.FAULT_LOCKED}:
            self.state = State.SESSION_LOCKED if reason == "DAILY_LOSS_LIMIT_REACHED" else State.FAULT_LOCKED
