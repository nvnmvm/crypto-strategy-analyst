"""Public Binance futures context; failures degrade rather than fabricate."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from ..models import Availability, DataPoint
from .base import AuxiliarySource, normalize_symbol


class BinanceDerivativesData(AuxiliarySource):
    def __init__(self, client: httpx.Client | None = None, timeout: float = 10):
        self.client = client or httpx.Client(timeout=timeout)
        self.base_url = "https://fapi.binance.com"

    def _point(self, path: str, symbol: str, key: str, transform) -> DataPoint:
        now = datetime.now(UTC)
        try:
            response = self.client.get(f"{self.base_url}{path}", params={"symbol": symbol})
            response.raise_for_status()
            return DataPoint(
                status=Availability.AVAILABLE,
                source=f"binance_futures:{path}",
                observed_at=now,
                freshness_seconds=0,
                value=transform(response.json()),
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            return DataPoint(
                status=Availability.FAILED,
                source=f"binance_futures:{path}",
                observed_at=now,
                detail=type(exc).__name__,
            )

    def fetch(self, symbol: str) -> dict[str, DataPoint]:
        normalized = normalize_symbol(symbol)
        return {
            "funding": self._point(
                "/fapi/v1/premiumIndex",
                normalized,
                "lastFundingRate",
                lambda value: float(value["lastFundingRate"]),
            ),
            "open_interest": self._point(
                "/fapi/v1/openInterest",
                normalized,
                "openInterest",
                lambda value: {"value": float(value["openInterest"]), "change_percent": 0.0},
            ),
        }
