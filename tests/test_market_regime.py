from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import crypto_strategy_analyst.regime as regime_module
from crypto_strategy_analyst.models import MarketRegime
from crypto_strategy_analyst.regime import classify_market_regime
from crypto_strategy_analyst.structure import SwingPoint


def _frame(periods: int, freq: str, close: np.ndarray, ema200: np.ndarray) -> pd.DataFrame:
    index = pd.date_range("2020-01-01", periods=periods, freq=freq, tz="UTC")
    atr = np.full(periods, 2.0)
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "ema20": close * 0.99,
            "ema50": np.linspace(float(close[0]), float(close[-1]) * 0.98, periods),
            "ema200": ema200,
            "atr14": atr,
        },
        index=index,
    )


def _four(close: float, *, reclaim: bool = True) -> pd.DataFrame:
    values = np.full(80, close)
    frame = _frame(80, "4h", values, np.full(80, close))
    frame["ema20"] = close * (0.98 if reclaim else 1.02)
    frame["ema50"] = close * (0.97 if reclaim else 1.03)
    return frame


def _swings(frame: pd.DataFrame, *, higher: bool) -> list[SwingPoint]:
    first, second = frame.index[-30], frame.index[-10]
    low_1, low_2 = (80.0, 90.0) if higher else (90.0, 80.0)
    return [
        SwingPoint(first, low_1, "low", frame.index[-27]),
        SwingPoint(second, low_2, "low", frame.index[-7]),
        SwingPoint(first, 120.0, "high", frame.index[-27]),
        SwingPoint(second, 130.0 if higher else 110.0, "high", frame.index[-7]),
    ]


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("bull", MarketRegime.BULL_TREND),
        ("pullback", MarketRegime.BULL_PULLBACK),
        ("sideways", MarketRegime.SIDEWAYS_RANGE),
        ("capitulation", MarketRegime.BEAR_CAPITULATION),
        ("recovery", MarketRegime.BEAR_RECOVERY),
        ("bear", MarketRegime.BEAR_TREND),
    ],
)
def test_six_market_regimes_are_deterministic(monkeypatch, kind, expected):
    periods = 365
    if kind == "bull":
        close = np.linspace(100, 200, periods)
        ema200 = np.linspace(90, 150, periods)
        four = _four(200)
        higher = True
    elif kind == "pullback":
        close = np.r_[np.linspace(100, 180, periods - 30), np.linspace(180, 150, 30)]
        ema200 = np.linspace(100, 145, periods)
        four = _four(150, reclaim=False)
        higher = False
    elif kind == "sideways":
        close = np.full(periods, 100.0)
        ema200 = np.full(periods, 100.0)
        four = _four(100)
        higher = False
    elif kind == "capitulation":
        close = np.r_[np.full(periods - 6, 120.0), [115, 108, 100, 93, 86, 80]]
        ema200 = np.full(periods, 110.0)
        four = _four(80, reclaim=False)
        higher = False
    elif kind == "recovery":
        close = np.r_[np.full(periods - 20, 120.0), np.linspace(75, 82, 20)]
        ema200 = np.full(periods, 110.0)
        four = _four(82)
        higher = True
    else:
        close = np.linspace(120, 80, periods)
        ema200 = np.linspace(115, 100, periods)
        four = _four(80, reclaim=False)
        higher = False
    daily = _frame(periods, "1d", close, ema200)
    if kind == "capitulation":
        daily.loc[daily.index[-6:], "atr14"] = 10.0
    monkeypatch.setattr(
        regime_module,
        "detect_confirmed_swings",
        lambda frame, left=3, right=3: _swings(frame, higher=higher),
    )
    first = classify_market_regime(daily, four)
    second = classify_market_regime(daily.copy(), four.copy())
    assert first.regime == expected
    assert first == second
