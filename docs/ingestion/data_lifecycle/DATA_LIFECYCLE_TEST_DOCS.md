> **⚠ DRAFT — PRE-IMPLEMENTATION TEST PLAN**
>
> This test plan was authored **before** source code existed. Test **strategy, scope, coverage, and requirement traceability** are appropriately pre-impl and will survive as-is. However, **specific module paths, fixture names, helper function signatures, and import statements** in integration test sections reference code that has not yet been written and may drift during implementation.
>
> To be **reconciled post-implementation** using `/write-test-docs` (which requires the post-impl engineering guide as input — transitively protected by the non-skippable existence check in `/write-engineering-guide`). Integration test module paths and fixtures will be refreshed against real code at that time.

---

> **Document type:** Test documentation (Layer 6)
> **Upstream:** DATA_LIFECYCLE_ENGINEERING_GUIDE.md
> **Last updated:** 2026-04-15
> **Status:** DRAFT (pre-implementation)

# Data Lifecycle — Test Documentation (v1.0.0-draft)

## 1. Test Strategy Overview

### 1.1 Scope

This document defines the test plan for the Data Lifecycle subsystem, which is a cross-cutting layer governing durable storage (MinIO clean store), trace propagation, garbage collection/sync, schema migration, manifest extension, and end-to-end validation across all four storage backends (Weaviate, MinIO, Neo4j, Manifest).

The test surface covers six functional areas:
1. MinIO clean store operations (write, read, delete, soft delete)
2. Manifest schema extension and backward compatibility
3. Trace ID generation and propagation through both pipeline phases
4. GC/Sync: orphan detection, four-store cleanup, soft delete, retention purge
5. Schema migration: strategy determination, idempotency, resumability
6. E2E validation: per-document store consistency checks

### 1.2 Test Categories

| Category | Purpose | Infrastructure Required |
|----------|---------|------------------------|
| **Unit** | Verify individual functions in isolation with mocked store clients | None |
| **Integration** | Verify multi-store operations against real Weaviate, MinIO, Neo4j | Docker Compose (`docker-compose.test.yaml`) |
| **Contract** | Verify manifest schema invariants, state TypedDict shapes, store interface contracts | None |
| **End-to-end** | Full `ingest_file()` through validation with all stores running | Docker Compose + source fixtures |

### 1.3 Dependencies and Fixtures

**External services (integration/e2e only):**
- Weaviate at `localhost:8080` (override: `WEAVIATE_TEST_URL`)
- MinIO at `localhost:9000` (override: `MINIO_TEST_URL`)
- Neo4j at `localhost:7687` (override: `NEO4J_TEST_URL`)

**Shared fixtures:**
- `MockMinioClient` — in-memory MinIO client for unit tests (put/get/stat/remove/list/copy)
- `sample_manifest` — manifest with versioned, pre-versioned, and soft-deleted entries
- `sample_changelog` — YAML changelog with `none`, `metadata_only`, and `kg_reextract` strategies
- `mock_weaviate_client` — `MagicMock` with `.collections.get()` preconfigured
- `mock_neo4j_client` — `MagicMock` with `delete_by_source_key`, `soft_delete_by_source_key`

---

## 2. Unit Tests

### 2.1 Module: `src/ingest/common/minio_clean_store.py`

**Test file:** `tests/ingest/common/test_minio_clean_store.py`

**Test class:** `TestMinioCleanStore`

| Test Method | Assertions | Mocks | FR |
|-------------|-----------|-------|-----|
| `test_write_stores_markdown_and_meta_json` | `put_object` called twice: once for `.md` (content-type `text/markdown`), once for `.meta.json` (content-type `application/json`). `.meta.json` is written last (commit marker). | `MockMinioClient` | FR-3031, FR-3033 |
| `test_read_returns_identical_text_and_metadata` | `read()` returns the same `clean_text` and metadata dict passed to `write()`. | `MockMinioClient` | FR-3031 |
| `test_delete_removes_both_objects` | `remove_object` called for both `.md` and `.meta.json` keys. | `MockMinioClient` | FR-3021 |
| `test_soft_delete_moves_to_deleted_prefix` | `copy_object` called to move from `clean/` to `deleted/` prefix for both objects. Originals removed. | `MockMinioClient` | FR-3020 |
| `test_soft_delete_preserves_content` | After soft delete, objects exist under `deleted/` prefix with identical content. | `MockMinioClient` | FR-3020 |
| `test_list_keys_returns_source_keys` | `list_keys()` returns all keys under `clean/` prefix, excluding `deleted/`. | `MockMinioClient` | FR-3000 |
| `test_write_includes_schema_version_in_meta` | `.meta.json` content includes `schema_version` field matching `PIPELINE_SCHEMA_VERSION`. | `MockMinioClient` | FR-3102 |
| `test_write_includes_trace_id_in_meta` | `.meta.json` content includes `trace_id` field. | `MockMinioClient` | FR-3051 |
| `test_write_meta_json_is_valid_json` | `.meta.json` content deserialises without error, all expected fields present. | `MockMinioClient` | FR-3033 |

### 2.2 Module: `src/ingest/common/schemas.py`

**Test file:** `tests/ingest/common/test_manifest_schema.py`

**Test class:** `TestManifestBackwardCompat`

| Test Method | Assertions | Mocks | FR |
|-------------|-----------|-------|-----|
| `test_pre_lifecycle_manifest_loads_without_error` | Load a manifest dict with no `schema_version`, `trace_id`, `deleted`, `deleted_at`, `validation`, `clean_hash`, or `batch_id`. No exceptions. | None | FR-3114 |
| `test_missing_fields_resolve_to_defaults` | `schema_version` defaults to `"0.0.0"`, `trace_id` to `""`, `deleted` to `False`, `deleted_at` to `""`, `validation` to `{}`, `clean_hash` to `""`. | None | FR-3114 |
| `test_new_fields_serialize_round_trip` | A manifest entry with all 7 new fields survives `json.dumps` / `json.loads` round-trip with identical values. | None | FR-3114 |
| `test_existing_fields_preserved_after_extension` | Pre-existing fields (`source`, `source_key`, `content_hash`, etc.) are unchanged after adding lifecycle fields. | None | FR-3114 |

### 2.3 Module: `src/ingest/lifecycle/sync.py`

**Test file:** `tests/ingest/lifecycle/test_sync.py`

**Test class:** `TestDiffSources`

| Test Method | Assertions | Mocks | FR |
|-------------|-----------|-------|-----|
| `test_diff_detects_deleted_files` | Given 97 source files and 100 manifest entries, `diff_sources()` returns `deleted` list with 3 keys. | `tmp_path` source dir | FR-3000 |
| `test_diff_detects_added_files` | Given 103 source files and 100 manifest entries, `diff_sources()` returns `added` list with 3 keys. | `tmp_path` source dir | FR-3000 |
| `test_diff_detects_modified_files` | Given files with changed hashes, `diff_sources()` returns `modified` list. | `tmp_path` source dir | FR-3000 |
| `test_diff_excludes_soft_deleted_from_manifest_keys` | Manifest entries with `deleted=True` are not included in the manifest key set for diffing. | `sample_manifest` | FR-3000, FR-3020 |
| `test_diff_is_o_n_set_operations` | Verify `diff_sources` uses set difference (no nested loops). Assert correct counts for known inputs. | `tmp_path` source dir | NFR-3180 |
| `test_diff_empty_source_dir` | All manifest entries appear in `deleted` list. | `tmp_path` empty dir | FR-3000 |
| `test_diff_empty_manifest` | All source files appear in `added` list. | `tmp_path` source dir | FR-3000 |

### 2.4 Module: `src/ingest/lifecycle/gc.py`

**Test file:** `tests/ingest/lifecycle/test_gc.py`

**Test class:** `TestReconcileDeleted`

| Test Method | Assertions | Mocks | FR |
|-------------|-----------|-------|-----|
| `test_soft_delete_calls_all_four_stores` | In soft mode: `soft_delete_by_source_key` called on Weaviate, MinIO `soft_delete` called, Neo4j `soft_delete_by_source_key` called, manifest entry has `deleted=True` and `deleted_at` set. | Mock clients | FR-3001, FR-3020 |
| `test_hard_delete_calls_all_four_stores` | In hard mode: `delete_by_source_key` called on Weaviate, MinIO `delete` called, Neo4j `delete_by_source_key` called, manifest entry removed. | Mock clients | FR-3001, FR-3021 |
| `test_weaviate_failure_does_not_block_other_stores` | Weaviate mock raises exception. MinIO, Neo4j, manifest cleanup still proceed. `StoreCleanupStatus.weaviate=False`, others `True`. | Mock clients | NFR-3210 |
| `test_minio_failure_does_not_block_other_stores` | MinIO mock raises exception. Weaviate, Neo4j, manifest cleanup still proceed. `StoreCleanupStatus.minio=False`. | Mock clients | NFR-3210 |
| `test_neo4j_failure_does_not_block_other_stores` | Neo4j mock raises exception. Weaviate, MinIO, manifest cleanup still proceed. `StoreCleanupStatus.neo4j=False`. | Mock clients | NFR-3210 |
| `test_gc_result_counts_are_correct` | `GCResult.soft_deleted` matches the number of successfully processed keys. | Mock clients | FR-3001 |
| `test_soft_delete_sets_deleted_at_timestamp` | Manifest entry `deleted_at` is a valid ISO 8601 timestamp string after soft delete. | Mock clients | FR-3020 |
| `test_dry_run_does_not_mutate_stores` | With `dry_run=True`, no store methods are called. Manifest is unchanged. | Mock clients | FR-3010 |

**Test class:** `TestPurgeExpired`

| Test Method | Assertions | Mocks | FR |
|-------------|-----------|-------|-----|
| `test_purge_expired_deletes_past_retention` | Entry soft-deleted 45 days ago with `retention_days=30` is hard-deleted. | `sample_manifest`, mock clients | FR-3022 |
| `test_purge_expired_preserves_within_retention` | Entry soft-deleted 10 days ago with `retention_days=30` is NOT purged. | `sample_manifest`, mock clients | FR-3022 |
| `test_purge_expired_ignores_non_deleted_entries` | Entries with `deleted=False` are never purged regardless of age. | `sample_manifest`, mock clients | FR-3022 |
| `test_purge_expired_handles_malformed_deleted_at` | Entry with unparseable `deleted_at` is logged as warning, not purged, no crash. | `sample_manifest` | FR-3022 |

### 2.5 Module: `src/ingest/lifecycle/orphan_report.py`

**Test file:** `tests/ingest/lifecycle/test_orphan_report.py`

**Test class:** `TestDetectOrphans`

| Test Method | Assertions | Mocks | FR |
|-------------|-----------|-------|-----|
| `test_detects_weaviate_orphans` | Weaviate has source_keys not in manifest. Reported in `report.weaviate_orphans`. | Mock clients | FR-3002 |
| `test_detects_minio_orphans` | MinIO has keys not in manifest. Reported in `report.minio_orphans`. | Mock clients | FR-3002 |
| `test_detects_neo4j_orphans` | Neo4j has source_keys not in manifest. Reported in `report.neo4j_orphans`. | Mock clients | FR-3002 |
| `test_no_orphans_returns_empty_lists` | When all stores match manifest, all orphan lists are empty. | Mock clients | FR-3002 |
| `test_orphan_detection_is_read_only` | No mutation methods called on any store client. | Mock clients | FR-3002 |

### 2.6 Module: `src/ingest/lifecycle/changelog.py`

**Test file:** `tests/ingest/lifecycle/test_changelog.py`

**Test class:** `TestMigrationStrategy`

| Test Method | Assertions | Mocks | FR |
|-------------|-----------|-------|-----|
| `test_metadata_only_strategy` | `determine_migration_strategy("0.0.0", "1.0.0", changelog)` returns `"metadata_only"`. | `sample_changelog` | FR-3111 |
| `test_kg_reextract_escalation` | `determine_migration_strategy("1.0.0", "1.1.0", changelog)` returns `"kg_reextract"`. | `sample_changelog` | FR-3111 |
| `test_full_phase2_escalation` | With a changelog containing `full_phase2` at 1.2.0, `determine_migration_strategy("0.0.0", "1.2.0")` returns `"full_phase2"` (highest rank wins). | Extended changelog | FR-3111 |
| `test_same_version_returns_none` | `determine_migration_strategy("1.0.0", "1.0.0", changelog)` returns `"none"` or equivalent skip signal. | `sample_changelog` | FR-3111 |
| `test_strategy_rank_ordering` | `"none"` < `"metadata_only"` < `"kg_reextract"` < `"full_phase2"`. | None | FR-3111 |

### 2.7 Module: `src/ingest/lifecycle/migration.py`

**Test file:** `tests/ingest/lifecycle/test_migration.py`

**Test class:** `TestRunMigration`

| Test Method | Assertions | Mocks | FR |
|-------------|-----------|-------|-----|
| `test_migration_idempotency_all_current` | All documents at target version. `MigrationResult.processed=0`, `skipped=N`, no store writes. | Mock clients, `sample_manifest` | FR-3112 |
| `test_migration_idempotency_partial` | Some documents at target, some below. Only below-target documents are processed. | Mock clients | FR-3112 |
| `test_migration_metadata_only_updates_weaviate` | For `metadata_only` strategy, `batch_update_metadata_by_source_key` called with `schema_version` update. | Mock clients | FR-3110, FR-3111 |
| `test_migration_updates_manifest_version` | After migration, manifest entry `schema_version` matches target version. | Mock clients | FR-3100 |
| `test_migration_dry_run_no_mutations` | With `dry_run=True`, no store methods called. Manifest unchanged. | Mock clients | FR-3110 |
| `test_migration_resumability_after_failure` | First run fails mid-way (mock raises on 3rd document). Second run processes only remaining documents. | Mock clients | NFR-3211 |
| `test_migration_result_strategy_counts` | `MigrationResult.strategy_counts` correctly tallies per-strategy document counts. | Mock clients | FR-3110 |

### 2.8 Module: `src/ingest/lifecycle/validation.py`

**Test file:** `tests/ingest/lifecycle/test_validation.py`

**Test class:** `TestValidateDocument`

| Test Method | Assertions | Mocks | FR |
|-------------|-----------|-------|-----|
| `test_all_stores_pass_returns_consistent_true` | All store queries return positive results. `consistent=True`, all `*_ok=True`. | Mock clients | FR-3060 |
| `test_weaviate_missing_returns_inconsistent` | Weaviate `count_by_trace_id` returns 0. `consistent=False`, `weaviate_ok=False`. | Mock clients | FR-3060 |
| `test_minio_missing_returns_inconsistent` | MinIO object does not exist. `consistent=False`, `minio_ok=False`. | Mock clients | FR-3060 |
| `test_neo4j_missing_returns_inconsistent` | Neo4j `count_triples_by_trace_id` returns 0. `consistent=False`, `neo4j_ok=False`. | Mock clients | FR-3060 |
| `test_kg_disabled_neo4j_ok_is_none` | `kg_enabled=False`. `neo4j_ok=None`, document still `consistent=True` if Weaviate and MinIO pass. | Mock clients | FR-3062 |
| `test_validation_result_recorded_in_manifest` | `ValidationResult` is serialisable and contains `validated_at` timestamp. | None | FR-3061 |

---

## 3. Integration Tests

### 3.1 MinIO Clean Store Round-Trip

**Test file:** `tests/ingest/lifecycle/test_minio_integration.py`

**Setup:** Real MinIO client connected to test instance. Create a unique test bucket per run.

**Test class:** `TestMinioCleanStoreIntegration`

| Test Method | Steps | Verification |
|-------------|-------|-------------|
| `test_write_read_delete_round_trip` | 1. `store.write(source_key, clean_text, meta)` 2. `result = store.read(source_key)` 3. `store.delete(source_key)` 4. `store.read(source_key)` | Step 2: text and meta match. Step 4: raises not-found. |
| `test_soft_delete_moves_objects` | 1. `store.write(...)` 2. `store.soft_delete(source_key)` 3. Check `deleted/` prefix exists 4. Check `clean/` prefix empty | Objects exist under `deleted/`, absent under `clean/`. |

**Teardown:** Delete test bucket.

### 3.2 Four-Store GC Integration

**Test file:** `tests/ingest/lifecycle/test_gc_integration.py`

**Setup:** Weaviate test collection, MinIO test bucket, Neo4j test database. Ingest a document through the full pipeline to populate all stores.

| Test Method | Steps | Verification |
|-------------|-------|-------------|
| `test_soft_delete_marks_all_stores` | 1. Ingest `doc_a`. 2. `reconcile_deleted(["doc_a"], mode="soft")`. 3. Query each store. | Weaviate: chunks have `deleted=True`. MinIO: objects under `deleted/`. Neo4j: triples have `deleted=True`. Manifest: `deleted=True`, `deleted_at` set. |
| `test_hard_delete_removes_from_all_stores` | 1. Ingest `doc_a`. 2. `reconcile_deleted(["doc_a"], mode="hard")`. 3. Query each store. | Weaviate: no chunks for `doc_a`. MinIO: no objects. Neo4j: no triples. Manifest: entry removed. |
| `test_purge_expired_integration` | 1. Ingest `doc_a`. 2. Soft delete with backdated `deleted_at` (45 days ago). 3. `purge_expired(retention_days=30)`. | All stores: `doc_a` data removed. Manifest entry removed. |

**Teardown:** Delete test collection, bucket, and database.

### 3.3 Trace ID End-to-End Propagation

**Test file:** `tests/ingest/lifecycle/test_trace_integration.py`

**Setup:** All stores running. Ingest a single document through `ingest_file()`.

| Test Method | Steps | Verification |
|-------------|-------|-------------|
| `test_trace_id_present_in_all_stores` | 1. `result = ingest_file(source_path, ...)`. 2. Extract `trace_id` from result. 3. Query each store by `trace_id`. | Weaviate: `count_by_trace_id > 0`. MinIO: `.meta.json` contains `trace_id`. Neo4j: `count_triples_by_trace_id > 0`. Manifest: `trace_id` field matches. |
| `test_trace_id_is_uuid4_format` | 1. `result = ingest_file(...)`. 2. Parse `result.trace_id` as UUID. | Valid UUID v4. |

### 3.4 Schema Migration Integration

**Test file:** `tests/ingest/lifecycle/test_migration_integration.py`

| Test Method | Steps | Verification |
|-------------|-------|-------------|
| `test_metadata_only_migration_updates_weaviate` | 1. Ingest documents at schema 1.0.0. 2. Run migration to 1.1.0 (metadata_only). 3. Query Weaviate chunks. | All chunks have `schema_version: "1.1.0"`. Manifest entries updated. |
| `test_migration_preserves_chunk_content` | 1. Record chunk text before migration. 2. Run metadata_only migration. 3. Compare chunk text after. | Text unchanged. Only `schema_version` metadata updated. |

---

## 4. Contract Tests

### 4.1 Interface Contracts

**Test file:** `tests/ingest/lifecycle/test_contracts.py`

| Test Method | What It Validates | FR |
|-------------|-------------------|-----|
| `test_sync_result_has_required_fields` | `SyncResult` has `added`, `modified`, `deleted`, `unchanged` fields of correct types. | FR-3000 |
| `test_gc_result_has_required_fields` | `GCResult` has `soft_deleted`, `hard_deleted`, per-key status list. | FR-3001 |
| `test_store_cleanup_status_has_all_stores` | `StoreCleanupStatus` has boolean fields for `weaviate`, `minio`, `neo4j`, `manifest`. | NFR-3210 |
| `test_migration_result_has_required_fields` | `MigrationResult` has `total_eligible`, `processed`, `failed`, `skipped`, `strategy_counts`. | FR-3110 |
| `test_validation_result_is_serialisable` | `ValidationResult` round-trips through `json.dumps`/`json.loads`. | FR-3061 |
| `test_orphan_report_has_per_store_lists` | `OrphanReport` has `weaviate_orphans`, `minio_orphans`, `neo4j_orphans` as `list[str]`. | FR-3002 |

### 4.2 State Invariants

| Test Method | What It Validates | FR |
|-------------|-------------------|-----|
| `test_manifest_entry_deleted_requires_deleted_at` | If `deleted=True`, `deleted_at` must be a non-empty ISO 8601 string. | FR-3020 |
| `test_manifest_entry_not_deleted_has_empty_deleted_at` | If `deleted=False`, `deleted_at` must be `""`. | FR-3020 |
| `test_trace_id_is_nonempty_on_lifecycle_entries` | Entries with `schema_version >= "1.0.0"` must have non-empty `trace_id`. | FR-3050 |
| `test_schema_version_is_semver_string` | `schema_version` matches `\d+\.\d+\.\d+` pattern. | FR-3100 |
| `test_clean_hash_is_64_char_hex` | `clean_hash` is a 64-character lowercase hex string (SHA-256). | FR-3031 |

---

## 5. Requirement Traceability

| FR | Description | Test Method | Test File |
|----|-------------|-------------|-----------|
| FR-3000 | Source-to-manifest diff | `test_diff_detects_deleted_files`, `test_diff_detects_added_files`, `test_diff_detects_modified_files`, `test_diff_excludes_soft_deleted_from_manifest_keys`, `test_diff_empty_source_dir`, `test_diff_empty_manifest` | `test_sync.py` |
| FR-3001 | Four-store reconciliation | `test_soft_delete_calls_all_four_stores`, `test_hard_delete_calls_all_four_stores`, `test_gc_result_counts_are_correct` | `test_gc.py` |
| FR-3002 | Orphan detection report | `test_detects_weaviate_orphans`, `test_detects_minio_orphans`, `test_detects_neo4j_orphans`, `test_no_orphans_returns_empty_lists`, `test_orphan_detection_is_read_only` | `test_orphan_report.py` |
| FR-3010 | Manual GC trigger | `test_dry_run_does_not_mutate_stores` | `test_gc.py` |
| FR-3020 | Soft delete with retention | `test_soft_delete_calls_all_four_stores`, `test_soft_delete_sets_deleted_at_timestamp`, `test_soft_delete_moves_to_deleted_prefix`, `test_soft_delete_preserves_content` | `test_gc.py`, `test_minio_clean_store.py` |
| FR-3021 | Hard delete override | `test_hard_delete_calls_all_four_stores`, `test_delete_removes_both_objects` | `test_gc.py`, `test_minio_clean_store.py` |
| FR-3022 | Retention purge | `test_purge_expired_deletes_past_retention`, `test_purge_expired_preserves_within_retention`, `test_purge_expired_ignores_non_deleted_entries`, `test_purge_expired_handles_malformed_deleted_at` | `test_gc.py` |
| FR-3031 | MinIO as durable clean store | `test_write_stores_markdown_and_meta_json`, `test_read_returns_identical_text_and_metadata` | `test_minio_clean_store.py` |
| FR-3033 | MinIO clean store object schema | `test_write_meta_json_is_valid_json`, `test_write_includes_schema_version_in_meta`, `test_write_includes_trace_id_in_meta` | `test_minio_clean_store.py` |
| FR-3050 | Trace ID generation | `test_trace_id_is_uuid4_format` | `test_trace_integration.py` |
| FR-3051 | Phase 1 trace ID injection | `test_write_includes_trace_id_in_meta`, `test_trace_id_present_in_all_stores` | `test_minio_clean_store.py`, `test_trace_integration.py` |
| FR-3052 | Phase 2 trace ID propagation | `test_trace_id_present_in_all_stores` | `test_trace_integration.py` |
| FR-3060 | Per-document store consistency validation | `test_all_stores_pass_returns_consistent_true`, `test_weaviate_missing_returns_inconsistent`, `test_minio_missing_returns_inconsistent`, `test_neo4j_missing_returns_inconsistent` | `test_validation.py` |
| FR-3061 | Validation result recording | `test_validation_result_recorded_in_manifest`, `test_validation_result_is_serialisable` | `test_validation.py`, `test_contracts.py` |
| FR-3062 | Validation skip for disabled stores | `test_kg_disabled_neo4j_ok_is_none` | `test_validation.py` |
| FR-3100 | Schema version on manifest | `test_schema_version_is_semver_string`, `test_migration_updates_manifest_version` | `test_contracts.py`, `test_migration.py` |
| FR-3102 | Schema version on MinIO metadata | `test_write_includes_schema_version_in_meta` | `test_minio_clean_store.py` |
| FR-3110 | Selective re-processing by schema version | `test_migration_metadata_only_updates_weaviate`, `test_migration_dry_run_no_mutations`, `test_migration_result_strategy_counts` | `test_migration.py` |
| FR-3111 | Migration strategy classification | `test_metadata_only_strategy`, `test_kg_reextract_escalation`, `test_full_phase2_escalation`, `test_same_version_returns_none`, `test_strategy_rank_ordering` | `test_changelog.py` |
| FR-3112 | Migration idempotency | `test_migration_idempotency_all_current`, `test_migration_idempotency_partial` | `test_migration.py` |
| FR-3114 | Backward-compatible manifest extension | `test_pre_lifecycle_manifest_loads_without_error`, `test_missing_fields_resolve_to_defaults`, `test_new_fields_serialize_round_trip`, `test_existing_fields_preserved_after_extension` | `test_manifest_schema.py` |
| NFR-3180 | GC scan performance (O(n)) | `test_diff_is_o_n_set_operations` | `test_sync.py` |
| NFR-3210 | Partial GC failure isolation | `test_weaviate_failure_does_not_block_other_stores`, `test_minio_failure_does_not_block_other_stores`, `test_neo4j_failure_does_not_block_other_stores` | `test_gc.py` |
| NFR-3211 | Migration resumability | `test_migration_resumability_after_failure` | `test_migration.py` |
