"""Past-only technical indicator calculations."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .errors import InsufficientDataError
from .models import IndicatorSnapshot

REQUIRED_COLUMNS = {"open", "high", "low", "close", "volume"}


def _wilder(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def add_indicators(frame: pd.DataFrame, *, enable_adx: bool = True) -> pd.DataFrame:
    """Add EMA, RSI, MACD, ATR, optional ADX, and volume ratio using past bars only."""

    if not REQUIRED_COLUMNS.issubset(frame.columns):
        raise ValueError(
            f"required columns missing: {sorted(REQUIRED_COLUMNS - set(frame.columns))}"
        )
    if len(frame) < 200:
        raise InsufficientDataError("at least 200 bars are required for EMA200")
    result = frame.copy()
    close = result["close"].astype(float)
    for period in (20, 50, 200):
        result[f"ema{period}"] = close.ewm(span=period, adjust=False, min_periods=period).mean()

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    average_gain = _wilder(gain, 14)
    average_loss = _wilder(loss, 14)
    rs = average_gain / average_loss.replace(0, np.nan)
    result["rsi14"] = (100 - 100 / (1 + rs)).clip(0, 100)
    result.loc[(average_loss == 0) & (average_gain > 0), "rsi14"] = 100.0
    result.loc[(average_loss == 0) & (average_gain == 0), "rsi14"] = 50.0

    ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
    result["macd"] = ema12 - ema26
    result["macd_signal"] = result["macd"].ewm(span=9, adjust=False, min_periods=9).mean()
    result["macd_histogram"] = result["macd"] - result["macd_signal"]

    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            result["high"] - result["low"],
            (result["high"] - previous_close).abs(),
            (result["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    result["atr14"] = _wilder(true_range, 14)
    result["volume_sma20"] = result["volume"].rolling(20, min_periods=20).mean()
    result["volume_ratio"] = result["volume"] / result["volume_sma20"].replace(0, np.nan)

    if enable_adx:
        up_move = result["high"].diff()
        down_move = -result["low"].diff()
        plus_dm = pd.Series(
            np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=result.index
        )
        minus_dm = pd.Series(
            np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=result.index
        )
        atr = result["atr14"].replace(0, np.nan)
        plus_di = 100 * _wilder(plus_dm, 14) / atr
        minus_di = 100 * _wilder(minus_dm, 14) / atr
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        result["adx14"] = _wilder(dx, 14).clip(0, 100)
    else:
        result["adx14"] = np.nan
    return result.replace([np.inf, -np.inf], np.nan)


def snapshot(frame: pd.DataFrame, *, enable_adx: bool = True) -> IndicatorSnapshot:
    """Create a finite, typed snapshot from the latest completed bar."""

    row = frame.iloc[-1]
    required = [
        "close",
        "ema20",
        "ema50",
        "ema200",
        "rsi14",
        "macd",
        "macd_signal",
        "macd_histogram",
        "atr14",
        "volume_ratio",
    ]
    if row[required].isna().any():
        missing = [name for name in required if pd.isna(row[name])]
        raise InsufficientDataError(f"latest indicators are unavailable: {missing}")
    adx: float | str
    adx = float(row["adx14"]) if enable_adx and pd.notna(row["adx14"]) else "not_available"
    return IndicatorSnapshot(
        close=float(row["close"]),
        ema20=float(row["ema20"]),
        ema50=float(row["ema50"]),
        ema200=float(row["ema200"]),
        rsi14=float(row["rsi14"]),
        macd=float(row["macd"]),
        macd_signal=float(row["macd_signal"]),
        macd_histogram=float(row["macd_histogram"]),
        atr14=float(row["atr14"]),
        adx14=adx,
        volume_ratio=float(row["volume_ratio"]),
    )
