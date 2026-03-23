# @summary
# LangGraph node for source read/change detection and skip gating.
# Exports: document_ingestion_node
# @end-summary

"""Document ingestion node."""

from __future__ import annotations

from pathlib import Path

from src.ingest.common.utils import read_text_with_fallbacks, sha256_path
from src.ingest.common.shared import append_processing_log
from src.ingest.common.types import IngestState


def document_ingestion_node(state: IngestState) -> dict:
    """Read source content, compute hash, and determine whether to skip processing.

    Args:
        state: Ingestion pipeline state.

    Returns:
        Partial state update containing raw text, content hash, skip decision, and
        updated processing log. On read failure, returns an error payload with
        ``should_skip=True`` to short-circuit the workflow.
    """
    source_path = Path(state["source_path"])
    try:
        raw_text = read_text_with_fallbacks(source_path)
    except Exception as exc:
        return {
            "errors": [f"read_failed:{source_path.name}:{exc}"],
            "should_skip": True,
            "processing_log": append_processing_log(state, "document_ingestion:failed"),
        }
    content_hash = sha256_path(source_path)
    source_uri_unchanged = state.get("existing_source_uri", "") == state["source_uri"]
    should_skip = (
        bool(state["existing_hash"])
        and content_hash == state["existing_hash"]
        and source_uri_unchanged
    )
    return {
        "raw_text": raw_text,
        "content_hash": content_hash,
        "should_skip": should_skip,
        "processing_log": append_processing_log(state, "document_ingestion:ok"),
    }
