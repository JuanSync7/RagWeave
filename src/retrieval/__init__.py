# @summary
# Retrieval package public API.
# Exports: RAGRequest, RAGChain, RAGResponse, process_query, QueryResult, QueryAction, LocalBGEReranker, RankedResult, OllamaGenerator, ConfidenceBreakdown, PostGuardrailAction, compute_composite_confidence, warm_up_ollama, call_ollama
# Deps: src.retrieval.common, src.retrieval.pipeline, src.retrieval.query, src.retrieval.generation
# @end-summary

from src.retrieval.common import (
    RAGRequest,
    RAGResponse,
    RankedResult,
)
from src.retrieval.query import (
    QueryAction,
    QueryResult,
    warm_up_ollama,
)
from src.retrieval.query.nodes import process_query
from src.retrieval.query.nodes import LocalBGEReranker
from src.retrieval.query.nodes import _call_ollama as call_ollama
from src.retrieval.pipeline import RAGChain
from src.retrieval.generation.nodes import OllamaGenerator
from src.retrieval.generation.confidence import (
    ConfidenceBreakdown,
    PostGuardrailAction,
    compute_composite_confidence,
)

__all__ = [
    "RAGRequest",
    "RAGChain",
    "RAGResponse",
    "RankedResult",
    "process_query",
    "QueryResult",
    "QueryAction",
    "LocalBGEReranker",
    "OllamaGenerator",
    "ConfidenceBreakdown",
    "PostGuardrailAction",
    "compute_composite_confidence",
    "warm_up_ollama",
    "call_ollama",
]
