"""Relative-pair returns from public Binance spot candles."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from ..models import Availability, DataPoint
from .base import AuxiliarySource, normalize_symbol

PAIRS = {
    "ETH": ("eth_btc", "ETHBTC"),
    "BNB": ("bnb_btc", "BNBBTC"),
    "SOL": ("sol_btc", "SOLBTC"),
}


class RelativeStrengthData(AuxiliarySource):
    def __init__(self, client: httpx.Client | None = None, timeout: float = 10):
        self.client = client or httpx.Client(timeout=timeout)
        self.base_url = "https://data-api.binance.vision"

    def _return(self, pair: str, name: str) -> DataPoint:
        now = datetime.now(UTC)
        try:
            response = self.client.get(
                f"{self.base_url}/api/v3/klines",
                params={"symbol": pair, "interval": "1d", "limit": 21},
            )
            response.raise_for_status()
            rows = response.json()
            change = (float(rows[-1][4]) / float(rows[0][4]) - 1) * 100
            return DataPoint(
                status=Availability.AVAILABLE,
                source=f"binance_spot:{pair}",
                observed_at=now,
                freshness_seconds=0,
                value={"change_percent": change, "window_days": 20},
            )
        except (httpx.HTTPError, IndexError, TypeError, ValueError, ZeroDivisionError) as exc:
            return DataPoint(
                status=Availability.FAILED,
                source=f"binance_spot:{pair}",
                observed_at=now,
                detail=type(exc).__name__,
            )

    def fetch(self, symbol: str) -> dict[str, DataPoint]:
        base = normalize_symbol(symbol).removesuffix("USDT")
        result: dict[str, DataPoint] = {}
        if base in PAIRS:
            name, pair = PAIRS[base]
            result[name] = self._return(pair, name)
        if base == "SOL":
            result["sol_eth"] = self._return("SOLETH", "sol_eth")
        return result
