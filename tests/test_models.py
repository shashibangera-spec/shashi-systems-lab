from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from shashi_engine.models import Candle, FundingObservation, Instrument, Ticker


NOW = datetime(2026, 11, 20, 21, 30, tzinfo=timezone.utc)


def test_instrument_keeps_api_settlement_separate_from_documented_margin_currency() -> None:
    instrument = Instrument(
        product_id=27, symbol="BTCUSD", contract_type="perpetual_futures",
        state="live", trading_status="operational", contract_value=Decimal("0.001"),
        contract_value_asset="BTC", tick_size=Decimal("0.50"), quote_asset="USD",
        api_settlement_asset="USD", funding_interval_seconds=28_800,
        minimum_order_lots=1, documented_margin_currency="INR",
        documented_effective_settlement_currency="INR",
    )
    assert instrument.contract_value == Decimal("0.001")
    assert instrument.tick_size == Decimal("0.50")
    assert instrument.api_settlement_asset == "USD"
    assert instrument.documented_margin_currency == "INR"
    assert instrument.documented_effective_settlement_currency == "INR"


def test_instrument_does_not_infer_margin_currency_from_api_settlement() -> None:
    instrument = Instrument(
        27, "BTCUSD", "perpetual_futures", "live", "operational",
        Decimal("0.001"), "BTC", Decimal("0.5"), "USD", "USD", 28_800,
    )
    assert instrument.api_settlement_asset == "USD"
    assert instrument.documented_margin_currency is None
    assert instrument.documented_effective_settlement_currency is None


def test_instrument_rejects_non_positive_tick_size() -> None:
    with pytest.raises(ValueError, match="tick_size"):
        Instrument(
            27, "BTCUSD", "perpetual_futures", "live", "operational",
            Decimal("0.001"), "BTC", Decimal("0"), "USD", "USD", 28_800,
        )


def test_ticker_requires_utc_timestamp_and_valid_bid_ask() -> None:
    with pytest.raises(ValueError, match="UTC"):
        Ticker("BTCUSD", datetime(2026, 11, 20, 21, 30), None, None, None, None)
    with pytest.raises(ValueError, match="best_bid"):
        Ticker("BTCUSD", NOW, None, None, Decimal("101"), Decimal("100"))


def test_market_data_models_accept_timezone_aware_utc_timestamps() -> None:
    ticker = Ticker("BTCUSD", NOW, Decimal("65000"), Decimal("65001"), None, None)
    funding = FundingObservation("BTCUSD", NOW, Decimal("0.0001"), None)
    assert ticker.observed_at.tzinfo == timezone.utc
    assert funding.observed_at.tzinfo == timezone.utc


def test_funding_rate_may_be_negative_but_must_be_finite() -> None:
    funding = FundingObservation("BTCUSD", NOW, Decimal("-0.0002"), None)
    assert funding.funding_rate == Decimal("-0.0002")
    with pytest.raises(ValueError, match="finite"):
        FundingObservation("BTCUSD", NOW, Decimal("NaN"), None)


def make_candle(start: datetime = NOW - timedelta(minutes=30), **changes: Decimal) -> Candle:
    values = {
        "symbol": "BTCUSD", "resolution": "30m", "start_time": start,
        "open": Decimal("100"), "high": Decimal("110"), "low": Decimal("90"),
        "close": Decimal("105"), "volume": Decimal("12"),
    }
    values.update(changes)
    return Candle(**values)


def test_candle_validates_ohlcv_and_computes_interval_end() -> None:
    assert make_candle().end_time == NOW


@pytest.mark.parametrize(
    "changes",
    [
        {"high": Decimal("99")}, {"low": Decimal("106")},
        {"volume": Decimal("-1")}, {"open": Decimal("0")},
    ],
)
def test_candle_rejects_invalid_ohlcv(changes: dict[str, Decimal]) -> None:
    with pytest.raises(ValueError):
        make_candle(**changes)


def test_candle_rejects_naive_or_unaligned_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        make_candle(start=datetime(2026, 11, 20, 21, 0))
    with pytest.raises(ValueError, match="half-hour"):
        make_candle(start=datetime(2026, 11, 20, 21, 15, tzinfo=timezone.utc))
