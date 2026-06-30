from __future__ import annotations

import json
import multiprocessing
import time
from datetime import date

import pytest

from crypto_strategy_analyst.config import RiskConfig
from crypto_strategy_analyst.errors import RiskStateError
from crypto_strategy_analyst.risk import RiskState, RiskStateStore, risk_blockers

TEST_DATE = date(2026, 6, 30)


def _record_concurrent_loss(path: str, trade_id: str) -> None:
    RiskStateStore(path, lock_timeout_seconds=10).record_trade(
        current_date=TEST_DATE,
        initial_equity_cny=1000,
        trade_id=trade_id,
        pnl_cny=-1,
        stopped_out=True,
    )


def _record_same_trade(path: str, queue) -> None:
    try:
        _record_concurrent_loss(path, "same-trade")
        queue.put("accepted")
    except RiskStateError:
        queue.put("duplicate")


def _hold_file_lock(lock_path: str, ready) -> None:
    import fcntl

    with open(lock_path, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        ready.set()
        time.sleep(1)


def test_missing_state_starts_safely(tmp_path):
    store = RiskStateStore(tmp_path / "risk.json")
    state = store.load(current_date=TEST_DATE, initial_equity_cny=1000)
    assert state.date == TEST_DATE
    assert state.current_equity_cny == 1000
    assert state.daily_start_equity_cny == 1000
    assert state.peak_equity_cny == 1000
    assert not store.path.exists()


def test_load_or_initialize_persists_missing_state(tmp_path):
    store = RiskStateStore(tmp_path / "risk.json")
    state, created = store.load_or_initialize(current_date=TEST_DATE, initial_equity_cny=1000)
    assert created is True
    assert state.current_equity_cny == 1000
    assert store.path.exists()


def test_initialize_refuses_overwrite_without_force(tmp_path):
    store = RiskStateStore(tmp_path / "risk.json")
    initialized = store.initialize(current_date=TEST_DATE, equity_cny=1000)
    assert initialized.current_equity_cny == 1000
    assert store.path.exists()
    with pytest.raises(RiskStateError, match="already exists"):
        store.initialize(current_date=TEST_DATE, equity_cny=900)
    overwritten = store.initialize(current_date=TEST_DATE, equity_cny=900, force=True)
    assert overwritten.current_equity_cny == 900


def test_corrupt_state_fails_closed(tmp_path):
    path = tmp_path / "risk.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(RiskStateError, match="corrupt"):
        RiskStateStore(path).load(current_date=TEST_DATE, initial_equity_cny=1000)


def test_update_equity_changes_peak_and_drawdown_only(tmp_path):
    store = RiskStateStore(tmp_path / "risk.json")
    store.initialize(current_date=TEST_DATE, equity_cny=1000)
    lower = store.update_equity(
        current_date=TEST_DATE,
        initial_equity_cny=1000,
        equity_cny=950,
    )
    assert lower.current_equity_cny == 950
    assert lower.peak_equity_cny == 1000
    assert lower.current_drawdown == pytest.approx(0.05)
    assert lower.daily_stop_losses == 0
    assert lower.daily_realized_loss_cny == 0
    higher = store.update_equity(
        current_date=TEST_DATE,
        initial_equity_cny=1000,
        equity_cny=1100,
    )
    assert higher.peak_equity_cny == 1100
    assert higher.current_drawdown == 0


def test_trade_results_update_equity_losses_and_stop_count(tmp_path):
    store = RiskStateStore(tmp_path / "risk.json")
    store.initialize(current_date=TEST_DATE, equity_cny=1000)
    profit = store.record_trade(
        current_date=TEST_DATE,
        initial_equity_cny=1000,
        trade_id="profit-1",
        pnl_cny=20,
        stopped_out=True,
    )
    assert profit.current_equity_cny == 1020
    assert profit.daily_stop_losses == 0
    ordinary_loss = store.record_trade(
        current_date=TEST_DATE,
        initial_equity_cny=1000,
        trade_id="ordinary-loss-1",
        pnl_cny=-5,
        stopped_out=False,
    )
    assert ordinary_loss.current_equity_cny == 1015
    assert ordinary_loss.daily_realized_loss_cny == 5
    assert ordinary_loss.daily_stop_losses == 0
    stopped = store.record_trade(
        current_date=TEST_DATE,
        initial_equity_cny=1000,
        trade_id="stopped-loss-1",
        pnl_cny=-10,
        stopped_out=True,
    )
    assert stopped.current_equity_cny == 1005
    assert stopped.daily_realized_loss_cny == 15
    assert stopped.daily_stop_losses == 1


def test_date_rollover_preserves_current_peak_and_drawdown(tmp_path):
    store = RiskStateStore(tmp_path / "risk.json")
    state = RiskState(
        date=date(2026, 6, 29),
        daily_stop_losses=2,
        daily_realized_loss_cny=20,
        daily_start_equity_cny=1000,
        current_equity_cny=900,
        peak_equity_cny=1200,
        current_drawdown=0.25,
    )
    store.save(state)
    loaded = store.load_existing(current_date=TEST_DATE, initial_equity_cny=1000)
    assert loaded.daily_stop_losses == 0
    assert loaded.daily_realized_loss_cny == 0
    assert loaded.daily_start_equity_cny == 900
    assert loaded.current_equity_cny == 900
    assert loaded.peak_equity_cny == 1200
    assert loaded.current_drawdown == 0.25


def test_manual_daily_reset_preserves_equity_history(tmp_path):
    store = RiskStateStore(tmp_path / "risk.json")
    store.initialize(current_date=TEST_DATE, equity_cny=1000)
    store.record_trade(
        current_date=TEST_DATE,
        initial_equity_cny=1000,
        trade_id="manual-reset-loss-1",
        pnl_cny=-10,
        stopped_out=True,
    )
    reset = store.reset_daily(current_date=TEST_DATE, initial_equity_cny=1000)
    assert reset.daily_stop_losses == 0
    assert reset.daily_realized_loss_cny == 0
    assert reset.current_equity_cny == 990
    assert reset.peak_equity_cny == 1000
    assert reset.current_drawdown == pytest.approx(0.01)


def test_atomic_save_replaces_valid_complete_json(tmp_path):
    path = tmp_path / "risk.json"
    store = RiskStateStore(path)
    state = store.initialize(current_date=TEST_DATE, equity_cny=1000)
    store.save(state.with_realized_result(-10, stopped_out=True))
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["daily_stop_losses"] == 1
    assert payload["current_equity_cny"] == 990
    assert not list(tmp_path.glob(".*.tmp"))


def test_concurrent_trade_updates_do_not_get_lost(tmp_path):
    path = tmp_path / "risk.json"
    RiskStateStore(path).initialize(current_date=TEST_DATE, equity_cny=1000)
    context = multiprocessing.get_context("spawn")
    processes = [
        context.Process(target=_record_concurrent_loss, args=(str(path), f"concurrent-{index}"))
        for index in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0
    state = RiskStateStore(path).load_existing(current_date=TEST_DATE, initial_equity_cny=1000)
    assert state.current_equity_cny == 998
    assert state.daily_realized_loss_cny == 2
    assert state.daily_stop_losses == 2


def test_duplicate_trade_id_is_rejected_without_changing_state(tmp_path):
    store = RiskStateStore(tmp_path / "risk.json")
    store.initialize(current_date=TEST_DATE, equity_cny=1000)
    first = store.record_trade(
        current_date=TEST_DATE,
        initial_equity_cny=1000,
        trade_id="manual-btc-1",
        pnl_cny=-10,
        stopped_out=True,
    )
    with pytest.raises(RiskStateError, match="already processed"):
        store.record_trade(
            current_date=TEST_DATE,
            initial_equity_cny=1000,
            trade_id="manual-btc-1",
            pnl_cny=-10,
            stopped_out=True,
        )
    after = store.load_existing(current_date=TEST_DATE, initial_equity_cny=1000)
    assert after == first
    assert after.current_equity_cny == 990
    assert after.daily_stop_losses == 1


def test_concurrent_duplicate_trade_id_allows_exactly_one(tmp_path):
    path = tmp_path / "risk.json"
    RiskStateStore(path).initialize(current_date=TEST_DATE, equity_cny=1000)
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    processes = [
        context.Process(target=_record_same_trade, args=(str(path), queue)) for _ in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0
    outcomes = sorted(queue.get(timeout=5) for _ in processes)
    assert outcomes == ["accepted", "duplicate"]
    state = RiskStateStore(path).load_existing(
        current_date=TEST_DATE, initial_equity_cny=1000
    )
    assert state.current_equity_cny == 999
    assert state.processed_trade_ids == ["same-trade"]


def test_old_state_migrates_with_backup_and_audit(tmp_path):
    path = tmp_path / "risk.json"
    path.write_text(
        json.dumps(
            {
                "date": TEST_DATE.isoformat(),
                "daily_stop_losses": 1,
                "daily_realized_loss_cny": 10,
                "daily_start_equity_cny": 1000,
                "current_equity_cny": 990,
                "peak_equity_cny": 1000,
                "current_drawdown": 0.01,
            }
        ),
        encoding="utf-8",
    )
    store = RiskStateStore(path)

    state = store.load_existing(current_date=TEST_DATE, initial_equity_cny=1000)

    assert state.state_version == 2
    assert state.current_equity_cny == 990
    assert state.daily_stop_losses == 1
    assert len(list(tmp_path.glob("risk.json.v1.*.bak"))) == 1
    assert store.history(limit=10)[-1]["operation"] == "migrate_state_v2"


def test_risk_audit_records_lifecycle_and_trade_fields(tmp_path):
    store = RiskStateStore(tmp_path / "risk.json")
    store.initialize(current_date=TEST_DATE, equity_cny=1000)
    store.record_trade(
        current_date=TEST_DATE,
        initial_equity_cny=1000,
        trade_id="audit-1",
        pnl_cny=-10,
        stopped_out=True,
    )

    event = store.history(limit=1)[0]
    assert event["operation"] == "record_trade"
    assert event["trade_id"] == "audit-1"
    assert event["before_equity_cny"] == 1000
    assert event["after_equity_cny"] == 990
    assert event["daily_stop_losses_after"] == 1
    assert event["pnl_cny"] == -10


def test_lock_timeout_fails_instead_of_writing_without_lock(tmp_path):
    store = RiskStateStore(tmp_path / "risk.json", lock_timeout_seconds=0.1)
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    holder = context.Process(target=_hold_file_lock, args=(str(store.lock_path), ready))
    holder.start()
    assert ready.wait(timeout=10)
    with pytest.raises(RiskStateError, match="timed out"):
        store.load(current_date=TEST_DATE, initial_equity_cny=1000)
    holder.join(timeout=10)
    assert holder.exitcode == 0


@pytest.mark.parametrize(
    ("state", "expected_lock"),
    [
        (
            RiskState(
                date=TEST_DATE,
                daily_stop_losses=2,
                daily_start_equity_cny=1000,
                current_equity_cny=1000,
                peak_equity_cny=1000,
            ),
            "daily_stop_count_reached",
        ),
        (
            RiskState(
                date=TEST_DATE,
                daily_realized_loss_cny=20,
                daily_start_equity_cny=1000,
                current_equity_cny=980,
                peak_equity_cny=1000,
                current_drawdown=0.02,
            ),
            "daily_loss_limit_reached",
        ),
        (
            RiskState(
                date=TEST_DATE,
                daily_start_equity_cny=1000,
                current_equity_cny=900,
                peak_equity_cny=1000,
                current_drawdown=0.10,
            ),
            "maximum_drawdown_protection_active",
        ),
    ],
)
def test_risk_lock_thresholds(state, expected_lock):
    assert expected_lock in risk_blockers(RiskConfig(), state)
