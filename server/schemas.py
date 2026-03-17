# @summary
# Pydantic request/response models for the RAG API server.
# Exports: QueryRequest, QueryResponse, ChunkResult, HealthResponse
# Deps: pydantic
# @end-summary
"""Pydantic models for RAG API request/response serialization."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Optional

from server.common.schemas import ApiErrorDetail, ApiErrorResponse, ConsoleEnvelope


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
    conversation_id: Optional[str] = Field(
        None,
        min_length=3,
        max_length=128,
        description="Conversation identifier for multi-turn memory",
    )
    memory_enabled: bool = Field(
        default=True,
        description="Whether conversation memory should be applied",
    )
    memory_turn_window: Optional[int] = Field(
        default=None,
        ge=1,
        le=40,
        description="Optional override for number of recent turns injected as context",
    )
    compact_now: bool = Field(
        default=False,
        description="Force a summary compaction pass for the conversation after this turn",
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


class TokenBudgetResponse(BaseModel):
    """Token budget snapshot included in query responses."""

    input_tokens: int = 0
    context_length: int = 0
    output_reservation: int = 0
    usage_percent: float = 0.0
    model_name: str = ""
    breakdown: Optional[dict] = None
    actual_prompt_tokens: int = 0
    actual_completion_tokens: int = 0
    actual_total_tokens: int = 0
    cost_usd: float = 0.0


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
    conversation_id: Optional[str] = None
    token_budget: Optional[TokenBudgetResponse] = None


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


class ConsoleQueryRequest(BaseModel):
    """Console query request supporting both stream and non-stream modes."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=2000)
    stream: bool = Field(default=True)
    source_filter: Optional[str] = None
    heading_filter: Optional[str] = None
    alpha: float = Field(default=0.5, ge=0.0, le=1.0)
    search_limit: int = Field(default=10, ge=1, le=100)
    rerank_top_k: int = Field(default=5, ge=1, le=50)
    tenant_id: Optional[str] = None
    max_query_iterations: Optional[int] = Field(default=None, ge=1, le=8)
    fast_path: Optional[bool] = None
    overall_timeout_ms: Optional[int] = Field(default=None, ge=1000, le=180000)
    stage_budget_overrides: dict[str, int] = Field(default_factory=dict)
    conversation_id: Optional[str] = Field(default=None, min_length=3, max_length=128)
    memory_enabled: bool = Field(default=True)
    memory_turn_window: Optional[int] = Field(default=None, ge=1, le=40)
    compact_now: bool = Field(default=False)


class ConsoleIngestionRequest(BaseModel):
    """Console ingestion request for file, directory, or full documents ingestion."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["single_file", "directory", "all_documents"] = Field(
        default="all_documents"
    )
    target_path: Optional[str] = Field(
        default=None,
        description="Required for single_file and directory modes",
    )
    update_mode: bool = Field(default=True)
    build_kg: bool = Field(default=True)
    export_obsidian: bool = Field(default=False)
    semantic_chunking: bool = Field(default=True)
    export_processed: bool = Field(default=False)
    verbose_stages: Optional[bool] = None
    persist_refactor_mirror: Optional[bool] = None
    docling_enabled: Optional[bool] = None
    docling_model: Optional[str] = None
    docling_artifacts_path: Optional[str] = None
    docling_strict: Optional[bool] = None
    docling_auto_download: Optional[bool] = None
    vision_enabled: Optional[bool] = None
    vision_provider: Optional[Literal["ollama", "openai_compatible"]] = None
    vision_model: Optional[str] = None
    vision_api_base_url: Optional[str] = None
    vision_timeout_seconds: Optional[int] = Field(default=None, ge=5, le=600)
    vision_max_figures: Optional[int] = Field(default=None, ge=1, le=32)
    vision_auto_pull: Optional[bool] = None
    vision_strict: Optional[bool] = None


class ConsoleCommandRequest(BaseModel):
    """Unified slash-command request for console query/ingest surfaces."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["query", "ingest"] = Field(default="query")
    command: str = Field(..., min_length=1, max_length=100)
    arg: Optional[str] = Field(default=None, max_length=2000)
    state: dict[str, Any] = Field(default_factory=dict)


class ConsoleLogsResponse(BaseModel):
    """Log snapshot payload for the console."""

    files: list[str] = Field(default_factory=list)
    lines: list[str] = Field(default_factory=list)


class ConsoleHealthSummary(BaseModel):
    """Extended health payload used in console panel."""

    status: str
    temporal_connected: bool
    worker_available: bool
    ollama_reachable: bool


class ConversationCreateRequest(BaseModel):
    title: str = Field(default="New conversation", max_length=200)
    conversation_id: Optional[str] = Field(default=None, min_length=3, max_length=128)


class ConversationMetaResponse(BaseModel):
    conversation_id: str
    tenant_id: str
    subject: str
    project_id: str = ""
    title: str = ""
    created_at_ms: int
    updated_at_ms: int
    message_count: int
    summary: dict = Field(default_factory=dict)


class ConversationTurnResponse(BaseModel):
    role: str
    content: str
    timestamp_ms: int
    query_id: str = ""


class ConversationHistoryResponse(BaseModel):
    conversation_id: str
    turns: list[ConversationTurnResponse] = Field(default_factory=list)


class ConversationCompactRequest(BaseModel):
    conversation_id: str = Field(..., min_length=3, max_length=128)
