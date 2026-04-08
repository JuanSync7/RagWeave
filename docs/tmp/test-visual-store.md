### `src/vector_db/weaviate/visual_store.py` + `backend.py` — Weaviate Visual Collection Store

**Module purpose:** Manages the `RAGVisualPages` Weaviate collection with idempotent creation, batch insert with named-vector support, and filter-based deletion by source key, exposed through abstract-base-class additions and WeaviateBackend delegation.

**In scope:**
- `ensure_visual_collection`: idempotent collection creation with exact schema (11 scalar properties + `mean_vector` named vector, 128-dim HNSW cosine, `patch_vectors` skip_vectorization flag)
- `add_visual_documents`: batch insert with mean_vector split, failed-object counting, empty-input short-circuit, and return of inserted count
- `delete_visual_by_source_key`: filter-based deletion via `source_key` equality, returning match count with safe fallback to 0
- VectorBackend ABC: three new abstract method signatures (ensure_visual_collection, add_visual_documents, delete_visual_by_source_key)
- WeaviateBackend delegation: `collection or "RAGVisualPages"` default resolution and forwarding to store functions
- Exception propagation: Weaviate client exceptions passed through without wrapping

**Out of scope:**
- ANN query / similarity search logic (tested under retrieval pipeline)
- MaxSim reranking against `patch_vectors` (app-side, not a store responsibility)
- MinIO storage operations (separate backend)
- Schema migration or diff detection when collection exists with wrong schema
- Text collection (`RAGTextPages`) and its interactions with visual collection
- Authentication or connection management for the Weaviate client

---

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Create collection when absent (FR-502, FR-504) | `client.collections.exists` returns False; no existing collection | `client.collections.create` called once with `"mean_vector"` NamedVector, 128-dim, cosine HNSW; all 11 scalar properties present; `patch_vectors` has `skip_vectorization=True`; function returns None without error |
| Idempotent: collection already exists (FR-502) | `client.collections.exists` returns True | `client.collections.create` is NOT called; function returns immediately without error |
| Batch insert 50 documents, zero failures (FR-507) | List of 50 dicts each containing `mean_vector` (128-float list) + all required properties; `col.batch.failed_objects` is empty | Returns 50; each `batch.add_object` call receives `properties` dict without `mean_vector` key and `vector={"mean_vector": <128-float list>}` |
| Batch insert with partial failures (FR-507 edge) | List of 10 dicts; `col.batch.failed_objects` contains 2 entries | Returns 8 (10 - 2) |
| Empty document list (FR-507 boundary) | `documents = []` | Returns 0 immediately; `client.collections.get` is NOT called |
| Delete matching objects (FR-506) | `source_key="doc_abc"`; result has `matches=3` | Returns 3; filter applied as `Filter.by_property("source_key").equal("doc_abc")` |
| Delete with zero matches (FR-506) | `source_key="nonexistent"`; result has `matches=0` | Returns 0; no error raised |
| WeaviateBackend delegates with explicit collection | `backend.ensure_visual_collection(client, collection="CustomCollection")` | Forwards to store function with `collection="CustomCollection"` |
| WeaviateBackend defaults collection name | `backend.add_visual_documents(client, documents)` with `collection=None` | Resolves to `"RAGVisualPages"` before forwarding; store function called with `collection="RAGVisualPages"` |
| All 11 properties present on inserted object (FR-503) | Single doc dict containing document_id, page_number, source_key, source_uri, source_name, tenant_id, total_pages, page_width_px, page_height_px, minio_key, patch_vectors, mean_vector | `batch.add_object` properties dict contains all 10 scalar keys (mean_vector excluded); none missing |
| `patch_vectors` is stored as JSON-serializable TEXT (FR-505) | `patch_vectors` is a list of 8 lists each with 128 floats | Property passed through as-is to Weaviate (no coercion); can be deserialized back to `list[list[float]]` |
| Visual and text collections independent (FR-501) | Both collections queried after visual insert | Each collection returns only its own objects; cross-collection contamination absent |
| ABC contract: all three methods abstract | Subclass omitting any one of the three new methods | Instantiation raises `TypeError` at class definition time |
| NFR-909: existing VectorBackend methods unchanged | Inspect VectorBackend method signatures before and after patch | All pre-existing method signatures identical; no existing method removed or renamed |

---

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| Weaviate connection error on `ensure_visual_collection` | `client.collections.exists` raises `WeaviateConnectionError` | Exception propagates to caller unwrapped; no suppression or re-wrapping |
| Weaviate connection error on `add_visual_documents` | `client.collections.get` raises `WeaviateConnectionError` | Exception propagates to caller unwrapped |
| Weaviate query error on `delete_visual_by_source_key` | `col.data.delete_many` raises `WeaviateQueryError` | Exception propagates to caller unwrapped |
| All documents fail batch insert | `col.batch.failed_objects` has same length as input (all fail) | Returns 0 (not negative); no exception raised |
| `DeleteManyResult` missing `matches` attribute | `delete_visual_by_source_key` result object has no `matches` attribute | Returns 0 via `getattr(result, "matches", 0) or 0` fallback; no AttributeError raised |
| `DeleteManyResult.matches` is None or 0 | result.matches is None | Returns 0; `or 0` guard handles falsy value |
| Weaviate error on `add_visual_documents` during batch context | Exception raised inside `col.batch.dynamic()` context manager body | Exception propagates to caller; no count returned |
| WeaviateBackend delegation error: connection error | `backend.delete_visual_by_source_key(client, "key")` and client raises | Exception propagates through delegation unchanged; no extra wrapping at backend layer |

---

#### Boundary conditions

- **Empty documents list** (`add_visual_documents`): must return 0 without calling `client.collections.get` — guard must be before any client interaction (FR-507).
- **Exactly 1 document**: batch path exercised for single-element list; not short-circuited.
- **`mean_vector` exactly 128 dimensions**: collection schema specifies 128 dims; inserting a 127- or 129-dim vector is a caller error, but the store must not silently truncate or pad — it passes through as-is and lets Weaviate reject it (not a store concern to validate).
- **`patch_vectors` inner list count**: each inner list must have exactly 128 elements per FR-505; store passes value through without validation — boundary is a caller/ingestion concern, but downstream deserialization test should verify round-trip integrity.
- **`collection` parameter is empty string `""`**: WeaviateBackend must treat `""` as falsy and substitute `"RAGVisualPages"` (since `collection or default` resolves `""` to default).
- **`collection` parameter is explicitly `"RAGVisualPages"`**: behaves identically to `None` after default resolution.
- **`failed_objects` attribute absent on batch result**: fallback to 0 must be safe (guard via `getattr` or equivalent).
- **`delete_visual_by_source_key` with `source_key=""` (empty string)**: filter applied with empty string; store does not guard against this — behavior is Weaviate-defined, but function must not raise before the Weaviate call.
- **NFR-909 boundary**: adding three new abstract methods must not change argument count, name, or default values of any pre-existing VectorBackend abstract method.

---

#### Integration points

- **Callers of `ensure_visual_collection`**: visual ingestion pipeline (embedding workflow) calls this before inserting visual page objects; passes in live Weaviate client handle.
- **Callers of `add_visual_documents`**: embedding pipeline's visual-store node passes a list of dicts built from VLM enrichment output; expected key set is `{mean_vector, document_id, source_key, source_uri, source_name, tenant_id, page_number, total_pages, page_width_px, page_height_px, minio_key, patch_vectors}`.
- **Callers of `delete_visual_by_source_key`**: clean-store / document deletion flow calls this when a document is removed; source_key is the canonical document identifier shared with MinIO.
- **WeaviateBackend**: implements the three new abstract methods; callers interact with `VectorBackend` interface only — store functions are internal to the weaviate subpackage.
- **Return values consumed by callers**:
  - `ensure_visual_collection` → None (fire-and-forget)
  - `add_visual_documents` → int inserted count (used for telemetry/logging)
  - `delete_visual_by_source_key` → int match count (used for telemetry/logging; 0 is ambiguous but acceptable per error-behavior spec)

---

#### Known test gaps

- **Schema validation on existing collection** (FR-502 / FR-504): the function returns without error if the collection exists with wrong dimensions or missing properties. There is no test that can verify incorrect-schema detection because the module intentionally does not detect it. Tests can only assert the function does not raise — they cannot assert correctness of an existing schema.
- **`patch_vectors` round-trip fidelity** (FR-505): the store passes `patch_vectors` through as-is without serialization. A full round-trip test (insert → retrieve → deserialize) requires a live or realistic Weaviate mock that stores and returns properties. Unit tests with simple mocks cannot cover this path end-to-end.
- **Weaviate batch partial-failure internals**: `col.batch.failed_objects` behavior depends on the Weaviate Python client's batch implementation. Tests must mock this attribute carefully; incorrect mock behavior could produce false positives.
- **True isolation of visual vs. text collection** (FR-501): confirming that a visual insert does not affect the text collection requires either a full integration test or a mock that asserts no cross-collection calls occur. Unit-level mocks can assert the correct collection name is used, but cannot confirm actual Weaviate isolation.
- **`DeleteManyResult` ambiguity**: the spec documents that 0 returned cannot distinguish "nothing deleted" from "count unavailable." There is no test that can distinguish these two cases at the store level — acceptance tests for FR-506 must rely on a subsequent query confirming object absence rather than on the return value alone.

---

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.
