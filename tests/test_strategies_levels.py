from datetime import UTC, datetime, timedelta

import pytest

from crypto_strategy_analyst.config import AppConfig
from crypto_strategy_analyst.indicators import calculate_indicators, indicator_map
from crypto_strategy_analyst.levels import detect_levels, merge_levels
from crypto_strategy_analyst.models import Candle, Horizon, IndicatorSet, KeyLevel, MarketRegime
from crypto_strategy_analyst.strategies import StrategyContext, evaluate_strategies
from crypto_strategy_analyst.strategies.bear_accumulation import detect as bear_accumulation
from crypto_strategy_analyst.strategies.bear_reversal import detect as bear_reversal
from crypto_strategy_analyst.strategies.breakout_retest import detect as breakout_retest
from crypto_strategy_analyst.strategies.range_reversal import detect as range_reversal
from crypto_strategy_analyst.strategies.support_rebound import detect as support_rebound
from crypto_strategy_analyst.strategies.trend_pullback import detect as trend_pullback
from crypto_strategy_analyst.structure import (
    bullish_pattern_confirmations,
    detect_chart_patterns,
)


def pattern_bars(prices: list[float]) -> list[Candle]:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    return [
        Candle(
            open_time=start + timedelta(days=index),
            close_time=start + timedelta(days=index + 1),
            open=price,
            high=price + 0.5,
            low=price - 0.5,
            close=price,
            volume=100,
        )
        for index, price in enumerate(prices)
    ]


def pattern_indicator(atr: float = 2) -> IndicatorSet:
    return IndicatorSet(
        close=100,
        ema20=100,
        ema50=100,
        ema200=100,
        ema20_slope=0,
        rsi=50,
        macd_histogram=0,
        atr=atr,
        atr_percent=2,
        volume_ratio=1,
        trend_strength=50,
    )


def context(snapshot_factory, mode="bull", regime=MarketRegime.BULLISH, horizon=Horizon.SWING):
    snapshot = snapshot_factory(mode=mode)
    config = AppConfig()
    frame = {Horizon.SHORT: "4h", Horizon.SWING: "1d", Horizon.LONG: "1w"}[horizon]
    bars = snapshot.completed(frame)
    indicator = calculate_indicators(bars, config.indicators)
    levels = detect_levels(
        {key: snapshot.completed(key) for key in snapshot.candles},
        indicator_map(snapshot.candles, config.indicators),
        snapshot.price,
        config.levels,
    )
    return StrategyContext(horizon, bars, indicator, regime, levels, config, 1.8)


def test_each_strategy_has_independent_failure_reasons(snapshot_factory):
    ctx = context(snapshot_factory)
    results = evaluate_strategies(ctx)
    assert {item.strategy for item in results} == {
        "support_rebound",
        "breakout_retest",
        "trend_pullback",
        "range_reversal",
        "bear_reversal",
        "bear_accumulation",
    }
    assert all(item.matched or item.failed_conditions for item in results)
    assert len({tuple(item.failed_conditions) for item in results}) > 2


def test_support_rebound_not_labeled_without_support(snapshot_factory):
    ctx = context(snapshot_factory)
    ctx = StrategyContext(
        ctx.horizon, ctx.bars, ctx.indicator, ctx.regime, [], ctx.config, ctx.minimum_r
    )
    result = support_rebound(ctx)
    assert not result.matched
    assert "missing_support" in result.failed_conditions


def test_breakout_without_retest_fails(snapshot_factory):
    result = breakout_retest(context(snapshot_factory))
    assert not result.matched
    assert {"no_valid_closed_breakout", "retest_not_completed"}.intersection(
        result.failed_conditions
    )


def test_broken_trend_pullback_fails(snapshot_factory):
    result = trend_pullback(context(snapshot_factory, mode="bear", regime=MarketRegime.BEARISH))
    assert not result.matched
    assert "higher_timeframe_not_bullish" in result.failed_conditions


def test_range_reversal_requires_range(snapshot_factory):
    result = range_reversal(context(snapshot_factory, regime=MarketRegime.BULLISH))
    assert not result.matched
    assert "range_not_confirmed" in result.failed_conditions


def test_rsi_or_bear_regime_alone_cannot_trigger_reversal(snapshot_factory):
    result = bear_reversal(context(snapshot_factory, mode="bear", regime=MarketRegime.BEARISH))
    assert not result.matched
    assert (
        "higher_low_missing" in result.failed_conditions
        or "local_downtrend_not_broken" in result.failed_conditions
    )


def test_bear_accumulation_never_short(snapshot_factory):
    result = bear_accumulation(context(snapshot_factory, horizon=Horizon.SHORT))
    assert not result.matched
    assert result.failed_conditions == ["long_horizon_only"]


def test_touch_cooldown_and_htf_priority(snapshot_factory):
    snapshot = snapshot_factory(mode="range")
    config = AppConfig()
    indicators = indicator_map(snapshot.candles, config.indicators)
    levels = detect_levels(snapshot.candles, indicators, snapshot.price, config.levels)
    assert levels
    assert max(level.touches for level in levels) < len(snapshot.candles["1d"]) / 2
    assert any(level.timeframe in {"1w", "1d"} for level in levels)


def test_merge_prefers_high_timeframe_and_combines_sources(snapshot_factory):
    snapshot = snapshot_factory()
    indicator = calculate_indicators(snapshot.candles["1d"], AppConfig().indicators)
    now = datetime.now(UTC)
    weekly = KeyLevel(
        type="support",
        lower=99,
        upper=101,
        midpoint=100,
        timeframe="1w",
        strength=70,
        touches=2,
        last_reaction_at=now,
        sources=["weekly"],
        distance_percent=0.01,
        distance_atr=0.2,
    )
    hourly = weekly.model_copy(
        update={
            "lower": 100,
            "upper": 102,
            "midpoint": 101,
            "timeframe": "1h",
            "strength": 80,
            "sources": ["hourly"],
        }
    )
    merged = merge_levels([hourly, weekly], indicator, AppConfig().levels)
    assert merged[0].timeframe == "1w"
    assert set(merged[0].sources) == {"weekly", "hourly"}


def test_broken_levels_are_removed(snapshot_factory):
    snapshot = snapshot_factory(mode="bull")
    config = AppConfig()
    levels = detect_levels(
        snapshot.candles,
        indicator_map(snapshot.candles, config.indicators),
        snapshot.price,
        config.levels,
    )
    assert all(
        not (level.type == "resistance" and level.midpoint < snapshot.price * 0.9)
        for level in levels
    )


@pytest.mark.parametrize("period", [10, 14, 20])
def test_indicator_ranges(snapshot_factory, period):
    config = AppConfig().indicators.model_copy(update={"rsi_period": period})
    result = calculate_indicators(snapshot_factory().candles["1d"], config)
    assert 0 <= result.rsi <= 100
    assert result.atr > 0


@pytest.mark.parametrize(
    ("prices", "expected"),
    [
        ([110, 108, 106, 101, 103, 106, 110, 108, 104, 101.3, 103, 108, 112, 116, 118], "double_bottom"),
        ([100, 104, 108, 104, 100, 106, 114, 106, 101, 105, 108, 104, 98, 94, 92], "head_shoulders"),
        ([110, 106, 102, 106, 110, 104, 96, 104, 109, 105, 102, 106, 112, 116], "inverse_head_shoulders"),
        ([100, 104, 108, 104, 102, 104, 107, 105, 103, 104, 106, 105, 104, 104.5, 112, 115], "triangle_breakout"),
    ],
)
def test_chart_patterns_require_and_recognize_closed_neckline_breaks(prices, expected):
    patterns = {pattern.name: pattern for pattern in detect_chart_patterns(pattern_bars(prices), pattern_indicator())}
    assert patterns[expected].state == "confirmed"


def test_forming_pattern_is_not_a_structure_confirmation():
    prices = [110, 108, 106, 101, 103, 106, 110, 108, 104, 101.3, 103, 108]
    patterns = {pattern.name: pattern for pattern in detect_chart_patterns(pattern_bars(prices), pattern_indicator())}
    assert patterns["double_bottom"].state == "forming"
    assert bullish_pattern_confirmations(pattern_bars(prices), pattern_indicator()) == []
