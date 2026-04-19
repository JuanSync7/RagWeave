# @summary
# LangGraph node for optional cross-reference pattern extraction from document text.
# Exports: cross_reference_extraction_node
# Deps: embedding.state
# @end-summary

"""Cross-reference extraction node implementation."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("rag.ingest.embedding.cross_reference_extraction")

from src.ingest.common import (
    append_processing_log,
    cross_refs,
)
from src.ingest.embedding.state import EmbeddingPipelineState


def cross_reference_extraction_node(state: EmbeddingPipelineState) -> dict[str, Any]:
    """Extract document cross-reference patterns when this stage is enabled.

    Args:
        state: Ingestion pipeline state.

    Returns:
        Partial state update containing ``cross_references`` (when enabled) and
        an updated ``processing_log``. When disabled, returns only a skipped log
        entry.
    """
    if not state["runtime"].config.enable_cross_reference_extraction:
        return {
            "processing_log": append_processing_log(
                state, "cross_reference_extraction:skipped"
            )
        }
    text = state.get("refactored_text") or state.get("cleaned_text", "")
    return {
        "cross_references": cross_refs(text),
        "processing_log": append_processing_log(
            state, "cross_reference_extraction:ok"
        ),
    }
