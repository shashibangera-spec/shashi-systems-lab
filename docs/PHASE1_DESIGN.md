# Phase 1 — Contract Verification and Market-Data Foundation

## Objective

Build a standalone Python application for Delta Exchange India's BTCUSD perpetual contract. Phase 1 is read-only: verify the instrument and consume public market data. It must not authenticate to a trading account or submit orders.

## BTCUSD contract facts — live API verified on 2026-11-20

Official Delta Exchange India contract specifications and help articles currently document:

- Product ID: `27`; symbol: `BTCUSD`
- Contract type: perpetual futures
- Contract value / lot size: `0.001 BTC`
- Minimum BTC futures order size: `0.001 BTC` (one lot)
- Order quantity: whole-number lots; do not send decimal BTC as the lot count
- Tick size: `0.50 USD`
- Price quotation: `USD per 1 BTC`
- Funding interval: `8 hours` (`28,800 seconds`)
- Maker/taker fees: `0.02% / 0.05%` before 18% GST on the fee (effective `0.0236% / 0.0590%`); potential taker-rate settlement fee for contracts open at settlement
- India contract specification page: margin and effective settlement currency shown as `INR`

**Currency reconciliation (Phase 1A closed 2026-11-21):** Delta India documents derivative contracts as notionally margined and settled in USD, while its India platform uses a fixed 1 USD = 85 INR conversion reference, keeps user balances in INR, and effectively performs margining/PnL realisation in INR. The India BTCUSD contract specification labels margin and effective settlement currency INR. Keep `api_settlement_asset=USD` distinct from documentation-derived `documented_margin_currency=INR` and `documented_effective_settlement_currency=INR`. The 85 reference is documentation-derived and must not be hard-coded as a live conversion without fresh confirmation. See [Phase 1A currency and fees](PHASE1A_CURRENCY_AND_FEES.md).

Sources:
- https://www.delta.exchange/en/contracts
- https://www.delta.exchange/support/solutions?articleId=80001177912
- https://www.delta.exchange/support/solutions?articleId=80001141030
- https://docs.delta.exchange/

User-run public API verification succeeded on 2026-11-20 at 20:37:14 UTC: product 27, BTCUSD, live/operational, 0.001 BTC per lot, $0.50 tick, USD quote and API settling asset, 28,800-second funding interval, minimum one whole-number lot. The user's local test run reported 14 passed. The currency denomination versus effective INR account-ledger distinction is documented in `docs/PHASE1A_CURRENCY_AND_FEES.md`. Base fee and GST rules are documented there too. Do not treat maximum leverage as a recommendation.

## Current implementation

`src/shashi_engine/market_data.py` adds an unauthenticated REST adapter for the BTCUSD ticker and 30-minute historical candles, with Decimal normalization and basic OHLCV validation. The historical candle endpoint accepts Unix `start` and `end` timestamps in seconds and supports up to 2,000 candles per response. `scripts/read_btcusd_ticker.py` prints a single public ticker snapshot. `scripts/read_btcusd_candles.py` fetches a bounded 48-hour sample of 30-minute candles and reports timestamp alignment, duplicates, gaps, candle completeness and representative OHLCV values. The scripts do not save raw API responses.

Run locally from the repository root:

```bash
python scripts/verify_btcusd_contract.py
python scripts/read_btcusd_ticker.py
python scripts/read_btcusd_candles.py
python -m pytest -q
```

The candle script is a live public-data validation step. Review its output for the expected approximate 96 intervals, no duplicate or misaligned timestamps, no unexplained gaps, valid OHLCV, and whether the latest returned candle is complete. A gap or incomplete latest candle is reported for review rather than silently filled or treated as a completed bar.

Do not commit live response dumps. Review returned fields and timestamps locally.
### Public WebSocket probe

The official India public WebSocket endpoint is `wss://public-socket.india.delta.exchange`. The current public `candlesticks` channel supports `candlestick_30m` and a BTCUSD symbol subscription without authentication. `scripts/probe_btcusd_websocket.py` is a bounded 90-second probe: it subscribes only to BTCUSD 30-minute traded-price candles, validates received OHLCV events and the explicit candle-start field (Delta compact key `cst`, Unix microseconds) when present, uses WebSocket ping/pong, and prints a summary. It does not persist data or connect to private channels.

Install the optional client and run:

```bash
pip install -e '.[market-data]'
python scripts/probe_btcusd_websocket.py
```

A successful probe should receive at least one BTCUSD candle update with a valid timestamp and OHLC values. A 90-second timeout with no event is inconclusive, not proof that the feed is unavailable. Do not subscribe to private channels or provide credentials.
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
5. **Local recorder** — append-only JSONL records for public feed diagnostics and candle history. Local output is git-ignored; no production database integration.
6. **Future risk/order interfaces** — design only; no order submission implementation.

## Milestones and acceptance gates

### 1A — Contract verification — CLOSED
- User-run public product verifier confirmed product 27 and the core BTCUSD contract fields on 2026-11-20.
- Official India documentation reconciles USD denomination with the effective INR balance/margin/PnL ledger; the documented fixed conversion reference is 85 INR per USD and is not hard-coded in software.
- Base maker/taker fees are 0.02% / 0.05%; 18% GST applies to fees; a taker-rate settlement fee may apply to open contracts at settlement.
- Delta support states no 1% TDS for F&O and no 30% VDA tax for F&O profits; tax treatment must be checked with a qualified professional.
- See `docs/PHASE1A_CURRENCY_AND_FEES.md` for sources, assumptions and implementation boundaries.

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

### 1D — Risk controls (non-executing implementation)
- Implemented a pure risk gate with max total exposure, per-intent loss, daily loss, stale-intent, currency-match, duplicate-intent and kill-switch checks.
- Decimal-only monetary inputs and explicit single-currency evaluation; no implicit USD/INR conversion.
- Process-local duplicate ID registry only; no persistence or execution adapter.
- An approved decision means research-only review, never permission to place an order.

### 1E — Non-executing accounting simulator — CLOSED
- Implemented pure Decimal BTCUSD scenario accounting, maker/taker fees and GST assumptions, conditional settlement fee, funding cash flows and optional timestamped USD/INR display equivalents.
- Integrated the existing RiskGate through an explicitly USD-only adapter.
- No exchange account access, margin, leverage, liquidation, sizing, persistence, or order execution.
- Specification: `docs/PHASE1E_ACCOUNTING_SIMULATOR_SPEC.md`; acceptance plan: `docs/PHASE1E_ACCEPTANCE_TESTS.md`.

### 1F — Local append-only recorder, feed health and REST gap recovery — CLOSED
- Append public BTCUSD 30m WebSocket updates and canonical completed candles to local JSONL without rewriting existing history.
- Record CONNECTED, STALE and DISCONNECTED feed-health transitions.
- On rollover/reconnect, recover only missing, UTC-aligned completed intervals from public REST; report any unresolved intervals.
- Local output under `data/` is git-ignored. No database, account credentials, private endpoints or order routes.
- Specification: `docs/PHASE1F_RECORDER_SPEC.md`; acceptance plan: `docs/PHASE1F_ACCEPTANCE_TESTS.md`.

### 1G — Historical JSONL integrity, recovery validation and data-quality reporting — CLOSED
- Audit JSONL structure, candle provenance, UTC alignment, duplicate/out-of-order starts and missing intervals without modifying source history.
- Validate bounded public REST gap responses read-only and report unresolved intervals; actual append-only recovery remains the Phase 1F function.
- Verify restart byte preservation, restored deduplication and append continuity.
- Produce JSON and Markdown quality reports; no strategy replay or execution is included.
- Specification: `docs/PHASE1G_HISTORY_INTEGRITY_SPEC.md`; acceptance plan: `docs/PHASE1G_ACCEPTANCE_TESTS.md`.

### 1H — Focused recorder soak and controlled restart validation — UNDER REVIEW
- Run 2–4 hours of active public BTCUSD 30m recording across three sequential recorder processes and exactly two controlled clean restarts.
- Verify the append-only byte prefix after each session and run Phase 1G audit/restart checks after every segment.
- Record feed errors, reconnects, recovery outcomes and safety metadata; a short pass is not a long-term reliability certification.
- Specification: `docs/PHASE1H_FOCUSED_SOAK_SPEC.md`; acceptance plan: `docs/PHASE1H_ACCEPTANCE_TESTS.md`.

### 1I — Strategy research and validation — PLANNED, CONDITIONAL
- Begins only after Phase 1H acceptance. First approve a written strategy specification covering signal rules, completed-candle timing, costs/funding/slippage, risk limits and out-of-sample evaluation.
- Research and simulation only; no execution adapter or live orders.

### 1J — Delta Exchange Testnet demo execution — PLANNED, CONDITIONAL
- Intended after Phase 1H and Phase 1I review, as a separate implementation and PR.
- Re-verify official Testnet endpoints and product behavior before coding. Isolate Testnet-only credentials and host allowlists; fail closed on any live/production host.
- Require a kill switch, strict order/risk caps, idempotency, audit logs and tests proving production hosts are rejected.
- No production credentials, live endpoints, withdrawals or real-money orders; this milestone does not authorize live trading.

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


### REST-versus-WebSocket completed-candle consistency check

After the short WebSocket probe succeeds, run `scripts/compare_btcusd_rest_websocket.py` to validate one fully completed 30-minute candle. This bounded read-only check waits for the WebSocket to roll into the next UTC 30-minute bucket, retains the final update for the prior bucket, then retrieves that exact candle from REST and compares open, high, low, close and volume with Decimal equality. The bucket is selected exclusively from the WebSocket `cst` candle-start timestamp (or descriptive `candle_start_time` alias), never from the event/publish timestamp `ts`. If the explicit candle-start field is missing or not aligned to a UTC 30-minute boundary, the check fails closed. It may wait up to 40 minutes depending on when it is started. A missing REST candle after bounded retries or a skipped WebSocket interval is reported as inconclusive; a field difference is reported as a mismatch. Neither outcome is silently repaired or treated as a pass.

Run:

```bash
python -m pytest -q
python scripts/compare_btcusd_rest_websocket.py
```

A `MATCH` is the acceptance result for this one sampled candle only. It does not establish long-term feed reliability or authorize persistence, strategy logic, or order execution.


## Phase 1C — Domain models and data quality

Phase 1C adds immutable, validated domain models for the instrument, ticker, funding observation and BTCUSD 30-minute OHLCV candle. Monetary and quantity values remain `Decimal`; no float conversion or lot-size/order-quantity conversion is performed by these models.

The instrument model deliberately stores `api_settlement_asset`, `documented_margin_currency` and `documented_effective_settlement_currency` as separate fields. The two documentation fields remain unset unless explicitly supplied from an identified source. An API value of USD is never used to infer an INR margin or effective settlement currency.

Candle validation requires a timezone-aware UTC half-hour start timestamp, positive finite OHLC values, non-negative finite volume, and internally consistent high/low relationships. The data-quality inspector reports duplicate starts, out-of-order input, missing 30-minute intervals and stale completed data. It does not sort the input, fill gaps, deduplicate records or otherwise repair observations. Any detected defect makes the report unacceptable.

Validation is local and synthetic; Phase 1C adds no live API calls, persistent recorder, database integration, strategy logic, account access or order routes.


See [Phase 1D risk controls](PHASE1D_RISK_CONTROLS.md) for exact gate semantics and non-goals.
