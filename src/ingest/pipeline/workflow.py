# @summary
# Top-level LangGraph state-machine composition for the 13-stage ingestion workflow.
# Exports: build_graph
# Deps: langgraph.graph, src.ingest.nodes.*, src.ingest.common.types
# @end-summary

"""Top-level LangGraph workflow composition for ingestion."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from src.ingest.nodes.chunk_enrichment import chunk_enrichment_node
from src.ingest.nodes.chunking import chunking_node
from src.ingest.nodes.cross_reference_extraction import cross_reference_extraction_node
from src.ingest.nodes.document_ingestion import document_ingestion_node
from src.ingest.nodes.document_refactoring import document_refactoring_node
from src.ingest.nodes.embedding_storage import embedding_storage_node
from src.ingest.nodes.knowledge_graph_extraction import knowledge_graph_extraction_node
from src.ingest.nodes.knowledge_graph_storage import knowledge_graph_storage_node
from src.ingest.nodes.metadata_generation import metadata_generation_node
from src.ingest.nodes.multimodal_processing import multimodal_processing_node
from src.ingest.nodes.quality_validation import quality_validation_node
from src.ingest.nodes.structure_detection import structure_detection_node
from src.ingest.nodes.text_cleaning import text_cleaning_node
from src.ingest.common.types import IngestState


def build_graph():
    """Compose and compile the ingestion workflow graph.

    Returns:
        A compiled LangGraph graph that can be invoked with an `IngestState`
        payload.
    """
    graph = StateGraph(IngestState)
    graph.add_node("document_ingestion", document_ingestion_node)
    graph.add_node("structure_detection", structure_detection_node)
    graph.add_node("multimodal_processing", multimodal_processing_node)
    graph.add_node("text_cleaning", text_cleaning_node)
    graph.add_node("document_refactoring", document_refactoring_node)
    graph.add_node("chunking", chunking_node)
    graph.add_node("chunk_enrichment", chunk_enrichment_node)
    graph.add_node("metadata_generation", metadata_generation_node)
    graph.add_node("cross_reference_extraction", cross_reference_extraction_node)
    graph.add_node("knowledge_graph_extraction", knowledge_graph_extraction_node)
    graph.add_node("quality_validation", quality_validation_node)
    graph.add_node("embedding_storage", embedding_storage_node)
    graph.add_node("knowledge_graph_storage", knowledge_graph_storage_node)

    graph.set_entry_point("document_ingestion")
    graph.add_conditional_edges(
        "document_ingestion",
        lambda state: "end" if state["should_skip"] else "structure_detection",
        {"structure_detection": "structure_detection", "end": END},
    )
    graph.add_conditional_edges(
        "structure_detection",
        lambda state: (
            "multimodal_processing"
            if (
                state["runtime"].config.enable_multimodal_processing
                and state["structure"].get("has_figures")
            )
            else "text_cleaning"
        ),
        {
            "multimodal_processing": "multimodal_processing",
            "text_cleaning": "text_cleaning",
        },
    )
    graph.add_edge("multimodal_processing", "text_cleaning")
    graph.add_conditional_edges(
        "text_cleaning",
        lambda state: (
            "document_refactoring"
            if state["runtime"].config.enable_document_refactoring
            else "chunking"
        ),
        {"document_refactoring": "document_refactoring", "chunking": "chunking"},
    )
    graph.add_edge("document_refactoring", "chunking")
    graph.add_edge("chunking", "chunk_enrichment")
    graph.add_edge("chunk_enrichment", "metadata_generation")
    graph.add_conditional_edges(
        "metadata_generation",
        lambda state: (
            "cross_reference_extraction"
            if state["runtime"].config.enable_cross_reference_extraction
            else "knowledge_graph_extraction"
        ),
        {
            "cross_reference_extraction": "cross_reference_extraction",
            "knowledge_graph_extraction": "knowledge_graph_extraction",
        },
    )
    graph.add_edge("cross_reference_extraction", "knowledge_graph_extraction")
    graph.add_edge("knowledge_graph_extraction", "quality_validation")
    graph.add_edge("quality_validation", "embedding_storage")
    graph.add_conditional_edges(
        "embedding_storage",
        lambda state: (
            "knowledge_graph_storage"
            if state["runtime"].config.enable_knowledge_graph_storage
            else "end"
        ),
        {"knowledge_graph_storage": "knowledge_graph_storage", "end": END},
    )
    graph.add_edge("knowledge_graph_storage", END)
    return graph.compile()
