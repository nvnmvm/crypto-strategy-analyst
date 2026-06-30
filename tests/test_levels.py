from __future__ import annotations

from crypto_strategy_analyst.levels import detect_zones, merge_timeframe_zones
from crypto_strategy_analyst.structure import detect_confirmed_swings


def test_levels_are_zones_with_evidence(enriched):
    swings = detect_confirmed_swings(enriched)
    supports, resistances = detect_zones(enriched, swings, "4h")
    assert supports
    assert resistances
    for zone in [*supports, *resistances]:
        assert zone.lower_price <= zone.center_price <= zone.upper_price
        assert zone.touch_count >= 1
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
