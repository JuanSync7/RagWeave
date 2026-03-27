# @summary
# No-op observability backend — all methods are zero-cost no-ops.
# Exports: NoopBackend, NoopSpan, NoopTrace, NoopGeneration
# Deps: src.platform.observability.backend
# @end-summary
"""No-op implementation of the observability backend.

Active when OBSERVABILITY_PROVIDER is unset or set to "noop".
Also used as the fallback when the configured backend fails to initialize.
All methods return typed no-op objects immediately with zero I/O.
"""
from __future__ import annotations

from typing import Optional

from src.platform.observability.backend import (
    Generation,
    ObservabilityBackend,
    Span,
    Trace,
)


class NoopSpan(Span):
    """Span implementation that does nothing."""

    def set_attribute(self, key: str, value: object) -> None:
        """Set attribute (no-op). Accepts any input, never raises."""
        return

    def end(self, status: str = "ok", error: Optional[Exception] = None) -> None:
        """End span (no-op). Accepts any input, never raises."""
        return


class NoopGeneration(Generation):
    """Generation implementation that does nothing."""

    def set_output(self, output: str) -> None:
        """Record output (no-op). Accepts any input, never raises."""
        return

    def set_token_counts(self, prompt_tokens: int, completion_tokens: int) -> None:
        """Record token counts (no-op). Accepts any input, never raises."""
        return

    def end(self, status: str = "ok", error: Optional[Exception] = None) -> None:
        """End generation (no-op). Accepts any input, never raises."""
        return


class NoopTrace(Trace):
    """Trace implementation that returns no-op children."""

    def span(self, name: str, attributes: Optional[dict] = None) -> Span:
        """Return a NoopSpan. Accepts any input, never raises."""
        return NoopSpan()

    def generation(
        self,
        name: str,
        model: str,
        input: str,
        metadata: Optional[dict] = None,
    ) -> Generation:
        """Return a NoopGeneration. Accepts any input, never raises."""
        return NoopGeneration()


class NoopBackend(ObservabilityBackend):
    """Observability backend that performs no operations.

    Active when OBSERVABILITY_PROVIDER is unset or set to "noop".
    Also used as the fallback when the configured backend fails to initialize.
    All methods return typed no-op objects immediately with zero I/O.
    """

    def span(
        self,
        name: str,
        attributes: Optional[dict] = None,
        parent: Optional[Span] = None,
    ) -> Span:
        """Return a NoopSpan immediately."""
        return NoopSpan()

    def trace(self, name: str, metadata: Optional[dict] = None) -> Trace:
        """Return a NoopTrace immediately."""
        return NoopTrace()

    def generation(
        self,
        name: str,
        model: str,
        input: str,
        metadata: Optional[dict] = None,
    ) -> Generation:
        """Return a NoopGeneration immediately."""
        return NoopGeneration()

    def flush(self) -> None:
        """Flush (no-op). Returns immediately."""
        return

    def shutdown(self) -> None:
        """Shutdown (no-op). Returns immediately."""
        return
