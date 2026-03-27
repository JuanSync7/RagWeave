# @summary
# Record dataclasses for in-memory span, trace, and generation data.
# Exports: SpanRecord, TraceRecord, GenerationRecord
# Deps: dataclasses, time, typing
# @end-summary
"""Provider-agnostic record types for the observability subsystem.

These dataclasses capture completed span/trace/generation data in memory.
They are importable without any third-party SDK installed and are used
by tests, the noop backend, and storage adapters.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Optional


@dataclass
class SpanRecord:
    """In-memory record for a completed span observation.

    Produced when Span.end() is called. Used for testing assertions
    and noop backend record capture.
    """

    name: str                                      # REQ-149
    trace_id: str                                  # REQ-149
    parent_span_id: Optional[str]                  # REQ-149
    attributes: dict = field(default_factory=dict) # REQ-149
    start_ts: float = field(default_factory=time)  # REQ-155
    end_ts: Optional[float] = None                 # REQ-155 — set by end()
    status: str = "ok"                             # REQ-117, REQ-149
    error_message: Optional[str] = None            # REQ-117, REQ-149


@dataclass
class TraceRecord:
    """In-memory record for a completed trace root.

    Produced when a Trace context manager exits or is manually closed.
    """

    name: str                                      # REQ-151
    trace_id: str                                  # REQ-151 — must not be None
    metadata: dict = field(default_factory=dict)   # REQ-151
    start_ts: float = field(default_factory=time)  # REQ-155
    end_ts: Optional[float] = None                 # REQ-155 — set by end()
    status: str = "ok"                             # REQ-151


@dataclass
class GenerationRecord:
    """In-memory record for a completed LLM generation observation.

    output, prompt_tokens, completion_tokens are optional because
    set_output() and set_token_counts() may not be called before end()
    in error paths or streaming scenarios.
    """

    name: str                                       # REQ-153
    trace_id: str                                   # REQ-153
    model: str                                      # REQ-153
    input: str                                      # REQ-153
    output: Optional[str] = None                    # REQ-153
    prompt_tokens: Optional[int] = None             # REQ-153
    completion_tokens: Optional[int] = None         # REQ-153
    start_ts: float = field(default_factory=time)   # REQ-155
    end_ts: Optional[float] = None                  # REQ-155
    status: str = "ok"                              # REQ-153
