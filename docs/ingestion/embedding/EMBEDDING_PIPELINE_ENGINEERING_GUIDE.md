# Embedding Pipeline Engineering Guide

> **Status:** Authoritative post-implementation guide for the Embedding Pipeline,
> including Phase 4 batch embedding (FR-1210–FR-1214).

---

## 1. Overview

The Embedding Pipeline is Phase 2 of RagWeave's two-phase ingestion workflow. It receives
clean Markdown text from the Clean Document Store boundary, runs it through an 8-node
LangGraph DAG, and persists chunk embeddings into Weaviate.

**Phase 4 batch embedding (FR-1210–FR-1214)** introduced configurable chunked batching
for the embedding step. Prior to this work, all chunks in a document were embedded in a
single `embed_documents` call. Under Phase 4:

- Chunks are split into sequential batches of a configurable size (FR-1210, FR-1212).
- `embedding_batch_size` is a typed config field with a validated range of [1, 2048] (FR-1211).
- Each batch is retried independently up to 3 times before being permanently excluded (FR-1213).
- Per-batch and aggregate metrics are emitted as structured log records (FR-1214).
- `trace_id`, `schema_version`, and `batch_id` are attached to every chunk payload persisted
  to Weaviate (FR-3052, FR-3053, FR-3100).

---

## 2. Module Layout

```
src/ingest/embedding/
├── __init__.py                        # Re-exports run_embedding_pipeline
├── state.py                           # EmbeddingPipelineState TypedDict
├── workflow.py                        # build_embedding_graph() — graph topology
├── impl.py                            # run_embedding_pipeline() — entry point
└── nodes/
    ├── chunking.py                    # Node 6
    ├── chunk_enrichment.py            # Node 7
    ├── metadata_generation.py         # Node 8
    ├── cross_reference_extraction.py  # Node 9 (conditional)
    ├── knowledge_graph_extraction.py  # Node 10 (conditional)
    ├── quality_validation.py          # Node 11
    ├── embedding_storage.py           # Node 12  ← batch embedding lives here
    └── knowledge_graph_storage.py     # Node 13 (conditional)
```

### embedding_storage.py exports

| Symbol | Kind | Purpose |
|---|---|---|
| `embedding_storage_node` | function | LangGraph node — top-level entry point |
| `_form_batches` | function | Split a flat list into sequential sub-lists |
| `_embed_batches` | function | Embed text batches with per-batch retry isolation |
| `_log_batch_metrics` | function | Emit `embedding_batch_complete` log record |
| `_log_batch_summary` | function | Emit `embedding_batch_summary` log record |

Logger name: `rag.ingest.embedding.storage`

Module-level constants:

```python
_BATCH_MAX_RETRIES = 3
_BATCH_RETRY_DELAY = 1.0  # seconds (multiplied by attempt number)
```

---

## 3. Key Function Signatures

### `_form_batches`

```python
def _form_batches(items: list, batch_size: int) -> list[list]:
    """Split items into sequential batches of at most batch_size.

    Handles partial final batches without error (FR-1212).
    Returns an empty list if items is empty (FR-1212 AC-3).
    """
```

**Behaviour:** Pure list-splitting utility. No I/O, no side effects. Returns an empty
list for empty input. The final batch may contain fewer than `batch_size` items.

### `_embed_batches`

```python
def _embed_batches(
    embedder,
    text_batches: list[list[str]],
    max_retries: int = _BATCH_MAX_RETRIES,
) -> tuple[list[list[float]], list[dict[str, Any]], list[bool]]:
    """Embed text batches with per-batch retry isolation.

    Returns:
        (all_vectors, errors, success_mask) where all_vectors is the flat list of
        embedding vectors for successfully embedded batches, errors is a list of
        error dicts for failed batches, and success_mask[i] is True when batch i
        succeeded.
    """
```

**Return value layout:**

| Return element | Type | Description |
|---|---|---|
| `all_vectors` | `list[list[float]]` | Flat list of vectors — only from successful batches |
| `errors` | `list[dict[str, Any]]` | One error dict per permanently-failed batch |
| `success_mask` | `list[bool]` | `success_mask[i]` is `True` when `text_batches[i]` succeeded |

### `_log_batch_metrics`

```python
def _log_batch_metrics(
    batch_idx: int,
    total_batches: int,
    chunk_count: int,
    latency_ms: float,
) -> None:
    """Log per-batch embedding metrics (FR-1214 AC-1)."""
```

### `_log_batch_summary`

```python
def _log_batch_summary(
    total_chunks: int,
    total_batches: int,
    total_ms: float,
) -> None:
    """Log aggregate embedding throughput (FR-1214 AC-2)."""
```

### `embedding_storage_node`

```python
def embedding_storage_node(state: EmbeddingPipelineState) -> dict[str, Any]:
    """Persist chunk embeddings and metadata into the configured vector store.

    Args:
        state: Ingestion pipeline state.

    Returns:
        Partial state update containing ``stored_count`` and an updated
        ``processing_log``. When the workflow is skipped or there are no chunks,
        returns ``stored_count=0``.
    """
```

---

## 4. Batch Embedding Flow

The full sequence inside `embedding_storage_node` after the skip-check and collection setup:

### Step 1 — Build lifecycle metadata dict

```python
lifecycle_meta = {
    "trace_id": state.get("trace_id", ""),
    "schema_version": PIPELINE_SCHEMA_VERSION,
    "batch_id": state.get("batch_id", ""),
}
```

This dict is merged into every chunk's metadata before storage.

### Step 2 — Extract texts

```python
texts = [chunk.metadata.get("enriched_content", chunk.text) for chunk in chunks]
```

If a chunk carries `enriched_content` in its metadata (from the VLM enrichment node),
that is used as the text to embed. Otherwise `chunk.text` is used.

### Step 3 — Form batches

```python
batch_size = runtime.config.embedding_batch_size
text_batches = _form_batches(texts, batch_size)
```

### Step 4 — Embed with retry isolation

```python
all_vectors, batch_errors, success_mask = _embed_batches(runtime.embedder, text_batches)
```

Each entry in `text_batches` is an independent unit. A failure in one batch does not
affect the others.

### Step 5 — Rebuild successful chunk indices

```python
successful_chunk_indices: list[int] = []
offset = 0
for i, batch in enumerate(text_batches):
    if success_mask[i]:
        successful_chunk_indices.extend(range(offset, offset + len(batch)))
    offset += len(batch)
```

Failed batches are simply skipped; their corresponding chunks are excluded from output.

### Step 6 — Construct `DocumentRecord` objects

```python
records = [
    DocumentRecord(
        text=texts[idx],
        embedding=all_vectors[pos],
        metadata={**chunks[idx].metadata, **lifecycle_meta},
    )
    for pos, idx in enumerate(successful_chunk_indices)
]
```

The lifecycle metadata (`trace_id`, `schema_version`, `batch_id`) is merged last,
so it always wins over any pre-existing chunk metadata keys with the same name.
The original `ProcessedChunk` objects are never mutated.

### Step 7 — Persist

```python
stored_count = add_documents(
    runtime.weaviate_client, records,
    collection=runtime.config.target_collection or None,
)
```

### Step 8 — Return partial state

```python
return {
    "stored_count": stored_count,
    "errors": existing_errors + batch_errors,
    "processing_log": append_processing_log(state, "embedding_storage:ok"),
}
```

Batch errors from permanently-failed batches are appended to the state error list.
The node does **not** raise; all errors are communicated through state.

---

## 5. Retry Isolation

Each batch is retried independently inside `_embed_batches`:

```
for batch_idx, batch_texts in enumerate(text_batches):
    for attempt in range(1, max_retries + 1):   # attempts 1, 2, 3
        try:
            batch_vectors = embedder.embed_documents(batch_texts)
            break                                 # success — stop retrying this batch
        except Exception:
            if attempt < max_retries:
                time.sleep(_BATCH_RETRY_DELAY * attempt)   # 1s, 2s
```

**Key invariants (FR-1213):**

- A successfully embedded batch is never re-embedded on a later retry of a different batch.
- `success_mask[i]` is set to `True` only when `batch_vectors is not None` after the loop.
- When all retries for a batch are exhausted, an error dict is recorded:

```python
{
    "type": "batch_embedding_failure",
    "batch_index": batch_idx + 1,          # 1-based
    "chunk_range": f"{chunk_start}-{chunk_end - 1}",
    "error": str(last_error),
}
```

- Retry delays are linear: attempt 1 → sleep 1.0s, attempt 2 → sleep 2.0s.
  There is no sleep before the first attempt.

**Partial success:** If batches B1 and B3 succeed but B2 fails, the records for B1 and
B3 are still stored. Only B2's chunks are excluded. The caller receives a non-empty
`errors` list in the returned state.

---

## 6. Observability

All log records are emitted to the `rag.ingest.embedding.storage` logger at `INFO` level
(warning/error for failures — see below).

### `embedding_batch_complete` (FR-1214 AC-1)

Emitted once per **successfully** embedded batch:

| Log extra key | Type | Description |
|---|---|---|
| `batch_index` | int | 1-based batch number |
| `total_batches` | int | Total number of batches for this document |
| `chunk_count` | int | Number of chunks in this batch |
| `latency_ms` | float | Embedding call wall time in milliseconds (rounded to 1 decimal) |

### `embedding_batch_summary` (FR-1214 AC-2)

Emitted once per document, after all batches have been processed (success or failure):

| Log extra key | Type | Description |
|---|---|---|
| `total_chunks` | int | Total successfully embedded chunks across all batches |
| `total_batches` | int | Total number of batches attempted |
| `total_ms` | float | Sum of per-batch latencies in milliseconds |
| `throughput_chunks_per_sec` | float | `total_chunks / (total_ms / 1000)`, or `0.0` when `total_ms == 0` |

### Failure logs

On each failed attempt within a batch, a `WARNING` is emitted:

```
batch {n}/{total} failed attempt {attempt}/{max_retries}: {exception}
```

When all retries are exhausted, an `ERROR` is emitted:

```
batch {n}/{total} exhausted retries batch_index={n} chunk_range={start}-{end}
```

---

## 7. Configuration

### Inference backend

```
INFERENCE_BACKEND=local   # or: vllm
```

Controls which embedding provider is instantiated by `get_embedding_provider()` in
`src/core/embeddings.py`:

| Value | Provider class | Notes |
|-------|---------------|-------|
| `local` (default) | `LocalBGEEmbeddings` | BAAI/bge-m3 loaded in-process via `sentence-transformers` |
| `vllm` | `LiteLLMEmbeddings` | Qwen3-Embedding served by the `rag-vllm-embed` Docker service via LiteLLM |

When `INFERENCE_BACKEND=vllm`, `sentence-transformers` is not imported; the worker image
can run without that package installed. Additional vLLM connection settings (`VLLM_*`) are
read from `config/settings.py` and validated at startup — an invalid combination causes a
fast-fail `ValueError` before any file processing begins.

### Environment variable

```
RAGWEAVE_EMBEDDING_BATCH_SIZE=64
```

Read in `config/settings.py` as:

```python
RAG_INGESTION_EMBEDDING_BATCH_SIZE: int = int(os.environ.get(
    "RAGWEAVE_EMBEDDING_BATCH_SIZE", "64"
))  # FR-1211
```

The default value is **64**.

### Config field

In `src/ingest/common/types.py` (`IngestionConfig` dataclass):

```python
# -- Batch embedding (FR-1211) --
embedding_batch_size: int = RAG_INGESTION_EMBEDDING_BATCH_SIZE
"""Number of chunks per embedding batch. Range: 1-2048. Default: 64. FR-1211"""
```

### Validation

`verify_core_design()` in `src/ingest/impl.py` calls `_check_embedding_batch_config()`:

```python
def _check_embedding_batch_config(
    config: IngestionConfig,
) -> tuple[list[str], list[str]]:
    """Validate embedding batch configuration. FR-1211."""
    errors: list[str] = []
    warnings: list[str] = []
    if not (1 <= config.embedding_batch_size <= 2048):
        errors.append(
            f"embedding_batch_size={config.embedding_batch_size} is out of range;"
            " must be between 1 and 2048 (inclusive)"
        )
    return errors, warnings
```

An out-of-range value causes `verify_core_design()` to return `ok=False`. In production,
`ingest_directory()` calls `verify_core_design()` before any file processing begins and
raises `ValueError` immediately if there are errors:

```python
design = verify_core_design(config)
if not design.ok:
    raise ValueError("Invalid ingestion config: " + "; ".join(design.errors))
```

**Valid range:** [1, 2048] inclusive.

---

## 8. trace_id / schema_version / batch_id Propagation

These three lifecycle fields are attached to every chunk payload stored in Weaviate
(FR-3052, FR-3053, FR-3100). Their propagation chain:

### trace_id (FR-3052)

1. Generated as `uuid.uuid4()` at the start of `ingest_file()` in `src/ingest/impl.py`.
2. Passed into Phase 1 (`run_document_processing`) as `trace_id=trace_id`.
3. Read back from Phase 1 state: `phase1.get("trace_id", trace_id)`.
4. Passed into Phase 2 (`run_embedding_pipeline`) as `trace_id=...`.
5. Lives in `EmbeddingPipelineState.trace_id` (field defined in `state.py`).
6. Read in `embedding_storage_node` via `state.get("trace_id", "")`.
7. Merged into every `DocumentRecord.metadata` dict as `"trace_id"`.

Empty string (`""`) is the safe default when the field is absent (legacy paths).

### schema_version (FR-3100)

The value is the module-level constant `PIPELINE_SCHEMA_VERSION = "1.0.0"` defined in
`src/ingest/common/schemas.py`. It is imported directly into `embedding_storage.py` and
added to `lifecycle_meta` unconditionally.

### batch_id (FR-3053)

1. Passed as an optional argument to `ingest_directory()` and `ingest_file()`.
2. Forwarded to Phase 2 via `run_embedding_pipeline(..., batch_id=batch_id)`.
3. Lives in `EmbeddingPipelineState.batch_id`.
4. Read in `embedding_storage_node` via `state.get("batch_id", "")`.
5. Merged into every `DocumentRecord.metadata` dict as `"batch_id"`.

Empty string is the safe default when no batch grouping is in use.

All three keys are also written to the manifest entry in `ingest_directory()` for
cross-referencing outside of Weaviate.

---

## 9. Troubleshooting

### A batch fails permanently — what happens?

1. `_embed_batches` exhausts all 3 retry attempts for the batch.
2. An error dict of type `"batch_embedding_failure"` is appended to the `errors` list.
3. `success_mask[i]` remains `False` for that batch index.
4. When `embedding_storage_node` rebuilds `successful_chunk_indices`, the failed batch's
   chunk indices are simply skipped.
5. Only the successful chunks' `DocumentRecord` objects are passed to `add_documents`.
6. The returned state has `"errors"` containing the batch failure dict(s).
7. `stored_count` reflects only the chunks that were successfully stored.
8. The pipeline does **not** halt. Downstream nodes still run; the error list is
   returned to the caller as part of `IngestFileResult.errors`.

### Diagnosing partial failures

Look for `embedding_batch_summary` in logs. A `total_chunks` value lower than the total
number of document chunks signals that at least one batch failed. Then look for
`batch exhausted retries` ERROR lines immediately before the summary, which identify
the batch index and chunk range.

### batch_size too small — performance impact

Each `embed_documents` call has fixed overhead (model warm-up, HTTP round-trip for
remote embedders). Very small batch sizes (e.g., `batch_size=1`) significantly increase
total embedding time. The default of 64 is a balance point for local BGE models.

### batch_size too large — memory pressure

For documents with thousands of chunks, a very large batch size (approaching 2048) may
cause OOM in the embedding model. If the embedder raises a memory error during a large
batch, the retry loop will re-attempt it — but the error is persistent (not transient),
so all 3 attempts will fail. Reduce `RAGWEAVE_EMBEDDING_BATCH_SIZE` to a lower value.

### Validating the config before a run

```python
from src.ingest.common.types import IngestionConfig
from src.ingest.impl import verify_core_design

config = IngestionConfig(embedding_batch_size=256)
check = verify_core_design(config)
print(check.ok, check.errors)
```
