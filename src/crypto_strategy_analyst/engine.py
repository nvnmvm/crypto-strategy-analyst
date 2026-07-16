"""Single public analysis engine shared by live analysis and replay."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta

import numpy as np

from .config import AppConfig
from .events import make_event
from .indicators import indicator_map
from .levels import detect_levels
from .models import (
    AnalysisReport,
    Availability,
    DataPoint,
    Horizon,
    HorizonPlan,
    MarketRegime,
    MarketSnapshot,
    RiskSuggestion,
    ScoreCard,
    SignalStatus,
)
from .profiles.base import AssetProfile
from .profiles.registry import get_profile
from .regime import classify_regime
from .strategies import StrategyContext, evaluate_strategies
from .structure import ChartPattern, detect_chart_patterns
from .technical_analysis import analyze_indicators

HORIZON_FRAMES = {
    Horizon.SHORT: ("4h", "1h", "15m"),
    Horizon.SWING: ("1d", "4h", "1h"),
    Horizon.LONG: ("1w", "1d", "4h"),
}
VALIDITY_HOURS = {Horizon.SHORT: 8, Horizon.SWING: 48, Horizon.LONG: 336}
REGIME_CONFIDENCE = {
    MarketRegime.STRONG_BULL: 5,
    MarketRegime.BULLISH: 3,
    MarketRegime.BULL_PULLBACK: 1,
    MarketRegime.RANGE: -2,
    MarketRegime.BEARISH: -8,
    MarketRegime.CAPITULATION: -12,
    MarketRegime.RECOVERY: -1,
}


def _required_failures(snapshot: MarketSnapshot) -> list[str]:
    failures = []
    if not snapshot.trading_rules.usable_at(snapshot.as_of):
        failures.append("trading_rules")
    for timeframe in ("1w", "1d", "4h", "1h"):
        if not snapshot.completed(timeframe):
            failures.append(f"candles:{timeframe}")
    return failures


def _component_score(snapshot: MarketSnapshot, names: tuple[str, ...]) -> float | None:
    values: list[float] = []
    for name in names:
        point = snapshot.auxiliary.get(name)
        if not point or not point.usable_at(snapshot.as_of):
            continue
        value = point.value
        number = (
            value
            if isinstance(value, (int, float))
            else value.get("score")
            if isinstance(value, dict)
            else None
        )
        if isinstance(number, (int, float)):
            values.append(float(np.clip(50 + number if -20 <= number <= 20 else number, 0, 100)))
    return float(np.mean(values)) if values else None


def _score_card(
    snapshot: MarketSnapshot,
    indicators,
    profile: AssetProfile,
    profile_scores: dict[str, float | None],
    confidence_adjustment: float,
) -> ScoreCard:
    technical_values = [indicator.trend_strength for indicator in indicators.values()]
    technical = float(np.mean(technical_values)) if technical_values else 0
    components: dict[str, float | None] = {
        "technical": technical,
        "derivatives": _component_score(snapshot, ("funding", "open_interest", "liquidations")),
        "onchain": _component_score(snapshot, ("onchain", "chain_activity", "gas", "staking")),
        "macro": _component_score(snapshot, ("macro", "etf_flow", "eth_etf_flow", "btc_dominance")),
        "relative_strength": _component_score(
            snapshot, ("eth_btc", "bnb_btc", "sol_btc", "sol_eth")
        ),
        "asset_specific": _component_score(snapshot, profile.context_fields),
    }
    components = profile.adjust_scores(components, snapshot, Horizon.SWING)
    components.update({key: value for key, value in profile_scores.items() if key in components})
    required_total = 5
    required_available = required_total - len(_required_failures(snapshot))
    auxiliary_available = sum(
        bool(snapshot.auxiliary.get(name) and snapshot.auxiliary[name].usable_at(snapshot.as_of))
        for name in profile.context_fields
    )
    completeness = (
        100
        * (required_available + auxiliary_available)
        / max(1, required_total + len(profile.context_fields))
    )
    weights = {
        "technical": 0.55,
        "derivatives": 0.1,
        "onchain": 0.08,
        "macro": 0.09,
        "relative_strength": 0.12,
        "asset_specific": 0.06,
    }
    present_weight = sum(weights[name] for name, value in components.items() if value is not None)
    raw = sum(
        float(value) * weights[name] for name, value in components.items() if value is not None
    ) / max(present_weight, 1e-12)
    confidence = min(
        profile.confidence_cap, raw * (0.55 + 0.45 * completeness / 100) + confidence_adjustment
    )
    return ScoreCard(**components, data_completeness=completeness, confidence=max(0, confidence))


def _minimum_r(config: AppConfig, horizon: Horizon) -> float:
    return {
        Horizon.SHORT: config.horizons.short_minimum_r,
        Horizon.SWING: config.horizons.swing_minimum_r,
        Horizon.LONG: config.horizons.long_minimum_r,
    }[horizon]


def _base_risk(config: AppConfig, horizon: Horizon) -> float:
    return {
        Horizon.SHORT: config.horizons.short_risk,
        Horizon.SWING: config.horizons.swing_risk,
        Horizon.LONG: config.horizons.long_risk,
    }[horizon]


def _plan(
    horizon: Horizon,
    snapshot: MarketSnapshot,
    indicators,
    levels,
    profile: AssetProfile,
    score: ScoreCard,
    blocked: list[str],
    profile_adjustment: float,
    config: AppConfig,
    chart_patterns: list[ChartPattern],
) -> HorizonPlan:
    frames = HORIZON_FRAMES[horizon]
    primary = frames[0]
    bars = snapshot.completed(primary)
    indicator = indicators.get(primary)
    if not bars or indicator is None:
        return HorizonPlan(
            horizon=horizon,
            status=SignalStatus.NO_TRADE,
            market_regime=MarketRegime.RANGE,
            confidence=0,
            risk_suggestion=RiskSuggestion(level="none", risk_fraction=0),
            failed_conditions=[f"missing_primary_timeframe:{primary}"],
        )
    regime = classify_regime(bars, indicator)
    risk_multiplier, risk_reasons = profile.adjust_risk(snapshot, horizon)
    regime_risk = {
        MarketRegime.STRONG_BULL: 1.0,
        MarketRegime.BULLISH: 1.0,
        MarketRegime.BULL_PULLBACK: 0.85,
        MarketRegime.RANGE: 0.7,
        MarketRegime.BEARISH: 0.45,
        MarketRegime.CAPITULATION: 0.25,
        MarketRegime.RECOVERY: 0.6,
    }[regime]
    risk_multiplier *= regime_risk
    regime_minimum_r = _minimum_r(config, horizon) + (
        0.3 if regime in {MarketRegime.BEARISH, MarketRegime.CAPITULATION} else 0
    )
    confirmed_bearish = [
        pattern
        for pattern in chart_patterns
        if pattern.direction == "bearish" and pattern.state == "confirmed"
    ]
    forming_bearish = [
        pattern
        for pattern in chart_patterns
        if pattern.direction == "bearish" and pattern.state == "forming"
    ]
    pattern_blockers = [f"confirmed_bearish_pattern:{pattern.name}" for pattern in confirmed_bearish]
    pattern_observations = [
        f"forming_bearish_pattern:{pattern.name}" for pattern in forming_bearish
    ]
    active_blockers = blocked + pattern_blockers
    confidence = float(
        np.clip(
            score.confidence
            + REGIME_CONFIDENCE[regime]
            + profile_adjustment
            - 6 * len(forming_bearish),
            0,
            profile.confidence_cap,
        )
    )
    parameters = profile.adjust_parameters(horizon)
    local_strategy = config.strategy.model_copy(
        update={
            "stop_buffer_atr": config.strategy.stop_buffer_atr
            * parameters.get("stop_multiplier", 1),
            "volume_ratio": parameters.get("volume_requirement", config.strategy.volume_ratio),
            "breakout_atr": parameters.get("breakout_atr", config.strategy.breakout_atr),
            "entry_deviation_atr": min(
                config.strategy.entry_deviation_atr,
                parameters.get("chase_limit_atr", config.strategy.entry_deviation_atr),
            ),
        }
    )
    local_config = config.model_copy(update={"strategy": local_strategy})
    context = StrategyContext(
        horizon, bars, indicator, regime, levels, local_config, regime_minimum_r
    )
    results = evaluate_strategies(context)
    allowed = profile.filter_strategies(regime, horizon, [result.strategy for result in results])
    matches = [result for result in results if result.matched and result.strategy in allowed]
    matches.sort(
        key=lambda item: (
            len(item.structure_confirmations),
            item.reward_risk or 0,
            len(item.secondary_confirmations),
        ),
        reverse=True,
    )
    nearby = [
        level
        for level in levels
        if level.distance_percent <= config.levels.near_percent
        and level.distance_atr <= config.levels.near_atr
        and level.strength >= 45
    ]
    risk_fraction = _base_risk(config, horizon) * risk_multiplier
    if active_blockers:
        status = SignalStatus.NO_TRADE
    elif matches and confidence >= config.strategy.candidate_confidence:
        status = SignalStatus.CANDIDATE
    elif nearby:
        status = SignalStatus.NEAR_KEY_LEVEL
    elif confidence >= config.strategy.minimum_confidence:
        status = SignalStatus.WATCH
    else:
        status = SignalStatus.NO_TRADE
    selected = matches[0] if status == SignalStatus.CANDIDATE else None
    return HorizonPlan(
        horizon=horizon,
        status=status,
        market_regime=regime,
        strategy=selected.strategy if selected else None,
        key_levels=nearby[:4],
        entry_range=selected.entry_range if selected else None,
        planned_entry=(selected.entry_range.lower + selected.entry_range.upper) / 2
        if selected and selected.entry_range
        else None,
        stop_loss=selected.stop_loss if selected else None,
        take_profits=selected.take_profits if selected else [],
        reward_risk=selected.reward_risk if selected else None,
        minimum_reward_risk=regime_minimum_r,
        valid_from=snapshot.as_of if selected else None,
        valid_until=snapshot.as_of
        + timedelta(hours=VALIDITY_HOURS[horizon] * config.strategy.validity_bars)
        if selected
        else None,
        structure_confirmations=selected.structure_confirmations if selected else [],
        secondary_confirmations=selected.secondary_confirmations if selected else [],
        failed_conditions=active_blockers
        + (
            []
            if selected
            else sorted({condition for result in results for condition in result.failed_conditions})
        ),
        invalidation_conditions=selected.invalidation_conditions if selected else [],
        confidence=confidence,
        risk_suggestion=RiskSuggestion(
            level="none"
            if active_blockers
            else "reduced"
            if risk_multiplier < 0.75 or pattern_observations
            else "normal",
            risk_fraction=0 if active_blockers else risk_fraction,
            rationale=risk_reasons + active_blockers + pattern_observations,
        ),
        strategy_results=results,
    )


def _fresh_snapshot(snapshot: MarketSnapshot, config: AppConfig) -> MarketSnapshot:
    auxiliary = {
        name: (
            point.model_copy(
                update={
                    "status": Availability.STALE,
                    "detail": "freshness_threshold_exceeded",
                }
            )
            if point.status == Availability.AVAILABLE
            and point.freshness_seconds is not None
            and point.freshness_seconds > config.data.stale_after_seconds
            else point
        )
        for name, point in snapshot.auxiliary.items()
    }
    return snapshot.model_copy(update={"auxiliary": auxiliary})


def _availability(snapshot: MarketSnapshot, completed) -> dict[str, DataPoint]:
    availability = {"trading_rules": snapshot.trading_rules, **snapshot.auxiliary}
    for timeframe in ("1w", "1d", "4h", "1h", "15m"):
        bars = completed.get(timeframe, [])
        availability[f"candles:{timeframe}"] = DataPoint(
            status=Availability.AVAILABLE if bars else Availability.NOT_AVAILABLE,
            source="market_snapshot",
            observed_at=bars[-1].close_time if bars else None,
            freshness_seconds=max(0, (snapshot.as_of - bars[-1].close_time).total_seconds())
            if bars
            else None,
            value={"bars": len(bars)},
        )
    return availability


def _events(snapshot, profile, plans, score, required, hard_filters, chart_patterns):
    events = []
    for horizon, plan in plans.items():
        if plan.status == SignalStatus.NEAR_KEY_LEVEL and plan.key_levels:
            level = plan.key_levels[0]
            events.append(
                make_event(
                    "near_key_level",
                    snapshot.symbol,
                    profile.name,
                    horizon,
                    snapshot.as_of,
                    f"{level.type}:{level.midpoint:.8g}",
                    {
                        "level_type": level.type,
                        "level_range": {"lower": level.lower, "upper": level.upper},
                        "distance_percent": level.distance_percent,
                        "distance_atr": level.distance_atr,
                        "level_strength": level.strength,
                        "required_confirmation": ["higher_low", "reclaim_ema20"],
                    },
                )
            )
        if plan.status == SignalStatus.CANDIDATE:
            events.append(
                make_event(
                    "candidate_created",
                    snapshot.symbol,
                    profile.name,
                    horizon,
                    snapshot.as_of,
                    f"{plan.strategy}:{plan.entry_range}",
                    {
                        "strategy": plan.strategy,
                        "entry_range": plan.entry_range.model_dump() if plan.entry_range else None,
                    },
                )
            )
    if required:
        events.append(
            make_event(
                "data_failure",
                snapshot.symbol,
                profile.name,
                None,
                snapshot.as_of,
                ",".join(required),
                {"missing": required},
                "critical",
            )
        )
    if hard_filters:
        events.append(
            make_event(
                "risk_alert",
                snapshot.symbol,
                profile.name,
                None,
                snapshot.as_of,
                ",".join(hard_filters),
                {"hard_filters": hard_filters},
                "critical",
            )
        )
    for timeframe, patterns in chart_patterns.items():
        for pattern in patterns:
            if pattern.direction == "bearish" and pattern.state == "confirmed":
                events.append(
                    make_event(
                        "risk_alert",
                        snapshot.symbol,
                        profile.name,
                        None,
                        snapshot.as_of,
                        f"confirmed_bearish_pattern:{timeframe}:{pattern.name}",
                        {
                            "timeframe": timeframe,
                            "pattern": pattern.as_dict(),
                            "action": "suppress_long_candidate",
                        },
                        "warning",
                    )
                )
    if profile.name == "generic":
        events.append(
            make_event(
                "profile_warning",
                snapshot.symbol,
                profile.name,
                None,
                snapshot.as_of,
                "generic_profile",
                {"profile_confidence": "limited"},
                "warning",
            )
        )
    events.append(
        make_event(
            "analysis_completed",
            snapshot.symbol,
            profile.name,
            None,
            snapshot.as_of,
            ";".join(f"{h.value}:{plans[h].status.value}" for h in Horizon),
            {"confidence": score.confidence},
        )
    )
    return events


def _report_id(snapshot: MarketSnapshot, completed) -> str:
    fingerprint = json.dumps(
        {
            frame: [bar.close_time.isoformat(), bar.close]
            for frame, bars in completed.items()
            for bar in bars[-1:]
        },
        sort_keys=True,
    )
    return hashlib.sha256(
        f"{snapshot.symbol}|{snapshot.as_of.isoformat()}|{fingerprint}".encode()
    ).hexdigest()[:24]


def _assemble_report(
    snapshot,
    profile,
    indicators,
    levels,
    plans,
    score,
    availability,
    events,
    warnings,
    required,
    hard_filters,
    report_id,
    chart_patterns,
    technical_analysis,
) -> AnalysisReport:
    primary_regime = plans[Horizon.SWING].market_regime
    return AnalysisReport(
        report_id=report_id,
        symbol=snapshot.symbol,
        profile=profile.name,
        profile_confidence="limited" if profile.name == "generic" else "dedicated",
        generated_at=snapshot.as_of,
        evaluation_time=snapshot.as_of,
        market={
            "regime": primary_regime.value,
            "volatility": indicators.get("1d").atr_percent
            if indicators.get("1d")
            else "not_available",
            "liquidity": snapshot.auxiliary.get(
                "liquidity", DataPoint(status=Availability.NOT_AVAILABLE, source="not_available")
            ).model_dump(mode="json"),
            "chart_patterns": {
                timeframe: [pattern.as_dict() for pattern in patterns]
                for timeframe, patterns in chart_patterns.items()
            },
            "technical_analysis": technical_analysis,
        },
        data_availability=availability,
        scores=score,
        confidence=score.confidence,
        key_levels={
            "supports": [level for level in levels if level.type == "support"],
            "resistances": [level for level in levels if level.type == "resistance"],
        },
        relative_strength={
            name: point.model_dump(mode="json")
            for name, point in snapshot.auxiliary.items()
            if name in {"eth_btc", "bnb_btc", "sol_btc", "sol_eth"}
        },
        horizons=plans,
        events=events,
        warnings=warnings + [f"required_data_failure:{item}" for item in required],
        limitations=["research_only", "historical auxiliary coverage may be incomplete"],
        hard_filters=hard_filters,
    )


def evaluate_setup_at_time(
    snapshot: MarketSnapshot, config: AppConfig, profile_name: str = "auto"
) -> AnalysisReport:
    if config.config_version != 3:
        raise ValueError("configuration version 3 is required")
    if profile_name == "auto" and config.profile != "auto":
        profile_name = config.profile
    snapshot = _fresh_snapshot(snapshot, config)
    profile = get_profile(profile_name, snapshot.symbol)
    completed = {timeframe: snapshot.completed(timeframe) for timeframe in snapshot.candles}
    indicators = indicator_map(completed, config.indicators)
    technical_analysis = analyze_indicators(indicators, config.indicators)
    chart_patterns = {
        timeframe: detect_chart_patterns(completed[timeframe], indicator)
        for timeframe, indicator in indicators.items()
    }
    levels = (
        detect_levels(completed, indicators, snapshot.price, config.levels) if indicators else []
    )
    evaluations = {horizon: profile.evaluate_context(snapshot, horizon) for horizon in Horizon}
    profile_scores: dict[str, float | None] = {}
    for value in evaluations.values():
        profile_scores.update(value.component_scores)
    average_adjustment = float(
        np.mean([value.confidence_adjustment for value in evaluations.values()])
    )
    score = _score_card(snapshot, indicators, profile, profile_scores, average_adjustment)
    required = _required_failures(snapshot)
    hard_filters = sorted(
        {item for horizon in Horizon for item in profile.apply_hard_filters(snapshot, horizon)}
    )
    plans = {
        horizon: _plan(
            horizon,
            snapshot,
            indicators,
            levels,
            profile,
            score,
            required + hard_filters,
            evaluations[horizon].confidence_adjustment,
            config,
            chart_patterns.get(HORIZON_FRAMES[horizon][0], []),
        )
        for horizon in Horizon
    }
    warnings = sorted({warning for value in evaluations.values() for warning in value.warnings})
    availability = _availability(snapshot, completed)
    events = _events(snapshot, profile, plans, score, required, hard_filters, chart_patterns)
    return _assemble_report(
        snapshot,
        profile,
        indicators,
        levels,
        plans,
        score,
        availability,
        events,
        warnings,
        required,
        hard_filters,
        _report_id(snapshot, completed),
        chart_patterns,
        technical_analysis,
    )


def analyze_snapshot(
    snapshot: MarketSnapshot, config: AppConfig, profile: str = "auto"
) -> AnalysisReport:
    return evaluate_setup_at_time(snapshot, config, profile)
