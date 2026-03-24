# @summary
# LangGraph node for vector embedding generation and Weaviate persistence.
# Exports: embedding_storage_node
# Deps: embedding.state
# @end-summary

"""Embedding-storage node implementation."""

from __future__ import annotations

from src.core.vector_store import (
    add_documents,
    delete_documents_by_source_key,
    ensure_collection,
)
from src.ingest.common.shared import append_processing_log
from src.ingest.embedding.state import EmbeddingPipelineState


def embedding_storage_node(state: EmbeddingPipelineState) -> dict:
    """Persist chunk embeddings and metadata into the configured vector store.

    Args:
        state: Ingestion pipeline state.

    Returns:
        Partial state update containing ``stored_count`` and an updated
        ``processing_log``. When the workflow is skipped or there are no chunks,
        returns ``stored_count=0``.
    """
    if state["should_skip"] or not state["chunks"]:
        return {
            "stored_count": 0,
            "processing_log": append_processing_log(state, "embedding_storage:skipped"),
        }

    runtime = state["runtime"]
    ensure_collection(runtime.weaviate_client)
    if runtime.config.update_mode:
        delete_documents_by_source_key(
            runtime.weaviate_client,
            state["source_key"],
            legacy_source=state["source_name"],
        )

    texts = [chunk.metadata.get("enriched_content", chunk.text) for chunk in state["chunks"]]
    vectors = runtime.embedder.embed_documents(texts)
    stored_count = add_documents(
        runtime.weaviate_client,
        texts,
        vectors,
        [chunk.metadata for chunk in state["chunks"]],
    )
    return {
        "stored_count": stored_count,
        "processing_log": append_processing_log(state, "embedding_storage:ok"),
    }
