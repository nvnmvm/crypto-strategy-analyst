from __future__ import annotations

import numpy as np

from crypto_strategy_analyst.indicators import add_indicators, snapshot


def test_indicators_are_finite_and_bounded(ohlcv):
    result = add_indicators(ohlcv)
    latest = snapshot(result)
    assert 0 <= latest.rsi14 <= 100
    assert latest.atr14 > 0
    assert latest.ema20 > 0
    assert latest.volume_ratio >= 0
    numeric = result.iloc[-1][["ema20", "ema50", "ema200", "rsi14", "macd", "atr14"]]
    assert np.isfinite(numeric.to_numpy(dtype=float)).all()


def test_optional_adx_is_explicitly_unavailable(ohlcv):
    result = add_indicators(ohlcv, enable_adx=False)
    assert snapshot(result, enable_adx=False).adx14 == "not_available"
