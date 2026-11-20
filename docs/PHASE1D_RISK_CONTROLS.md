# Phase 1D — Non-executing risk controls

## Scope

Phase 1D implements deterministic, testable risk checks for research intent objects only. It does not connect to Delta, read account balances or positions, calculate order size, submit/cancel orders, select leverage, or persist state.

## Inputs

    RiskPolicy(
        currency="USD",  # or INR; all inputs must use this same declared currency
        max_total_exposure=Decimal("..."),
        max_single_trade_loss=Decimal("..."),
        max_daily_loss=Decimal("..."),
    )

The currency is explicit. The gate never converts USD to INR and never uses the documented platform conversion factor. Monetary inputs must be precomputed by a separately approved caller; no BTC lot, contract-value, fee or FX calculation is performed here.

- RiskIntent: unique caller-supplied ID, currency, proposed notional, worst-case loss, creation time.
- RiskContext: current exposure, daily net PnL, currency, UTC evaluation time and kill-switch state.
- RiskPolicy: maximum total exposure, maximum single-intent loss, maximum daily loss and maximum intent age.

## Evaluation order

The gate rejects an intent if any of the following apply:

1. The intent ID has already been evaluated.
2. Policy, intent and context currencies do not match.
3. Kill switch is active.
4. Intent is future-dated or older than the configured maximum age.
5. Daily net PnL is at or below the negative daily-loss limit.
6. Worst-case loss exceeds the single-intent loss limit.
7. Current exposure plus proposed notional exceeds the total exposure limit.

Boundary semantics: equality at the exposure and per-intent loss limits is allowed; reaching the daily loss limit blocks new intents. Negative daily PnL represents a loss.

## Duplicate protection

The RiskGate stores evaluated IDs in process memory and protects the check-and-record operation with a lock. IDs are consumed on first evaluation, including rejected intents, so a rejected intent cannot later be replayed under the same ID. This registry is not durable and resets on process restart. It is a testable research guard, not a production idempotency service.

## Kill switch

The caller supplies kill_switch_active. When true, the gate rejects every new intent. This milestone defines and tests the blocking behavior only; it does not provide a user interface, remote switch, process supervisor, or exchange-side cancellation.

## Output

    RiskDecision(
        approved=False,
        reason_code="KILL_SWITCH_ACTIVE",
        intent_id="...",
    )

Even approved=True means **approved for research-only downstream review**. It does not mean an order is valid, sized, funded, safe to execute, or submitted. No execution adapter exists.

## Acceptance

- Deterministic tests for each rejection reason and allowed boundary.
- Decimal-only finite monetary inputs; no float conversion.
- UTC timestamps and stale/future intent rejection.
- Currency mismatch fails closed; no implicit conversion.
- Duplicate IDs rejected under repeated and concurrent evaluation.
- Kill switch blocks intents.
- Full existing test suite and CI pass.

## Explicit non-goals

No order routes, account credentials, private API, live/demo trading, order sizing, leverage, margin calculations, PnL accounting, liquidation simulation, database, persistent duplicate registry, strategy signals or dashboard changes.
