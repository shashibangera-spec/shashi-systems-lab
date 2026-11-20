# Shashi Systems Lab

A standalone research and engineering workspace for a modular market-data and simulated-execution system.

## Current scope

**Phase 1 — BTCUSD perpetual contract verification and market-data foundation.**

- Verify instrument metadata from Delta Exchange's public API.
- Consume public market data only.
- Normalize market data into typed internal models.
- Record data quality and connection health.
- Design order and risk interfaces without submitting orders.

## Safety boundaries

- No live trading or live order submission.
- No production exchange credentials.
- No withdrawal permissions.
- No connection to the existing BTC dashboard or its production database.
- No strategy signals connected to execution.
- Demo execution requires separate approval after Phase 1 validation.

## Public repository warning

This repository is public. Never commit API keys, credentials, account identifiers, private URLs, personal data, or exchange account exports. Use local environment variables for future private configuration. Keep secrets out of issues, commits, logs, and screenshots.

## Project status

See [Phase 1 design](docs/PHASE1_DESIGN.md). Phase 1A currency/fee research is documented in [Phase 1A closure](docs/PHASE1A_CURRENCY_AND_FEES.md); non-executing controls are documented in [Phase 1D](docs/PHASE1D_RISK_CONTROLS.md). The repository does not place orders.
