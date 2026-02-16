"""Custom exception hierarchy for the PilotAI Credit Spreads system."""


class PilotAIError(Exception):
    """Base exception for all PilotAI errors."""


class DataFetchError(PilotAIError):
    """Raised when data fetching (e.g. yfinance download) fails."""


class ProviderError(PilotAIError):
    """Raised when a provider API call (Tradier, Polygon, Alpaca) fails."""


class StrategyError(PilotAIError):
    """Raised on strategy execution errors."""


class ModelError(PilotAIError):
    """Raised on ML model errors (training, prediction, loading)."""


class ConfigError(PilotAIError):
    """Raised on configuration errors."""
