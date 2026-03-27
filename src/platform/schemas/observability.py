"""Typed schemas for observability payloads.

These dataclasses define structured tracing payloads used by observability
providers and in-memory logging/export.
"""

from dataclasses import dataclass, field
from time import time
from typing import Dict, Optional


Attributes = Dict[str, object]


@dataclass
class SpanRecord:
    """In-memory span payload for structured tracing."""

    name: str
    trace_id: Optional[str] = None
    parent_span_id: Optional[str] = None
    attributes: Attributes = field(default_factory=dict)
    start_ts: float = field(default_factory=time)
    end_ts: Optional[float] = None
    status: str = "ok"
    error_message: Optional[str] = None


# Backward-compatible re-exports from the canonical location
from src.platform.observability.schemas import (  # noqa: F401, E402
    TraceRecord as TraceRecord,
    GenerationRecord as GenerationRecord,
)
