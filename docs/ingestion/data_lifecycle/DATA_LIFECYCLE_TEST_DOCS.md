# Data Lifecycle Test Documentation

| Field | Value |
|-------|-------|
| **Subsystem** | Data Lifecycle |
| **Status** | Authoritative (post-implementation) |
| **Engineering guide** | `DATA_LIFECYCLE_ENGINEERING_GUIDE.md` |
| **Test location** | `tests/ingest/lifecycle/` |
| **Last updated** | 2026-04-17 |

---

## 1. Test Strategy

### Unit vs integration

All tests in `tests/ingest/lifecycle/` are **unit tests**. There are no
integration tests that exercise real MinIO, Weaviate, or Neo4j backends. Every
external store dependency is replaced with either:

- A lightweight in-process stub class (defined in the test file or `conftest.py`).
- A `monkeypatch` / `unittest.mock.patch` override of the facade function the
  engine imports lazily (`src.vector_db.aggregate_by_source`,
  `src.vector_db.count_by_trace_id`, etc.).

### What is mocked

| Dependency | Mocking approach |
|------------|-----------------|
| Weaviate — `aggregate_by_source` | `monkeypatch.setattr(src.vector_db, "aggregate_by_source", ...)` |
| Weaviate — `count_by_trace_id` | `monkeypatch.setattr(src.vector_db, "count_by_trace_id", ..., raising=False)` |
| Weaviate — `delete_by_source_key` | `monkeypatch.setattr` or `engine._cleanup_weaviate` patched directly |
| MinIO client | `_FakeMinio` / `_MockMinioClientWithKeys` stub class with `list_objects` |
| `MinioCleanStore` | Monkeypatched class factory or `_cleanup_minio` patched on engine |
| Neo4j client | `_MockNeo4jClient` stub with `list_source_keys()` |
| KG client | `MagicMock()` with `count_triples_by_trace_id` |
| Manifest | Plain `dict` constructed in-test |
| CLI infrastructure (`_open_weaviate_client`, etc.) | `unittest.mock.patch` |

### What is real

- All dataclass construction and field access (`schemas.py`)
- All set-diff logic (`SyncEngine.diff`)
- Manifest mutations (`GCEngine._cleanup_manifest`)
- Retention window calculation (`GCEngine.purge_expired`)
- Changelog YAML parsing (`load_changelog`)
- Strategy resolution (`determine_migration_strategy`)
- Migration plan generation (`MigrationEngine.plan`)
- Migration idempotency check (`MigrationEngine.execute` — skips already-at-target)
- `ValidationFinding` consistency logic
- Report formatters (`format_text`, `format_json`)
- CLI argument parsing and exit code behaviour

---

## 2. Test File Map

| File | What it covers |
|------|---------------|
| `conftest.py` | Lifecycle-local stubs for PIL, prometheus_client, langfuse, redis, temporalio, nemoguardrails, colpali_engine, bitsandbytes, docling, jwt, langdetect, tree_sitter. Prevents deep transitive imports from loading GPU/ML dependencies. |
| `test_sync_engine.py` | `SyncEngine.inventory()` and `SyncEngine.diff()` — key population from each store, error capture, optional-store skip, orphan and manifest-only detection, sort order. |
| `test_gc_engine.py` | `GCEngine.collect_keys()` soft delete, hard delete, dry run, `purge_expired()` retention window, store isolation (NFR-3210), `_require_hard_delete_confirmation` helper. |
| `test_migration.py` | `MigrationEngine.plan()` and `execute()` — eligible entry selection, strategy assignment, `metadata_only` execution path, per-entry failure isolation, idempotency. |
| `test_changelog.py` | `load_changelog()`, `get_required_migrations()`, `determine_migration_strategy()` — valid and malformed files, multi-step ranges, strategy escalation. |
| `test_validation.py` | `E2EValidator.validate_by_trace_id()` and `validate_all()` — consistent/inconsistent findings, KG disabled, MinIO disabled, `sample_size` limit. |
| `test_orphan_report.py` | `format_text()` and `format_json()` — output structure, serialisation correctness, optional GC summary, sorted keys, roundtrip parity. |
| `test_lifecycle_cli.py` | `run_migration_cli()` and `run_validation_cli()` — argparse integration, dry-run/confirm guards, JSON/text output, mutual exclusion, exit codes. |

---

## 3. Coverage by FR

| FR / NFR | Test function(s) |
|----------|-----------------|
| FR-3000 (four-store inventory) | `TestInventory.test_weaviate_keys_populated`, `test_minio_keys_populated`, `test_neo4j_keys_populated`, `test_empty_manifest_and_stores` |
| FR-3002 (orphan detection) | `TestDiff.test_weaviate_orphan_detected`, `test_minio_orphan_detected`, `test_neo4j_orphan_detected`, `test_manifest_only_detected`, `test_no_orphans_when_all_match`, `test_orphan_lists_are_sorted` |
| FR-3001 (GC collect) | `TestSoftDelete.test_soft_delete_marks_manifest`, `test_soft_delete_increments_counter`, `TestHardDelete.test_hard_delete_removes_from_manifest` |
| FR-3010 (soft delete) | `TestSoftDelete.test_soft_delete_marks_manifest`, `test_soft_delete_uses_minio_soft_delete` |
| FR-3020 (retention window) | `TestRetentionWindow.test_expired_entries_are_purged`, `test_recent_entries_are_not_purged`, `test_dry_run_purge_does_not_delete`, `test_non_deleted_entries_never_purged`, `test_entries_without_deleted_at_are_skipped`, `test_mixed_entries_purges_only_expired` |
| FR-3022 (purge_expired) | `TestRetentionWindow.*` |
| FR-3060 (E2E validation) | `TestValidateByTraceIdConsistent.test_consistent_when_all_stores_ok`, `TestValidateAll.test_validate_all_consistent` |
| FR-3061 (per-store findings) | `TestValidateByTraceIdMissingStore.*`, `TestValidateAll.test_validate_all_one_inconsistent` |
| FR-3062 (disabled stores = None) | `TestValidateByTraceIdKgDisabled.test_kg_none_reports_neo4j_ok_as_none`, `TestValidateAll.test_validate_all_minio_disabled_is_none` |
| FR-3110 (migration plan) | `TestMigrationEnginePlan.test_plan_identifies_eligible_entries`, `test_plan_skips_deleted_entries`, `test_plan_sets_correct_strategy` |
| FR-3111 (strategies) | `TestMigrationEngineExecuteMetadataOnly.test_execute_metadata_only_calls_batch_update`, `TestDetermineMigrationStrategy.*` |
| FR-3112 (idempotency) | `TestMigrationEngineIdempotency.test_re_run_on_migrated_manifest_is_noop`, `test_execute_idempotency_at_target_version` |
| FR-3113 (changelog) | `TestLoadChangelog.*`, `TestGetRequiredMigrations.*`, `TestDetermineMigrationStrategy.*` |
| NFR-3210 (store isolation) | `TestStoreIsolation.test_weaviate_failure_does_not_block_manifest`, `test_per_document_status_recorded` |
| NFR-3211 (resumability) | `TestMigrationEngineIdempotency.test_re_run_on_migrated_manifest_is_noop` |
| NFR-3221 (audit log) | Covered implicitly (log calls execute without error in integration paths) |
| NFR-3230 (hard delete guard) | `TestHardDelete.test_hard_delete_refused_without_confirm`, `test_hard_delete_refused_without_cli_confirmed`, `test_hard_delete_refused_without_any_confirmation`, `TestRequireHardDeleteConfirmation.*` |

---

## 4. Fixture Reference

### `conftest.py` — `_install_lifecycle_stubs()`

Called once at import time. Installs in-process module stubs for heavy
dependencies to prevent transitive import failures during test collection:

| Stub | Purpose |
|------|---------|
| `PIL` / `PIL.Image` | Prevents Pillow import errors in vision-dependent modules |
| `prometheus_client` | Stub Counter/Gauge/Histogram/Summary |
| `langfuse` / `langfuse.decorators` | Stub Langfuse tracing |
| `redis` / `redis.asyncio` | Stub Redis client |
| `temporalio.*` | Stub all Temporal workflow decorators |
| `nemoguardrails.*` | Stub NeMo guardrails |
| `colpali_engine.*` | Stub ColQwen2 and ColQwen2Processor |
| `bitsandbytes` | Stub quantization library |
| `docling.*` / `docling_core.*` | Stub document conversion library |
| `jwt` | Stub PyJWT encode/decode |
| `langdetect` | Stub language detection (returns `"en"`) |
| `tree_sitter` / `tree_sitter_verilog` | Stub tree-sitter parser |

### In-test fixtures and helpers

**`test_sync_engine.py`**

| Helper | Description |
|--------|-------------|
| `_manifest(*source_keys, deleted_keys=[])` | Build a minimal manifest dict |
| `_MockWeaviateClient(keys)` | Stub Weaviate client holding a key list |
| `_MockMinioClientWithKeys(keys)` | Stub MinIO client with `list_objects` returning `.meta.json` objects |
| `_MockNeo4jClient(keys)` | Stub KG client with `list_source_keys()` |
| `_make_sync_engine(manifest, weaviate_keys, minio_keys, neo4j_keys, monkeypatch)` | Build a `SyncEngine` with patched store enumeration |
| `_patch_aggregate(monkeypatch, keys)` | Patch `src.vector_db.aggregate_by_source` |

**`test_gc_engine.py`**

| Helper | Description |
|--------|-------------|
| `_soft_entry(key)` | Build a non-deleted manifest entry |
| `_deleted_entry(key, deleted_at)` | Build a soft-deleted manifest entry with timestamp |
| `_orphan_report(*manifest_only)` | Build an `OrphanReport` with manifest_only keys |
| `_FakeWeaviateClient` | Empty Weaviate client stub |

**`test_migration.py`**

| Fixture | Description |
|---------|-------------|
| `changelog_path(tmp_path)` | Write a three-version YAML changelog to a temp file |
| `changelog(changelog_path)` | Load the temp changelog |
| `stub_vector_db()` | `MagicMock()` with `batch_update_metadata_by_source_key.return_value = 1` |
| `weaviate_client()` | `MagicMock()` |
| `_make_engine(...)` | Build a `MigrationEngine` with injected stubs |
| `_manifest_with_entries(*versions)` | Build a manifest with N entries at the given schema versions |

**`test_changelog.py`**

| Fixture | Description |
|---------|-------------|
| `changelog_yaml(tmp_path)` | Write a four-version YAML changelog (0.0.0, 1.0.0, 2.0.0, 2.1.0) |
| `changelog(changelog_yaml)` | Load the temp changelog |

**`test_validation.py`**

| Helper | Description |
|--------|-------------|
| `_manifest(trace_id, source_key, deleted)` | Build a single-entry manifest |
| `_patch_weaviate_count(monkeypatch, count)` | Patch `src.vector_db.count_by_trace_id` |

**`test_orphan_report.py`**

| Helper | Description |
|--------|-------------|
| `_report(weaviate, minio, neo4j, manifest_only)` | Build an `OrphanReport` |
| `_gc(soft_deleted, hard_deleted, retention_purged, dry_run, per_document)` | Build a `GCReport` |

**`test_lifecycle_cli.py`**

| Fixture/Helper | Description |
|----------------|-------------|
| `changelog_path(tmp_path)` | Write a two-version (0.0.0, 1.0.0) changelog to temp file |
| `_empty_manifest()` | Returns `{}` |
| `_manifest_one_entry(version)` | Returns a single-entry manifest at the given version |

---

## 5. Running Tests

### Run the full lifecycle suite

```bash
cd /path/to/RagWeave-ingestion-hardening
pytest tests/ingest/lifecycle/ -v
```

### Run a single test file

```bash
pytest tests/ingest/lifecycle/test_gc_engine.py -v
pytest tests/ingest/lifecycle/test_sync_engine.py -v
pytest tests/ingest/lifecycle/test_migration.py -v
pytest tests/ingest/lifecycle/test_changelog.py -v
pytest tests/ingest/lifecycle/test_validation.py -v
pytest tests/ingest/lifecycle/test_orphan_report.py -v
pytest tests/ingest/lifecycle/test_lifecycle_cli.py -v
```

### Run a specific test class or function

```bash
pytest tests/ingest/lifecycle/test_gc_engine.py::TestRetentionWindow -v
pytest tests/ingest/lifecycle/test_migration.py::TestMigrationEngineIdempotency::test_re_run_on_migrated_manifest_is_noop -v
```

### Run with coverage

```bash
pytest tests/ingest/lifecycle/ --cov=src.ingest.lifecycle --cov=src.ingest.common.minio_clean_store --cov-report=term-missing
```

### Useful pytest flags

| Flag | Purpose |
|------|---------|
| `-v` | Verbose output (show test names) |
| `-x` | Stop on first failure |
| `-k "soft"` | Run only tests whose name contains "soft" |
| `--tb=short` | Shorter tracebacks for faster scanning |
| `-p no:warnings` | Suppress deprecation warnings from stubs |
