from .base import AssetProfile

PROFILE = AssetProfile(
    name="bnb",
    context_fields=("bnb_btc", "binance_platform_risk", "launchpool", "chain_activity"),
    hard_filter_fields=("binance_platform_risk",),
    stop_atr=2.0,
)
