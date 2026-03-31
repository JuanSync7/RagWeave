# API Schema Contract Tests

> **Test file:** `tests/test_schema_contracts.py`
> **16 tests** — 8 ingestion, 8 retrieval

## Purpose

These tests catch drift between API Pydantic models (`server/schemas.py`) and internal pipeline dataclasses. When an internal contract adds, removes, or renames a field, the relevant contract test fails — forcing a conscious decision about whether to expose the change via the API or classify it as internal-only.

## How It Works

Every internal field is partitioned into exactly one of two sets:

```
Internal field
  ├── EXPOSED → mapped in the API schema (user-visible)
  └── INFRA_ONLY → explicitly listed in the test (not user-visible)

EXPOSED ∪ INFRA_ONLY = all internal fields  (enforced by test)
EXPOSED ∩ INFRA_ONLY = ∅                    (enforced by test)
```

If a new field appears in neither set, the test fails with a message telling the developer exactly what to do.

## Ingestion: ConsoleIngestionRequest ↔ IngestionConfig

| Test | What it catches |
|------|----------------|
| `test_all_config_fields_are_classified` | New `IngestionConfig` field not in `INGESTION_REQUEST_FIELD_MAP` or `INGESTION_INFRA_ONLY_FIELDS` |
| `test_no_phantom_exposed_fields` | `INGESTION_REQUEST_FIELD_MAP` references an `IngestionConfig` field that was removed/renamed |
| `test_no_phantom_infra_fields` | `INGESTION_INFRA_ONLY_FIELDS` references an `IngestionConfig` field that was removed/renamed |
| `test_no_overlap_between_exposed_and_infra` | Same field classified as both exposed and infra-only |
| `test_to_config_produces_valid_instance` | `to_config()` broken — can't construct `IngestionConfig` from defaults |
| `test_to_config_overlays_non_none_fields` | `to_config()` doesn't forward explicit request values |
| `test_to_config_preserves_defaults_for_none_fields` | `to_config()` overrides env-var defaults when it shouldn't |
| `test_request_only_fields_not_in_field_map` | Execution-mode fields (`mode`, `target_path`) leaked into config mapping |

### Classification sets

- **`INGESTION_REQUEST_FIELD_MAP`** (in `server/schemas.py`) — maps `ConsoleIngestionRequest` field names to `IngestionConfig` field names. Used by `to_config()` at runtime and by contract tests at test time.
- **`INGESTION_INFRA_ONLY_FIELDS`** (in `tests/test_schema_contracts.py`) — fields intentionally not exposed: API keys, internal paths, server-side tuning knobs, quality thresholds.
- **`INGESTION_REQUEST_ONLY_FIELDS`** (in `tests/test_schema_contracts.py`) — `ConsoleIngestionRequest` fields that control execution mode, not pipeline config (`mode`, `target_path`, `export_obsidian`).

### When you add a field to IngestionConfig

1. Run `uv run python -m pytest tests/test_schema_contracts.py -v`
2. `test_all_config_fields_are_classified` will fail with the field name
3. Decide: should the web UI user control this?
   - **Yes** → add to `INGESTION_REQUEST_FIELD_MAP` in `server/schemas.py` + add the field to `ConsoleIngestionRequest`
   - **No** → add to `INGESTION_INFRA_ONLY_FIELDS` in `tests/test_schema_contracts.py`
4. Tests pass again

## Retrieval: QueryRequest ↔ RAGRequest, QueryResponse ↔ RAGResponse

| Test | What it catches |
|------|----------------|
| `test_query_request_fields_exist_in_rag_request` | `QueryRequest` field doesn't exist in `RAGRequest` and isn't classified as request-only |
| `test_all_rag_request_fields_are_classified` | New `RAGRequest` field not in `QueryRequest` or `RAG_REQUEST_INTERNAL_FIELDS` |
| `test_no_phantom_rag_request_internal_fields` | `RAG_REQUEST_INTERNAL_FIELDS` references a field that was removed |
| `test_query_response_fields_exist_in_rag_response` | `QueryResponse` field doesn't exist in `RAGResponse` and isn't classified as response-only |
| `test_all_rag_response_fields_are_classified` | New `RAGResponse` field not in `QueryResponse` or `RAG_RESPONSE_INTERNAL_FIELDS` |
| `test_no_phantom_rag_response_internal_fields` | `RAG_RESPONSE_INTERNAL_FIELDS` references a field that was removed |
| `test_no_phantom_query_response_only_fields` | `QUERY_RESPONSE_ONLY_FIELDS` references a field that was removed |
| `test_chunk_result_matches_ranked_result` | `ChunkResult` (API) and `RankedResult` (internal) field sets diverge |

### Classification sets

- **`QUERY_REQUEST_ONLY_FIELDS`** — fields on `QueryRequest` that don't map to `RAGRequest` (route handler fills memory/compaction fields).
- **`RAG_REQUEST_INTERNAL_FIELDS`** — `RAGRequest` fields not exposed via API (server injects `memory_context`, `memory_recent_turns`, `skip_generation`).
- **`RAG_RESPONSE_INTERNAL_FIELDS`** — `RAGResponse` fields not surfaced to API clients (guardrails, confidence breakdown, re-retrieval signals).
- **`QUERY_RESPONSE_ONLY_FIELDS`** — `QueryResponse` fields added by the route handler (`workflow_id`, `latency_ms`).

### When you add a field to RAGRequest or RAGResponse

Same pattern as ingestion: run the tests, read the failure message, classify the field.

## File Locations

| File | Role |
|------|------|
| `server/schemas.py` | Pydantic API models + `INGESTION_REQUEST_FIELD_MAP` |
| `src/ingest/common/types.py` | `IngestionConfig` dataclass |
| `src/retrieval/common/schemas.py` | `RAGRequest`, `RAGResponse`, `RankedResult` dataclasses |
| `tests/test_schema_contracts.py` | Contract tests + `INFRA_ONLY` / `INTERNAL` classification sets |
