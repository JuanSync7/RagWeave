# @summary
# Retrieval package public API.
# Exports: RAGRequest, RAGChain, RAGResponse, process_query, QueryResult, QueryAction, LocalBGEReranker, RankedResult, OllamaGenerator, ConfidenceBreakdown, PostGuardrailAction, compute_composite_confidence
# Deps: src.retrieval.common, src.retrieval.pipeline, src.retrieval.query, src.retrieval.generation
# @end-summary

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

_lazy = {
    "RAGRequest": ("src.retrieval.common", "RAGRequest"),
    "RAGResponse": ("src.retrieval.common", "RAGResponse"),
    "RankedResult": ("src.retrieval.common", "RankedResult"),
    "QueryAction": ("src.retrieval.query", "QueryAction"),
    "QueryResult": ("src.retrieval.query", "QueryResult"),
    "process_query": ("src.retrieval.query.nodes", "process_query"),
    "LocalBGEReranker": ("src.retrieval.query.nodes", "LocalBGEReranker"),
    "RAGChain": ("src.retrieval.pipeline", "RAGChain"),
    "OllamaGenerator": ("src.retrieval.generation.nodes", "OllamaGenerator"),
    "ConfidenceBreakdown": ("src.retrieval.generation.confidence", "ConfidenceBreakdown"),
    "PostGuardrailAction": ("src.retrieval.generation.confidence", "PostGuardrailAction"),
    "compute_composite_confidence": ("src.retrieval.generation.confidence", "compute_composite_confidence"),
}


def __getattr__(name: str):
    if name in _lazy:
        import importlib
        mod_name, attr = _lazy[name]
        mod = importlib.import_module(mod_name)
        return getattr(mod, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
