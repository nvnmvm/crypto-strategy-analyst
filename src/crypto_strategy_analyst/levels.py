"""Support/resistance extraction with de-duplicated price interactions."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .models import PriceZone
from .structure import SwingPoint


@dataclass(frozen=True, slots=True)
class CandidateLevel:
    price: float
    evidence: str
    timestamp: pd.Timestamp


@dataclass(frozen=True, slots=True)
class ZoneInteractions:
    touches: int
    reactions: int
    breaks: int
    last_touch: pd.Timestamp


def _candidates(frame: pd.DataFrame, swings: list[SwingPoint]) -> list[CandidateLevel]:
    candidates = [
        CandidateLevel(point.price, f"confirmed_swing_{point.kind}", point.timestamp)
        for point in swings[-30:]
    ]
    latest = frame.iloc[-1]
    timestamp = pd.Timestamp(frame.index[-1])
    for name in ("ema20", "ema50", "ema200"):
        value = latest.get(name)
        if pd.notna(value):
            candidates.append(CandidateLevel(float(value), f"dynamic_{name}", timestamp))
    recent = frame.iloc[-100:]
    high_idx, low_idx = recent["high"].idxmax(), recent["low"].idxmin()
    high, low = float(recent.loc[high_idx, "high"]), float(recent.loc[low_idx, "low"])
    candidates.extend(
        [
            CandidateLevel(high, "previous_100_bar_high", pd.Timestamp(high_idx)),
            CandidateLevel(low, "previous_100_bar_low", pd.Timestamp(low_idx)),
        ]
    )
    span = high - low
    if span > 0:
        for ratio in (0.382, 0.5, 0.618):
            candidates.append(
                CandidateLevel(high - span * ratio, f"fibonacci_{ratio:.3f}", timestamp)
            )
    return [candidate for candidate in candidates if candidate.price > 0]


def _cooldown_events(mask: pd.Series | np.ndarray, cooldown_bars: int) -> list[int]:
    events: list[int] = []
    last_event = -cooldown_bars
    was_active = False
    values = mask.to_numpy(dtype=bool) if isinstance(mask, pd.Series) else mask.astype(bool)
    for position, active in enumerate(values):
        if active and not was_active and position - last_event >= cooldown_bars:
            events.append(position)
            last_event = position
        was_active = active
    return events


def _interactions(
    frame: pd.DataFrame,
    *,
    lower: float,
    upper: float,
    level_type: str,
    cooldown_bars: int,
    reaction_atr_multiple: float,
    break_atr_multiple: float,
) -> ZoneInteractions:
    recent = frame.iloc[-200:]
    lows = recent["low"].to_numpy(dtype=float)
    highs = recent["high"].to_numpy(dtype=float)
    closes = recent["close"].to_numpy(dtype=float)
    atr_values = recent["atr14"].to_numpy(dtype=float)
    contact_mask = (lows <= upper) & (highs >= lower)
    touch_positions = _cooldown_events(contact_mask, cooldown_bars)
    reactions = 0
    for position in touch_positions:
        atr = atr_values[position]
        future_start = position + 1
        future_end = min(len(recent), position + cooldown_bars + 1)
        if future_start >= future_end or not np.isfinite(atr):
            continue
        if (
            level_type == "support"
            and float(np.max(highs[future_start:future_end])) - upper
            >= atr * reaction_atr_multiple
        ):
            reactions += 1
        if (
            level_type == "resistance"
            and lower - float(np.min(lows[future_start:future_end]))
            >= atr * reaction_atr_multiple
        ):
            reactions += 1

    finite_atr = atr_values[np.isfinite(atr_values)]
    fallback_atr = float(finite_atr[-1]) if len(finite_atr) else 0.0
    atr_values = np.where(np.isfinite(atr_values), atr_values, fallback_atr)
    if level_type == "support":
        break_mask = closes < lower - atr_values * break_atr_multiple
    else:
        break_mask = closes > upper + atr_values * break_atr_multiple
    breaks = len(_cooldown_events(break_mask, cooldown_bars))
    last_touch = (
        pd.Timestamp(recent.index[touch_positions[-1]])
        if touch_positions
        else pd.Timestamp(recent.index[-1])
    )
    return ZoneInteractions(
        touches=max(1, len(touch_positions)),
        reactions=reactions,
        breaks=breaks,
        last_touch=last_touch,
    )


def detect_zones(
    frame: pd.DataFrame,
    swings: list[SwingPoint],
    timeframe: str,
    *,
    merge_percent: float = 0.006,
    touch_cooldown_bars: int = 6,
    reaction_atr_multiple: float = 0.75,
    break_atr_multiple: float = 0.25,
) -> tuple[list[PriceZone], list[PriceZone]]:
    """Merge nearby evidence and score independent touch/reaction/break episodes."""

    current_price = float(frame["close"].iloc[-1])
    atr = float(frame["atr14"].iloc[-1])
    tolerance = max(current_price * merge_percent, atr * 0.35)
    candidates = sorted(_candidates(frame, swings), key=lambda item: item.price)
    clusters: list[list[CandidateLevel]] = []
    for candidate in candidates:
        if not clusters:
            clusters.append([candidate])
            continue
        center = sum(item.price for item in clusters[-1]) / len(clusters[-1])
        if abs(candidate.price - center) <= tolerance:
            clusters[-1].append(candidate)
        else:
            clusters.append([candidate])

    zones: list[PriceZone] = []
    for cluster in clusters:
        center = sum(item.price for item in cluster) / len(cluster)
        lower = min(item.price for item in cluster) - tolerance * 0.35
        upper = max(item.price for item in cluster) + tolerance * 0.35
        level_type = "support" if center <= current_price else "resistance"
        stats = _interactions(
            frame,
            lower=lower,
            upper=upper,
            level_type=level_type,
            cooldown_bars=touch_cooldown_bars,
            reaction_atr_multiple=reaction_atr_multiple,
            break_atr_multiple=break_atr_multiple,
        )
        methods = sorted({item.evidence for item in cluster})
        confluence = len({method.split("_")[0] for method in methods})
        strength = min(
            100.0,
            max(
                0.0,
                10.0
                + stats.touches * 4.0
                + stats.reactions * 10.0
                - stats.breaks * 12.0
                + len(methods) * 7.0
                + confluence * 4.0,
            ),
        )
        evidence = [
            *methods,
            f"independent_touches:{stats.touches}",
            f"effective_reactions:{stats.reactions}",
            f"effective_breaks:{stats.breaks}",
        ]
        zones.append(
            PriceZone(
                lower_price=round(lower, 8),
                upper_price=round(upper, 8),
                center_price=round(center, 8),
                level_type=level_type,
                timeframe=timeframe,
                touch_count=stats.touches,
                reaction_count=stats.reactions,
                break_count=stats.breaks,
                last_touch_time=stats.last_touch.to_pydatetime(),
                strength_score=round(strength, 2),
                evidence=evidence,
            )
        )
    supports = sorted(
        (zone for zone in zones if zone.level_type == "support"),
        key=lambda zone: zone.center_price,
        reverse=True,
    )
    resistances = sorted(
        (zone for zone in zones if zone.level_type == "resistance"),
        key=lambda zone: zone.center_price,
    )
    return supports[:8], resistances[:8]


def merge_timeframe_zones(zones: list[PriceZone], current_price: float) -> list[PriceZone]:
    """Merge overlaps without counting the same price behavior once per timeframe."""

    if not zones:
        return []
    ordered = sorted(zones, key=lambda zone: zone.center_price)
    merged: list[PriceZone] = []
    for zone in ordered:
        if not merged or zone.lower_price > merged[-1].upper_price:
            merged.append(zone.model_copy(deep=True))
            continue
        previous = merged[-1]
        evidence = sorted(set(previous.evidence + zone.evidence + [f"timeframe_{zone.timeframe}"]))
        timeframes = sorted(set(previous.timeframe.split("+") + zone.timeframe.split("+")))
        lower, upper = (
            min(previous.lower_price, zone.lower_price),
            max(previous.upper_price, zone.upper_price),
        )
        center = (previous.center_price + zone.center_price) / 2
        merged[-1] = PriceZone(
            lower_price=lower,
            upper_price=upper,
            center_price=center,
            level_type="support" if center <= current_price else "resistance",
            timeframe="+".join(timeframes),
            touch_count=max(previous.touch_count, zone.touch_count),
            reaction_count=max(previous.reaction_count, zone.reaction_count),
            break_count=max(previous.break_count, zone.break_count),
            last_touch_time=max(previous.last_touch_time, zone.last_touch_time),
            strength_score=min(100, max(previous.strength_score, zone.strength_score) + 10),
            evidence=evidence,
        )
    return merged
