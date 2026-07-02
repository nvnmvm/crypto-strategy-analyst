from ..models import Horizon, MarketRegime, MarketSnapshot
from .base import AssetProfile, ProfileEvaluation, point_number, point_text


class BNBProfile(AssetProfile):
    name = "bnb"
    context_fields = ("bnb_btc", "binance_platform_risk", "launchpool", "chain_activity")
    confidence_cap = 84.0
    base_risk_multiplier = 0.72
    stop_multiplier = 1.15

    def evaluate_context(self, snapshot: MarketSnapshot, horizon: Horizon) -> ProfileEvaluation:
        result = super().evaluate_context(snapshot, horizon)
        relative = point_number(snapshot, "bnb_btc")
        if relative is not None:
            result.component_scores["relative_strength"] = max(0, min(100, 50 + relative * 4))
            result.confidence_adjustment += max(-8, min(7, relative))
        return result

    def apply_hard_filters(self, snapshot: MarketSnapshot, horizon: Horizon) -> list[str]:
        risk = point_text(snapshot, "binance_platform_risk")
        return (
            ["binance_platform_risk"]
            if any(word in risk for word in ("severe", "critical", "halted"))
            else []
        )

    def adjust_scores(self, scores, snapshot: MarketSnapshot, horizon: Horizon):
        relative = point_number(snapshot, "bnb_btc")
        return (
            {**scores, "relative_strength": max(0, min(100, 50 + relative * 4))}
            if relative is not None
            else scores
        )

    def filter_strategies(
        self, regime: MarketRegime, horizon: Horizon, strategies: list[str]
    ) -> list[str]:
        preferred = {"support_rebound", "breakout_retest", "range_reversal", "trend_pullback"}
        return [name for name in strategies if name in preferred]

    def adjust_parameters(self, horizon: Horizon) -> dict[str, float]:
        return {"stop_multiplier": 1.15, "volume_requirement": 1.2}

    def adjust_risk(self, snapshot: MarketSnapshot, horizon: Horizon) -> tuple[float, list[str]]:
        return self.base_risk_multiplier, []


PROFILE = BNBProfile()
