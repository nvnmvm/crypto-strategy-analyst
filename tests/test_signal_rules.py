from __future__ import annotations

from crypto_strategy_analyst.config import AppConfig
from crypto_strategy_analyst.levels import detect_zones
from crypto_strategy_analyst.models import SignalLabel, Trend
from crypto_strategy_analyst.signal import generate_signal
from crypto_strategy_analyst.structure import detect_confirmed_swings


def _decision(enriched, daily_trend=Trend.SIDEWAYS, complete=True):
    swings = detect_confirmed_swings(enriched)
    supports, resistances = detect_zones(enriched, swings, "4h")
    return generate_signal(
        daily_trend=daily_trend,
        four_hour_trend=Trend.SIDEWAYS,
        one_hour_frame=enriched,
        four_hour_frame=enriched,
        supports=supports,
        resistances=resistances,
        data_is_complete=complete,
        config=AppConfig(),
    )


def test_bearish_daily_trend_hard_blocks_buy(enriched):
    decision = _decision(enriched, daily_trend=Trend.BEARISH)
    assert decision.label == SignalLabel.NO_TRADE
    assert "daily_trend_bearish" in decision.blockers


def test_incomplete_data_hard_blocks_buy(enriched):
    decision = _decision(enriched, complete=False)
    assert decision.label == SignalLabel.NO_TRADE
    assert "required_market_data_incomplete" in decision.blockers


def test_score_is_sum_of_fixed_components(enriched):
    decision = _decision(enriched)
    assert decision.score == decision.breakdown.total
    assert 0 <= decision.score <= 100
    assert decision.breakdown.sentiment_adjustment == 0
