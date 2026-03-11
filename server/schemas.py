# @summary
# Pydantic request/response models for the RAG API server.
# Exports: QueryRequest, QueryResponse, ChunkResult, HealthResponse
# Deps: pydantic
# @end-summary
"""Pydantic models for RAG API request/response serialization."""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Optional


class QueryRequest(BaseModel):
    """Incoming query from a user."""
    query: str = Field(..., min_length=1, max_length=2000, description="The search query")
    source_filter: Optional[str] = Field(None, description="Filter by source document filename")
    heading_filter: Optional[str] = Field(None, description="Filter by section heading")
    alpha: float = Field(0.5, ge=0.0, le=1.0, description="Hybrid search balance (0=BM25, 1=vector)")
    search_limit: int = Field(10, ge=1, le=100, description="Max results from hybrid search")
    rerank_top_k: int = Field(5, ge=1, le=50, description="Top-K results after reranking")


class ChunkResult(BaseModel):
    """A single retrieved chunk with its reranking score."""
    text: str
    score: float
    metadata: dict


class QueryResponse(BaseModel):
    """Full response from the RAG pipeline."""
    query: str
    processed_query: str
    query_confidence: float
    action: str
    results: list[ChunkResult] = []
    clarification_message: Optional[str] = None
    kg_expanded_terms: Optional[list[str]] = None
    generated_answer: Optional[str] = None
    workflow_id: Optional[str] = None
    latency_ms: Optional[float] = None
    stage_timings: list[dict] = Field(default_factory=list)
    timing_totals: dict = Field(default_factory=dict)


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    temporal_connected: bool
    worker_available: bool
