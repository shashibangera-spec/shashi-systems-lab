# Phase 1G — Acceptance Tests

## A. JSONL audit

1. A valid contiguous synthetic history is accepted and its bytes remain unchanged.
2. SHA-256 and file byte count match the exact source bytes.
3. Invalid UTF-8, malformed JSON, blank lines and an unterminated final line are reported.
4. Canonical records require exact BTCUSD/30m identity and matching record type/source provenance.
5. Candle start/end must form an exact 30-minute interval and OHLCV must satisfy the shared Candle model.
6. Duplicate starts, out-of-order canonical records and internal missing intervals are reported.
7. Recovery reports must reconcile requested = recovered + unresolved; unresolved timestamps must be UTC.
8. Any integrity defect prevents an acceptable result.

## B. REST gap validation and recovery

9. Read-only REST validation checks only bounded, UTC-aligned internal gaps.
10. Valid returned candles are listed; intervals absent from REST remain unresolved.
11. Duplicate, out-of-order, out-of-window or wrong-symbol/resolution results are rejected.
12. The REST validation path does not modify the input file.
13. Existing Phase 1F recovery writer is exercised with synthetic fixtures: valid returned candles append with REST provenance and unresolved starts are reported; invalid response batches fail before any recovered candle write.

## C. Restart and append integrity

14. Reopening a valid log leaves exact input bytes and SHA-256 unchanged.
15. Reopening restores latest canonical candle identity.
16. A previously recorded candle remains deduplicated after restart.
17. A new later candle appends and all prior bytes remain an exact prefix.
18. No cross-process locking guarantee is claimed.

## D. Report and CLI

19. JSON and Markdown reports include counts, coverage, gap/duplicate/order status, recovery unresolved count, provenance and safety metadata.
20. Default report outputs are under git-ignored `data/`; the input recording is never modified.
21. REST access occurs only with explicit `--check-rest-gaps`; all requests use the existing unauthenticated public GET adapter.
22. Exit status is nonzero when the audited history is unacceptable or restart verification fails.

## E. Final gates

23. Full local Windows pytest suite passes.
24. GitHub Actions passes on the exact PR head commit.
25. No recordings, credentials, private account data or other local artifacts are committed.
26. Phase 1F recorder behavior and the separate BTC dashboard remain untouched.
27. PR stays open and unmerged until explicit user approval.

All automated tests use synthetic candles and temporary files. A live public REST gap check and audit of the user's actual local recording are optional, separate, read-only acceptance activities.
