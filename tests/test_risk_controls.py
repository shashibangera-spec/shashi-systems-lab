from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from shashi_engine.risk_controls import RiskContext, RiskGate, RiskIntent, RiskPolicy

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)


def policy(**overrides):
    values = {
        "currency": "USD",
        "max_total_exposure": Decimal("10000"),
        "max_single_trade_loss": Decimal("100"),
        "max_daily_loss": Decimal("250"),
        "max_intent_age": timedelta(seconds=30),
    }
    values.update(overrides)
    return RiskPolicy(**values)


def context(**overrides):
    values = {
        "currency": "USD",
        "current_exposure": Decimal("2000"),
        "daily_net_pnl": Decimal("0"),
        "as_of": NOW,
        "kill_switch_active": False,
    }
    values.update(overrides)
    return RiskContext(**values)


def intent(intent_id="i-1", **overrides):
    values = {
        "intent_id": intent_id,
        "currency": "USD",
        "proposed_notional": Decimal("1000"),
        "worst_case_loss": Decimal("50"),
        "created_at": NOW - timedelta(seconds=1),
    }
    values.update(overrides)
    return RiskIntent(**values)


def test_valid_intent_is_approved_for_research_only():
    result = RiskGate(policy()).evaluate(intent(), context())
    assert result.approved
    assert result.reason_code == "APPROVED_FOR_RESEARCH_ONLY"


@pytest.mark.parametrize(
    ("ctx", "expected"),
    [
        ({"kill_switch_active": True}, "KILL_SWITCH_ACTIVE"),
        ({"daily_net_pnl": Decimal("-250")}, "DAILY_LOSS_LIMIT_REACHED"),
        ({"daily_net_pnl": Decimal("-251")}, "DAILY_LOSS_LIMIT_REACHED"),
        ({"current_exposure": Decimal("9500")}, "MAX_TOTAL_EXPOSURE_EXCEEDED"),
        ({"currency": "INR"}, "CURRENCY_MISMATCH"),
    ],
)
def test_context_blocks_are_fail_closed(ctx, expected):
    result = RiskGate(policy()).evaluate(intent(), context(**ctx))
    assert not result.approved
    assert result.reason_code == expected


def test_intent_risk_limit_is_enforced():
    result = RiskGate(policy()).evaluate(
        intent(worst_case_loss=Decimal("100.01")), context()
    )
    assert result.reason_code == "SINGLE_TRADE_RISK_EXCEEDED"


@pytest.mark.parametrize(
    ("created_at", "expected"),
    [
        (NOW - timedelta(seconds=31), "STALE_OR_FUTURE_INTENT"),
        (NOW + timedelta(seconds=1), "STALE_OR_FUTURE_INTENT"),
    ],
)
def test_stale_or_future_intents_are_rejected(created_at, expected):
    result = RiskGate(policy()).evaluate(intent(created_at=created_at), context())
    assert result.reason_code == expected


def test_currency_must_match_policy_and_context():
    result = RiskGate(policy()).evaluate(intent(currency="INR"), context())
    assert result.reason_code == "CURRENCY_MISMATCH"


def test_duplicate_id_is_rejected_even_after_first_rejection():
    gate = RiskGate(policy())
    first = gate.evaluate(intent(), context(kill_switch_active=True))
    second = gate.evaluate(intent(), context())
    assert first.reason_code == "KILL_SWITCH_ACTIVE"
    assert second.reason_code == "DUPLICATE_INTENT"


def test_exposure_equal_to_limit_is_allowed():
    result = RiskGate(policy()).evaluate(
        intent(proposed_notional=Decimal("8000")), context()
    )
    assert result.approved


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_total_exposure": Decimal("0")}, "max_total_exposure"),
        ({"max_single_trade_loss": Decimal("NaN")}, "max_single_trade_loss"),
        ({"max_daily_loss": Decimal("-1")}, "max_daily_loss"),
    ],
)
def test_policy_rejects_invalid_limits(kwargs, message):
    with pytest.raises(ValueError, match=message):
        policy(**kwargs)


def test_context_rejects_negative_exposure():
    with pytest.raises(ValueError, match="current_exposure"):
        context(current_exposure=Decimal("-1"))


def test_intent_rejects_negative_loss():
    with pytest.raises(ValueError, match="worst_case_loss"):
        intent(worst_case_loss=Decimal("-0.01"))


def test_context_requires_utc_timestamp():
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        context(as_of=datetime(2026, 11, 21, 12, 0))


def test_no_float_inputs():
    with pytest.raises(ValueError, match="finite Decimal"):
        context(daily_net_pnl=1.0)


def test_concurrent_duplicate_evaluation_approves_at_most_once():
    from concurrent.futures import ThreadPoolExecutor

    gate = RiskGate(policy())
    proposed = intent("same-id")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: gate.evaluate(proposed, context()), range(32)))
    assert sum(result.approved for result in results) == 1
    assert sum(result.reason_code == "DUPLICATE_INTENT" for result in results) == 31
