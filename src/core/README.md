<!-- @summary
Core runtime primitives for embeddings, vector storage, and knowledge graph
construction/query expansion used by ingestion and retrieval.
@end-summary -->

# core

## Overview

This directory contains foundational components used across the project for:

- embedding generation,
- vector document storage/retrieval,
- knowledge graph extraction and expansion.

## Files

| File | Purpose | Key Exports |
| --- | --- | --- |
| `embeddings.py` | Local embedding wrapper (LangChain-compatible) for BAAI/bge models | `LocalBGEEmbeddings` |
| `knowledge_graph.py` | Entity/relation extraction, graph build/export, and query-time KG expansion | `KnowledgeGraphBuilder`, `GraphQueryExpander`, `export_obsidian` |
| `vector_store.py` | Weaviate embedded client helpers for collection management, ingest, and hybrid retrieval | `create_persistent_client`, `get_weaviate_client`, `ensure_collection`, `add_documents`, `hybrid_search`, `delete_collection` |

## Internal Dependencies

- Retrieval and ingestion depend on this directory.
- `vector_store.py` and `embeddings.py` use observability provider hooks.

## Subdirectories

None
