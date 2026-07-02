from ..models import Horizon, MarketRegime, MarketSnapshot
from .base import AssetProfile, ProfileEvaluation, point_number, point_text


class BTCProfile(AssetProfile):
    name = "btc"
    context_fields = (
        "btc_dominance",
        "funding",
        "open_interest",
        "liquidations",
        "etf_flow",
        "macro",
    )
    confidence_cap = 92.0
    base_risk_multiplier = 1.0
    stop_multiplier = 1.1

    def evaluate_context(self, snapshot: MarketSnapshot, horizon: Horizon) -> ProfileEvaluation:
        result = super().evaluate_context(snapshot, horizon)
        funding = point_number(snapshot, "funding")
        oi = point_number(snapshot, "open_interest")
        etf = point_number(snapshot, "etf_flow")
        if funding is not None and funding > 0.0008 and oi is not None and oi > 5:
            result.confidence_adjustment -= 12
            result.risk_multiplier *= 0.5
            result.warnings.append("crowded_long_funding_and_oi")
        if etf is not None and etf < -5 and horizon in {Horizon.SWING, Horizon.LONG}:
            result.confidence_adjustment -= 8
        return result

    def apply_hard_filters(self, snapshot: MarketSnapshot, horizon: Horizon) -> list[str]:
        return ["major_macro_event"] if "critical" in point_text(snapshot, "macro") else []

    def adjust_scores(self, scores, snapshot: MarketSnapshot, horizon: Horizon):
        dominance = point_number(snapshot, "btc_dominance")
        if dominance is not None:
            scores = {
                **scores,
                "asset_specific": max(0, min(100, 50 + (dominance - 50) * 2)),
            }
        return scores

    def filter_strategies(
        self, regime: MarketRegime, horizon: Horizon, strategies: list[str]
    ) -> list[str]:
        if regime == MarketRegime.STRONG_BULL and horizon == Horizon.SHORT:
            return [name for name in strategies if name != "range_reversal"]
        return strategies

    def adjust_parameters(self, horizon: Horizon) -> dict[str, float]:
        return {"stop_multiplier": 1.2 if horizon == Horizon.LONG else 1.1, "chase_limit_atr": 0.2}

    def adjust_risk(self, snapshot: MarketSnapshot, horizon: Horizon) -> tuple[float, list[str]]:
        macro = point_text(snapshot, "macro")
        return (0.5, ["macro_event_risk"]) if "high" in macro else (1.0, [])


PROFILE = BTCProfile()
