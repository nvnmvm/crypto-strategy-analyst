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


@dataclass(frozen=True, slots=True)
class SetupEvaluation:
    evaluated_at: datetime
    frames: dict[str, pd.DataFrame]
    trends: dict[str, Trend]
    indicators: dict[str, IndicatorSnapshot]
    supports: list[PriceZone]
    resistances: list[PriceZone]
    decision: SignalDecision


def prepare_market_frames(
    frames: Mapping[str, pd.DataFrame],
    config: AppConfig,
) -> dict[str, pd.DataFrame]:
    """Calculate past-only indicators once for all required timeframes."""

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
    evaluated_at: datetime,
    *,
    history_limit: int,
) -> pd.DataFrame:
    """Return only candles whose close time is at or before evaluated_at."""

    timestamp = pd.Timestamp(evaluated_at)
    timestamp = (
        timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")
    )
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
    evaluated_at: datetime | None = None,
    risk_state: RiskState | None = None,
    data_is_complete: bool = True,
) -> SetupEvaluation:
    """Evaluate one setup identically for current-time analysis and historical replay."""

    as_of = evaluated_at or datetime.now(UTC)
    visible_frames: dict[str, pd.DataFrame] = {}
    trends: dict[str, Trend] = {}
    indicators: dict[str, IndicatorSnapshot] = {}
    timeframe_zones: list[PriceZone] = []
    for timeframe in REQUIRED_TIMEFRAMES:
        visible = closed_bars_at(
            prepared_frames[timeframe],
            timeframe,
            as_of,
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
        evaluated_at=pd.Timestamp(as_of).to_pydatetime(),
        frames=visible_frames,
        trends=trends,
        indicators=indicators,
        supports=supports,
        resistances=resistances,
        decision=decision,
    )
