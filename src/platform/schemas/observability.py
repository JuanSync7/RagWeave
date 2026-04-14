"""Typed schemas for observability payloads.

These dataclasses define structured tracing payloads used by observability
providers and in-memory logging/export.
"""
from __future__ import annotations


from dataclasses import dataclass, field
from time import time
from typing import Optional


Attributes = dict[str, object]


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
