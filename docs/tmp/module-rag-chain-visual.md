### `src/retrieval/pipeline/rag_chain.py` — RAGChain Visual Retrieval Track

**Purpose:**

`RAGChain` is the orchestrator for the full retrieval pipeline. This section documents only the visual retrieval additions — the three methods and initialization changes that implement the visual track. The visual track runs after the text retrieval track (stages 1–5: query processing, KG expansion, embedding, hybrid search, reranking) and is gated by `RAG_VISUAL_RETRIEVAL_ENABLED`. It encodes the processed query via ColQwen2, searches the `RAGVisualPages` Weaviate collection, generates presigned MinIO URLs for each matched page, and attaches the results to `RAGResponse.visual_results`. The ColQwen2 model is loaded lazily — only on the first visual query, not at `RAGChain.__init__` time.

Spec requirements addressed: FR-601 (visual track enabled by config), FR-603 (lazy model loading), FR-605 (encode processed query), FR-607 (presigned URLs per result), FR-609 (search visual collection), FR-611 (attach results to response), FR-613 (unload on close), FR-617 (stage budget for visual retrieval), FR-111 (fail-fast config validation).

**How it works:**

**Initialization (`__init__`):**

After loading GPU models (BGE-M3, reranker) and other pipeline components, the constructor checks `RAG_VISUAL_RETRIEVAL_ENABLED`:

```python
self._visual_retrieval_enabled = RAG_VISUAL_RETRIEVAL_ENABLED
self._visual_model = None
self._visual_processor = None
if self._visual_retrieval_enabled:
    from config.settings import validate_visual_retrieval_config
    validate_visual_retrieval_config()   # fail fast on bad config
    logger.info("Visual retrieval enabled — model will be loaded on first visual query.")
```

The model and processor are initialized to `None` and loaded on first use. `validate_visual_retrieval_config()` raises `ValueError` immediately if configuration is contradictory (e.g., empty collection name, out-of-range score threshold), preventing silent misconfiguration.

**Lazy model loading (`_ensure_visual_model`):**

```python
def _ensure_visual_model(self) -> None:
    if self._visual_model is not None:
        return  # warm path — no-op after first load
    with self.tracer.span("visual_retrieval.model_load"):
        from src.ingest.support.colqwen import ensure_colqwen_ready, load_colqwen_model
        from config.settings import RAG_INGESTION_COLQWEN_MODEL
        ensure_colqwen_ready()
        self._visual_model, self._visual_processor = load_colqwen_model(RAG_INGESTION_COLQWEN_MODEL)
```

The warm path (`if self._visual_model is not None: return`) is a single attribute check — negligible cost on every query after the first.

**Visual retrieval track (`_run_visual_retrieval`):**

Called from `run()` when `self._visual_retrieval_enabled` is True, after the text retrieval stages complete. Executes three sequential steps, each wrapped in an observability span:

1. `visual_retrieval.text_encode`: Calls `embed_text_query(self._visual_model, self._visual_processor, processed_query)` to produce a 128-dim float list. Uses the **processed query** (post-reformulation), not the raw user input.

2. `visual_retrieval.search`: Calls `search_visual(client=self._weaviate_client, query_vector=query_vector, limit=RAG_VISUAL_RETRIEVAL_LIMIT, score_threshold=RAG_VISUAL_RETRIEVAL_MIN_SCORE, tenant_id=tenant_id)`. Uses the persistent Weaviate client shared with the text retrieval path.

3. `visual_retrieval.presigned_urls`: Creates a new `minio_client` per call, then iterates `page_records`. For each record, calls `get_page_image_url(minio_client, minio_key=record["minio_key"])`. Per-page URL generation failures are logged as WARNING and the page is skipped (FR-905 — per-page isolation). Successfully processed pages are assembled into `VisualPageResult` dataclasses.

**Pipeline integration in `run()`:**

The `run()` method allocates a stage budget for `"visual_retrieval"` from `stage_budget_overrides` or `RAG_STAGE_BUDGET_VISUAL_RETRIEVAL_MS`. After the text retrieval stages complete (stages 1–5 or 1–6 with generation), if `self._visual_retrieval_enabled` is True:

```python
visual_results = self._run_visual_retrieval(processed_query, tenant_id)
# attached to response:
response.visual_results = visual_results if visual_results else None
```

**Close (`close`):**

```python
if self._visual_model is not None:
    from src.ingest.support.colqwen import unload_colqwen_model
    unload_colqwen_model(self._visual_model)
    self._visual_model = None
    self._visual_processor = None
```

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Lazy model loading (load on first query, not at init) | Eager loading at startup | Avoids VRAM consumption when visual retrieval is enabled but no visual queries have been issued. Particularly important during server startup where multiple workers may initialize RAGChain simultaneously. |
| Visual track runs sequentially after text track | Parallel execution of text and visual tracks | BGE-M3 (text embedding) and ColQwen2 (visual encoding) both use GPU. Running them concurrently causes VRAM contention and meta-tensor errors on constrained hardware (RTX 2060). Sequential execution is the safe choice. |
| Use processed query (not raw query) for visual encoding | Use raw user query | The query processor reformulates ambiguous, multi-part, or poorly-phrased queries into a cleaner retrieval query. Using the processed query improves visual search quality for the same reason it improves text search quality. |
| Per-page URL generation failure = skip that page | Abort entire visual retrieval on any URL failure | A single MinIO error should not erase all visual results. Returning partial results is strictly better than returning none. |
| New MinIO client per `_run_visual_retrieval` call | Persistent MinIO client like Weaviate | MinIO clients are lightweight (no persistent connection). Creating one per call avoids connection lifecycle management. The performance cost is negligible compared to the GPU inference and Weaviate query steps. |
| Config validation at init (`validate_visual_retrieval_config`) | Lazy validation at first query | Fail-fast at startup surfaces configuration errors immediately, before any traffic is served. Deferring to first query would hide misconfiguration until a user hits the visual path. |

**Configuration:**

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `RAG_VISUAL_RETRIEVAL_ENABLED` | `bool` | `False` | Master switch — if False, visual track is never executed and ColQwen2 is never loaded |
| `RAG_INGESTION_COLQWEN_MODEL` | `str` | `"vidore/colqwen2-v1.0"` | Model identifier used for both ingestion-time embedding and retrieval-time query encoding |
| `RAG_VISUAL_RETRIEVAL_LIMIT` | `int` | `5` | Maximum visual results requested from Weaviate |
| `RAG_VISUAL_RETRIEVAL_MIN_SCORE` | `float` | `0.3` | Minimum cosine similarity for a page to be included |
| `RAG_STAGE_BUDGET_VISUAL_RETRIEVAL_MS` | `int` | `10000` | Stage time budget in milliseconds for the visual retrieval stage |

**Error behavior:**

- `ColQwen2LoadError` from `_ensure_visual_model`: Propagates up through `_run_visual_retrieval` to `run()`. The caller should catch this, log it, and return the text-only `RAGResponse` with `visual_results=None`.
- `ValueError` from `validate_visual_retrieval_config` at init: Propagates immediately, preventing RAGChain from being constructed with invalid config. The server or CLI will fail to start.
- `VisualEmbeddingError` from `embed_text_query`: Propagates from `_run_visual_retrieval`. Callers should treat as a non-fatal visual track failure and return text-only results.
- `weaviate.exceptions.WeaviateQueryError` from `search_visual`: Propagates from `_run_visual_retrieval`. Same treatment — non-fatal, return text-only results.
- Per-page MinIO URL generation failure: Caught inside `_run_visual_retrieval`, logged as WARNING, page skipped. Does not raise.
