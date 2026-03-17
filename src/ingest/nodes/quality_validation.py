# @summary
# LangGraph node for optional chunk quality gating and de-duplication.
# Exports: quality_validation_node
# @end-summary

"""Quality-validation node implementation."""

from __future__ import annotations

import re

from src.ingest.common.shared import _quality_score, append_processing_log
from src.ingest.common.types import IngestState


def quality_validation_node(state: IngestState) -> dict:
    """Filter chunks by heuristic quality thresholds and deduplicate text."""
    config = state["runtime"].config
    if not config.enable_quality_validation:
        return {
            "processing_log": append_processing_log(state, "quality_validation:skipped")
        }

    filtered_chunks = []
    seen_normalized = set()
    for chunk in state["chunks"]:
        text = chunk.text.strip()
        normalized = re.sub(r"\s+", " ", text).lower()
        if len(text) < config.min_chunk_chars:
            continue
        if normalized in seen_normalized:
            continue
        if _quality_score(text) < config.min_quality_score:
            continue
        seen_normalized.add(normalized)
        filtered_chunks.append(chunk)

    return {
        "chunks": filtered_chunks,
        "processing_log": append_processing_log(state, "quality_validation:ok"),
    }
