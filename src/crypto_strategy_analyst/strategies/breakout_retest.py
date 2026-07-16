from ..models import MarketRegime, StrategyMatch
from ..structure import secondary_confirmations, structure_confirmations
from .base import StrategyContext, build_match, failed, targets

ALLOWED = {
    MarketRegime.STRONG_BULL,
    MarketRegime.BULLISH,
    MarketRegime.RECOVERY,
    MarketRegime.RANGE,
}


def detect(context: StrategyContext) -> StrategyMatch:
    bars = context.bars
    if len(bars) < 25:
        return failed("breakout_retest", ["insufficient_history"])
    resistance = max(bar.high for bar in bars[-25:-3])
    breakout = bars[-2]
    retest = bars[-1]
    failures: list[str] = []
    if context.regime not in ALLOWED:
        failures.append("regime_not_supported")
    if breakout.close < resistance + context.config.strategy.breakout_atr * context.indicator.atr:
        failures.append("no_valid_closed_breakout")
    if (
        breakout.volume
        < sum(bar.volume for bar in bars[-22:-2]) / 20 * context.config.strategy.volume_ratio
    ):
        failures.append("breakout_without_volume")
    if retest.low > resistance + context.indicator.atr * 0.3 or retest.close < resistance:
        failures.append("retest_not_completed")
    structure = structure_confirmations(bars, context.indicator)
    if retest.close > resistance and "break_local_high" not in structure:
        structure.append("breakout_retest_hold")
    secondary = secondary_confirmations(context.indicator)
    stop = resistance - context.indicator.atr * context.config.strategy.stop_buffer_atr
    return build_match(
        "breakout_retest", context, structure, secondary, stop, targets(context), failures
    )
