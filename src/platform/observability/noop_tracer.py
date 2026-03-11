"""No-op tracer for local/default use."""

from typing import Optional

from src.platform.observability.contracts import Span, Tracer
from src.platform.schemas.observability import Attributes


class NoopSpan(Span):
    """Span implementation that does nothing."""

    def set_attribute(self, key: str, value: object) -> None:
        return

    def end(self, status: str = "ok", error: Optional[Exception] = None) -> None:
        return


class NoopTracer(Tracer):
    """Tracer implementation that does nothing."""

    def start_span(
        self, name: str, attributes: Optional[Attributes] = None, parent: Optional[Span] = None
    ) -> Span:
        return NoopSpan()

