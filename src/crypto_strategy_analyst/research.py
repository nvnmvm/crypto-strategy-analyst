"""Finite, preregistered research diagnostics over strict backtests."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

import numpy as np

from .backtest import run_backtest
from .config import AppConfig
from .models import BacktestResult, MarketSnapshot


def diagnose(result: BacktestResult) -> dict[str, Any]:
    funnel = result.candidate_funnel
    evaluations = max(1, funnel.get("evaluations", 0))
    return {
        "candidate_funnel": funnel,
        "blockers": result.blockers,
        "strategy_failed_conditions": result.blockers,
        "entry_cancellations": result.cancellations,
        "data_missing_reasons": {
            key: value for key, value in result.blockers.items() if "missing" in key
        },
        "conversion_rates": {
            "candidate_per_evaluation": funnel.get("candidates", 0) / evaluations,
            "validated_per_candidate": funnel.get("validated", 0)
            / max(1, funnel.get("candidates", 0)),
        },
    }


def _group_metrics(trades) -> dict[str, float | int]:
    pnls = [trade.pnl for trade in trades]
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    equity = np.cumsum(pnls)
    peaks = np.maximum.accumulate(np.insert(equity, 0, 0))[1:] if len(equity) else np.array([])
    maximum_drawdown = float(np.max(peaks - equity)) if len(equity) else 0
    return {
        "trades": len(trades),
        "win_rate": len(wins) / len(trades) if trades else 0,
        "average_win_r": float(
            np.mean([trade.r_multiple for trade in trades if trade.r_multiple > 0])
        )
        if wins
        else 0,
        "average_loss_r": float(
            np.mean([trade.r_multiple for trade in trades if trade.r_multiple < 0])
        )
        if losses
        else 0,
        "expectancy_r": float(np.mean([trade.r_multiple for trade in trades])) if trades else 0,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else (float("inf") if wins else 0),
        "maximum_drawdown_amount": maximum_drawdown,
        "fees": sum(trade.fees for trade in trades),
        "average_holding_hours": float(np.mean([trade.holding_hours for trade in trades]))
        if trades
        else 0,
        "mfe": float(np.mean([trade.mfe for trade in trades])) if trades else 0,
        "mae": float(np.mean([trade.mae for trade in trades])) if trades else 0,
    }


def attribution(result: BacktestResult) -> dict[str, Any]:
    dimensions: dict[str, dict[str, list]] = {
        name: defaultdict(list)
        for name in (
            "symbol",
            "profile",
            "strategy",
            "horizon",
            "market_regime",
            "year",
            "confidence_bucket",
        )
    }
    for trade in result.trades:
        values = {
            "symbol": trade.symbol,
            "profile": trade.profile,
            "strategy": trade.strategy,
            "horizon": trade.horizon.value,
            "market_regime": trade.regime.value,
            "year": str(trade.entry_time.year),
            "confidence_bucket": f"{int(trade.confidence // 10) * 10}-{int(trade.confidence // 10) * 10 + 9}",
        }
        for dimension, value in values.items():
            dimensions[dimension][value].append(trade)
    return {
        dimension: {key: _group_metrics(items) for key, items in groups.items()}
        for dimension, groups in dimensions.items()
    }


def ablation(snapshot: MarketSnapshot, config: AppConfig, profile: str = "auto") -> dict[str, Any]:
    baseline = run_backtest(snapshot, config, profile)
    cases = {
        "volume_confirmation": {"strategy": {"volume_ratio": 0.5}},
        "relative_strength": {},
        "funding_filter": {},
        "trend_filter": {"strategy": {"minimum_confidence": 0}},
        "profile_filters": {},
    }
    output = {"baseline": baseline.metrics, "ablations": {}}
    for name, updates in cases.items():
        changed = config.model_copy(deep=True)
        if updates.get("strategy"):
            changed.strategy = changed.strategy.model_copy(update=updates["strategy"])
        modified_snapshot = snapshot
        if name == "relative_strength":
            modified_snapshot = snapshot.model_copy(
                update={
                    "auxiliary": {
                        key: value
                        for key, value in snapshot.auxiliary.items()
                        if key not in {"eth_btc", "bnb_btc", "sol_btc", "sol_eth"}
                    }
                }
            )
        if name == "funding_filter":
            modified_snapshot = snapshot.model_copy(
                update={
                    "auxiliary": {
                        key: value for key, value in snapshot.auxiliary.items() if key != "funding"
                    }
                }
            )
        if name == "profile_filters":
            output["ablations"][name] = run_backtest(snapshot, changed, "generic").metrics
        else:
            output["ablations"][name] = run_backtest(modified_snapshot, changed, profile).metrics
    for strategy in (
        "support_rebound",
        "breakout_retest",
        "trend_pullback",
        "range_reversal",
        "bear_reversal",
        "bear_accumulation",
    ):
        changed = config.model_copy(deep=True)
        changed.strategy = changed.strategy.model_copy(update={strategy: False})
        output["ablations"][f"strategy:{strategy}"] = run_backtest(
            snapshot, changed, profile
        ).metrics
    return output


def walk_forward(result: BacktestResult, window_days: int) -> dict[str, Any]:
    return {
        "method": "frozen_parameter_rolling_windows",
        "window_days": window_days,
        "parameter_refit": False,
        "windows": result.rolling_windows,
        "lookahead_used": False,
    }


def cost_sensitivity(
    snapshot: MarketSnapshot, config: AppConfig, profile: str = "auto"
) -> dict[str, Any]:
    scenarios = {
        "base": (1, 1),
        "double_fee": (2, 1),
        "double_slippage": (1, 2),
        "double_both": (2, 2),
        "extreme_slippage": (1, 5),
    }
    output = {}
    for name, (fee_factor, slip_factor) in scenarios.items():
        changed = config.model_copy(deep=True)
        changed.research = changed.research.model_copy(
            update={
                "fee_rate": config.research.fee_rate * fee_factor,
                "slippage_rate": config.research.slippage_rate * slip_factor,
            }
        )
        output[name] = run_backtest(snapshot, changed, profile).metrics
    return output


def parameter_stability(
    snapshot: MarketSnapshot, config: AppConfig, profile: str = "auto"
) -> dict[str, Any]:
    cases = []
    for merge_factor in (0.9, 1.0, 1.1):
        for confidence_delta in (-3, 0, 3):
            changed = config.model_copy(deep=True)
            changed.levels = changed.levels.model_copy(
                update={"merge_atr": config.levels.merge_atr * merge_factor}
            )
            changed.strategy = changed.strategy.model_copy(
                update={
                    "candidate_confidence": config.strategy.candidate_confidence + confidence_delta
                }
            )
            result = run_backtest(snapshot, changed, profile)
            cases.append(
                {
                    "merge_factor": merge_factor,
                    "confidence_delta": confidence_delta,
                    "metrics": result.metrics,
                }
            )
    return {"method": "declared_parameter_neighborhood", "cases": cases}


def compare(snapshot: MarketSnapshot, config: AppConfig, profile: str = "auto") -> dict[str, Any]:
    configurations = {
        "baseline": {},
        "conservative": {"candidate_confidence": config.strategy.candidate_confidence + 5},
        "trend_only": {
            "support_rebound": False,
            "breakout_retest": False,
            "range_reversal": False,
            "bear_reversal": False,
        },
    }
    return {
        name: run_backtest(
            snapshot,
            config.model_copy(
                update={"strategy": config.strategy.model_copy(update=updates)}, deep=True
            ),
            profile,
        ).metrics
        for name, updates in configurations.items()
    }


def blocker_totals(result: BacktestResult) -> Counter:
    return Counter(result.blockers)
