"""Domain-specific exceptions."""


class CryptoStrategyError(Exception):
    """Base exception for expected strategy failures."""


class ConfigurationError(CryptoStrategyError):
    """Raised when configuration is invalid."""


class MarketDataError(CryptoStrategyError):
    """Raised when public market data cannot be fetched or trusted."""


class InsufficientDataError(MarketDataError):
    """Raised when a calculation lacks enough historical bars."""
