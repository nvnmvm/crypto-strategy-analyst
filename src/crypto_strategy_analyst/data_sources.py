"""Pluggable market data sources with explicit availability semantics."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

import httpx

from .models import Availability, Candle, DataPoint, MarketSnapshot

INTERVAL_MS = {
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
    "1w": 604_800_000,
}


def normalize_symbol(symbol: str) -> str:
    return symbol.upper().replace("/", "").replace("-", "").replace("_", "")


class MarketDataSource(ABC):
    @abstractmethod
    def snapshot(self, symbol: str, timeframes: list[str], limit: int) -> MarketSnapshot: ...


class BinancePublicData(MarketDataSource):
    def __init__(
        self,
        client: httpx.Client | None = None,
        base_url: str = "https://data-api.binance.vision",
    ):
        self.client = client or httpx.Client(timeout=15)
        self.base_url = base_url.rstrip("/")

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        response = self.client.get(f"{self.base_url}{path}", params=params)
        response.raise_for_status()
        return response.json()

    def snapshot(self, symbol: str, timeframes: list[str], limit: int = 500) -> MarketSnapshot:
        venue_symbol = normalize_symbol(symbol)
        now = datetime.now(UTC)
        candles: dict[str, list[Candle]] = {}
        for frame in timeframes:
            raw = self._get(
                "/api/v3/klines", {"symbol": venue_symbol, "interval": frame, "limit": limit}
            )
            candles[frame] = [
                Candle(
                    open_time=datetime.fromtimestamp(row[0] / 1000, UTC),
                    close_time=datetime.fromtimestamp((row[6] + 1) / 1000, UTC),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
                for row in raw
            ]
        ticker = self._get("/api/v3/ticker/price", {"symbol": venue_symbol})
        rules = self._get("/api/v3/exchangeInfo", {"symbol": venue_symbol})
        completed = [bar for bar in candles[timeframes[-1]] if bar.close_time <= now]
        latest_volume = completed[-1].volume
        return MarketSnapshot(
            symbol=venue_symbol,
            as_of=now,
            price=float(ticker["price"]),
            candles=candles,
            trading_rules=DataPoint(
                status=Availability.AVAILABLE,
                source="binance",
                observed_at=now,
                freshness_seconds=0,
                value=rules,
            ),
            timestamp=DataPoint(
                status=Availability.AVAILABLE,
                source="local_clock",
                observed_at=now,
                freshness_seconds=0,
                value=now.isoformat(),
            ),
            volume=DataPoint(
                status=Availability.AVAILABLE,
                source="binance",
                observed_at=now,
                freshness_seconds=0,
                value=latest_volume,
            ),
        )
