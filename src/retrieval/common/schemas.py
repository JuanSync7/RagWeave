# @summary
# Shared retrieval schema contracts and dataclasses used across query processor, reranker, and rag chain.
# Exports: QueryAction, QueryResult, QueryState, RankedResult, RAGResponse
# Deps: dataclasses, enum, typing
# @end-summary
"""Shared retrieval schema contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict, TYPE_CHECKING

if TYPE_CHECKING:
    from src.platform.token_budget.schemas import TokenBudgetSnapshot


class QueryAction(Enum):
    """Action to take after query processing."""

    SEARCH = "search"
    ASK_USER = "ask_user"


@dataclass
class QueryResult:
    """Result of the query processing pipeline."""

    processed_query: str
    confidence: float
    action: QueryAction
    clarification_message: Optional[str] = None
    iterations: int = 0


class QueryState(TypedDict):
    """LangGraph state schema for query processing."""

    original_query: str
    current_query: str
    confidence: float
    reasoning: str
    iteration: int
    max_iterations: int
    confidence_threshold: float
    action: str
    clarification_message: str
    ollama_available: bool
    fast_path: bool


@dataclass
class RankedResult:
    """A search result with its reranking score."""

    text: str
    score: float
    metadata: dict


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
