# @summary
# LangGraph node for optional relation extraction to intermediate KG triples.
# Exports: knowledge_graph_extraction_node
# Deps: embedding.state
# @end-summary

"""Knowledge-graph extraction node implementation."""

from __future__ import annotations

from src.core.knowledge_graph import EntityExtractor
from src.ingest.common.shared import append_processing_log
from src.ingest.embedding.state import EmbeddingPipelineState


def knowledge_graph_extraction_node(state: EmbeddingPipelineState) -> dict:
    """Extract entity relations and stage triples for downstream KG storage.

    Args:
        state: Ingestion pipeline state.

    Returns:
        Partial state update containing ``kg_triples`` (when enabled) and an
        updated ``processing_log``. When disabled, returns only a skipped log
        entry.
    """
    if not state["runtime"].config.enable_knowledge_graph_extraction:
        return {
            "processing_log": append_processing_log(
                state, "knowledge_graph_extraction:skipped"
            )
        }

    extractor = EntityExtractor()
    triples = []
    for chunk in state["chunks"]:
        entities = extractor.extract_entities(chunk.text)
        relations = extractor.extract_relations(chunk.text, entities)
        triples.extend(
            {
                "subject": subject,
                "predicate": predicate,
                "object": obj,
                "source": state["source_name"],
            }
            for subject, predicate, obj in relations
        )

    return {
        "kg_triples": triples,
        "processing_log": append_processing_log(
            state, "knowledge_graph_extraction:ok"
        ),
    }
