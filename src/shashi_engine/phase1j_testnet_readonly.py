"""Strictly read-only Delta Exchange India Testnet REST client.

Only fixed GET endpoints are exposed. No arbitrary URL, method, redirect, or
request-body interface exists in this module.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener

BASE_URL = "https://cdn-ind.testnet.deltaex.org"
BLOCKED_HOSTS = frozenset({"api.india.delta.exchange", "testnet-api.delta.exchange"})
PRODUCT_ID = 27
PRODUCT_PATH = "/v2/products/BTCUSD"
POSITIONS_PATH = "/v2/positions"
ORDERS_PATH = "/v2/orders"
FILLS_PATH = "/v2/fills"
WALLET_PATH = "/v2/wallet/balances"
USER_AGENT = "shashi-systems-lab-phase1j-readonly/1.0"


class DeltaReadOnlyError(RuntimeError):
    """A safe, non-secret-bearing exchange/client error."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DeltaReadOnlyError("Redirect refused; authenticated requests never follow redirects")


def load_local_credentials() -> tuple[str, str]:
    """Read credentials from process environment, then a local .env file.

    Existing process environment values take precedence. The .env file is
    parsed without third-party packages and is never written or displayed.
    """
    values = dict(os.environ)
    env_path = os.environ.get("DELTA_TESTNET_ENV_FILE", ".env")
    if os.path.isfile(env_path):
        with open(env_path, "r", encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1]
                if key in ("DELTA_TESTNET_API_KEY", "DELTA_TESTNET_API_SECRET"):
                    values.setdefault(key, value)
    api_key = values.get("DELTA_TESTNET_API_KEY", "").strip()
    api_secret = values.get("DELTA_TESTNET_API_SECRET", "").strip()
    if not api_key or not api_secret:
        raise DeltaReadOnlyError(
            "Missing DELTA_TESTNET_API_KEY or DELTA_TESTNET_API_SECRET. "
            "Set them in the local environment or project .env file."
        )
    return api_key, api_secret


class DeltaIndiaTestnetReadOnlyClient:
    """Fixed-operation GET-only client for Delta India Testnet."""

    def __init__(self, api_key: str, api_secret: str, timeout: float = 12.0):
        if not api_key or not api_secret:
            raise ValueError("API key and secret are required")
        if not (1 <= timeout <= 30):
            raise ValueError("timeout must be between 1 and 30 seconds")
        self._api_key = api_key
        self._api_secret = api_secret.encode("utf-8")
        self._timeout = timeout
        self._opener = build_opener(ProxyHandler({}), HTTPSHandler(), _NoRedirect())

    @staticmethod
    def _query(params: dict[str, str] | None) -> str:
        return urlencode(sorted((params or {}).items()))

    def _get(self, path: str, params: dict[str, str] | None = None, authenticated: bool = True):
        allowed = {PRODUCT_PATH, POSITIONS_PATH, ORDERS_PATH, FILLS_PATH, WALLET_PATH}
        if path not in allowed:
            raise DeltaReadOnlyError("Endpoint is not in the fixed GET allowlist")
        query = self._query(params)
        request_path = path + (("?" + query) if query else "")
        url = BASE_URL + request_path
        timestamp = str(int(time.time()))
        headers = {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        if authenticated:
            prehash = "GET" + timestamp + path + (("?" + query) if query else "")
            signature = hmac.new(
                self._api_secret, prehash.encode("utf-8"), hashlib.sha256
            ).hexdigest()
            headers.update({
                "api-key": self._api_key,
                "signature": signature,
                "timestamp": timestamp,
            })
        request = Request(url, headers=headers, method="GET")
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise DeltaReadOnlyError("Exchange response exceeded 2 MB safety limit")
                payload = json.loads(raw.decode("utf-8"))
        except HTTPError as exc:
            # Do not include response bodies or request headers; they may contain
            # account details. Never include credentials in exception text.
            raise DeltaReadOnlyError(f"Exchange GET failed with HTTP {exc.code}") from None
        except (URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError):
            raise DeltaReadOnlyError("Exchange GET failed (network, timeout, or invalid JSON)") from None
        if not isinstance(payload, dict) or payload.get("success") is not True:
            code = payload.get("error", {}).get("code") if isinstance(payload, dict) and isinstance(payload.get("error"), dict) else "unknown"
            raise DeltaReadOnlyError(f"Exchange returned an unsuccessful response ({code})")
        return payload

    def get_product(self):
        return self._get(PRODUCT_PATH, authenticated=False)

    def get_positions(self):
        return self._get(POSITIONS_PATH, {"product_id": str(PRODUCT_ID)})

    def get_open_orders(self):
        return self._get(ORDERS_PATH, {"product_id": str(PRODUCT_ID), "state": "open"})

    def get_fills(self):
        return self._get(FILLS_PATH, {"product_ids": str(PRODUCT_ID)})

    def get_wallet_balances(self):
        return self._get(WALLET_PATH)
