from copy import deepcopy
from datetime import timedelta

import pytest

from crypto_strategy_analyst.config import AppConfig
from crypto_strategy_analyst.engine import analyze_snapshot
from crypto_strategy_analyst.models import Horizon, PriceRange, SignalStatus, TakeProfit
from crypto_strategy_analyst.validation import validate_entry


def candidate_report(
    snapshot_factory, *, lower=150, upper=180, stop=140, target=220, expired=False
):
    snapshot = snapshot_factory()
    report = analyze_snapshot(snapshot, AppConfig())
    plan = report.horizons[Horizon.SWING].model_copy(
        update={
            "status": SignalStatus.CANDIDATE,
            "strategy": "support_rebound",
            "entry_range": PriceRange(lower=lower, upper=upper),
            "planned_entry": (lower + upper) / 2,
            "stop_loss": stop,
            "take_profits": [TakeProfit(price=target, fraction=1, source="test")],
            "minimum_reward_risk": 1.8,
            "valid_from": snapshot.as_of,
            "valid_until": snapshot.as_of - timedelta(hours=1)
            if expired
            else snapshot.as_of + timedelta(days=3),
        }
    )
    return snapshot, report.model_copy(
        update={"horizons": {**report.horizons, Horizon.SWING: plan}}
    )


def with_next_bar(snapshot, open_price):
    previous = snapshot.candles["1d"][-1]
    next_bar = previous.model_copy(
        update={
            "open_time": snapshot.as_of,
            "close_time": snapshot.as_of + timedelta(days=1),
            "open": open_price,
            "high": max(open_price, 230),
            "low": min(open_price, 130),
            "close": open_price,
        }
    )
    return snapshot.model_copy(
        update={
            "as_of": next_bar.open_time,
            "candles": {**snapshot.candles, "1d": [*snapshot.candles["1d"], next_bar]},
        }
    )


def test_validate_uses_actual_next_open_and_preserves_plan(snapshot_factory):
    snapshot, report = candidate_report(snapshot_factory)
    original = deepcopy(report.model_dump())
    result = validate_entry(report, with_next_bar(snapshot, 170), Horizon.SWING)
    assert result.actual_open_price == 170
    assert result.stop_loss == 140
    assert result.take_profits[0].price == 220
    assert report.model_dump() == original


@pytest.mark.parametrize(
    ("open_price", "reason"),
    [(190, "open_above_entry_range"), (130, "open_below_stop"), (225, "open_above_target")],
)
def test_validate_cancels_invalid_open(snapshot_factory, open_price, reason):
    snapshot, report = candidate_report(snapshot_factory)
    result = validate_entry(report, with_next_bar(snapshot, open_price), Horizon.SWING)
    assert result.status == SignalStatus.ENTRY_CANCELLED
    assert reason in result.reasons


def test_validate_cancels_low_reward_risk(snapshot_factory):
    snapshot, report = candidate_report(
        snapshot_factory, lower=170, upper=195, stop=160, target=200
    )
    result = validate_entry(report, with_next_bar(snapshot, 190), Horizon.SWING)
    assert "reward_risk_below_minimum" in result.reasons


def test_validate_expired_and_missing_next_bar(snapshot_factory):
    snapshot, report = candidate_report(snapshot_factory, expired=True)
    expired = validate_entry(report, with_next_bar(snapshot, 170), Horizon.SWING)
    assert "plan_expired" in expired.reasons
    missing = validate_entry(report, snapshot, Horizon.SWING)
    assert "next_bar_not_available" in missing.reasons
