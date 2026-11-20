# Phase 1F — Local Append-Only Recorder, Feed Health and REST Gap Recovery

## Status and objective

Phase 1F adds a local, public-data-only recorder for Delta Exchange India's BTCUSD 30-minute candle stream. The goal is a restart-tolerant research dataset with visible feed-health transitions and explicit recovery provenance.

The recorder is a bounded command-line process, not a production service. It does not connect to the existing BTC dashboard or its database.

## Data sources

- WebSocket: `wss://public-socket.india.delta.exchange`
- Public channel: `candlestick_30m`, symbol `BTCUSD`
- REST recovery: existing public `GET /v2/history/candles` adapter
- Candle identity comes only from explicit `cst` / `candle_start_time`, normalized to UTC. The WebSocket event timestamp `ts` is not used as the candle key.

Only public market data is consumed. No authentication, private channels, API keys, account balances or order endpoints are used.

## Local storage contract

- Output format: newline-delimited JSON (JSONL), one self-contained record per line.
- Default path: `data/market_data/btcusd_30m.jsonl`.
- The `data/` directory is git-ignored; recordings must remain local and must not be committed.
- Every record includes a `record_type` and a UTC recording timestamp.
- Supported record families include `websocket_update`, `completed_candle`, `rest_recovery`, `recovery_report`, `feed_health`, `feed_error` and `recorder_session_end`.
- Existing history is opened in append mode only. The implementation never truncates, rewrites, sorts, deletes or silently repairs old lines.
- Canonical completed candles are keyed by UTC candle-start time. A second canonical record for the same start is skipped; original lines remain unchanged.
- Existing malformed JSON, blank lines, an unterminated final line or malformed canonical timestamps cause startup to fail closed. The recorder does not try to repair a damaged file.
- Use one recorder process per output file; cross-process locking is not provided.
- Writes are flushed and fsynced. A process interruption may leave a malformed final line; on next start that condition is surfaced for manual inspection rather than overwritten.

## Feed-health monitoring

The monitor emits state changes only:
- `CONNECTED`: public WebSocket connection established or a valid candle update received.
- `STALE`: no valid candle update within the configured stale threshold, measured from connection establishment until the first message and from the last message thereafter.
- `DISCONNECTED`: WebSocket connection closed or errored.

A later valid message returns the state to `CONNECTED`. A reconnect resets the freshness clock. Transient disconnects are recorded and the runner retries with a bounded delay while its configured session remains active.

## Completed candles and recovery

1. Every valid public WebSocket candle update is appended as an immutable `websocket_update` event.
2. A candle is marked `completed_candle` only when the stream advances to the next explicit 30-minute candle start and the previous update is not known stale.
3. After startup/reconnect, or when a rollover skips intervals, the recorder calculates the missing UTC half-hour starts from the latest canonical candle to the current bucket.
4. The missing range is requested from the existing public REST adapter, with a configurable maximum of 48 intervals per recovery call by default.
5. Returned candles must be BTCUSD 30m candles, UTC-aligned, within the requested range, unique and in chronological order. Invalid REST responses fail closed before recovery writes.
6. Valid REST candles are appended as `rest_recovery`. Any expected start not returned by REST is listed as unresolved in a `recovery_report`; no candle is fabricated or filled.
7. On reconnect, an unfinished in-memory WebSocket bucket is discarded as a canonical candle. REST recovery is used to reconstruct the completed interval instead.

A successful recovery report means the REST endpoint supplied all requested intervals in that one recovery window. It is not proof of indefinite feed reliability.

## Run instructions

Install the optional WebSocket dependency:

```powershell
python -m pip install -e ".[market-data,dev]"
```

Run a one-hour bounded recording session:

```powershell
python scripts/record_btcusd_market_data.py --duration-seconds 3600
```

Optional controls:

```powershell
python scripts/record_btcusd_market_data.py --output data/market_data/btcusd_30m.jsonl --duration-seconds 3600 --stale-after-seconds 120 --max-recovery-intervals 48
```

The process prints a final summary. Exit code 1 indicates one or more recorded operational errors; inspect the JSONL health/error/recovery records. An unresolved recovery interval must remain visible and must not be used as completed data.

Run synthetic tests:

```powershell
python -m pytest -q
```

## Explicit exclusions

- No database, cloud bucket, dashboard, Telegram or external alert integration.
- No credentials, private account data, private WebSocket channels or authenticated REST calls.
- No strategies, signals, position sizing, margin, PnL or order execution.
- No automatic deletion, compaction, rewriting or gap fabrication.
- No changes to the separate `btc-dashboard` repository.
