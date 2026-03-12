"""Langfuse-backed tracer implementation."""

import logging
from typing import Optional

from src.platform.observability.contracts import Span, Tracer
from src.platform.schemas.observability import Attributes

logger = logging.getLogger("rag.observability.langfuse")


class LangfuseSpan(Span):
    """Lightweight span wrapper over Langfuse generations/spans."""

    def __init__(self, inner_span):
        self._inner = inner_span

    def set_attribute(self, key: str, value: object) -> None:
        try:
            self._inner.update(metadata={key: value})
        except Exception as exc:  # pragma: no cover
            logger.warning("Langfuse set_attribute failed: %s", exc)

    def end(self, status: str = "ok", error: Optional[Exception] = None) -> None:
        try:
            if error:
                self._inner.update(level="ERROR", status_message=str(error))
            elif status != "ok":
                self._inner.update(level="WARNING", status_message=status)
            self._inner.end()
        except Exception as exc:  # pragma: no cover
            logger.warning("Langfuse span end failed: %s", exc)


class LangfuseTracer(Tracer):
    """Langfuse tracer with fail-open behavior."""

    def __init__(self):
        try:
            from langfuse import get_client
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "Langfuse SDK not installed. Install `langfuse` to enable tracing."
            ) from exc
        self._client = get_client()

    def start_span(
        self, name: str, attributes: Optional[Attributes] = None, parent: Optional[Span] = None
    ) -> Span:
        try:
            metadata = attributes or {}
            if isinstance(parent, LangfuseSpan):
                span = parent._inner.start_observation(
                    as_type="span",
                    name=name,
                    metadata=metadata,
                )
            else:
                span = self._client.start_observation(
                    as_type="span",
                    name=name,
                    metadata=metadata,
                )
            return LangfuseSpan(span)
        except Exception as exc:  # pragma: no cover
            logger.warning("Langfuse start_span failed: %s", exc)
            from src.platform.observability.noop_tracer import NoopSpan

            return NoopSpan()

