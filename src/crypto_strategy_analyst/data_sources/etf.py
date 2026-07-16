from ..models import Availability, DataPoint
from .base import AuxiliarySource


class ETFData(AuxiliarySource):
    def fetch(self, symbol: str) -> dict[str, DataPoint]:
        name = "eth_etf_flow" if symbol.upper().startswith("ETH") else "etf_flow"
        return {
            name: DataPoint(
                status=Availability.NOT_AVAILABLE,
                source="external_input_required",
                detail="No stable unauthenticated source configured",
            )
        }
