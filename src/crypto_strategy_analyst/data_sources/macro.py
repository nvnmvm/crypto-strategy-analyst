from ..models import Availability, DataPoint
from .base import AuxiliarySource


class MacroData(AuxiliarySource):
    def fetch(self, symbol: str) -> dict[str, DataPoint]:
        return {
            "macro": DataPoint(status=Availability.NOT_AVAILABLE, source="external_input_required")
        }
