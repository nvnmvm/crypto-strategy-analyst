"""Single multi-timeframe strategy evaluator used by live analysis and backtests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd

from .config import AppConfig
from .data import INTERVAL_SECONDS
from .errors import InsufficientDataError
from .indicators import add_indicators, snapshot
from .levels import detect_zones, merge_timeframe_zones
from .models import IndicatorSnapshot, PriceZone, Trend
from .risk import RiskState
from .signal import SignalDecision, generate_signal
from .structure import classify_trend, detect_confirmed_swings

REQUIRED_TIMEFRAMES = ("1d", "4h", "1h")
DECISION_TIMEFRAME = "4h"


@dataclass(frozen=True, slots=True)
class SetupEvaluation:
    requested_at: datetime
    evaluation_time: datetime
    evaluation_timeframe: str
    time_alignment_applied: bool
    frames: dict[str, pd.DataFrame]
    trends: dict[str, Trend]
    indicators: dict[str, IndicatorSnapshot]
    supports: list[PriceZone]
    resistances: list[PriceZone]
    decision: SignalDecision

    @property
    def evaluated_at(self) -> datetime:
        """Backward-compatible alias for the common strategy evaluation time."""

        return self.evaluation_time


def _as_utc_timestamp(value: datetime) -> pd.Timestamp:
    """Normalize a naive-or-aware datetime to an aware UTC timestamp."""

    timestamp = pd.Timestamp(value)
    return timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")


def align_evaluation_time(
    requested_at: datetime,
    decision_timeframe: str = DECISION_TIMEFRAME,
) -> datetime:
    """Align a request to the latest completed decision-candle close.

    DataFrame indices are candle open times. For the 4h decision timeframe, a
    candle opened at 12:00 closes at 16:00. Exact UTC boundaries are treated as
    completed close instants, so 16:00 aligns to 16:00 while 15:30 aligns to
    12:00. All strategy inputs are subsequently clipped to this shared instant.
    """

    if decision_timeframe != DECISION_TIMEFRAME:
        raise ValueError(f"unsupported decision timeframe: {decision_timeframe}")
    requested = _as_utc_timestamp(requested_at)
    return requested.floor("4h").to_pydatetime()


def prepare_market_frames(
    frames: Mapping[str, pd.DataFrame],
    config: AppConfig,
) -> dict[str, pd.DataFrame]:
    """Calculate past-only indicators for frames indexed by candle open time."""

    missing = set(REQUIRED_TIMEFRAMES) - set(frames)
    if missing:
        raise InsufficientDataError(f"missing required timeframes: {sorted(missing)}")
    prepared: dict[str, pd.DataFrame] = {}
    for timeframe in REQUIRED_TIMEFRAMES:
        frame = frames[timeframe].copy().sort_index()
        if frame.index.tz is None:
            frame.index = frame.index.tz_localize("UTC")
        else:
            frame.index = frame.index.tz_convert("UTC")
        prepared[timeframe] = add_indicators(
            frame,
            enable_adx=config.strategy.enable_adx,
        )
    return prepared


def closed_bars_at(
    frame: pd.DataFrame,
    timeframe: str,
    evaluation_time: datetime,
    *,
    history_limit: int,
) -> pd.DataFrame:
    """Return candles whose ``open time + duration`` is at most evaluation_time."""

    timestamp = _as_utc_timestamp(evaluation_time)
    close_times = frame.index + pd.Timedelta(seconds=INTERVAL_SECONDS[timeframe])
    visible = frame.loc[close_times <= timestamp].tail(history_limit).copy()
    if len(visible) < 210:
        raise InsufficientDataError(
            f"{timeframe} has only {len(visible)} completed bars at {timestamp.isoformat()}"
        )
    return visible


def evaluate_setup_at_time(
    prepared_frames: Mapping[str, pd.DataFrame],
    config: AppConfig,
    *,
    requested_at: datetime | None = None,
    evaluated_at: datetime | None = None,
    risk_state: RiskState | None = None,
    data_is_complete: bool = True,
) -> SetupEvaluation:
    """Evaluate one setup after aligning every timeframe to one completed 4h close.

    ``requested_at`` is the caller's wall-clock or replay request. The legacy
    ``evaluated_at`` keyword remains an alias for compatibility. Every frame is
    indexed by candle open time and is clipped using its explicit close time.
    """

    if requested_at is not None and evaluated_at is not None:
        raise ValueError("pass only one of requested_at or evaluated_at")
    requested = requested_at or evaluated_at or datetime.now(UTC)
    requested_timestamp = _as_utc_timestamp(requested)
    evaluation_time = align_evaluation_time(requested_timestamp.to_pydatetime())
    visible_frames: dict[str, pd.DataFrame] = {}
    trends: dict[str, Trend] = {}
    indicators: dict[str, IndicatorSnapshot] = {}
    timeframe_zones: list[PriceZone] = []
    for timeframe in REQUIRED_TIMEFRAMES:
        visible = closed_bars_at(
            prepared_frames[timeframe],
            timeframe,
            evaluation_time,
            history_limit=config.market.history_limit,
        )
        visible_frames[timeframe] = visible
        swings = detect_confirmed_swings(
            visible,
            left=config.strategy.swing_left,
            right=config.strategy.swing_right,
        )
        trends[timeframe] = classify_trend(visible, swings)
        indicators[timeframe] = snapshot(visible, enable_adx=config.strategy.enable_adx)
        supports, resistances = detect_zones(
            visible,
            swings,
            timeframe,
            merge_percent=config.strategy.level_merge_percent,
            touch_cooldown_bars=config.strategy.touch_cooldown_bars,
            reaction_atr_multiple=config.strategy.reaction_atr_multiple,
            break_atr_multiple=config.strategy.break_atr_multiple,
        )
        timeframe_zones.extend([*supports[:5], *resistances[:5]])

    current_price = float(visible_frames["4h"]["close"].iloc[-1])
    merged = merge_timeframe_zones(timeframe_zones, current_price)
    supports = sorted(
        (zone for zone in merged if zone.level_type == "support"),
        key=lambda zone: zone.center_price,
        reverse=True,
    )[:8]
    resistances = sorted(
        (zone for zone in merged if zone.level_type == "resistance"),
        key=lambda zone: zone.center_price,
    )[:8]
    decision = generate_signal(
        daily_trend=trends["1d"],
        four_hour_trend=trends["4h"],
        one_hour_frame=visible_frames["1h"],
        four_hour_frame=visible_frames["4h"],
        supports=supports,
        resistances=resistances,
        data_is_complete=data_is_complete,
        config=config,
        risk_state=risk_state,
    )
    return SetupEvaluation(
        requested_at=requested_timestamp.to_pydatetime(),
        evaluation_time=evaluation_time,
        evaluation_timeframe=DECISION_TIMEFRAME,
        time_alignment_applied=requested_timestamp != _as_utc_timestamp(evaluation_time),
        frames=visible_frames,
        trends=trends,
        indicators=indicators,
        supports=supports,
        resistances=resistances,
        decision=decision,
    )
