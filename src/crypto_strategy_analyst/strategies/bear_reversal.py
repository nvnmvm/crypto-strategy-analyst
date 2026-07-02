from ..models import MarketRegime, StrategyMatch
from ..structure import drawdown, secondary_confirmations, structure_confirmations
from .base import StrategyContext, build_match, targets

ALLOWED = {MarketRegime.BEARISH, MarketRegime.CAPITULATION, MarketRegime.RECOVERY}


def detect(context: StrategyContext) -> StrategyMatch:
    structure = structure_confirmations(context.bars, context.indicator)
    failures: list[str] = []
    if context.regime not in ALLOWED:
        failures.append("bear_regime_not_present")
    if drawdown(context.bars, 120) < context.config.strategy.bear_drawdown:
        failures.append("drawdown_not_deep")
    if "higher_low" not in structure:
        failures.append("higher_low_missing")
    if not {"break_local_high", "reclaim_ema20"}.intersection(structure):
        failures.append("local_downtrend_not_broken")
    secondary = secondary_confirmations(context.indicator)
    if not secondary:
        failures.append("momentum_not_improving")
    support = context.support
    low = support.lower if support else min(bar.low for bar in context.bars[-20:])
    stop = low - context.indicator.atr * context.config.strategy.stop_buffer_atr
    return build_match(
        "bear_reversal", context, structure, secondary, stop, targets(context), failures
    )
