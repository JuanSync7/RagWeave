<!-- @summary
Source tree for the RAG platform, organized by functional domains: shared core
primitives, ingestion pipeline, retrieval runtime, and platform capabilities.
@end-summary -->

# src

## Overview

`src/` contains implementation modules used by ingestion, retrieval, and server runtime flows.

## Subdirectories

| Directory | Purpose |
| --- | --- |
| `core/` | Foundational primitives (embeddings, vector store, knowledge graph). |
| `ingest/` | Modular document ingestion pipeline and LangGraph stage workflow. |
| `retrieval/` | Query processing, retrieval orchestration, reranking, generation integration. |
| `platform/` | Security/auth, limits, cache, metrics, observability, and retry providers. |

## Cross-Directory Notes

- Retrieval composes `core/` plus `platform/` services.
- Ingestion uses `core/` storage primitives and its own pipeline modules.
- Server modules in `server/` consume `src/retrieval/` and `src/platform/` APIs.
