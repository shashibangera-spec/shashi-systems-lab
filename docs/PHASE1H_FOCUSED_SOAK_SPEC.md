# Phase 1H — Focused Recorder Soak and Controlled Restart Validation

## Status

Proposed implementation on a separate branch/PR. It must remain unmerged until CI and user-run Windows acceptance pass and the user explicitly approves merge.

## Objective

Validate the Phase 1F public BTCUSD 30-minute recorder over a focused **2–4 hours of active recording**, split across three independent recorder processes with exactly two controlled stop/restart boundaries. Reuse Phase 1G audit tooling after each segment. The test is designed to gather short-window operational evidence without requiring a 24–72-hour laptop run.

This is a focused soak, not proof of long-term production reliability.

## Run design

- Default active recording time: 7,200 seconds (2 hours).
- Allowed active recording time: 7,200–14,400 seconds (2–4 hours).
- Exactly three recorder sessions, producing two controlled clean stops and restarts.
- Active recording time is divided as evenly as possible across the three sessions.
- Default pause between sessions: 15 seconds; configurable from 0–300 seconds.
- Every session uses the same existing JSONL output path and the existing Phase 1F recorder.
- No parallel recorder processes are launched.
- The runner waits for each bounded recorder process to exit normally before starting the next.
- The runner does not force-kill a recorder as a planned restart. A bounded timeout is a test failure.

## Per-session sequence

1. If a history file already exists, run a fail-closed Phase 1G audit/restart preflight before the first session.
2. Record the existing file byte count and SHA-256.
3. Launch one Phase 1F recorder process for the assigned segment duration.
4. Wait for clean process termination and capture its exit code and bounded console output.
5. Verify the file is at least as long as before and that the complete pre-session byte prefix has the same SHA-256.
6. Run Phase 1G JSONL audit with restart integrity enabled.
7. Optionally pass `--check-rest-gaps` to validate any internal missing intervals through public unauthenticated REST without writing returned candles.
8. If integrity gates pass, pause briefly and start the next process against the same path.

The final report records each session, audit result, restart boundary, prefix check, timestamps, exit codes and safety assertions. JSON and Markdown reports are written under git-ignored `data/reports/`.

## CLI

From the repository root on Windows PowerShell:

Install dependencies if needed:

```powershell
python -m pip install -e ".[market-data,dev]"
```

Default two-hour run:

```powershell
python scripts/run_btcusd_soak.py
```

Four-hour active recording:

```powershell
python scripts/run_btcusd_soak.py --total-recording-seconds 14400
```

Two-hour run with optional read-only REST gap validation after each segment:

```powershell
python scripts/run_btcusd_soak.py --total-recording-seconds 7200 --check-rest-gaps
```

Reports:

- `data/reports/phase1h_soak_<UTC timestamp>.json`
- `data/reports/phase1h_soak_<UTC timestamp>.md`
- Per-session Phase 1G audit reports with the same run identifier.

The runner appends to the selected history; it never resets or replaces the file. Do not run another recorder against the same path concurrently.

## Acceptance gates

1. Full Windows pytest suite passes.
2. The soak completes all three recorder sessions and exactly two clean process restarts.
3. Every recorder process exits with code 0.
4. Each of the two restart boundaries passes append-prefix integrity: all bytes present before the next session remain byte-for-byte unchanged afterward.
5. Initial preflight (when an existing file is present) and all three post-session Phase 1G audits pass.
6. No malformed JSONL, duplicate canonical candle starts, out-of-order canonical candles, unexplained missing intervals or unresolved recovery intervals.
7. Feed health, reconnects and recovery reports are retained in the local JSONL; any transient disconnect/error is disclosed in the report.
8. No forced termination, input-history rewrite, credential use, private account access or order submission.
9. GitHub Actions passes on the exact PR head.
10. No local market-data recordings or reports are committed; `data/` remains git-ignored.
11. No changes to the separate BTC dashboard, Pine scripts, production collectors or production databases.

A clean run is evidence for this exact 2–4-hour window and the two tested restart boundaries only. If no real data gap occurs, REST gap-fill behavior is marked **not exercised in this soak**; synthetic Phase 1F/1G tests remain the evidence for that branch. Do not manufacture missing candles or deliberately corrupt the live recording to force a recovery test.

## Explicit exclusions

- No strategy signals, backtesting, position sizing, margin or PnL work in Phase 1H.
- No authenticated API calls, account data, private WebSocket channels, demo/testnet or live order routes.
- No file repair, truncation, compaction, sorting, deduplication or automatic gap filling by the soak runner.
- No cloud database, dashboard, Telegram, external alert or production integration.
- No claim of long-term reliability from a short soak.

## Next milestones (conditional, separate approvals)

### Phase 1I — Strategy research and validation

After Phase 1H passes, define a strategy specification before implementation. Separate market-data features, signal rules, completed-candle timing, fees/funding/slippage assumptions, risk limits, walk-forward/out-of-sample evaluation and paper/simulation results. No execution adapter in this phase.

### Phase 1J — Delta Exchange Testnet demo execution

The user has requested this as the intended next engineering milestone after Phase 1H and strategy review. It must be a separately scoped implementation and PR. Before coding, verify current official Testnet endpoints and contract behavior. Use Testnet-only credentials and a hard allowlist for Testnet hosts; fail closed if the host, environment or product identity is not Testnet. No production credentials, live endpoint fallback, withdrawals or real-money orders. Include an explicit kill switch, order-size/risk caps, idempotency, audit logs, and tests proving live hosts are rejected. This does not authorize live trading.

