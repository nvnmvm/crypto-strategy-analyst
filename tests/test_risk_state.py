from __future__ import annotations

from datetime import date

import pytest

from crypto_strategy_analyst.errors import RiskStateError
from crypto_strategy_analyst.risk import RiskState, RiskStateStore


def test_missing_state_starts_safely(tmp_path):
    store = RiskStateStore(tmp_path / "risk.json")
    state = store.load(current_date=date(2026, 6, 30), initial_equity_cny=1000)
    assert state.date == date(2026, 6, 30)
    assert state.daily_stop_losses == 0
    assert state.daily_realized_loss_cny == 0
    assert state.peak_equity_cny == 1000


def test_corrupt_state_fails_closed(tmp_path):
    path = tmp_path / "risk.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(RiskStateError, match="corrupt"):
        RiskStateStore(path).load(current_date=date(2026, 6, 30), initial_equity_cny=1000)


def test_date_rollover_preserves_drawdown_and_peak(tmp_path):
    store = RiskStateStore(tmp_path / "risk.json")
    state = RiskState(
        date=date(2026, 6, 29),
        daily_stop_losses=2,
        daily_realized_loss_cny=20,
        peak_equity_cny=1200,
        current_drawdown=0.25,
    )
    store.save(state)
    loaded = store.load(current_date=date(2026, 6, 30), initial_equity_cny=1000)
    assert loaded.daily_stop_losses == 0
    assert loaded.daily_realized_loss_cny == 0
    assert loaded.peak_equity_cny == 1200
    assert loaded.current_drawdown == 0.25


def test_atomic_save_replaces_valid_json(tmp_path):
    path = tmp_path / "risk.json"
    store = RiskStateStore(path)
    state = RiskState(date=date(2026, 6, 30), peak_equity_cny=1000).with_realized_result(
        -10,
        stopped_out=True,
    )
    store.save(state)
    loaded = store.load(current_date=date(2026, 6, 30), initial_equity_cny=1000)
    assert loaded.daily_stop_losses == 1
    assert loaded.daily_realized_loss_cny == 10
    assert not list(tmp_path.glob("*.tmp"))
