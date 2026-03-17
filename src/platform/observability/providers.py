# @summary
# Observability provider factory for selecting a Tracer implementation.
# Exports: get_tracer
# Deps: config.settings, logging, src.platform.observability.noop_tracer
# @end-summary
"""Factory for observability providers."""

import logging

from config.settings import OBSERVABILITY_PROVIDER
from src.platform.observability.contracts import Tracer
from src.platform.observability.noop_tracer import NoopTracer

logger = logging.getLogger("rag.observability")


def get_tracer() -> Tracer:
    """Get the configured tracer.

    Returns:
        A `Tracer` implementation selected via settings. Falls back to `NoopTracer`
        on any initialization failure.
    """
    provider = OBSERVABILITY_PROVIDER.strip().lower()
    if provider == "langfuse":
        try:
            from src.platform.observability.langfuse_tracer import LangfuseTracer

            return LangfuseTracer()
        except Exception as exc:
            logger.warning("Failed to initialize Langfuse tracer; using noop: %s", exc)
    return NoopTracer()

