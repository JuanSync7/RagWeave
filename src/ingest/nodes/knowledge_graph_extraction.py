# @summary
# LangGraph node for optional relation extraction to intermediate KG triples.
# Exports: knowledge_graph_extraction_node
# @end-summary

"""Knowledge-graph extraction node implementation."""

from __future__ import annotations

from src.core.knowledge_graph import EntityExtractor
from src.ingest.common.shared import append_processing_log
from src.ingest.common.types import IngestState


def knowledge_graph_extraction_node(state: IngestState) -> dict:
    """Extract entity relations and stage triples for downstream KG storage."""
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
