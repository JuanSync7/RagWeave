<!-- @summary
RAG platform with modular ingestion, retrieval/query serving, and Temporal-based
multi-user API orchestration. Includes engineering docs, onboarding guides, and
operations tooling for observability, backup/restore, and scaling.
@end-summary -->

# RAG

## Overview

This repository contains an end-to-end RAG system with:

- a modular 13-node ingestion workflow (`src/ingest`) for document-to-vector/KG processing,
- a retrieval and query-serving runtime (`src/retrieval`, `server`) with Temporal orchestration,
- platform modules for auth, limits, observability, and caching (`src/platform`),
- operations and architecture documentation (`docs/`).

## Architecture (Runtime)

```text
Users/CLI -> FastAPI (`server/api.py`) -> Temporal workflow -> Worker activity
                                                    |
                                                    v
                                          `RAGChain` singleton
                                  (retrieval, reranking, optional generation)
```

Ingestion runs separately and writes processed content/embeddings consumed by retrieval.

## Directory Map

| Directory | Purpose |
| --- | --- |
| `src/ingest/` | Modular ingestion pipeline (node-per-file, shared helpers, LangGraph workflow). |
| `src/retrieval/` | Query processing, retrieval orchestration, reranking, and generation. |
| `src/platform/` | Cross-cutting platform services: auth, quotas/rate limits, cache, metrics, observability. |
| `server/` | FastAPI/Temporal runtime: API, workflows, activities, worker, schemas, and CLI client. |
| `config/` | Central environment-driven settings (`config/settings.py`). |
| `docs/` | Engineering guides, specs, operations runbooks, onboarding checklists. |
| `tests/` | Unit/integration tests, including ingestion-focused tests in `tests/ingest/`. |
| `scripts/` | Ops helpers (backup/restore, DR drill, tuning signal watcher, smoke test). |
| `prompts/` | Prompt templates for retrieval query processing. |

## Entry Points

- `ingest.py`: CLI for ingestion runs.
- `query.py`: Local retrieval query CLI.
- `python -m server.worker`: Temporal worker process.
- `uvicorn server.api:app --host 0.0.0.0 --port 8000`: API server.
- `python -m server.cli_client`: Interactive client targeting the API server.

## Engineering Docs

- Retrieval: `docs/retrieval/RETRIEVAL_ENGINEERING_GUIDE.md`
- Retrieval onboarding: `docs/retrieval/RETRIEVAL_NEW_ENGINEER_ONBOARDING_CHECKLIST.md`
- Ingestion: `docs/embedding/INGESTION_PIPELINE_ENGINEERING_GUIDE.md`
- Ingestion onboarding: `docs/embedding/INGESTION_NEW_ENGINEER_ONBOARDING_CHECKLIST.md`
- Server/runtime operations: `server/README.md`
