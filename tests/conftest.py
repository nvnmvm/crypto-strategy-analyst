from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_analyst.indicators import add_indicators


def make_ohlcv(periods: int = 600, freq: str = "4h", seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.date_range("2022-01-01", periods=periods, freq=freq, tz="UTC")
    trend = np.linspace(100, 145, periods)
    cycle = np.sin(np.arange(periods) / 8) * 12 + np.sin(np.arange(periods) / 35) * 8
    noise = rng.normal(0, 0.7, periods)
    close = trend + cycle + noise
    open_price = np.r_[close[0], close[:-1]] + rng.normal(0, 0.35, periods)
    spread = rng.uniform(0.8, 2.0, periods)
    high = np.maximum(open_price, close) + spread
    low = np.minimum(open_price, close) - spread
    volume = 1000 + np.abs(np.sin(np.arange(periods) / 5)) * 500 + rng.uniform(0, 150, periods)
    return pd.DataFrame(
        {"open": open_price, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )


@pytest.fixture
def ohlcv() -> pd.DataFrame:
    return make_ohlcv()


@pytest.fixture
def enriched(ohlcv: pd.DataFrame) -> pd.DataFrame:
    return add_indicators(ohlcv)
