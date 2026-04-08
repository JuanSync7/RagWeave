# @summary
# LangGraph TypedDict state contract for the Phase 2 Embedding Pipeline.
# Exports: EmbeddingPipelineState
# Deps: src.ingest.common.types, src.ingest.common.schemas
# Fields: runtime, source_*, raw_text, cleaned_text, refactored_text, clean_hash,
#   document_id, chunks, enriched_chunks, metadata_*, cross_references, kg_triples,
#   stored_count, errors, processing_log, docling_document (Optional[Any]),
#   visual_stored_count (int, FR-602), page_images (Optional[List[Any]], FR-602)
# @end-summary

"""State contract for the Embedding Pipeline (Phase 2, nodes 6–13)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict

from src.ingest.common.schemas import ProcessedChunk
from src.ingest.common.types import Runtime


class EmbeddingPipelineState(TypedDict, total=False):
    """Shared state flowing through the 8-node Embedding Pipeline DAG.

    Initial fields are populated by the orchestrator from CleanDocumentStore
    before the graph is invoked.

    Fields
    ------
    runtime : Runtime
        Shared runtime dependencies.
    source_key : str
        Stable source identity key.
    source_name : str
        Display name.
    source_uri : str
        Stable URI for the source.
    source_id : str
        OS-level stable identity.
    source_version : str
        Source version string.
    connector : str
        Connector identifier.
    raw_text : str
        The clean Markdown text read from CleanDocumentStore (used as raw_text
        for compatibility with chunking/enrichment nodes).
    cleaned_text : str
        Same as raw_text for Phase 2 entry point — the clean text is the input.
    refactored_text : str | None
        Stored refactored text from Phase 1, if present in CleanDocumentStore meta.
    clean_hash : str
        SHA-256 of the clean text (for change detection on Phase 2 re-runs).
    document_id : str
        Stable document UUID set by document_storage_node (node X), links to MinIO.
    chunks : list[ProcessedChunk]
        Chunks produced by chunking_node (node 6).
    enriched_chunks : list[ProcessedChunk]
        Chunks with IDs and provenance from chunk_enrichment_node (node 7).
    metadata_summary : str
        LLM-generated document summary from metadata_generation_node (node 8).
    metadata_keywords : list[str]
        Extracted keywords from metadata_generation_node (node 8).
    cross_references : list[dict[str, str]]
        Pattern-matched cross-references from cross_reference_extraction_node (node 9).
    kg_triples : list[dict[str, Any]]
        Extracted KG triples (subject/predicate/object) from kg_extraction_node (node 10).
    stored_count : int
        Number of chunks successfully stored in Weaviate from embedding_storage_node (node 12).
    errors : list[str]
        Error messages from any node.
    processing_log : list[str]
        Stage completion log entries.
    """

    runtime: Runtime
    source_key: str
    source_name: str
    source_uri: str
    source_id: str
    source_version: str
    connector: str
    raw_text: str
    cleaned_text: str
    refactored_text: Optional[str]
    clean_hash: str
    document_id: str
    chunks: List[ProcessedChunk]
    enriched_chunks: List[ProcessedChunk]
    metadata_summary: str
    metadata_keywords: List[str]
    cross_references: List[Dict[str, str]]
    kg_triples: List[Dict[str, Any]]
    stored_count: int
    errors: List[str]
    processing_log: List[str]
    docling_document: Optional[Any]
    """Native DoclingDocument object loaded from CleanDocumentStore at
    Phase 2 initialization. None if no .docling.json was stored (fallback
    path). Read by chunking_node to select HybridChunker vs markdown path.
    """

    # -- Visual embedding extensions (FR-602) --
    visual_stored_count: int  # FR-602: number of visual page objects stored; default 0
    page_images: Optional[List[Any]]  # FR-602: PIL.Image objects; cleared after node (FR-606)
