from datetime import datetime, timezone
from decimal import Decimal

from shashi_engine.models import FundingObservation, Instrument, Ticker


def test_instrument_preserves_decimal_contract_values() -> None:
    instrument = Instrument(
        product_id=27,
        symbol="BTCUSD",
        contract_type="perpetual_futures",
        state="live",
        trading_status="operational",
        contract_value=Decimal("0.001"),
        contract_value_asset="BTC",
        tick_size=Decimal("0.50"),
        quote_asset="USD",
        settlement_asset="USD",
        funding_interval_seconds=28_800,
    )

    assert instrument.product_id == 27
    assert instrument.contract_value == Decimal("0.001")
    assert instrument.tick_size == Decimal("0.50")


def test_market_data_models_accept_timezone_aware_timestamps() -> None:
    now = datetime.now(timezone.utc)
    ticker = Ticker("BTCUSD", now, Decimal("65000"), Decimal("65001"), None, None)
    funding = FundingObservation("BTCUSD", now, Decimal("0.0001"), None)

    assert ticker.observed_at.tzinfo is not None
    assert funding.observed_at.tzinfo is not None
