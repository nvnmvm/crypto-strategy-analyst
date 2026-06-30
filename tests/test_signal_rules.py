from __future__ import annotations

from crypto_strategy_analyst.config import AppConfig
from crypto_strategy_analyst.levels import detect_zones
from crypto_strategy_analyst.models import PriceZone, SignalLabel, Trend
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


def _zone(center, level_type, timestamp, *, lower=None, upper=None):
    return PriceZone(
        lower_price=lower or center * 0.999,
        upper_price=upper or center * 1.001,
        center_price=center,
        level_type=level_type,
        timeframe="1d+4h",
        touch_count=3,
        reaction_count=2,
        break_count=0,
        last_touch_time=timestamp,
        strength_score=80,
        evidence=["test"],
    )


def _target_decision(enriched, resistance_lower):
    current = float(enriched["close"].iloc[-1])
    atr = float(enriched["atr14"].iloc[-1])
    timestamp = enriched.index[-1].to_pydatetime()
    support = _zone(
        current - atr * 0.2,
        "support",
        timestamp,
        lower=current - atr * 0.5,
        upper=current + atr * 0.1,
    )
    resistance = _zone(
        resistance_lower + atr * 0.1,
        "resistance",
        timestamp,
        lower=resistance_lower,
        upper=resistance_lower + atr * 0.2,
    )
    decision = generate_signal(
        daily_trend=Trend.BULLISH,
        four_hour_trend=Trend.BULLISH,
        one_hour_frame=enriched,
        four_hour_frame=enriched,
        supports=[support],
        resistances=[resistance],
        data_is_complete=True,
        config=AppConfig(),
    )
    return decision, current, atr, resistance


def test_resistance_below_two_r_blocks_targets(enriched):
    current = float(enriched["close"].iloc[-1])
    atr = float(enriched["atr14"].iloc[-1])
    decision, _, _, _ = _target_decision(enriched, current + atr)
    assert decision.label == SignalLabel.NO_TRADE
    assert decision.take_profit_1 is None
    assert decision.take_profit_2 is None
    assert "resistance_space_below_two_r" in decision.blockers


def test_missing_second_target_downgrades_signal(enriched):
    current = float(enriched["close"].iloc[-1])
    atr = float(enriched["atr14"].iloc[-1])
    decision, _, _, _ = _target_decision(enriched, current + atr * 2.35)
    assert decision.label not in {
        SignalLabel.BUY_CANDIDATE,
        SignalLabel.STRONG_BUY_CANDIDATE,
    }
    assert decision.take_profit_1 is not None
    assert decision.take_profit_2 is None
    assert "second_target_unavailable_before_resistance" in decision.blockers


def test_targets_never_cross_nearest_resistance(enriched):
    current = float(enriched["close"].iloc[-1])
    atr = float(enriched["atr14"].iloc[-1])
    decision, _, _, resistance = _target_decision(enriched, current + atr * 3.35)
    assert decision.take_profit_1 is not None
    assert decision.take_profit_2 is not None
    resistance_cap = (
        resistance.lower_price - atr * AppConfig().strategy.target_resistance_buffer_atr
    )
    assert decision.take_profit_1 <= resistance_cap
    assert decision.take_profit_2 <= resistance_cap
