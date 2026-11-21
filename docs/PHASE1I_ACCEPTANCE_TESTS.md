# Phase 1I — Acceptance Tests

These are implementation acceptance criteria, not claims of live-market validation.

## Instrument and data
1. Reject any instrument other than Delta India BTCUSD perpetual product_id 27.
2. Reject wrong symbol, non-30m resolution, duplicate, non-chronological or missing candle intervals.
3. Historical fetch uses the existing public Delta India adapter and verifies product metadata first.
4. Current incomplete candle is excluded; no unconfirmed candle is used.
5. A 05:30 IST session is exactly 48 consecutive bars and incomplete sessions produce no profile.

## AMT profile
6. $50 row bins use floor(price / 50), row-centre levels, 70% TPO value area.
7. Each candle contributes one TPO per intersected row.
8. POC ties resolve upward; VA expansion ties resolve upward.
9. Session profile is reproducible and independent of input list order.
10. Current developing session levels are never used for targets.
11. Target candidates come only from the five most recent completed sessions; nearest eligible level strictly ahead of entry wins.
12. No eligible reference skips the trade and increments an explicit counter.

## Signals and fills
13. Setup A long/short requires probe, close back through prior boundary, no preceding accepted close, wick/body and close-location confirmation.
14. Setup B requires two completed acceptance closes, later retest and displacement confirmation.
15. Signal close to next candle open sequencing is enforced.
16. No lookahead, same-close entry or retrospective signal.
17. One active position at a time; no same-signal re-entry.
18. Position lots are even and >=2 so 50% is an integer number of lots.
19. Initial stop is one tick beyond signal candle extreme.
20. Stop/target collision in one candle is stop-first.
21. Partial closes exactly 50%; runner keeps initial stop in baseline.
22. Structural invalidation requires two completed closes across the thesis level plus ATR buffer and exits next open.
23. A single wick does not trigger structural exit.
24. End-of-data close is identified separately from strategy exits.

## Accounting
25. Phase 1E calculate_accounting is reused for both equal tranches.
26. Entry/exit taker rates and GST are passed explicitly and reported.
27. Funding is supplied as timestamped 8-hour events with mark prices; no fabricated history.
28. Funding before partial close applies to both tranches; funding after partial close applies only to runner.
29. Missing expected funding events make net including funding null and are enumerated.
30. Fee/GST currency and rounding caveats from Phase 1E remain visible; no exchange-reconciled claim.
31. No implicit FX; INR display only if a valid explicit Phase 1E FX observation is supplied.

## Safety and audit
32. Engine module performs no network or filesystem I/O.
33. CLI uses only public unauthenticated candle/product GET endpoints and local input/output files.
34. No private account, credential, order, execution, database, dashboard, Pine or collector integration.
35. Full local and GitHub Actions tests pass; PR remains open and unmerged pending explicit approval.


## Public REST historical fetch
36. \`--fetch-days 40\` requests 40 complete 05:30 IST sessions via bounded public GET calls and produces 1,920 30m bars when the exchange has complete coverage.
37. The current developing AMT session is excluded by ending the request window at the latest UTC midnight / 05:30 IST boundary.
38. Duplicate, missing or out-of-window timestamps fail closed; no synthetic bars are created.
39. Historical fetch does not read, append, rewrite or otherwise mutate the append-only recorder JSONL.
40. The backtest report is written to a separate, explicitly supplied output path.


## Mechanical/reporting regression checks

- A completed signal candle is recorded with its start and close boundary; the entry timestamp and price come only from the immediately following candle's open. For contiguous candles, the signal-close and next-open timestamps may be equal as a shared boundary.
- If one post-entry candle touches both protective stop and first target, the stop is processed first, the full remaining position exits at the stop, and no partial exit is recorded.
- `runner_lots` equals the full original position when no partial exit occurred, and equals the remaining position only after a partial has occurred.
- Summary output keeps backward-compatible overall metrics and separately reports normal strategy exits, end-of-data liquidations, and all trades including end-of-data.
- Trade #10's matching 12:30 UTC partial/final timestamps are interpreted using candle intervals: prior candle end versus next candle start. They are not treated as proof of same-candle ambiguity.
- With pullback entry and minimum first-target R:R enabled, Setup A eligibility is screened at signal close using the resting limit, signal-derived stop and nearest eligible completed prior-session AMT Target 1. Low-R:R signals are rejected before an order is placed; post-fill R:R rejections must be zero.
- Target 1 and the next-AMT runner reference are fixed at signal close from the resting limit and are not re-selected using later fill prices.
- With `--pullback-require-tick-through`, a buy limit fills only if the candle low is at least one instrument tick below the limit; a sell limit fills only if the candle high is at least one tick above. A mere touch does not fill.
- With tick-through enabled, an opening gap at least one tick beyond the limit fills at the better opening price and is taker; a later qualifying penetration fills at the resting limit and is maker when `--pullback-maker-entry` is enabled. Setup B next-open entries and all exits remain taker.
- Pullback order accounting reconciles placed = filled + expired + stop-invalidated + pending; filled = accepted, with zero post-fill minimum-R:R rejections.


## Optional ATR runner trailing-stop acceptance

41. `--runner-trail-atr-multiplier 2.0` requires fee-adjusted runner breakeven and is mutually exclusive with `--runner-next-amt-target`.
42. The trail activates only after Target 1 is confirmed at a completed candle close and is first effective on the following candle.
43. Long trailing candidates use highest high since T1 minus multiplier × previous completed candle ATR(14), rounded down to $0.50; short candidates use lowest low since T1 plus multiplier × ATR(14), rounded up to $0.50.
44. Fee-adjusted breakeven is the absolute floor; stops ratchet only in the protective direction and never loosen.
45. A candle's high/low may update the watermark only for the next candle; the candidate may not use the current candle's not-yet-completed range.
46. Gap-through stop exits fill at the candle open; otherwise at the stop. All exits remain taker.
47. Trailing mode has no fixed Target 2; all entry, Target 1, initial stop, 1.0R, pullback, tick-through and accounting rules remain identical to the control.
48. Synthetic tests cover activation timing, trailing-stop price, gap-through fill, breakeven floor and invalid/mutually-exclusive configuration.
