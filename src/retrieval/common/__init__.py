# @summary
# Retrieval common package: pipeline boundary contracts, wire types, and shared exceptions.
# Exports: RAGRequest, RAGResponse, RankedResult, RetrievalError, ModelLoadError
# Deps: src.retrieval.common.schemas, src.retrieval.common.exceptions
# @end-summary
"""Pipeline boundary contracts, shared wire types, and exception hierarchy."""

from src.retrieval.common.schemas import RAGRequest, RAGResponse, RankedResult
from src.retrieval.common.exceptions import RetrievalError, ModelLoadError

__all__ = [
    "RAGRequest",
    "RAGResponse",
    "RankedResult",
    "RetrievalError",
    "ModelLoadError",
]

# --- Auto-generated re-exports (fix_encapsulation.py) ---
from src.retrieval.common.schemas import VisualPageResult
from src.retrieval.common.utils import parse_json_object
