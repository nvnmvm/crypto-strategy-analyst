"""Confirmed swing points and deterministic trend state."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .models import Trend


@dataclass(frozen=True, slots=True)
class SwingPoint:
    timestamp: pd.Timestamp
    price: float
    kind: str
    confirmed_at: pd.Timestamp


def detect_confirmed_swings(
    frame: pd.DataFrame,
    *,
    left: int = 3,
    right: int = 3,
) -> list[SwingPoint]:
    """Return swings only after their right-side confirmation bars exist."""

    swings: list[SwingPoint] = []
    for idx in range(left, len(frame) - right):
        high_window = frame["high"].iloc[idx - left : idx + right + 1]
        low_window = frame["low"].iloc[idx - left : idx + right + 1]
        high = float(frame["high"].iloc[idx])
        low = float(frame["low"].iloc[idx])
        confirmed_at = pd.Timestamp(frame.index[idx + right])
        if high == float(high_window.max()) and int((high_window == high).sum()) == 1:
            swings.append(SwingPoint(pd.Timestamp(frame.index[idx]), high, "high", confirmed_at))
        if low == float(low_window.min()) and int((low_window == low).sum()) == 1:
            swings.append(SwingPoint(pd.Timestamp(frame.index[idx]), low, "low", confirmed_at))
    return sorted(swings, key=lambda point: point.timestamp)


def classify_trend(frame: pd.DataFrame, swings: list[SwingPoint]) -> Trend:
    """Classify trend from confirmed structure, EMA alignment, and MACD."""

    latest = frame.iloc[-1]
    score = 0
    highs = [point for point in swings if point.kind == "high"][-2:]
    lows = [point for point in swings if point.kind == "low"][-2:]
    if len(highs) == 2 and len(lows) == 2:
        if highs[-1].price > highs[-2].price and lows[-1].price > lows[-2].price:
            score += 2
        elif highs[-1].price < highs[-2].price and lows[-1].price < lows[-2].price:
            score -= 2
    if latest["ema20"] > latest["ema50"] > latest["ema200"]:
        score += 2
    elif latest["ema20"] < latest["ema50"] < latest["ema200"]:
        score -= 2
    if latest["close"] > latest["ema200"]:
        score += 1
    elif latest["close"] < latest["ema200"]:
        score -= 1
    if latest["macd_histogram"] > 0:
        score += 1
    elif latest["macd_histogram"] < 0:
        score -= 1
    if score >= 3:
        return Trend.BULLISH
    if score <= -3:
        return Trend.BEARISH
    return Trend.SIDEWAYS


def bullish_reversal_pattern(frame: pd.DataFrame) -> tuple[bool, str]:
    """Detect a hammer or bullish engulfing pattern on completed bars."""

    if len(frame) < 2:
        return False, "none"
    previous, current = frame.iloc[-2], frame.iloc[-1]
    body = abs(float(current["close"] - current["open"]))
    full_range = float(current["high"] - current["low"])
    lower_wick = float(min(current["open"], current["close"]) - current["low"])
    upper_wick = float(current["high"] - max(current["open"], current["close"]))
    hammer = (
        full_range > 0
        and current["close"] >= current["open"]
        and lower_wick >= max(body * 2, full_range * 0.4)
        and upper_wick <= full_range * 0.25
    )
    engulfing = (
        previous["close"] < previous["open"]
        and current["close"] > current["open"]
        and current["open"] <= previous["close"]
        and current["close"] >= previous["open"]
    )
    if engulfing:
        return True, "bullish_engulfing"
    if hammer:
        return True, "hammer"
    return False, "none"
