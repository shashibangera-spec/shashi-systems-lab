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
