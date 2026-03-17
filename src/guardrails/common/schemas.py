# @summary
# Shared data contracts for the NeMo Guardrails integration.
# Exports: RailVerdict, RailExecution, InputRailResult, OutputRailResult, GuardrailsMetadata
# Deps: dataclasses, enum, typing
# @end-summary
"""Shared guardrails schema contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class RailVerdict(Enum):
    """Verdict returned by a rail execution."""

    PASS = "pass"
    REJECT = "reject"
    MODIFY = "modify"


@dataclass
class RailExecution:
    """Result of a single rail execution."""

    rail_name: str
    verdict: RailVerdict
    execution_ms: float
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InputRailResult:
    """Combined result of all input rails."""

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
    """Combined result of all output rails."""

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
    """Metadata embedded in RAGResponse for caller visibility."""

    enabled: bool = True
    input_rails: List[RailExecution] = field(default_factory=list)
    output_rails: List[RailExecution] = field(default_factory=list)
    intent: Optional[str] = None
    intent_confidence: Optional[float] = None
    faithfulness_score: Optional[float] = None
    faithfulness_warning: bool = False
    total_rail_ms: float = 0.0
