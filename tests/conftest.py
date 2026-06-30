from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from crypto_strategy_analyst.indicators import add_indicators
from crypto_strategy_analyst.models import SymbolTradingRules


def make_ohlcv(
    periods: int = 600,
    freq: str = "4h",
    seed: int = 42,
    start: str = "2022-01-01",
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.date_range(start, periods=periods, freq=freq, tz="UTC")
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


@pytest.fixture
def market_frames() -> dict[str, pd.DataFrame]:
    return {
        "1d": make_ohlcv(periods=240, freq="1d", seed=1),
        "4h": make_ohlcv(periods=1_440, freq="4h", seed=2),
        "1h": make_ohlcv(periods=5_760, freq="1h", seed=3),
    }


@pytest.fixture
def trading_rules() -> SymbolTradingRules:
    return SymbolTradingRules(
        symbol="BTC/USDT",
        price_tick_size=0.01,
        quantity_step_size=0.00001,
        minimum_quantity=0.00001,
        maximum_quantity=1000,
        minimum_notional=5,
        fetched_at=datetime(2026, 7, 1, tzinfo=UTC),
        data_source="test fixture",
    )
