# Phase 1A closure — BTCUSD currency and fee rules

Research completed: 2026-11-21. Scope: Delta Exchange India BTCUSD perpetual, public documentation only. No account was accessed and no live orders were submitted.

## Currency reconciliation

The earlier apparent USD/INR conflict is a distinction between denomination and the India platform's effective account ledger:

- The public Products API observation for product 27 (BTCUSD) reports settling_asset: USD. Preserve this raw API field as api_settlement_asset = "USD"; do not rewrite or discard it.
- Delta Exchange India's USD-INR help article says derivatives are notionally margined and settled in USD, while the platform fixes its USD-INR conversion at **1 USD = 85 INR**, maintains user balances in INR, and effectively performs margining and PnL realisation in INR.
- The India BTCUSD contract specification separately labels **Margin & Effective Settlement Currency: INR**.

These statements are consistent when fields are kept distinct:
- API / contract denomination and notional settlement representation: USD.
- India platform effective margin and account-balance / PnL ledger currency: INR.
- Documented platform conversion reference: 85 INR per USD, as stated in the help article.

**Implementation rule:** retain api_settlement_asset="USD" and record documented_margin_currency="INR" and documented_effective_settlement_currency="INR" as documentation-derived fields. Never treat the API field alone as proof that the user's account ledger is USD. Conversely, do not assume the 85 rate is a live FX market rate or hard-code it as an execution conversion without fresh confirmation from the current product/account API. This Phase 1A closure resolves the documentation semantics; it does not authorize margin or PnL accounting code.

## BTCUSD fee rules

Delta India's current BTCUSD contract specification and fee material list the base futures fees:

| Fill type | Base fee | With 18% GST on fee |
|---|---:|---:|
| Maker | 0.02% | 0.0236% |
| Taker | 0.05% | 0.0590% |

The published futures fee formula is based on trade notional. The BTCUSD fee calculator illustrates notional as:

    number_of_lots × 0.001 BTC × BTC index price

Trading fee per fill is notional multiplied by the applicable maker or taker rate. GST at 18% is applied to the trading fee, not to the trade notional. Entry and exit fills are each charged according to how they execute; a limit order is not automatically maker if it immediately removes liquidity.

Delta's fee page also says a settlement fee applies to open contracts at settlement and that taker fees are charged. Include this as a separate potential cost when estimating a position that remains open through settlement/expiry; do not silently treat it as zero.

Offers such as the Scalper Offer can change closing fees and eligibility. They are account/offer-dependent and are **not** assumed in the base fee model. Fee tiers, promotions and the live fee schedule can change; re-check the exchange fee page before any future cost-accounting implementation.

## India tax / charge notes from Delta support

- Delta's support article says 18% GST applies to trading and liquidation fees.
- Delta's support article says 1% TDS does not apply to its Futures and Options segment.
- Delta's support article says the 30% VDA tax does not apply to profits from its crypto Futures and Options contracts; it describes net profits as taxable under the user's income-tax slab. This is exchange guidance, not personal tax advice. Confirm current law and individual treatment with a qualified Indian tax professional.
- Funding is a separate periodic payment between counterparties on perpetual contracts, not a maker/taker trading fee. The BTCUSD contract specification lists an 8-hour funding interval.

## Verified facts and limits

Previously user-run public product verification (2026-11-20) reported product 27, BTCUSD, perpetual futures, 0.001 BTC per lot, $0.50 tick, USD quote asset, API settling asset USD, 8-hour funding interval and minimum one whole-number lot. This is the user's supplied verification output, not a new live API check performed for this documentation update.

This document is not an execution/accounting specification. Before implementing margin, realised/unrealised PnL, liquidation, fee ledger, tax ledger or order sizing, obtain a fresh public product response and, where account-specific behaviour matters, authoritative current confirmation from Delta. Do not assume the fixed 85 conversion is guaranteed to remain unchanged.

## Official Delta sources consulted

- https://prod-landing-page.delta.exchange/contracts
- https://www.delta.exchange/support/solutions?articleId=80001200076&categoryId=undefined&folderId=undefined
- https://www.delta.exchange/support/solutions?articleId=80001177869&categoryId=80000464973&folderId=80000726071
- https://prod-mobile-india.delta.exchange/fees
- https://www.delta.exchange/support/solutions?articleId=80001132759
- https://www.delta.exchange/support/solutions?articleId=80001132760
- https://www.delta.exchange/support/solutions?articleId=80001132761
- https://www.delta.exchange/support/solutions?articleId=80001177915
