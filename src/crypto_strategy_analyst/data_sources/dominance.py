"""BTC dominance from CoinGecko public global endpoint."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from ..models import Availability, DataPoint
from .base import AuxiliarySource


class DominanceData(AuxiliarySource):
    def __init__(self, client: httpx.Client | None = None, timeout: float = 10):
        self.client = client or httpx.Client(timeout=timeout)

    def fetch(self, symbol: str) -> dict[str, DataPoint]:
        now = datetime.now(UTC)
        try:
            response = self.client.get("https://api.coingecko.com/api/v3/global")
            response.raise_for_status()
            value = float(response.json()["data"]["market_cap_percentage"]["btc"])
            point = DataPoint(
                status=Availability.AVAILABLE,
                source="coingecko_global",
                observed_at=now,
                freshness_seconds=0,
                value=value,
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            point = DataPoint(
                status=Availability.FAILED,
                source="coingecko_global",
                observed_at=now,
                detail=type(exc).__name__,
            )
        return {"btc_dominance": point}
