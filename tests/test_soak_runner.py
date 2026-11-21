from pathlib import Path

import pytest

from scripts.run_btcusd_soak import (
    MAX_RECORDING_SECONDS,
    MIN_RECORDING_SECONDS,
    sha256_prefix,
    split_recording_duration,
)


@pytest.mark.parametrize("total,expected", [
    (7200, [2400, 2400, 2400]),
    (7201, [2400, 2400, 2401]),
    (14400, [4800, 4800, 4800]),
])
def test_recording_duration_is_split_across_three_sessions(total, expected):
    assert split_recording_duration(total) == expected


@pytest.mark.parametrize("total", [MIN_RECORDING_SECONDS - 1, MAX_RECORDING_SECONDS + 1, 0, -1])
def test_recording_duration_rejects_out_of_range_values(total):
    with pytest.raises(ValueError):
        split_recording_duration(total)


def test_sha256_prefix_hashes_only_the_requested_existing_prefix(tmp_path: Path):
    path = tmp_path / "recording.jsonl"
    path.write_bytes(b"first\nsecond\n")
    prefix_hash = sha256_prefix(path, len(b"first\n"))
    path.write_bytes(b"first\nsecond\nthird\n")
    assert prefix_hash == sha256_prefix(path, len(b"first\n"))


def test_sha256_prefix_rejects_file_shorter_than_requested(tmp_path: Path):
    path = tmp_path / "recording.jsonl"
    path.write_bytes(b"short")
    with pytest.raises(ValueError, match="shorter"):
        sha256_prefix(path, 100)
