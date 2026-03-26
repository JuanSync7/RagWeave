<!-- @summary
Pipeline boundary contracts: RAGRequest (input), RAGResponse (output), and RankedResult (wire type crossing query and generation). Also holds the shared deterministic utility parse_json_object.
@end-summary -->

# retrieval/common

## Overview

This directory holds the pipeline-level contracts — the types that define what enters and exits the RAG pipeline, and what flows between its sub-packages.

## Files

| File | Purpose | Key Exports |
| --- | --- | --- |
| `schemas.py` | Pipeline boundary contracts | `RAGRequest`, `RAGResponse`, `RankedResult` |
| `utils.py` | Deterministic helper utilities | `parse_json_object` |

## Schema Roles

- **`RAGRequest`** — input contract for `RAGChain.run()`. Optional numeric fields default to `None`; the pipeline substitutes config defaults at runtime, keeping this schema config-free.
- **`RAGResponse`** — full pipeline output returned to callers.
- **`RankedResult`** — wire type produced by the reranker (query side) and consumed by document formatting and confidence scoring (generation side). Lives here because it crosses the query↔generation boundary.

## What Does Not Belong Here

Sub-package-specific types stay in their own `schemas.py`:

- `QueryAction`, `QueryResult`, `QueryState` → `query/schemas.py`
- `FormattedContext`, `VersionConflict` → `generation/schemas.py`
- `ConfidenceBreakdown`, `PostGuardrailAction` → `generation/confidence/schemas.py`
