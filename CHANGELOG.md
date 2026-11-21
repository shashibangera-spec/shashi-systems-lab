# Changelog

## Unreleased
- Phase 1I: reconcile Setup A pullback-order lifecycle counters without double-counting: `filled` counts every executed limit fill (including fills later rejected by the R:R gate), accepted trades and post-fill rejections are separate, resting-limit and gap-through fills are separated, and machine-checkable funnel identities are included in reports. Add opt-in `--pullback-maker-entry`: resting fills at the limit use maker entry fees; gap-through fills at the opening price, Setup B next-open entries, and all exits remain taker. The runner fee-adjusted breakeven stop uses the actual maker/taker entry fee plus conservative taker exit fee. Default remains all-taker.
- Phase 1I: add opt-in `--pullback-entry` for Setup A only (default off) with `--pullback-limit-bars` (default 3). After a completed rejection signal, rest a limit at the original prior-session VAL (long) or VAH (short); fill only on a touch within the next N completed 30m candles, use a better opening price when gapped through, cancel on initial ATR-stop breach, and never chase. Recalculate the nearest AMT Target 1, next-AMT runner target and 1.0R entry filter from the actual fill; preserve the frozen ATR stop, partial and fee-adjusted runner breakeven rules. Do not evaluate Target 1 on the intrabar fill candle. Record placed, filled, expired, invalidated, R:R-rejected and end-of-data-pending order counts.
- Phase 1I: add opt-in `--runner-next-amt-target` (default off): record the nearest completed prior-session VAH/POC/VAL strictly beyond Target 1 at entry; after the confirmed 50% partial, keep the fee-adjusted breakeven stop with stop-first same-candle priority and exit the runner at that AMT reference. If no second reference exists, retain breakeven-only fallback and record the reason in the trade ledger. Requires `--runner-breakeven`.
- Phase 1I: add optional `--stop-atr-multiplier` initial-stop padding (default `0` preserves the one-tick baseline); positive values place the stop the selected signal-candle ATR multiple beyond the signal candle extreme, rounded outward to the instrument tick. Entry and runner 1.0R gates recalculate from each variant's resulting stop. Add tests for 0, 0.25 and 0.50 multipliers; no other strategy rules change.
- Phase 1I: add a diagnostic-only MAE/MFE script for the frozen 90-day BTCUSD window; re-fetch and validate all 4,320 public 30m candles, replay the unchanged rules, verify all 28 trades against the reference report, and report signal-ATR-normalized in-trade excursions, stop-candle breach size, and post-stop original-target recovery. No strategy rules or source reports are modified.
- Phase 1I: add opt-in `--min-first-target-rr` entry eligibility filter (default off); record each rejected low-R:R setup with entry, stop, nearest AMT target, source and computed R:R in the JSON report and console output.
- Phase 1I: add an optional minimum first-target R:R gate for fee-adjusted runner breakeven activation; the gate is activation-only, defaults to no gate for the always-breakeven comparator, and leaves entries, initial stops, targets and sizing unchanged.
- Phase 1I: add opt-in fee-adjusted runner breakeven after a completed-candle 50% target confirmation; activation begins on the following candle and includes runner entry/exit taker fees plus GST.
- Phase 1I: make signal-bar start, signal-close boundary and next-bar entry-open timestamps explicit; correct runner lot reporting when no partial exit occurs.
- Phase 1I: add a strict same-candle stop-first regression test and separate normal strategy-exit metrics from administrative end-of-data liquidations while preserving the all-trades summary.
- Phase 1I: add a bounded public Delta REST historical fetch option for 1–90 complete 05:30 IST sessions; verify exact candle coverage and keep the append-only recorder JSONL untouched.
- Phase 1I: add offline Delta India BTCUSD perpetual 30m AMT + Price Action research backtester.
- Reuse the Phase 1B public candle/product metadata adapters and Phase 1E Decimal accounting for fees, GST and explicit 8-hour funding events.
- Reconstruct complete 05:30 IST AMT sessions with fixed $50 TPO rows and 70% value area; exclude developing-session references from profit targets.
- Add deterministic Setup A failed-auction/rejection and Setup B acceptance/retest rules, next-open entries, stop-first ambiguity handling, 50% partial exits and structural runner exits.
- Add synthetic tests and formal Phase 1I specification/acceptance criteria; no private account access, order execution, production dashboard, database, collector or Pine changes.

- Fix Delta REST gap recovery to ignore only adjacent start/end boundary candles and process only timestamps inside the requested half-open gap; retain duplicate, ordering and unrelated out-of-range validation.
- Normalize Delta newest-first REST candle responses by rejecting duplicates, filtering adjacent boundary candles, then sorting and validating requested timestamps chronologically before recovery or audit.
- Add recorder and read-only history-audit regression tests for harmless REST boundary candles and unrelated out-of-range responses.
- Phase 1H: add a focused 2–4-hour public BTCUSD recorder soak runner with three bounded sessions and two controlled clean restarts.
- Verify append-only byte-prefix integrity and run Phase 1G history/restart audits after each session; save run-level JSON/Markdown reports locally.
- Add synthetic tests for soak duration allocation and prefix hashing; no credentials, private account access or order execution.

- Phase 1G: add read-only JSONL history audit, optional public REST gap validation, restart/append integrity checks and data-quality reports.
- Add synthetic tests for malformed history, provenance, gaps, recovery reports, restart deduplication and append continuity.
- Keep Phase 1G non-executing; the audit never rewrites source history or automatically fills gaps.

- Phase 1F: add a local append-only JSONL recorder for public BTCUSD 30m WebSocket updates and completed candles.
- Add CONNECTED/STALE/DISCONNECTED feed-health monitoring and bounded REST recovery for missing completed intervals.
- Add synthetic tests for append-only behavior, duplicate protection, recovery gaps and feed-health transitions.
- Keep Phase 1F local and non-executing; no credentials, private account access, database integration, order execution or changes to the existing BTC dashboard.

## 2026-11-21
- Phase 1F local public-data recorder and REST recovery merged after CI and user-run Windows/live recording validation.
- Phase 1E non-executing accounting simulator merged; roadmap labels reconciled.
