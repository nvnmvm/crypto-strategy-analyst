"""Deterministic multi-timeframe data-freshness checks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from .data import INTERVAL_SECONDS
from .models import DataFreshnessItem, FreshnessStatus


@dataclass(frozen=True, slots=True)
class DataFreshnessResult:
    """Freshness details for every required timeframe."""

    timeframes: dict[str, DataFreshnessItem]

    @property
    def is_fresh(self) -> bool:
        return all(item.status == FreshnessStatus.FRESH for item in self.timeframes.values())

    @property
    def blockers(self) -> list[str]:
        return [
            f"data_freshness_{timeframe}_{item.status.value}"
            for timeframe, item in self.timeframes.items()
            if item.status != FreshnessStatus.FRESH
        ]


def _utc(value: datetime) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    return timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")


def expected_latest_close(timeframe: str, evaluation_time: datetime) -> datetime:
    """Return the required latest close for a shared strategy evaluation time."""

    evaluation = _utc(evaluation_time)
    if timeframe == "1d":
        return evaluation.normalize().to_pydatetime()
    if timeframe in {"4h", "1h"}:
        return evaluation.to_pydatetime()
    raise ValueError(f"unsupported timeframe: {timeframe}")


def check_data_freshness(
    frames: Mapping[str, pd.DataFrame],
    evaluation_time: datetime,
    required_timeframes: Sequence[str],
) -> DataFreshnessResult:
    """Compare actual completed closes with the close required at evaluation_time."""

    results: dict[str, DataFreshnessItem] = {}
    for timeframe in required_timeframes:
        expected = _utc(expected_latest_close(timeframe, evaluation_time))
        frame = frames.get(timeframe)
        if frame is None or frame.empty:
            results[timeframe] = DataFreshnessItem(
                status=FreshnessStatus.MISSING,
                expected_latest_close=expected.to_pydatetime(),
                actual_latest_close=None,
                staleness_seconds=0,
                reason="required timeframe has no completed candles",
            )
            continue
        try:
            index = pd.DatetimeIndex(frame.index)
            if index.hasnans or index.duplicated().any() or not index.is_monotonic_increasing:
                raise ValueError("invalid timestamp index")
            index = (
                index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
            )
            close_times = index + pd.to_timedelta(INTERVAL_SECONDS[timeframe], unit="s")
            eligible = close_times[close_times <= expected]
            if len(eligible) == 0:
                results[timeframe] = DataFreshnessItem(
                    status=FreshnessStatus.MISSING,
                    expected_latest_close=expected.to_pydatetime(),
                    actual_latest_close=None,
                    staleness_seconds=0,
                    reason="no candle closes at or before the required time",
                )
                continue
            actual = eligible[-1]
        except (KeyError, TypeError, ValueError) as exc:
            results[timeframe] = DataFreshnessItem(
                status=FreshnessStatus.INVALID,
                expected_latest_close=expected.to_pydatetime(),
                actual_latest_close=None,
                staleness_seconds=0,
                reason=f"cannot determine latest close: {exc}",
            )
            continue
        staleness = max(0.0, (expected - actual).total_seconds())
        if actual == expected:
            status, reason = FreshnessStatus.FRESH, None
        elif actual < expected:
            status, reason = FreshnessStatus.STALE, "latest completed candle is older than required"
        else:  # pragma: no cover - eligible closes cannot be newer than expected
            status, reason = FreshnessStatus.INVALID, "latest close is after evaluation time"
        results[timeframe] = DataFreshnessItem(
            status=status,
            expected_latest_close=expected.to_pydatetime(),
            actual_latest_close=actual.to_pydatetime(),
            staleness_seconds=staleness,
            reason=reason,
        )
    return DataFreshnessResult(timeframes=results)
