# @summary
# Framework-agnostic public contracts for the LLM composition layer.
# Exports: ModelTier, OutputResult, ParallelResult, BatchResult,
#          FallbackResult, StreamEvent, StreamFrame, StepStatus,
#          StepResult, GateDecision, ConversationMessage, MessageRole
# Deps: dataclasses, enum
# @end-summary
"""Public schemas for src.common.llm.

All types that cross the boundary between caller code and the LLM layer
live here.  Nothing in this module imports from LangChain, LiteLLM, or
any other framework — callers depend only on stdlib types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── Provider ─────────────────────────────────────────────────────────────

class ModelTier(str, Enum):
    """Cost / capability tiers — provider-agnostic."""

    HIGH = "high"        # Opus, GPT-4o
    MEDIUM = "medium"    # Sonnet, GPT-4o-mini
    LOW = "low"          # Haiku, small cloud models
    LOCAL = "local"      # Ollama, vLLM


# ── Structured Output ────────────────────────────────────────────────────

@dataclass
class OutputResult:
    """Return value of ``structured_output()``."""

    parsed: Any
    """The validated Pydantic / dataclass object."""

    raw: str = ""
    """Raw LLM response text (useful for debugging)."""

    auto_fixed: bool = False
    """True if the auto-fix parser had to intervene."""

    model_used: str = ""
    """Which model actually produced the response."""


# ── Parallel ─────────────────────────────────────────────────────────────

@dataclass
class ParallelResult:
    """Return value of ``parallel()``."""

    results: dict[str, Any] = field(default_factory=dict)
    """Named results keyed by the task name."""

    timings: dict[str, float] = field(default_factory=dict)
    """Wall-clock seconds per task."""

    errors: dict[str, Exception] = field(default_factory=dict)
    """Tasks that raised — partial success is OK."""


# ── Batch ────────────────────────────────────────────────────────────────

@dataclass
class BatchResult:
    """Return value of ``batch()``."""

    succeeded: list[Any] = field(default_factory=list)
    failed: list[tuple[Any, Exception]] = field(default_factory=list)
    """(input_item, exception) pairs for items that errored."""

    total: int = 0
    concurrency: int = 1


# ── Fallback ─────────────────────────────────────────────────────────────

@dataclass
class FallbackResult:
    """Return value of ``fallback_chain()``."""

    result: Any = None
    strategy_used: int = 0
    """0-indexed: which strategy succeeded."""

    strategies_tried: int = 0
    """How many strategies were attempted before success."""


# ── Stream ───────────────────────────────────────────────────────────────

class StreamEvent(str, Enum):
    """Event types emitted during streaming execution."""

    LLM_TOKEN = "llm_token"
    STEP_START = "step_start"
    STEP_END = "step_end"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ERROR = "error"


@dataclass
class StreamFrame:
    """Single event from ``stream()``."""

    event: StreamEvent
    data: Any
    step_name: str | None = None
    elapsed_ms: float = 0.0


# ── Graph / Workflow ─────────────────────────────────────────────────────

class StepStatus(str, Enum):
    """Status of a workflow step."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING = "waiting"  # paused at human gate


@dataclass
class StepResult:
    """Return value of a single workflow step."""

    status: StepStatus
    output: Any = None
    error: str | None = None


@dataclass
class GateDecision:
    """Return value of ``human_gate()`` after resume."""

    approved: bool
    input: str | None = None
    """Human's response text (None if provisional was used)."""

    provisional: bool = False
    """True if no human responded and provisional value was used."""


# ── Memory / Conversation ────────────────────────────────────────────────

class MessageRole(str, Enum):
    """Chat message roles."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class ConversationMessage:
    """A single message in a conversation history."""

    role: MessageRole
    content: str


__all__ = [
    "ModelTier",
    "OutputResult",
    "ParallelResult",
    "BatchResult",
    "FallbackResult",
    "StreamEvent",
    "StreamFrame",
    "StepStatus",
    "StepResult",
    "GateDecision",
    "MessageRole",
    "ConversationMessage",
]
