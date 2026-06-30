"""Domain-specific exceptions."""


class CryptoStrategyError(Exception):
    """Base exception for expected strategy failures."""


class ConfigurationError(CryptoStrategyError):
    """Raised when configuration is invalid."""


class MarketDataError(CryptoStrategyError):
    """Raised when public market data cannot be fetched or trusted."""


class InsufficientDataError(MarketDataError):
    """Raised when a calculation lacks enough historical bars."""


class RiskStateError(CryptoStrategyError):
    """Raised when persisted risk state is missing required integrity."""


class PositionConstraintError(CryptoStrategyError):
    """Raised when a risk-sized position cannot satisfy public spot rules."""


class DatasetIntegrityError(CryptoStrategyError):
    """Raised when an offline dataset snapshot fails manifest verification."""
