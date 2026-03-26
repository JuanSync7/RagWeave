# @summary
# Shared ingestion pipeline dataclasses, typed state schema, runtime container, and node-name registry.
# Exports: IngestionConfig, IngestionDesignCheck, IngestionRunSummary, Runtime, IngestState, PIPELINE_NODE_NAMES
# Deps: config.settings, src.core.embeddings, src.core.knowledge_graph, src.ingest.common.schemas
# @end-summary

"""Shared ingestion pipeline types, configuration, and state contracts.

This module defines the ingestion pipeline's primary configuration dataclass,
runtime dependency container, and the shared LangGraph state schema used across
pipeline nodes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TypedDict

from config.settings import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    OLLAMA_BASE_URL,
    VECTOR_COLLECTION_DEFAULT,
    RAG_INGESTION_ENABLE_CROSS_REFERENCE_EXTRACTION,
    RAG_INGESTION_DOCLING_ARTIFACTS_PATH,
    RAG_INGESTION_DOCLING_AUTO_DOWNLOAD,
    RAG_INGESTION_DOCLING_ENABLED,
    RAG_INGESTION_DOCLING_MODEL,
    RAG_INGESTION_DOCLING_STRICT,
    RAG_INGESTION_ENABLE_DOCUMENT_REFACTORING,
    RAG_INGESTION_ENABLE_KNOWLEDGE_GRAPH_EXTRACTION,
    RAG_INGESTION_ENABLE_KNOWLEDGE_GRAPH_STORAGE,
    RAG_INGESTION_ENABLE_MULTIMODAL_PROCESSING,
    RAG_INGESTION_ENABLE_QUALITY_VALIDATION,
    RAG_INGESTION_VISION_AUTO_PULL,
    RAG_INGESTION_VISION_ENABLED,
    RAG_INGESTION_VISION_MAX_FIGURES,
    RAG_INGESTION_VISION_MAX_IMAGE_BYTES,
    RAG_INGESTION_VISION_MAX_TOKENS,
    RAG_INGESTION_VISION_MODEL,
    RAG_INGESTION_VISION_PROVIDER,
    RAG_INGESTION_VISION_API_BASE_URL,
    RAG_INGESTION_VISION_API_KEY,
    RAG_INGESTION_VISION_API_PATH,
    RAG_INGESTION_VISION_STRICT,
    RAG_INGESTION_VISION_TEMPERATURE,
    RAG_INGESTION_VISION_TIMEOUT_SECONDS,
    RAG_INGESTION_LLM_ENABLED,
    RAG_INGESTION_LLM_MAX_KEYWORDS,
    RAG_INGESTION_LLM_MODEL,
    RAG_INGESTION_LLM_TEMPERATURE,
    RAG_INGESTION_LLM_TIMEOUT_SECONDS,
    RAG_INGESTION_MIRROR_DIR,
    RAG_INGESTION_PERSIST_REFACTOR_MIRROR,
    RAG_INGESTION_VERBOSE_STAGE_LOGS,
    SEMANTIC_CHUNKING_ENABLED,
)
from src.core.embeddings import LocalBGEEmbeddings
from src.core.knowledge_graph import KnowledgeGraphBuilder
from src.ingest.common.schemas import ProcessedChunk

PIPELINE_NODE_NAMES = [
    "document_ingestion",
    "structure_detection",
    "multimodal_processing",
    "text_cleaning",
    "document_refactoring",
    "chunking",
    "chunk_enrichment",
    "metadata_generation",
    "cross_reference_extraction",
    "knowledge_graph_extraction",
    "quality_validation",
    "embedding_storage",
    "knowledge_graph_storage",
]


@dataclass
class IngestionConfig:
    """Configuration knobs controlling ingestion behavior and optional stages.

    LLM routing (model selection, provider, retries, fallbacks) is handled by
    ``src.platform.llm.LLMProvider`` via LiteLLM Router.  Fields like
    ``llm_model``, ``ollama_url``, ``vision_provider``, ``vision_api_base_url``
    are retained for backward compatibility and metadata logging but are **not**
    used for HTTP calls — LiteLLM handles that via ``RAG_LLM_*`` env vars or
    the Router YAML config.
    """

    # ── LLM behavioral flags (still active) ────────────────────────────
    llm_temperature: float = RAG_INGESTION_LLM_TEMPERATURE
    llm_timeout_seconds: int = RAG_INGESTION_LLM_TIMEOUT_SECONDS
    max_keywords: int = RAG_INGESTION_LLM_MAX_KEYWORDS
    enable_llm_metadata: bool = RAG_INGESTION_LLM_ENABLED
    # Retained for metadata logging; routing handled by LiteLLM Router.
    llm_model: str = RAG_INGESTION_LLM_MODEL
    enable_docling_parser: bool = RAG_INGESTION_DOCLING_ENABLED
    docling_model: str = RAG_INGESTION_DOCLING_MODEL
    docling_artifacts_path: str = RAG_INGESTION_DOCLING_ARTIFACTS_PATH
    docling_strict: bool = RAG_INGESTION_DOCLING_STRICT
    docling_auto_download: bool = RAG_INGESTION_DOCLING_AUTO_DOWNLOAD
    semantic_chunking: bool = SEMANTIC_CHUNKING_ENABLED
    chunk_size: int = CHUNK_SIZE
    chunk_overlap: int = CHUNK_OVERLAP
    enable_multimodal_processing: bool = RAG_INGESTION_ENABLE_MULTIMODAL_PROCESSING
    # ── Vision behavioral flags (still active) ────────────────────────
    enable_vision_processing: bool = RAG_INGESTION_VISION_ENABLED
    vision_timeout_seconds: int = RAG_INGESTION_VISION_TIMEOUT_SECONDS
    vision_max_figures: int = RAG_INGESTION_VISION_MAX_FIGURES
    vision_max_image_bytes: int = RAG_INGESTION_VISION_MAX_IMAGE_BYTES
    vision_temperature: float = RAG_INGESTION_VISION_TEMPERATURE
    vision_max_tokens: int = RAG_INGESTION_VISION_MAX_TOKENS
    vision_auto_pull: bool = RAG_INGESTION_VISION_AUTO_PULL
    vision_strict: bool = RAG_INGESTION_VISION_STRICT
    # Retained for metadata logging; routing handled by LiteLLM Router.
    vision_provider: str = RAG_INGESTION_VISION_PROVIDER
    vision_model: str = RAG_INGESTION_VISION_MODEL
    vision_api_base_url: str = RAG_INGESTION_VISION_API_BASE_URL
    vision_api_key: str = RAG_INGESTION_VISION_API_KEY
    vision_api_path: str = RAG_INGESTION_VISION_API_PATH
    enable_document_refactoring: bool = RAG_INGESTION_ENABLE_DOCUMENT_REFACTORING
    enable_cross_reference_extraction: bool = (
        RAG_INGESTION_ENABLE_CROSS_REFERENCE_EXTRACTION
    )
    enable_knowledge_graph_extraction: bool = (
        RAG_INGESTION_ENABLE_KNOWLEDGE_GRAPH_EXTRACTION
    )
    enable_quality_validation: bool = RAG_INGESTION_ENABLE_QUALITY_VALIDATION
    enable_knowledge_graph_storage: bool = RAG_INGESTION_ENABLE_KNOWLEDGE_GRAPH_STORAGE
    min_chunk_chars: int = 40
    min_quality_score: float = 0.45
    build_kg: bool = True
    export_processed: bool = False
    update_mode: bool = False
    verbose_stage_logs: bool = RAG_INGESTION_VERBOSE_STAGE_LOGS
    persist_refactor_mirror: bool = RAG_INGESTION_PERSIST_REFACTOR_MIRROR
    mirror_output_dir: str = str(RAG_INGESTION_MIRROR_DIR)
    clean_store_dir: str = "data/clean_store"  # Directory for CleanDocumentStore. Empty string disables persistent store.
    # Target vector store collection for embedding storage. Defaults to VECTOR_COLLECTION_DEFAULT.
    target_collection: str = VECTOR_COLLECTION_DEFAULT
    store_documents: bool = True  # Whether to persist clean markdown to the document store (MinIO).
    target_bucket: str = ""  # MinIO bucket for document storage. Empty string uses MINIO_BUCKET default.
    # Retained for backward compat; routing handled by LiteLLM Router.
    ollama_url: str = OLLAMA_BASE_URL


@dataclass
class IngestionDesignCheck:
    """Validation report for ingestion configuration design constraints.

    Attributes:
        ok: Whether the configuration passed validation.
        errors: Human-readable errors that should fail fast.
        warnings: Non-fatal issues that may affect quality or performance.
    """
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class IngestionRunSummary:
    """Result summary for a directory-level ingestion run.

    Attributes:
        processed: Number of sources processed (including those later failed).
        skipped: Number of sources skipped due to idempotency checks.
        failed: Number of sources that failed during processing.
        stored_chunks: Total number of chunks successfully stored.
        removed_sources: Number of sources removed from storage (when applicable).
        errors: Human-readable error messages for failures.
        design_warnings: Non-fatal configuration warnings surfaced during the run.
    """
    processed: int
    skipped: int
    failed: int
    stored_chunks: int
    removed_sources: int
    errors: list[str]
    design_warnings: list[str] = field(default_factory=list)


@dataclass
class Runtime:
    """Runtime container holding expensive shared ingestion dependencies.

    Attributes:
        config: Effective ingestion configuration.
        embedder: Embedding model wrapper used by storage stages.
        weaviate_client: Client used for vector and (optionally) metadata storage.
        kg_builder: Optional knowledge graph builder used by KG stages.
    """
    config: IngestionConfig
    embedder: LocalBGEEmbeddings
    weaviate_client: Any
    kg_builder: Optional[KnowledgeGraphBuilder]
    db_client: Optional[Any] = None


class IngestState(TypedDict):
    """LangGraph state schema shared across ingestion pipeline nodes.

    The ingestion pipeline uses a shared mutable state object that is passed
    between nodes. Keys are populated progressively as stages complete.
    """
    source_path: str
    source_name: str
    source_uri: str
    source_key: str
    source_id: str
    connector: str
    source_version: str
    content_hash: str
    existing_hash: str
    existing_source_uri: str
    should_skip: bool
    errors: List[str]
    processing_log: List[str]
    raw_text: str
    structure: Dict[str, Any]
    multimodal_notes: List[str]
    cleaned_text: str
    refactored_text: str
    chunks: List[ProcessedChunk]
    metadata_summary: str
    metadata_keywords: List[str]
    cross_references: List[Dict[str, str]]
    kg_triples: List[Dict[str, Any]]
    stored_count: int
    runtime: Runtime
