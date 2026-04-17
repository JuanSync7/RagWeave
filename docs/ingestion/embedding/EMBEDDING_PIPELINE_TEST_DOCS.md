# Embedding Pipeline Test Documentation

> **Scope:** Phase 4 batch embedding optimisation tests (FR-1210–FR-1214).
> Test file: `tests/ingest/nodes/test_embedding_storage_batching.py`
> Total tests: 30

---

## 1. Test Strategy

The test suite validates the batch embedding subsystem end-to-end — from the low-level
helper functions up through the LangGraph node integration. It is structured around the
five functional requirements introduced in Phase 4:

| Area | What is tested |
|---|---|
| Batch formation | Correctness and order preservation of `_form_batches` across edge cases |
| Config validation | `embedding_batch_size` range enforcement and env-var-to-config flow |
| Retry isolation | Per-batch retry independence, delay timing, success-mask accuracy |
| Observability | Structured log record keys and values for both log event types |
| Node integration | `embedding_storage_node` with batching: record counts, partial failure, lifecycle metadata |

All tests use `unittest.mock` to avoid any real embedding model or Weaviate connection.
The `time.sleep` call in the retry loop is patched for retry tests so the suite runs
quickly without real delays.

---

## 2. Test File Map

### `TestFormBatches` (7 tests) — FR-1210, FR-1212

Tests for `_form_batches`. Each test exercises a distinct boundary condition:

| Test | Condition |
|---|---|
| `test_standard_split_preserves_order` | Normal split with partial final batch |
| `test_empty_input_returns_empty` | Empty list → empty result (FR-1212 AC-3) |
| `test_exact_fit_single_batch` | Item count equals batch size → single batch |
| `test_single_item_smaller_than_batch` | 1 item, batch_size=64 → 1 batch of 1 |
| `test_batch_size_one` | batch_size=1 → each item in its own batch |
| `test_batch_size_larger_than_input` | batch_size > len(items) → single batch |
| `test_order_preserved_strings` | Order of string items is preserved; no items dropped |

---

### `TestEmbeddingBatchSizeValidation` (7 tests) — FR-1211

Tests for `_check_embedding_batch_config()` via `verify_core_design()`. Uses `_safe_cfg()`
helper to build `IngestionConfig` with safe defaults so that only the batch-size validation
is the variable under test:

| Test | Condition |
|---|---|
| `test_zero_batch_size_fails` | `embedding_batch_size=0` → `result.ok` is False |
| `test_over_max_batch_size_fails` | `embedding_batch_size=2049` → error |
| `test_negative_batch_size_fails` | `embedding_batch_size=-1` → error |
| `test_default_batch_size_passes` | `embedding_batch_size=64` → `result.ok` is True |
| `test_min_boundary_passes` | `embedding_batch_size=1` → passes |
| `test_max_boundary_passes` | `embedding_batch_size=2048` → passes |
| `test_env_var_flows_to_settings` | `RAGWEAVE_EMBEDDING_BATCH_SIZE=32` env var → `RAG_INGESTION_EMBEDDING_BATCH_SIZE==32` after module reload |

---

### `TestEmbedBatches` (6 tests) — FR-1213

Tests for `_embed_batches`. Covers retry independence, delay timing, and error dict shape:

| Test | Condition |
|---|---|
| `test_all_succeed_returns_all_vectors` | All batches succeed → full vector list, no errors |
| `test_first_batch_fails_permanently_second_succeeds` | First batch exhausts 3 retries; second succeeds; only second vectors returned; error dict has correct `chunk_range` |
| `test_single_batch_fails_permanently_error_dict` | Single batch fails 3x → empty vectors, one error dict with correct `type`, `batch_index`, `chunk_range`, `error` |
| `test_successful_batches_not_re_embedded` | First batch succeeds first try; second batch fails 2x then succeeds; `embed_documents` called exactly 4 times total |
| `test_retry_delay_called_between_attempts` | Two failures then success → `time.sleep` called twice with delays `1.0` and `2.0` (FR-1213 linear backoff) |
| `test_empty_batches_list` | Empty `text_batches` → empty returns; `embed_documents` never called |

---

### `TestBatchObservability` (4 tests) — FR-1214

Tests for `_log_batch_metrics` and `_log_batch_summary` log output using `caplog`:

| Test | Condition |
|---|---|
| `test_log_batch_metrics_emits_structured_record` | `_log_batch_metrics` emits exactly one `embedding_batch_complete` record with correct `batch_index`, `total_batches`, `chunk_count`, `latency_ms` extras |
| `test_log_batch_summary_emits_structured_record` | `_log_batch_summary` emits exactly one `embedding_batch_summary` record with correct `total_chunks`, `total_batches`, `total_ms`, `throughput_chunks_per_sec` extras |
| `test_embed_batches_emits_complete_and_summary_logs` | 2-batch run → 2 `embedding_batch_complete` records + 1 `embedding_batch_summary` record |
| `test_summary_throughput_zero_when_no_elapsed` | `total_ms=0.0` → `throughput_chunks_per_sec == 0.0` (no divide-by-zero) |

---

### `TestEmbeddingStorageNodeBatching` (6 tests) — FR-1210–FR-1214, FR-3052/3053/3100

Integration tests for `embedding_storage_node`. All three Weaviate call sites
(`ensure_collection`, `delete_by_source_key`, `add_documents`) are patched:

| Test | Condition |
|---|---|
| `test_5_chunks_batch_size_2_three_batches_all_stored` | 5 chunks + batch_size=2 → 3 batches formed; `add_documents` receives 5 records; `stored_count==5` |
| `test_batch_2_fails_chunks_0_1_excluded_errors_recorded` | Middle batch fails permanently → only 3 records passed to `add_documents`; error dict with `batch_index==2` and `chunk_range=="2-3"` in state errors |
| `test_all_batches_succeed_no_errors` | All batches succeed → `stored_count==4`, errors list empty |
| `test_lifecycle_meta_attached_to_stored_records` | `trace_id`, `batch_id`, and `schema_version` present in every `DocumentRecord.metadata` |
| `test_should_skip_returns_zero_stored` | `should_skip=True` in state → `stored_count==0`, `add_documents` never called |
| `test_embed_exception_caught_and_recorded` | All retries exhausted → no exception raised; error recorded in state `errors` |

---

## 3. Coverage by FR

| FR | Description | Test class / functions |
|---|---|---|
| FR-1210 | Chunks embedded in configurable batches | `TestFormBatches`, `TestEmbeddingStorageNodeBatching::test_5_chunks_batch_size_2_three_batches_all_stored` |
| FR-1211 | `embedding_batch_size` config field + range validation | `TestEmbeddingBatchSizeValidation` (all 7 tests) |
| FR-1212 | Partial final batch handled without error | `TestFormBatches::test_standard_split_preserves_order`, `test_empty_input_returns_empty`, `test_batch_size_larger_than_input` |
| FR-1213 | Per-batch retry isolation; failed batches excluded | `TestEmbedBatches` (all 6 tests), `TestEmbeddingStorageNodeBatching::test_batch_2_fails_chunks_0_1_excluded_errors_recorded`, `test_embed_exception_caught_and_recorded` |
| FR-1214 | Structured observability logs per batch and aggregate | `TestBatchObservability` (all 4 tests) |
| FR-3052 | `trace_id` propagated to chunk payloads | `TestEmbeddingStorageNodeBatching::test_lifecycle_meta_attached_to_stored_records` |
| FR-3053 | `batch_id` propagated to chunk payloads | `TestEmbeddingStorageNodeBatching::test_lifecycle_meta_attached_to_stored_records` |
| FR-3100 | `schema_version` attached to chunk payloads | `TestEmbeddingStorageNodeBatching::test_lifecycle_meta_attached_to_stored_records` |

---

## 4. Fixture Reference

### Module-level patch targets

```python
_ADD_DOCS = "src.ingest.embedding.nodes.embedding_storage.add_documents"
_DELETE   = "src.ingest.embedding.nodes.embedding_storage.delete_by_source_key"
_ENSURE   = "src.ingest.embedding.nodes.embedding_storage.ensure_collection"
```

These are used with `unittest.mock.patch` in all `TestEmbeddingStorageNodeBatching` tests
to prevent any real Weaviate calls.

### `_make_chunk(text: str = "chunk text") -> ProcessedChunk`

Builds a minimal `ProcessedChunk` with empty metadata. Used to construct chunk lists
for state fixtures.

### `_make_state(...) -> dict`

Builds a complete fake `EmbeddingPipelineState` dict. Parameters:

| Parameter | Default | Description |
|---|---|---|
| `chunks` | `[]` | `ProcessedChunk` list |
| `batch_size` | `64` | `IngestionConfig.embedding_batch_size` |
| `update_mode` | `False` | `IngestionConfig.update_mode` |
| `source_key` | `"doc-001"` | State source key |
| `source_name` | `"doc.md"` | State source name |
| `embed_return` | `None` | If set, `mock_embedder.embed_documents.return_value`; otherwise side_effect returns `[[0.1, 0.1, 0.1]] * len(texts)` |

Returns a dict containing `chunks`, `source_key`, `source_name`, `stored_count`,
`errors`, `processing_log`, and `runtime` (with `MagicMock` weaviate client and
mock embedder).

### `_safe_cfg(**overrides) -> IngestionConfig`

Builds an `IngestionConfig` with minimal safe defaults that pass all other
`verify_core_design()` checks, leaving `embedding_batch_size` as the free variable.
Defaults include: `chunk_size=512`, `chunk_overlap=64`, `build_kg=False`,
`enable_docling_parser=False`, `vlm_mode="disabled"`,
`enable_multimodal_processing=False`, `enable_vision_processing=False`,
`enable_visual_embedding=False`, `enable_knowledge_graph_storage=False`,
`parser_strategy="auto"`, `chunker="native"`.

### `caplog` (pytest built-in)

Used by `TestBatchObservability` to capture log records from `rag.ingest.embedding.storage`
at `logging.INFO` level. Tests inspect `caplog.records` for records where
`record.message == "embedding_batch_complete"` or `"embedding_batch_summary"` and verify
the extra dict keys directly via `rec.__dict__`.

### `monkeypatch` (pytest built-in)

Used by `test_env_var_flows_to_settings` to set `RAGWEAVE_EMBEDDING_BATCH_SIZE` in the
environment and reload `config.settings` to verify the env-var-to-constant flow. The test
restores the original state via `monkeypatch.delenv` and a second `importlib.reload`.

---

## 5. Running Tests

Run the full batch embedding test file:

```bash
pytest tests/ingest/nodes/test_embedding_storage_batching.py -v
```

Run a single class:

```bash
pytest tests/ingest/nodes/test_embedding_storage_batching.py::TestEmbedBatches -v
```

Run with log output visible (useful for verifying observability tests):

```bash
pytest tests/ingest/nodes/test_embedding_storage_batching.py -v -s --log-cli-level=INFO
```

Run by FR coverage marker (if markers are configured):

```bash
pytest tests/ingest/nodes/test_embedding_storage_batching.py -k "FR1213 or retry"
```
