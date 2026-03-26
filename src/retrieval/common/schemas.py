# @summary
# Pipeline boundary contracts: input/output schemas and the cross-cutting wire type.
# Exports: RAGRequest, RAGResponse, RankedResult
# Deps: dataclasses, typing
# @end-summary
"""Pipeline-level schema contracts — what enters and exits the RAG pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.platform.token_budget.schemas import TokenBudgetSnapshot


@dataclass
class RankedResult:
    """A search result with its reranking score.

    Wire type that flows from query (reranker output) through to generation.
    """

    text: str
    score: float
    metadata: dict


@dataclass
class RAGRequest:
    """Input contract for the RAG pipeline.

    Optional numeric fields default to None — the pipeline fills in
    config defaults when None, keeping this schema config-free.
    """

    query: str
    alpha: Optional[float] = None
    search_limit: Optional[int] = None
    rerank_top_k: Optional[int] = None
    source_filter: Optional[str] = None
    heading_filter: Optional[str] = None
    tenant_id: Optional[str] = None
    skip_generation: bool = False
    fast_path: Optional[bool] = None
    memory_context: Optional[str] = None
    memory_recent_turns: Optional[List[Dict[str, str]]] = None
    conversation_id: Optional[str] = None
    overall_timeout_ms: Optional[int] = None
    stage_budget_overrides: Optional[Dict[str, int]] = None
    max_query_iterations: Optional[int] = None


@dataclass
class RAGResponse:
    """Complete response from the retrieval pipeline."""

    query: str
    processed_query: str
    query_confidence: float
    action: str
    results: List[RankedResult] = field(default_factory=list)
    clarification_message: Optional[str] = None
    kg_expanded_terms: Optional[List[str]] = None
    generated_answer: Optional[str] = None
    stage_timings: List[Dict[str, Any]] = field(default_factory=list)
    timing_totals: Dict[str, float] = field(default_factory=dict)
    budget_exhausted: bool = False
    budget_exhausted_stage: Optional[str] = None
    conversation_id: Optional[str] = None
    guardrails: Optional[Dict[str, Any]] = None
    token_budget: Optional["TokenBudgetSnapshot"] = None
    composite_confidence: Optional[float] = None
    confidence_breakdown: Optional[Dict[str, Any]] = None
    post_guardrail_action: Optional[str] = None
    version_conflicts: Optional[List[Dict[str, Any]]] = None
    retry_count: int = 0
    verification_warning: Optional[str] = None
    retrieval_quality: Optional[str] = None  # "strong" | "moderate" | "weak" | "insufficient"
    retrieval_quality_note: Optional[str] = None
    re_retrieval_suggested: bool = False
    re_retrieval_params: Optional[Dict[str, Any]] = None
