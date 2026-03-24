# @summary
# LangGraph node for optional persistence of chunks into the knowledge graph builder.
# Exports: knowledge_graph_storage_node
# Deps: embedding.state
# @end-summary

"""Knowledge-graph storage node implementation."""

from __future__ import annotations

from src.ingest.common.shared import append_processing_log
from src.ingest.embedding.state import EmbeddingPipelineState


def knowledge_graph_storage_node(state: EmbeddingPipelineState) -> dict:
    """Store processed chunks into the runtime knowledge graph builder.

    Args:
        state: Ingestion pipeline state.

    Returns:
        Partial state update containing an updated ``processing_log``. When the
        stage is disabled or the runtime has no KG builder, returns only a
        skipped log entry.
    """
    config = state["runtime"].config
    kg_builder = state["runtime"].kg_builder
    if not config.enable_knowledge_graph_storage or kg_builder is None:
        return {
            "processing_log": append_processing_log(
                state, "knowledge_graph_storage:skipped"
            )
        }

    for chunk in state["chunks"]:
        kg_builder.add_chunk(chunk.text, source=state["source_name"])
    return {
        "processing_log": append_processing_log(state, "knowledge_graph_storage:ok")
    }
