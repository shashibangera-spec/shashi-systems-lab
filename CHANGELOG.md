# Changelog

## Unreleased
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

- Phase 1G: add read-only JSONL history audit, optional public REST gap validation, restart/append integrity checks and JSON/Markdown data-quality reports.
- Add synthetic tests for malformed history, provenance, gaps, recovery reports, restart deduplication and append continuity.
- Keep Phase 1G non-executing; the audit never rewrites source history or automatically fills gaps.

- Phase 1F: add a local append-only JSONL recorder for public BTCUSD 30m WebSocket updates and completed candles.
- Add CONNECTED/STALE/DISCONNECTED feed-health monitoring and bounded REST recovery for missing completed intervals.
- Add synthetic tests for append-only behavior, duplicate protection, recovery gaps and feed-health transitions.
- Keep local recordings git-ignored; no private account access, database integration, order execution or changes to the existing BTC dashboard.

## 2026-11-21
- Phase 1F local public-data recorder and REST recovery merged after CI and user-run Windows/live recording validation.
- Phase 1E non-executing accounting simulator merged; roadmap labels reconciled.
