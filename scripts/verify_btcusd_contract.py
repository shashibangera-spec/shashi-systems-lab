"""Run the read-only Delta BTCUSD contract metadata check."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shashi_engine.contract_verification import (  # noqa: E402
    ContractVerificationError,
    to_json_dict,
    verify_live_contract,
)


def main() -> int:
    try:
        contract = verify_live_contract()
    except ContractVerificationError as exc:
        print(f"VERIFICATION FAILED: {exc}")
        return 1

    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "https://api.india.delta.exchange/v2/products",
        "mode": "public_read_only",
        "contract": to_json_dict(contract),
        "safety": {
            "authenticated": False,
            "orders_submitted": False,
            "private_account_data_accessed": False,
        },
        "note": (
            "API settling_asset is reported as returned by the API. "
            "Delta's India contract page separately describes INR as margin/effective "
            "settlement currency; resolve this documentation discrepancy before "
            "any order or PnL/margin accounting implementation."
        ),
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
