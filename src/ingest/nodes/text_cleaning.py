# @summary
# LangGraph node for markdown-aware text normalization and figure note injection.
# Exports: text_cleaning_node
# @end-summary

"""Text-cleaning node implementation."""

from __future__ import annotations

from src.ingest.support.markdown import clean_document
from src.ingest.common.shared import append_processing_log
from src.ingest.common.types import IngestState


def text_cleaning_node(state: IngestState) -> dict:
    """Normalize source text and append generated multimodal notes."""
    cleaned = clean_document(state["raw_text"])
    if state["multimodal_notes"]:
        cleaned += "\n\n## Figure Notes\n" + "\n".join(
            f"- {note}" for note in state["multimodal_notes"]
        )
    return {
        "cleaned_text": cleaned,
        "processing_log": append_processing_log(state, "text_cleaning:ok"),
    }
