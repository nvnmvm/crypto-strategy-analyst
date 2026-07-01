"""Regime-aware candidate plans with weighted confirmation and tiered risk."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import AppConfig
from .models import MarketRegime, PriceZone, ScoreBreakdown, SignalLabel, StrategyHorizon
from .regime import RegimeAssessment
from .risk import RiskState, risk_blockers
from .signal import SignalDecision
from .structure import bullish_reversal_pattern, detect_confirmed_swings


@dataclass(frozen=True, slots=True)
class ConfirmationAssessment:
    names: tuple[str, ...]
    score: float
    strong_count: int
    breakout_level: float | None


def _breakout_retest(frame: pd.DataFrame) -> tuple[bool, float | None]:
    if len(frame) < 30:
        return False, None
    recent = frame.iloc[-30:]
    breakout_position: int | None = None
    breakout_level: float | None = None
    for position in range(len(recent) - 6, len(recent) - 1):
        previous_high = float(recent["high"].iloc[position - 20 : position].max())
        if float(recent["close"].iloc[position]) > previous_high:
            breakout_position = position
            breakout_level = previous_high
    if breakout_position is None or breakout_level is None:
        return False, None
    after = recent.iloc[breakout_position + 1 :]
    if after.empty:
        return False, None
    atr = float(recent["atr14"].iloc[breakout_position])
    held = float(after["close"].min()) >= breakout_level - atr * 0.25
    retested = float(after["low"].min()) <= breakout_level + atr * 0.35
    latest = recent.iloc[-1]
    resumed = (
        breakout_level <= float(latest["close"]) <= breakout_level + atr * 0.75
        and latest["close"] > latest["open"]
    )
    volume_contracts = float(after["volume"].mean()) <= float(
        recent["volume"].iloc[breakout_position]
    )
    return held and retested and resumed and volume_contracts, breakout_level


def weighted_confirmations(
    daily: pd.DataFrame,
    four_hour: pd.DataFrame,
    one_hour: pd.DataFrame,
    supports: list[PriceZone],
    regime: RegimeAssessment,
    config: AppConfig,
) -> ConfirmationAssessment:
    names: list[str] = []
    score = 0.0
    strong = 0
    swings = detect_confirmed_swings(four_hour, left=3, right=3)
    lows = [point for point in swings if point.kind == "low"][-2:]
    higher_low = len(lows) == 2 and lows[-1].price > lows[-2].price
    if higher_low:
        names.append("strong:four_hour_higher_low")
        score += 2
        strong += 1

    candle_ok, candle_name = bullish_reversal_pattern(four_hour)
    current = four_hour.iloc[-1]
    previous = four_hour.iloc[-2]
    if candle_ok and float(current["close"]) > float(current["ema20"]):
        names.append(f"strong:four_hour_{candle_name}_reclaim_ema20")
        score += 2
        strong += 1

    breakout_ok, breakout_level = _breakout_retest(four_hour)
    if breakout_ok:
        names.append("strong:breakout_retest")
        score += 2
        strong += 1

    if regime.regime == MarketRegime.BEAR_RECOVERY and regime.daily_higher_low:
        names.append("strong:daily_reversal_structure")
        score += 2
        strong += 1

    if float(current["volume_ratio"]) >= config.strategy.volume_ratio_threshold and float(
        current["close"]
    ) > float(previous["close"]):
        names.append("normal:volume_rebound")
        score += 1
    histogram = four_hour["macd_histogram"].iloc[-3:]
    if histogram.is_monotonic_increasing:
        names.append("normal:macd_histogram_consecutive_improvement")
        score += 1
    if float(previous["rsi14"]) < 35 <= float(current["rsi14"]):
        names.append("normal:rsi_oversold_recovery")
        score += 1
    one_hour_candle, one_hour_name = bullish_reversal_pattern(one_hour)
    if one_hour_candle:
        names.append(f"normal:one_hour_{one_hour_name}")
        score += 1
    if any("+" in zone.timeframe for zone in supports[:3]):
        names.append("normal:multi_timeframe_support")
        score += 1

    if float(current["close"]) > float(current["ema20"]):
        names.append("auxiliary:above_ema20")
        score += 0.5
    if 1.05 <= float(current["volume_ratio"]) < config.strategy.volume_ratio_threshold:
        names.append("auxiliary:slightly_above_average_volume")
        score += 0.5
    if float(current["rsi14"]) > float(previous["rsi14"]):
        names.append("auxiliary:rsi_rising")
        score += 0.5
    return ConfirmationAssessment(tuple(names), score, strong, breakout_level)


def _entry_zone(
    four_hour: pd.DataFrame,
    supports: list[PriceZone],
    resistances: list[PriceZone],
    regime: RegimeAssessment,
    confirmations: ConfirmationAssessment,
    config: AppConfig,
) -> tuple[str, PriceZone | None, PriceZone | None, float | None]:
    current = four_hour.iloc[-1]
    price = float(current["close"])
    atr = float(current["atr14"])
    nearby = [
        zone
        for zone in supports
        if price - zone.upper_price <= atr * config.strategy.support_proximity_atr
        and zone.lower_price <= price + atr * config.strategy.support_proximity_atr
    ]
    support = max(nearby, key=lambda item: item.strength_score, default=None)
    variant = config.strategy.strategy_variant
    if (
        variant in {"relaxed_trend_plus_breakout", "relaxed_trend_plus_bear_reversal"}
        and confirmations.breakout_level is not None
    ):
        level = confirmations.breakout_level
        lower, upper = level - atr * 0.20, level + atr * 0.35
        zone = PriceZone(
            lower_price=lower,
            upper_price=upper,
            center_price=(lower + upper) / 2,
            level_type="support",
            timeframe="4h",
            touch_count=1,
            last_touch_time=four_hour.index[-1].to_pydatetime(),
            strength_score=60,
            evidence=["allowed_entry_range", "breakout_retest"],
        )
        return "breakout_retest", support, zone, level - atr * 0.50

    near_resistance = next(
        (
            zone
            for zone in resistances
            if zone.lower_price > price and zone.lower_price - price <= atr * 1.5
        ),
        None,
    )
    continuation = (
        regime.regime == MarketRegime.BULL_TREND
        and float(current["ema20"]) > float(current["ema50"])
        and price >= float(current["ema20"]) - atr
        and near_resistance is None
        and confirmations.score >= 1
    )
    if (
        variant in {"relaxed_trend_plus_breakout", "relaxed_trend_plus_bear_reversal"}
        and continuation
    ):
        lower, upper = price - atr * 0.25, price + atr * 0.35
        zone = PriceZone(
            lower_price=lower,
            upper_price=upper,
            center_price=(lower + upper) / 2,
            level_type="support",
            timeframe="4h",
            touch_count=1,
            last_touch_time=four_hour.index[-1].to_pydatetime(),
            strength_score=55,
            evidence=["allowed_entry_range", "trend_continuation"],
        )
        stop = min(float(current["ema50"]), float(four_hour["low"].iloc[-10:].min()))
        return "trend_continuation", support, zone, stop - atr * 0.25

    if support is not None:
        lower = max(
            support.lower_price,
            support.upper_price - atr * config.strategy.entry_zone_depth_atr,
        )
        upper = max(price + atr * config.strategy.entry_zone_chase_atr, support.upper_price)
        zone = support.model_copy(
            update={
                "lower_price": lower,
                "upper_price": upper,
                "center_price": (lower + upper) / 2,
                "evidence": [*support.evidence, "allowed_entry_range", "support_rebound"],
            }
        )
        return (
            "support_rebound",
            support,
            zone,
            support.lower_price - atr * config.strategy.stop_buffer_atr,
        )

    if regime.regime in {MarketRegime.BEAR_CAPITULATION, MarketRegime.BEAR_RECOVERY}:
        lower, upper = price - atr * 0.25, price + atr * 0.25
        zone = PriceZone(
            lower_price=lower,
            upper_price=upper,
            center_price=price,
            level_type="support",
            timeframe="4h",
            touch_count=1,
            last_touch_time=four_hour.index[-1].to_pydatetime(),
            strength_score=50,
            evidence=["allowed_entry_range", "higher_low_reversal"],
        )
        return (
            "higher_low_reversal",
            support,
            zone,
            float(four_hour["low"].iloc[-20:].min()) - atr * 0.25,
        )
    return "not_available", support, None, None


def generate_adaptive_signal(
    *,
    regime: RegimeAssessment,
    daily_frame: pd.DataFrame,
    four_hour_frame: pd.DataFrame,
    one_hour_frame: pd.DataFrame,
    supports: list[PriceZone],
    resistances: list[PriceZone],
    data_is_complete: bool,
    config: AppConfig,
    risk_state: RiskState,
) -> SignalDecision:
    confirmations = weighted_confirmations(
        daily_frame, four_hour_frame, one_hour_frame, supports, regime, config
    )
    entry_setup, support, allowed, stop = _entry_zone(
        four_hour_frame, supports, resistances, regime, confirmations, config
    )
    strategy_id = regime.selected_strategy
    current = four_hour_frame.iloc[-1]
    price, atr = float(current["close"]), float(current["atr14"])
    planned = (
        min(max(price, allowed.lower_price), allowed.upper_price) if allowed is not None else None
    )
    blockers = risk_blockers(config.risk, risk_state)
    variant = config.strategy.strategy_variant
    bear_enabled = variant == "relaxed_trend_plus_bear_reversal"
    if not data_is_complete:
        blockers.append("required_market_data_incomplete")
    if regime.regime == MarketRegime.BEAR_TREND:
        blockers.append("bear_trend_disables_all_long_entries")
    if strategy_id == "bear_reversal_accumulation" and not bear_enabled:
        blockers.append("bear_reversal_strategy_disabled")
    if strategy_id == "bear_reversal_accumulation":
        if regime.drawdown_from_365d_high < config.strategy.bear_drawdown_threshold:
            blockers.append("bear_drawdown_not_deep_enough")
        if regime.accelerated_decline:
            blockers.append("accelerated_decline_without_stabilization")
        if confirmations.strong_count == 0:
            blockers.append("bear_reversal_requires_structure_confirmation")
    if confirmations.strong_count == 0 and confirmations.score < 2:
        blockers.append("weighted_confirmation_below_minimum")
    if allowed is None or stop is None or planned is None or stop <= 0 or stop >= planned:
        blockers.append("no_valid_allowed_entry_range")

    target_1 = target_2 = reward_risk = None
    tier = "none"
    target_sources: tuple[str, ...] = ()
    risk_multiplier = 0.0
    if planned is not None and stop is not None and 0 < stop < planned:
        one_r = planned - stop
        resistance = next((zone for zone in resistances if zone.lower_price > planned), None)
        cap = (
            resistance.lower_price - atr * config.strategy.target_resistance_buffer_atr
            if resistance
            else None
        )
        available_r = (cap - planned) / one_r if cap is not None else None
        a_target_r = config.risk.min_reward_risk + config.strategy.execution_reward_risk_cushion
        b_target_r = (
            config.strategy.b_tier_min_reward_risk + config.strategy.execution_reward_risk_cushion
        )
        if available_r is not None and available_r >= config.strategy.min_second_target_r_multiple:
            target_1 = planned + a_target_r * one_r
            target_2 = min(
                planned + config.strategy.min_second_target_r_multiple * one_r,
                cap,
            )
            reward_risk = available_r
            tier = "A"
            target_sources = ("risk_multiple", "nearest_resistance")
            risk_multiplier = 1.0
        elif confirmations.strong_count >= 1 and (
            available_r is None or available_r >= config.strategy.b_tier_min_reward_risk
        ):
            target_1 = planned + b_target_r * one_r
            if cap is not None:
                target_1 = min(target_1, cap)
            reward_risk = b_target_r if available_r is None else available_r
            tier = "B"
            target_sources = (
                ("risk_multiple",)
                if resistance is None
                else ("risk_multiple", "nearest_resistance")
            )
            risk_multiplier = config.strategy.b_tier_risk_multiplier
        else:
            blockers.append("target_space_below_tier_minimum")

    # Targets and the original stop stay immutable. Derive the highest
    # acceptable future fill from the tier's minimum reward/risk instead.
    if allowed is not None and stop is not None and target_1 is not None:
        minimum_r = (
            config.strategy.b_tier_min_reward_risk if tier == "B" else config.risk.min_reward_risk
        )
        maximum_entry_for_r = (target_1 + minimum_r * stop) / (1 + minimum_r)
        upper = min(allowed.upper_price, maximum_entry_for_r)
        if upper < allowed.lower_price:
            blockers.append("allowed_entry_range_has_no_valid_reward_risk_price")
        else:
            allowed = allowed.model_copy(
                update={
                    "upper_price": upper,
                    "center_price": (allowed.lower_price + upper) / 2,
                }
            )

    if regime.regime == MarketRegime.SIDEWAYS_RANGE:
        risk_multiplier = min(risk_multiplier, config.strategy.sideways_risk_multiplier)
    if strategy_id == "bear_reversal_accumulation":
        risk_multiplier = min(risk_multiplier, config.strategy.bear_first_risk_multiplier)
        tier = "B" if tier != "none" else tier
        if target_1 is not None:
            daily_swings = detect_confirmed_swings(daily_frame, left=3, right=3)
            cutoff = daily_frame.index[-1] - pd.Timedelta(days=180)
            confirmed_highs = [
                point.price
                for point in daily_swings
                if point.kind == "high" and point.timestamp >= cutoff
            ]
            previous_major_high = confirmed_highs[-1] if confirmed_highs else None
            daily_ema200 = float(daily_frame["ema200"].iloc[-1])
            range_high = float(daily_frame["high"].iloc[-90:].max())
            distant_targets = [
                ("daily_ema200", daily_ema200),
                ("range_high", range_high),
                ("previous_major_high", previous_major_high),
            ]
            feasible = [
                (source, value)
                for source, value in distant_targets
                if value is not None and value > target_1
            ]
            if feasible:
                source, value = min(feasible, key=lambda item: item[1])
                if cap is None or value <= cap:
                    target_2 = value
                    target_sources = tuple(dict.fromkeys([*target_sources, source, "atr_trailing"]))
            elif "atr_trailing" not in target_sources:
                target_sources = (*target_sources, "atr_trailing")

    trend_points = {
        MarketRegime.BULL_TREND: 20.0,
        MarketRegime.BULL_PULLBACK: 16.0,
        MarketRegime.SIDEWAYS_RANGE: 10.0,
        MarketRegime.BEAR_RECOVERY: 12.0,
        MarketRegime.BEAR_CAPITULATION: 6.0,
        MarketRegime.BEAR_TREND: 0.0,
    }[regime.regime]
    level_points = min(25.0, support.strength_score * 0.25) if support else 8.0
    candle_points = min(15.0, confirmations.strong_count * 10.0)
    volume_points = 15.0 if any("volume" in name for name in confirmations.names) else 0.0
    indicator_points = min(15.0, confirmations.score * 3.0)
    space_points = 10.0 if tier == "A" else 7.0 if tier == "B" else 0.0
    breakdown = ScoreBreakdown(
        higher_timeframe_trend=trend_points,
        support_resistance=level_points,
        candlestick_confirmation=candle_points,
        volume_confirmation=volume_points,
        indicator_confirmation=indicator_points,
        reward_risk_space=space_points,
    )
    score = breakdown.total
    label = (
        SignalLabel.STRONG_BUY_CANDIDATE
        if score >= config.strategy.strong_buy_score and tier == "A"
        else SignalLabel.BUY_CANDIDATE
        if score >= config.strategy.buy_score and tier in {"A", "B"}
        else SignalLabel.WATCH
        if score >= config.strategy.watch_score
        else SignalLabel.NO_TRADE
    )
    hard_prefixes = (
        "required_",
        "bear_trend_",
        "bear_reversal_strategy_disabled",
        "accelerated_",
        "weighted_",
        "no_valid_",
        "target_space_",
    )
    if any(blocker.startswith(hard_prefixes) for blocker in blockers):
        label = SignalLabel.NO_TRADE
    elif blockers:
        label = SignalLabel.WATCH
    if tier == "B" and label == SignalLabel.STRONG_BUY_CANDIDATE:
        label = SignalLabel.BUY_CANDIDATE
    horizon = (
        StrategyHorizon.LONG_TERM
        if strategy_id == "bear_reversal_accumulation"
        else StrategyHorizon.SHORT_TERM
        if entry_setup in {"breakout_retest", "trend_continuation"}
        else StrategyHorizon.MEDIUM_TERM
    )

    return SignalDecision(
        label=label,
        score=score,
        breakdown=breakdown,
        confirmations=list(confirmations.names),
        blockers=list(dict.fromkeys(blockers)),
        entry_zone=allowed,
        stop_loss=stop,
        take_profit_1=target_1,
        take_profit_2=target_2,
        reward_risk=reward_risk,
        planned_entry_price=planned,
        support_zone=support,
        market_regime=regime.regime,
        regime_evidence=tuple(regime.evidence),
        strategy_id=strategy_id,
        strategy_horizon=horizon,
        entry_setup=entry_setup,
        candidate_tier=tier,
        risk_multiplier=risk_multiplier,
        target_sources=target_sources,
        confirmation_score=confirmations.score,
        strong_confirmation_count=confirmations.strong_count,
    )
