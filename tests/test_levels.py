from __future__ import annotations

import pandas as pd

from crypto_strategy_analyst.levels import _interactions, detect_zones, merge_timeframe_zones
from crypto_strategy_analyst.structure import detect_confirmed_swings


def test_levels_are_zones_with_evidence(enriched):
    swings = detect_confirmed_swings(enriched)
    supports, resistances = detect_zones(enriched, swings, "4h")
    assert supports
    assert resistances
    for zone in [*supports, *resistances]:
        assert zone.lower_price <= zone.center_price <= zone.upper_price
        assert zone.touch_count >= 1
        assert zone.reaction_count >= 0
        assert zone.break_count >= 0
        assert zone.evidence
        assert 0 <= zone.strength_score <= 100


def test_multitimeframe_overlap_increases_strength(enriched):
    swings = detect_confirmed_swings(enriched)
    supports, _ = detect_zones(enriched, swings, "4h")
    zone = supports[0]
    duplicate = zone.model_copy(
        update={"timeframe": "1d", "strength_score": max(1, zone.strength_score - 5)}
    )
    merged = merge_timeframe_zones([zone, duplicate], float(enriched["close"].iloc[-1]))
    assert len(merged) == 1
    assert "+" in merged[0].timeframe
    assert merged[0].strength_score >= zone.strength_score
    assert merged[0].touch_count == max(zone.touch_count, duplicate.touch_count)
    assert merged[0].reaction_count == max(zone.reaction_count, duplicate.reaction_count)
    assert merged[0].break_count == max(zone.break_count, duplicate.break_count)


def test_adjacent_contacts_count_as_one_touch_episode():
    index = pd.date_range("2026-01-01", periods=30, freq="4h", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": [100.0] * 3 + [103.0] * 27,
            "high": [100.5] * 3 + [104.0] * 27,
            "low": [99.5] * 3 + [102.0] * 27,
            "close": [100.0] * 3 + [103.0] * 27,
            "atr14": [1.0] * 30,
        },
        index=index,
    )
    stats = _interactions(
        frame,
        lower=99.0,
        upper=101.0,
        level_type="support",
        cooldown_bars=6,
        reaction_atr_multiple=0.75,
        break_atr_multiple=0.25,
    )
    assert stats.touches == 1
    assert stats.reactions == 1
    assert stats.breaks == 0


def test_effective_break_is_scored_separately():
    index = pd.date_range("2026-01-01", periods=30, freq="4h", tz="UTC")
    close = [100.0] * 3 + [103.0] * 7 + [97.0] * 20
    frame = pd.DataFrame(
        {
            "open": close,
            "high": [value + 0.5 for value in close],
            "low": [value - 0.5 for value in close],
            "close": close,
            "atr14": [1.0] * 30,
        },
        index=index,
    )
    stats = _interactions(
        frame,
        lower=99.0,
        upper=101.0,
        level_type="support",
        cooldown_bars=6,
        reaction_atr_multiple=0.75,
        break_atr_multiple=0.25,
    )
    assert stats.touches == 1
    assert stats.reactions == 1
    assert stats.breaks >= 1
