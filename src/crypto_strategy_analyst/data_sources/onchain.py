from ..models import Availability, DataPoint
from .base import AuxiliarySource, normalize_symbol


class OnchainData(AuxiliarySource):
    def fetch(self, symbol: str) -> dict[str, DataPoint]:
        base = normalize_symbol(symbol).removesuffix("USDT").lower()
        names = {
            "eth": ("gas", "staking", "onchain"),
            "bnb": ("chain_activity", "binance_platform_risk", "launchpool"),
            "sol": ("onchain", "network_health", "ecosystem", "memecoin_activity"),
        }.get(base, ("onchain",))
        return {
            name: DataPoint(status=Availability.NOT_AVAILABLE, source="external_input_required")
            for name in names
        }
