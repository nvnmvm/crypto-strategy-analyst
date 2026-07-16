from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from crypto_strategy_analyst.models import Availability, Candle, DataPoint, MarketSnapshot


@pytest.fixture
def snapshot_factory():
    def build(
        symbol: str = "BTC/USDT",
        mode: str = "bull",
        count: int = 240,
        auxiliary: dict[str, DataPoint] | None = None,
        future_spike: bool = False,
    ) -> MarketSnapshot:
        end = datetime(2026, 1, 1, tzinfo=UTC)
        durations = {
            "1w": timedelta(days=7),
            "1d": timedelta(days=1),
            "4h": timedelta(hours=4),
            "1h": timedelta(hours=1),
            "15m": timedelta(minutes=15),
        }
        candles = {}
        for frame, duration in durations.items():
            bars = []
            for index in range(count):
                close_time = end - duration * (count - 1 - index)
                if mode == "bull":
                    price = 100 + index * 0.25 + math.sin(index / 5) * 2
                elif mode == "bear":
                    price = 200 - index * 0.35 + math.sin(index / 4) * 2
                else:
                    price = 120 + math.sin(index / 5) * 8
                price = max(5, price)
                open_price = price - math.sin(index) * 0.8
                bars.append(
                    Candle(
                        open_time=close_time - duration,
                        close_time=close_time,
                        open=open_price,
                        high=max(open_price, price) + 1.2,
                        low=min(open_price, price) - 1.2,
                        close=price,
                        volume=100 + (index % 10) * 8,
                    )
                )
            if future_spike:
                bars.append(
                    Candle(
                        open_time=end,
                        close_time=end + duration,
                        open=bars[-1].close,
                        high=10_001,
                        low=bars[-1].close - 1,
                        close=10_000,
                        volume=100_000,
                    )
                )
            candles[frame] = bars
        point = DataPoint(
            status=Availability.AVAILABLE,
            source="test",
            observed_at=end,
            freshness_seconds=0,
            value={"symbol": symbol},
        )
        return MarketSnapshot(
            symbol=symbol,
            as_of=end,
            price=candles["4h"][-1 if not future_spike else -2].close,
            candles=candles,
            trading_rules=point,
            auxiliary=auxiliary or {},
        )

    return build


@pytest.fixture
def available_point():
    def build(value, source="test", observed_at=None):
        return DataPoint(
            status=Availability.AVAILABLE,
            source=source,
            observed_at=observed_at,
            freshness_seconds=0,
            value=value,
        )

    return build
