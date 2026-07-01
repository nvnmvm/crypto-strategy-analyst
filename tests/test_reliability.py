from __future__ import annotations

import json
import logging
import time

import httpx
import pytest

from crypto_strategy_analyst.config import MarketConfig
from crypto_strategy_analyst.data import BinancePublicClient
from crypto_strategy_analyst.errors import MarketDataError
from crypto_strategy_analyst.logging_utils import JsonFormatter


class _FailingClient:
    def __init__(self):
        self.calls = 0

    def get(self, *args, **kwargs):
        del args, kwargs
        self.calls += 1
        raise httpx.ConnectError("offline")


def test_retries_are_bounded_and_open_circuit_stops_more_requests():
    client = _FailingClient()
    config = MarketConfig(
        max_retries=5,
        retry_backoff_base_seconds=0,
        circuit_failure_threshold=2,
        circuit_cooldown_seconds=60,
    )
    public = BinancePublicClient(config, client=client)
    with pytest.raises(MarketDataError, match="circuit_open:market_data"):
        public.fetch_klines("BTC/USDT", "4h")
    assert client.calls == 2

    with pytest.raises(MarketDataError, match="circuit_open:market_data"):
        public.fetch_klines("BTC/USDT", "4h")
    assert client.calls == 2


def test_structured_log_drops_secrets_and_paths():
    record = logging.LogRecord(
        name="crypto_strategy_analyst.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="safe message",
        args=(),
        exc_info=None,
    )
    record.event_data = {
        "event_name": "public_request",
        "symbol": "BTCUSDT",
        "api_key": "SECRET",
        "private_path": "/Users/name/state.json",
    }
    payload = json.loads(JsonFormatter().format(record))
    assert payload["data"] == {"event_name": "public_request", "symbol": "BTCUSDT"}
    assert "SECRET" not in json.dumps(payload)


def test_exchange_rules_stale_cache_is_explicit(trading_rules):
    public = BinancePublicClient(MarketConfig(), client=_FailingClient())
    public._rules_cache["BTCUSDT"] = trading_rules
    public._circuit_open_until = time.monotonic() + 60
    cached = public.fetch_symbol_trading_rules("BTC/USDT")
    assert "exchange_rules_stale_cache" in cached.data_source
