from crypto_strategy_analyst.backtest import replay_signal, snapshot_at
from crypto_strategy_analyst.config import AppConfig
from crypto_strategy_analyst.engine import analyze_snapshot, evaluate_setup_at_time
from crypto_strategy_analyst.models import Availability, DataPoint, Horizon, SignalStatus


def test_schema_and_three_independent_horizons(snapshot_factory):
    report = analyze_snapshot(snapshot_factory(), AppConfig())
    assert report.schema_version == "2.0"
    assert set(report.plans) == set(Horizon)
    assert report.profile == "btc"
    assert len(report.events) == 3


def test_live_and_replay_are_identical(snapshot_factory):
    snapshot = snapshot_factory()
    direct = evaluate_setup_at_time(snapshot_at(snapshot, snapshot.as_of), AppConfig())
    replay = replay_signal(snapshot, snapshot.as_of, AppConfig())
    assert direct.model_dump() == replay.model_dump()


def test_future_bar_cannot_change_historical_signal(snapshot_factory):
    baseline = snapshot_factory()
    future = snapshot_factory(future_spike=True)
    a = replay_signal(baseline, baseline.as_of, AppConfig())
    b = replay_signal(future, future.as_of, AppConfig())
    assert a.scores == b.scores
    assert a.plans == b.plans


def test_required_data_failure_forces_no_trade(snapshot_factory):
    snapshot = snapshot_factory()
    snapshot.trading_rules = DataPoint(status=Availability.FAILED, source="test")
    report = analyze_snapshot(snapshot, AppConfig())
    assert all(plan.status == SignalStatus.NO_TRADE for plan in report.plans.values())
    assert report.warnings


def test_generic_confidence_cap(snapshot_factory):
    report = analyze_snapshot(snapshot_factory("DOGEUSDT"), AppConfig())
    assert report.profile == "generic"
    assert report.confidence <= 72


def test_bnb_and_sol_hard_filters(snapshot_factory):
    for symbol, field in (("BNBUSDT", "binance_platform_risk"), ("SOLUSDT", "network_health")):
        snapshot = snapshot_factory(symbol)
        snapshot.auxiliary[field] = DataPoint(
            status=Availability.AVAILABLE, source="test", value={"severity": "severe"}
        )
        report = analyze_snapshot(snapshot, AppConfig())
        assert report.hard_filters
        assert report.plans[Horizon.SWING].status == SignalStatus.NO_TRADE


def test_adjacent_level_touches_are_cooled_down(snapshot_factory):
    report = analyze_snapshot(snapshot_factory(slope=0), AppConfig())
    assert all(level.touches <= 14 for level in report.key_levels)


def test_missing_auxiliary_lowers_confidence(snapshot_factory):
    snapshot = snapshot_factory()
    base = analyze_snapshot(snapshot, AppConfig()).confidence
    for name in ("funding", "open_interest", "liquidations", "etf_flow", "macro", "btc_dominance"):
        snapshot.auxiliary[name] = DataPoint(
            status=Availability.AVAILABLE, source="test", value={"score": 100}
        )
    assert analyze_snapshot(snapshot, AppConfig()).confidence > base


def test_future_auxiliary_data_is_not_used(snapshot_factory):
    snapshot = snapshot_factory()
    baseline = analyze_snapshot(snapshot, AppConfig()).confidence
    snapshot.auxiliary["funding"] = DataPoint(
        status=Availability.AVAILABLE,
        source="future",
        observed_at=snapshot.as_of.replace(year=snapshot.as_of.year + 1),
        value={"score": 100},
    )
    assert analyze_snapshot(snapshot, AppConfig()).confidence == baseline
