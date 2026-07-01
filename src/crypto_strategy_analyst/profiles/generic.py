from .base import AssetProfile

PROFILE = AssetProfile(
    name="generic",
    context_fields=("pair_status", "listing_status", "liquidity", "spread", "atr"),
    hard_filter_fields=("pair_status", "listing_status"),
    confidence_cap=72,
    position_multiplier=0.5,
    stop_atr=2.2,
)
