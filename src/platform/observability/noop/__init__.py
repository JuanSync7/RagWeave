# @summary
# Public exports for the noop observability backend package.
# Exports: NoopBackend
# Deps: noop.backend
# @end-summary
"""Noop observability backend package.

Exports only NoopBackend — the concrete no-op implementation that is active
when OBSERVABILITY_PROVIDER is unset or set to "noop".
"""
from src.platform.observability.noop.backend import NoopBackend

__all__ = ["NoopBackend"]
