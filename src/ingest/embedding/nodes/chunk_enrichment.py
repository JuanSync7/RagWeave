# @summary
# LangGraph node for chunk ID assignment and enriched content projection.
# Exports: chunk_enrichment_node
# Deps: src.vector_db, src.ingest.embedding.state, src.ingest.common.shared
# @end-summary

"""Chunk-enrichment node implementation."""

from __future__ import annotations

from src.vector_db import build_chunk_id
from src.ingest.common.shared import append_processing_log, map_chunk_provenance
from src.ingest.embedding.state import EmbeddingPipelineState


def chunk_enrichment_node(state: EmbeddingPipelineState) -> dict:
    """Attach stable chunk IDs and enriched content fields to chunk metadata.

    This node assigns a deterministic chunk ID, adds retrieval/citation fields,
    and attempts to map each chunk back to source offsets for provenance.

    Args:
        state: Ingestion pipeline state.

    Returns:
        Partial state update containing the enriched ``chunks`` list and an
        updated ``processing_log``.
    """
    config = state["runtime"].config
    original_text = state["raw_text"]
    refactored_text = state["refactored_text"] or state["cleaned_text"] or state["raw_text"]
    origin_label = "refactored" if config.enable_document_refactoring else "original"
    original_cursor = 0
    refactored_cursor = 0
    for index, chunk in enumerate(state["chunks"]):
        provenance, original_cursor, refactored_cursor = map_chunk_provenance(
            chunk.text,
            original_text=original_text,
            refactored_text=refactored_text,
            original_cursor=original_cursor,
            refactored_cursor=refactored_cursor,
        )
        # Keep source display/filter field explicit even if upstream metadata changes.
        chunk.metadata["source"] = state["source_name"]
        chunk.metadata["source_key"] = state["source_key"]
        chunk.metadata["chunk_id"] = build_chunk_id(state["source_key"], index, chunk.text)
        chunk.metadata["enriched_content"] = chunk.text
        chunk.metadata["retrieval_text_origin"] = origin_label
        chunk.metadata["citation_source_uri"] = state["source_uri"]
        chunk.metadata["document_id"] = state.get("document_id", "")
        chunk.metadata.update(provenance)
    return {
        "chunks": state["chunks"],
        "processing_log": append_processing_log(state, "chunk_enrichment:ok"),
    }
