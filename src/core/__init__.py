# @summary
# Core package public API: local BGE embeddings and legacy knowledge graph builder.
# Exports: LocalBGEEmbeddings, EntityExtractor, GraphQueryExpander, KnowledgeGraphBuilder, export_obsidian
# Deps: src.core.embeddings, src.core.knowledge_graph
# @end-summary
"""Core subsystem — local embedding models and legacy knowledge graph."""

from src.core.embeddings import LocalBGEEmbeddings
from src.core.knowledge_graph import (
    EntityExtractor,
    GraphQueryExpander,
    KnowledgeGraphBuilder,
    export_obsidian,
)

__all__ = [
    "LocalBGEEmbeddings",
    "EntityExtractor",
    "GraphQueryExpander",
    "KnowledgeGraphBuilder",
    "export_obsidian",
]
