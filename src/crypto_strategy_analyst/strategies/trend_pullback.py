from ..models import MarketRegime, StrategyMatch
from ..structure import drawdown, secondary_confirmations, structure_confirmations, structure_intact
from .base import StrategyContext, build_match, targets

ALLOWED = {MarketRegime.STRONG_BULL, MarketRegime.BULLISH, MarketRegime.BULL_PULLBACK}


def detect(context: StrategyContext) -> StrategyMatch:
    failures: list[str] = []
    pullback = drawdown(context.bars, 60)
    if context.regime not in ALLOWED:
        failures.append("higher_timeframe_not_bullish")
    if pullback < context.config.strategy.pullback_minimum:
        failures.append("pullback_too_shallow")
    if not structure_intact(context.bars):
        failures.append("major_structure_broken")
    near_trend = abs(context.price - context.indicator.ema20) <= context.indicator.atr or (
        context.support and context.support.distance_atr <= 1
    )
    if not near_trend:
        failures.append("not_in_trend_support_zone")
    structure = structure_confirmations(context.bars, context.indicator)
    secondary = secondary_confirmations(context.indicator)
    support = context.support
    stop = (
        support.lower if support else min(bar.low for bar in context.bars[-10:])
    ) - context.indicator.atr * context.config.strategy.stop_buffer_atr
    return build_match(
        "trend_pullback", context, structure, secondary, stop, targets(context), failures
    )
