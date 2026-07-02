"""Asset-profile behavior contract."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models import Horizon, MarketRegime, MarketSnapshot


@dataclass
class ProfileEvaluation:
    component_scores: dict[str, float | None] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    hard_filters: list[str] = field(default_factory=list)
    confidence_adjustment: float = 0
    risk_multiplier: float = 1
    parameter_overrides: dict[str, float] = field(default_factory=dict)


def point_number(snapshot: MarketSnapshot, name: str) -> float | None:
    point = snapshot.auxiliary.get(name)
    if not point or not point.usable_at(snapshot.as_of):
        return None
    value = point.value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for key in ("score", "change_percent", "value", "rate"):
            if isinstance(value.get(key), (int, float)):
                return float(value[key])
    return None


def point_text(snapshot: MarketSnapshot, name: str) -> str:
    point = snapshot.auxiliary.get(name)
    return str(point.value).lower() if point and point.usable_at(snapshot.as_of) else ""


class AssetProfile:
    name = "generic"
    context_fields: tuple[str, ...] = ()
    confidence_cap = 72.0
    base_risk_multiplier = 0.6
    stop_multiplier = 1.0

    def evaluate_context(self, snapshot: MarketSnapshot, horizon: Horizon) -> ProfileEvaluation:
        missing = [name for name in self.context_fields if point_number(snapshot, name) is None]
        return ProfileEvaluation(
            warnings=[f"auxiliary_not_available:{name}" for name in missing],
            risk_multiplier=self.base_risk_multiplier,
        )

    def adjust_scores(
        self, scores: dict[str, float | None], snapshot: MarketSnapshot, horizon: Horizon
    ) -> dict[str, float | None]:
        return scores

    def apply_hard_filters(self, snapshot: MarketSnapshot, horizon: Horizon) -> list[str]:
        return []

    def filter_strategies(
        self, regime: MarketRegime, horizon: Horizon, strategies: list[str]
    ) -> list[str]:
        return strategies

    def adjust_parameters(self, horizon: Horizon) -> dict[str, float]:
        return {"stop_multiplier": self.stop_multiplier}

    def adjust_risk(self, snapshot: MarketSnapshot, horizon: Horizon) -> tuple[float, list[str]]:
        return self.base_risk_multiplier, []
