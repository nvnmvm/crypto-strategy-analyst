from ..models import Horizon, MarketSnapshot
from .base import AssetProfile, ProfileEvaluation, point_number, point_text


class GenericProfile(AssetProfile):
    name = "generic"
    context_fields = (
        "pair_status",
        "listing_history_days",
        "liquidity",
        "spread",
        "data_integrity",
    )
    confidence_cap = 68.0
    base_risk_multiplier = 0.45
    stop_multiplier = 1.25

    def evaluate_context(self, snapshot: MarketSnapshot, horizon: Horizon) -> ProfileEvaluation:
        result = super().evaluate_context(snapshot, horizon)
        result.warnings.insert(0, "该币种没有专属分析Profile")
        liquidity = point_number(snapshot, "liquidity")
        spread = point_number(snapshot, "spread")
        if liquidity is not None and liquidity < 30:
            result.confidence_adjustment -= 12
        if spread is not None and spread > 0.01:
            result.confidence_adjustment -= 10
        return result

    def apply_hard_filters(self, snapshot: MarketSnapshot, horizon: Horizon) -> list[str]:
        status = point_text(snapshot, "pair_status")
        history = point_number(snapshot, "listing_history_days")
        filters = ["pair_not_trading"] if status and "trading" not in status else []
        if history is not None and history < 90:
            filters.append("listing_history_too_short")
        return filters


PROFILE = GenericProfile()
