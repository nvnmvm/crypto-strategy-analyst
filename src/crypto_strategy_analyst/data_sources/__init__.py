"""Public, pluggable analysis data sources."""

from .base import MarketDataSource, normalize_symbol
from .binance_market import BinanceMarketData
from .composite import CompositeDataSource

# Backward-compatible alias used by the CLI entrypoint.
BinancePublicData = CompositeDataSource

__all__ = [
    "BinanceMarketData",
    "BinancePublicData",
    "CompositeDataSource",
    "MarketDataSource",
    "normalize_symbol",
]
