from datetime import timedelta
from types import SimpleNamespace

from crypto_strategy_analyst import backtest as backtest_module
from crypto_strategy_analyst.backtest import _simulate_trade, run_backtest, snapshot_at
from crypto_strategy_analyst.config import AppConfig
from crypto_strategy_analyst.engine import analyze_snapshot
from crypto_strategy_analyst.models import (
    BacktestTrade,
    Horizon,
    MarketRegime,
    PriceRange,
    RiskSuggestion,
    SignalStatus,
    TakeProfit,
)
from crypto_strategy_analyst.research import (
    ablation,
    attribution,
    compare,
    cost_sensitivity,
    diagnose,
    parameter_stability,
    walk_forward,
)


def candidate_plan(snapshot_factory, horizon=Horizon.SWING):
    snapshot = snapshot_factory()
    plan = analyze_snapshot(snapshot, AppConfig()).horizons[horizon]
    return plan.model_copy(
        update={
            "status": SignalStatus.CANDIDATE,
            "strategy": "support_rebound",
            "market_regime": MarketRegime.BULLISH,
            "entry_range": PriceRange(lower=plan.risk_suggestion.risk_fraction + 150, upper=180),
            "planned_entry": 165,
            "stop_loss": 140,
            "take_profits": [
                TakeProfit(price=200, fraction=0.5, source="tp1"),
                TakeProfit(price=220, fraction=0.5, source="tp2"),
            ],
            "minimum_reward_risk": 1.5,
            "valid_from": snapshot.as_of,
            "valid_until": snapshot.as_of + timedelta(days=3),
            "risk_suggestion": RiskSuggestion(level="normal", risk_fraction=0.01),
        }
    )


def test_snapshot_at_excludes_future(snapshot_factory):
    snapshot = snapshot_factory(future_spike=True)
    view = snapshot_at(snapshot, snapshot.as_of)
    assert all(bar.close_time <= snapshot.as_of for bars in view.candles.values() for bar in bars)
    assert view.price < 10_000


def test_snapshot_at_applies_live_history_limit_without_future_bars(snapshot_factory):
    snapshot = snapshot_factory(count=30)
    view = snapshot_at(snapshot, snapshot.as_of, history_limit=12)
    assert {len(bars) for bars in view.candles.values()} == {12}
    assert all(bar.close_time <= snapshot.as_of for bars in view.candles.values() for bar in bars)


def test_same_bar_stop_and_target_uses_stop_first(snapshot_factory):
    snapshot = snapshot_factory(count=10)
    plan = candidate_plan(snapshot_factory)
    bar = snapshot.candles["1d"][-1].model_copy(
        update={"open": 170, "high": 230, "low": 130, "close": 180}
    )
    trade = _simulate_trade([bar], 0, plan, snapshot.symbol, 600, AppConfig())
    assert trade.exit_reason == "stop_first_same_bar"
    assert trade.pnl < 0


def test_fees_and_slippage_are_adverse(snapshot_factory):
    snapshot = snapshot_factory(count=10)
    plan = candidate_plan(snapshot_factory)
    bar = snapshot.candles["1d"][-1].model_copy(
        update={"open": 170, "high": 230, "low": 160, "close": 220}
    )
    base = AppConfig().model_copy(
        update={
            "research": AppConfig().research.model_copy(update={"fee_rate": 0, "slippage_rate": 0})
        }
    )
    costly = AppConfig().model_copy(
        update={
            "research": AppConfig().research.model_copy(
                update={"fee_rate": 0.002, "slippage_rate": 0.002}
            )
        }
    )
    assert (
        _simulate_trade([bar], 0, plan, snapshot.symbol, 600, costly).pnl
        < _simulate_trade([bar], 0, plan, snapshot.symbol, 600, base).pnl
    )


def test_backtest_calls_shared_replay_engine(snapshot_factory, monkeypatch):
    snapshot = snapshot_factory(count=30)
    calls = 0
    original = backtest_module.replay_signal

    def spy(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(backtest_module, "replay_signal", spy)
    result = run_backtest(snapshot, AppConfig(), horizons=[Horizon.SHORT])
    assert calls == len(snapshot.candles["4h"]) - 2
    assert result.assumptions["execution"] == "next_primary_bar_open"
    assert result.assumptions["intrabar_order"] == "stop_first"


def test_backtest_sizes_multi_horizon_candidates_in_chronological_order(
    snapshot_factory, monkeypatch
):
    """Horizon loop order must not let a later result change earlier capital."""

    snapshot = snapshot_factory(count=4)
    base_plan = candidate_plan(snapshot_factory)

    def fake_replay(_snapshot, _at, _config, _profile, _close_time_index):
        return SimpleNamespace(
            profile="test",
            horizons={
                Horizon.SHORT: base_plan.model_copy(update={"horizon": Horizon.SHORT}),
                Horizon.LONG: base_plan.model_copy(update={"horizon": Horizon.LONG}),
            },
        )

    monkeypatch.setattr(backtest_module, "replay_signal", fake_replay)
    monkeypatch.setattr(
        backtest_module,
        "validate_entry",
        lambda *_args, **_kwargs: SimpleNamespace(status=SignalStatus.ENTRY_VALIDATED),
    )
    seen: list[tuple] = []

    def immediate_exit(bars, start_index, plan, symbol, equity, _config, profile):
        bar = bars[start_index]
        seen.append((bar.open_time, equity))
        return BacktestTrade(
            symbol=symbol,
            profile=profile,
            horizon=plan.horizon,
            strategy=plan.strategy,
            regime=plan.market_regime,
            planned_at=plan.valid_from,
            entry_time=bar.open_time,
            exit_time=bar.open_time,
            entry_price=bar.open,
            exit_price=bar.open,
            quantity=1,
            pnl=10,
            return_fraction=10 / equity,
            r_multiple=1,
            confidence=plan.confidence,
            fees=0,
            holding_hours=0,
            mfe=0,
            mae=0,
            exit_reason="test",
        )

    monkeypatch.setattr(backtest_module, "_simulate_trade", immediate_exit)
    run_backtest(snapshot, AppConfig(), horizons=[Horizon.SHORT, Horizon.LONG])
    assert [entry for entry, _equity in seen] == sorted(entry for entry, _equity in seen)
    assert [equity for _entry, equity in seen] == [600 + 10 * index for index in range(len(seen))]


def test_time_splits_are_named_dates(snapshot_factory):
    result = run_backtest(snapshot_factory(count=30), AppConfig(), horizons=[Horizon.SHORT])
    assert set(result.time_splits) == {
        "train",
        "validation",
        "historical_replay",
        "post_freeze_forward",
    }
    assert "walk_forward" not in result.time_splits


def test_research_functions_return_real_structures(snapshot_factory):
    snapshot = snapshot_factory(count=30)
    config = AppConfig().model_copy(
        update={
            "research": AppConfig().research.model_copy(
                update={"minimum_trades": 1, "rolling_days": 30}
            )
        }
    )
    result = run_backtest(snapshot, config, horizons=[Horizon.SHORT])
    assert "candidate_funnel" in diagnose(result)
    assert "strategy" in attribution(result)
    assert walk_forward(result, 30)["lookahead_used"] is False
    assert "base" in cost_sensitivity(snapshot, config)
    assert len(parameter_stability(snapshot, config)["cases"]) == 9
    assert set(compare(snapshot, config)) == {"baseline", "conservative", "trend_only"}
    assert "ablations" in ablation(snapshot, config)


def test_attribution_trade_totals_match(snapshot_factory):
    result = run_backtest(snapshot_factory(count=30), AppConfig(), horizons=[Horizon.SHORT])
    grouped = attribution(result)["strategy"]
    assert sum(value["trades"] for value in grouped.values()) == len(result.trades)


def test_cost_increase_cannot_improve_identical_trade(monkeypatch, snapshot_factory):
    snapshot = snapshot_factory(count=30)
    outputs = cost_sensitivity(snapshot, AppConfig())
    assert outputs["double_both"]["total_return"] <= outputs["base"]["total_return"] + 1e-12
