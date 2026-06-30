"""Support/resistance candidate extraction and zone merging."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .models import PriceZone
from .structure import SwingPoint


@dataclass(frozen=True, slots=True)
class CandidateLevel:
    price: float
    evidence: str
    timestamp: pd.Timestamp


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


def detect_zones(
    frame: pd.DataFrame,
    swings: list[SwingPoint],
    timeframe: str,
    *,
    merge_percent: float = 0.006,
) -> tuple[list[PriceZone], list[PriceZone]]:
    """Merge nearby evidence into support/resistance price zones."""

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
    touch_tolerance = tolerance * 0.75
    for cluster in clusters:
        center = sum(item.price for item in cluster) / len(cluster)
        lower = min(item.price for item in cluster) - tolerance * 0.35
        upper = max(item.price for item in cluster) + tolerance * 0.35
        touches_mask = (frame["low"] <= center + touch_tolerance) & (
            frame["high"] >= center - touch_tolerance
        )
        touch_count = max(1, int(touches_mask.iloc[-200:].sum()))
        touch_indices = frame.index[touches_mask]
        last_touch = pd.Timestamp(
            touch_indices[-1] if len(touch_indices) else cluster[-1].timestamp
        )
        methods = sorted({item.evidence for item in cluster})
        confluence = len({method.split("_")[0] for method in methods})
        strength = min(100.0, 12.0 + touch_count * 5.0 + len(methods) * 8.0 + confluence * 4.0)
        zone_type = "support" if center <= current_price else "resistance"
        zones.append(
            PriceZone(
                lower_price=round(lower, 8),
                upper_price=round(upper, 8),
                center_price=round(center, 8),
                level_type=zone_type,
                timeframe=timeframe,
                touch_count=touch_count,
                last_touch_time=last_touch.to_pydatetime(),
                strength_score=round(strength, 2),
                evidence=methods,
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
    """Merge overlapping timeframe zones and reward multi-timeframe confluence."""

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
            touch_count=previous.touch_count + zone.touch_count,
            last_touch_time=max(previous.last_touch_time, zone.last_touch_time),
            strength_score=min(100, max(previous.strength_score, zone.strength_score) + 10),
            evidence=evidence,
        )
    return merged
