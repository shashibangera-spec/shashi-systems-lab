"""Fetch and print a read-only BTCUSD public ticker snapshot."""
from __future__ import annotations

import json
import sys

from shashi_engine.market_data import MarketDataError, fetch_ticker, ticker_to_json


def main() -> int:
    try:
        ticker = fetch_ticker()
    except MarketDataError as exc:
        print(f"MARKET DATA ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(ticker_to_json(ticker), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
