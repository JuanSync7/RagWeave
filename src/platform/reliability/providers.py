"""Factory for retry providers."""

from config.settings import RETRY_PROVIDER
from src.platform.reliability.contracts import RetryProvider
from src.platform.reliability.local_retry import LocalRetryProvider


def get_retry_provider() -> RetryProvider:
    """Get retry provider configured via environment."""
    provider = RETRY_PROVIDER.strip().lower()
    if provider == "temporal":
        from src.platform.reliability.temporal_retry import TemporalRetryProvider

        return TemporalRetryProvider()
    return LocalRetryProvider()

