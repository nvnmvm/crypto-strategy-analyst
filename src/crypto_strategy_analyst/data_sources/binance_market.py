"""Binance public spot candles, ticker and exchange rules."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from ..models import Availability, Candle, DataPoint, MarketSnapshot
from .base import MarketDataSource, display_symbol, normalize_symbol


class BinanceMarketData(MarketDataSource):
    def __init__(
        self,
        client: httpx.Client | None = None,
        base_url: str = "https://data-api.binance.vision",
        timeout: float = 15,
    ):
        self.client = client or httpx.Client(timeout=timeout)
        self.base_url = base_url.rstrip("/")

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        response = self.client.get(f"{self.base_url}{path}", params=params)
        response.raise_for_status()
        return response.json()

    def snapshot(self, symbol: str, timeframes: list[str], limit: int = 500) -> MarketSnapshot:
        normalized = normalize_symbol(symbol)
        now = datetime.now(UTC)
        candles: dict[str, list[Candle]] = {}
        for timeframe in timeframes:
            rows = self._get(
                "/api/v3/klines", {"symbol": normalized, "interval": timeframe, "limit": limit}
            )
            candles[timeframe] = [
                Candle(
                    open_time=datetime.fromtimestamp(row[0] / 1000, UTC),
                    close_time=datetime.fromtimestamp((row[6] + 1) / 1000, UTC),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
                for row in rows
            ]
        ticker = self._get("/api/v3/ticker/price", {"symbol": normalized})
        rules = self._get("/api/v3/exchangeInfo", {"symbol": normalized})
        return MarketSnapshot(
            symbol=display_symbol(symbol),
            as_of=now,
            price=float(ticker["price"]),
            candles=candles,
            trading_rules=DataPoint(
                status=Availability.AVAILABLE,
                source="binance_spot_exchange_info",
                observed_at=now,
                freshness_seconds=0,
                value=rules,
            ),
        )

    def history(
        self,
        symbol: str,
        timeframes: list[str],
        start_at: datetime,
        end_at: datetime | None = None,
    ) -> MarketSnapshot:
        """Fetch every closed public kline in a bounded interval, oldest first.

        Binance returns the oldest rows after ``startTime``. Advancing by the
        previous row's close time creates a complete reproducible dataset without
        depending on the endpoint's recent-history limit.
        """

        normalized = normalize_symbol(symbol)
        now = datetime.now(UTC)
        start = start_at.astimezone(UTC)
        requested_end = end_at.astimezone(UTC) if end_at else now
        if requested_end <= start:
            raise ValueError("history end must be later than start")
        candles: dict[str, list[Candle]] = {}
        for timeframe in timeframes:
            rows: list[list[Any]] = []
            cursor = int(start.timestamp() * 1000)
            end_ms = int(requested_end.timestamp() * 1000)
            while cursor < end_ms:
                page = self._get(
                    "/api/v3/klines",
                    {
                        "symbol": normalized,
                        "interval": timeframe,
                        "startTime": cursor,
                        "endTime": end_ms,
                        "limit": 1000,
                    },
                )
                if not page:
                    break
                rows.extend(page)
                next_cursor = int(page[-1][6]) + 1
                if next_cursor <= cursor or len(page) < 1000:
                    break
                cursor = next_cursor
            candles[timeframe] = [
                Candle(
                    open_time=datetime.fromtimestamp(row[0] / 1000, UTC),
                    close_time=datetime.fromtimestamp((row[6] + 1) / 1000, UTC),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
                for row in rows
                if datetime.fromtimestamp((row[6] + 1) / 1000, UTC) <= requested_end
            ]
        ticker = self._get("/api/v3/ticker/price", {"symbol": normalized})
        rules = self._get("/api/v3/exchangeInfo", {"symbol": normalized})
        return MarketSnapshot(
            symbol=display_symbol(symbol),
            as_of=requested_end,
            price=float(ticker["price"]),
            candles=candles,
            trading_rules=DataPoint(
                status=Availability.AVAILABLE,
                source="binance_spot_exchange_info",
                observed_at=now,
                freshness_seconds=max(0, (now - requested_end).total_seconds()),
                value=rules,
            ),
        )
