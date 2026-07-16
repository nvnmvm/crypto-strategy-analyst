"""Price structure, swing points and independent confirmations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .models import Candle, IndicatorSet


@dataclass(frozen=True)
class Swing:
    index: int
    price: float
    kind: str


@dataclass(frozen=True)
class ChartPattern:
    """A deterministic chart pattern found only from completed candle swings."""

    name: Literal[
        "double_bottom",
        "double_top",
        "inverse_head_shoulders",
        "head_shoulders",
        "triangle_breakout",
    ]
    direction: Literal["bullish", "bearish"]
    state: Literal["forming", "confirmed", "invalidated"]
    neckline: float
    invalidation: float
    measured_target: float
    completed_index: int

    def as_dict(self) -> dict[str, str | float | int]:
        return {
            "name": self.name,
            "direction": self.direction,
            "state": self.state,
            "neckline": self.neckline,
            "invalidation": self.invalidation,
            "measured_target": self.measured_target,
            "completed_index": self.completed_index,
        }


PATTERN_SWING_WINDOW = 2
PATTERN_LOOKBACK_BARS = 120
PATTERN_MIN_SPAN_BARS = 4
PATTERN_LEVEL_TOLERANCE_ATR = 0.8
PATTERN_BREAKOUT_ATR = 0.3
PATTERN_MIN_HEIGHT_ATR = 1.0
PATTERN_MIN_HEAD_ATR = 0.5


def swings(bars: list[Candle], window: int) -> list[Swing]:
    result: list[Swing] = []
    for index in range(window, len(bars) - window):
        segment = bars[index - window : index + window + 1]
        if bars[index].low == min(bar.low for bar in segment):
            result.append(Swing(index, bars[index].low, "low"))
        if bars[index].high == max(bar.high for bar in segment):
            result.append(Swing(index, bars[index].high, "high"))
    return result


def _pattern_state(
    close: float,
    neckline: float,
    invalidation: float,
    direction: Literal["bullish", "bearish"],
    atr: float,
) -> Literal["forming", "confirmed", "invalidated"]:
    threshold = atr * PATTERN_BREAKOUT_ATR
    if direction == "bullish":
        if close > neckline + threshold:
            return "confirmed"
        if close < invalidation:
            return "invalidated"
    else:
        if close < neckline - threshold:
            return "confirmed"
        if close > invalidation:
            return "invalidated"
    return "forming"


def _double_pattern(
    bars: list[Candle], points: list[Swing], indicator: IndicatorSet, kind: str
) -> ChartPattern | None:
    """Detect the latest double top/bottom and require a completed-neckline break."""

    direction: Literal["bullish", "bearish"] = "bullish" if kind == "low" else "bearish"
    name: Literal["double_bottom", "double_top"] = (
        "double_bottom" if kind == "low" else "double_top"
    )
    candidates: list[ChartPattern] = []
    tolerance = indicator.atr * PATTERN_LEVEL_TOLERANCE_ATR
    for first_index, first in enumerate(points[:-2]):
        if first.kind != kind:
            continue
        for second in points[first_index + 2 :]:
            if second.kind != kind:
                continue
            span = second.index - first.index
            if not PATTERN_MIN_SPAN_BARS <= span <= PATTERN_LOOKBACK_BARS:
                continue
            if abs(first.price - second.price) > tolerance:
                continue
            segment = bars[first.index : second.index + 1]
            if kind == "low":
                neckline = max(bar.high for bar in segment)
                reference = max(first.price, second.price)
                height = neckline - reference
                invalidation = min(first.price, second.price) - indicator.atr * PATTERN_BREAKOUT_ATR
                target = neckline + height
            else:
                neckline = min(bar.low for bar in segment)
                reference = min(first.price, second.price)
                height = reference - neckline
                invalidation = max(first.price, second.price) + indicator.atr * PATTERN_BREAKOUT_ATR
                target = neckline - height
            if height < indicator.atr * PATTERN_MIN_HEIGHT_ATR:
                continue
            candidates.append(
                ChartPattern(
                    name=name,
                    direction=direction,
                    state=_pattern_state(
                        bars[-1].close, neckline, invalidation, direction, indicator.atr
                    ),
                    neckline=neckline,
                    invalidation=invalidation,
                    measured_target=target,
                    completed_index=second.index,
                )
            )
    return max(candidates, key=lambda pattern: pattern.completed_index, default=None)


def _neckline_at(first: Swing, second: Swing, index: int) -> float:
    if first.index == second.index:
        return first.price
    slope = (second.price - first.price) / (second.index - first.index)
    return first.price + slope * (index - first.index)


def _head_shoulders(
    bars: list[Candle], points: list[Swing], indicator: IndicatorSet, inverse: bool
) -> ChartPattern | None:
    """Detect a completed head-and-shoulders family pattern from five alternating swings."""

    expected = ["low", "high", "low", "high", "low"] if inverse else ["high", "low", "high", "low", "high"]
    direction: Literal["bullish", "bearish"] = "bullish" if inverse else "bearish"
    name: Literal["inverse_head_shoulders", "head_shoulders"] = (
        "inverse_head_shoulders" if inverse else "head_shoulders"
    )
    candidates: list[ChartPattern] = []
    shoulder_tolerance = indicator.atr * PATTERN_LEVEL_TOLERANCE_ATR
    for start in range(len(points) - 4):
        left, first_neck, head, second_neck, right = points[start : start + 5]
        if [point.kind for point in (left, first_neck, head, second_neck, right)] != expected:
            continue
        if not PATTERN_MIN_SPAN_BARS <= right.index - left.index <= PATTERN_LOOKBACK_BARS:
            continue
        if abs(left.price - right.price) > shoulder_tolerance:
            continue
        if inverse:
            head_height = min(left.price, right.price) - head.price
            if head_height < indicator.atr * PATTERN_MIN_HEAD_ATR:
                continue
        else:
            head_height = head.price - max(left.price, right.price)
            if head_height < indicator.atr * PATTERN_MIN_HEAD_ATR:
                continue
        neckline = _neckline_at(first_neck, second_neck, len(bars) - 1)
        invalidation = (
            head.price - indicator.atr * PATTERN_BREAKOUT_ATR
            if inverse
            else head.price + indicator.atr * PATTERN_BREAKOUT_ATR
        )
        height = abs(head.price - neckline)
        if height < indicator.atr * PATTERN_MIN_HEIGHT_ATR:
            continue
        target = neckline + height if inverse else neckline - height
        candidates.append(
            ChartPattern(
                name=name,
                direction=direction,
                state=_pattern_state(
                    bars[-1].close, neckline, invalidation, direction, indicator.atr
                ),
                neckline=neckline,
                invalidation=invalidation,
                measured_target=target,
                completed_index=right.index,
            )
        )
    return max(candidates, key=lambda pattern: pattern.completed_index, default=None)


def _triangle_breakout(
    bars: list[Candle], points: list[Swing], indicator: IndicatorSet
) -> ChartPattern | None:
    """Recognize a compressed triangle only after its completed-candle breakout.

    This intentionally covers ascending, descending and symmetrical triangles as
    one compact continuation family.  The breakout direction, not a visual label,
    determines the bias.
    """

    highs = [point for point in points if point.kind == "high"]
    lows = [point for point in points if point.kind == "low"]
    if len(highs) < 2 or len(lows) < 2:
        return None
    first_high, second_high = highs[-2:]
    first_low, second_low = lows[-2:]
    start = min(first_high.index, first_low.index)
    end = max(second_high.index, second_low.index)
    if not PATTERN_MIN_SPAN_BARS <= end - start <= PATTERN_LOOKBACK_BARS:
        return None
    first_width = first_high.price - first_low.price
    latest_width = second_high.price - second_low.price
    if first_width < indicator.atr * PATTERN_MIN_HEIGHT_ATR:
        return None
    if latest_width <= 0 or latest_width > first_width * 0.8:
        return None
    tolerance = indicator.atr * PATTERN_LEVEL_TOLERANCE_ATR
    if second_high.price > first_high.price + tolerance:
        return None
    if second_low.price < first_low.price - tolerance:
        return None
    current_index = len(bars) - 1
    upper = _neckline_at(first_high, second_high, current_index)
    lower = _neckline_at(first_low, second_low, current_index)
    threshold = indicator.atr * PATTERN_BREAKOUT_ATR
    close = bars[-1].close
    if close > upper + threshold:
        return ChartPattern(
            name="triangle_breakout",
            direction="bullish",
            state="confirmed",
            neckline=upper,
            invalidation=lower - threshold,
            measured_target=upper + first_width,
            completed_index=end,
        )
    if close < lower - threshold:
        return ChartPattern(
            name="triangle_breakout",
            direction="bearish",
            state="confirmed",
            neckline=lower,
            invalidation=upper + threshold,
            measured_target=lower - first_width,
            completed_index=end,
        )
    return None


def detect_chart_patterns(bars: list[Candle], indicator: IndicatorSet) -> list[ChartPattern]:
    """Return the latest formation of each supported pattern from closed candles only.

    Forming patterns are observations, not signals.  A pattern becomes ``confirmed``
    only when the final completed candle has moved through the neckline by an
    ATR-scaled threshold.
    """

    if len(bars) < 12:
        return []
    recent = bars[-PATTERN_LOOKBACK_BARS:]
    points = swings(recent, PATTERN_SWING_WINDOW)
    patterns = [
        _double_pattern(recent, points, indicator, "low"),
        _double_pattern(recent, points, indicator, "high"),
        _head_shoulders(recent, points, indicator, inverse=True),
        _head_shoulders(recent, points, indicator, inverse=False),
        _triangle_breakout(recent, swings(recent, 1), indicator),
    ]
    return sorted(
        [pattern for pattern in patterns if pattern is not None],
        key=lambda pattern: pattern.completed_index,
        reverse=True,
    )


def bullish_pattern_confirmations(bars: list[Candle], indicator: IndicatorSet) -> list[str]:
    return [
        f"confirmed_{pattern.name}"
        for pattern in detect_chart_patterns(bars, indicator)
        if pattern.direction == "bullish" and pattern.state == "confirmed"
    ]


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
    return confirmations + bullish_pattern_confirmations(bars, indicator)


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
