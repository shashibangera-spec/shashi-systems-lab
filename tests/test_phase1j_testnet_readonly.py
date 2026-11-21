from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import patch

import pytest

from shashi_engine.phase1j_testnet_readonly import (
    BASE_URL,
    PRODUCT_PATH,
    DeltaIndiaTestnetReadOnlyClient,
    DeltaReadOnlyError,
    load_local_credentials,
)


def test_client_has_only_fixed_get_methods():
    public = {name for name in dir(DeltaIndiaTestnetReadOnlyClient) if name.startswith("get_")}
    assert public == {"get_product", "get_positions", "get_open_orders", "get_fills", "get_wallet_balances"}
    assert not hasattr(DeltaIndiaTestnetReadOnlyClient, "post")
    assert not hasattr(DeltaIndiaTestnetReadOnlyClient, "put")
    assert not hasattr(DeltaIndiaTestnetReadOnlyClient, "delete")


def test_base_url_is_exact_india_testnet_and_not_production_or_global():
    assert BASE_URL == "https://cdn-ind.testnet.deltaex.org"
    assert "api.india.delta.exchange" not in BASE_URL
    assert "testnet-api.delta.exchange" not in BASE_URL


def test_signature_uses_get_timestamp_path_and_sorted_query():
    client = DeltaIndiaTestnetReadOnlyClient("key", "secret")
    expected = hmac.new(b"secret", b"GET1700000000/v2/positions?product_id=27", hashlib.sha256).hexdigest()
    with patch("shashi_engine.phase1j_testnet_readonly.time.time", return_value=1700000000):
        with patch.object(client._opener, "open") as mocked:
            response = type("Response", (), {
                "__enter__": lambda self: self,
                "__exit__": lambda self, *args: None,
                "read": lambda self, n: json.dumps({"success": True, "result": []}).encode(),
            })()
            mocked.return_value = response
            client.get_positions()
            req = mocked.call_args.args[0]
            assert req.get_method() == "GET"
            assert req.full_url == BASE_URL + "/v2/positions?product_id=27"
            assert req.get_header("Api-key") == "key"
            assert req.get_header("Signature") == expected
            assert req.get_header("Timestamp") == "1700000000"


def test_unknown_endpoint_is_rejected_before_network():
    client = DeltaIndiaTestnetReadOnlyClient("key", "secret")
    with pytest.raises(DeltaReadOnlyError, match="allowlist"):
        client._get("/v2/orders/batch")


def test_response_failure_does_not_leak_credentials():
    client = DeltaIndiaTestnetReadOnlyClient("DO_NOT_PRINT_KEY", "DO_NOT_PRINT_SECRET")
    with patch.object(client._opener, "open", side_effect=OSError("network")):
        with pytest.raises(DeltaReadOnlyError) as err:
            client.get_positions()
    assert "DO_NOT_PRINT" not in str(err.value)


def test_credentials_are_read_from_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DELTA_TESTNET_API_KEY", "local-key")
    monkeypatch.setenv("DELTA_TESTNET_API_SECRET", "local-secret")
    assert load_local_credentials() == ("local-key", "local-secret")


def test_dotenv_is_supported_without_overriding_process_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        'DELTA_TESTNET_API_KEY="file-key"\nDELTA_TESTNET_API_SECRET=file-secret\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("DELTA_TESTNET_API_KEY", raising=False)
    monkeypatch.delenv("DELTA_TESTNET_API_SECRET", raising=False)
    assert load_local_credentials() == ("file-key", "file-secret")


def test_missing_credentials_fail_closed(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DELTA_TESTNET_API_KEY", raising=False)
    monkeypatch.delenv("DELTA_TESTNET_API_SECRET", raising=False)
    with pytest.raises(DeltaReadOnlyError, match="Missing"):
        load_local_credentials()


def test_timeout_range_is_bounded():
    with pytest.raises(ValueError):
        DeltaIndiaTestnetReadOnlyClient("key", "secret", timeout=60)
