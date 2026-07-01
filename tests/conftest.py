from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from crypto_strategy_analyst.models import Availability, Candle, DataPoint, MarketSnapshot


@pytest.fixture
def snapshot_factory():
    def build(
        symbol: str = "BTCUSDT", slope: float = 1, future_spike: bool = False
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
            for index in range(80):
                close_time = end - duration * (79 - index)
                price = 100 + slope * index
                bars.append(
                    Candle(
                        open_time=close_time - duration,
                        close_time=close_time,
                        open=price - 0.3,
                        high=price + 1,
                        low=price - 1,
                        close=price,
                        volume=100 + index,
                    )
                )
            if future_spike:
                bars.append(
                    Candle(
                        open_time=end,
                        close_time=end + duration,
                        open=179,
                        high=10_001,
                        low=178,
                        close=10_000,
                        volume=10_000,
                    )
                )
            candles[frame] = bars
        point = DataPoint(
            status=Availability.AVAILABLE,
            source="test",
            observed_at=end,
            freshness_seconds=0,
            value={"score": 60},
        )
        return MarketSnapshot(
            symbol=symbol,
            as_of=end,
            price=179,
            candles=candles,
            trading_rules=point,
            timestamp=point,
            volume=point,
        )

    return build
