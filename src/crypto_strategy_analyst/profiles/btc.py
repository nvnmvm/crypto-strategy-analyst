from .base import AssetProfile

PROFILE = AssetProfile(
    name="btc",
    context_fields=(
        "btc_dominance",
        "funding",
        "open_interest",
        "liquidations",
        "etf_flow",
        "macro",
    ),
    stop_atr=2.1,
    timeframe_weights={"1w": 0.35, "1d": 0.35, "4h": 0.2, "1h": 0.1},
)
