# Vector Store Subsystem — Test Documentation

| Field | Value |
|-------|-------|
| **Document type** | Test plan and coverage map |
| **Status** | Draft |
| **Version** | v1.0.0 |
| **Last updated** | 2026-04-10 |
| **Companion documents** | `VECTOR_DB_SPEC.md`, `VECTOR_DB_ENGINEERING_GUIDE.md` |

---

## 1) Test Inventory

### Currently shipped

| Test file | Test | Type | Covers |
|-----------|------|------|--------|
| `tests/test_vector_store_integration.py` | `test_chunk_id_is_deterministic` | Unit | REQ-VDB-301, REQ-VDB-1100 |

### Planned

| Test file | Test | Type | Covers |
|-----------|------|------|--------|
| `tests/vector_db/test_filter_translation.py` | `test_each_operator_translates`, `test_unknown_operator_raises`, `test_multi_clause_and_combined` | Unit | REQ-VDB-800, REQ-VDB-801, REQ-VDB-1102 |
| `tests/vector_db/test_multi_search.py` | `test_dedup_keeps_higher_score`, `test_per_collection_failure_skipped`, `test_empty_collections_falls_back` | Unit | REQ-VDB-402, REQ-VDB-1103 |
| `tests/vector_db/test_dispatcher.py` | `test_unknown_backend_raises`, `test_lazy_singleton_caches`, `test_default_collection_resolution` | Unit | REQ-VDB-100, REQ-VDB-101, REQ-VDB-102 |
| `tests/vector_db/test_lazy_imports.py` | `test_import_without_engine_dependency` | Subprocess | REQ-VDB-1001 |
| `tests/vector_db/test_chunk_store_integration.py` | round-trip insert + search; aggregate; delete by source/source_key (with legacy fallback); list collections | Integration | REQ-VDB-300, REQ-VDB-302, REQ-VDB-303, REQ-VDB-304, REQ-VDB-400, REQ-VDB-401, REQ-VDB-600, REQ-VDB-601, REQ-VDB-602, REQ-VDB-700, REQ-VDB-701 |
| `tests/vector_db/test_visual_store_integration.py` | round-trip insert + search; threshold filter; tenant filter; patch_vectors exclusion; delete by source_key | Integration | REQ-VDB-500, REQ-VDB-501, REQ-VDB-502, REQ-VDB-503, REQ-VDB-504, REQ-VDB-1104 |
| `tests/vector_db/test_abc_contract.py` | parameterised over every concrete backend | Contract | REQ-VDB-200, REQ-VDB-202, REQ-VDB-1101 (mandatory once a 2nd backend ships) |

---

## 2) Coverage Matrix (Spec → Test)

| Requirement | Test | Status |
|-------------|------|--------|
| REQ-VDB-100 (public API surface) | `test_dispatcher.py::test_unknown_backend_raises` (negative); grep check (positive) | Planned |
| REQ-VDB-101 (lazy singleton) | `test_dispatcher.py::test_lazy_singleton_caches` | Planned |
| REQ-VDB-102 (default collection) | `test_dispatcher.py::test_default_collection_resolution` | Planned |
| REQ-VDB-103 (new backend additivity) | manual review of `_get_vector_backend` | N/A |
| REQ-VDB-200 (ABC) | `test_abc_contract.py` | Planned |
| REQ-VDB-201 (no embedding gen) | grep check (`no embedding model imports in src/vector_db/`) | Manual |
| REQ-VDB-202 (collection param everywhere) | `test_abc_contract.py` | Planned |
| REQ-VDB-203 (two client modes) | `test_chunk_store_integration.py` | Planned |
| REQ-VDB-300 (add_documents) | `test_chunk_store_integration.py::test_add_and_search` | Planned |
| REQ-VDB-301 (deterministic IDs) | `test_chunk_id_is_deterministic` | **Shipped** |
| REQ-VDB-302 (chunk_id override) | `test_chunk_store_integration.py::test_chunk_id_override` | Planned |
| REQ-VDB-303 (delete by source) | `test_chunk_store_integration.py::test_delete_by_source` | Planned |
| REQ-VDB-304 (delete by source_key + legacy) | `test_chunk_store_integration.py::test_delete_by_source_key_legacy_fallback` | Planned |
| REQ-VDB-400 (hybrid search) | `test_chunk_store_integration.py::test_hybrid_alpha` | Planned |
| REQ-VDB-401 (filters) | `test_filter_translation.py` + integration smoke | Planned |
| REQ-VDB-402 (multi_search) | `test_multi_search.py` | Planned |
| REQ-VDB-500–504 (visual collection) | `test_visual_store_integration.py` | Planned |
| REQ-VDB-600 (aggregate) | `test_chunk_store_integration.py::test_aggregate_by_source` | Planned |
| REQ-VDB-601 (stats) | `test_chunk_store_integration.py::test_stats_returns_none_for_missing` | Planned |
| REQ-VDB-602 (list_collections) | `test_chunk_store_integration.py::test_list_collections` | Planned |
| REQ-VDB-700 (idempotent ensure) | `test_chunk_store_integration.py::test_ensure_idempotent` | Planned |
| REQ-VDB-701 (delete_collection no-op) | `test_chunk_store_integration.py::test_delete_missing_noop` | Planned |
| REQ-VDB-702 (close_client safe) | `test_chunk_store_integration.py::test_close_idempotent` | Planned |
| REQ-VDB-800 (operator coverage) | `test_filter_translation.py::test_each_operator_translates` | Planned |
| REQ-VDB-801 (multi-clause AND) | `test_filter_translation.py::test_multi_clause_and_combined` | Planned |
| REQ-VDB-900–903 (schemas) | static type check + import test | Planned |
| REQ-VDB-950 (tracing) | spy on `tracer.start_span` in unit tests | Planned |
| REQ-VDB-1000 (config-only swap) | manual review (no consumer edits required to switch) | Manual |
| REQ-VDB-1001 (lazy imports) | `test_lazy_imports.py` | Planned |
| REQ-VDB-1002 (multi_search parallelism) | `test_multi_search.py::test_runs_in_parallel` (timing assertion) | Planned |
| REQ-VDB-1003 (no full scans) | code review check on aggregation helpers | Manual |
| REQ-VDB-1004 (re-ingestion idempotency) | `test_chunk_store_integration.py::test_reingest_idempotent` | Planned |

---

## 3) Fixtures

### `embedded_weaviate_client` (session-scoped)

Boots an embedded Weaviate instance under a per-session temp directory, yields the client, and tears it down on session exit. Used by every integration test.

```python
@pytest.fixture(scope="session")
def embedded_weaviate_client(tmp_path_factory):
    import os
    os.environ["RAG_WEAVIATE_DATA_DIR"] = str(tmp_path_factory.mktemp("weaviate"))
    from src.vector_db import create_persistent_client, close_client
    client = create_persistent_client()
    try:
        yield client
    finally:
        close_client(client)
```

### `clean_collection` (function-scoped)

Drops and recreates the default collection before each test so state is isolated.

### `fake_backend` (function-scoped)

A `VectorBackend` subclass with stub methods that return canned data, used for unit tests of `multi_search` and the public API dispatcher without booting a real engine.

### `populated_chunk_collection` (function-scoped)

Inserts a small fixture document set (3 sources, varying connectors, varying tenants) for aggregation, stats, and filter tests.

### `populated_visual_collection` (function-scoped)

Inserts visual page records for two `tenant_id` values across two `source_key` values for tenant-filter and threshold tests.

---

## 4) Critical Test Scenarios

The following scenarios MUST pass before any vector_db change is merged. They represent the contract that consumers depend on.

### S1. Round-trip insert + search

Insert a `DocumentRecord` with known text, embedding, and metadata. Search with a query embedding aligned to the document. Assert the document is returned with all metadata fields preserved.

### S2. Re-ingestion idempotency

Insert the same 3-chunk document twice. Assert the collection contains exactly 3 objects (not 6) and that all 3 chunk IDs are unchanged between runs.

### S3. Caller-supplied chunk_id wins

Insert a record with `metadata.chunk_id = "<custom-uuid>"`. Assert the stored object's UUID equals that value, and that re-inserting with the same `chunk_id` does not duplicate.

### S4. Multi-search dedup with overlapping results

Two collections each return a result for the same `object_id` with different scores. Assert the merged list contains exactly one entry, with the higher score, and that the `collection` field reflects the higher-scoring source.

### S5. Multi-search survives a per-collection failure

Three collections; one raises during `search`. Assert: a warning is logged with the collection name, the function returns results from the surviving two collections, and no exception propagates.

### S6. Filter operator coverage

For each of `eq`, `ne`, `gt`, `lt`, `gte`, `lte`, `like`, build a `SearchFilter`, run a search, and assert results match the expected subset. For `like`, use a glob pattern with a wildcard.

### S7. Filter unknown operator

Construct `SearchFilter("p", "FOO", 1)`. Assert `ValueError` listing the seven valid operators is raised.

### S8. Filter multi-clause AND

Two filters: `tenant_id eq "acme"` and `connector eq "local_fs"`. Assert results match the AND, not the OR.

### S9. Delete by source_key with legacy fallback

Populate a collection with mixed pre/post-migration objects (some have `source_key`, some only have `source`). Call `delete_by_source_key("foo", legacy_source="bar")`. Assert both sets are deleted across the two attempts.

### S10. Aggregate native group-by

Populate a collection with 3 sources × varying chunk counts. Call `aggregate_by_source`. Assert: result count equals distinct `source_key` count, each entry's `chunk_count` matches, and the test runs in O(distinct sources) not O(total objects).

### S11. Stats on missing collection

Call `get_collection_stats(client, "nonexistent")`. Assert `None` is returned (not an exception).

### S12. Visual search threshold and tenant filter

Insert visual records for two tenants. Search with `score_threshold=0.5` and `tenant_id="X"`. Assert: every returned object has `tenant_id == "X"`, every returned `score >= 0.5`, no result dict contains `patch_vectors`.

### S13. Lazy import (REQ-VDB-1001)

Spawn a subprocess in an environment where the engine client library is uninstalled (simulated by sys.modules patch). Import `src.vector_db`. Assert no `ImportError` until a public API function is called.

### S14. Idempotent close

Call `close_client(client)` twice on the same persistent client handle. Assert the second call does not raise.

### S15. Idempotent ensure

Call `ensure_collection(client, "Test")` three times. Assert exactly one create operation is performed against the engine.

---

## 5) Test Execution

```bash
# All vector_db tests
pytest tests/vector_db/ tests/test_vector_store_integration.py

# Just the unit tests (fast — no embedded engine)
pytest tests/vector_db/test_filter_translation.py \
       tests/vector_db/test_multi_search.py \
       tests/vector_db/test_dispatcher.py \
       tests/test_vector_store_integration.py

# Integration tests only
pytest tests/vector_db/test_chunk_store_integration.py \
       tests/vector_db/test_visual_store_integration.py
```

The lazy-import test runs in a subprocess and is excluded from normal collection — invoke explicitly:

```bash
pytest tests/vector_db/test_lazy_imports.py --run-subprocess-tests
```

---

## 6) Acceptance for the Test Plan

The test plan is satisfied when:

1. Every requirement in the coverage matrix has at least one test (or an explicit Manual marker with justification).
2. The shipped tests run green in CI on every PR touching `src/vector_db/`.
3. No integration test depends on a network-reachable engine — embedded mode only.
4. Adding a new backend triggers the contract test suite to run against both backends automatically.
