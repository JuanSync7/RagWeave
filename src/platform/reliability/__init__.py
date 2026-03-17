# @summary
# Reliability facade package: retry provider selection.
# Exports: get_retry_provider
# Deps: src.platform.reliability.providers
# @end-summary
"""Reliability providers and contracts."""

from src.platform.reliability.providers import get_retry_provider

__all__ = ["get_retry_provider"]
