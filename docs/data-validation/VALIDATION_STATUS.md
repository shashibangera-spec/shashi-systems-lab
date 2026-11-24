# Data Validation Status — Shashi Systems Lab

**Repository:** `shashibangera-spec/shashi-systems-lab`  
**Role:** Algorithmic trading research, strategy and execution-logic research  
**Registry status:** Draft for review  
**Last inventory:** 2026-11-24  
**Source commit reviewed:** `842c5e25b7335ff84af279d611b73c0e74c95911`

## Status vocabulary

- **PASS** — exact check completed successfully with linked evidence.
- **CONDITIONAL** — evidence supports only the stated scope and qualifications.
- **OPEN** — unresolved finding or work item.
- **FAIL** — a check was run and failed.
- **NOT VERIFIED** — not checked in this validation.
- **SUPERSEDED** — replaced by a later linked baseline.

A phase marked closed in a README or acceptance document does not prove its tests ran. Link the exact Actions run, command output and test case names before marking execution evidence PASS.

## Project boundary

The documented project scope is BTCUSD perpetual market-data recording and offline research using local append-only JSONL data. The inspected phase documents do not establish a production dashboard/database connection, live account access, or live order submission. Keep research approval distinct from execution approval.

## Accepted documented baselines

### SYS-BASE-001 — Phase 1A currency and fees
**Status: CONDITIONAL — documented reference, not live account verification**

The Phase 1A notes identify Delta Product API product 27 as BTCUSD and record `settling_asset: USD`. Delta India documentation distinguishes USD denomination/notional settlement representation from INR effective margin/account-ledger treatment. The notes use 85 INR/USD as a documented conversion reference at that time; it is not a live FX quote or an approved hard-coded execution conversion.

Documented fee assumptions:
- Maker fee: 0.02%.
- Taker fee: 0.05%.
- GST: 18% on the trading fee.
- Funding: separate periodic cash flow (8-hour cycle), not a trading fee.
- Settlement fee may apply separately.

These are research assumptions and documentation references, not current account-tier, live fee or order evidence.

### SYS-BASE-002 — Phase 1D risk controls
**Status: CONDITIONAL — design/acceptance scope**

The documented risk-control layer is research-intent only. It does not establish Delta account access, order sizing, leverage selection, order submission/cancellation, or persistent execution state. Currency must be explicit; there must be no implicit USD/INR conversion. Duplicate intent IDs are rejected, but the documented registry is in-memory and resets on process restart. A kill switch blocks new intents. `APPROVED_FOR_RESEARCH_ONLY` is not execution approval.

Treat the phase as a design specification unless actual test evidence is linked.

### SYS-BASE-003 — Phase 1E accounting simulator
**Status: CONDITIONAL — acceptance specification recorded**

The README describes Phase 1E as closed. The acceptance material specifies Decimal-based calculations; explicit product contract metadata and FX observations; separation of USD and INR; separate accounting for fees, GST, funding and settlement; and blocking fabricated net results when funding data is missing. RiskGate is USD-only and research-only. Fixtures are synthetic, with no network, database, account or order access.

The acceptance specification is not itself proof that the test suite executed successfully.

### SYS-BASE-004 — Phase 1F recorder and feed recovery
**Status: CONDITIONAL — acceptance specification recorded**

The documented design includes append-only JSONL, canonical candle identity, duplicate suppression, fail-closed malformed data handling, explicit feed states, bounded UTC REST recovery, no synthetic candles, and no promotion of unfinished candles to completed records. Public market endpoints are distinguished from account/order APIs.

Fixture tests and a live REST validation are different evidence types; do not conflate them.

### SYS-BASE-005 — Phase 1G JSONL history integrity
**Status: CONDITIONAL — acceptance specification recorded**

The acceptance material covers source-byte SHA-256 and file size; malformed, invalid UTF-8, blank and unterminated records; BTCUSD/30m identity; interval and OHLCV validity; duplicates, out-of-order records and gaps; read-only REST gap validation; prohibition on synthetic records; append-prefix preservation; and exclusion of local data from Git.

The specification does not prove that CI ran those tests or that a particular local recording passed an audit.

### SYS-BASE-006 — Phase 1H soak
**Status: OPEN — under review**

The documented soak design calls for 2-hour/4-hour recording, three sessions, two controlled restart boundaries, a shared output path, per-session integrity reports, prefix-hash preservation and explicit unexplained-gap/duplicate reporting.

A short soak cannot certify long-term reliability. A soak with no gap does not, by itself, exercise the recovery path.

### SYS-BASE-007 — Phase 1I AMT/PA offline backtester
**Status: OPEN — PR/acceptance pending**

The README describes Phase 1I as open/unmerged pending approval. The acceptance scope includes:
- Delta BTCUSD product ID 27.
- 30-minute candle integrity and completed candles only.
- 05:30 IST session reset, 48-bar session.
- $50 TPO row size and 70% value area.
- Deterministic tie-breaking and no lookahead.
- Next-open entry convention.
- Explicit stop/target collision handling and funding events.
- No I/O inside the backtest engine.
- Public GET access only in the CLI.
- No database, Pine, collector or order-execution integration.

Do not treat the acceptance document as a completed validation or as authorization to merge.

### SYS-BASE-008 — Phase 1J testnet
**Status: NOT STARTED — future and conditional**

No testnet execution is established by the inspected documents. Any future testnet work requires its own explicit scope, authorization and evidence.

## Open evidence gaps

| ID | Evidence gap | Required evidence |
|---|---|---|
| SYS-OPEN-001 | Phase 1D risk-control execution evidence | Exact CI run, command, test files/cases and result |
| SYS-OPEN-002 | Phase 1E accounting simulator CI evidence | Exact Actions URL and executed test list |
| SYS-OPEN-003 | Phase 1F recorder/recovery CI evidence | Exact Actions URL and executed test list |
| SYS-OPEN-004 | Phase 1G history-integrity CI evidence | Exact Actions URL and executed test list |
| SYS-OPEN-005 | Phase 1H soak evidence | Session logs, restart boundaries, integrity reports and prefix hashes |
| SYS-OPEN-006 | Phase 1I review/acceptance | PR status, review decision and actual test evidence |
| SYS-OPEN-007 | Dataset provenance | Exact local dataset identity, byte size, SHA-256 and date/time coverage |

## Validation register

| Validation ID | Date | Scope | Outcome | Evidence / limitation |
|---|---|---|---|---|
| SYS-INV-20261124 | 2026-11-24 | README and Phase 1A, 1D, 1E, 1F, 1G, 1H and 1I documentation inventory | CONDITIONAL | Documentation inventory only; no local recording/replay, pytest run, recorder execution or exchange request performed |

## Evidence rules

For test claims, record exact test file paths and test case names, command, collected/executed counts, pass/fail/skip/deselected counts, Actions run URL and job. For data claims, record dataset identity, source, symbol, timeframe, timezone, time range, file size and SHA-256. Mark unperformed checks NOT VERIFIED.

## Safety boundary

This registry commit is documentation-only. It does not authorize strategy/code changes, local data mutation, database activity, collector execution, exchange calls, deployment, testnet activity or live trading.