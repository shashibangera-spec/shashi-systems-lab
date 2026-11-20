"""Read-only Delta Exchange India product metadata verification.

This module performs one unauthenticated GET request. It contains no order API,
private WebSocket, credentials, or trading functionality.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

BASE_URL = "https://api.india.delta.exchange"
PRODUCTS_PATH = "/v2/products"
EXPECTED_SYMBOL = "BTCUSD"
EXPECTED_PRODUCT_ID = 27


class ContractVerificationError(RuntimeError):
    """Raised when the public product response is missing or contradicts required data."""


@dataclass(frozen=True, slots=True)
class VerifiedContract:
    product_id: int
    symbol: str
    contract_type: str
    state: str
    trading_status: str
    contract_value: Decimal
    contract_unit_currency: str
    tick_size: Decimal
    quoting_asset: str
    api_settling_asset: str
    funding_interval_seconds: int
    minimum_order_lots: int
    quantity_unit: str
    btc_per_lot: Decimal


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ContractVerificationError(f"Invalid or missing {field}") from exc
    if not result.is_finite() or result <= 0:
        raise ContractVerificationError(f"{field} must be a positive finite number")
    return result


def _asset_symbol(value: Any, field: str) -> str:
    if isinstance(value, dict):
        value = value.get("symbol")
    if not isinstance(value, str) or not value.strip():
        raise ContractVerificationError(f"Missing {field}.symbol")
    return value.upper()


def parse_product(product: dict[str, Any]) -> VerifiedContract:
    """Parse and validate one product object from Delta's public products API."""
    try:
        product_id = int(product["id"])
        symbol = str(product["symbol"]).upper()
        contract_type = str(product["contract_type"])
        state = str(product["state"])
        trading_status = str(product["trading_status"])
        contract_value = _decimal(product["contract_value"], "contract_value")
        contract_unit_currency = _asset_symbol(
            product.get("contract_unit_currency"), "contract_unit_currency"
        )
        tick_size = _decimal(product["tick_size"], "tick_size")
        quoting_asset = _asset_symbol(product["quoting_asset"], "quoting_asset")
        api_settling_asset = _asset_symbol(product["settling_asset"], "settling_asset")
        specs = product["product_specs"]
        funding_interval_seconds = int(specs["expiry_interval"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractVerificationError(f"Incomplete BTCUSD product metadata: {exc}") from exc

    if product_id != EXPECTED_PRODUCT_ID or symbol != EXPECTED_SYMBOL:
        raise ContractVerificationError(
            f"Unexpected instrument identity: id={product_id}, symbol={symbol}"
        )
    if contract_type != "perpetual_futures":
        raise ContractVerificationError(f"Unexpected contract_type: {contract_type}")
    if state != "live" or trading_status != "operational":
        raise ContractVerificationError(
            f"Contract not operational: state={state}, trading_status={trading_status}"
        )
    if contract_value != Decimal("0.001") or contract_unit_currency != "BTC":
        raise ContractVerificationError("BTCUSD contract value/unit differs from expected 0.001 BTC")
    if tick_size != Decimal("0.5"):
        raise ContractVerificationError(f"BTCUSD tick size differs from documented 0.5: {tick_size}")
    if quoting_asset != "USD":
        raise ContractVerificationError(f"Unexpected quoting asset: {quoting_asset}")
    if funding_interval_seconds != 28_800:
        raise ContractVerificationError(
            f"Funding interval differs from documented 28800 seconds: {funding_interval_seconds}"
        )

    # Delta India documentation states the minimum futures size is 0.001 BTC
    # and its order examples use whole-number lot quantities.
    return VerifiedContract(
        product_id=product_id,
        symbol=symbol,
        contract_type=contract_type,
        state=state,
        trading_status=trading_status,
        contract_value=contract_value,
        contract_unit_currency=contract_unit_currency,
        tick_size=tick_size,
        quoting_asset=quoting_asset,
        api_settling_asset=api_settling_asset,
        funding_interval_seconds=funding_interval_seconds,
        minimum_order_lots=1,
        quantity_unit="whole_number_of_lots",
        btc_per_lot=Decimal("0.001"),
    )


def fetch_btcusd_product(timeout_seconds: int = 10) -> dict[str, Any]:
    """Fetch BTCUSD directly by symbol using Delta's documented public endpoint."""
    request = Request(
        f"{BASE_URL}{PRODUCTS_PATH}/{EXPECTED_SYMBOL}",
        headers={"Accept": "application/json", "User-Agent": "shashi-systems-lab/0.1"},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise ContractVerificationError(f"Public BTCUSD product request failed: {exc}") from exc

    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ContractVerificationError("Delta product API returned an unsuccessful response")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ContractVerificationError("Expected a single product object in API result")
    if str(result.get("symbol", "")).upper() != EXPECTED_SYMBOL:
        raise ContractVerificationError(
            f"Symbol endpoint returned unexpected product: {result.get('symbol')!r}"
        )
    return result


def verify_live_contract() -> VerifiedContract:
    return parse_product(fetch_btcusd_product())


def to_json_dict(contract: VerifiedContract) -> dict[str, Any]:
    """Return JSON-safe output while preserving exact decimal values as strings."""
    result = asdict(contract)
    for key, value in result.items():
        if isinstance(value, Decimal):
            result[key] = str(value)
    return result
