# @summary
# Observability facade package: tracer provider selection.
# Exports: get_tracer
# Deps: src.platform.observability.providers
# @end-summary
"""Observability providers and contracts."""

from src.platform.observability.providers import get_tracer

__all__ = ["get_tracer"]
