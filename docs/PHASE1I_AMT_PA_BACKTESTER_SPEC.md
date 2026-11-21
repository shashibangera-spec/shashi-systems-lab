# Phase 1I — Delta BTCUSD AMT + Price Action Backtester

Status: **Implementation proposal — offline research only. PR remains open and unmerged pending review and acceptance.**

## 1. Instrument and data boundary

- Venue/instrument: Delta Exchange India BTCUSD perpetual, public product metadata product_id 27.
- Candle source: existing Phase 1B unauthenticated GET /v2/history/candles adapter; existing Phase 1F local JSONL recorder is also an accepted input source.
- Timeframe: completed 30-minute candles only.
- Session: 05:30 IST to 05:30 IST (00:00 UTC to 00:00 UTC).
- Contract metadata is fetched and validated through the existing public product verifier before a public historical fetch. Expected contract metadata is 0.001 BTC/lot, $0.50 tick, USD quote/API settlement fields, and 8-hour funding; the verifier remains authoritative and the engine rejects a different product identity.
- No Binance candles, BTCUSDT proxy data, private endpoints, API keys, account data, database, production dashboard, order routes or execution adapter.

The pure engine receives validated Candle objects. Network access is isolated in the CLI and uses only the existing public Phase 1B adapter. Local JSONL input is normalized into the same domain model. The engine itself has no network or filesystem access.

## 2. AMT profile construction

Phase 1I baseline configuration:

- TPO row size: USD 50.
- Value area: 70% of total TPO counts.
- Each completed 30-minute candle contributes one TPO to every price row intersected by its low-to-high range, inclusive.
- Row index is floor(price / 50); displayed row level is the row centre (row lower edge + $25).
- POC is the row with the greatest TPO count; ties resolve to the higher row.
- Value area expands from POC toward the adjacent row with the larger count; ties resolve upward. Continue until included TPO count is at least 70%.
- A completed AMT session must contain exactly 48 unique, consecutive 30-minute candles beginning at 05:30 IST. Incomplete or gapped sessions do not produce levels.
- Developing-session VAH/VAL/POC and developing session high/low are never used as profit targets.

This is a deterministic Python reconstruction on Delta BTCUSD candles, not a claim of exact Pine v7.2.2 parity. Before treating the values as production-equivalent, compare reconstructed profiles against saved Pine/Data Window examples and reconcile TPO allocation, row alignment, POC tie-break and value-area expansion differences.

## 3. Fixed reference set and first partial

The setup boundary is Prior VAH for long acceptance/retest and Prior VAL for short acceptance/retest (or the corresponding boundary for failed-auction rejection).

For first-profit selection, use the VAH, POC and VAL of the latest five completed AMT sessions before the current session. This fixed historical pool allows a continuation trade above yesterday's VAH (or below yesterday's VAL) to have an older reference ahead. The current developing session is always excluded. Select the nearest eligible price strictly ahead of simulated entry in the trade direction. Record its session date, level type and price at signal time. If none exists, skip the setup and count NO_ELIGIBLE_REFERENCE; do not invent a target.

The five-session target pool is a Phase 1I implementation convention, not a proven optimum. Report it explicitly so alternate lookbacks can be compared in later research.

## 4. Entry setups

ATR is a simple mean of the last 14 completed true ranges. The baseline discovery/retest buffer is 0.10 × ATR(14).

### Setup A — Failed Auction / Rejection

Long:
1. Current candle trades below Prior VAL by more than the buffer.
2. It closes above Prior VAL by more than the buffer.
3. Previous candle did not close below Prior VAL minus the buffer.
4. Lower wick is at least 1.5 × max(real body, one tick); close is in the upper 40% of the candle range.

Short is the exact inverse at Prior VAH.

### Setup B — Acceptance and Retest

Long:
1. Two preceding completed candles both close above Prior VAH + buffer.
2. Current candle retests the VAH zone (low <= VAH + buffer).
3. It closes above VAH + buffer and above the previous candle high.
4. Close is in the upper 40% of the candle range.

Short is the exact inverse below Prior VAL.

Only one position is allowed at a time. Signal is known at the signal candle close; simulated entry is the next 30-minute candle open. A signal with no next candle is ignored. No lookahead, unconfirmed candle or same-close fill is allowed.

## 5. Position, stop and partial

- Fixed research position: configurable even whole-number lots, baseline 2 lots. This permits a 50% close in whole lots under the verified minimum lot increment.
- No dynamic position sizing, leverage, margin, liquidation or capital allocation is calculated.
- Initial stop: one configured tick beyond the signal candle extreme (one tick baseline): below signal low for long, above signal high for short.
- If next-candle entry opens beyond the stop, skip the trade.
- First target: nearest eligible fixed historical AMT level ahead of entry.
- When target is touched, close 50% at the target level; target touch is simulated as a taker fill for conservative fee treatment.
- Keep the initial stop on the runner; no automatic breakeven or trailing stop in the baseline.
- On every post-entry candle, evaluate the protective stop before evaluating the first target. If both are touched in the same candle, the stop closes the full still-open position first and no partial is credited. A target recorded at a candle's end boundary and a stop recorded at the next candle's start boundary can share a timestamp while belonging to two different adjacent candles.
- Target-touch time is recorded as the completed candle's end timestamp because OHLC candles do not reveal the exact intrabar touch time.
- Remaining 50% exits on confirmed structural invalidation, initial stop, or end-of-data close. End-of-data is an administrative backtest close, not a strategy time exit.

## 6. Structural invalidation

For a long, two consecutive completed candles after entry closing below the setup's thesis reference minus the current ATR buffer invalidate the thesis. For a short, two consecutive completed candles after entry closing above the thesis reference plus the buffer invalidate it. Exit is simulated at the next candle open. A single wick does not invalidate. The original protective stop remains active and has intrabar priority.

## 7. Fees, GST, funding and USD ledger

- Reuse Phase 1E calculate_accounting, FeeSchedule, FundingEvent and AccountingPolicy; do not duplicate formulas.
- Baseline entry and exit fills are explicitly taker assumptions; maker fills are not inferred from order type.
- Base scenario schedule: maker 0.02%, taker 0.05%, GST 18% on trading fees. Fee/GST currency and exchange rounding remain unverified assumptions under Phase 1E; results must never claim exchange-reconciled account PnL.
- Positive funding means longs pay shorts; negative funding means shorts pay longs. Apply each explicit 8-hour event on mark-price notional. Funding is separate from fees/GST.
- Historical funding observations are supplied as a separate local CSV with columns timestamp_utc,rate,mark_price. The public candle adapter does not fabricate historical funding.
- Every expected 8-hour funding event between entry and exit must be present before net_including_funding_usd is reported. Missing events are listed and net including funding is null; price PnL and fees-only net remain available.
- Funding events before partial close apply to both tranches; events after partial close apply only to the runner.
- Contract denomination and accounting remain USD. INR equivalents require a separately supplied, timestamped and fresh USD/INR observation under Phase 1E policy; no hard-coded FX is permitted. The CLI currently reports USD only.

## 8. Data quality and execution simulation

- Input candles must be BTCUSD 30m, UTC-aligned, unique, strictly chronological and gap-free. A gap fails closed; the engine never fills or fabricates candles.
- Use only completed candles. No intrabar path is inferred.
- Stop/target same-candle ambiguity is stop-first.
- All signal, entry, partial and final timestamps are retained in output.
- Price/fee/funding arithmetic uses Decimal.
- Local output reports are research artifacts only; raw recorder JSONL remains append-only and is never rewritten.

## 9. Reporting and acceptance

Report per trade: setup, side, signal/entry timestamps, entry, thesis level, stop, first target and source, partial timestamp/price, final exit timestamp/price/reason, lots, gross USD PnL, fees and GST, funding cash flow, fees-only net, net including funding (only if complete), and missing funding events.

Summary: preserve the overall all-trades metrics and separately report `strategy_exits_excluding_end_of_data` (normal stop/structural exits only), `end_of_data_liquidations` (administrative final-bar closes only), and `all_trades_including_end_of_data`. Each group reports trade count, gross/net P&L, fees/GST, funding completeness, win rate, profit factor and drawdown. End-of-data liquidation is not presented as a normal strategy exit. Per-trade reporting includes `signal_candle_start_time`, `signal_time` (signal bar close boundary), and `entry_time` (next bar open boundary).

Acceptance requires full test suite, exact PR-head CI green, deterministic synthetic tests for profile/entries/exits/partial accounting/funding gaps/stop-first, no secrets or local recordings committed, and user Windows acceptance. PR remains open and unmerged until separate explicit merge approval.

## 10. Safety boundaries

Research-only. No strategy-to-execution wiring, orders, demo orders, private account access, production credentials, dashboard/database/Pine/collector changes, leverage, margin, liquidation or automated sizing. Phase 1E RiskGate remains separate; this backtester does not treat APPROVED_FOR_RESEARCH_ONLY as execution authorization.


## 11. Public historical REST fetch option

The CLI supports \`--fetch-days N\` (1–90). It uses the existing Phase 1B unauthenticated Delta India \`GET /v2/history/candles\` adapter in bounded 48-candle requests. The window is anchored to UTC midnight, which is 05:30 IST, and ends at the latest completed 05:30 IST session boundary. Thus \`--fetch-days 40\` requests 40 complete sessions (1,920 half-hour candles), excluding the developing session. The helper sorts exchange rows and fails closed on duplicate or missing candle timestamps; it does not fill gaps.

The helper returns candles in memory only. It does not open, append to, rewrite or otherwise touch \`recordings/btcusd_30m.jsonl\` or any recorder file. Backtest output is a separate report path. Example from the repository root on Windows PowerShell:

\`\`\`powershell
py -3 scripts\\backtest_btcusd_amt_pa.py --fetch-days 40 --output data\\reports\\phase1i_btcusd_40d.json
\`\`\`

Historical candle data is public and unauthenticated. Funding is not included by this fetch; unless a complete, separately verified funding CSV is supplied, net including funding remains unavailable for trades with expected funding events.
