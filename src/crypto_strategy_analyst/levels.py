"""Multi-source price zones with cooldown, invalidation and HTF priority."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

import numpy as np

from .config import LevelConfig
from .models import Candle, IndicatorSet, KeyLevel
from .structure import swings

TIMEFRAME_WEIGHT = {"1w": 35, "1d": 25, "4h": 15, "1h": 8, "15m": 4}


def _pivot_candidates(
    timeframe: str, bars: list[Candle], config: LevelConfig
) -> list[tuple[str, float, int, str]]:
    candidates = [
        ("support" if point.kind == "low" else "resistance", point.price, point.index, "swing")
        for point in swings(bars, config.swing_window)
    ]
    if bars:
        candidates += [
            ("support", min(bar.low for bar in bars[-40:]), len(bars) - 1, "range_boundary"),
            ("resistance", max(bar.high for bar in bars[-40:]), len(bars) - 1, "range_boundary"),
        ]
    return candidates


def _touches(
    bars: list[Candle],
    price: float,
    tolerance: float,
    cooldown: int,
    kind: str,
    reaction_distance: float,
) -> tuple[int, int, datetime]:
    indexes: list[int] = []
    for index, bar in enumerate(bars):
        if bar.low - tolerance <= price <= bar.high + tolerance and (
            not indexes or index - indexes[-1] >= cooldown
        ):
            indexes.append(index)
    last = bars[indexes[-1]].close_time if indexes else bars[-1].close_time
    reactions = sum(
        index + 1 < len(bars)
        and (
            bars[index + 1].high >= price + reaction_distance
            if kind == "support"
            else bars[index + 1].low <= price - reaction_distance
        )
        for index in indexes
    )
    return max(1, len(indexes)), reactions, last


def detect_levels(
    candles: dict[str, list[Candle]],
    indicators: dict[str, IndicatorSet],
    price: float,
    config: LevelConfig,
) -> list[KeyLevel]:
    raw: list[KeyLevel] = []
    for timeframe in ("1w", "1d", "4h", "1h"):
        bars = candles.get(timeframe, [])
        indicator = indicators.get(timeframe)
        if len(bars) < config.swing_window * 2 + 2 or indicator is None:
            continue
        tolerance = indicator.atr * config.zone_atr
        candidates = _pivot_candidates(timeframe, bars, config)
        candidates += [
            (
                "support" if indicator.ema20 <= price else "resistance",
                indicator.ema20,
                len(bars) - 1,
                "ema20",
            )
        ]
        round_unit = 10 ** max(0, len(str(int(price))) - 2)
        psychological = round(price / round_unit) * round_unit
        candidates.append(
            (
                "support" if psychological <= price else "resistance",
                psychological,
                len(bars) - 1,
                "psychological",
            )
        )
        for kind, level_price, _, source in candidates:
            broken = (
                kind == "resistance"
                and bars[-1].close > level_price + config.break_atr * indicator.atr
            )
            broken |= (
                kind == "support"
                and bars[-1].close < level_price - config.break_atr * indicator.atr
            )
            if broken:
                continue
            touches, reactions, reacted_at = _touches(
                bars,
                level_price,
                tolerance,
                config.touch_cooldown_bars,
                kind,
                indicator.atr * config.reaction_atr,
            )
            midpoint = float(level_price)
            raw.append(
                KeyLevel(
                    type=kind,
                    lower=max(1e-12, midpoint - tolerance),
                    upper=midpoint + tolerance,
                    midpoint=midpoint,
                    timeframe=timeframe,
                    strength=min(
                        100,
                        TIMEFRAME_WEIGHT[timeframe]
                        + touches * 12
                        + reactions * 5
                        + (8 if source == "range_boundary" else 0),
                    ),
                    touches=touches,
                    last_reaction_at=reacted_at,
                    sources=[f"{timeframe}_{source}"],
                    distance_percent=abs(midpoint / price - 1),
                    distance_atr=abs(midpoint - price) / max(indicator.atr, 1e-12),
                )
            )
    return merge_levels(raw, indicators.get("1d") or next(iter(indicators.values())), config)


def merge_levels(
    levels: list[KeyLevel], anchor: IndicatorSet, config: LevelConfig
) -> list[KeyLevel]:
    groups: dict[str, list[list[KeyLevel]]] = defaultdict(list)
    for level in sorted(
        levels, key=lambda item: (-TIMEFRAME_WEIGHT.get(item.timeframe, 0), -item.strength)
    ):
        group = next(
            (
                items
                for items in groups[level.type]
                if abs(np.mean([x.midpoint for x in items]) - level.midpoint)
                <= anchor.atr * config.merge_atr
            ),
            None,
        )
        if group is None:
            groups[level.type].append([level])
        else:
            group.append(level)
    result: list[KeyLevel] = []
    for kind_groups in groups.values():
        for items in kind_groups:
            best = max(
                items, key=lambda item: (TIMEFRAME_WEIGHT.get(item.timeframe, 0), item.strength)
            )
            result.append(
                best.model_copy(
                    update={
                        "lower": min(item.lower for item in items),
                        "upper": max(item.upper for item in items),
                        "midpoint": float(
                            np.average(
                                [item.midpoint for item in items],
                                weights=[TIMEFRAME_WEIGHT.get(item.timeframe, 1) for item in items],
                            )
                        ),
                        "strength": min(
                            100, max(item.strength for item in items) + 3 * (len(items) - 1)
                        ),
                        "touches": max(item.touches for item in items),
                        "sources": sorted({source for item in items for source in item.sources}),
                    }
                )
            )
    return sorted(result, key=lambda item: (abs(item.distance_percent), -item.strength))[:16]
