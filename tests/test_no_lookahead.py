from __future__ import annotations

import pandas.testing as pdt

from crypto_strategy_analyst.indicators import add_indicators
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
