# Shashi Systems Lab

A standalone research and engineering workspace for a modular market-data and simulated-execution system.

## Current scope

**Phase 1 — BTCUSD perpetual contract verification and market-data foundation.**

- Verify instrument metadata from Delta Exchange's public API.
- Consume public market data only.
- Normalize market data into typed internal models.
- Record public market data locally in append-only JSONL.
- Monitor feed freshness and connection health.
- Recover missing completed 30-minute candles from public REST.
- Keep risk and accounting research separate from all execution.

## Safety boundaries

- No live trading or live order submission.
- No production exchange credentials.
- No withdrawal permissions.
- No connection to the existing BTC dashboard or its production database.
- No strategy signals connected to execution.
- No live trading, production credentials, private account access or production integrations.
- Strategy research and Delta Exchange Testnet demo execution are conditional future milestones after Phase 1H acceptance and separate scoped reviews; no live execution is authorized.

## Public repository warning

This repository is public. Never commit API keys, credentials, account identifiers, private URLs, personal data, or exchange account exports. Use local environment variables for future private configuration. Keep secrets out of issues, commits, logs, and screenshots.

## Project status

See [Phase 1 design](docs/PHASE1_DESIGN.md) for the reconciled milestone roadmap. Phase 1A currency/fee research is closed in [Phase 1A documentation](docs/PHASE1A_CURRENCY_AND_FEES.md); non-executing risk controls are documented in [Phase 1D](docs/PHASE1D_RISK_CONTROLS.md).

- **Phase 1E — CLOSED:** non-executing accounting simulator. See [specification](docs/PHASE1E_ACCOUNTING_SIMULATOR_SPEC.md) and [acceptance tests](docs/PHASE1E_ACCEPTANCE_TESTS.md). RiskGate remains USD-only; INR equivalents require explicit fresh FX and are display-only.
- **Phase 1F — CLOSED:** append-only local recorder, feed-health monitoring and REST gap recovery. See [specification](docs/PHASE1F_RECORDER_SPEC.md) and [acceptance tests](docs/PHASE1F_ACCEPTANCE_TESTS.md).
- **Phase 1G — UNDER REVIEW:** JSONL history audit, read-only REST gap validation, restart/append integrity and data-quality reporting. See [specification](docs/PHASE1G_HISTORY_INTEGRITY_SPEC.md) and [acceptance tests](docs/PHASE1G_ACCEPTANCE_TESTS.md).
- **Phase 1H — NOT AUTHORIZED:** demo execution requires separate explicit approval.

The repository uses public market data only and does not place orders or connect to the existing BTC dashboard or its production database.
