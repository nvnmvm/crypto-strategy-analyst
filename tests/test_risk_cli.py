from __future__ import annotations

import json

import pytest

from crypto_strategy_analyst.cli import main


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
