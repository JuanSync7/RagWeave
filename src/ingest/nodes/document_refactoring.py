# @summary
# LangGraph node for optional LLM-driven document refactoring.
# Exports: document_refactoring_node
# @end-summary

"""Document-refactoring node implementation."""

from __future__ import annotations

from src.ingest.support.llm import _llm_json
from src.ingest.common.shared import append_processing_log
from src.ingest.common.types import IngestState


def document_refactoring_node(state: IngestState) -> dict:
    """Optionally rewrite cleaned text through an LLM-based refactoring pass."""
    config = state["runtime"].config
    if not config.enable_document_refactoring:
        return {
            "refactored_text": state["cleaned_text"],
            "processing_log": append_processing_log(
                state, "document_refactoring:skipped"
            ),
        }
    prompt = 'Return {"refactored_text":"..."} for:\n' + state["cleaned_text"][:10000]
    response = _llm_json(prompt, config, 900)
    refactored_text = str(response.get("refactored_text", "")).strip()
    return {
        "refactored_text": refactored_text or state["cleaned_text"],
        "processing_log": append_processing_log(state, "document_refactoring:ok"),
    }
