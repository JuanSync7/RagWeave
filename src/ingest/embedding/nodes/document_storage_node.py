# @summary
# LangGraph node for storing the full clean markdown document in the document store (MinIO).
# Exports: document_storage_node
# Deps: src.db, src.ingest.embedding.state, src.ingest.common.shared
# @end-summary
"""Document-storage node — persists the clean markdown to MinIO before chunking."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("rag.ingest.embedding.document_storage")

from src.db import build_document_id, ensure_bucket, put_document
from src.ingest.common import append_processing_log
from src.ingest.embedding.state import EmbeddingPipelineState


def document_storage_node(state: EmbeddingPipelineState) -> dict[str, Any]:
    """Compute a stable document_id and persist the clean markdown to MinIO.

    Runs before chunking so that ``document_id`` is available to all downstream
    nodes. Failing here surfaces MinIO unavailability before any embedding work
    is done, keeping Weaviate and MinIO consistent.

    Skips the write (but still sets ``document_id``) when
    ``runtime.config.store_documents`` is False or no db_client is available.

    Args:
        state: Embedding pipeline state.

    Returns:
        Partial state update containing ``document_id`` and an updated
        ``processing_log``.
    """
    document_id = build_document_id(state["source_key"])
    runtime = state["runtime"]

    if not runtime.config.store_documents or runtime.db_client is None:
        reason = "skipped" if not runtime.config.store_documents else "no_client"
        return {
            "document_id": document_id,
            "processing_log": append_processing_log(state, f"document_storage:{reason}"),
        }

    content = state.get("refactored_text") or state.get("cleaned_text") or state.get("raw_text", "")
    metadata = {
        "source_key": state["source_key"],
        "source_name": state["source_name"],
        "source_uri": state["source_uri"],
        "source_id": state["source_id"],
        "source_version": state["source_version"],
        "connector": state["connector"],
    }

    try:
        ensure_bucket(runtime.db_client, runtime.config.target_bucket or None)
        put_document(runtime.db_client, document_id, content, metadata, runtime.config.target_bucket or None)
    except Exception as exc:
        return {
            **state,
            "errors": state.get("errors", []) + [f"document_storage:{exc}"],
            "processing_log": append_processing_log(state, "document_storage:error"),
        }

    return {
        "document_id": document_id,
        "processing_log": append_processing_log(state, "document_storage:ok"),
    }
