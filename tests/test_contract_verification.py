from decimal import Decimal
from io import BytesIO
import json

import pytest

from shashi_engine import contract_verification
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


def test_fetch_uses_documented_direct_symbol_endpoint(
    monkeypatch: pytest.MonkeyPatch, btcusd_product: dict
) -> None:
    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"success": True, "result": btcusd_product}).encode()

    requested_urls: list[str] = []

    def fake_urlopen(request: object, timeout: int) -> FakeResponse:
        requested_urls.append(request.full_url)  # type: ignore[attr-defined]
        return FakeResponse()

    monkeypatch.setattr(contract_verification, "urlopen", fake_urlopen)
    result = contract_verification.fetch_btcusd_product()

    assert result["symbol"] == "BTCUSD"
    assert requested_urls == [
        "https://api.india.delta.exchange/v2/products/BTCUSD"
    ]
