# @summary
# LangGraph node for document-level summary and keyword generation with fallback extraction.
# Exports: metadata_generation_node
# @end-summary

"""Metadata-generation node implementation."""

from __future__ import annotations

from src.ingest.support.llm import _llm_json
from src.ingest.common.shared import _extract_keywords_fallback, append_processing_log
from src.ingest.common.types import IngestState


def metadata_generation_node(state: IngestState) -> dict:
    """Generate document summary/keywords and project them into chunk metadata."""
    config = state["runtime"].config
    prompt = (
        'Return {"summary":"...","keywords":[]} for:\n'
        + state["refactored_text"][:10000]
    )
    response = _llm_json(prompt, config, 250)
    summary = str(response.get("summary", "")).strip() or state["refactored_text"][
        :240
    ].strip()

    keywords = response.get("keywords")
    if isinstance(keywords, list):
        parsed_keywords = [str(keyword).strip() for keyword in keywords]
    else:
        parsed_keywords = _extract_keywords_fallback(
            state["refactored_text"], config.max_keywords
        )
    parsed_keywords = parsed_keywords[: config.max_keywords]
    joined_keywords = ", ".join(parsed_keywords)

    for chunk in state["chunks"]:
        chunk.metadata["document_summary"] = summary
        chunk.metadata["document_keywords"] = joined_keywords

    return {
        "metadata_summary": summary,
        "metadata_keywords": parsed_keywords,
        "processing_log": append_processing_log(state, "metadata_generation:ok"),
    }
