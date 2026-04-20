# Ingestion Pipeline Test Coverage — Auto-Research Program (v3)

## Objective

Increase test coverage of `src/ingest/` from 60% to 75% by writing new tests. Each iteration adds one *type* of test (pure logic, edge case/error path, mock-based, or fixture-based integration) across one or more files.

Baseline: 60% coverage (1121 tests passing, 4785 statements, 1855 missed).

## Scoring mode

Numerical

## Metric

Score = integer coverage percentage reported by `pytest-cov` on `src/ingest/`.
Higher is better. Target: 75%.

## Scoring mechanism

`uv run python src/ingest/scorer_v3.py` from the project root.

### Correctness guard

1. All existing tests must pass (`pytest tests/ingest/ -x -q --tb=short`).
2. Mock naming convention: any new test function whose name contains "mock" must start with `test_mock_`. Pre-existing violations are grandfathered.

## Mutable files

Only test files may be modified or created:

### Existing test files (modify to add tests)
- `tests/ingest/test_clean_store.py`
- `tests/ingest/test_cli_args.py`
- `tests/ingest/test_ingest_cli.py`
- `tests/ingest/test_shared_helpers.py`
- `tests/ingest/test_manifest_io.py`
- `tests/ingest/test_orchestrator.py`
- `tests/ingest/test_parser_integration.py`
- `tests/ingest/test_dedup_revert.py`
- `tests/ingest/test_dedup_workflow_integration.py`
- `tests/ingest/test_visual_embedding_node.py`
- `tests/ingest/test_visual_embedding_colqwen.py`
- `tests/ingest/test_visual_embedding_config_state.py`
- `tests/ingest/test_visual_embedding_minio.py`
- `tests/ingest/test_visual_embedding_docling.py`
- `tests/ingest/test_visual_store.py`
- `tests/ingest/doc_processing/test_structure_detection_coverage.py`
- `tests/ingest/embedding/test_chunk_enrichment.py`
- `tests/ingest/embedding/test_chunking.py`
- `tests/ingest/embedding/test_cross_reference.py`
- `tests/ingest/embedding/test_document_storage.py`
- `tests/ingest/embedding/test_embedding_storage.py`
- `tests/ingest/embedding/test_quality_validation.py`
- `tests/ingest/lifecycle/test_gc_engine.py`
- `tests/ingest/lifecycle/test_migration.py`
- `tests/ingest/lifecycle/test_validation.py`
- `tests/ingest/lifecycle/test_changelog.py`
- `tests/ingest/lifecycle/test_sync_engine.py`

### New test files (create as needed)
- `tests/ingest/test_document_support.py` — for `support/document.py`
- `tests/ingest/test_markdown_support.py` — for `support/markdown.py`
- `tests/ingest/test_parser_code.py` — for `support/parser_code.py`
- `tests/ingest/test_parser_text.py` — for `support/parser_text.py`
- `tests/ingest/test_parser_registry.py` — for `support/parser_registry.py`
- `tests/ingest/test_vision_support.py` — for `support/vision.py`
- `tests/ingest/test_minhash_engine.py` — for `embedding/support/minhash_engine.py`
- `tests/ingest/test_dedup_utils.py` — for `embedding/common/dedup_utils.py`
- `tests/ingest/test_minio_clean_store.py` — for `common/minio_clean_store.py`
- `tests/ingest/test_temporal_constants.py` — for `temporal/constants.py`
- `tests/ingest/test_temporal_worker.py` — for `temporal/worker.py`
- `tests/ingest/test_temporal_activities.py` — for `temporal/activities.py`
- `tests/ingest/test_temporal_workflows.py` — for `temporal/workflows.py`
- `tests/ingest/test_embedding_impl.py` — for `embedding/impl.py`
- `tests/ingest/test_cross_document_dedup.py` — for `embedding/nodes/cross_document_dedup.py`
- `tests/ingest/test_common_utils.py` — for `common/utils.py`
- `tests/ingest/test_impl_coverage.py` — for `impl.py` (orchestrator edge cases)

### Existing conftest files (modify to add shared fixtures)
- `tests/ingest/conftest.py`
- `tests/ingest/lifecycle/conftest.py`

## Immutable files (DO NOT MODIFY)

- `src/ingest/PROGRAM.md` — this file
- `src/ingest/scorer_v3.py` — the scoring script
- `src/ingest/scorer_v2.py` — previous scoring script
- `src/ingest/scorer.py` — v1 scoring script
- All source files under `src/ingest/` — this run adds tests only, never changes production code
- All existing test files NOT listed in the mutable set above

## Exploration directions

Each iteration picks ONE test type and applies it across the highest-impact uncovered files:

### 1. Pure logic tests (highest priority — easiest wins)
Unit tests for functions with no external dependencies. Target files in priority order:
- `support/document.py` (42% → all uncovered lines are pure string ops)
- `support/markdown.py` (42% → heading normalization, sentence splitting, section metadata)
- `temporal/constants.py` (0% → `trigger_to_priority`, `trigger_to_queue`, env-driven constants)
- `temporal/worker.py` (0% → `_resolve_slots`, `_resolve_queues`, `_validate_*` pure functions)
- `embedding/support/minhash_engine.py` (0% → `_word_shingles`, `MinHashEngine`, `compute_fuzzy_fingerprint`)
- `common/utils.py` (81% → `sha256_path`, `decode_with_fallbacks` edge cases)

### 2. Edge case and error path tests
Tests for error handling, boundary conditions, and fallback paths in partially-covered modules:
- `support/parser_text.py` (57% → HTML/RST fallback paths, RuntimeError on chunk before parse)
- `support/parser_code.py` (37% → `chunk()` RuntimeError, `_get_name` anonymous fallback, `_extract_docstring`, `_extract_imports`)
- `support/parser_registry.py` (64% → ImportError fallback paths, unknown extension, missing dep fallback)
- `lifecycle/validation.py` (67% → Weaviate error paths, KG count None paths, manifest load errors)
- `lifecycle/migration.py` (56% → unknown strategy ValueError, manifest load/save errors, lazy init paths)
- `lifecycle/gc.py` (44% → dry-run paths, cleanup error paths, manifest soft/hard branches)
- `embedding/common/dedup_utils.py` (72% → exception handlers, no-op paths)
- `embedding/nodes/cross_document_dedup.py` (65% → degraded path, fuzzy dedup tier 2)

### 3. Mock-based tests (test_mock_* naming required)
Tests using `unittest.mock` or `pytest-mock` for code that calls external services. All mock test functions MUST be named `test_mock_*`:
- `support/vision.py` (34% → mock VLM provider for `_describe_image`, `generate_vision_notes`, `ensure_vision_ready`)
- `common/minio_clean_store.py` (43% → mock MinIO client for write/read/exists/delete/soft_delete/list_keys)
- `temporal/activities.py` (0% → mock embedder, db_client, docling for `prewarm_worker_resources`, `_deserialise_config`)
- `temporal/workflows.py` (0% → mock Temporal workflow test harness)
- `embedding/impl.py` (50% → mock graph invoke for `run_embedding_pipeline` error/success paths)
- `cli.py` (44% → mock `ingest_directory` for CLI entry points)
- `support/docling.py` (69% → mock DocumentConverter for parse/chunk paths)

### 4. Fixture-based integration tests
Tests using pytest fixtures (`tmp_path`, custom conftest fixtures) to wire up real components:
- `impl.py` (83% → fixture with temp directory + sample files for `ingest_directory` edge cases)
- `lifecycle/gc.py` (44% → fixture-based GC engine with in-memory manifest)
- `lifecycle/migration.py` (56% → fixture-based migration plan/execute with tmp manifest)

## Constraints

- **Never modify production source code** — only test files are mutable
- **Mock naming convention** — any test function using mocks whose name contains "mock" must start with `test_mock_`. This is enforced by the scorer's naming guard.
- **No new external dependencies** — use only `pytest`, `pytest-cov`, `unittest.mock`, and existing project deps
- **Test isolation** — new tests must not depend on external services being running (MinIO is available but tests should work without it via mocks; use real MinIO only for minio-specific integration tests)
- **Backward compatibility** — existing 1121 tests must continue to pass at all times
- **One test TYPE per iteration** — pick one exploration direction per iteration, apply it to one or more files

## Stop conditions

- Coverage reaches 75% — success, stop
- 5 consecutive iterations with no coverage improvement — stop and report
- Correctness guard fails 3× in a row — stop, infrastructure broken
- 20 iterations reached — stop and report regardless of score
