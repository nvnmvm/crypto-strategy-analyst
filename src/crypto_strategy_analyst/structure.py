"""Price structure, swing points and independent confirmations."""

from __future__ import annotations

from dataclasses import dataclass

from .models import Candle, IndicatorSet


@dataclass(frozen=True)
class Swing:
    index: int
    price: float
    kind: str


def swings(bars: list[Candle], window: int) -> list[Swing]:
    result: list[Swing] = []
    for index in range(window, len(bars) - window):
        segment = bars[index - window : index + window + 1]
        if bars[index].low == min(bar.low for bar in segment):
            result.append(Swing(index, bars[index].low, "low"))
        if bars[index].high == max(bar.high for bar in segment):
            result.append(Swing(index, bars[index].high, "high"))
    return result


def structure_confirmations(bars: list[Candle], indicator: IndicatorSet) -> list[str]:
    if len(bars) < 6:
        return []
    confirmations: list[str] = []
    recent = bars[-1]
    previous = bars[-2]
    lows = [point for point in swings(bars[-30:], 2) if point.kind == "low"]
    highs = [point for point in swings(bars[-30:], 2) if point.kind == "high"]
    if len(lows) >= 2 and lows[-1].price > lows[-2].price:
        confirmations.append("higher_low")
    if recent.close > previous.high and highs:
        confirmations.append("break_local_high")
    if recent.close > indicator.ema20 and previous.close <= indicator.ema20:
        confirmations.append("reclaim_ema20")
    if (
        recent.close > recent.open
        and previous.close < previous.open
        and recent.close >= previous.open
    ):
        confirmations.append("bullish_engulfing")
    if recent.low < min(bar.low for bar in bars[-6:-1]) and recent.close > previous.close:
        confirmations.append("false_break_reclaim")
    return confirmations


def secondary_confirmations(indicator: IndicatorSet) -> list[str]:
    result: list[str] = []
    if indicator.volume_ratio >= 1.15:
        result.append("volume_expansion")
    if 45 <= indicator.rsi <= 68:
        result.append("rsi_recovery")
    if indicator.macd_histogram > 0:
        result.append("macd_improving")
    return result


def structure_intact(bars: list[Candle], lookback: int = 30) -> bool:
    points = [point for point in swings(bars[-lookback:], 2) if point.kind == "low"]
    return len(points) < 2 or points[-1].price >= points[-2].price * 0.98


def drawdown(bars: list[Candle], lookback: int = 90) -> float:
    if not bars:
        return 0
    high = max(bar.high for bar in bars[-lookback:])
    return max(0, 1 - bars[-1].close / high)
