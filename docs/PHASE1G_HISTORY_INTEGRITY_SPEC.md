# Phase 1G — Historical JSONL Integrity, Recovery Validation and Data-Quality Reporting

## Status

Approved implementation scope; implementation is proposed on a separate branch and must remain in an open, unmerged PR until review and user approval.

## Objective

Establish deterministic evidence that local Phase 1F BTCUSD 30-minute recordings are structurally sound, chronologically coherent, recoverable through public REST where data is available, and safe to reopen and append to. Phase 1G is a read-only audit/research toolset plus synthetic tests. It does not alter trading logic or the recorder's existing storage contract.

## Scope

### 1. JSONL history audit

- Read the selected JSONL file as bytes first and calculate SHA-256, byte length and a before-state fingerprint.
- Require UTF-8, newline-terminated records, nonblank lines, valid JSON objects and a string `record_type`.
- Validate canonical candle records (`completed_candle`, `rest_recovery`) for BTCUSD, 30m resolution, exact source/type pairing, UTC half-hour alignment, start/end consistency, finite Decimal OHLCV and the existing Candle domain invariants.
- Report duplicate canonical candle starts, out-of-order canonical records and missing 30-minute intervals between the earliest and latest canonical candle.
- Validate recovery-report arithmetic: requested intervals must equal recovered count plus unresolved count; unresolved starts must be UTC timestamps.
- Report, never sort, deduplicate, rewrite, truncate or repair. A defect makes the report unacceptable.

### 2. REST recovery gap-fill validation

- Offer an explicit opt-in public REST check for internal missing intervals only.
- Check bounded, UTC-aligned windows (48 intervals by default) using the existing public REST adapter.
- Require unique, ordered, in-range BTCUSD 30m results.
- Report each returned and unresolved interval.
- This check is non-mutating: it does not append candles, change the JSONL file or create synthetic data. Actual gap-fill writing remains the existing Phase 1F `recover_missing_candles` function and is covered by synthetic tests in temporary directories.

### 3. Restart/append integrity

- Reopen the selected file through `AppendOnlyJsonlRecorder` and compare exact bytes and SHA-256 before/after initialization.
- Report latest canonical candle start restored from history.
- Synthetic tests verify that duplicate protection is reconstructed after restart, duplicate candles are skipped and a new later candle appends without changing any prior byte.
- One process per file remains required; cross-process locking is not added.

### 4. Data-quality report

- Generate JSON and Markdown reports with file fingerprint, record counts, WebSocket/REST canonical counts, time coverage, gaps, duplicates, ordering defects, unresolved recovery intervals and validation issues.
- Include explicit safety metadata: public/read-only, unauthenticated, no writes to input history, no automatic gap filling.
- Exit nonzero when the history audit is unacceptable or requested restart integrity check fails. REST gaps remain clearly reported; they are not silently repaired.

## CLI

From repository root:

```powershell
python scripts/audit_btcusd_history.py --input data/market_data/btcusd_30m.jsonl
python scripts/audit_btcusd_history.py --restart-check
python scripts/audit_btcusd_history.py --check-rest-gaps --max-recovery-intervals 48
```

Default reports are written under git-ignored `data/reports/`. The input JSONL is never modified. `--check-rest-gaps` is opt-in and uses only public unauthenticated REST GET requests.

## Non-goals and safety boundaries

- No automatic file repair, sorting, deduplication, compaction, deletion or rewriting.
- No automatic REST gap filling by the audit CLI; no fabricated candles.
- No database, cloud storage, dashboard, alerts, credentials, private endpoints or account data.
- No strategy signals, backtests, order sizing, margin, PnL or order execution.
- No changes to Phase 1F recorder behavior or the separate `btc-dashboard` repository.
- No cross-process file locking or claim of crash-proof atomic append beyond the existing fsync behavior.

## Acceptance gate

1. Synthetic tests cover valid history, malformed/unterminated JSONL, invalid provenance/schema, duplicates, ordering, missing intervals and recovery-report consistency.
2. REST gap validation rejects duplicates, out-of-order and out-of-window candles before producing a valid result; unresolved intervals remain explicit.
3. Reopen test proves byte-for-byte unchanged history and reconstructed duplicate protection.
4. Append-after-restart test proves the old bytes remain an exact prefix and the new record is valid.
5. JSON and Markdown reports are deterministic apart from their generated-at timestamp and accurately identify safety boundaries.
6. Full pytest suite and GitHub Actions pass on the exact PR head.
7. Local Windows audit against the user's actual recording is a separate acceptance step; raw recording data must not be committed.
8. PR remains open and unmerged pending user review and explicit approval.
