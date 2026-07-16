"""Compact, explainable RSI/MACD/EMA/SMA technical diagnostics."""

from __future__ import annotations

import numpy as np

from .config import IndicatorConfig
from .models import IndicatorSet


def _moving_average_state(price: float, fast: float, medium: float, slow: float) -> str:
    if price > fast > medium > slow:
        return "bullish"
    if price < fast < medium < slow:
        return "bearish"
    return "mixed"


def _rsi_state(rsi: float) -> str:
    if rsi <= 30:
        return "oversold"
    if rsi < 45:
        return "weak"
    if rsi <= 55:
        return "neutral"
    if rsi < 70:
        return "bullish"
    return "overbought"


def _macd_state(indicator: IndicatorSet) -> str:
    if indicator.macd_line > indicator.macd_signal and indicator.macd_histogram >= 0:
        return "strengthening" if indicator.macd_histogram_change >= 0 else "bullish"
    if indicator.macd_line < indicator.macd_signal and indicator.macd_histogram <= 0:
        return "weakening" if indicator.macd_histogram_change <= 0 else "bearish"
    return "mixed"


def _vote(state: str, bullish: set[str], bearish: set[str]) -> tuple[int, int]:
    return (int(state in bullish), int(state in bearish))


def analyze_indicator_set(
    indicator: IndicatorSet, config: IndicatorConfig
) -> dict[str, float | int | str | dict[str, float | int | str | list[int]]]:
    """Explain the four primary technical inputs without creating a trade signal.

    The output intentionally separates a trend-following reading (EMA/SMA), a
    momentum reading (MACD), and an oscillator state (RSI).  Oversold and
    overbought are observations rather than standalone reversal calls.
    """

    ema_state = _moving_average_state(
        indicator.close, indicator.ema20, indicator.ema50, indicator.ema200
    )
    sma_state = _moving_average_state(
        indicator.close, indicator.sma_fast, indicator.sma_medium, indicator.sma_slow
    )
    rsi_state = _rsi_state(indicator.rsi)
    macd_state = _macd_state(indicator)
    votes = [
        _vote(ema_state, {"bullish"}, {"bearish"}),
        _vote(sma_state, {"bullish"}, {"bearish"}),
        _vote(rsi_state, {"bullish"}, {"weak"}),
        _vote(macd_state, {"bullish", "strengthening"}, {"bearish", "weakening"}),
    ]
    bullish_votes = sum(item[0] for item in votes)
    bearish_votes = sum(item[1] for item in votes)
    if bullish_votes >= 3 and not bearish_votes:
        bias = "bullish"
    elif bearish_votes >= 3 and not bullish_votes:
        bias = "bearish"
    elif bullish_votes > bearish_votes:
        bias = "bullish_lean"
    elif bearish_votes > bullish_votes:
        bias = "bearish_lean"
    else:
        bias = "mixed"
    score_delta = (
        20 * (ema_state == "bullish")
        - 20 * (ema_state == "bearish")
        + 15 * (sma_state == "bullish")
        - 15 * (sma_state == "bearish")
        + 10 * (rsi_state == "bullish")
        - 10 * (rsi_state == "weak")
        + 15 * (macd_state in {"bullish", "strengthening"})
        - 15 * (macd_state in {"bearish", "weakening"})
    )
    score = float(np.clip(50 + score_delta, 0, 100))
    return {
        "close": indicator.close,
        "bias": bias,
        "confluence_score": score,
        "bullish_votes": bullish_votes,
        "bearish_votes": bearish_votes,
        "ema": {
            "periods": [config.ema_fast, config.ema_medium, config.ema_slow],
            "fast": indicator.ema20,
            "medium": indicator.ema50,
            "slow": indicator.ema200,
            "state": ema_state,
        },
        "sma": {
            "periods": [config.sma_fast, config.sma_medium, config.sma_slow],
            "fast": indicator.sma_fast,
            "medium": indicator.sma_medium,
            "slow": indicator.sma_slow,
            "state": sma_state,
        },
        "rsi": {"period": config.rsi_period, "value": indicator.rsi, "state": rsi_state},
        "macd": {
            "fast_period": 12,
            "slow_period": 26,
            "signal_period": 9,
            "line": indicator.macd_line,
            "signal": indicator.macd_signal,
            "histogram": indicator.macd_histogram,
            "histogram_change": indicator.macd_histogram_change,
            "state": macd_state,
        },
        "atr": {
            "period": config.atr_period,
            "value": indicator.atr,
            "percent": indicator.atr_percent,
        },
        "volume": {
            "period": config.volume_period,
            "ratio": indicator.volume_ratio,
            "state": "expanding"
            if indicator.volume_ratio >= 1.15
            else "contracting"
            if indicator.volume_ratio < 0.85
            else "normal",
        },
    }


def analyze_indicators(
    indicators: dict[str, IndicatorSet], config: IndicatorConfig
) -> dict[str, dict[str, float | int | str | dict[str, float | int | str | list[int]]]]:
    return {
        timeframe: analyze_indicator_set(indicator, config)
        for timeframe, indicator in indicators.items()
    }
