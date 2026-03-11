"""Typed schemas for observability payloads."""

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
