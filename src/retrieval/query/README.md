<!-- @summary
Query sub-pipeline: LangGraph-based query sanitization, LLM reformulation, confidence routing, and cross-encoder reranking. Owns QueryAction, QueryResult, and QueryState contracts.
@end-summary -->

# retrieval/query

## Overview

This sub-package handles everything from raw user input to a ranked list of retrieved documents ready for generation.

## Files

| File | Purpose | Key Exports |
| --- | --- | --- |
| `schemas.py` | Query sub-package contracts | `QueryAction`, `QueryResult`, `QueryState` |

## Subdirectories

### `nodes/`

| File | Purpose | Key Exports |
| --- | --- | --- |
| `query_processor.py` | LangGraph state machine: sanitize → reformulate → evaluate → route | `process_query`, `warm_up_ollama` |
| `reranker.py` | Local BAAI bge-reranker-v2-m3 cross-encoder wrapper | `LocalBGEReranker` |

## Schema Ownership

- `QueryAction` — routing decision: `SEARCH` or `ASK_USER`.
- `QueryResult` — output of `process_query`: processed query text, confidence score, action, and optional clarification message.
- `QueryState` — LangGraph `TypedDict` for the query processing state machine.
- `RankedResult` (wire type) — produced by the reranker but lives in `common/schemas.py` because it crosses into generation.

## Flow

```
raw query
  → sanitize_node        (injection check, length guard)
  → reformulate_and_evaluate_node  (LLM: reformulate + score in one call)
  → route                (confidence ≥ threshold → SEARCH, else → ASK_USER or retry)
  → LocalBGEReranker     (cross-encoder score + sort)
  → List[RankedResult]
```
