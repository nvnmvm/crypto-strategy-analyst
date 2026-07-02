from ..models import Horizon, MarketRegime, MarketSnapshot
from .base import AssetProfile, ProfileEvaluation, point_number, point_text


class SOLProfile(AssetProfile):
    name = "sol"
    context_fields = (
        "sol_btc",
        "sol_eth",
        "onchain",
        "network_health",
        "ecosystem",
        "memecoin_activity",
        "funding",
        "open_interest",
    )
    confidence_cap = 82.0
    base_risk_multiplier = 0.58
    stop_multiplier = 1.4

    def evaluate_context(self, snapshot: MarketSnapshot, horizon: Horizon) -> ProfileEvaluation:
        result = super().evaluate_context(snapshot, horizon)
        values = [point_number(snapshot, name) for name in ("sol_btc", "sol_eth")]
        present = [value for value in values if value is not None]
        if present:
            result.component_scores["relative_strength"] = max(
                0, min(100, 50 + sum(present) / len(present) * 4)
            )
            if len(present) == 2 and all(value > 0 for value in present):
                result.confidence_adjustment += 7
        funding = point_number(snapshot, "funding")
        oi = point_number(snapshot, "open_interest")
        if funding is not None and funding > 0.001 and oi is not None and oi > 7:
            result.confidence_adjustment -= 14
            result.risk_multiplier *= 0.45
            result.warnings.append("sol_crowded_long")
        return result

    def apply_hard_filters(self, snapshot: MarketSnapshot, horizon: Horizon) -> list[str]:
        network = point_text(snapshot, "network_health")
        return (
            ["sol_network_severe"]
            if any(word in network for word in ("severe", "halted", "critical"))
            else []
        )

    def adjust_scores(self, scores, snapshot: MarketSnapshot, horizon: Horizon):
        values = [
            value
            for value in (
                point_number(snapshot, "sol_btc"),
                point_number(snapshot, "sol_eth"),
            )
            if value is not None
        ]
        return (
            {
                **scores,
                "relative_strength": max(0, min(100, 50 + sum(values) / len(values) * 4)),
            }
            if values
            else scores
        )

    def filter_strategies(
        self, regime: MarketRegime, horizon: Horizon, strategies: list[str]
    ) -> list[str]:
        return [
            name
            for name in strategies
            if not (name == "bear_accumulation" and horizon != Horizon.LONG)
        ]

    def adjust_parameters(self, horizon: Horizon) -> dict[str, float]:
        return {
            "stop_multiplier": 1.5 if horizon == Horizon.SHORT else 1.4,
            "volume_requirement": 1.3,
            "breakout_atr": 0.45,
        }

    def adjust_risk(self, snapshot: MarketSnapshot, horizon: Horizon) -> tuple[float, list[str]]:
        return self.base_risk_multiplier, ["high_volatility_asset"]


PROFILE = SOLProfile()
