# @summary
# LangGraph StateGraph for the 9-node Embedding Pipeline (Phase 2).
# Exports: build_embedding_graph
# Deps: langgraph.graph, src.ingest.embedding.nodes.*, src.ingest.embedding.state
# Node order: document_storage → chunking → vlm_enrichment → chunk_enrichment → ...
# vlm_enrichment_node is always present; it short-circuits internally for
# vlm_mode != "external".
# @end-summary

"""Phase 2 LangGraph workflow for embedding and storage."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from src.ingest.embedding.nodes.chunk_enrichment import chunk_enrichment_node
from src.ingest.embedding.nodes.chunking import chunking_node
from src.ingest.embedding.nodes.vlm_enrichment import vlm_enrichment_node
from src.ingest.embedding.nodes.document_storage_node import document_storage_node
from src.ingest.embedding.nodes.cross_reference_extraction import (
    cross_reference_extraction_node,
)
from src.ingest.embedding.nodes.embedding_storage import embedding_storage_node
from src.ingest.embedding.nodes.knowledge_graph_extraction import (
    knowledge_graph_extraction_node,
)
from src.ingest.embedding.nodes.knowledge_graph_storage import (
    knowledge_graph_storage_node,
)
from src.ingest.embedding.nodes.metadata_generation import metadata_generation_node
from src.ingest.embedding.nodes.quality_validation import quality_validation_node
from src.ingest.embedding.state import EmbeddingPipelineState


def build_embedding_graph():
    """Compile the Phase 2 Embedding Pipeline StateGraph.

    Node order:
        document_storage → chunking → vlm_enrichment → chunk_enrichment
        → metadata_generation → [cross_reference_extraction →]
        knowledge_graph_extraction → quality_validation → embedding_storage
        → [knowledge_graph_storage]

    Routing:
    - vlm_enrichment: always in graph; short-circuits internally when
      ``config.vlm_mode != "external"`` (logs ``vlm_enrichment:skipped``).
    - cross_reference_extraction: only if config.enable_cross_reference_extraction.
    - knowledge_graph_extraction: always runs (handles disabled state internally).
    - knowledge_graph_storage: only if config.enable_knowledge_graph_storage.

    Returns:
        Compiled LangGraph graph accepting ``EmbeddingPipelineState``.
    """
    graph = StateGraph(EmbeddingPipelineState)
    graph.add_node("document_storage", document_storage_node)
    graph.add_node("chunking", chunking_node)
    graph.add_node("vlm_enrichment", vlm_enrichment_node)
    graph.add_node("chunk_enrichment", chunk_enrichment_node)
    graph.add_node("metadata_generation", metadata_generation_node)
    graph.add_node("cross_reference_extraction", cross_reference_extraction_node)
    graph.add_node("knowledge_graph_extraction", knowledge_graph_extraction_node)
    graph.add_node("quality_validation", quality_validation_node)
    graph.add_node("embedding_storage", embedding_storage_node)
    graph.add_node("knowledge_graph_storage", knowledge_graph_storage_node)

    graph.set_entry_point("document_storage")
    graph.add_edge("document_storage", "chunking")
    graph.add_edge("chunking", "vlm_enrichment")
    graph.add_edge("vlm_enrichment", "chunk_enrichment")
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
    # knowledge_graph_extraction_node checks config.enable_knowledge_graph_extraction
    # internally and returns early if disabled — always run the node, no conditional edge.
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
