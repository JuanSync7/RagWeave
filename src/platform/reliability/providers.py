# @summary
# Retry provider factory for selecting local vs Temporal retry semantics.
# Exports: get_retry_provider
# Deps: config.settings, src.platform.reliability.local_retry
# @end-summary
"""Factory for retry providers."""

from config.settings import RETRY_PROVIDER
from src.platform.reliability.contracts import RetryProvider
from src.platform.reliability.local_retry import LocalRetryProvider


def get_retry_provider() -> RetryProvider:
    """Get the configured retry provider.

    Returns:
        A `RetryProvider` implementation selected via settings.
    """
    provider = RETRY_PROVIDER.strip().lower()
    if provider == "temporal":
        from src.platform.reliability.temporal_retry import TemporalRetryProvider

        return TemporalRetryProvider()
    return LocalRetryProvider()

