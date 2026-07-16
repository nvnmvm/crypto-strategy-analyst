from ..models import Horizon, StrategyMatch
from ..structure import structure_confirmations
from .base import StrategyContext, build_match, failed, targets


def detect(context: StrategyContext) -> StrategyMatch:
    if context.horizon != Horizon.LONG:
        return failed("bear_accumulation", ["long_horizon_only"])
    support = context.support
    if support is None:
        return failed("bear_accumulation", ["missing_long_term_support"])
    structure = structure_confirmations(context.bars, context.indicator)
    stop = support.lower - context.indicator.atr * context.config.strategy.stop_buffer_atr
    return build_match(
        "bear_accumulation",
        context,
        structure,
        ["confirmation_only_mode"],
        stop,
        targets(context),
        [] if structure else ["new_structure_confirmation_required"],
    )
