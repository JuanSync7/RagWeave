# @summary
# Pydantic request/response models for the RAG API server.
# Exports: QueryRequest, QueryResponse, ChunkResult, HealthResponse
# Deps: pydantic
# @end-summary
"""Pydantic models for RAG API request/response serialization."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Optional


class QueryRequest(BaseModel):
    """Incoming query from a user."""
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=2000, description="The search query")
    source_filter: Optional[str] = Field(None, description="Filter by source document filename")
    heading_filter: Optional[str] = Field(None, description="Filter by section heading")
    alpha: float = Field(0.5, ge=0.0, le=1.0, description="Hybrid search balance (0=BM25, 1=vector)")
    search_limit: int = Field(10, ge=1, le=100, description="Max results from hybrid search")
    rerank_top_k: int = Field(5, ge=1, le=50, description="Top-K results after reranking")
    tenant_id: Optional[str] = Field(None, description="Optional tenant override for admins")
    max_query_iterations: Optional[int] = Field(
        None,
        ge=1,
        le=8,
        description="Cap for reformulation iterations",
    )
    fast_path: Optional[bool] = Field(
        None,
        description="Enable fast-path mode to bypass iterative reformulation",
    )
    overall_timeout_ms: Optional[int] = Field(
        None,
        ge=1000,
        le=180000,
        description="Overall retrieval timeout budget",
    )
    stage_budget_overrides: dict[str, int] = Field(
        default_factory=dict,
        description="Optional per-stage budget overrides in milliseconds",
    )

    @model_validator(mode="after")
    def _validate_stage_budget_overrides(self) -> "QueryRequest":
        allowed = {
            "query_processing",
            "kg_expansion",
            "embedding",
            "hybrid_search",
            "reranking",
            "generation",
        }
        for stage, budget_ms in self.stage_budget_overrides.items():
            if stage not in allowed:
                raise ValueError(
                    f"Invalid stage budget key '{stage}'. Allowed: {sorted(allowed)}"
                )
            if int(budget_ms) < 100 or int(budget_ms) > 300000:
                raise ValueError(
                    f"Stage budget for '{stage}' must be between 100 and 300000 ms"
                )
        return self


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
    budget_exhausted: bool = False
    budget_exhausted_stage: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    temporal_connected: bool
    worker_available: bool


class CreateApiKeyRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=200)
    tenant_id: Optional[str] = Field(None, description="Tenant bound to this key")
    roles: list[str] = Field(default_factory=lambda: ["query"])
    description: str = Field(default="", max_length=300)


class ApiKeyRecord(BaseModel):
    key_id: str
    subject: str
    tenant_id: str
    roles: list[str]
    description: str = ""
    created_at: int
    revoked_at: Optional[int] = None


class CreateApiKeyResponse(ApiKeyRecord):
    api_key: str


class QuotaUpdateRequest(BaseModel):
    requests_per_minute: int = Field(..., ge=1, le=100000)


class QuotasResponse(BaseModel):
    defaults: dict
    tenants: dict
    projects: dict


class QuotaSetResponse(BaseModel):
    """Payload for tenant quota upsert operations."""
    tenant_id: str
    requests_per_minute: int


class StatusResponse(BaseModel):
    """Standard status payload for simple mutating admin endpoints."""
    status: str
    key_id: Optional[str] = None
    tenant_id: Optional[str] = None


class RootResponse(BaseModel):
    """Root endpoint service metadata."""
    service: str
    docs: str
    health: str
    query_endpoint: str


class ApiErrorDetail(BaseModel):
    """Structured error detail payload."""
    code: str
    message: str
    details: Optional[dict] = None


class ApiErrorResponse(BaseModel):
    """Standardized API error envelope for all non-2xx responses."""
    ok: bool = False
    error: ApiErrorDetail
    request_id: Optional[str] = None
