from ..models import Horizon, MarketRegime, MarketSnapshot
from .base import AssetProfile, ProfileEvaluation, point_number, point_text


class ETHProfile(AssetProfile):
    name = "eth"
    context_fields = ("eth_btc", "btc_context", "gas", "staking", "eth_etf_flow", "onchain")
    confidence_cap = 88.0
    base_risk_multiplier = 0.85
    stop_multiplier = 1.15

    def evaluate_context(self, snapshot: MarketSnapshot, horizon: Horizon) -> ProfileEvaluation:
        result = super().evaluate_context(snapshot, horizon)
        relative = point_number(snapshot, "eth_btc")
        if relative is not None:
            result.component_scores["relative_strength"] = max(0, min(100, 50 + relative * 4))
            result.confidence_adjustment += max(-10, min(8, relative * 1.5))
        if "bearish" in point_text(snapshot, "btc_context"):
            result.confidence_adjustment -= 10
            result.risk_multiplier *= 0.6
            result.warnings.append("btc_context_conflict")
        return result

    def filter_strategies(
        self, regime: MarketRegime, horizon: Horizon, strategies: list[str]
    ) -> list[str]:
        return (
            [name for name in strategies if name != "bear_accumulation"]
            if horizon != Horizon.LONG
            else strategies
        )

    def adjust_scores(self, scores, snapshot: MarketSnapshot, horizon: Horizon):
        relative = point_number(snapshot, "eth_btc")
        return (
            {**scores, "relative_strength": max(0, min(100, 50 + relative * 4))}
            if relative is not None
            else scores
        )

    def adjust_parameters(self, horizon: Horizon) -> dict[str, float]:
        return {"stop_multiplier": 1.25 if horizon == Horizon.LONG else 1.15}

    def adjust_risk(self, snapshot: MarketSnapshot, horizon: Horizon) -> tuple[float, list[str]]:
        relative = point_number(snapshot, "eth_btc")
        return (
            (0.55, ["eth_btc_weakness"]) if relative is not None and relative < -3 else (0.85, [])
        )


PROFILE = ETHProfile()
