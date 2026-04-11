# @summary
# LangGraph node for source file read and SHA-256 hash computation (Phase 1).
# Exports: document_ingestion_node
# Deps: src.ingest.common.utils, src.ingest.common.shared, src.ingest.doc_processing.state
# @end-summary

"""Document ingestion node — Phase 1."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.ingest.common import (
    read_text_with_fallbacks,
    sha256_path,
)
from src.ingest.common import append_processing_log
from src.ingest.doc_processing.state import DocumentProcessingState


def document_ingestion_node(state: DocumentProcessingState) -> dict[str, Any]:
    """Read source content and compute SHA-256 hash.

    The idempotency skip check is handled by the orchestrator before this
    node is invoked — this node does not read or write ``should_skip``.

    Args:
        state: Document processing pipeline state.

    Returns:
        Partial state update with ``raw_text``, ``source_hash``, and
        ``processing_log``. On read failure, returns an ``errors`` payload
        to short-circuit the workflow.
    """
    source_path = Path(state["source_path"])
    try:
        raw_text = read_text_with_fallbacks(source_path)
    except Exception as exc:
        return {
            "errors": [f"read_failed:{source_path.name}:{exc}"],
            "processing_log": append_processing_log(state, "document_ingestion:failed"),
        }
    source_hash = sha256_path(source_path)
    return {
        "raw_text": raw_text,
        "source_hash": source_hash,
        "processing_log": append_processing_log(state, "document_ingestion:ok"),
    }
