# Phase 1E — Non-executing accounting simulator specification

Status: **Approved implementation specification — non-executing simulator only.**  
Repository: `shashibangera-spec/shashi-systems-lab`  
Base: `main` at `64354b21deabf38608f9a63dd7cef6915b1aa05b`

## 1. Objective

Define a deterministic, Decimal-only simulator for BTCUSD perpetual trade economics and the India account ledger. It must keep USD contract denomination separate from INR account-ledger representation, calculate explicitly configured fees/GST/funding, and pass a same-currency risk intent into the existing non-executing `RiskGate`.

The simulator is for synthetic/research scenarios only. It must never connect to Delta, access account data, size a real order, submit/cancel an order, or claim that a research approval permits execution.

## 2. Scope

### Included
- BTCUSD contract notional from verified contract metadata and whole-number lots.
- Explicit USD-denominated trade/fee calculations.
- Explicitly parameterized USD-to-INR ledger conversion using a supplied, timestamped rate observation; no implicit or hard-coded FX.
- Maker/taker fee scenarios, 18% GST on the trading fee, and a separately represented possible settlement fee.
- Funding cash-flow scenarios as a separate cost/credit, not a trading fee.
- A transparent accounting breakdown with source/assumption provenance.
- RiskGate integration using a single, explicit risk currency and caller-supplied exposure/PnL context.
- Synthetic fixtures and unit/integration tests only.

### Excluded
- Exchange connectivity, authentication, private endpoints, balances, positions or fills.
- Order creation, modification, cancellation, execution, demo execution or live execution.
- Margin, liquidation, leverage, collateral sufficiency, exchange-realised PnL or tax-liability calculations.
- A production FX feed or assumption that Delta's published 85 INR/USD reference is a live or guaranteed conversion rate.
- Persisted ledgers, databases, dashboards, strategy signals or automated trading.
- Any modification to the existing `btc-dashboard` repository.

## 3. Critical accounting boundary: denomination vs ledger

Keep these concepts distinct in types and output:

1. **Contract denomination:** BTCUSD notional is represented in USD.
2. **API metadata:** preserve the raw `api_settlement_asset` value returned by the public product API (the user's earlier verifier reported USD).
3. **India account ledger:** Delta India documentation describes INR balances and effective INR margin/PnL realization.
4. **FX observation:** an explicit input record, not a constant. It must include base currency USD, quote currency INR, positive finite Decimal rate, observed-at UTC timestamp, source label, and an explicit status indicating whether it is synthetic or externally verified. An explicit `max_age` freshness policy is mandatory; the policy value is configuration, not an inferred default.

The simulator must not infer one field from another. It must not rewrite the raw API settlement asset to INR or infer that a USD API field means the account ledger is USD.

**No implicit FX:** every conversion requires a supplied FX observation. Missing, stale, future-dated, wrong-direction, non-positive, or provenance-incomplete FX input must fail closed for INR output. Staleness is determined against the explicitly configured maximum age; if no maximum age is configured, INR output fails closed. Synthetic observations are allowed only in clearly labelled test/research fixtures and must never be presented as a live Delta conversion rate. A supplied externally sourced observation may be used for a separately labelled INR equivalent when its source, timestamp, pair, rate and freshness all validate.

The previously documented 85 INR/USD value is historical/documentation context only. Do not use it as a default, fallback, constant, or test oracle.

## 4. Proposed domain objects

Names are illustrative; implementation may refine names while preserving semantics.

- `ContractSpec`: symbol, product ID, contract type, BTC per lot, lot increment/minimum, tick size, quote currency, API settlement asset, funding interval. Decimal quantities only.
- `FillAssumption`: side (entry/exit), lots, reference/index price, maker/taker classification, timestamp. This is a scenario input, not an exchange fill.
- `FeeSchedule`: maker/taker rates, GST rate, optional settlement-fee rate and eligibility flag. Rates are explicit configuration, not hidden defaults.
- `FundingAssumption`: funding rate, notional basis, payment direction and timestamp/interval. Keep funding separate from trading fee and GST.
- `FxObservation`: base, quote, rate, observed-at UTC, source, synthetic/verified status. `AccountingPolicy` must require a configured maximum FX age; there is no default age.
- `AccountingPolicy`: USD-only RiskGate currency, fee denomination assumption, GST denomination assumption, mandatory maximum FX age, reporting/ledger rounding policy and settlement-fee scenario setting.
- `AccountingBreakdown`: lots, BTC quantity, USD notional, entry/exit fee, GST, potential settlement fee, funding cash-flow, gross price PnL scenario if supplied, net scenario result, INR ledger equivalents where allowed, FX provenance, warnings and assumptions.
- `RiskEvaluationInput`: USD-only proposed notional, worst-case loss, current exposure, daily net PnL, UTC context time and kill-switch state. INR equivalents are reporting-only and cannot enter this object.
- Existing `RiskPolicy`, `RiskIntent`, `RiskContext`, `RiskDecision` remain the gate interface; do not weaken their validation or alter their research-only approval meaning.

All monetary and rate arithmetic must use finite `Decimal`; binary floats are rejected. Timestamps must be timezone-aware UTC. Contract lot quantity must be a whole number of lots and obey the verified minimum/increment. Price must align to the configured tick when the scenario represents an assumed executable fill; index/reference prices used only for valuation must be separately typed and need not be tick-aligned.

## 5. Calculation rules

### 5.1 Contract quantity and notional
For the currently verified BTCUSD contract facts:
- 1 lot represents 0.001 BTC.
- BTC quantity = whole-number lots × BTC per lot.
- USD notional = BTC quantity × explicitly supplied BTCUSD index/reference price.

The contract metadata remains configurable and must be validated; do not scatter 0.001 through calculation code. Do not infer INR notional before an FX observation is supplied.

### 5.2 Trading fees and GST
Use configured rates. The documented base fee assumptions for the research scenario are maker 0.02%, taker 0.05%, and GST 18% on the trading fee.

For each entry/exit fill independently:
- fee amount = fill notional × applicable maker/taker rate;
- GST amount = fee amount × GST rate;
- record fee and GST separately.

Do not classify a limit order as maker merely because it is a limit order; maker/taker is an explicit scenario input. Do not apply GST to notional. Do not assume promotional discounts, fee tiers, or account-specific offers.

**Unresolved billing detail:** before claiming exact account-ledger equivalence, obtain authoritative confirmation of the currency in which fees/GST are charged and how rounding is applied. Until then, represent fee denomination as an explicit policy assumption and label output as simulated, not exchange-reconciled.

### 5.3 Settlement fee
A settlement fee is a separate conditional line item. Apply it only when the scenario explicitly states that a contract is held through expiry/settlement. Calculate it on the explicitly supplied settlement notional using the configured settlement-fee rate (the documented base taker rate may be used as a clearly labelled scenario assumption, not a hidden constant). If the contract is not held through settlement, record zero with the reason. If settlement eligibility, notional or rate is unknown, mark the settlement component unresolved; do not silently assume zero or charge every closed trade.

### 5.4 Funding
Funding is a separate periodic perpetual-contract cash flow, not a maker/taker fee and not GST on trading fees. Use the standard perpetual convention: positive funding means longs pay shorts; negative funding means shorts pay longs. Calculate each funding event on mark-price notional at the 8-hour funding interval specified by the verified contract metadata. A long position's signed cash flow is negative for positive funding and positive for negative funding; a short position is the inverse. Require an explicit funding rate, position side/quantity, mark price and event timestamp. Funding remains separate from trading fees and GST. No historical or live funding fetch is in scope.

### 5.5 FX conversion and INR reporting view
Convert each eligible USD component for a separately labelled INR equivalent using the supplied USD/INR observation only. This is a parallel reporting view, not a second source of truth and not an input to RiskGate:
- INR equivalent = USD amount × supplied INR-per-USD rate.
- Preserve original USD value and converted INR value side by side.
- Record exact FX rate, source, timestamp, and synthetic/verified status.
- Never convert an already-INR amount again.
- Do not aggregate USD and INR values in one total.
- If fee/GST currency treatment is unresolved, show the assumed denomination prominently and prevent the report from being labelled exchange-reconciled. INR equivalents are omitted if the observation is missing, future-dated, older than the configured maximum age, wrong-direction, non-positive, or missing provenance. USD calculations remain available.

### 5.6 Rounding
Keep full Decimal precision through intermediate calculations. Quantize only at an explicitly configured presentation/ledger boundary. Currency minor-unit precision and exchange rounding rules must be configurable and marked unverified until Delta confirms them. Tests must verify no premature rounding.

### 5.7 PnL
Only a clearly labelled **scenario price PnL** may be calculated from explicit entry/exit assumptions. Do not label it exchange realised PnL, account PnL, or tax PnL. Separate gross price PnL, fees, GST, settlement fee and funding. Net scenario result is a research estimate under the configured assumptions.

## 6. RiskGate integration contract

RiskGate evaluation is **strictly USD-only** in Phase 1E. INR is display-only and must never be passed to RiskGate.

1. Proposed notional, worst-case loss, current exposure and daily net PnL must all be USD amounts.
2. Mixed-currency inputs are rejected before the gate is called. No FX conversion is performed for RiskGate.
3. Missing or invalid INR FX does not block a valid USD-only RiskGate evaluation; it only suppresses the separate INR reporting equivalents.
4. If any USD risk input is missing, invalid, stale/future-dated where applicable, or based on unresolved accounting assumptions, do not call the gate; return a fail-closed accounting validation result.
5. Construct existing `RiskIntent` and `RiskContext` with USD and UTC timestamps, then call existing `RiskGate.evaluate()`.
6. Preserve the exact gate decision and reason code. Do not translate `APPROVED_FOR_RESEARCH_ONLY` into execution approval.
7. Duplicate-intent behaviour remains process-local and is not a durable idempotency guarantee.

RiskGate currently accepts caller-provided precomputed notional and worst-case loss. The simulator must document the derivation and assumptions for those values; it must not imply the gate itself computes them.

## 7. Output and auditability

Every report must include:
- scenario ID and generated-at UTC timestamp;
- contract metadata version/source;
- all input assumptions and whether synthetic or verified;
- USD quantities and totals;
- INR equivalents only when a valid, fresh, explicitly sourced USD/INR observation was supplied; RiskGate inputs and decisions in USD only;
- fee, GST, settlement fee and funding as distinct rows;
- rounding policy;
- unresolved assumptions/warnings;
- RiskGate decision, currency, reason code and explicit research-only label.

A report with incomplete FX or fee-currency assumptions may still show USD-only calculations, but must not claim an INR ledger reconciliation.

## 8. Safety and architecture constraints

- Pure calculation functions; deterministic inputs/outputs.
- No network clients, environment-secret reads, filesystem writes, database calls, or account access in the simulator package.
- No order/execution modules or execution-shaped callbacks.
- No automatic leverage, margin, position sizing or trade recommendations.
- No mutation to Phase 1B/1C data collection or the locked BTC dashboard.
- Never commit credentials, account identifiers, private data or raw account exports.
- Keep simulator separate from the existing BTC dashboard project.

## 9. Approved conventions and remaining caveats

The following conventions are approved and implemented in the Phase 1E branch:
- RiskGate is USD-only; INR equivalents are display-only and never passed to RiskGate.
- Every INR conversion requires an explicit timestamped USD/INR observation, source/provenance, and explicitly configured maximum age. There is no default age or ₹85 fallback. Missing, stale, future-dated, or invalid observations suppress INR output while USD calculations continue.
- Settlement fee applies only when held through expiry/settlement and is calculated on supplied settlement notional at an explicit configured rate.
- Funding: positive rate means longs pay shorts; negative rate means shorts pay longs; use mark-price notional at each 8-hour contract funding interval.
- Full Decimal precision is retained internally; quantization is confined to explicit reporting/ledger boundaries.

Remaining limitations:
- Fee/GST booking currency and exchange-specific rounding have not been independently reconciled against an authoritative account/API example. USD fee/GST denomination is an explicit scenario assumption; outputs are not exchange-reconciled.
- FX is supplied by the caller. No live FX feed or account integration is included.
- No demo or live execution, margin, leverage, liquidation, position sizing, tax calculation, or private account access is in scope.
