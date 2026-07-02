from ..models import MarketRegime, StrategyMatch
from ..structure import secondary_confirmations, structure_confirmations
from .base import StrategyContext, build_match, failed, targets

ALLOWED = {
    MarketRegime.BULLISH,
    MarketRegime.BULL_PULLBACK,
    MarketRegime.RANGE,
    MarketRegime.RECOVERY,
}


def detect(context: StrategyContext) -> StrategyMatch:
    failures: list[str] = []
    support = context.support
    if context.regime not in ALLOWED:
        failures.append("regime_not_supported")
    if support is None or support.distance_atr > context.config.levels.near_atr:
        failures.append("not_near_confirmed_support")
    elif support.touches < 2 and support.timeframe not in {"1w", "1d"}:
        failures.append("support_strength_insufficient")
    structure = structure_confirmations(context.bars, context.indicator)
    secondary = secondary_confirmations(context.indicator)
    if not secondary:
        failures.append("missing_secondary_confirmation")
    if support is None:
        return failed("support_rebound", [*failures, "missing_support"])
    stop = support.lower - context.indicator.atr * context.config.strategy.stop_buffer_atr
    return build_match(
        "support_rebound", context, structure, secondary, stop, targets(context), failures
    )
