# @summary
# Retrieval package public API.
# Exports: RAGRequest, RAGChain, RAGResponse, process_query, QueryResult, QueryAction, LocalBGEReranker, RankedResult, OllamaGenerator, ConfidenceBreakdown, PostGuardrailAction, compute_composite_confidence
# Deps: src.retrieval.common, src.retrieval.pipeline, src.retrieval.query, src.retrieval.generation
# @end-summary

from src.retrieval.common.schemas import RAGRequest, RAGResponse, RankedResult
from src.retrieval.query.schemas import QueryAction, QueryResult
from src.retrieval.query.nodes.query_processor import process_query
from src.retrieval.query.nodes.reranker import LocalBGEReranker
from src.retrieval.pipeline.rag_chain import RAGChain
from src.retrieval.generation.nodes.generator import OllamaGenerator
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
]
