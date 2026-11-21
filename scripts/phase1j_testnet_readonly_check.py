"""Run a read-only Delta India Testnet account reconciliation report."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from shashi_engine.phase1j_testnet_readonly import (
    DeltaIndiaTestnetReadOnlyClient,
    DeltaReadOnlyError,
    load_local_credentials,
)


def _result_rows(payload):
    result = payload.get("result")
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        for key in ("positions", "orders", "fills", "wallets", "data"):
            value = result.get(key)
            if isinstance(value, list):
                return value
        return [result]
    return []


def main() -> int:
    try:
        key, secret = load_local_credentials()
        client = DeltaIndiaTestnetReadOnlyClient(key, secret)
        # Fixed calls only; this script has no order mutation capability.
        product_payload = client.get_product()
        positions_payload = client.get_positions()
        orders_payload = client.get_open_orders()
        fills_payload = client.get_fills()
        wallets_payload = client.get_wallet_balances()

        product = product_payload.get("result")
        if not isinstance(product, dict):
            raise DeltaReadOnlyError("Product metadata response has an unexpected shape")
        if product.get("id") != 27 or product.get("symbol") != "BTCUSD":
            raise DeltaReadOnlyError("Product identity mismatch: expected product 27 BTCUSD")

        positions = _result_rows(positions_payload)
        orders = _result_rows(orders_payload)
        fills = _result_rows(fills_payload)
        wallets = _result_rows(wallets_payload)

        # Keep only non-zero positions; all open orders are treated as exposure
        # until a later, separately approved order-state classifier exists.
        open_positions = [
            row for row in positions
            if isinstance(row, dict) and str(row.get("size", "0")) not in ("0", "0.0", "")
        ]
        account_ids = set()
        for row in wallets + positions + orders + fills:
            if isinstance(row, dict) and row.get("user_id") is not None:
                account_ids.add(str(row["user_id"]))
        if len(account_ids) > 1:
            raise DeltaReadOnlyError("Account identity mismatch across returned records")

        report = {
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "environment": "DELTA_INDIA_TESTNET",
            "origin": "https://cdn-ind.testnet.deltaex.org",
            "http_operations": ["GET product", "GET positions", "GET open orders", "GET fills", "GET wallet balances"],
            "product": {"id": product.get("id"), "symbol": product.get("symbol"), "state": product.get("state"), "trading_status": product.get("trading_status"), "tick_size": product.get("tick_size"), "contract_value": product.get("contract_value")},
            "account_user_ids": sorted(account_ids),
            "wallet_records": len(wallets),
            "position_records": len(positions),
            "nonzero_positions": open_positions,
            "open_order_records": len(orders),
            "fill_records_returned": len(fills),
            "reconciliation": "READ_ONLY_SNAPSHOT_COMPLETE",
            "execution_authorized": False,
            "warning": "This is a read-only snapshot, not proof of flatness across paginated history or a reconciled local execution ledger. Any unexpected position/order must be reviewed manually. No orders were submitted, changed, or cancelled.",
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except (DeltaReadOnlyError, ValueError) as exc:
        print(f"RECONCILIATION BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
