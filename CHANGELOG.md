# Changelog

## Unreleased
- Phase 1F: add a local append-only JSONL recorder for public BTCUSD 30m WebSocket updates and completed candles.
- Add CONNECTED/STALE/DISCONNECTED feed-health monitoring and bounded REST recovery for missing completed intervals.
- Add synthetic tests for append-only behavior, duplicate protection, recovery gaps and feed-health transitions.
- Keep local recordings git-ignored; no private account access, database integration, order execution or changes to the existing BTC dashboard.

## 2026-11-21
- Phase 1E non-executing accounting simulator merged; roadmap labels reconciled.
