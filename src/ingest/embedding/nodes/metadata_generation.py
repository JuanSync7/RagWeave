# @summary
# LangGraph node for document-level summary and keyword generation with fallback extraction.
# Exports: metadata_generation_node
# Deps: embedding.state
# @end-summary

"""Metadata-generation node implementation."""

from __future__ import annotations

from src.ingest.support.llm import _llm_json
from src.ingest.common.shared import _extract_keywords_fallback, append_processing_log
from src.ingest.embedding.state import EmbeddingPipelineState


def metadata_generation_node(state: EmbeddingPipelineState) -> dict:
    """Generate document summary/keywords and project them into chunk metadata.

    This node uses an LLM (when enabled) to produce a short summary and a list
    of keywords for the document, falling back to deterministic extraction when
    LLM metadata is disabled or unavailable.

    Args:
        state: Ingestion pipeline state.

    Returns:
        Partial state update containing ``metadata_summary``, ``metadata_keywords``,
        and an updated ``processing_log``.
    """
    config = state["runtime"].config
    text = state.get("refactored_text") or state.get("cleaned_text", "")
    prompt = (
        'Return {"summary":"...","keywords":[]} for:\n'
        + text[:10000]
    )
    response = _llm_json(prompt, config, 250)
    summary = str(response.get("summary", "")).strip() or text[:240].strip()

    keywords = response.get("keywords")
    if isinstance(keywords, list):
        parsed_keywords = [str(keyword).strip() for keyword in keywords]
    else:
        parsed_keywords = _extract_keywords_fallback(
            text, config.max_keywords
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
