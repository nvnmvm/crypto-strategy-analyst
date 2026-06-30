"""Deterministic candidate scoring and resistance-aware targets."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import AppConfig
from .models import PriceZone, ScoreBreakdown, SignalLabel, Trend
from .risk import RiskState, risk_blockers
from .structure import bullish_reversal_pattern


@dataclass(frozen=True, slots=True)
class SignalDecision:
    label: SignalLabel
    score: float
    breakdown: ScoreBreakdown
    confirmations: list[str]
    blockers: list[str]
    entry_zone: PriceZone | None
    stop_loss: float | None
    take_profit_1: float | None
    take_profit_2: float | None
    reward_risk: float | None


def _label_for_score(score: float) -> SignalLabel:
    if score >= 80:
        return SignalLabel.STRONG_BUY_CANDIDATE
    if score >= 65:
        return SignalLabel.BUY_CANDIDATE
    if score >= 50:
        return SignalLabel.WATCH
    return SignalLabel.NO_TRADE


def generate_signal(
    *,
    daily_trend: Trend,
    four_hour_trend: Trend,
    one_hour_frame: pd.DataFrame,
    four_hour_frame: pd.DataFrame,
    supports: list[PriceZone],
    resistances: list[PriceZone],
    data_is_complete: bool,
    config: AppConfig,
    risk_state: RiskState | None = None,
) -> SignalDecision:
    """Score one completed-bar setup without model judgment or future bars."""

    risk_state = risk_state or RiskState(peak_equity_cny=config.risk.account_equity_cny)
    current = four_hour_frame.iloc[-1]
    previous = four_hour_frame.iloc[-2]
    current_price, atr = float(current["close"]), float(current["atr14"])
    nearby_supports = [
        zone
        for zone in supports
        if zone.lower_price <= current_price + atr * config.strategy.support_proximity_atr
        and current_price - zone.upper_price <= atr * config.strategy.support_proximity_atr
    ]
    entry_zone = max(nearby_supports, key=lambda zone: zone.strength_score, default=None)
    next_resistance = next(
        (zone for zone in resistances if zone.upper_price > current_price),
        None,
    )

    confirmations: list[str] = []
    candle_ok, candle_name = bullish_reversal_pattern(one_hour_frame)
    if candle_ok:
        confirmations.append(f"bullish_candle:{candle_name}")
    if (
        current["volume_ratio"] >= config.strategy.volume_ratio_threshold
        and current["close"] > previous["close"]
    ):
        confirmations.append("volume_expansion_rebound")
    rsi_recovery = current["rsi14"] > previous["rsi14"] and (
        current["rsi14"] <= 50 or previous["rsi14"] < 30 <= current["rsi14"]
    )
    if rsi_recovery:
        confirmations.append("rsi_recovery")
    macd_improving = current["macd_histogram"] > previous["macd_histogram"]
    if macd_improving:
        confirmations.append("macd_momentum_improving")
    if previous["close"] <= previous["ema20"] and current["close"] > current["ema20"]:
        confirmations.append("reclaimed_ema20")
    if entry_zone and "+" in entry_zone.timeframe:
        confirmations.append("multi_timeframe_support")

    daily_points = (
        14.0 if daily_trend == Trend.BULLISH else 8.0 if daily_trend == Trend.SIDEWAYS else 0.0
    )
    four_hour_points = (
        6.0
        if four_hour_trend == Trend.BULLISH
        else 3.0
        if four_hour_trend == Trend.SIDEWAYS
        else 0.0
    )
    trend_points = daily_points + four_hour_points
    level_points = min(25.0, entry_zone.strength_score * 0.25) if entry_zone else 0.0
    candle_points = 15.0 if candle_ok else 0.0
    volume_points = 15.0 if "volume_expansion_rebound" in confirmations else 0.0
    indicator_points = sum(
        (
            5.0 if rsi_recovery else 0.0,
            5.0 if macd_improving else 0.0,
            5.0 if current["close"] > current["ema20"] else 0.0,
        )
    )

    stop_loss: float | None = None
    target_1: float | None = None
    target_2: float | None = None
    reward_risk: float | None = None
    space_points = 0.0
    target_blockers: list[str] = []
    if entry_zone:
        stop_loss = min(entry_zone.lower_price - atr * 0.5, current_price - atr)
        if stop_loss > 0 and stop_loss < current_price:
            one_r = current_price - stop_loss
            if next_resistance is None:
                target_blockers.append("no_key_resistance_for_targets")
            else:
                resistance_cap = next_resistance.lower_price - (
                    atr * config.strategy.target_resistance_buffer_atr
                )
                available_r = (resistance_cap - current_price) / one_r
                reward_risk = max(0.0, available_r)
                space_points = min(10.0, reward_risk / config.risk.min_reward_risk * 10.0)
                if available_r < config.risk.min_reward_risk:
                    target_blockers.append("resistance_space_below_two_r")
                else:
                    target_1 = min(
                        current_price + config.risk.min_reward_risk * one_r, resistance_cap
                    )
                    if available_r >= config.strategy.min_second_target_r_multiple:
                        target_2 = min(current_price + 3.0 * one_r, resistance_cap)
                    else:
                        target_blockers.append("second_target_unavailable_before_resistance")

    breakdown = ScoreBreakdown(
        higher_timeframe_trend=trend_points,
        support_resistance=level_points,
        candlestick_confirmation=candle_points,
        volume_confirmation=volume_points,
        indicator_confirmation=indicator_points,
        reward_risk_space=space_points,
        sentiment_adjustment=0.0,
    )
    score = breakdown.total
    blockers = [*risk_blockers(config.risk, risk_state), *target_blockers]
    if not data_is_complete:
        blockers.append("required_market_data_incomplete")
    if daily_trend == Trend.BEARISH:
        blockers.append("daily_trend_bearish")
    if four_hour_trend == Trend.BEARISH:
        blockers.append("four_hour_trend_bearish")
    if entry_zone is None:
        blockers.append("not_near_key_support")
    if len(confirmations) < config.strategy.min_confirmations:
        blockers.append("fewer_than_two_confirmations")
    if (
        reward_risk is None or reward_risk < config.risk.min_reward_risk
    ) and "resistance_space_below_two_r" not in blockers:
        blockers.append("reward_risk_below_minimum")

    label = _label_for_score(score)
    hard_blockers = {
        "required_market_data_incomplete",
        "daily_trend_bearish",
        "daily_stop_count_reached",
        "daily_loss_limit_reached",
        "maximum_drawdown_protection_active",
        "resistance_space_below_two_r",
        "no_key_resistance_for_targets",
    }
    if any(blocker in hard_blockers for blocker in blockers):
        label = SignalLabel.NO_TRADE
    elif blockers:
        label = SignalLabel.WATCH
    if target_1 is None or target_2 is None:
        label = SignalLabel.NO_TRADE if label == SignalLabel.NO_TRADE else SignalLabel.WATCH

    return SignalDecision(
        label=label,
        score=score,
        breakdown=breakdown,
        confirmations=confirmations,
        blockers=blockers,
        entry_zone=entry_zone,
        stop_loss=stop_loss,
        take_profit_1=target_1,
        take_profit_2=target_2,
        reward_risk=reward_risk,
    )
