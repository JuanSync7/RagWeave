# @summary
# Retrieval common package: pipeline boundary contracts and cross-cutting wire types.
# Exports: RAGRequest, RAGResponse, RankedResult
# Deps: src.retrieval.common.schemas
# @end-summary
"""Pipeline boundary contracts and shared wire types."""

from src.retrieval.common.schemas import RAGRequest, RAGResponse, RankedResult

__all__ = ["RAGRequest", "RAGResponse", "RankedResult"]
