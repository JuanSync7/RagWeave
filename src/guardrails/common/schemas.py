# @summary
# Shared data contracts for the guardrails subsystem (backend-agnostic).
# Exports: RailVerdict, RailExecution, InputRailResult, OutputRailResult, GuardrailsMetadata
# Deps: dataclasses, enum, typing
# @end-summary
"""Shared guardrails schema contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class RailVerdict(Enum):
    """Verdict returned by a rail execution.

    Rails can either allow processing to continue unchanged, reject the request,
    or provide a modified version of the input/output payload.
    """

    PASS = "pass"
    REJECT = "reject"
    MODIFY = "modify"


@dataclass
class RailExecution:
    """Result of a single rail execution.

    Attributes:
        rail_name: Human-readable identifier for the rail.
        verdict: Overall decision for the rail.
        execution_ms: Wall-clock time spent executing the rail.
        details: Rail-specific structured metadata for debugging/telemetry.
    """

    rail_name: str
    verdict: RailVerdict
    execution_ms: float
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InputRailResult:
    """Combined result of all input rails.

    Attributes:
        intent: Detected user intent label (used for routing / policy).
        intent_confidence: Confidence score for the detected intent.
        injection_verdict: Verdict from prompt-injection checks.
        pii_redactions: Structured list of PII findings/redactions.
        redacted_query: Optional rewritten query after redaction/modification.
        toxicity_verdict: Verdict from toxicity checks.
        topic_off_topic: Whether the request is off-topic for the configured domain.
        rail_executions: Ordered per-rail execution results.
    """

    intent: str = "rag_search"
    intent_confidence: float = 1.0
    injection_verdict: RailVerdict = RailVerdict.PASS
    pii_redactions: List[Dict[str, str]] = field(default_factory=list)
    redacted_query: Optional[str] = None
    toxicity_verdict: RailVerdict = RailVerdict.PASS
    topic_off_topic: bool = False
    rail_executions: List[RailExecution] = field(default_factory=list)


@dataclass
class OutputRailResult:
    """Combined result of all output rails.

    Attributes:
        faithfulness_score: Faithfulness score for the answer against sources.
        faithfulness_verdict: Verdict derived from faithfulness checks.
        faithfulness_warning: Whether to warn the caller even if not rejecting.
        claim_scores: Optional per-claim evaluation metadata.
        pii_redactions: Structured list of PII findings/redactions.
        toxicity_verdict: Verdict from toxicity checks.
        final_answer: Optional post-processed answer text.
        rail_executions: Ordered per-rail execution results.
    """

    faithfulness_score: float = 1.0
    faithfulness_verdict: RailVerdict = RailVerdict.PASS
    faithfulness_warning: bool = False
    claim_scores: List[Dict[str, Any]] = field(default_factory=list)
    pii_redactions: List[Dict[str, str]] = field(default_factory=list)
    toxicity_verdict: RailVerdict = RailVerdict.PASS
    final_answer: Optional[str] = None
    rail_executions: List[RailExecution] = field(default_factory=list)


@dataclass
class GuardrailsMetadata:
    """Metadata embedded in `RAGResponse` for caller visibility.

    Attributes:
        enabled: Whether guardrails were enabled for this request.
        input_rails: Per-rail results for input validation/transforms.
        output_rails: Per-rail results for output validation/transforms.
        intent: Final selected intent label (if intent detection ran).
        intent_confidence: Confidence score for the final intent (if available).
        faithfulness_score: Faithfulness score (if evaluated).
        faithfulness_warning: Whether to warn on potential faithfulness issues.
        total_rail_ms: Aggregate wall-clock time spent in rails.
    """

    enabled: bool = True
    input_rails: List[RailExecution] = field(default_factory=list)
    output_rails: List[RailExecution] = field(default_factory=list)
    intent: Optional[str] = None
    intent_confidence: Optional[float] = None
    faithfulness_score: Optional[float] = None
    faithfulness_warning: bool = False
    total_rail_ms: float = 0.0
