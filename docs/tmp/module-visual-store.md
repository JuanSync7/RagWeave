### `src/vector_db/weaviate/visual_store.py` + `backend.py` additions — Weaviate Visual Collection Store

**Purpose:**

The Visual Collection Store manages the `RAGVisualPages` Weaviate collection, which holds per-page visual embeddings produced by the Visual Embedding Pipeline. It is intentionally separate from the text embedding collection because visual pages require a fundamentally different retrieval strategy: a two-tier approach where a compact 128-dimensional mean vector enables fast approximate-nearest-neighbor (ANN) search to retrieve a shortlist of candidate pages, and a full set of patch vectors stored as a JSON-serialised TEXT field enables a second-pass MaxSim re-scoring pass that refines the shortlist without requiring dense patch vectors to be indexed by the vector database.

Keeping visual pages in their own collection preserves schema independence (visual properties such as `page_width_px`, `page_height_px`, and `minio_key` are meaningless for text chunks), allows the HNSW index to be tuned exclusively for 128-dimensional cosine similarity, and prevents the visual ingestion path from touching or risking corruption of text embeddings. The `RAGVisualPages` name is the default but is parameterised throughout, so deployments that need collection-name isolation (for example per-tenant prefixing) can pass a different name without code changes.

The three source files covered here form a single logical unit:

- `visual_store.py` — the collection-level store functions (create, insert, delete).
- `backend.py` additions — three new abstract methods on the `VectorBackend` ABC that declare the visual interface contract without modifying any existing methods (NFR-909).
- `weaviate/backend.py` additions — the `WeaviateBackend` concrete class that delegates each abstract method call to the corresponding `visual_store` function.

---

**How it works:**

**1. Collection creation — `ensure_visual_collection` (FR-502, FR-504)**

On first use the collection must be created. `ensure_visual_collection` checks whether the named collection already exists via `client.collections.exists(collection)` and returns immediately if it does, making the call idempotent. When the collection is absent it builds:

- A `NamedVectors.none` vector configuration named `"mean_vector"` with a 128-dimensional HNSW index using cosine distance. The `none` vectorizer means Weaviate never tries to vectorize objects automatically; all vectors are supplied by the caller at insert time.
- Eleven scalar properties covering document provenance (`document_id`, `source_key`, `source_uri`, `source_name`, `tenant_id`), page geometry (`page_number`, `total_pages`, `page_width_px`, `page_height_px`), storage location (`minio_key`), and the serialised patch payload (`patch_vectors`).

The `patch_vectors` property carries `skip_vectorization=True`, which prevents Weaviate from attempting module-level vectorization on a field that is intentionally raw JSON text (FR-505).

**2. Batch insert — `add_visual_documents` (FR-507)**

```python
def add_visual_documents(
    client: weaviate.WeaviateClient,
    documents: List[dict[str, Any]],
    collection: str = "RAGVisualPages",
) -> int:
    if not documents:
        return 0
    col = client.collections.get(collection)
    with col.batch.dynamic() as batch:
        for doc in documents:
            mean_vector = doc["mean_vector"]
            properties = {k: v for k, v in doc.items() if k != "mean_vector"}
            batch.add_object(properties=properties, vector={"mean_vector": mean_vector})
    failed = len(col.batch.failed_objects) if hasattr(col.batch, "failed_objects") else 0
    return len(documents) - failed
```

The Weaviate v4 named-vector pattern requires the `vector` argument to `add_object` to be a dictionary keyed by vector name rather than a plain list. Here `{"mean_vector": mean_vector}` is the named-vector envelope that associates the 128-dim float list with the index configured in step 1. All other keys in the document dict become scalar properties. The function uses `col.batch.dynamic()` which lets Weaviate auto-tune batch sizing, and returns the number of objects successfully inserted (total minus failed). If `documents` is empty the function short-circuits and returns `0` without touching the client.

**3. Delete by source key — `delete_visual_by_source_key` (FR-506)**

```python
where = Filter.by_property("source_key").equal(source_key)
result = col.data.delete_many(where=where)
return getattr(result, "matches", 0) or 0
```

All visual page objects for a document share the same `source_key` (the canonical object storage key for the source file). Deleting by `source_key` therefore removes every page of a document atomically in a single server-side filter operation, without the caller needing to enumerate page numbers. The return value is the count of matched (and deleted) objects from the Weaviate `DeleteManyResult`, falling back to `0` if the attribute is absent on older client versions.

**4. ABC → WeaviateBackend delegation chain**

The `VectorBackend` abstract base class declares three new abstract methods (`ensure_visual_collection`, `add_visual_documents`, `delete_visual_by_source_key`) with identical signatures to the store functions but with `client` typed as `Any` and `collection` as `Optional[str]` to remain backend-agnostic. This means any alternative backend (for example a future Qdrant or pgvector backend) must implement the same three visual methods to satisfy the interface contract.

`WeaviateBackend` implements each method by resolving the collection name — using the caller-supplied value if provided, falling back to the class-level constant `_VISUAL_COLLECTION_DEFAULT = "RAGVisualPages"` — and then forwarding the call to the corresponding `visual_store` function imported with a `_wv_` prefix alias. The delegation layer adds no logic of its own; it exists solely to honour the ABC contract and inject the default collection name.

---

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Separate `RAGVisualPages` collection (FR-501) | Single collection with a type discriminator field; separate Weaviate tenant per modality | A dedicated collection allows the HNSW index to be sized and tuned purely for 128-dim cosine vectors, avoids schema pollution in the text collection, and makes query filters simpler (no type-discriminator clause needed on every visual query). |
| Named vector `"mean_vector"` with `vectorizer=none` (FR-504) | Default unnamed vector; multi-vector index for both mean and patch | Named vectors are the Weaviate v4 idiomatic pattern for externally supplied embeddings; `none` vectorizer ensures no accidental re-vectorization. A separate named vector for patch vectors was rejected because patch vectors are used only for CPU-side MaxSim re-scoring, not ANN search, making indexing them wasteful. |
| `patch_vectors` stored as serialised JSON TEXT (FR-505) | Weaviate BLOB property; separate object or external store; structured array property | TEXT avoids binary encoding round-trips, is human-readable in debug queries, and does not require a schema change when patch dimensionality changes. Storing patches externally would add a second lookup per page during re-scoring. |
| Idempotent `ensure_visual_collection` (FR-502) | Fail-fast if collection absent; caller-managed creation | Idempotent creation removes the need for startup ordering guarantees between the pipeline and an admin setup script. It is safe to call on every ingestion run; the existence check is a single lightweight Weaviate metadata call. |
| Delete by `source_key` rather than UUID list (FR-506) | Store per-page UUIDs and delete individually; delete by `document_id` | `source_key` is the stable, externally visible identity of a file. Deleting by `source_key` on the server side is a single atomic filter-delete; UUID-by-UUID deletion would require a prior query to enumerate UUIDs and would be non-atomic. |
| `add_visual_documents` returns insert count (FR-507) | Return `None`; raise on any failure; return list of failed objects | A count is the minimal, backend-neutral success signal. Callers that need stricter guarantees can compare the returned count to `len(documents)` and decide whether to retry or raise; the function itself does not raise on partial failure to allow the caller to apply its own retry policy. |
| Three new ABC methods, existing methods untouched (NFR-909) | Extend existing `add_documents` / `delete_documents` signatures with a `modality` flag | Adding three distinct methods preserves the existing calling convention and avoids conditionals in existing method bodies. Backend implementors that do not yet support visual collections can raise `NotImplementedError` without affecting any text-retrieval code path. |

---

**Configuration:**

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `collection` (store functions) | `str` | `"RAGVisualPages"` | The Weaviate collection name targeted by all three store operations. Override to isolate visual pages by tenant or deployment environment. Must match the name used for creation, insertion, and deletion — passing different names to create and insert will result in a missing collection error. |
| `dimensions` (HNSW config, set at collection creation) | `int` | `128` | The expected dimensionality of `mean_vector` embeddings. This is fixed at collection-creation time; changing it requires dropping and re-creating the collection. Set to match the output dimensionality of the visual mean-pooling model. |
| `distance_metric` (HNSW config, set at collection creation) | `VectorDistances` enum | `VectorDistances.COSINE` | The distance metric used for ANN search. Cosine is appropriate for normalised visual embedding vectors. Changing this requires collection re-creation. |
| `_VISUAL_COLLECTION_DEFAULT` (WeaviateBackend class constant) | `str` | `"RAGVisualPages"` | The fallback collection name used by `WeaviateBackend` when the caller passes `collection=None`. Changing this constant at the class level renames the default target for all visual operations on that backend instance. |

---

**Error behavior:**

`ensure_visual_collection` is the only operation with meaningful idempotency guarantees. If the collection already exists, the function returns without error regardless of whether the existing schema matches the expected schema. A schema mismatch (for example an existing collection with the same name but different properties or vector dimensions) will not be detected or corrected; the caller is responsible for ensuring that the collection was originally created by this function or an equivalent configuration.

`add_visual_documents` does not raise on partial batch failure. Weaviate's `batch.dynamic()` context manager absorbs per-object errors internally. The function reads `col.batch.failed_objects` after the context exits and subtracts the failed count from the total to compute the return value. Callers should treat a return value less than `len(documents)` as a partial failure and apply their own retry or alerting logic. If `documents` is an empty list the function returns `0` immediately without contacting Weaviate.

`delete_visual_by_source_key` returns `0` both when no objects matched the filter and when the `DeleteManyResult` object does not carry a `matches` attribute (older Weaviate client versions). Callers that need to distinguish "nothing to delete" from "delete count unavailable" should not rely on this return value as a strict audit signal; it is best used as an approximate progress counter or log annotation.

All three store functions propagate Weaviate client exceptions (`weaviate.exceptions.WeaviateConnectionError`, `weaviate.exceptions.WeaviateQueryError`, and similar) directly to the caller without wrapping. The `WeaviateBackend` delegation layer adds no exception handling either. Callers at the pipeline orchestration level are responsible for catch-and-retry behaviour on transient connection errors.
