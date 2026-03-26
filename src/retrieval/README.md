<!-- @summary
Retrieval subsystem for query processing, hybrid search, reranking, and optional LLM generation with timing/observability support. Organised into query/, generation/, and pipeline/ sub-packages with shared pipeline contracts in common/.
@end-summary -->

# retrieval

## Overview

This directory contains the runtime retrieval path used by query serving, including:

- LangGraph-based query processing and confidence routing,
- hybrid vector + keyword retrieval orchestration,
- reranking and optional answer generation,
- stage timing instrumentation for retrieval vs generation latency splits.

## Package Structure

```
retrieval/
├── __init__.py           — public API surface
├── common/               — pipeline boundary contracts (RAGRequest, RAGResponse, RankedResult)
├── pipeline/             — end-to-end RAG orchestration (RAGChain)
├── query/                — query sub-pipeline: sanitization, reformulation, reranking
│   ├── schemas.py        — QueryAction, QueryResult, QueryState
│   └── nodes/            — query_processor, reranker
└── generation/           — generation sub-pipeline: formatting, LLM synthesis, confidence routing
    ├── schemas.py        — FormattedContext, VersionConflict
    ├── confidence/       — ConfidenceBreakdown, PostGuardrailAction, scoring, routing
    └── nodes/            — generator, document_formatter, output_sanitizer
```

## Schema Ownership

| Schema | Location | Purpose |
| --- | --- | --- |
| `RAGRequest` | `common/schemas.py` | Pipeline input contract |
| `RAGResponse` | `common/schemas.py` | Pipeline output contract |
| `RankedResult` | `common/schemas.py` | Wire type crossing query → generation |
| `QueryAction`, `QueryResult`, `QueryState` | `query/schemas.py` | Query sub-package internals |
| `FormattedContext`, `VersionConflict` | `generation/schemas.py` | Generation sub-package internals |
| `ConfidenceBreakdown`, `PostGuardrailAction` | `generation/confidence/schemas.py` | Post-gen confidence routing |

## Subdirectories

- `common/`: pipeline boundary contracts and shared wire types.
- `pipeline/`: `RAGChain` — composes query, KG expansion, hybrid search, reranking, and generation.
- `query/`: query sanitization, LLM-based reformulation, confidence routing, and reranking.
- `generation/`: document formatting, LLM answer synthesis, output sanitization, and composite confidence scoring.

## Engineering Documentation

- `docs/retrieval/README.md`: architecture overview and onboarding checklist.
