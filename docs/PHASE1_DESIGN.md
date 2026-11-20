# Phase 1 — Contract Verification and Market-Data Foundation

## Objective

Build a standalone Python application for Delta Exchange India's BTCUSD perpetual contract. Phase 1 is read-only: verify the instrument and consume public market data. It must not authenticate to a trading account or submit orders.

## Contract facts to verify at runtime

The public product lookup performed during project planning reported:

- Product ID: `27`
- Symbol: `BTCUSD`
- Contract type: `perpetual_futures`
- Product state: `live`
- Trading status: `operational`
- Contract value: `0.001 BTC`
- Tick size: `0.50 USD`
- Quote and settlement asset: `USD`
- Funding interval: `28,800 seconds (8 hours)`
- Published maker/taker commission: `0.02% / 0.05%`

These are planning-time observations, not constants to trust indefinitely. Fetch current official product metadata at runtime and fail closed if required fields are missing or inconsistent. Minimum order quantity, quantity increment/precision, and margin asset must be independently confirmed before any order-related implementation. Do not treat the exchange's displayed maximum leverage as a recommendation.

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

1. **Contract metadata** — fetch product details; validate symbol, product ID, state, tick size, contract value, precision and minimum order constraints.
2. **Market-data adapter** — public ticker, mark price, trades, order book, funding and candle data. Reconnect safely and detect stale or missing data.
3. **Domain models** — typed representations for instrument metadata, ticker, order-book levels, trades, funding observations and candles.
4. **Data-quality layer** — timestamp sanity, sequence/gap checks where available, numeric validation and stale-feed detection.
5. **Local recorder** — structured local logs for diagnostics. No production database integration in Phase 1.
6. **Future risk/order interfaces** — design only; no order submission implementation.

## Milestones and acceptance gates

### 1A — Contract verification
- Query the official public product endpoint.
- Validate product ID and symbol against the current response.
- Confirm tick size, contract value, quantity precision, minimum order size, margin/settlement assets, and operational status.
- Fail closed if required metadata is missing or inconsistent.
- Record the source and retrieval time for verified metadata.

### 1B — Public market data
- Connect to the currently documented India demo/public market-data endpoint.
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

The India demo endpoints identified during planning were:

- Demo REST: `https://cdn-ind.testnet.deltaex.org`
- Demo public WebSocket: `wss://socket-ind-pub.testnet.deltaex.org`

Reconfirm endpoints against current official Delta Exchange India documentation before implementation. Do not assume URLs remain unchanged.

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
