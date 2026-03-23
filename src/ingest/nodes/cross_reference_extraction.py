# @summary
# LangGraph node for optional cross-reference pattern extraction from document text.
# Exports: cross_reference_extraction_node
# @end-summary

"""Cross-reference extraction node implementation."""

from __future__ import annotations

from src.ingest.common.shared import _cross_refs, append_processing_log
from src.ingest.common.types import IngestState


def cross_reference_extraction_node(state: IngestState) -> dict:
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
    return {
        "cross_references": _cross_refs(state["refactored_text"]),
        "processing_log": append_processing_log(
            state, "cross_reference_extraction:ok"
        ),
    }
