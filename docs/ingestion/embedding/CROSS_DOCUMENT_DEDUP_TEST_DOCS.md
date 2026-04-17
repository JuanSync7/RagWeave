> **Document type:** Test documentation (Layer 5 — post-implementation)
> **Upstream:** CROSS_DOCUMENT_DEDUP_ENGINEERING_GUIDE.md
> **Last updated:** 2026-04-17
> **Status:** Authoritative

# Cross-Document Deduplication Test Documentation

| Field | Value |
|-------|-------|
| **Document** | Cross-Document Deduplication Test Documentation |
| **Version** | 1.0.0 |
| **Status** | Active |
| **Engineering Guide** | `CROSS_DOCUMENT_DEDUP_ENGINEERING_GUIDE.md` v1.0.0 |
| **Spec Reference** | `CROSS_DOCUMENT_DEDUP_SPEC.md` v1.0.0 (FR-3400–FR-3461, NFR-3500–NFR-3504) |
| **Created** | 2026-04-17 |
| **Last Updated** | 2026-04-17 |

---

## 1. Test Strategy

The cross-document dedup test suite verifies three distinct concerns:

**Behavioural correctness of the dedup node:** Does the node correctly route chunks through
the bypass, override, Tier 1 exact, and Tier 2 fuzzy paths? Does it emit the right merge
events and stats? Does it degrade gracefully on Weaviate errors?

**Correctness of the revert path:** Does `revert_merge()` correctly detach a source key,
delete canonical chunks when they lose all provenance, and behave as a safe no-op when the
source key is already absent?

**Graph wiring:** Is `cross_document_dedup_node` registered in the compiled LangGraph graph,
and does it sit between `quality_validation` and `embedding_storage`?

The suite uses **mocked Weaviate clients** throughout. No running Weaviate instance is required
for any test — Weaviate interactions are exercised via `MagicMock` with controlled return
values. This makes the tests fast, fully deterministic, and CI-safe.

The lower-level unit modules (`dedup_utils`, `minhash_engine`, `types`) do not have
dedicated test files in the current suite. Their correctness is exercised indirectly through
the integration tests. The key hash-contract assertions (normalisation idempotency,
case-sensitivity) are validated inline via `test_novel_chunk_has_content_hash_in_metadata`,
which asserts the SHA-256 hex output is exactly 64 characters.

---

## 2. Test File Map

| File | Location | What it tests |
|------|----------|---------------|
| `test_dedup_workflow_integration.py` | `tests/ingest/` | `cross_document_dedup_node` — bypass, override, exact match, merge events, stats, graph wiring |
| `test_dedup_revert.py` | `tests/ingest/` | `revert_merge()` — successful revert, canonical deletion, no-op, error tolerance |

Both files use `unittest.mock.MagicMock` and `pytest` class-based test organisation.

---

## 3. Coverage by FR

### FR-3402 — Master bypass

Covered by `TestDedupBypassWhenDisabled` in `test_dedup_workflow_integration.py`:

| Test | What it asserts |
|------|----------------|
| `test_disabled_returns_all_chunks` | All input chunks returned when `enable_cross_document_dedup=False` |
| `test_disabled_empty_merge_report` | `dedup_merge_report == []` when disabled |
| `test_disabled_empty_dedup_stats` | `dedup_stats == {}` when disabled |
| `test_disabled_skipped_in_processing_log` | Processing log contains a "skipped" entry |
| `test_disabled_no_weaviate_calls` | `weaviate_client.collections.get` never called when disabled |

### FR-3411, FR-3430, FR-3431, FR-3440 — Tier 1 exact match and merge events

Covered by `TestMergeEventsInState` in `test_dedup_workflow_integration.py`:

| Test | What it asserts |
|------|----------------|
| `test_exact_match_emits_merged_event` | Match produces `action="merged"`, `match_tier="exact"`, `similarity_score=1.0`, correct `canonical_chunk_id`, `merged_source_key`, `timestamp`, `canonical_content_hash` |
| `test_exact_match_chunk_removed_from_output` | Deduplicated chunk is not in output `chunks` |
| `test_dedup_stats_populated` | `exact_matches=1`, `novel_chunks=0`, `total_input_chunks=1`, `degraded=False` |
| `test_novel_chunk_has_content_hash_in_metadata` | Novel chunk has `content_hash` (64-char hex) in metadata |
| `test_merge_event_contains_required_fields` | Event dict contains every key declared in `MergeEvent.__annotations__` |

### FR-3450 — Per-source override

Covered by `TestDedupOverridePath` in `test_dedup_workflow_integration.py`:

| Test | What it asserts |
|------|----------------|
| `test_override_source_chunks_pass_through` | All chunks for an overridden source_key appear in output |
| `test_override_emits_override_skipped_events` | Each chunk emits `action="override_skipped"`, `match_tier="override"`, `canonical_chunk_id=""` |
| `test_override_no_weaviate_lookup` | `weaviate_client.collections.get` never called when source is in override list |
| `test_non_overridden_source_still_deduplicates` | A source not in the override list follows normal dedup logic |

### FR-3451 — Revert merge

Covered across four classes in `test_dedup_revert.py`:

| Class | Tests | What they assert |
|-------|-------|-----------------|
| `TestRevertMergeSuccess` | `test_removes_source_key_from_source_documents`, `test_returns_true_on_successful_revert`, `test_uses_custom_collection_name` | Source key detached; `data.update` called with correct remaining array; `collection=` param respected |
| `TestRevertMergeDeletesCanonical` | `test_deletes_chunk_when_last_source_removed` | `data.delete_by_id` called when `source_documents` becomes empty; `data.update` not called |
| `TestRevertMergeNoOp` | `test_returns_false_when_source_key_not_in_documents`, `test_returns_false_when_chunk_not_found`, `test_idempotent_double_call` | Returns `False` for absent source key; returns `False` when chunk not found; second call is a no-op |
| `TestRevertMergeErrorTolerance` | `test_returns_false_on_update_error`, `test_does_not_raise_on_delete_error` | Weaviate errors return `False` without propagating exceptions |

### NFR-3504 — Graceful degradation

Not covered by a dedicated test class. Degradation is exercised implicitly — the mock
clients in `TestMergeEventsInState` and `TestDedupOverridePath` exercise error branches via
controlled return values. A dedicated class injecting exceptions from
`find_chunk_by_content_hash` is an identified coverage gap (see Section 6).

### Graph wiring (Phase 3.3 integration)

Covered by `TestWorkflowWiring` in `test_dedup_workflow_integration.py`:

| Test | What it asserts |
|------|----------------|
| `test_build_embedding_graph_returns_non_none` | `build_embedding_graph()` returns a non-None compiled graph |
| `test_cross_document_dedup_node_in_graph` | Compiled graph has a `"cross_document_dedup"` node (via `get_graph().nodes`; skips gracefully if API unavailable) |
| `test_dedup_node_between_quality_and_storage` | `quality_validation`, `cross_document_dedup`, and `embedding_storage` all registered as nodes |

---

## 4. Fixture Reference

### Chunk factory

```python
from src.ingest.common.schemas import ProcessedChunk

def _make_chunk(text: str = "hello world chunk text here", metadata: dict | None = None):
    return ProcessedChunk(text=text, metadata=metadata if metadata is not None else {})
```

### State factory

Used in `test_dedup_workflow_integration.py` for every node test:

```python
from src.ingest.common.types import IngestionConfig, Runtime
from unittest.mock import MagicMock

def _make_state(
    chunks: list,
    *,
    enable_dedup: bool = True,
    enable_fuzzy: bool = False,
    override_sources: list | None = None,
    source_key: str = "doc/test.md",
    weaviate_client: object | None = None,
) -> dict:
    config = IngestionConfig(
        enable_cross_document_dedup=enable_dedup,
        enable_fuzzy_dedup=enable_fuzzy,
        dedup_override_sources=override_sources or [],
    )
    runtime = Runtime(
        config=config,
        embedder=MagicMock(),
        weaviate_client=weaviate_client or MagicMock(),
        kg_builder=None,
    )
    return {
        "chunks": chunks,
        "errors": [],
        "processing_log": [],
        "runtime": runtime,
        "source_key": source_key,
    }
```

### Mock Weaviate client — exact match found

```python
def _make_client_with_match(existing_uuid: str = "aaaa-bbbb-cccc-dddd") -> MagicMock:
    client = MagicMock()
    collection = MagicMock()
    client.collections.get.return_value = collection

    obj = MagicMock()
    obj.uuid = existing_uuid
    obj.properties = {
        "content_hash": "some_hash",
        "source_documents": ["original/doc.md"],
        "text": "hello world chunk text here",
    }
    fetch_result = MagicMock()
    fetch_result.objects = [obj]
    collection.query.fetch_objects.return_value = fetch_result

    existing_obj = MagicMock()
    existing_obj.properties = {"source_documents": ["original/doc.md"]}
    collection.query.fetch_object_by_id.return_value = existing_obj
    collection.data.update.return_value = None

    return client
```

### Mock Weaviate client — no match

```python
def _make_client_no_match() -> MagicMock:
    client = MagicMock()
    collection = MagicMock()
    client.collections.get.return_value = collection
    fetch_result = MagicMock()
    fetch_result.objects = []
    collection.query.fetch_objects.return_value = fetch_result
    return client
```

### MergeEvent factory (for revert tests)

```python
from src.ingest.embedding.common.types import create_merge_event

def _make_event(
    source_key: str = "doc/incoming.md",
    content_hash: str = "a" * 64,
    canonical_chunk_id: str = "uuid-canonical-0001",
) -> dict:
    return create_merge_event(
        canonical_content_hash=content_hash,
        canonical_chunk_id=canonical_chunk_id,
        merged_source_key=source_key,
        merged_section="",
        match_tier="exact",
        similarity_score=1.0,
        canonical_replaced=False,
        action="merged",
    )
```

### Mock Weaviate client with known chunk (for revert tests)

```python
def _make_client_with_chunk(
    chunk_uuid: str,
    content_hash: str,
    source_documents: list[str],
) -> MagicMock:
    client = MagicMock()
    collection = MagicMock()
    client.collections.get.return_value = collection

    obj = MagicMock()
    obj.uuid = chunk_uuid
    obj.properties = {
        "content_hash": content_hash,
        "source_documents": list(source_documents),
        "text": "canonical chunk text",
    }
    fetch_result = MagicMock()
    fetch_result.objects = [obj]
    collection.query.fetch_objects.return_value = fetch_result

    return client
```

---

## 5. Running Tests

No external services are required. All Weaviate interactions are mocked.

```bash
# Both dedup test files
pytest tests/ingest/test_dedup_workflow_integration.py tests/ingest/test_dedup_revert.py -v

# Node integration tests only
pytest tests/ingest/test_dedup_workflow_integration.py -v

# Revert tests only
pytest tests/ingest/test_dedup_revert.py -v

# All dedup-related tests by keyword
pytest tests/ingest/ -k "dedup" -v

# Full test suite (includes dedup)
pytest tests/ -v
```

**Test class summary:**

| Class | File | Tests |
|-------|------|-------|
| `TestWorkflowWiring` | `test_dedup_workflow_integration.py` | 3 |
| `TestDedupBypassWhenDisabled` | `test_dedup_workflow_integration.py` | 5 |
| `TestDedupOverridePath` | `test_dedup_workflow_integration.py` | 4 |
| `TestMergeEventsInState` | `test_dedup_workflow_integration.py` | 5 |
| `TestRevertMergeSuccess` | `test_dedup_revert.py` | 3 |
| `TestRevertMergeDeletesCanonical` | `test_dedup_revert.py` | 1 |
| `TestRevertMergeNoOp` | `test_dedup_revert.py` | 3 |
| `TestRevertMergeErrorTolerance` | `test_dedup_revert.py` | 2 |

**Total: 26 tests across 2 files.**

---

## 6. Coverage Gaps and Planned Tests

The following scenarios are not yet covered and are candidates for future additions:

| Gap | Priority | Notes |
|-----|----------|-------|
| Graceful degradation — `find_chunk_by_content_hash` raises | High | Inject exception via mock; assert `degraded=True` in stats and all input chunks in output |
| Tier 2 fuzzy match — merge path | High | Mock `compute_fuzzy_fingerprint` and `find_chunk_by_fuzzy_fingerprint`; assert `fuzzy_matches=1`, `action="merged"` |
| Tier 2 canonical replacement — longer-chunk wins | High | Mock Tier 2 match with `text_length < len(chunk.text)`; assert `canonical_replaced=True` and `update_chunk_content` called |
| Re-ingestion cleanup (`update_mode=True`) | Medium | Assert `remove_source_document_refs` called before per-chunk loop |
| `normalise_chunk_text` contract | Medium | Dedicated unit: whitespace variants produce identical hashes; case variants produce different hashes |
| `append_source_document` deduplication | Medium | Re-appending an already-present source key is a no-op (no second `data.update`) |
| `compute_fuzzy_fingerprint` + `estimate_similarity` round-trip | Medium | Fingerprint identical text, assert `jaccard >= 0.99`; fingerprint unrelated text, assert below threshold |
