> **⚠ DRAFT — PRE-IMPLEMENTATION TEST PLAN**
>
> This test plan was authored **before** source code existed. Test **strategy, scope, coverage, and requirement traceability** are appropriately pre-impl and will survive as-is. However, **specific module paths, fixture names, helper function signatures, and import statements** in integration test sections reference code that has not yet been written and may drift during implementation.
>
> To be **reconciled post-implementation** using `/write-test-docs` (which requires the post-impl engineering guide as input — transitively protected by the non-skippable existence check in `/write-engineering-guide`). Integration test module paths and fixtures will be refreshed against real code at that time.

---

> **Document type:** Test documentation (Layer 6)
> **Upstream:** CROSS_DOCUMENT_DEDUP_ENGINEERING_GUIDE.md
> **Last updated:** 2026-04-15
> **Status:** DRAFT (pre-implementation)

# Cross-Document Deduplication — Test Documentation (v1.0.0-draft)

## 1. Test Strategy Overview

### 1.1 Scope

This document defines the test plan for the Cross-Document Deduplication subsystem, which eliminates duplicate chunks across documents using a two-tier architecture (exact content hash + optional MinHash fuzzy matching). The test surface covers:

1. Content hash: normalisation, SHA-256 computation, exact match detection
2. MinHash: fingerprint computation, similarity threshold, longer-chunk-wins canonical selection
3. Back-references: `source_documents` array initialisation, append, merge detection, deduplication
4. Merge reporting: event schema, persistence, security constraint (no chunk text in events)
5. Revert: targeted revert, document-level override, re-ingestion with `--dedup-override`
6. Pipeline integration: DAG wiring, state flow, bypass when disabled, graceful degradation

### 1.2 Test Categories

| Category | Purpose | Infrastructure Required |
|----------|---------|------------------------|
| **Unit** | Verify hash computation, normalisation, MinHash engine, merge logic with mocked Weaviate | None |
| **Integration** | Verify full dedup flow against real Weaviate with test collections | Weaviate (`localhost:8080`) |
| **Contract** | Verify `MergeEvent` schema, `dedup_stats` structure, state extension invariants | None |
| **End-to-end** | Ingest multiple documents through the embedding pipeline and verify dedup outcomes | Weaviate (`localhost:8080`) |

### 1.3 Dependencies and Fixtures

**External services (integration/e2e only):**
- Weaviate at `localhost:8080` (override: `WEAVIATE_TEST_URL`)

**Shared fixtures:**
- `CHUNK_ASIC_ORIGINAL` — `"ASIC design requires careful clock domain crossing analysis."`
- `CHUNK_ASIC_DUPLICATE` — identical text to `CHUNK_ASIC_ORIGINAL`
- `CHUNK_ASIC_NEAR_DUP` — `"ASIC design requires careful clock-domain crossing analysis and verification."`
- `CHUNK_ASIC_UNRELATED` — `"FPGA prototyping enables rapid hardware validation."`
- `CHUNK_WHITESPACE_VARIANT` — `"  ASIC  design requires   careful clock domain crossing analysis.  \n"`
- `EXPECTED_HASH` — SHA-256 of normalised `CHUNK_ASIC_ORIGINAL`
- `make_mock_client(stored_chunks)` — factory for mock Weaviate client pre-loaded with stored chunks
- `weaviate_test_collection` — fixture creating a fresh Weaviate collection with dedup schema properties per test

---

## 2. Unit Tests

### 2.1 Module: `src/ingest/embedding/common/dedup_utils.py`

**Test file:** `tests/ingest/embedding/test_content_hash.py`

**Test class:** `TestNormalisation`

| Test Method | Assertions | Mocks | FR |
|-------------|-----------|-------|-----|
| `test_normalise_strips_leading_trailing_whitespace` | `"  Hello  "` normalises to `"Hello"`. | None | FR-3410 |
| `test_normalise_collapses_internal_whitespace` | `"Hello   World"` normalises to `"Hello World"`. | None | FR-3410 |
| `test_normalise_collapses_newlines_and_tabs` | `"Hello\n\tWorld"` normalises to `"Hello World"`. | None | FR-3410 |
| `test_normalise_preserves_case` | `"Hello World"` stays `"Hello World"` (not lowered). | None | FR-3410 |
| `test_whitespace_variant_matches_original` | `CHUNK_WHITESPACE_VARIANT` normalises to same text as `CHUNK_ASIC_ORIGINAL`. | None | FR-3410 |

**Test class:** `TestContentHash`

| Test Method | Assertions | Mocks | FR |
|-------------|-----------|-------|-----|
| `test_hash_is_sha256_hex` | `compute_content_hash(text)` returns a 64-character lowercase hex string. | None | FR-3410 |
| `test_identical_text_produces_identical_hash` | `compute_content_hash(CHUNK_ASIC_ORIGINAL) == compute_content_hash(CHUNK_ASIC_DUPLICATE)`. | None | FR-3410 |
| `test_whitespace_variant_produces_identical_hash` | `compute_content_hash(CHUNK_WHITESPACE_VARIANT) == EXPECTED_HASH`. | None | FR-3410 |
| `test_different_text_produces_different_hash` | `compute_content_hash(CHUNK_ASIC_ORIGINAL) != compute_content_hash(CHUNK_ASIC_UNRELATED)`. | None | FR-3410 |
| `test_case_sensitive_hashing` | `compute_content_hash("Hello World") != compute_content_hash("hello world")`. | None | FR-3410 |
| `test_empty_string_hash` | `compute_content_hash("")` returns a valid 64-char hex (hash of empty after normalisation). | None | FR-3410 |

**Test class:** `TestSourceDocumentsAppend`

| Test Method | Assertions | Mocks | FR |
|-------------|-----------|-------|-----|
| `test_append_adds_source_key` | `append_source_document(client, chunk_id, "doc_b")` adds `"doc_b"` to `source_documents`. | Mock client | FR-3431 |
| `test_append_does_not_duplicate` | Appending `"doc_a"` to `source_documents: ["doc_a"]` leaves array as `["doc_a"]`. | Mock client | FR-3431 |
| `test_remove_source_document_refs_cleans_array` | `remove_source_document_refs(client, "doc_b")` removes `"doc_b"` from all chunks' arrays. | Mock client | FR-3433 |
| `test_remove_source_document_refs_deletes_orphaned_chunk` | Chunk with `source_documents: ["doc_b"]` only is deleted after removing `"doc_b"`. | Mock client | FR-3433 |

### 2.2 Module: `src/ingest/embedding/support/minhash_engine.py`

**Test file:** `tests/ingest/embedding/test_minhash_engine.py`

**Test class:** `TestMinHashEngine`

| Test Method | Assertions | Mocks | FR |
|-------------|-----------|-------|-----|
| `test_fingerprint_is_hex_string` | `compute_minhash_fingerprint(text)` returns a non-empty hex string. | None | FR-3421 |
| `test_identical_text_produces_identical_fingerprint` | Same normalised text always produces same fingerprint. | None | FR-3421 |
| `test_similar_text_above_threshold` | `CHUNK_ASIC_ORIGINAL` and `CHUNK_ASIC_NEAR_DUP` have Jaccard similarity >= 0.95 (default threshold). | None | FR-3423 |
| `test_dissimilar_text_below_threshold` | `CHUNK_ASIC_ORIGINAL` and `CHUNK_ASIC_UNRELATED` have Jaccard similarity < 0.95. | None | FR-3422 |
| `test_threshold_boundary_exact` | Two chunks engineered to have similarity exactly at 0.95. Verify merge occurs at >= threshold and not at < threshold. | None | FR-3422, FR-3423 |
| `test_shingle_size_affects_similarity` | With `shingle_size=2` vs `shingle_size=5`, similarity estimates differ for the same pair. | None | FR-3421 |
| `test_num_hashes_affects_precision` | With `num_hashes=32` vs `num_hashes=256`, estimates converge toward same value but 256 is more stable. | None | FR-3421 |

**Test class:** `TestCanonicalSelection`

| Test Method | Assertions | Mocks | FR |
|-------------|-----------|-------|-----|
| `test_longer_chunk_wins` | Incoming chunk (72 chars) vs stored chunk (60 chars). Incoming wins: canonical text, hash, and fingerprint updated in Weaviate. | Mock client | FR-3424 |
| `test_shorter_chunk_does_not_replace` | Incoming chunk (50 chars) vs stored chunk (60 chars). Stored wins: only `source_documents` updated, no text/hash/fingerprint change. | Mock client | FR-3424 |
| `test_equal_length_preserves_canonical` | Incoming chunk same length as stored. Stored canonical preserved (tie goes to existing). | Mock client | FR-3424 |

### 2.3 Module: `src/ingest/embedding/nodes/cross_document_dedup.py`

**Test file:** `tests/ingest/embedding/test_cross_document_dedup.py`

**Test class:** `TestDedupNodeBypass`

| Test Method | Assertions | Mocks | FR |
|-------------|-----------|-------|-----|
| `test_bypass_when_disabled` | `enable_cross_document_dedup=False`. All chunks pass through unchanged. No Weaviate queries made. | Mock client | FR-3402 |
| `test_bypass_with_dedup_override` | `dedup_override=True`. All chunks pass through with `content_hash` attached but no Weaviate lookups. | Mock client | FR-3450 |

**Test class:** `TestDedupNodeTier1`

| Test Method | Assertions | Mocks | FR |
|-------------|-----------|-------|-----|
| `test_exact_match_removes_duplicate_chunk` | Incoming chunk text matches stored chunk. Incoming chunk removed from output list. | Mock client with stored chunk | FR-3411 |
| `test_exact_match_appends_source_document` | After exact match, canonical chunk's `source_documents` includes both source keys. | Mock client | FR-3431 |
| `test_novel_chunk_passes_through_with_hash` | No match found. Chunk passes through with `content_hash` and `source_documents` in metadata. | Mock client (empty) | FR-3412, FR-3430 |
| `test_novel_chunk_source_documents_initialised` | Novel chunk has `source_documents: ["<source_key>"]` (single-element array). | Mock client (empty) | FR-3430 |

**Test class:** `TestDedupNodeTier2`

| Test Method | Assertions | Mocks | FR |
|-------------|-----------|-------|-----|
| `test_fuzzy_match_above_threshold_merges` | No Tier 1 match. Tier 2 finds similarity 0.97. Chunk merged. | Mock client with fingerprints | FR-3423 |
| `test_fuzzy_match_below_threshold_passes_through` | No Tier 1 match. Tier 2 finds similarity 0.93 (below 0.95). Chunk passes as novel. | Mock client with fingerprints | FR-3422 |
| `test_fuzzy_disabled_skips_tier2` | `enable_fuzzy_dedup=False`. No MinHash computation or fingerprint queries. | Mock client | FR-3420 |
| `test_fuzzy_match_longer_chunk_replaces_canonical` | Incoming chunk is longer. Canonical chunk's text, hash, and fingerprint are updated in Weaviate. `canonical_replaced=True` in merge event. | Mock client | FR-3424 |

**Test class:** `TestDedupNodeGracefulDegradation`

| Test Method | Assertions | Mocks | FR |
|-------------|-----------|-------|-----|
| `test_weaviate_error_passes_all_chunks_through` | Mock client raises `ConnectionError`. All chunks pass through. `dedup_stats["degraded"] = True`. | Mock client that raises | NFR-3504 |
| `test_degraded_flag_in_stats` | After Weaviate error, `dedup_stats` contains `degraded: True` and correct `total_input_chunks`. | Mock client that raises | NFR-3504 |
| `test_processing_log_records_degraded` | `processing_log` contains `"cross_document_dedup:degraded"`. | Mock client that raises | NFR-3504 |

**Test class:** `TestDedupNodeStats`

| Test Method | Assertions | Mocks | FR |
|-------------|-----------|-------|-----|
| `test_stats_counts_are_correct` | After processing 10 chunks (3 exact, 2 fuzzy, 5 novel): `exact_matches=3`, `fuzzy_matches=2`, `novel_chunks=5`, `total_input_chunks=10`. | Mock client | FR-3403 |
| `test_stats_sum_equals_total` | `exact_matches + fuzzy_matches + novel_chunks == total_input_chunks`. | Mock client | FR-3403 |

**Test class:** `TestMergeReport`

| Test Method | Assertions | Mocks | FR |
|-------------|-----------|-------|-----|
| `test_merge_event_has_required_fields` | Each `MergeEvent` has `canonical_content_hash`, `canonical_chunk_id`, `merged_source_key`, `merged_section`, `match_tier`, `similarity_score`, `canonical_replaced`, `timestamp`. | None | FR-3440 |
| `test_merge_event_contains_no_chunk_text` | No field in `MergeEvent` contains the full chunk text content. | None | FR-3440, SC-3510 |
| `test_exact_match_event_has_similarity_1` | Tier 1 merge event has `match_tier="exact"` and `similarity_score=1.0`. | Mock client | FR-3440 |
| `test_fuzzy_match_event_has_correct_tier` | Tier 2 merge event has `match_tier="fuzzy"` and `similarity_score` between 0.0 and 1.0. | Mock client | FR-3440 |
| `test_merge_report_is_list_of_events` | `dedup_merge_report` in state is a list. Each element is a dict conforming to `MergeEvent`. | None | FR-3403, FR-3440 |
| `test_merge_report_persisted_in_state` | After node execution, `dedup_merge_report` is present in the returned partial state update. | Mock client | FR-3441 |

### 2.4 Module: Revert Operations

**Test file:** `tests/ingest/embedding/test_dedup_revert.py`

**Test class:** `TestRevertMerge`

| Test Method | Assertions | Mocks | FR |
|-------------|-----------|-------|-----|
| `test_targeted_revert_removes_source_from_array` | `revert_merge(client, "doc_b", hash)` removes `"doc_b"` from canonical's `source_documents`. | Mock client | FR-3451 |
| `test_targeted_revert_is_idempotent` | Calling `revert_merge` twice with same args. Second call returns `reverted=True` (safe no-op). | Mock client | FR-3451 |
| `test_targeted_revert_preserves_other_sources` | Canonical has `source_documents: ["doc_a", "doc_b", "doc_c"]`. Revert `"doc_b"`. Array becomes `["doc_a", "doc_c"]`. | Mock client | FR-3451 |
| `test_document_level_override_cleans_all_refs` | Re-ingest with `dedup_override=True`. All existing back-references for this source are removed before independent storage. | Mock client | FR-3452 |
| `test_override_stores_chunks_independently` | After re-ingest with override, all chunks have `source_documents: ["<source_key>"]` only. | Mock client | FR-3450, FR-3452 |
| `test_override_still_computes_content_hash` | With `dedup_override=True`, chunks still have `content_hash` in metadata. | Mock client | FR-3450 |

---

## 3. Integration Tests

### 3.1 Cross-Document Dedup End-to-End

**Test file:** `tests/ingest/embedding/test_dedup_integration.py`

**Setup:** Weaviate test collection with dedup schema properties. Fresh collection per test.

| Test Method | Steps | Verification |
|-------------|-------|-------------|
| `test_exact_match_merge_e2e` | 1. Ingest doc_a (3 chunks, all novel). 2. Ingest doc_b (3 chunks: 1 duplicate of doc_a, 2 novel). | `result_b.dedup_stats["exact_matches"] == 1`. Canonical chunk has `source_documents: ["doc_a", "doc_b"]`. `len(result_b.dedup_merge_report) == 1`. |
| `test_fuzzy_match_merge_e2e` | 1. Ingest doc_a with `CHUNK_ASIC_ORIGINAL`. 2. Ingest doc_c with `CHUNK_ASIC_NEAR_DUP` (similarity ~0.97). | `result_c.dedup_stats["fuzzy_matches"] == 1`. Canonical chunk updated if incoming is longer. `source_documents` includes both. |
| `test_re_ingestion_cleanup_e2e` | 1. Ingest doc_a (creates back-refs). 2. Re-ingest doc_a (modified content). | Old back-refs removed before new dedup runs. Final state consistent with new content. |
| `test_novel_chunks_stored_with_metadata_e2e` | 1. Ingest doc_a (all unique content). | All chunks stored with `content_hash` and `source_documents: ["doc_a"]`. `dedup_stats["novel_chunks"] == total`. |
| `test_dedup_override_e2e` | 1. Ingest doc_a. 2. Ingest doc_b with `dedup_override=True` (has overlapping content). | doc_b chunks stored independently despite overlap. `content_hash` still present. |

**Teardown:** Delete test collection.

### 3.2 DAG Wiring Verification

**Test file:** `tests/ingest/embedding/test_dedup_dag.py`

| Test Method | Steps | Verification |
|-------------|-------|-------------|
| `test_dedup_node_positioned_after_quality_validation` | 1. Build embedding pipeline DAG. 2. Inspect edge list. | `quality_validation -> cross_document_dedup` edge exists. |
| `test_dedup_node_positioned_before_embedding_storage` | 1. Build embedding pipeline DAG. 2. Inspect edge list. | `cross_document_dedup -> embedding_storage` edge exists. |
| `test_state_flows_dedup_fields_downstream` | 1. Run pipeline with dedup enabled. 2. Check `embedding_storage` node input. | `dedup_merge_report` and `dedup_stats` available to downstream node. |

---

## 4. Contract Tests

### 4.1 Interface Contracts

**Test file:** `tests/ingest/embedding/test_dedup_contracts.py`

| Test Method | What It Validates | FR |
|-------------|-------------------|-----|
| `test_merge_event_schema_has_all_fields` | `MergeEvent` TypedDict has `canonical_content_hash`, `canonical_chunk_id`, `merged_source_key`, `merged_section`, `match_tier`, `similarity_score`, `canonical_replaced`, `timestamp`. | FR-3440 |
| `test_merge_event_is_json_serialisable` | `json.dumps(create_merge_event(...))` succeeds. | FR-3440 |
| `test_dedup_stats_has_required_keys` | `dedup_stats` dict has `total_input_chunks`, `exact_matches`, `fuzzy_matches`, `novel_chunks`, `degraded`. | FR-3403 |
| `test_state_extension_includes_dedup_fields` | `EmbeddingPipelineState` TypedDict includes `dedup_merge_report` and `dedup_stats`. | FR-3403 |
| `test_content_hash_property_type_is_text` | Weaviate schema for chunk collection has `content_hash` as `TEXT` with `filterable: true`. | FR-3410 |
| `test_source_documents_property_type_is_text_array` | Weaviate schema has `source_documents` as `TEXT_ARRAY`. | FR-3430 |

### 4.2 State Invariants

| Test Method | What It Validates | FR |
|-------------|-------------------|-----|
| `test_stats_sum_invariant` | `exact_matches + fuzzy_matches + novel_chunks == total_input_chunks` for any dedup run. | FR-3403 |
| `test_novel_chunk_has_single_element_source_documents` | Every novel chunk has `source_documents` with exactly one element. | FR-3430 |
| `test_merge_event_match_tier_is_exact_or_fuzzy` | `match_tier` field is always `"exact"` or `"fuzzy"`. | FR-3440 |
| `test_merge_event_similarity_score_range` | `similarity_score` is between 0.0 and 1.0 inclusive. Exact matches always 1.0. | FR-3440 |
| `test_merge_event_timestamp_is_iso8601` | `timestamp` field parses as a valid ISO 8601 datetime. | FR-3440 |
| `test_content_hash_is_64_char_hex` | Every `content_hash` value is a 64-character lowercase hex string. | FR-3410 |

---

## 5. Requirement Traceability

| FR | Description | Test Method | Test File |
|----|-------------|-------------|-----------|
| FR-3400 | Dedup node position in DAG | `test_dedup_node_positioned_after_quality_validation`, `test_dedup_node_positioned_before_embedding_storage` | `test_dedup_dag.py` |
| FR-3402 | Dedup node bypass | `test_bypass_when_disabled` | `test_cross_document_dedup.py` |
| FR-3403 | State extension for dedup results | `test_stats_counts_are_correct`, `test_stats_sum_equals_total`, `test_merge_report_is_list_of_events`, `test_dedup_stats_has_required_keys`, `test_state_extension_includes_dedup_fields` | `test_cross_document_dedup.py`, `test_dedup_contracts.py` |
| FR-3410 | Content hash computation | `test_hash_is_sha256_hex`, `test_identical_text_produces_identical_hash`, `test_whitespace_variant_produces_identical_hash`, `test_different_text_produces_different_hash`, `test_case_sensitive_hashing`, `test_empty_string_hash`, `test_normalise_*` (5 tests) | `test_content_hash.py` |
| FR-3411 | Content hash lookup | `test_exact_match_removes_duplicate_chunk`, `test_exact_match_merge_e2e` | `test_cross_document_dedup.py`, `test_dedup_integration.py` |
| FR-3412 | Content hash storage on novel chunks | `test_novel_chunk_passes_through_with_hash`, `test_novel_chunks_stored_with_metadata_e2e` | `test_cross_document_dedup.py`, `test_dedup_integration.py` |
| FR-3420 | Tier 2 enable flag | `test_fuzzy_disabled_skips_tier2` | `test_cross_document_dedup.py` |
| FR-3421 | MinHash fingerprint computation | `test_fingerprint_is_hex_string`, `test_identical_text_produces_identical_fingerprint`, `test_shingle_size_affects_similarity`, `test_num_hashes_affects_precision` | `test_minhash_engine.py` |
| FR-3422 | Fuzzy similarity threshold | `test_dissimilar_text_below_threshold`, `test_threshold_boundary_exact`, `test_fuzzy_match_below_threshold_passes_through` | `test_minhash_engine.py`, `test_cross_document_dedup.py` |
| FR-3423 | Fuzzy fingerprint lookup | `test_similar_text_above_threshold`, `test_fuzzy_match_above_threshold_merges`, `test_fuzzy_match_merge_e2e` | `test_minhash_engine.py`, `test_cross_document_dedup.py`, `test_dedup_integration.py` |
| FR-3424 | Canonical chunk selection | `test_longer_chunk_wins`, `test_shorter_chunk_does_not_replace`, `test_equal_length_preserves_canonical`, `test_fuzzy_match_longer_chunk_replaces_canonical` | `test_minhash_engine.py`, `test_cross_document_dedup.py` |
| FR-3430 | source_documents initialisation | `test_novel_chunk_source_documents_initialised`, `test_novel_chunk_has_single_element_source_documents` | `test_cross_document_dedup.py`, `test_dedup_contracts.py` |
| FR-3431 | source_documents append on merge | `test_exact_match_appends_source_document`, `test_append_adds_source_key`, `test_append_does_not_duplicate` | `test_cross_document_dedup.py`, `test_content_hash.py` |
| FR-3433 | source_documents consistency on re-ingestion | `test_remove_source_document_refs_cleans_array`, `test_remove_source_document_refs_deletes_orphaned_chunk`, `test_re_ingestion_cleanup_e2e` | `test_content_hash.py`, `test_dedup_integration.py` |
| FR-3440 | Merge event schema | `test_merge_event_has_required_fields`, `test_merge_event_contains_no_chunk_text`, `test_exact_match_event_has_similarity_1`, `test_fuzzy_match_event_has_correct_tier`, `test_merge_event_schema_has_all_fields`, `test_merge_event_is_json_serialisable` | `test_cross_document_dedup.py`, `test_dedup_contracts.py` |
| FR-3441 | Merge report persistence | `test_merge_report_persisted_in_state` | `test_cross_document_dedup.py` |
| FR-3450 | Per-source dedup override | `test_bypass_with_dedup_override`, `test_override_stores_chunks_independently`, `test_override_still_computes_content_hash`, `test_dedup_override_e2e` | `test_cross_document_dedup.py`, `test_dedup_revert.py`, `test_dedup_integration.py` |
| FR-3451 | Revert merge operation | `test_targeted_revert_removes_source_from_array`, `test_targeted_revert_is_idempotent`, `test_targeted_revert_preserves_other_sources` | `test_dedup_revert.py` |
| FR-3452 | Revert via re-ingestion | `test_document_level_override_cleans_all_refs` | `test_dedup_revert.py` |
| NFR-3504 | Graceful degradation on Weaviate errors | `test_weaviate_error_passes_all_chunks_through`, `test_degraded_flag_in_stats`, `test_processing_log_records_degraded` | `test_cross_document_dedup.py` |
| SC-3510 | No chunk text in merge events | `test_merge_event_contains_no_chunk_text` | `test_cross_document_dedup.py` |
