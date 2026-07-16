"""Deterministic technical indicators with no third-party TA dependency."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import IndicatorConfig
from .models import Candle, IndicatorSet


def _ema(values: pd.Series, period: int) -> pd.Series:
    return values.ewm(span=period, adjust=False, min_periods=1).mean()


def _sma(values: pd.Series, period: int) -> pd.Series:
    return values.rolling(period, min_periods=1).mean()


def _rsi(values: pd.Series, period: int) -> pd.Series:
    change = values.diff()
    gain = change.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-change.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    relative = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + relative)).fillna(50).clip(0, 100)


def _atr(frame: pd.DataFrame, period: int) -> pd.Series:
    previous = frame.close.shift(1)
    true_range = pd.concat(
        [frame.high - frame.low, (frame.high - previous).abs(), (frame.low - previous).abs()],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1 / period, adjust=False).mean()


def calculate_indicators(bars: list[Candle], config: IndicatorConfig) -> IndicatorSet | None:
    if len(bars) < max(
        config.ema_fast,
        config.ema_medium,
        config.ema_slow,
        config.sma_fast,
        config.sma_medium,
        config.sma_slow,
        config.atr_period,
        config.volume_period,
    ) + 2:
        return None
    frame = pd.DataFrame([bar.model_dump() for bar in bars])
    close = frame.close.astype(float)
    ema20 = _ema(close, config.ema_fast)
    ema50 = _ema(close, config.ema_medium)
    ema200 = _ema(close, config.ema_slow)
    sma_fast = _sma(close, config.sma_fast)
    sma_medium = _sma(close, config.sma_medium)
    sma_slow = _sma(close, config.sma_slow)
    rsi = _rsi(close, config.rsi_period)
    atr = _atr(frame, config.atr_period)
    macd = _ema(close, 12) - _ema(close, 26)
    macd_signal = _ema(macd, 9)
    histogram = macd - macd_signal
    volume_mean = frame.volume.rolling(config.volume_period, min_periods=1).mean()
    slope = ema20.iloc[-1] / ema20.iloc[-6] - 1 if len(ema20) >= 6 else 0
    alignment = (ema20.iloc[-1] / ema50.iloc[-1] - 1) * 400
    momentum = (close.iloc[-1] / close.iloc[-10] - 1) * 250 if len(close) >= 10 else 0
    strength = float(np.clip(50 + alignment + momentum + slope * 300, 0, 100))
    current_atr = max(float(atr.iloc[-1]), float(close.iloc[-1]) * 1e-6)
    return IndicatorSet(
        close=float(close.iloc[-1]),
        ema20=float(ema20.iloc[-1]),
        ema50=float(ema50.iloc[-1]),
        ema200=float(ema200.iloc[-1]),
        sma_fast=float(sma_fast.iloc[-1]),
        sma_medium=float(sma_medium.iloc[-1]),
        sma_slow=float(sma_slow.iloc[-1]),
        ema20_slope=float(slope),
        rsi=float(rsi.iloc[-1]),
        macd_line=float(macd.iloc[-1]),
        macd_signal=float(macd_signal.iloc[-1]),
        macd_histogram=float(histogram.iloc[-1]),
        macd_histogram_change=float(histogram.iloc[-1] - histogram.iloc[-2]),
        atr=current_atr,
        atr_percent=current_atr / float(close.iloc[-1]),
        volume_ratio=float(frame.volume.iloc[-1] / max(volume_mean.iloc[-1], 1e-12)),
        trend_strength=strength,
    )


def indicator_map(
    candles: dict[str, list[Candle]], config: IndicatorConfig
) -> dict[str, IndicatorSet]:
    return {
        timeframe: result
        for timeframe, bars in candles.items()
        if (result := calculate_indicators(bars, config)) is not None
    }
