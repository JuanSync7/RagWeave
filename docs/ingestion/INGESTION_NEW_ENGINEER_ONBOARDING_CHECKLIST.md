# Ingestion New Engineer Onboarding Checklist

## Purpose

Use this one-page checklist to get productive in the ingestion subsystem on day one.

## Day 1 Setup

- [ ] Clone repo and create virtual environment.
- [ ] Install dependencies (`uv sync` or your team-standard install flow).
- [ ] Confirm local services needed for ingestion are reachable (Ollama, Weaviate path/runtime setup).
- [ ] Run ingestion tests: `uv run --with pytest python -m pytest tests/ingest`.
- [ ] Read these docs in order:
  1. `src/ingest/README.md`
  2. `docs/ingestion/INGESTION_PIPELINE_ENGINEERING_GUIDE.md`
  3. `docs/ingestion/DOCUMENT_PROCESSING_SPEC.md` (Document Processing requirements, FR-100–FR-589)
  4. `docs/ingestion/EMBEDDING_PIPELINE_SPEC.md` (Embedding requirements, FR-600–FR-1304)

## First Code Change Flow (Safe Path)

- [ ] Identify target stage/module:
  - workflow routing: `src/ingest/pipeline_workflow.py`
  - runtime orchestration: `src/ingest/pipeline_impl.py`
  - stage logic: `src/ingest/nodes/<stage>.py`
  - state/config contract: `src/ingest/pipeline_types.py`
  - shared helpers: `src/ingest/pipeline_shared.py` or `src/ingest/pipeline_llm.py`
- [ ] Keep API surface stable via `src/ingest/pipeline/__init__.py`.
- [ ] If adding/removing state fields, update `IngestState` in `pipeline_types.py`.
- [ ] If adding optional behavior, expose it through `IngestionConfig` (no hidden hardcoding).
- [ ] Add/adjust tests in `tests/ingest/` before finalizing.
- [ ] Run tests again and ensure no regression.
- [ ] Update docs:
  - `src/ingest/README.md` for structure/interface changes
  - engineering guide when flow or decisions change

## Common Gotchas

- [ ] **Manifest confusion:** unchanged files are skipped by hash; verify manifest entries before debugging node logic.
- [ ] **Identity confusion:** uniqueness is based on `source_key`/`source_id`/`source_uri`, not filename alone.
- [ ] **Optional stage not running:** check config flag and routing condition in `pipeline_workflow.py`.
- [ ] **LLM metadata/refactor empty or unstable:** validate Ollama connectivity and fallback path expectations.
- [ ] **Refactor provenance drift:** check `processed/refactor_mirror/*.mapping.json` and chunk `provenance_*` metadata before trusting citations.
- [ ] **Update mode stale vectors:** verify cleanup path in `embedding_storage_node`.
- [ ] **KG not persisted:** validate `build_kg` plus extraction/storage toggles together.

## Definition of Done (Ingestion PR)

- [ ] Code follows node-per-file + shared-library layout.
- [ ] New/changed modules include module/function docstrings and `@summary` blocks.
- [ ] `tests/ingest` passes locally.
- [ ] Affected README and docs are updated.
- [ ] Config changes are documented and validated.
