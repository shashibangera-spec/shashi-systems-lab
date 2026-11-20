from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import pytest

from shashi_engine.accounting import (
    AccountingPolicy, AccountingScenario, FeeSchedule, FundingEvent,
    FxObservation, calculate_accounting, evaluate_usd_risk_gate, reporting_amount,
)
from shashi_engine.models import Instrument
from shashi_engine.risk_controls import RiskContext, RiskGate, RiskIntent, RiskPolicy

UTC = timezone.utc
NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


def instrument() -> Instrument:
    return Instrument(
        product_id=27, symbol="BTCUSD", contract_type="perpetual_futures",
        state="live", trading_status="operational", contract_value=Decimal("0.001"),
        contract_value_asset="BTC", tick_size=Decimal("0.5"), quote_asset="USD",
        api_settlement_asset="USD", funding_interval_seconds=28800,
        minimum_order_lots=1, documented_margin_currency="INR",
        documented_effective_settlement_currency="INR",
    )


def policy(max_age=timedelta(minutes=10)) -> AccountingPolicy:
    return AccountingPolicy(max_fx_age=max_age)


def fees(settlement=Decimal("0.0005")) -> FeeSchedule:
    return FeeSchedule(
        maker_rate=Decimal("0.0002"), taker_rate=Decimal("0.0005"),
        gst_rate=Decimal("0.18"), settlement_fee_rate=settlement,
    )


def scenario(**kwargs) -> AccountingScenario:
    base = dict(
        instrument=instrument(), lots=1, position_side="long",
        entry_price=Decimal("60000"), entry_liquidity="maker",
        entry_at=NOW - timedelta(minutes=30), fee_schedule=fees(),
        policy=policy(), as_of=NOW, exit_price=Decimal("61000"),
        exit_liquidity="taker", exit_at=NOW,
    )
    base.update(kwargs)
    return AccountingScenario(**base)


def test_contract_quantity_and_usd_notional_exact():
    result = calculate_accounting(scenario())
    assert result.btc_quantity == Decimal("0.001")
    assert result.entry_notional_usd == Decimal("60")
    assert result.exit_notional_usd == Decimal("61")


def test_fee_and_gst_keep_full_decimal_precision():
    result = calculate_accounting(scenario())
    assert result.entry_fee_usd == Decimal("0.012")
    assert result.entry_gst_usd == Decimal("0.00216")
    assert result.exit_fee_usd == Decimal("0.0305")
    assert result.exit_gst_usd == Decimal("0.005490")


def test_no_fx_means_no_inr_but_usd_calculation_continues():
    result = calculate_accounting(scenario())
    assert result.inr_equivalents is None
    assert result.entry_notional_usd == Decimal("60")


def test_fresh_explicit_fx_produces_separate_inr_view():
    fx = FxObservation("USD", "INR", Decimal("90"), NOW, "synthetic-test-fixture", "synthetic")
    result = calculate_accounting(scenario(fx_observation=fx))
    assert result.inr_equivalents is not None
    assert result.inr_equivalents["entry_notional"] == Decimal("5400")
    assert result.currency == "USD"
    assert result.fx_status == "synthetic"
    assert result.exchange_reconciled is False


def test_stale_fx_suppresses_inr_only():
    fx = FxObservation(
        "USD", "INR", Decimal("90"), NOW - timedelta(minutes=11),
        "fixture", "verified",
    )
    result = calculate_accounting(scenario(fx_observation=fx))
    assert result.inr_equivalents is None
    assert result.entry_notional_usd == Decimal("60")


def test_future_fx_suppresses_inr_only():
    fx = FxObservation("USD", "INR", Decimal("90"), NOW + timedelta(seconds=1), "fixture", "verified")
    result = calculate_accounting(scenario(fx_observation=fx))
    assert result.inr_equivalents is None


def test_missing_max_fx_age_is_not_permitted():
    with pytest.raises(TypeError):
        AccountingPolicy()  # type: ignore[call-arg]


def test_wrong_fx_pair_rejected():
    with pytest.raises(ValueError, match="USD/INR"):
        FxObservation("INR", "USD", Decimal("0.011"), NOW, "fixture", "verified")


def test_no_silent_85_fx_fallback():
    result = calculate_accounting(scenario())
    assert result.inr_equivalents is None


def test_settlement_fee_only_when_held_through_settlement():
    not_held = calculate_accounting(scenario())
    held = calculate_accounting(scenario(
        held_through_settlement=True, settlement_notional_usd=Decimal("62"),
    ))
    assert not_held.settlement_fee_usd == Decimal("0")
    assert held.settlement_fee_usd == Decimal("0.0310")


def test_settlement_notional_and_rate_required_when_held():
    with pytest.raises(ValueError, match="settlement notional"):
        scenario(held_through_settlement=True)
    with pytest.raises(ValueError, match="settlement fee rate"):
        scenario(
            held_through_settlement=True, settlement_notional_usd=Decimal("60"),
            fee_schedule=fees(settlement=None),
        )


def test_funding_sign_convention_and_mark_price_notional():
    long_positive = FundingEvent(
        Decimal("0.001"), "long", 1, Decimal("60000"), NOW, 28800,
    )
    short_positive = FundingEvent(
        Decimal("0.001"), "short", 1, Decimal("60000"), NOW, 28800,
    )
    long_negative = FundingEvent(
        Decimal("-0.001"), "long", 1, Decimal("60000"), NOW, 28800,
    )
    assert calculate_accounting(scenario(funding_events=(long_positive,))).funding_cashflow_usd == Decimal("-0.06")
    assert calculate_accounting(scenario(funding_events=(short_positive,))).funding_cashflow_usd == Decimal("0.06")
    assert calculate_accounting(scenario(funding_events=(long_negative,))).funding_cashflow_usd == Decimal("0.06")


def test_funding_interval_must_match_contract():
    event = FundingEvent(Decimal("0.001"), "long", 1, Decimal("60000"), NOW, 3600)
    with pytest.raises(ValueError, match="funding interval"):
        scenario(funding_events=(event,))


def test_short_scenario_pnl_sign():
    result = calculate_accounting(scenario(position_side="short"))
    assert result.gross_scenario_pnl_usd == Decimal("-1")


def test_no_exit_means_no_closed_trade_pnl_or_exit_fee():
    result = calculate_accounting(scenario(exit_price=None, exit_liquidity=None, exit_at=None))
    assert result.gross_scenario_pnl_usd is None
    assert result.net_scenario_result_usd is None
    assert result.exit_fee_usd == Decimal("0")


def test_rounding_only_at_reporting_boundary():
    raw = Decimal("0.01216")
    result = calculate_accounting(scenario())
    assert result.entry_gst_usd == Decimal("0.00216")
    assert reporting_amount(raw, policy()) == Decimal("0.01")


def test_risk_gate_accepts_usd_only_and_preserves_research_label():
    gate = RiskGate(RiskPolicy("USD", Decimal("1000"), Decimal("100"), Decimal("200")))
    intent = RiskIntent("research-1", "USD", Decimal("60"), Decimal("5"), NOW)
    context = RiskContext("USD", Decimal("0"), Decimal("0"), NOW)
    decision = evaluate_usd_risk_gate(gate, intent, context)
    assert decision.reason_code == "APPROVED_FOR_RESEARCH_ONLY"


def test_risk_gate_rejects_inr_before_gate():
    gate = RiskGate(RiskPolicy("USD", Decimal("1000"), Decimal("100"), Decimal("200")))
    intent = RiskIntent("research-inr", "INR", Decimal("5400"), Decimal("100"), NOW)
    context = RiskContext("INR", Decimal("0"), Decimal("0"), NOW)
    with pytest.raises(ValueError, match="USD-only"):
        evaluate_usd_risk_gate(gate, intent, context)
