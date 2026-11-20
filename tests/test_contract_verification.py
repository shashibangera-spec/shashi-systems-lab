from decimal import Decimal

import pytest

from shashi_engine.contract_verification import (
    ContractVerificationError,
    parse_product,
)


@pytest.fixture
def btcusd_product() -> dict:
    return {
        "id": 27,
        "symbol": "BTCUSD",
        "contract_type": "perpetual_futures",
        "state": "live",
        "trading_status": "operational",
        "contract_value": "0.001",
        "contract_unit_currency": "BTC",
        "tick_size": "0.5",
        "quoting_asset": {"symbol": "USD"},
        "settling_asset": {"symbol": "USD"},
        "product_specs": {"expiry_interval": 28800},
    }


def test_parse_valid_btcusd_product(btcusd_product: dict) -> None:
    contract = parse_product(btcusd_product)
    assert contract.product_id == 27
    assert contract.symbol == "BTCUSD"
    assert contract.contract_value == Decimal("0.001")
    assert contract.tick_size == Decimal("0.5")
    assert contract.minimum_order_lots == 1
    assert contract.btc_per_lot == Decimal("0.001")
    assert contract.api_settling_asset == "USD"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", 999),
        ("symbol", "BTCUSDT"),
        ("contract_type", "futures"),
        ("state", "expired"),
        ("trading_status", "suspended"),
        ("contract_value", "0.01"),
        ("tick_size", "1"),
        ("quoting_asset", {"symbol": "INR"}),
        ("product_specs", {"expiry_interval": 3600}),
    ],
)
def test_rejects_unexpected_contract_metadata(
    btcusd_product: dict, field: str, value: object
) -> None:
    btcusd_product[field] = value
    with pytest.raises(ContractVerificationError):
        parse_product(btcusd_product)


def test_rejects_missing_required_field(btcusd_product: dict) -> None:
    del btcusd_product["settling_asset"]
    with pytest.raises(ContractVerificationError):
        parse_product(btcusd_product)
