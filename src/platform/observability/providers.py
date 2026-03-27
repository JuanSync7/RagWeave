# @summary
# Deprecated backward-compat shim for the old providers import path.
# Use: from src.platform.observability import get_tracer
# Deps: src.platform.observability
# @end-summary
"""Deprecated: import get_tracer from src.platform.observability instead.

This module exists only for backward compatibility during migration from
the old ``from src.platform.observability.providers import get_tracer`` pattern.
It will be removed in a future release.
"""
import warnings

warnings.warn(
    "Importing from src.platform.observability.providers is deprecated. "
    "Use 'from src.platform.observability import get_tracer' instead.",
    DeprecationWarning,
    stacklevel=2,
)

from src.platform.observability import get_tracer  # noqa: F401, E402

__all__ = ["get_tracer"]
