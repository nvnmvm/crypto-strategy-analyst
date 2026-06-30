from __future__ import annotations

import json

import pytest

import crypto_strategy_analyst.cli as cli_module
from crypto_strategy_analyst.cli import main
from crypto_strategy_analyst.risk import RiskStateStore, calculate_position


def _last_json(capsys):
    return json.loads(capsys.readouterr().out)


def test_risk_cli_lifecycle(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state_path = tmp_path / "risk.json"

    assert main(["risk", "initialize", "--equity-cny", "1000", "--risk-state", str(state_path)]) == 0
    initialized = _last_json(capsys)
    assert initialized["current_equity_cny"] == 1000

    assert main(["risk", "status", "--risk-state", str(state_path)]) == 0
    assert _last_json(capsys)["new_trade_allowed"] is True

    assert main(
        ["risk", "update-equity", "--equity-cny", "950", "--risk-state", str(state_path)]
    ) == 0
    assert _last_json(capsys)["current_drawdown"] == pytest.approx(0.05)

    assert main(
        [
            "risk",
            "record-trade",
            "--trade-id",
            "cli-loss-1",
            "--pnl-cny",
            "-10",
            "--stopped-out",
            "--risk-state",
            str(state_path),
        ]
    ) == 0
    traded = _last_json(capsys)
    assert traded["current_equity_cny"] == 940
    assert traded["daily_realized_loss_cny"] == 10
    assert traded["daily_stop_losses"] == 1
    assert traded["equity_rule"] == "new_equity = previous_equity + pnl_cny"

    assert main(["risk", "reset-daily", "--risk-state", str(state_path)]) == 0
    reset = _last_json(capsys)
    assert reset["daily_stop_losses"] == 0
    assert reset["daily_realized_loss_cny"] == 0
    assert reset["current_equity_cny"] == 940
    assert "warning" in reset


def test_position_cli_uses_persisted_equity_and_shared_sizing(
    tmp_path, capsys, monkeypatch, trading_rules
):
    state_path = tmp_path / "risk.json"
    RiskStateStore(state_path).initialize(
        current_date=cli_module.datetime.now(cli_module.UTC).date(), equity_cny=500
    )

    class _RulesClient:
        def __init__(self, config):
            del config

        def fetch_symbol_trading_rules(self, symbol):
            del symbol
            return trading_rules

    monkeypatch.setattr(cli_module, "BinancePublicClient", _RulesClient)
    assert main(
        [
            "position",
            "--entry",
            "100",
            "--stop",
            "95",
            "--risk-state",
            str(state_path),
        ]
    ) == 0
    payload = _last_json(capsys)
    expected = calculate_position(
        entry_price=100,
        stop_price=95,
        config=cli_module.AppConfig().risk,
        account_equity_cny=500,
        trading_rules=trading_rules,
    )
    assert payload["account_equity_cny"] == 500
    assert payload["quantity"] == expected.quantity
    assert payload["maximum_loss_cny"] == expected.risk_amount_cny
    assert payload["position_notional_cny"] == expected.position_notional_cny


def test_position_cli_missing_state_fails_closed(tmp_path, capsys):
    assert main(
        [
            "position",
            "--entry",
            "100",
            "--stop",
            "95",
            "--risk-state",
            str(tmp_path / "missing.json"),
        ]
    ) == 2
    assert "run 'risk initialize' first" in capsys.readouterr().err
