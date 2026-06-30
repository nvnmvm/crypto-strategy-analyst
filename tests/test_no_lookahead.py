from __future__ import annotations

import pandas as pd
import pandas.testing as pdt

from crypto_strategy_analyst.config import AppConfig
from crypto_strategy_analyst.indicators import add_indicators
from crypto_strategy_analyst.strategy import evaluate_setup_at_time, prepare_market_frames
from crypto_strategy_analyst.structure import detect_confirmed_swings


def test_future_prices_do_not_change_past_indicators(ohlcv):
    cutoff = 350
    original = add_indicators(ohlcv)
    modified = ohlcv.copy()
    modified.iloc[cutoff + 1 :, modified.columns.get_loc("close")] *= 10
    modified.iloc[cutoff + 1 :, modified.columns.get_loc("high")] *= 10
    changed = add_indicators(modified)
    pdt.assert_series_equal(
        original["ema20"].iloc[: cutoff + 1], changed["ema20"].iloc[: cutoff + 1]
    )
    pdt.assert_series_equal(
        original["rsi14"].iloc[: cutoff + 1], changed["rsi14"].iloc[: cutoff + 1]
    )


def test_swing_requires_right_side_confirmation(ohlcv):
    swings = detect_confirmed_swings(ohlcv, left=3, right=3)
    for swing in swings:
        assert swing.confirmed_at > swing.timestamp
    prefix = ohlcv.iloc[:400]
    prefix_swings = detect_confirmed_swings(prefix, left=3, right=3)
    full_visible = [point for point in swings if point.confirmed_at <= prefix.index[-1]]
    assert prefix_swings == full_visible


def test_future_multitimeframe_bars_do_not_change_historical_signal(market_frames):
    config = AppConfig()
    evaluated_at = (market_frames["1d"].index[220] + pd.Timedelta(days=1)).to_pydatetime()
    baseline = evaluate_setup_at_time(
        prepare_market_frames(market_frames, config),
        config,
        evaluated_at=evaluated_at,
    )
    modified = {timeframe: frame.copy() for timeframe, frame in market_frames.items()}
    durations = {
        "1d": pd.Timedelta(days=1),
        "4h": pd.Timedelta(hours=4),
        "1h": pd.Timedelta(hours=1),
    }
    cutoff = pd.Timestamp(evaluated_at)
    for timeframe, frame in modified.items():
        future = frame.index + durations[timeframe] > cutoff
        frame.loc[future, ["open", "high", "low", "close"]] *= 5
        frame.loc[future, "volume"] *= 10
    changed = evaluate_setup_at_time(
        prepare_market_frames(modified, config),
        config,
        evaluated_at=evaluated_at,
    )
    assert changed.decision == baseline.decision
    assert changed.trends == baseline.trends
    assert changed.supports == baseline.supports
    assert changed.resistances == baseline.resistances
