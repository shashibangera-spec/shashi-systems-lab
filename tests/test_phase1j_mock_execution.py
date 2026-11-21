from decimal import Decimal

import pytest

from shashi_engine.phase1j_mock_execution import (
    DAILY_LOSS_LIMIT_USD,
    DailyLossLatch,
    Exposure,
    MockExecutionMachine,
    Reconciliation,
    SafetyError,
    SessionPnl,
    State,
    validate_testnet_origin,
)


def pnl(realized="0", unrealized="0", fees="0", funding="0"):
    return SessionPnl(
        Decimal(realized) if realized is not None else None,
        Decimal(unrealized) if unrealized is not None else None,
        Decimal(fees) if fees is not None else None,
        Decimal(funding) if funding is not None else None,
    )


def clean_reconciliation(**overrides):
    values = {
        "environment_verified": True,
        "product_verified": True,
        "local_position_lots": 0,
        "exchange_position_lots": 0,
        "local_open_order_ids": frozenset(),
        "exchange_open_order_ids": frozenset(),
        "fills_complete": True,
        "audit_complete": True,
    }
    values.update(overrides)
    return Reconciliation(**values)


def ready_machine():
    machine = MockExecutionMachine(loss_latch=DailyLossLatch("2026-11-22"))
    machine.preflight("https://testnet-api.delta.exchange", True, True)
    machine.reconcile(clean_reconciliation())
    assert machine.state is State.READY
    return machine


def test_daily_loss_limit_is_exactly_approved_amount():
    assert DAILY_LOSS_LIMIT_USD == Decimal("2.50")


@pytest.mark.parametrize(
    "url",
    [
        "https://testnet-api.delta.exchange",
        "https://testnet-api.delta.exchange/",
    ],
)
def test_exact_testnet_origin_is_accepted(url):
    assert validate_testnet_origin(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://api.india.delta.exchange",
        "http://testnet-api.delta.exchange",
        "https://testnet-api.delta.exchange.evil.test",
        "https://testnet-api.delta.exchange@evil.test",
        "https://evil.test/testnet-api.delta.exchange",
        "https://testnet-api.delta.exchange:443",
        "https://testnet-api.delta.exchange/path",
        "https://testnet-api.delta.exchange/?redirect=prod",
        "https://testnet-api.delta.exchange/#fragment",
        "https://user:pass@testnet-api.delta.exchange",
        "https://TESTNET-api.delta.exchange",
        "not a url",
    ],
)
def test_non_exact_or_ambiguous_origins_are_rejected(url):
    assert not validate_testnet_origin(url)


def test_preflight_fails_closed_for_production_host():
    machine = MockExecutionMachine()
    machine.preflight("https://api.india.delta.exchange", True, True)
    assert machine.state is State.FAULT_LOCKED


@pytest.mark.parametrize(
    "writable",
    [(False, True), (True, False), (False, False)],
)
def test_preflight_requires_both_risk_and_audit_stores(writable):
    machine = MockExecutionMachine()
    machine.preflight("https://testnet-api.delta.exchange", *writable)
    assert machine.state is State.FAULT_LOCKED


def test_reconciliation_mismatch_blocks_ready_state():
    machine = MockExecutionMachine()
    machine.preflight("https://testnet-api.delta.exchange", True, True)
    machine.reconcile(clean_reconciliation(exchange_position_lots=1))
    assert machine.state is State.RECONCILIATION_BLOCKED


def test_reconciliation_requires_order_fill_and_audit_agreement():
    machine = MockExecutionMachine()
    machine.preflight("https://testnet-api.delta.exchange", True, True)
    evidence = clean_reconciliation(
        local_open_order_ids=frozenset({"local"}),
        exchange_open_order_ids=frozenset({"exchange"}),
        fills_complete=False,
        audit_complete=False,
    )
    machine.reconcile(evidence)
    assert machine.state is State.RECONCILIATION_BLOCKED


def test_daily_loss_triggers_at_exactly_2_50_including_all_components():
    latch = DailyLossLatch("session-1")
    # 0.50 realized + 1.00 unrealized - 0.25 fees - 2.75 funding = -1.50
    assert not latch.evaluate(pnl("0.50", "1.00", "0.25", "-2.75"))
    assert latch.evaluate(pnl("-1.00", "-1.00", "0.50", "0"))
    assert latch.reason == "DAILY_LOSS_LIMIT_REACHED"


def test_daily_loss_below_threshold_does_not_trigger():
    latch = DailyLossLatch("session-1")
    assert not latch.evaluate(pnl("-1.00", "-1.00", "0.49", "0"))


def test_daily_loss_latch_survives_recovery_in_same_mock_instance():
    latch = DailyLossLatch("session-1")
    assert latch.evaluate(pnl("-2.50", "0", "0", "0"))
    assert latch.evaluate(pnl("100", "0", "0", "0"))
    assert latch.latched


@pytest.mark.parametrize(
    "incomplete",
    [
        pnl(None, "0", "0", "0"),
        pnl("0", None, "0", "0"),
        pnl("0", "0", None, "0"),
        pnl("0", "0", "0", None),
    ],
)
def test_missing_pnl_component_latches_fail_closed(incomplete):
    latch = DailyLossLatch("session-1")
    assert latch.evaluate(incomplete)
    assert latch.reason == "P_AND_L_COMPONENT_MISSING_OR_INVALID"


@pytest.mark.parametrize("value", ["0", "-0.01", "2.51", "NaN"])
def test_limit_cannot_be_disabled_or_changed(value):
    with pytest.raises(ValueError):
        DailyLossLatch("session-1", Decimal(value))


@pytest.mark.parametrize(
    ("filled", "working", "additional", "expected"),
    [
        (0, 0, 2, True),
        (1, 0, 1, True),
        (1, 1, 1, False),
        (2, 0, 1, False),
        (0, 3, 0, False),
        (-1, 0, 0, False),
    ],
)
def test_two_lot_cap_counts_filled_plus_working_entry_orders(filled, working, additional, expected):
    assert Exposure(filled, working).permits(additional) is expected


def test_mock_entry_requires_clean_gates_and_unique_intent():
    machine = ready_machine()
    assert machine.permit_entry(
        "signal-1", Exposure(0, 0), pnl(), True, True
    )
    assert machine.state is State.SIGNAL_PENDING


@pytest.mark.parametrize(
    "kwargs",
    [
        {"exposure": Exposure(1, 0)},
        {"data_fresh": False},
        {"protective_system_ready": False},
    ],
)
def test_entry_guardrails_reject_unsafe_conditions(kwargs):
    machine = ready_machine()
    args = {
        "intent_id": "signal-1",
        "exposure": Exposure(0, 0),
        "pnl": pnl(),
        "data_fresh": True,
        "protective_system_ready": True,
    }
    args.update(kwargs)
    assert not machine.permit_entry(**args)
    assert machine.state is State.READY


def test_daily_loss_blocks_entry_and_locks_session():
    machine = ready_machine()
    assert not machine.permit_entry(
        "signal-1", Exposure(0, 0), pnl("-2.50"), True, True
    )
    assert machine.state is State.SESSION_LOCKED


def test_duplicate_intent_cannot_be_reused():
    machine = ready_machine()
    args = {
        "exposure": Exposure(0, 0),
        "pnl": pnl(),
        "data_fresh": True,
        "protective_system_ready": True,
    }
    assert machine.permit_entry("same-signal", **args)
    machine.transition(State.ENTRY_WORKING)
    machine.confirm_entry_fill(protective_coverage_confirmed=True)
    machine.transition(State.EXIT_PENDING)
    machine.transition(State.FLAT_RECONCILIATION)
    machine.transition(State.READY)
    assert not machine.permit_entry("same-signal", **args)


def test_unknown_submission_outcome_transitions_to_reconciliation_only():
    machine = ready_machine()
    assert machine.permit_entry("unknown-submit", Exposure(0, 0), pnl(), True, True)
    machine.transition(State.ENTRY_WORKING)
    machine.mark_submission_unknown()
    assert machine.state is State.SUBMISSION_UNKNOWN
    with pytest.raises(SafetyError):
        machine.transition(State.READY)
    machine.transition(State.RECONCILING)


def test_illegal_state_transition_is_rejected():
    machine = MockExecutionMachine()
    with pytest.raises(SafetyError):
        machine.transition(State.ENTRY_WORKING)


def test_mock_module_has_no_exchange_adapter_surface():
    import shashi_engine.phase1j_mock_execution as module

    assert not hasattr(module, "requests")
    assert not hasattr(module, "httpx")
    assert not hasattr(module, "websocket")
    assert not hasattr(module, "submit_order")



def test_entry_fill_without_confirmed_protection_enters_protection_fault():
    machine = ready_machine()
    machine.transition(State.SIGNAL_PENDING)
    machine.transition(State.ENTRY_WORKING)
    machine.confirm_entry_fill(protective_coverage_confirmed=False)
    assert machine.state is State.PROTECTION_FAULT


def test_entry_fill_cannot_bypass_protection_confirmation():
    machine = ready_machine()
    machine.transition(State.SIGNAL_PENDING)
    machine.transition(State.ENTRY_WORKING)
    with pytest.raises(SafetyError, match="verified protection"):
        machine.transition(State.POSITION_OPEN)


def test_startup_reconciliation_enforces_aggregate_two_lot_cap():
    machine = MockExecutionMachine()
    machine.preflight("https://testnet-api.delta.exchange", True, True)
    machine.reconcile(clean_reconciliation(
        exchange_position_lots=2,
        exchange_live_entry_lots=1,
    ))
    assert machine.state is State.RECONCILIATION_BLOCKED



def test_signal_pending_cannot_be_entered_without_entry_guard():
    machine = ready_machine()
    with pytest.raises(SafetyError, match="permit_entry"):
        machine.transition(State.SIGNAL_PENDING)


def test_non_decimal_pnl_component_fails_closed():
    latch = DailyLossLatch("session-1")
    invalid = SessionPnl(0.0, Decimal("0"), Decimal("0"), Decimal("0"))  # type: ignore[arg-type]
    assert latch.evaluate(invalid)
