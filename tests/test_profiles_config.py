from pathlib import Path

import pytest

from crypto_strategy_analyst.config import AppConfig, load_config
from crypto_strategy_analyst.profiles.registry import get_profile, profile_for_symbol


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("BTC/USDT", "btc"),
        ("ETHUSDT", "eth"),
        ("BNB-USDT", "bnb"),
        ("SOL_USDT", "sol"),
        ("XRPUSDT", "generic"),
    ],
)
def test_auto_profiles(symbol, expected):
    assert profile_for_symbol(symbol).name == expected


def test_forced_profile_and_unknown():
    assert get_profile("btc", "ETHUSDT").name == "btc"
    with pytest.raises(ValueError, match="unknown profile"):
        get_profile("wat", "BTCUSDT")


def test_layered_config(tmp_path: Path):
    override = tmp_path / "local.yaml"
    override.write_text("risk:\n  account_equity: 999\n", encoding="utf-8")
    config = load_config(override, "sol", {"risk": {"risk_per_trade": 0.02}})
    assert config.profile == "sol"
    assert config.risk.account_equity == 999
    assert config.risk.risk_per_trade == 0.02
    assert config.risk.maximum_position_fraction == 0.18


def test_config_rejects_futures_and_confirmation_bypass():
    with pytest.raises(ValueError, match="futures"):
        AppConfig.model_validate({"trading": {"futures_enabled": True}})
    with pytest.raises(ValueError, match="confirmation"):
        AppConfig.model_validate(
            {"trading": {"trading_enabled": True, "require_human_confirmation": False}}
        )
