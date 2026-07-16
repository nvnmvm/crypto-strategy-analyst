"""Public, deterministic market-regime classification."""

from __future__ import annotations

from .models import Candle, IndicatorSet, MarketRegime
from .structure import drawdown, structure_intact


def classify_regime(bars: list[Candle], indicator: IndicatorSet) -> MarketRegime:
    price = indicator.close
    drop = drawdown(bars)
    if drop >= 0.25 and indicator.rsi < 28 and indicator.volume_ratio >= 1.5:
        return MarketRegime.CAPITULATION
    if price > indicator.ema20 > indicator.ema50 > indicator.ema200:
        return (
            MarketRegime.STRONG_BULL
            if indicator.trend_strength >= 68 and indicator.ema20_slope > 0
            else MarketRegime.BULLISH
        )
    if price < indicator.ema20 and indicator.ema50 > indicator.ema200 and structure_intact(bars):
        return MarketRegime.BULL_PULLBACK
    if price < indicator.ema50 < indicator.ema200:
        return (
            MarketRegime.RECOVERY
            if indicator.macd_histogram > 0 and indicator.rsi > 40
            else MarketRegime.BEARISH
        )
    return MarketRegime.RANGE
