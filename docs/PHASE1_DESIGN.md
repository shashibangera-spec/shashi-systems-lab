# Phase 1 — Contract Verification and Market-Data Foundation

## Objective

Build a standalone Python application for Delta Exchange India's BTCUSD perpetual contract. Phase 1 is read-only: verify the instrument and consume public market data. It must not authenticate to a trading account or submit orders.

## BTCUSD contract facts — documentation verified, API runtime pending

Official Delta Exchange India contract specifications and help articles currently document:

- Product ID: `27`; symbol: `BTCUSD`
- Contract type: perpetual futures
- Contract value / lot size: `0.001 BTC`
- Minimum BTC futures order size: `0.001 BTC` (one lot)
- Order quantity: whole-number lots; do not send decimal BTC as the lot count
- Tick size: `0.50 USD`
- Price quotation: `USD per 1 BTC`
- Funding interval: `8 hours` (`28,800 seconds`)
- Maker/taker fees: `0.02% / 0.05%` before any applicable taxes/charges
- India contract specification page: margin and effective settlement currency shown as `INR`

**Important unresolved currency discrepancy:** Delta's India contract specification page says margin/effective settlement currency is INR, while the API documentation's BTCUSD example describes the contract as settled in USD and its sample product object shows a USD settling asset. These labels may describe different accounting fields or reflect documentation inconsistency. The verifier preserves the API's `settling_asset` separately and does not infer the margin currency. This discrepancy must be resolved from a current API response and Delta's authoritative clarification before any margin, PnL, or order-sizing implementation.

Sources:
- https://www.delta.exchange/en/contracts
- https://www.delta.exchange/support/solutions?articleId=80001177912
- https://www.delta.exchange/support/solutions?articleId=80001141030
- https://docs.delta.exchange/

These are documented facts, not a substitute for current runtime verification. Do not treat maximum leverage as a recommendation.

## Current implementation

`src/shashi_engine/contract_verification.py` performs a public unauthenticated GET to Delta India's `/v2/products` endpoint, selects BTCUSD and validates its identity, state, contract type, contract value, unit, tick, quote asset and funding interval. It records minimum order as one whole lot based on Delta's help-centre documentation. It deliberately does not infer margin currency.

Run locally from the repository root:

```bash
python scripts/verify_btcusd_contract.py
```

A successful run prints a timestamped JSON report. A failed request or unexpected required field exits non-zero. The verifier has no private API authentication or order methods.

## Architecture

```
Delta public REST / public WebSocket
              |
              v
      Market Data Adapter
              |
              v
       Normalized Models
              |
        +-----+------+
        |            |
        v            v
   Data Quality   Local Logs
        |
        v
   Health Status

Future, separately approved:
Signal Provider -> Risk Gate -> Order Manager -> Demo Adapter
                         |
                     Kill Switch
```

## Components

1. **Contract metadata** — fetch current product details and fail closed on missing or inconsistent required fields.
2. **Market-data adapter** — public ticker, mark price, trades, order book, funding and candle data. Reconnect safely and detect stale or missing data.
3. **Domain models** — typed representations for instrument metadata, ticker, order-book levels, trades, funding observations and candles.
4. **Data-quality layer** — timestamp sanity, sequence/gap checks where available, numeric validation and stale-feed detection.
5. **Local recorder** — structured local logs for diagnostics. No production database integration in Phase 1.
6. **Future risk/order interfaces** — design only; no order submission implementation.

## Milestones and acceptance gates

### 1A — Contract verification
- Run the public product verifier from a user-controlled local environment.
- Save the timestamped report as a local artifact; do not commit raw API dumps.
- Confirm current API response fields and resolve the INR/USD margin-settlement discrepancy.
- Independently confirm lot increment/minimum, fees and any applicable tax/charges.
- Fail closed if required metadata is missing or inconsistent.

### 1B — Public market data
- Reconfirm current India public REST and WebSocket endpoints against official documentation.
- Subscribe only to public BTCUSD market channels.
- Normalize messages and timestamps.
- Handle disconnect/reconnect and stale-feed conditions.
- No private WebSocket and no account authentication.

### 1C — Models and tests
- Unit-test metadata parsing and price/quantity precision.
- Test malformed, missing, stale and out-of-order messages.
- Use recorded synthetic fixtures; do not include account data or secrets.

### 1D — Risk controls (design and tests only)
- Specify maximum position, per-trade risk, daily loss limit, duplicate-intent prevention and emergency stop.
- No leverage is selected automatically.
- No order route is enabled.

### 1E — Demo execution
Not included in the current authorization. Requires separate explicit approval after 1A–1D pass. Demo credentials, if later needed, must be isolated from live credentials.

## Endpoint notes

The official India REST base URL in Delta's API onboarding material is:

- `https://api.india.delta.exchange`

Products endpoint:

- `GET /v2/products`

The demo REST/WebSocket URLs recorded in early planning notes have not yet been reconfirmed against current official documentation. Do not connect to them until verified.

## Non-negotiable safety rules

- No live orders.
- No production API credentials.
- No withdrawal permissions.
- No real-money account connection.
- No production database, dashboard, collector, alert or Pine changes.
- No automatic leverage selection.
- Any future order path must be disabled by default and fail closed.
- A kill switch must block new order intents before any execution adapter is enabled.

## Public repository hygiene

This repository is public by user choice. Do not commit secrets, credentials, private account information, personal identifiers, raw private API responses, or logs that may contain them. No secrets file should be tracked. Use `.env.example` only for placeholder variable names if needed later.
