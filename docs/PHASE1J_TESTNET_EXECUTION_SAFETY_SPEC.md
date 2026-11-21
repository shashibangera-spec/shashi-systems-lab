# Phase 1J — Delta Exchange India Testnet Execution Safety Specification

**Status:** Approved safety specification; mock-only implementation added; test execution pending  
**Phase:** 1J  
**Branch:** `phase1j-testnet-execution-spec`  
**Base:** `main` at Phase 1I merge commit `842c5e25b7335ff84af279d611b73c0e74c95911`  
**Instrument:** Delta Exchange India BTCUSD perpetual, product ID 27  
**Strategy source:** Phase 1I offline AMT + Price Action research backtester  
**Execution mode in this phase:** Testnet demo only; production trading is prohibited

---

## 1. Purpose and non-goals

Phase 1J defines a safety-first state machine for translating the selected Phase 1I research candidate into a controlled Testnet demo workflow.

This document is a design contract, not an execution implementation. Creating this specification does not authorize:
- API credential creation, storage, or use;
- network access to either exchange environment;
- order, cancel, amend, or position-management API calls;
- any Testnet or production order;
- deployment, live trading, or changes to Phase 1I research logic.

No order route may be connected until this specification is reviewed, unresolved parameters are explicitly approved, implementation and adversarial tests are complete, and a separate user authorization is given.

## 2. Absolute environment boundary

### 2.1 Allowlist

The only permitted exchange API origin for any future Phase 1J execution component is:

`https://testnet-api.delta.exchange`

The host must be an exact allowlist match. Validate the parsed URL scheme, hostname, port, and absence of user-info before every request. HTTPS is mandatory.

### 2.2 Production hard block

The production India API origin `https://api.india.delta.exchange` is explicitly forbidden.

The execution process must fail closed if:
- the configured host is anything other than `testnet-api.delta.exchange`;
- the resolved request URL, redirect target, proxy target, or API response origin indicates production;
- a production hostname appears in any execution configuration;
- environment identity cannot be established unambiguously.

Do not follow redirects for authenticated or order-related requests. Do not accept an arbitrary base URL from command-line arguments, environment variables, strategy files, or remote responses. The production host must be covered by explicit negative tests, including lookalike hostnames and URL parsing edge cases.

This host check is a safety guard, not proof that credentials are Testnet credentials. Future setup must use a separately created Testnet-only key, least privilege, IP restrictions where supported, and no production key material. Secrets must never be committed, logged, or copied into test fixtures.

## 3. Hard risk limits and kill-switch

### 3.1 Maximum position/order size

- Absolute cap: **2 lots** for this strategy and account.
- Count filled position quantity plus all live entry orders and any other orders that could increase exposure.
- At no point may aggregate potential BTCUSD exposure exceed 2 lots.
- The configured strategy size is 2 lots; the cap is not a target and cannot be raised by strategy configuration.
- Any unexpected position or external order is a reconciliation failure, not spare capacity.
- Reduce-only exits may reduce exposure but must never increase or reverse it.

A 2-lot trade is intended to support one lot for the 50% first-target reduction and one lot for the runner. Quantity rounding must be validated against the exchange contract's lot increment before any future order is allowed.

### 3.2 Daily loss kill-switch — fixed approved threshold

The kill-switch must latch when the configured daily loss limit is reached or exceeded. Daily loss measurement must include:
- realized trading P&L;
- unrealized P&L on the reconciled open position;
- exchange-reported trading fees and applicable charges;
- funding debits/credits attributable to the session.

Use exchange-reported fills, fees, funding and position marks where available; record the source and timestamp of each component. If any required component is stale or unavailable, the risk calculation is unknown and new entries are blocked.

**Approved immutable threshold:** `DAILY_LOSS_LIMIT_USD = 2.50`. The user approved USD 2.50 on 22 November 2026, representing 2.5% of the planned USD 100 capital. The limit applies to each 05:30 IST–05:30 IST session. Calculate session net P&L as realized P&L + unrealized P&L − trading fees/charges + funding credits/debits (funding debits are negative; credits are positive), all normalized to USD. Latch when net P&L is less than or equal to -USD 2.50. The threshold is fixed and cannot be changed or disabled through runtime configuration. If any required component is missing, stale, invalid, or not denominated/convertible to USD with verified data, the calculation is unknown and new entries are blocked; the mock safety model latches this condition.

On trigger:
1. Latch the kill-switch persistently for the session.
2. Reject all new entries and pullback orders.
3. Cancel all working entry orders and verify cancellation state.
4. Preserve protective exits for any open position.
5. Do not automatically market-flatten unless a separate emergency-exit policy is explicitly approved and tested.
6. Raise a high-priority alert and require operator acknowledgement.
7. Keep the latch through process restarts. Reset only at the next approved session boundary after successful reconciliation and explicit reset policy checks.

A missing, corrupt, stale, or unwritable risk-state store is itself a kill condition.

### 3.3 Additional risk gates

Block new entries when:
- daily loss limit is unset, breached, or cannot be calculated;
- position/order reconciliation is incomplete;
- any position is already open (unless the state machine recognizes and manages that exact strategy position);
- any non-reduce-only order could take aggregate exposure above 2 lots;
- market data is stale, incomplete, out of sequence, or not based on completed 30-minute candles;
- instrument status, tick size, lot size, or contract value is unknown;
- the system clock is materially out of sync;
- audit persistence is unavailable;
- a previous order has an unknown submission outcome;
- the strategy or safety configuration hash differs from the approved session configuration.

## 4. Startup and continuous account reconciliation

The process starts in `DISARMED`. It must not submit, cancel, amend, or otherwise mutate exchange state during startup.

Before entering a ready state, perform a read-only reconciliation of:
- account/environment identity;
- BTCUSD product identity and trading status;
- current BTCUSD position quantity, side, entry price and mark;
- all open orders for the product, including client IDs, exchange IDs, remaining quantities and reduce-only flags;
- recent fills since the last durable audit checkpoint;
- fees and funding records needed for daily P&L;
- local durable order/position ledger versus exchange state.

Reconciliation succeeds only when the local ledger and exchange state agree exactly within documented exchange quantity/price precision. Unknown external orders, unexplained fills, orphan positions, duplicate client IDs, missing audit events, or ambiguous API responses leave the system locked in `RECONCILIATION_BLOCKED`.

Never automatically adopt an unexplained position as a strategy position. Never assume an empty local database means the exchange account is flat.

Repeat reconciliation:
- before arming each session;
- after reconnect or process restart;
- after any request timeout or ambiguous order response;
- after an order/fill event gap;
- before and after a protective-order replacement;
- before session shutdown and final flat-state confirmation.

A single strategy process/account lease is required to prevent concurrent workers from submitting against the same account and instrument. Failure to acquire the lease blocks execution.

## 5. Duplicate-order idempotency and uncertain submissions

Every logical order intent must receive a deterministic, unique client order ID derived from a persisted intent identity (session, strategy instance, signal identity, order role, and revision). The exact exchange-supported client ID format and uniqueness scope must be verified before implementation.

Required protocol:
1. Persist the order intent and its unique client ID before network submission.
2. Submit once.
3. Persist the request/response outcome and exchange order ID when received.
4. If the request times out or the response is ambiguous, mark the intent `SUBMISSION_UNKNOWN`.
5. Query the exchange by client ID and reconcile open orders, fills and order history before considering any retry.
6. Reuse the same client ID only where the exchange's documented idempotency semantics make that safe; never create a fresh ID merely because a response was lost.
7. If the exchange cannot prove whether the order exists, remain blocked and require reconciliation/operator intervention.

Duplicate signal events, repeated websocket messages, process restarts, replayed candles and repeated scheduler invocations must not create duplicate orders. A signal identity may produce at most one entry intent.

## 6. Phase 1I candidate configuration to be carried forward

The selected research candidate is a **Testnet-only candidate**, not a proven profitable strategy or a production authorization.

| Parameter | Phase 1J candidate rule |
|---|---|
| Product | Delta Exchange India BTCUSD perpetual, product ID 27 |
| Bar interval | 30 minutes; completed candles only |
| AMT session | 05:30 IST to 05:30 IST |
| Position size | 2 lots maximum; no scale-in |
| Initial stop | 0.50 × completed signal-candle ATR(14) beyond the signal-candle extreme, plus the Phase 1I one-tick pad; round outward to the $0.50 tick |
| Entry eligibility | Minimum first-target reward/risk = 1.0R |
| Runner breakeven | Fee-adjusted breakeven activation gate at 1.0R / first-target confirmation, following the Phase 1I runner rules |
| Runner target | `--runner-next-amt-target`; nearest eligible completed prior-session VAH/POC/VAL strictly beyond Target 1, fixed from signal close |
| Pullback entry | `--pullback-entry` |
| Pullback validity | `--pullback-limit-bars 3`; Setup A only |
| Pullback fill | Require a one-tick-through; mere touch is not a fill; no chase |
| Partial exit | 50% at Target 1 (with 2 lots, one lot) |
| Runner | Remaining one lot; stop-first ambiguity handling |
| No second AMT reference | Fee-adjusted breakeven fallback, as in Phase 1I |
| Funding/costs | Record actual Testnet fills, fees and funding; do not substitute unverified model estimates for exchange records |

The stop formula, 1.0R eligibility, target references and runner management must match the approved Phase 1I implementation. Any mismatch between the execution adapter and the research engine is a blocking defect, not a reason to silently alter the candidate.

### 6.1 Pullback lifecycle

- Only a completed Setup A signal may create a pullback intent.
- Long limit reference is the original prior-session VAL; short limit reference is the original prior-session VAH.
- The reference, Target 1, runner reference and signal identity are frozen at signal close.
- The order remains eligible for at most the next three completed 30-minute bars.
- A mere touch is insufficient; the market must trade through the limit by at least one $0.50 tick under the Phase 1I fill convention.
- Cancel when the validity window expires, the pre-fill stop is breached, the signal is invalidated, the session is no longer eligible, or a kill condition occurs.
- Never chase an expired or missed entry.
- If the actual fill changes the achievable first-target R:R below 1.0R, do not classify it as an eligible strategy trade. Immediately follow a pre-approved safe disposition (protect and reduce-only exit); this disposition must be implemented and tested before execution is enabled.
- Do not credit Target 1 on the fill candle where OHLC cannot establish ordering.

### 6.2 Position management

- On every fill, reconcile actual filled quantity and immediately establish verified protective coverage for that quantity.
- Protective stop quantity must never exceed the open position and must be reduce-only if the exchange supports that flag.
- If protective coverage cannot be confirmed, cancel remaining entry quantity, latch an execution fault, alert the operator, and follow only the separately approved emergency-exit procedure. Do not continue normal strategy operation unprotected.
- Partial exit occurs only after confirmed Target 1 execution; update the remaining position from exchange fills, not intended quantity.
- Activate the fee-adjusted runner breakeven according to the Phase 1I 1.0R gate and only after the partial is confirmed.
- Evaluate the next AMT target from the candle after partial confirmation, with stop-first handling when both stop and target are touched in one candle.
- All stop replacements must avoid a gap in protective coverage. If atomic amend/replace behavior is not guaranteed by the exchange, the implementation must use a tested safe sequence or block the feature.
- Never allow an exit order to reverse the position. Verify reduce-only behavior or equivalent quantity/side safeguards.

## 7. Explicit execution state machine

All state transitions must be durable, auditable, and driven by confirmed exchange events or completed market-data events. Unknown outcomes transition to a blocked state, never optimistically to success.

| State | Meaning | Permitted next transitions |
|---|---|---|
| `DISARMED` | Default state; no execution permitted | `PREFLIGHT` after explicit operator arm request |
| `PREFLIGHT` | Validate exact Testnet host, key scope metadata, config hash, clock, instrument metadata, risk limit and audit store | `RECONCILING` or `FAULT_LOCKED` |
| `RECONCILING` | Read-only account/order/fill/position comparison | `READY` or `RECONCILIATION_BLOCKED` |
| `READY` | Flat, reconciled, risk gates clear; awaiting eligible completed candle | `SIGNAL_PENDING`, `SESSION_LOCKED`, `FAULT_LOCKED` |
| `SIGNAL_PENDING` | Completed signal validated; persist unique intent and frozen references | `ENTRY_WORKING`, `READY`, `FAULT_LOCKED` |
| `ENTRY_WORKING` | Pullback limit resting; manage three-bar expiry and cancel conditions | `POSITION_OPEN`, `ENTRY_CANCEL_PENDING`, `SUBMISSION_UNKNOWN`, `FAULT_LOCKED` |
| `ENTRY_CANCEL_PENDING` | Cancel requested; await confirmed terminal state and reconcile fills | `READY`, `POSITION_OPEN`, `SUBMISSION_UNKNOWN`, `FAULT_LOCKED` |
| `POSITION_OPEN` | One or more entry fills; protective coverage must be confirmed | `PARTIAL_EXIT_WORKING`, `PROTECTION_FAULT`, `EXIT_PENDING` |
| `PARTIAL_EXIT_WORKING` | Target 1 reduction submitted; remaining quantity derived from fills | `RUNNER_ACTIVE`, `POSITION_OPEN`, `SUBMISSION_UNKNOWN`, `FAULT_LOCKED` |
| `RUNNER_ACTIVE` | Runner managed by fee-adjusted BE and next AMT target | `EXIT_PENDING`, `PROTECTION_FAULT`, `FAULT_LOCKED` |
| `EXIT_PENDING` | Protective, target, or approved risk exit in progress | `FLAT_RECONCILIATION`, `POSITION_OPEN`, `SUBMISSION_UNKNOWN` |
| `FLAT_RECONCILIATION` | Verify zero position and no live strategy orders; finalize ledger | `READY`, `SESSION_LOCKED`, `RECONCILIATION_BLOCKED` |
| `SESSION_LOCKED` | Session ended or daily loss kill-switch latched; no new entries | `RECONCILING` only after approved reset conditions |
| `SUBMISSION_UNKNOWN` | Order outcome uncertain; no new order intent allowed | `RECONCILING` only |
| `PROTECTION_FAULT` | Open position lacks verified protective coverage | Approved emergency handling only; no new entries |
| `RECONCILIATION_BLOCKED` | Exchange/local state mismatch or incomplete account evidence | Manual resolution followed by full `RECONCILING` |
| `FAULT_LOCKED` | Safety, data, persistence, environment or invariant failure | Manual acknowledgement and full preflight/reconciliation |

Global transitions: daily loss trigger, production-host detection, 2-lot cap breach, audit failure, stale data, clock fault, unexpected position/order, duplicate-intent conflict, or unresolved submission outcome immediately block new entries and latch the appropriate fault/lock state.

## 8. Full order, fill, fee and decision audit trail

Use an append-only durable event ledger. Persist intent before submission and persist every response/event before allowing dependent state transitions.

Minimum fields:
- event ID, event type, schema version, UTC timestamp, exchange timestamp when available, local monotonic timestamp;
- session ID, strategy instance ID, process lease ID, correlation ID, signal ID, client order ID, exchange order ID;
- exact environment hostname and product ID;
- strategy/configuration hash and Phase 1I candidate version;
- signal candle timestamps, ATR(14), signal extreme, stop, tick rounding, Target 1, runner AMT reference and source session;
- intended side, order type, limit/stop prices, quantity, reduce-only flag, time-in-force and order role;
- sanitized request metadata, HTTP status, exchange response/error code, retry/reconciliation history;
- every order status transition, cancel/amend request and confirmation;
- every fill quantity, price, timestamp, fee amount/currency, liquidity classification if supplied, and trade/fill ID;
- position snapshots before and after fills, realized/unrealized P&L, funding, daily-loss calculation inputs and kill-switch state;
- operator arm/disarm/acknowledgement actions and reason codes.

Never log API keys, signatures, authorization headers, secrets, or raw credential-bearing request material. Redact sensitive headers and query parameters before persistence. Audit records must be tamper-evident (hash chaining or equivalent), backed up, and retained under a documented policy. If durable audit write fails, do not submit new orders; if it fails while a position is open, latch a fault and alert immediately.

## 9. Market-data and clock requirements

- Signals use completed 30-minute candles only; no intrabar signal decisions.
- Maintain the Phase 1I 05:30 IST session boundary and complete-session profile rules.
- Reject duplicate, missing, out-of-order, stale or incomplete candles.
- Verify exchange/server time offset before arming and periodically while active.
- No order may be generated from a candle whose close has not been confirmed.
- Reconcile market-data timestamps and execution timestamps in UTC while retaining IST session labels for operator review.

## 10. Failure handling and operator controls

- Default on startup, crash, restart or uncertain state is `DISARMED` or a more restrictive locked state.
- Manual disarm must be available independently of the strategy loop.
- A kill-switch or fault must survive restart.
- The operator must be able to inspect current state, position, open orders, protective coverage, daily loss and last audit event without enabling execution.
- No automatic re-arm after network recovery, process restart, API error, or kill-switch event.
- Any emergency flattening behavior requires a separately reviewed policy specifying trigger, order type, retry/idempotency behavior, slippage bounds, and operator notification. It is intentionally unspecified here and must not be improvised by implementation.

## 11. Unresolved decisions — blockers before implementation

The following must be explicitly settled before any order route can be connected:

1. ~~Daily loss limit~~ **Resolved:** USD 2.50 per 05:30 IST–05:30 IST session; include realized and unrealized P&L, subtract fees/charges, and include funding credits/debits. Missing or stale components block entries and latch the mock kill-switch.
2. **Protective-order semantics:** verify Delta Testnet support for reduce-only stops, stop trigger source, amend/replace guarantees, partial fills, and behavior on disconnect.
3. **Client-order idempotency:** confirm accepted client ID field, uniqueness scope, queryability and retention after cancellation/fill.
4. **Testnet account isolation:** verify the Testnet API key is distinct from production and has only required permissions.
5. **Quantity and precision:** confirm current product metadata for contract value, lot increment, tick size, minimum order size and allowed order types.
6. **Emergency position policy:** define whether/when to flatten if protective coverage fails, and who authorizes it.
7. **Audit durability:** choose local/database persistence, backup, retention and tamper-evidence mechanism.
8. **Operator controls:** define alert channel, acknowledgement, manual reset and kill-switch access.
9. **Funding/fee accounting:** verify the Testnet event sources and currencies for actual fees/funding; do not infer missing values.
10. **Session shutdown:** define handling of open positions and orders at 05:30 IST; no automatic liquidation assumption is made.

The daily-loss decision is resolved as above. All other Section 11 blockers remain unresolved and continue to prohibit exchange connectivity and order routes. The current implementation is mock-only and in-memory; it is not a durable execution service.

## 12. Acceptance gates before first Testnet order

The first Testnet order remains prohibited until all gates pass:

- [x] This specification reviewed and approved.
- [ ] All Section 11 blockers resolved in writing.
- [ ] Exact Testnet hostname allowlist and production-host negative tests pass.
- [ ] Testnet-only credential isolation verified without exposing secrets.
- [ ] 2-lot aggregate exposure cap tested across positions plus working orders.
- [ ] Daily loss kill-switch tested at, below and above the USD 2.50 threshold, including durable restart persistence (mock tests cover latch behavior; production-grade persistence remains unimplemented).
- [ ] Startup reconciliation tested for flat, open position, open order, orphan fill, stale snapshot and external/manual order.
- [ ] Duplicate submission, timeout, lost response, replay and process restart tests prove no duplicate exposure.
- [ ] Protective stop coverage, partial fill, cancel/replace and reduce-only behavior verified on Testnet.
- [ ] Full order/fill/fee/funding audit records verified and tamper-evidence checked.
- [ ] Market-data gaps, stale candles, clock drift, websocket disconnect and API rate-limit tests fail closed.
- [ ] Manual disarm and operator alerts tested.
- [ ] A separate, explicit authorization for the first Testnet demo order is obtained.

Passing these gates does not authorize production access. Production API host, production credentials and live orders remain out of scope.

## 13. Phase boundary

Phase 1J begins with this written safety specification only. The next work item is mock-only state-machine and fail-closed safety tests that do not contact the exchange. Only after those are approved may a separately scoped Testnet connectivity step be proposed. No production route will be implemented in Phase 1J.
