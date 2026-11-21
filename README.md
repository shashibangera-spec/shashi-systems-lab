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
- **Phase 1G — CLOSED:** JSONL history audit, read-only REST gap validation, restart/append integrity and data-quality reporting. See [specification](docs/PHASE1G_HISTORY_INTEGRITY_SPEC.md) and [acceptance tests](docs/PHASE1G_ACCEPTANCE_TESTS.md).
- **Phase 1H — UNDER REVIEW:** focused 2–4-hour recorder soak with three sessions, two controlled restarts and per-session integrity audits. See [specification](docs/PHASE1H_FOCUSED_SOAK_SPEC.md) and [acceptance tests](docs/PHASE1H_ACCEPTANCE_TESTS.md).
- **Phase 1I — IMPLEMENTATION PR OPEN:** Delta India BTCUSD perpetual 30m AMT + Price Action offline backtester; no execution adapter. See [specification](docs/PHASE1I_AMT_PA_BACKTESTER_SPEC.md) and [acceptance tests](docs/PHASE1I_ACCEPTANCE_TESTS.md).
- **Phase 1J — PLANNED, CONDITIONAL:** isolated Delta Exchange Testnet demo execution after Phase 1H and strategy gates; never live trading.

The repository uses public market data only and does not place orders or connect to the existing BTC dashboard or its production database.

## Phase 1J — local India Testnet read-only check

This is a **read-only snapshot utility**, not an execution bot. The client exposes only fixed GET calls for product 27 metadata, positions, open orders, fills and wallet balances. It has no order, cancel, amend, POST, PUT or DELETE operation. It is hard-wired to `https://cdn-ind.testnet.deltaex.org`; production India and Global Testnet hosts are excluded. Redirects and environment-configured HTTP proxies are disabled.

### Windows setup

1. Create a separate **Delta Exchange India Demo/Testnet** API key. Use a separate **Demo/Testnet-only** key and an IP allowlist if Delta offers it. Do not use a production key. Important: Delta's REST API reference explicitly says Orders, Positions and Wallet endpoints require **Trading** permission, even for GET requests. That means the key may have exchange trading capability if it is compromised, although this repository's client exposes only fixed GET operations and contains no order mutation methods. Use this key only if you accept that credential-level risk; never use it outside the local Demo/Testnet account. Do not grant this permission to any production key.
2. In PowerShell, from the repository folder:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install --upgrade pip
py -m pip install -e ".[dev]"
Copy-Item .env.example .env
notepad .env
```

3. In the local `.env` file, replace the two placeholder values with the Demo/Testnet key and secret. Save it. The `.env` file is git-ignored. Never paste credentials into ChatGPT, GitHub, screenshots, or logs.
4. Run the read-only check:

```powershell
py scripts\phase1j_testnet_readonly_check.py
```

5. Expected success output includes `"environment": "DELTA_INDIA_TESTNET"`, product `27 / BTCUSD`, and `"execution_authorized": false`. A nonzero position or any open order is a finding to investigate, not permission to trade. Keep the full report local because it contains private account information.

If the script reports missing credentials, verify the two variable names exactly. If it reports HTTP 401/403 or an API permission error, check the Demo key, timestamp/Windows clock and IP allowlist; **do not switch to production or enable Trading permission as a workaround**. If it reports network or signature errors, stop and share only the sanitized error text.

This snapshot is not yet a complete ledger reconciliation: API pagination, fee/funding history completeness, account-key permission behavior and Windows execution still need verification. No orders are submitted, changed or cancelled. A successful read-only check does not authorize any Testnet order.
