# Ingestion Pipeline Test Coverage — Auto-Research Program (v4)

## Objective

Increase test coverage of `src/ingest/` from 75% to 85% by writing new tests. Each iteration adds one *type* of test (pure logic, edge case/error path, mock-based, or fixture-based integration) targeting the remaining uncovered code paths.

Baseline: 75% coverage (1548 tests passing, 4864 statements, 1240 missed).

## Scoring mode

Numerical

## Metric

Score = integer coverage percentage reported by `pytest-cov` on `src/ingest/`.
Higher is better. Target: 85%.

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
- `tests/ingest/test_document_support.py`
- `tests/ingest/test_markdown_support.py`
- `tests/ingest/test_parser_code.py`
- `tests/ingest/test_parser_text.py`
- `tests/ingest/test_parser_registry.py`
- `tests/ingest/test_vision_support.py`
- `tests/ingest/test_minhash_engine.py`
- `tests/ingest/test_minio_clean_store.py`
- `tests/ingest/test_temporal_constants.py`
- `tests/ingest/test_temporal_worker.py`
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
- `tests/ingest/test_impl_coverage.py` — for `impl.py` orchestrator edge cases
- `tests/ingest/test_cli_coverage.py` — for `cli.py` ingest function + main
- `tests/ingest/test_embedding_impl.py` — for `embedding/impl.py`
- `tests/ingest/test_cross_document_dedup.py` — for `embedding/nodes/cross_document_dedup.py`
- `tests/ingest/test_dedup_utils.py` — for `embedding/common/dedup_utils.py`
- `tests/ingest/test_temporal_activities.py` — for `temporal/activities.py`
- `tests/ingest/test_temporal_workflows.py` — for `temporal/workflows.py`
- `tests/ingest/test_common_utils.py` — for `common/utils.py`
- `tests/ingest/test_common_shared.py` — for `common/shared.py`
- `tests/ingest/test_colqwen_support.py` — for `support/colqwen.py`
- `tests/ingest/test_docling_support.py` — for `support/docling.py`
- `tests/ingest/test_visual_embedding_coverage.py` — for `embedding/nodes/visual_embedding.py`
- `tests/ingest/test_structure_detection_extra.py` — for `doc_processing/nodes/structure_detection.py`

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

### 1. Mock-based tests for CLI and orchestrator paths (highest priority — biggest gaps)
Tests using mocks for code that wires up multiple components. All mock test functions MUST be named `test_mock_*`:
- `cli.py` (44%, 55 missed) — mock `ingest_directory` for the `ingest()` function body, test IngestionConfig construction from params, `--file` / `--dir` path handling in `main()`
- `impl.py` (83%, 48 missed) — mock Phase 1/2 pipelines for orchestrator edge cases: error handling, skip logic, design warnings
- `embedding/impl.py` (50%, 8 missed) — mock `_GRAPH.invoke()` for `run_embedding_pipeline` error/success/deprecated-docling paths
- `lifecycle/gc.py` (65%, 82 missed) — remaining: `run_gc_cli()` full CLI path with mocked clients, `_open_*_client` helpers, `_emit_report` text/json paths, `_load_manifest`/`_save_manifest`
- `lifecycle/migration.py` (69%, 79 missed) — remaining: `_migrate_full_phase2()`, `_migrate_kg_reextract()`, CLI helpers, `_emit_migration_report()`

### 2. Mock-based tests for Temporal and dedup paths
- `temporal/activities.py` (64%, 31 missed) — mock embedder, db_client for `prewarm_worker_resources`, `_deserialise_config`, activity functions
- `temporal/workflows.py` (61%, 30 missed) — mock Temporal workflow execution for `IngestDocumentWorkflow.run()` and `IngestDirectoryWorkflow.run()`
- `temporal/worker.py` (69%, 22 missed) — mock Temporal Client.connect and Worker for `run_worker()` async paths
- `cross_document_dedup.py` (65%, 28 missed) — mock Weaviate for update_mode, fuzzy dedup tier 2, degraded path, `_replace_canonical`
- `dedup_utils.py` (72%, 23 missed) — mock Weaviate for exception handlers, `remove_source_document_refs`, `build_fuzzy_fingerprint`

### 3. Edge case tests for parser and support modules
- `parser_code.py` (60%, 68 missed) — chunk() body with real tree-sitter: function/class chunk building, KG relationship extraction (`_extract_kg_relationships`, `_walk_calls`), multi-line docstring extraction, import extraction for Rust/Go
- `docling.py` (69%, 58 missed) — mock Docling DocumentConverter for parse paths, page image extraction, chunk() with HybridChunker
- `colqwen.py` (78%, 28 missed) — mock ColQwen model for embedding paths
- `visual_embedding.py` (82%, 34 missed) — additional visual embedding node paths

### 4. Pure logic / edge case tests for common modules
- `common/shared.py` (85%, 14 missed) — edge cases in shared helpers
- `common/utils.py` (81%, 9 missed) — `sha256_path` chunked read, `decode_with_fallbacks` edge cases, `read_text_with_fallbacks`
- `lifecycle/sync.py` (88%, 8 missed) — edge cases in sync engine
- `lifecycle/validation.py` (82%, 35 missed) — remaining CLI helpers

## Constraints

- **Never modify production source code** — only test files are mutable
- **Mock naming convention** — any test function using mocks whose name contains "mock" must start with `test_mock_`
- **No new external dependencies** — use only `pytest`, `pytest-cov`, `unittest.mock`, and existing project deps
- **Test isolation** — new tests must not depend on external services being running
- **Backward compatibility** — existing 1548 tests must continue to pass at all times
- **One test TYPE per iteration** — pick one exploration direction per iteration, apply it to one or more files

## Stop conditions

- Coverage reaches 85% — success, stop
- 5 consecutive iterations with no coverage improvement — stop and report
- Correctness guard fails 3× in a row — stop, infrastructure broken
- 15 iterations reached — stop and report regardless of score
