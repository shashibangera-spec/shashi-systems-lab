from scripts.probe_btcusd_websocket import parse_candle_message


def test_parse_public_btcusd_30m_candle_message():
    parsed = parse_candle_message(
        {
            "type": "candlestick_30m",
            "sy": "BTCUSD",
            "res": "30m",
            "ts": 1795200000000000,
            "cst": 1795200000000000,
            "o": "65000.0",
            "h": "65100.0",
            "l": "64900.0",
            "c": "65050.0",
            "v": "12.5",
        }
    )
    assert parsed is not None
    assert parsed["symbol"] == "BTCUSD"
    assert parsed["resolution"] == "30m"
    assert parsed["event_time_utc"] == "2026-11-20T18:40:00+00:00"
    assert parsed["candle_start_time_utc"] == "2026-11-20T18:40:00+00:00"

    # The descriptive field has also been emitted as Unix nanoseconds.
    nanosecond_message = {
        "type": "candlestick_30m",
        "sy": "BTCUSD",
        "ts": 1795200000000000,
        "candle_start_time": 1795200000000000000,
        "o": "65000", "h": "65100", "l": "64900", "c": "65050",
    }
    parsed_ns = parse_candle_message(nanosecond_message)
    assert parsed_ns is not None
    assert parsed_ns["candle_start_time_utc"] == "2026-11-20T18:40:00+00:00"
    assert parsed["close"] == "65050.0"
    assert parsed["volume"] == "12.5"


def test_parse_ignores_other_symbols_and_channels():
    assert parse_candle_message(
        {"type": "ticker", "sy": "BTCUSD"}
    ) is None
    assert parse_candle_message(
        {"type": "candlestick_30m", "sy": "ETHUSD"}
    ) is None


def test_parse_rejects_inconsistent_ohlc():
    message = {
        "type": "candlestick_30m",
        "sy": "BTCUSD",
        "ts": 1795200000000000,
        "cst": 1795200000000000,
        "o": "65000",
        "h": "64900",
        "l": "64800",
        "c": "65050",
    }
    try:
        parse_candle_message(message)
    except ValueError as exc:
        assert "Invalid BTCUSD 30m candle message" in str(exc)
    else:
        raise AssertionError("Expected invalid OHLC message to be rejected")
