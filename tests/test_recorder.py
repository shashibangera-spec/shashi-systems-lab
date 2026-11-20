from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

import pytest

from shashi_engine.feed_health import FeedHealthMonitor
from shashi_engine.models import Candle
from shashi_engine.recorder import (
    AppendOnlyJsonlRecorder,
    RecorderError,
    recover_missing_candles,
)

T0 = datetime(2026, 11, 21, 0, 0, tzinfo=timezone.utc)


def candle(offset_minutes: int) -> Candle:
    return Candle(
        symbol="BTCUSD",
        resolution="30m",
        start_time=T0 + timedelta(minutes=offset_minutes),
        open=Decimal("60000"),
        high=Decimal("60100"),
        low=Decimal("59900"),
        close=Decimal("60050"),
        volume=Decimal("12.5"),
    )


def epoch(stamp: datetime) -> int:
    return int(stamp.timestamp())


def test_append_only_writer_appends_jsonl_records(tmp_path):
    path = tmp_path / "market" / "btc.jsonl"
    recorder = AppendOnlyJsonlRecorder(path)
    recorder.append({"record_type": "feed_health", "state": "CONNECTED"})
    recorder.append({"record_type": "feed_health", "state": "STALE"})
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["state"] for row in rows] == ["CONNECTED", "STALE"]
    assert all("recorded_at_utc" in row for row in rows)


def test_canonical_candle_is_not_appended_twice(tmp_path):
    recorder = AppendOnlyJsonlRecorder(tmp_path / "btc.jsonl")
    assert recorder.append_candle(candle(0), record_type="completed_candle", source="websocket")
    assert not recorder.append_candle(candle(0), record_type="rest_recovery", source="rest")
    assert len((tmp_path / "btc.jsonl").read_text().splitlines()) == 1


def test_existing_history_is_loaded_for_duplicate_protection(tmp_path):
    path = tmp_path / "btc.jsonl"
    first = AppendOnlyJsonlRecorder(path)
    first.append_candle(candle(0), record_type="completed_candle", source="websocket")
    reopened = AppendOnlyJsonlRecorder(path)
    assert reopened.latest_candle_start == T0
    assert not reopened.append_candle(candle(0), record_type="rest_recovery", source="rest")


def test_corrupt_existing_jsonl_fails_closed(tmp_path):
    path = tmp_path / "btc.jsonl"
    path.write_text('{"record_type":"ok"}\nnot-json\n', encoding="utf-8")
    with pytest.raises(RecorderError, match="invalid JSON"):
        AppendOnlyJsonlRecorder(path)


def test_blank_existing_line_fails_closed(tmp_path):
    path = tmp_path / "btc.jsonl"
    path.write_text('{"record_type":"ok"}\n\n', encoding="utf-8")
    with pytest.raises(RecorderError, match="blank line"):
        AppendOnlyJsonlRecorder(path)


def test_recovery_appends_returned_candles_and_reports_missing(tmp_path):
    recorder = AppendOnlyJsonlRecorder(tmp_path / "btc.jsonl")
    calls = []

    def fetcher(start, end, resolution):
        calls.append((start, end, resolution))
        return [candle(0), candle(30)]

    result = recover_missing_candles(
        recorder, start_epoch=epoch(T0), end_epoch=epoch(T0 + timedelta(minutes=90)),
        fetcher=fetcher, max_intervals=4,
    )
    assert calls == [(epoch(T0), epoch(T0 + timedelta(minutes=90)), "30m")]
    assert result["requested_intervals"] == 3
    assert result["recovered"] == [T0.isoformat(), (T0 + timedelta(minutes=30)).isoformat()]
    assert result["unresolved"] == [(T0 + timedelta(minutes=60)).isoformat()]
    rows = [json.loads(line) for line in (tmp_path / "btc.jsonl").read_text().splitlines()]
    assert [row["record_type"] for row in rows] == ["rest_recovery", "rest_recovery", "recovery_report"]


def test_empty_rest_response_reports_all_intervals_unresolved(tmp_path):
    recorder = AppendOnlyJsonlRecorder(tmp_path / "btc.jsonl")
    result = recover_missing_candles(
        recorder, start_epoch=epoch(T0), end_epoch=epoch(T0 + timedelta(minutes=60)),
        fetcher=lambda *_: [], max_intervals=2,
    )
    assert result["recovered"] == []
    assert len(result["unresolved"]) == 2


def test_recovery_rejects_duplicate_rest_candles_before_writing(tmp_path):
    recorder = AppendOnlyJsonlRecorder(tmp_path / "btc.jsonl")
    with pytest.raises(RecorderError, match="duplicate"):
        recover_missing_candles(
            recorder, start_epoch=epoch(T0), end_epoch=epoch(T0 + timedelta(minutes=60)),
            fetcher=lambda *_: [candle(0), candle(0)], max_intervals=2,
        )
    assert not (tmp_path / "btc.jsonl").exists()


def test_recovery_rejects_out_of_order_rest_candles_before_writing(tmp_path):
    recorder = AppendOnlyJsonlRecorder(tmp_path / "btc.jsonl")
    with pytest.raises(RecorderError, match="out-of-order"):
        recover_missing_candles(
            recorder, start_epoch=epoch(T0), end_epoch=epoch(T0 + timedelta(minutes=60)),
            fetcher=lambda *_: [candle(30), candle(0)], max_intervals=2,
        )
    assert not (tmp_path / "btc.jsonl").exists()


def test_recovery_rejects_candle_outside_requested_gap(tmp_path):
    recorder = AppendOnlyJsonlRecorder(tmp_path / "btc.jsonl")
    with pytest.raises(RecorderError, match="outside"):
        recover_missing_candles(
            recorder, start_epoch=epoch(T0), end_epoch=epoch(T0 + timedelta(minutes=30)),
            fetcher=lambda *_: [candle(30)], max_intervals=1,
        )


def test_recovery_rejects_unaligned_window(tmp_path):
    recorder = AppendOnlyJsonlRecorder(tmp_path / "btc.jsonl")
    with pytest.raises(ValueError, match="align"):
        recover_missing_candles(
            recorder, start_epoch=epoch(T0) + 1, end_epoch=epoch(T0 + timedelta(minutes=30)),
            fetcher=lambda *_: [], max_intervals=1,
        )


def test_recovery_enforces_maximum_window(tmp_path):
    recorder = AppendOnlyJsonlRecorder(tmp_path / "btc.jsonl")
    with pytest.raises(ValueError, match="exceeds"):
        recover_missing_candles(
            recorder, start_epoch=epoch(T0), end_epoch=epoch(T0 + timedelta(minutes=90)),
            fetcher=lambda *_: [], max_intervals=2,
        )


def test_zero_length_recovery_is_noop(tmp_path):
    recorder = AppendOnlyJsonlRecorder(tmp_path / "btc.jsonl")
    result = recover_missing_candles(
        recorder, start_epoch=epoch(T0), end_epoch=epoch(T0),
        fetcher=lambda *_: pytest.fail("fetcher should not be called"),
    )
    assert result == {"requested_intervals": 0, "recovered": [], "unresolved": []}


def test_feed_health_transitions_connected_stale_connected_disconnected():
    transitions = []
    monitor = FeedHealthMonitor(
        stale_after=timedelta(seconds=30),
        on_transition=lambda state, at, last: transitions.append((state, at, last)),
    )
    monitor.connected(T0)
    assert monitor.check(T0 + timedelta(seconds=31)) == "STALE"
    monitor.message_received(T0 + timedelta(seconds=32))
    monitor.disconnected(T0 + timedelta(seconds=33))
    assert [item[0] for item in transitions] == ["CONNECTED", "STALE", "CONNECTED", "DISCONNECTED"]


def test_feed_becomes_stale_even_if_no_first_message_arrives():
    transitions = []
    monitor = FeedHealthMonitor(
        stale_after=timedelta(seconds=10),
        on_transition=lambda state, at, last: transitions.append(state),
    )
    monitor.connected(T0)
    assert monitor.check(T0 + timedelta(seconds=11)) == "STALE"
    assert transitions == ["CONNECTED", "STALE"]


def test_duplicate_health_checks_do_not_emit_duplicate_transitions():
    transitions = []
    monitor = FeedHealthMonitor(
        stale_after=timedelta(seconds=5),
        on_transition=lambda state, at, last: transitions.append(state),
    )
    monitor.connected(T0)
    monitor.check(T0 + timedelta(seconds=6))
    monitor.check(T0 + timedelta(seconds=7))
    assert transitions == ["CONNECTED", "STALE"]


def test_feed_health_rejects_naive_timestamps():
    monitor = FeedHealthMonitor(
        stale_after=timedelta(seconds=5),
        on_transition=lambda *_: None,
    )
    with pytest.raises(ValueError, match="UTC"):
        monitor.connected(datetime(2026, 11, 21))
