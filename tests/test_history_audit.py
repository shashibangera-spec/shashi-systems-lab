import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from shashi_engine.history_audit import (
    audit_jsonl_history, validate_rest_gap, verify_restart_integrity,
)
from shashi_engine.models import Candle
from shashi_engine.recorder import AppendOnlyJsonlRecorder, RecorderError, recover_missing_candles

T0 = datetime(2026, 11, 21, 0, 0, tzinfo=timezone.utc)


def candle(offset_minutes: int) -> Candle:
    return Candle(
        symbol="BTCUSD", resolution="30m",
        start_time=T0 + timedelta(minutes=offset_minutes),
        open=Decimal("60000"), high=Decimal("60100"),
        low=Decimal("59900"), close=Decimal("60050"), volume=Decimal("12.5"),
    )


def write_candles(path, offsets=(0, 30, 60)):
    recorder = AppendOnlyJsonlRecorder(path)
    for offset in offsets:
        recorder.append_candle(candle(offset), record_type="completed_candle", source="websocket")


def test_audit_accepts_valid_history_and_preserves_exact_bytes(tmp_path):
    path = tmp_path / "btc.jsonl"
    write_candles(path)
    before = path.read_bytes()
    report = audit_jsonl_history(path)
    assert report.acceptable
    assert report.canonical_candles == 3
    assert report.websocket_candles == 3
    assert report.missing_intervals == 0
    assert path.read_bytes() == before
    assert report.sha256_before == hashlib.sha256(before).hexdigest()


def test_audit_reports_duplicates_out_of_order_and_gaps(tmp_path):
    path = tmp_path / "btc.jsonl"
    recorder = AppendOnlyJsonlRecorder(path)
    for offset in (0, 60, 30):
        recorder.append_candle(candle(offset), record_type="completed_candle", source="websocket")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(path.read_text(encoding="utf-8").splitlines()[0] + "\n")
    report = audit_jsonl_history(path)
    assert report.duplicate_starts == (T0.isoformat(),)
    assert report.out_of_order_pairs
    assert report.missing_intervals == 0
    assert not report.acceptable


def test_audit_reports_missing_intervals(tmp_path):
    path = tmp_path / "btc.jsonl"
    write_candles(path, (0, 90))
    report = audit_jsonl_history(path)
    assert report.missing_intervals == 2
    assert not report.acceptable


@pytest.mark.parametrize("content,expected", [
    ('{"record_type":"feed_health"}\nnot-json\n', "invalid JSON"),
    ('{"record_type":"feed_health"}\n\n', "blank line"),
    ('{"record_type":"feed_health"}', "unterminated"),
])
def test_audit_reports_malformed_jsonl(tmp_path, content, expected):
    path = tmp_path / "bad.jsonl"
    path.write_text(content, encoding="utf-8")
    report = audit_jsonl_history(path)
    assert any(expected in issue for issue in report.malformed_lines)
    assert not report.acceptable


def test_audit_flags_bad_canonical_provenance_and_end_time(tmp_path):
    path = tmp_path / "bad.jsonl"
    row = {
        "record_type": "rest_recovery", "source": "websocket",
        "symbol": "BTCUSD", "resolution": "30m",
        "candle_start_utc": T0.isoformat(),
        "candle_end_utc": (T0 + timedelta(minutes=30)).isoformat(),
        "open": "60000", "high": "60100", "low": "59900",
        "close": "60050", "volume": "1",
    }
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    report = audit_jsonl_history(path)
    assert any("type/source mismatch" in issue for issue in report.structural_issues)
    assert not report.acceptable


def test_recovery_report_counts_must_not_exceed_requested(tmp_path):
    path = tmp_path / "btc.jsonl"
    path.write_text(json.dumps({
        "record_type": "recovery_report", "requested_intervals": 3,
        "recovered_count": 4, "unresolved": [],
    }) + "\n", encoding="utf-8")
    report = audit_jsonl_history(path)
    assert report.recovery_report_issues
    assert not report.acceptable


def test_old_unresolved_report_is_cleared_when_later_history_fills_gap(tmp_path):
    path = tmp_path / "btc.jsonl"
    recorder = AppendOnlyJsonlRecorder(path)
    recover_missing_candles(
        recorder, start_epoch=int(T0.timestamp()),
        end_epoch=int((T0 + timedelta(minutes=60)).timestamp()),
        fetcher=lambda *_: [candle(0)],
    )
    reopened = AppendOnlyJsonlRecorder(path)
    assert reopened.append_candle(candle(30), record_type="rest_recovery", source="rest")
    report = audit_jsonl_history(path)
    assert report.unresolved_recovery_intervals == 0
    assert report.acceptable


def test_rest_gap_validation_is_read_only_and_reports_missing(tmp_path):
    path = tmp_path / "btc.jsonl"
    write_candles(path, (0,))
    before = path.read_bytes()
    result = validate_rest_gap(
        int(T0.timestamp()), int((T0 + timedelta(minutes=90)).timestamp()),
        fetcher=lambda *_: [candle(0), candle(30)],
    )
    assert result["requested_intervals"] == 3
    assert result["unresolved"] == [(T0 + timedelta(minutes=60)).isoformat()]
    assert not result["valid"]
    assert path.read_bytes() == before


def test_rest_gap_validation_sorts_newest_first_and_ignores_boundaries():
    result = validate_rest_gap(
        int(T0.timestamp()), int((T0 + timedelta(minutes=60)).timestamp()),
        fetcher=lambda *_: [candle(60), candle(30), candle(0), candle(-30)],
    )
    assert result["valid"]
    assert result["returned"] == [T0.isoformat(), (T0 + timedelta(minutes=30)).isoformat()]
    assert result["unresolved"] == []


def test_rest_gap_validation_still_rejects_non_boundary_out_of_range_candle():
    with pytest.raises(RecorderError, match="outside"):
        validate_rest_gap(
            int(T0.timestamp()), int((T0 + timedelta(minutes=60)).timestamp()),
            fetcher=lambda *_: [candle(90)],
        )


def test_rest_gap_validation_rejects_duplicate_before_any_write():
    with pytest.raises(RecorderError, match="duplicate"):
        validate_rest_gap(
            int(T0.timestamp()), int((T0 + timedelta(minutes=60)).timestamp()),
            fetcher=lambda *_: [candle(0), candle(0)],
        )


def test_existing_recovery_writer_and_audit_reconcile(tmp_path):
    path = tmp_path / "btc.jsonl"
    recorder = AppendOnlyJsonlRecorder(path)
    result = recover_missing_candles(
        recorder, start_epoch=int(T0.timestamp()),
        end_epoch=int((T0 + timedelta(minutes=90)).timestamp()),
        fetcher=lambda *_: [candle(0), candle(30), candle(60)],
    )
    assert not result["unresolved"]
    report = audit_jsonl_history(path)
    assert report.rest_recovery_candles == 3
    assert report.unresolved_recovery_intervals == 0
    assert report.acceptable


def test_restart_reopen_does_not_change_existing_bytes(tmp_path):
    path = tmp_path / "btc.jsonl"
    write_candles(path)
    before = path.read_bytes()
    result = verify_restart_integrity(path)
    assert result["status"] == "PASS"
    assert result["history_unchanged"]
    assert path.read_bytes() == before


def test_restart_reloads_duplicate_protection_and_append_continues(tmp_path):
    path = tmp_path / "btc.jsonl"
    write_candles(path, (0, 30))
    original = path.read_bytes()
    reopened = AppendOnlyJsonlRecorder(path)
    assert not reopened.append_candle(candle(30), record_type="rest_recovery", source="rest")
    assert reopened.append_candle(candle(60), record_type="completed_candle", source="websocket")
    after = path.read_bytes()
    assert after.startswith(original)
    assert len(after.splitlines()) == 3
    assert audit_jsonl_history(path).acceptable
