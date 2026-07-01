"""Binance Spot adapter with signed requests and no blind order retries."""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from urllib.parse import urlencode

import httpx

from ..config import AppConfig
from ..data_sources import normalize_symbol
from ..models import OrderDraft, OrderResult
from .base import ExchangeAdapter
from .safety import SafetyError, create_draft, validate_draft


class BinanceAdapter(ExchangeAdapter):
    def __init__(self, config: AppConfig, client: httpx.Client | None = None):
        self.config = config
        self.base_url = (
            "https://testnet.binance.vision"
            if config.trading.testnet
            else "https://api.binance.com"
        )
        self.client = client or httpx.Client(timeout=config.trading.request_timeout_seconds)
        self._submitted: set[str] = set()

    def ticker(self, symbol: str) -> float:
        response = self.client.get(
            f"{self.base_url}/api/v3/ticker/price", params={"symbol": normalize_symbol(symbol)}
        )
        response.raise_for_status()
        return float(response.json()["price"])

    def create_draft(
        self, symbol: str, side: str, quantity: float, reference_price: float
    ) -> tuple[OrderDraft, str]:
        return create_draft(self.config, symbol, side, quantity, reference_price)

    def _credentials(self) -> tuple[str, str]:
        key = os.environ.get(self.config.trading.api_key_env)
        secret = os.environ.get(self.config.trading.api_secret_env)
        if not key or not secret:
            raise SafetyError("exchange credentials are missing from environment")
        return key, secret

    def _signed(self, method: str, path: str, params: dict[str, object]) -> dict[str, object]:
        key, secret = self._credentials()
        signed = {**params, "timestamp": int(time.time() * 1000)}
        signed["signature"] = hmac.new(
            secret.encode(), urlencode(signed).encode(), hashlib.sha256
        ).hexdigest()
        response = self.client.request(
            method, f"{self.base_url}{path}", params=signed, headers={"X-MBX-APIKEY": key}
        )
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise RuntimeError("unexpected exchange response")
        return value

    def query_order(self, symbol: str, client_order_id: str) -> OrderResult | None:
        try:
            data = self._signed(
                "GET",
                "/api/v3/order",
                {"symbol": normalize_symbol(symbol), "origClientOrderId": client_order_id},
            )
        except httpx.HTTPStatusError as exc:
            try:
                error = exc.response.json()
            except ValueError:
                error = {}
            if exc.response.status_code == 400 and error.get("code") == -2013:
                return None
            raise
        return self._result(data)

    def place_spot_order(self, draft: OrderDraft, confirmation_token: str) -> OrderResult:
        current = self.ticker(draft.symbol)
        validate_draft(self.config, draft, confirmation_token, current)
        existing = self.query_order(draft.symbol, draft.client_order_id)
        if existing:
            return existing
        if draft.client_order_id in self._submitted:
            raise SafetyError("duplicate order blocked")
        self._submitted.add(draft.client_order_id)
        params: dict[str, object] = {
            "symbol": draft.symbol,
            "side": draft.side,
            "type": draft.order_type,
            "quantity": format(draft.quantity, ".12g"),
            "newClientOrderId": draft.client_order_id,
        }
        try:
            return self._result(self._signed("POST", "/api/v3/order", params))
        except (httpx.TimeoutException, httpx.NetworkError):
            result = self.query_order(draft.symbol, draft.client_order_id)
            if result is None:
                raise SafetyError("order status unknown; no automatic retry performed") from None
            return result

    @staticmethod
    def _result(data: dict[str, object]) -> OrderResult:
        executed = float(data.get("executedQty", 0))
        quote = float(data.get("cummulativeQuoteQty", 0))
        return OrderResult(
            order_id=str(data.get("orderId", "unknown")),
            client_order_id=str(
                data.get("clientOrderId", data.get("origClientOrderId", "unknown"))
            ),
            symbol=str(data.get("symbol", "unknown")),
            status=str(data.get("status", "UNKNOWN")),
            executed_quantity=executed,
            average_price=quote / executed if executed else None,
            raw_status={
                key: value for key, value in data.items() if key not in {"apiKey", "secret"}
            },
        )
