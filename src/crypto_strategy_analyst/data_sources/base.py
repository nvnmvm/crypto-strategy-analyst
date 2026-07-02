from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import DataPoint, MarketSnapshot


def normalize_symbol(symbol: str) -> str:
    return symbol.upper().replace("/", "").replace("-", "").replace("_", "")


def display_symbol(symbol: str) -> str:
    normalized = normalize_symbol(symbol)
    for quote in ("USDT", "USDC", "BTC", "ETH", "BNB"):
        if normalized.endswith(quote) and len(normalized) > len(quote):
            return f"{normalized[: -len(quote)]}/{quote}"
    return normalized


class MarketDataSource(ABC):
    @abstractmethod
    def snapshot(self, symbol: str, timeframes: list[str], limit: int) -> MarketSnapshot: ...


class AuxiliarySource(ABC):
    @abstractmethod
    def fetch(self, symbol: str) -> dict[str, DataPoint]: ...
