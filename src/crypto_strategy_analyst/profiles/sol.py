from .base import AssetProfile

PROFILE = AssetProfile(
    name="sol",
    context_fields=(
        "sol_btc",
        "sol_eth",
        "onchain",
        "network_health",
        "ecosystem",
        "memecoin_activity",
        "funding",
        "open_interest",
    ),
    hard_filter_fields=("network_health",),
    position_multiplier=0.65,
    stop_atr=2.4,
)
