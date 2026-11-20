# Phase 1F — Acceptance Tests

## A. Append-only local JSONL

1. A new output path creates parent directories and appends valid JSONL records.
2. Each record includes `record_type` and `recorded_at_utc`.
3. Multiple records remain in append order.
4. Canonical candle timestamps are unique across the existing file and current process.
5. Reopening an existing valid file rebuilds canonical candle identity without changing prior bytes.
6. A duplicate canonical candle is skipped; the original record is not rewritten.
7. Existing malformed JSON, blank lines, unterminated final lines or malformed canonical timestamps fail closed.
8. Generic append cannot bypass the canonical candle deduplication path.
9. JSON serialization rejects non-serializable and non-finite values.
10. Output under `data/` remains git-ignored.

## B. Feed health

11. Connection establishment emits CONNECTED.
12. No first candle update within the stale threshold emits STALE.
13. A message arriving after STALE emits CONNECTED.
14. Connection close/error emits DISCONNECTED.
15. Repeated checks in the same state do not emit duplicate transition records.
16. Reconnection resets the freshness clock; an old pre-disconnect message does not make a new connection instantly stale.
17. Naive/non-UTC timestamps and non-positive stale thresholds are rejected.

## C. REST recovery

18. Recovery requests only UTC-aligned half-hour windows.
19. A zero-length recovery window performs no REST request and writes no record.
20. Recovery enforces a configurable maximum number of intervals.
21. Only BTCUSD 30m candles inside the requested window are accepted.
22. Duplicate, out-of-order or out-of-window REST candles fail closed before any recovered candle is written.
23. Returned valid candles are appended with `record_type=rest_recovery` and `source=rest`.
24. Missing REST intervals are listed explicitly as unresolved; no synthetic candles are created.
25. A recovery report records requested bounds, recovered count and unresolved starts.
26. Existing canonical candles are never overwritten.

## D. WebSocket runner

27. The runner subscribes only to the public BTCUSD `candlestick_30m` channel.
28. Candle identity requires explicit `cst` / `candle_start_time`; event timestamp `ts` is never used as candle identity.
29. Every valid WebSocket update is appended with WebSocket provenance.
30. A previous bucket is marked completed only after a later bucket is observed and the previous update was not stale.
31. An unfinished bucket is not promoted to completed when a connection closes.
32. Startup/reconnect/rollover gaps use the REST recovery path.
33. Session duration is bounded and configurable; connection retries do not run indefinitely past the requested duration.
34. No API key, private channel, account endpoint, order endpoint or database is accessed.

## E. Validation and merge gates

35. Full local Windows pytest suite passes.
36. GitHub Actions passes on the exact PR head commit.
37. Review confirms `data/` is git-ignored and no recording, credential or account data is committed.
38. PR diff is limited to Phase 1F code, tests, documentation and roadmap/changelog reconciliation.
39. No file in the separate `btc-dashboard` repository is changed.
40. PR remains open and unmerged until explicit user approval.

Tests use synthetic candles and temporary local paths only. Live WebSocket/REST validation is a separate user-run acceptance step; CI does not need network access.
