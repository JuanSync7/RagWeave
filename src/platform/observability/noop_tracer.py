# @summary
# No-op Tracer implementation used as a safe default/fallback.
# Exports: NoopSpan, NoopTracer
# Deps: src.platform.observability.contracts, src.platform.schemas.observability
# @end-summary
"""No-op tracer for local/default use."""

from typing import Optional

from src.platform.observability.contracts import Span, Tracer
from src.platform.schemas.observability import Attributes


class NoopSpan(Span):
    """Span implementation that does nothing."""

    def set_attribute(self, key: str, value: object) -> None:
        """Set an attribute on the span (no-op)."""
        return

    def end(self, status: str = "ok", error: Optional[Exception] = None) -> None:
        """End the span (no-op)."""
        return


class NoopTracer(Tracer):
    """Tracer implementation that does nothing."""

    def start_span(
        self, name: str, attributes: Optional[Attributes] = None, parent: Optional[Span] = None
    ) -> Span:
        """Start a span (returns a `NoopSpan`)."""
        return NoopSpan()

