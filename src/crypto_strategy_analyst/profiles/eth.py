from .base import AssetProfile

PROFILE = AssetProfile(
    name="eth",
    context_fields=("eth_btc", "gas", "staking", "etf_flow", "onchain", "btc_context"),
    stop_atr=2.0,
)
