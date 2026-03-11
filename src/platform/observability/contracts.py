"""Observability contracts used by the pipeline."""

from abc import ABC, abstractmethod
from typing import Optional

from src.platform.schemas.observability import Attributes


class Span(ABC):
    """Abstract tracing span."""

    @abstractmethod
    def set_attribute(self, key: str, value: object) -> None:
        """Set an attribute on the span."""

    @abstractmethod
    def end(self, status: str = "ok", error: Optional[Exception] = None) -> None:
        """End the span."""


class Tracer(ABC):
    """Abstract tracer interface."""

    @abstractmethod
    def start_span(
        self, name: str, attributes: Optional[Attributes] = None, parent: Optional[Span] = None
    ) -> Span:
        """Start and return a span."""

