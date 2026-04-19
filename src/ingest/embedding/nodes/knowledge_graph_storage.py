# @summary
# LangGraph node for optional persistence of chunks into the knowledge graph builder.
# Exports: knowledge_graph_storage_node
# Deps: embedding.state
# @end-summary

"""Knowledge-graph storage node implementation."""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger("rag.ingest.embedding.knowledge_graph_storage")

from src.ingest.common import append_processing_log
from src.ingest.embedding.state import EmbeddingPipelineState


def knowledge_graph_storage_node(state: EmbeddingPipelineState) -> dict[str, Any]:
    """Store processed chunks into the runtime knowledge graph builder.

    Args:
        state: Ingestion pipeline state.

    Returns:
        Partial state update containing an updated ``processing_log``. When the
        stage is disabled or the runtime has no KG builder, returns only a
        skipped log entry.
    """
    t0 = time.monotonic()
    config = state["runtime"].config
    kg_builder = state["runtime"].kg_builder
    if not config.enable_knowledge_graph_storage or kg_builder is None:
        return {
            "processing_log": append_processing_log(
                state, "knowledge_graph_storage:skipped"
            )
        }

    try:
        for chunk in state["chunks"]:
            kg_builder.add_chunk(chunk.text, source=state["source_name"])
    except Exception as exc:
        return {
            **state,
            "errors": state.get("errors", []) + [f"kg_storage:{exc}"],
            "processing_log": append_processing_log(state, "knowledge_graph_storage:error"),
        }
    logger.info("knowledge_graph_storage complete: source=%s chunks=%d", state["source_name"], len(state["chunks"]))
    logger.debug("knowledge_graph_storage_node completed in %.3fs", time.monotonic() - t0)
    return {
        "processing_log": append_processing_log(state, "knowledge_graph_storage:ok")
    }
