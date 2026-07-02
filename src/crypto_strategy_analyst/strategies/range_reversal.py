from ..models import MarketRegime, StrategyMatch
from ..structure import secondary_confirmations, structure_confirmations
from .base import StrategyContext, build_match, failed


def detect(context: StrategyContext) -> StrategyMatch:
    support = context.support
    resistance = context.resistances[0] if context.resistances else None
    failures: list[str] = []
    if context.regime != MarketRegime.RANGE:
        failures.append("range_not_confirmed")
    if support is None or resistance is None:
        return failed("range_reversal", [*failures, "range_boundaries_missing"])
    if support.touches < 2 or support.distance_atr > context.config.levels.near_atr:
        failures.append("not_at_reacted_range_low")
    if context.price < support.lower:
        failures.append("range_low_broken")
    structure = structure_confirmations(context.bars, context.indicator)
    secondary = secondary_confirmations(context.indicator)
    midpoint = (support.midpoint + resistance.midpoint) / 2
    target_values = [(midpoint, "range_midpoint"), (resistance.lower, "range_high")]
    stop = support.lower - context.indicator.atr * context.config.strategy.stop_buffer_atr
    return build_match(
        "range_reversal", context, structure, secondary, stop, target_values, failures
    )
