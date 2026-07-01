"""Deterministic market-regime classification from closed daily and 4h bars."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .models import MarketRegime
from .structure import detect_confirmed_swings


@dataclass(frozen=True, slots=True)
class RegimeAssessment:
    regime: MarketRegime
    evidence: list[str]
    selected_strategy: str
    drawdown_from_365d_high: float
    daily_higher_low: bool
    four_hour_reclaim: bool
    accelerated_decline: bool


def _slope(series: pd.Series, bars: int) -> float:
    current = float(series.iloc[-1])
    previous = float(series.iloc[-bars - 1])
    return current / previous - 1 if previous > 0 else 0.0


def classify_market_regime(
    daily: pd.DataFrame,
    four_hour: pd.DataFrame,
) -> RegimeAssessment:
    """Classify one closed-bar snapshot without using future confirmation."""

    if len(daily) < 210 or len(four_hour) < 60:
        raise ValueError("market regime requires 210 daily and 60 four-hour bars")
    day = daily.iloc[-1]
    four = four_hour.iloc[-1]
    close = float(day["close"])
    ema200 = float(day["ema200"])
    ema50_slope = _slope(daily["ema50"], 20)
    ema200_slope = _slope(daily["ema200"], 50)
    high_365 = float(daily["high"].iloc[-365:].max())
    drawdown = max(0.0, 1 - close / high_365) if high_365 > 0 else 0.0
    atr_percent = float(day["atr14"]) / close
    median_atr_percent = float(
        (daily["atr14"].iloc[-90:] / daily["close"].iloc[-90:]).median()
    )
    five_day_return = close / float(daily["close"].iloc[-6]) - 1
    accelerated_decline = five_day_return <= -0.08 and atr_percent >= median_atr_percent * 1.5

    swings = detect_confirmed_swings(daily, left=3, right=3)
    lows = [point for point in swings if point.kind == "low"][-2:]
    highs = [point for point in swings if point.kind == "high"][-2:]
    higher_low = len(lows) == 2 and lows[-1].price > lows[-2].price
    higher_high = len(highs) == 2 and highs[-1].price > highs[-2].price
    lower_low = len(lows) == 2 and lows[-1].price < lows[-2].price
    four_reclaim = float(four["close"]) > float(four["ema20"])
    four_strong_reclaim = float(four["close"]) > float(four["ema50"])
    above_ema200 = close >= ema200
    near_ema200 = abs(close / ema200 - 1) <= 0.05

    evidence = [
        f"daily_close_vs_ema200:{close / ema200 - 1:.6f}",
        f"ema50_slope_20d:{ema50_slope:.6f}",
        f"ema200_slope_50d:{ema200_slope:.6f}",
        f"drawdown_from_365d_high:{drawdown:.6f}",
        f"daily_atr_percent:{atr_percent:.6f}",
        f"daily_higher_low:{str(higher_low).lower()}",
        f"daily_higher_high:{str(higher_high).lower()}",
        f"daily_lower_low:{str(lower_low).lower()}",
        f"four_hour_reclaim_ema20:{str(four_reclaim).lower()}",
        f"four_hour_reclaim_ema50:{str(four_strong_reclaim).lower()}",
        f"accelerated_decline:{str(accelerated_decline).lower()}",
    ]

    if (
        above_ema200
        and ema50_slope > 0.01
        and ema200_slope > 0
        and (higher_low or higher_high)
    ):
        regime = MarketRegime.BULL_TREND
    elif above_ema200 and ema200_slope >= -0.005 and (drawdown >= 0.08 or not four_reclaim):
        regime = MarketRegime.BULL_PULLBACK
    elif near_ema200 and abs(ema50_slope) <= 0.02 and abs(ema200_slope) <= 0.01:
        regime = MarketRegime.SIDEWAYS_RANGE
    elif drawdown >= 0.25 and accelerated_decline and not higher_low:
        regime = MarketRegime.BEAR_CAPITULATION
    elif drawdown >= 0.25 and (higher_low or four_strong_reclaim) and not accelerated_decline:
        regime = MarketRegime.BEAR_RECOVERY
    else:
        regime = MarketRegime.BEAR_TREND

    selected = (
        "trend_pullback"
        if regime
        in {
            MarketRegime.BULL_TREND,
            MarketRegime.BULL_PULLBACK,
            MarketRegime.SIDEWAYS_RANGE,
        }
        else "bear_reversal_accumulation"
        if regime in {MarketRegime.BEAR_CAPITULATION, MarketRegime.BEAR_RECOVERY}
        else "none"
    )
    return RegimeAssessment(
        regime=regime,
        evidence=evidence,
        selected_strategy=selected,
        drawdown_from_365d_high=drawdown,
        daily_higher_low=higher_low,
        four_hour_reclaim=four_reclaim or four_strong_reclaim,
        accelerated_decline=accelerated_decline,
    )
