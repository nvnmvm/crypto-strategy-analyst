from __future__ import annotations

from datetime import UTC, datetime

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
