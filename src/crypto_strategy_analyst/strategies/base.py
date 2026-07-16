"""Strategy context, shared plan math and detector registry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..config import AppConfig
from ..models import (
    Candle,
    Horizon,
    IndicatorSet,
    KeyLevel,
    MarketRegime,
    PriceRange,
    StrategyMatch,
    TakeProfit,
)


@dataclass(frozen=True)
class StrategyContext:
    horizon: Horizon
    bars: list[Candle]
    indicator: IndicatorSet
    regime: MarketRegime
    levels: list[KeyLevel]
    config: AppConfig
    minimum_r: float

    @property
    def price(self) -> float:
        return self.bars[-1].close

    @property
    def support(self) -> KeyLevel | None:
        return next(
            (
                level
                for level in self.levels
                if level.type == "support" and level.lower <= self.price
            ),
            None,
        )

    @property
    def resistances(self) -> list[KeyLevel]:
        return sorted(
            [
                level
                for level in self.levels
                if level.type == "resistance" and level.upper > self.price
            ],
            key=lambda level: level.midpoint,
        )


def failed(name: str, conditions: list[str]) -> StrategyMatch:
    return StrategyMatch(
        strategy=name,
        matched=False,
        structure_confirmations=[],
        secondary_confirmations=[],
        failed_conditions=conditions,
    )


def build_match(
    name: str,
    context: StrategyContext,
    structure: list[str],
    secondary: list[str],
    stop: float,
    target_prices: list[tuple[float, str]],
    failed_conditions: list[str],
) -> StrategyMatch:
    if failed_conditions or not structure or not target_prices or stop >= context.price:
        conditions = list(failed_conditions)
        if not structure:
            conditions.append("missing_structure_confirmation")
        if not target_prices:
            conditions.append("missing_valid_target")
        return StrategyMatch(
            strategy=name,
            matched=False,
            structure_confirmations=structure,
            secondary_confirmations=secondary,
            failed_conditions=sorted(set(conditions)),
        )
    nearest = target_prices[0][0]
    maximum_entry = (nearest + context.minimum_r * stop) / (context.minimum_r + 1)
    anchor = context.support
    lower = max(
        stop + context.indicator.atr * 0.1,
        anchor.lower if anchor else context.price - context.indicator.atr * 0.2,
    )
    upper = min(
        maximum_entry,
        context.price + context.indicator.atr * context.config.strategy.entry_deviation_atr,
    )
    if upper < lower:
        return failed(name, ["reward_risk_below_minimum"])
    planned = (lower + upper) / 2
    reward_risk = (nearest - planned) / max(planned - stop, 1e-12)
    if reward_risk < context.minimum_r:
        return failed(name, ["reward_risk_below_minimum"])
    fractions = [1.0] if len(target_prices) == 1 else [0.5, 0.5]
    targets = [
        TakeProfit(price=price, fraction=fractions[index], source=source)
        for index, (price, source) in enumerate(target_prices[:2])
    ]
    return StrategyMatch(
        strategy=name,
        matched=True,
        structure_confirmations=structure,
        secondary_confirmations=secondary,
        failed_conditions=[],
        entry_range=PriceRange(lower=lower, upper=upper),
        stop_loss=stop,
        take_profits=targets,
        reward_risk=reward_risk,
        invalidation_conditions=[f"close_below_{stop:.8g}", "structure_confirmation_invalidated"],
    )


def targets(context: StrategyContext) -> list[tuple[float, str]]:
    resistance = context.resistances
    if resistance:
        values = [
            (level.lower, "nearest_resistance" if index == 0 else "higher_resistance")
            for index, level in enumerate(resistance[:2])
        ]
        return [item for item in values if item[0] > context.price]
    risk = context.indicator.atr * 2
    return [(context.price + risk * context.minimum_r, "fixed_r_without_known_resistance")]


Detector = Callable[[StrategyContext], StrategyMatch]


def evaluate_strategies(context: StrategyContext) -> list[StrategyMatch]:
    from .bear_accumulation import detect as bear_accumulation
    from .bear_reversal import detect as bear_reversal
    from .breakout_retest import detect as breakout_retest
    from .range_reversal import detect as range_reversal
    from .support_rebound import detect as support_rebound
    from .trend_pullback import detect as trend_pullback

    detectors: list[tuple[str, Detector]] = [
        ("support_rebound", support_rebound),
        ("breakout_retest", breakout_retest),
        ("trend_pullback", trend_pullback),
        ("range_reversal", range_reversal),
        ("bear_reversal", bear_reversal),
        ("bear_accumulation", bear_accumulation),
    ]
    return [
        detector(context)
        if getattr(context.config.strategy, name)
        else failed(name, ["strategy_disabled"])
        for name, detector in detectors
    ]
