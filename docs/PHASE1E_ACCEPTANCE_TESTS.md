# Phase 1E — Acceptance test plan

Status: **Test specification only — no implementation or execution performed.**  
Companion: [Phase 1E accounting simulator specification](PHASE1E_ACCOUNTING_SIMULATOR_SPEC.md)

These are acceptance criteria for a future implementation. They are not evidence that tests have run.

## A. Contract and quantity validation

1. A one-lot scenario using the verified BTCUSD contract metadata produces exactly 0.001 BTC.
2. A scenario with N whole-number lots produces N × configured BTC-per-lot using Decimal arithmetic.
3. Zero, negative, fractional-lot, below-minimum, or off-increment quantities are rejected.
4. Missing contract value, invalid currency metadata, non-finite Decimal values, or unsupported contract type fail closed.
5. The 0.001 BTC lot size is read from contract metadata, not duplicated as a magic constant in calculations.
6. Reference/index price must be positive and finite. Assumed executable fill price must additionally satisfy tick alignment; valuation-only index price is not incorrectly forced to tick alignment.

## B. USD notional

7. Given 1 lot and a supplied reference price of USD 60,000/BTC, USD notional is exactly USD 60.00.
8. Given 3 lots at USD 60,000/BTC, USD notional is exactly USD 180.00.
9. USD notional remains USD and is never silently relabelled INR.
10. Changing only the FX observation does not change BTC quantity or USD notional.

## C. FX and INR ledger

11. A supplied synthetic USD/INR rate of 90.00 converts USD 60.00 to INR 5,400.00; output clearly labels the rate synthetic.
12. The documented 85 INR/USD value is never silently used as a default or fallback.
13. Missing FX observation prevents INR output while allowing valid USD-only calculations.
14. Wrong pair (e.g. INR/USD when USD/INR is required), zero, negative, NaN, infinity, stale, or future-dated FX observation fails closed for INR display; USD-only calculations remain available.
15. FX observation includes source, UTC timestamp, base/quote and synthetic/verified status; missing provenance is rejected.
16. Converted INR and original USD amounts remain separately available and are never added together.
17. An already-INR amount is not converted again.
18. A maximum FX age must be explicitly configured; absent policy fails closed for INR output. Freshness boundary semantics are tested at exactly the maximum age and just beyond it.
19. The raw API settlement asset remains distinct from documented INR account-ledger currency in models and serialized output.

## D. Maker/taker fees and GST

20. At USD 60 notional, maker fee at 0.02% is USD 0.012 before GST.
21. At USD 60 notional, taker fee at 0.05% is USD 0.030 before GST.
22. GST at 18% on those fees is respectively USD 0.00216 and USD 0.00540 under a USD-denominated fee assumption.
23. Fee plus GST effective rates are 0.0236% maker and 0.0590% taker before any separately modelled settlement fee.
24. Entry and exit fills are charged independently; mixed maker-entry/taker-exit scenarios use the correct rate per fill.
25. A limit-order label alone never forces maker classification; maker/taker is explicit input.
26. GST is applied to fee amount, never to trade notional.
27. Fee/GST denomination assumption is present in output. If exchange billing denomination or rounding remains unverified, output cannot be labelled exchange-reconciled.
28. Missing fee schedule, negative/non-finite rates, or unsupported tax rate fails closed rather than silently substituting a default.

## E. Settlement fee

29. Settlement fee is a separate line item and never merged into entry/exit trading fee.
30. When the scenario explicitly indicates no settlement event/eligibility, settlement fee is zero with the reason recorded.
31. When eligible, the configured settlement-fee rate and explicitly configured notional basis are applied and disclosed.
32. Missing settlement-fee rate or unknown eligibility produces an unresolved warning/fail-closed total, not an assumed zero.

## F. Funding

33. Funding appears as a separate cash-flow line, never as maker/taker fee or GST.
34. Funding calculation requires explicit rate, notional basis, interval, sign convention and payer/receiver direction.
35. Positive and negative funding scenarios produce opposite cash-flow signs according to the declared convention.
36. Missing sign convention, interval, or notional basis prevents funding calculation.
37. Funding is not multiplied by GST unless a separately verified rule explicitly requires it; the default simulator must not apply GST to funding.

## G. PnL and rounding

38. Scenario gross price PnL uses explicit entry/exit assumptions and is labelled scenario PnL, not exchange realised PnL.
39. Net scenario result separately accounts for gross price PnL, entry/exit fees, GST, settlement fee and funding.
40. Missing exit price does not fabricate closed-trade PnL; open-position mark scenarios are labelled separately if later approved.
41. Intermediate Decimal values are not rounded prematurely.
42. Rounding is applied only at the configured boundary; precision and rounding mode appear in report metadata.
43. Unknown exchange currency precision or rounding rule is clearly labelled unverified.

## H. RiskGate integration

44. A valid USD scenario constructs RiskIntent and RiskContext with USD throughout and invokes the existing RiskGate.
45. INR equivalents are display-only and never invoke or feed RiskGate.
46. Mixed USD/INR inputs are rejected before RiskGate is called.
47. Missing/stale/future-dated FX suppresses INR equivalents but does not block otherwise-valid USD-only RiskGate evaluation.
48. Worst-case loss passed to RiskGate includes the explicitly selected cost components and documented assumptions; it is not silently equated with gross price movement.
49. Existing RiskGate reason codes are preserved exactly: duplicate intent, currency mismatch, kill switch, stale/future intent, daily loss, single-intent loss and aggregate exposure.
50. Duplicate intent IDs are rejected by the existing gate; integration does not bypass or reset its registry.
51. A successful decision is always reported as `APPROVED_FOR_RESEARCH_ONLY`; no code path calls it execution approval.
52. If accounting validation fails, RiskGate is not invoked and the result is a distinct accounting validation failure.

## I. Determinism, isolation and safety

53. Same inputs and same configuration produce byte-for-byte equivalent normalized calculation outputs (excluding an explicitly injected generated-at timestamp).
54. Monetary/rate inputs reject Python floats and non-finite Decimal values.
55. All timestamps require timezone-aware UTC; naive and non-UTC timestamps fail validation.
56. Unit tests use synthetic fixtures only; no exchange or network calls occur.
57. Package tests run with network access disabled and still pass.
58. No private account access, secrets, environment credentials, database writes, persistent ledger or file writes occur.
59. No order submission/cancellation, execution adapter, leverage, margin, liquidation or position-sizing logic is introduced.
60. No files in the existing `btc-dashboard` repository are modified.

## J. Acceptance evidence required before merge

- Full local Windows test suite result supplied by the user.
- GitHub Actions full test suite green.
- Review confirms all assumptions and unresolved caveats are visible in docs and report output.
- Diff contains only approved Phase 1E simulator/spec/test files; no secrets or account data.
- No order/execution or account-access code.
- PR remains open and unmerged until explicit user approval.

## Explicit implementation policy inputs and caveats

- FX source is supplied per observation and recorded verbatim; no network FX client is included. `max_fx_age` is a required policy input with no implicit default. Synthetic FX is confined to clearly labelled tests.
- Fee/GST denomination and exchange-specific rounding remain configurable assumptions pending authoritative account/API reconciliation. Outputs must not claim exchange-reconciled ledger equivalence.
- Settlement-fee rate is explicit configuration; charge only for positions held through expiry/settlement, on settlement notional.
- Funding rate and mark price are explicit scenario inputs; positive means longs pay shorts, negative means shorts pay longs; apply each 8-hour event.
- Decimal values remain unrounded internally; quantize only at explicit reporting/ledger boundaries.
- RiskGate is USD-only; INR equivalents are display-only.

These are accepted implementation conventions, not a claim that all exchange-specific fee/account-ledger semantics have been independently verified.
