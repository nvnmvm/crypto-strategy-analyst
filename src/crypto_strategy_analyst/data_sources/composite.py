"""Compose public market and auxiliary sources with caller JSON overrides."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..models import DataPoint, MarketSnapshot
from .base import AuxiliarySource, MarketDataSource
from .binance_derivatives import BinanceDerivativesData
from .binance_market import BinanceMarketData
from .dominance import DominanceData
from .etf import ETFData
from .macro import MacroData
from .onchain import OnchainData
from .relative_strength import RelativeStrengthData


class CompositeDataSource(MarketDataSource):
    def __init__(
        self,
        market: MarketDataSource | None = None,
        auxiliary: list[AuxiliarySource] | None = None,
        timeout: float = 15,
    ):
        self.market = market or BinanceMarketData(timeout=timeout)
        self.auxiliary = auxiliary or [
            BinanceDerivativesData(timeout=timeout),
            RelativeStrengthData(timeout=timeout),
            DominanceData(timeout=timeout),
            ETFData(),
            MacroData(),
            OnchainData(),
        ]

    def snapshot(self, symbol: str, timeframes: list[str], limit: int = 500) -> MarketSnapshot:
        snapshot = self.market.snapshot(symbol, timeframes, limit)
        return self._with_auxiliary(snapshot, symbol)

    def history(
        self,
        symbol: str,
        timeframes: list[str],
        start_at: datetime,
        end_at: datetime | None = None,
    ) -> MarketSnapshot:
        if not isinstance(self.market, BinanceMarketData):
            raise ValueError("ranged history requires the built-in Binance public market source")
        return self._with_auxiliary(
            self.market.history(symbol, timeframes, start_at, end_at), symbol
        )

    def _with_auxiliary(self, snapshot: MarketSnapshot, symbol: str) -> MarketSnapshot:
        values: dict[str, DataPoint] = {}
        for source in self.auxiliary:
            values.update(source.fetch(symbol))
        return snapshot.model_copy(update={"auxiliary": values})


def load_external_context(path: str | Path) -> dict[str, DataPoint]:
    import json

    value = json.loads(Path(path).read_text(encoding="utf-8"))
    return {name: DataPoint.model_validate(point) for name, point in value.items()}
