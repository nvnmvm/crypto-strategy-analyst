from datetime import UTC, datetime, timedelta

import pytest

from crypto_strategy_analyst.config import AppConfig
from crypto_strategy_analyst.exchange.binance import BinanceAdapter
from crypto_strategy_analyst.exchange.safety import SafetyError, create_draft, validate_draft
from crypto_strategy_analyst.models import OrderResult


def enabled_config(**trading):
    values = {"trading_enabled": True, "testnet": True, **trading}
    return AppConfig.model_validate({"trading": values})


def test_real_trading_off_by_default():
    config = AppConfig()
    draft, token = create_draft(config, "BTC/USDT", "BUY", 0.01, 100)
    with pytest.raises(SafetyError, match="disabled"):
        validate_draft(config, draft, token, 100)


@pytest.mark.parametrize(
    ("config", "draft_change", "token", "price", "message"),
    [
        (enabled_config(emergency_stop=True), {}, "valid", 100, "emergency"),
        (enabled_config(symbol_whitelist=["ETHUSDT"]), {}, "valid", 100, "whitelisted"),
        (
            enabled_config(),
            {"expires_at": datetime.now(UTC) - timedelta(seconds=1)},
            "valid",
            100,
            "expired",
        ),
        (enabled_config(), {}, "wrong", 100, "invalid confirmation"),
        (enabled_config(maximum_price_deviation=0.01), {}, "valid", 110, "deviated"),
    ],
)
def test_safety_fail_closed(config, draft_change, token, price, message):
    draft, valid_token = create_draft(config, "BTCUSDT", "BUY", 0.01, 100)
    draft = draft.model_copy(update=draft_change)
    supplied = valid_token if token == "valid" else token
    with pytest.raises(SafetyError, match=message):
        validate_draft(config, draft, supplied, price)


def test_notional_limit_and_valid_order():
    config = enabled_config()
    too_big, token = create_draft(config, "BTCUSDT", "BUY", 3, 100)
    with pytest.raises(SafetyError, match="risk limit"):
        validate_draft(config, too_big, token, 100)
    valid, token = create_draft(config, "BTCUSDT", "SELL", 0.1, 100)
    validate_draft(config, valid, token, 100)


def test_bad_side():
    with pytest.raises(SafetyError, match="BUY/SELL"):
        create_draft(AppConfig(), "BTCUSDT", "SHORT", 1, 100)


def test_adapter_returns_existing_order_without_duplicate(monkeypatch):
    config = enabled_config()
    adapter = BinanceAdapter(config)
    draft, token = adapter.create_draft("BTCUSDT", "BUY", 0.1, 100)
    existing = OrderResult(
        order_id="1",
        client_order_id=draft.client_order_id,
        symbol="BTCUSDT",
        status="FILLED",
        executed_quantity=0.1,
        average_price=100,
    )
    monkeypatch.setattr(adapter, "ticker", lambda symbol: 100)
    monkeypatch.setattr(adapter, "query_order", lambda symbol, client_id: existing)
    assert adapter.place_spot_order(draft, token) == existing


def test_result_mapping():
    result = BinanceAdapter._result(
        {
            "orderId": 1,
            "clientOrderId": "x",
            "symbol": "BTCUSDT",
            "status": "FILLED",
            "executedQty": "2",
            "cummulativeQuoteQty": "210",
        }
    )
    assert result.average_price == 105
