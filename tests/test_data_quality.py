from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from crypto_strategy_analyst.analysis import analyze_frames_at_time
from crypto_strategy_analyst.config import AppConfig
from crypto_strategy_analyst.data import drop_incomplete_last_bar, validate_market_data
from crypto_strategy_analyst.models import QualityGrade


def test_valid_data_passes_quality_gate(ohlcv):
    quality = validate_market_data(ohlcv, "4h")
    assert quality.grade == QualityGrade.VALID
    assert quality.gap_count == 0


def test_gap_is_not_silently_neutral(ohlcv):
    gapped = ohlcv.drop(ohlcv.index[300])
    quality = validate_market_data(gapped, "4h")
    assert quality.grade == QualityGrade.DEGRADED
    assert quality.gap_count == 1


def test_gap_count_is_not_truncated_with_evidence_preview(ohlcv):
    positions = list(range(220, 262, 2))
    quality = validate_market_data(ohlcv.drop(ohlcv.index[positions]), "4h")
    assert quality.gap_count == len(positions)
    assert len(quality.missing_intervals) == 20


def test_duplicate_is_invalid(ohlcv):
    duplicated = ohlcv._append(ohlcv.iloc[[20]]).sort_index()
    quality = validate_market_data(duplicated, "4h")
    assert quality.grade == QualityGrade.INVALID


def test_open_candle_is_removed(ohlcv):
    last_open = ohlcv.index[-1]
    now = (last_open + (ohlcv.index[1] - ohlcv.index[0]) / 2).to_pydatetime().astimezone(UTC)
    completed = drop_incomplete_last_bar(ohlcv, "4h", now=now)
    assert len(completed) == len(ohlcv) - 1
    assert isinstance(now, datetime)


def test_gap_inside_strategy_lookback_forces_no_trade(market_frames, trading_rules):
    frames = {key: value.copy() for key, value in market_frames.items()}
    frames["4h"] = frames["4h"].drop(frames["4h"].index[-50])
    evaluated_at = (frames["4h"].index[-1] + pd.Timedelta(hours=4)).to_pydatetime()
    report = analyze_frames_at_time(
        "BTC/USDT",
        frames,
        AppConfig(),
        evaluated_at=evaluated_at,
        trading_rules=trading_rules,
    )
    assert report.signal.value == "no_trade"
    assert "required_market_data_incomplete" in report.warnings[-10:][0] or any(
        "required_market_data_incomplete" in warning for warning in report.warnings
    )
