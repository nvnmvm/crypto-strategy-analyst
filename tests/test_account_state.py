from __future__ import annotations

import inspect
import json
from datetime import UTC, date, datetime, timedelta

import pytest

import crypto_strategy_analyst.cli as cli_module
from crypto_strategy_analyst.account import (
    AccountStateStore,
    AddSpotPosition,
    CancelPendingPlan,
    CloseSpotPosition,
    CreatePendingPlan,
    InitializeAccount,
    OpenSpotPosition,
    PendingPlan,
    RecordPartialExit,
    ResetDailyRisk,
    UpdateExternalEquity,
    UpdateMarkPrice,
    ValidatePendingPlan,
    apply_command,
    empty_account_state,
)
from crypto_strategy_analyst.errors import RiskStateError
from crypto_strategy_analyst.risk import RiskStateStore

NOW = datetime(2026, 7, 1, 8, tzinfo=UTC)


def _initialized(cash: float = 600.0):
    state = empty_account_state(NOW)
    return apply_command(
        state,
        InitializeAccount(
            command_id="init",
            timestamp=NOW,
            expected_state_version=state.state_version,
            initial_cash=cash,
        ),
    )[0]


def _plan(plan_id: str = "btc-plan") -> PendingPlan:
    return PendingPlan(
        plan_id=plan_id,
        symbol="BTC/USDT",
        created_at=NOW,
        expires_at=NOW + timedelta(hours=4),
        entry_lower=99,
        entry_upper=101,
        planned_entry=100,
        stop_price=95,
        take_profit_1=110,
        take_profit_2=115,
        initial_risk_quote=20,
    )


def _with_validated_plan():
    state = _initialized()
    state, _ = apply_command(
        state,
        CreatePendingPlan(
            command_id="create",
            timestamp=NOW,
            expected_state_version=state.state_version,
            plan=_plan(),
        ),
    )
    state, _ = apply_command(
        state,
        ValidatePendingPlan(
            command_id="validate",
            timestamp=NOW + timedelta(hours=1),
            expected_state_version=state.state_version,
            plan_id="btc-plan",
        ),
    )
    return state


def test_same_command_id_is_idempotent_and_version_conflicts_fail():
    state = _initialized()
    command = UpdateExternalEquity(
        command_id="equity-once",
        timestamp=NOW,
        expected_state_version=state.state_version,
        current_equity=590,
    )
    updated, events = apply_command(state, command)
    duplicate, duplicate_events = apply_command(updated, command)
    assert len(events) == 1
    assert duplicate == updated
    assert duplicate_events == []

    with pytest.raises(RiskStateError, match="version conflict"):
        apply_command(
            updated,
            UpdateExternalEquity(
                command_id="stale-command",
                timestamp=NOW,
                expected_state_version=state.state_version,
                current_equity=580,
            ),
        )


def test_portfolio_cash_and_aggregate_open_risk_are_hard_limits():
    state = _with_validated_plan()
    with pytest.raises(RiskStateError, match="aggregate open risk"):
        apply_command(
            state,
            OpenSpotPosition(
                command_id="too-risky",
                timestamp=NOW + timedelta(hours=1),
                expected_state_version=state.state_version,
                plan_id="btc-plan",
                position_id="btc-1",
                symbol="BTC/USDT",
                entry_price=100,
                quantity=3,
                stop_price=95,
                aggregate_open_risk_limit=0.02,
                max_symbol_deployed_fraction=1,
            ),
        )

    opened, _ = apply_command(
        state,
        OpenSpotPosition(
            command_id="open",
            timestamp=NOW + timedelta(hours=1),
            expected_state_version=state.state_version,
            plan_id="btc-plan",
            position_id="btc-1",
            symbol="BTC/USDT",
            entry_price=100,
            quantity=2,
            stop_price=95,
            aggregate_open_risk_limit=0.02,
            max_symbol_deployed_fraction=1,
        ),
    )
    assert opened.portfolio.cash == 400
    assert opened.risk.aggregate_open_risk == 10
    assert opened.portfolio.available_cash == 400


def test_bear_second_entry_requires_confirmation_never_averages_down_and_stops_at_two():
    state = _with_validated_plan()
    state, _ = apply_command(
        state,
        OpenSpotPosition(
            command_id="open-first",
            timestamp=NOW,
            expected_state_version=state.state_version,
            plan_id="btc-plan",
            position_id="btc-1",
            symbol="BTC/USDT",
            entry_price=100,
            quantity=0.5,
            stop_price=95,
            max_symbol_deployed_fraction=1,
        ),
    )
    base = dict(
        timestamp=NOW + timedelta(hours=4),
        expected_state_version=state.state_version,
        symbol="BTC/USDT",
        entry_price=102,
        quantity=0.5,
        stop_price=95,
    )
    with pytest.raises(RiskStateError, match="independent structure"):
        apply_command(
            state,
            AddSpotPosition(
                command_id="no-confirmation",
                independent_structure_confirmation=False,
                **base,
            ),
        )
    with pytest.raises(RiskStateError, match="average down"):
        apply_command(
            state,
            AddSpotPosition(
                command_id="average-down",
                independent_structure_confirmation=True,
                **{**base, "entry_price": 99},
            ),
        )
    state, _ = apply_command(
        state,
        AddSpotPosition(
            command_id="second",
            independent_structure_confirmation=True,
            **base,
        ),
    )
    assert state.portfolio.positions["BTC/USDT"].entry_count == 2
    with pytest.raises(RiskStateError, match="at most two"):
        apply_command(
            state,
            AddSpotPosition(
                command_id="third",
                timestamp=NOW + timedelta(hours=8),
                expected_state_version=state.state_version,
                symbol="BTC/USDT",
                entry_price=103,
                quantity=0.1,
                stop_price=95,
                independent_structure_confirmation=True,
            ),
        )


def test_partial_exit_mark_close_and_daily_reset_preserve_peak():
    state = _with_validated_plan()
    state, _ = apply_command(
        state,
        OpenSpotPosition(
            command_id="open",
            timestamp=NOW,
            expected_state_version=state.state_version,
            plan_id="btc-plan",
            position_id="btc-1",
            symbol="BTC/USDT",
            entry_price=100,
            quantity=2,
            stop_price=95,
            max_symbol_deployed_fraction=1,
        ),
    )
    state, _ = apply_command(
        state,
        UpdateMarkPrice(
            command_id="mark",
            timestamp=NOW,
            expected_state_version=state.state_version,
            symbol="BTC/USDT",
            mark_price=110,
        ),
    )
    assert state.risk.current_equity == 620
    assert state.risk.peak_equity == 620
    state, _ = apply_command(
        state,
        RecordPartialExit(
            command_id="partial",
            timestamp=NOW,
            expected_state_version=state.state_version,
            symbol="BTC/USDT",
            quantity=0.5,
            exit_price=90,
            stopped_out=True,
        ),
    )
    assert state.risk.realized_daily_loss == 5
    assert state.risk.daily_stop_losses == 1
    assert state.risk.aggregate_open_risk == 7.5
    state, _ = apply_command(
        state,
        CloseSpotPosition(
            command_id="close",
            timestamp=NOW,
            expected_state_version=state.state_version,
            symbol="BTC/USDT",
            exit_price=105,
        ),
    )
    peak = state.risk.peak_equity
    state, _ = apply_command(
        state,
        ResetDailyRisk(
            command_id="new-day",
            timestamp=NOW + timedelta(days=1),
            expected_state_version=state.state_version,
            new_date=date(2026, 7, 2),
        ),
    )
    assert state.risk.realized_daily_loss == 0
    assert state.risk.daily_stop_losses == 0
    assert state.risk.peak_equity == peak
    assert state.risk.aggregate_open_risk == 0


def test_cancel_pending_plan_is_auditable_transition():
    state = _initialized()
    state, _ = apply_command(
        state,
        CreatePendingPlan(
            command_id="create",
            timestamp=NOW,
            expected_state_version=state.state_version,
            plan=_plan(),
        ),
    )
    state, events = apply_command(
        state,
        CancelPendingPlan(
            command_id="cancel",
            timestamp=NOW,
            expected_state_version=state.state_version,
            plan_id="btc-plan",
            reason="signal_expired",
        ),
    )
    assert state.pending_plans == []
    assert events[0].data["reason"] == "signal_expired"


def test_store_recovers_wal_without_duplicate_events(tmp_path):
    store = AccountStateStore(tmp_path / "account-state.json")
    current = store.initialize(timestamp=NOW, initial_cash=600)
    command = UpdateExternalEquity(
        command_id="recover-me",
        timestamp=NOW,
        expected_state_version=current.state_version,
        current_equity=580,
    )
    updated, events = apply_command(current, command)
    store._write_atomic(
        store.wal_path,
        {
            "state": updated.model_dump(mode="json"),
            "events": [event.model_dump(mode="json") for event in events],
        },
    )
    recovered = store.load()
    recovered_again = store.load()
    history = store.history(limit=20)
    assert recovered == updated == recovered_again
    assert len([event for event in history if event["command_id"] == "recover-me"]) == 1
    assert not store.wal_path.exists()
    assert store.verify_consistency() is True


def test_store_fails_closed_on_corrupt_state_or_wal(tmp_path):
    state_path = tmp_path / "account-state.json"
    state_path.write_text("{broken", encoding="utf-8")
    with pytest.raises(RiskStateError, match="corrupt"):
        AccountStateStore(state_path).load()

    store = AccountStateStore(tmp_path / "second-state.json")
    store.initialize(timestamp=NOW, initial_cash=600)
    store.wal_path.write_text("{broken", encoding="utf-8")
    with pytest.raises(RiskStateError, match="WAL is corrupt"):
        store.load()


def test_v2_risk_state_migration_preserves_values_and_backup(tmp_path):
    path = tmp_path / "risk.json"
    RiskStateStore(path).initialize(current_date=NOW.date(), equity_cny=720)
    migrated = AccountStateStore(path, cny_per_usdt=7.2).load()
    assert migrated.schema_version == 3
    assert migrated.risk.current_equity == 100
    assert migrated.portfolio.cash == 100
    assert list(tmp_path.glob("risk.json.v2.*.bak"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 3


def test_production_cli_does_not_write_legacy_risk_state_directly():
    source = inspect.getsource(cli_module)
    assert "RiskStateStore" not in source
    assert "AccountStateStore" in source
