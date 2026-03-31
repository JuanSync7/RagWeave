# @summary
# Phase 2 orchestrator: compiles and invokes the Embedding Pipeline LangGraph.
# Exports: run_embedding_pipeline
# Deps: src.ingest.embedding.workflow, src.ingest.embedding.state, src.ingest.common.types
# @end-summary

"""Phase 2 runtime implementation for the embedding pipeline."""

from __future__ import annotations

from typing import Any, Optional

from src.ingest.common.types import Runtime
from src.ingest.embedding.state import EmbeddingPipelineState
from src.ingest.embedding.workflow import build_embedding_graph

_GRAPH = build_embedding_graph()


def run_embedding_pipeline(
    runtime: Runtime,
    source_key: str,
    source_name: str,
    source_uri: str,
    source_id: str,
    connector: str,
    source_version: str,
    clean_text: str,
    clean_hash: str,
    refactored_text: Optional[str] = None,
    docling_document: Optional[Any] = None,
) -> EmbeddingPipelineState:
    """Run the Phase 2 Embedding Pipeline for a single clean document.

    Args:
        runtime: Shared runtime dependencies.
        source_key: Stable source identity key.
        source_name: Display name for the source.
        source_uri: Stable URI for the source.
        source_id: OS-level stable identity.
        connector: Connector identifier.
        source_version: Source version string.
        clean_text: Clean Markdown text from CleanDocumentStore.
        clean_hash: SHA-256 of ``clean_text`` for change detection.
        refactored_text: LLM-refactored text from Phase 1, if available.
        docling_document: Native DoclingDocument loaded from CleanDocumentStore,
            or ``None`` if not persisted. Read by chunking_node to select
            HybridChunker vs markdown path.

    Returns:
        Final ``EmbeddingPipelineState`` after all nodes have run.
    """
    initial_state: EmbeddingPipelineState = {
        "runtime": runtime,
        "source_key": source_key,
        "source_name": source_name,
        "source_uri": source_uri,
        "source_id": source_id,
        "connector": connector,
        "source_version": source_version,
        "raw_text": clean_text,
        "cleaned_text": clean_text,
        "refactored_text": refactored_text,
        "clean_hash": clean_hash,
        "docling_document": docling_document,
        "chunks": [],
        "enriched_chunks": [],
        "metadata_summary": "",
        "metadata_keywords": [],
        "cross_references": [],
        "kg_triples": [],
        "stored_count": 0,
        "errors": [],
        "processing_log": [],
    }
    try:
        final_state = _GRAPH.invoke(initial_state)
    except Exception as exc:
        final_state = {**initial_state, "errors": [f"embedding_graph:{exc}"], "stored_count": 0}
    return final_state
