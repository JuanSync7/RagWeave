# @summary
# LangGraph node for embedding generation and vector store persistence.
# Exports: embedding_storage_node
# Deps: src.vector_db, src.ingest.embedding.state, src.ingest.common.shared
# @end-summary

"""Embedding-storage node implementation."""

from __future__ import annotations

from typing import Any

from src.vector_db import (
    add_documents,
    delete_by_source_key,
    ensure_collection,
    DocumentRecord,
)
from src.ingest.common.shared import append_processing_log
from src.ingest.embedding.state import EmbeddingPipelineState


def embedding_storage_node(state: EmbeddingPipelineState) -> dict[str, Any]:
    """Persist chunk embeddings and metadata into the configured vector store.

    Args:
        state: Ingestion pipeline state.

    Returns:
        Partial state update containing ``stored_count`` and an updated
        ``processing_log``. When the workflow is skipped or there are no chunks,
        returns ``stored_count=0``.
    """
    if state.get("should_skip", False) or not state["chunks"]:
        return {
            "stored_count": 0,
            "processing_log": append_processing_log(state, "embedding_storage:skipped"),
        }

    runtime = state["runtime"]
    try:
        ensure_collection(runtime.weaviate_client)
        if runtime.config.update_mode:
            delete_by_source_key(
                runtime.weaviate_client,
                state["source_key"],
                legacy_source=state["source_name"],
            )

        texts = [chunk.metadata.get("enriched_content", chunk.text) for chunk in state["chunks"]]
        vectors = runtime.embedder.embed_documents(texts)
        records = [
            DocumentRecord(text=text, embedding=vector, metadata=chunk.metadata)
            for text, vector, chunk in zip(texts, vectors, state["chunks"])
        ]
        stored_count = add_documents(
            runtime.weaviate_client, records,
            collection=runtime.config.target_collection or None,
        )
    except Exception as exc:
        return {
            **state,
            "errors": state.get("errors", []) + [f"embedding_storage:{exc}"],
            "processing_log": append_processing_log(state, "embedding_storage:error"),
        }
    return {
        "stored_count": stored_count,
        "processing_log": append_processing_log(state, "embedding_storage:ok"),
    }
