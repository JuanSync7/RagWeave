# Project Navigation Protocol

This project uses **context-agent** for hierarchical context management.
Every source file has an `@summary` block at the top, and every directory has a `README.md`.

## How to Navigate

1. **Start here**: Read the root `README.md` for the project overview
2. **Find your target**: Use the directory map to identify which directory is relevant
3. **Read the directory README**: Each directory's `README.md` explains its contents and file relationships
4. **Check file summaries**: Each source file has an `@summary` comment block at the top — read it before diving into the full source
5. **Load source**: Only then read the full source files you need — and consider loading only the relevant sections

## Context Locations

| Context | Location | Purpose |
| --- | --- | --- |
| Project overview | `README.md` (root) | What this project does, architecture, directory map |
| Directory overview | `<dir>/README.md` | What a directory contains, file relationships |
| File summary | `@summary` block at top of each file | What a file does, key exports, dependencies |
| State ledger | `.context/state.yaml` | File hashes and timestamps for change tracking |
| Config | `.context/config.yaml` | Project-level context-agent settings |

## Summary Formats

### Source files — `@summary` block

Each source file has a comment block at the top:

```python
# @summary
# Brief description of what this file does.
# Exports: ClassName, function_name
# Deps: external_lib, internal.module
# @end-summary
```

### README.md — `<!-- @summary -->` block

Each directory's README.md starts with a promotable summary:

```markdown
<!-- @summary
Brief description of this directory's purpose.
@end-summary -->

# Directory Name
...
```

The `@summary` from each README.md is "promoted" into its parent directory's README.md,
creating a bottom-up chain of context from leaf directories to the project root.

## After Making Changes

When you modify source files:

1. The `@summary` blocks may become stale — this is expected
2. Run `context-agent update` to refresh affected summaries and README.md files
3. If you add a new directory, `context-agent update` will auto-generate its README.md

## Implementation Conventions (Code + Docs)

Use these conventions for all new implementation work (especially pipeline-style systems).

### 1) Python Style (PEP-oriented)

- Follow PEP 8 naming/layout conventions.
- Use module docstrings and function docstrings for all non-trivial modules/functions.
- Keep functions single-purpose and readable; avoid long "god functions".
- Add concise inline comments only where intent is not obvious.

### 2) File Structure and Separation of Concerns

- Prefer a thin public API/facade module (stable import surface).
- Keep orchestration/runtime flow separate from business logic.
- For workflow systems, use a top-level workflow composer file and stage/node-per-file implementations.
- Move reusable helpers to dedicated shared modules (avoid helper duplication across nodes).
- Keep shared type/state/config contracts in one canonical module.
- Use a predictable package layout in feature directories:
  - `schemas.py` for typed contracts (TypedDict/dataclass/pydantic),
  - `utils.py` for deterministic, side-effect-light helpers,
  - `common/` for cross-module contracts/helpers used by multiple subpackages.
- Standardize shared helpers in layers (RAGFlow-style, but domain-safe):
  - **Feature-local first**: keep helpers in `<feature>/common/` when only that feature uses them.
  - **Cross-domain promote**: move helpers to `src/common/` only when used by multiple features.
  - Keep feature-level `utils.py` facades stable so callers do not import deep internals.
- Keep backward-compatible aliases in facade modules when moving helpers between files.

Recommended pattern:

- `pipeline/__init__.py`: public exports only
- `pipeline_impl.py`: orchestration/runtime lifecycle
- `pipeline_workflow.py`: graph topology and routing
- `nodes/*.py`: one stage per file
- `pipeline_types.py`: state/config dataclasses and typed contracts
- `pipeline_shared.py`/`pipeline_llm.py`: ingestion-specific shared heuristics + LLM helpers
- `common/schemas.py` + `common/utils.py`: canonical cross-module contracts and deterministic utilities

API/server-oriented pattern:

- `schemas.py`: request/response models (endpoint contract surface)
- `utils.py`: facade for reusable request/response helper functions
- `common/schemas.py`: shared envelopes or cross-endpoint models
- `common/utils.py`: shared helpers (error payloads, request-id helpers, normalization)
- Keep route handlers thin; move reusable helper logic out of monolithic API modules.
- For major UX surfaces (for example web console), create a dedicated feature package
  (for example `server/console/`) with route/service separation and room for future growth.
- Co-locate static assets with the feature package (for example `server/console/static/`)
  and keep explicit fallback logic only when needed for migration compatibility.

CLI/UI parity contract:

- Treat CLI and UI as two clients of one product surface, not separate features.
- Any user-facing setting/command/state added to one interface must be reflected in the other
  in the same change set (or explicitly marked as intentionally interface-specific).
- Keep a single source of truth for shared interaction contracts:
  - shared request/response schemas in Python models,
  - shared command/config metadata in a reusable module consumed by both CLI and UI adapters.
- Do not duplicate business rules in interface layers; adapters should map to shared services/contracts.
- Hidden maintenance/debug commands must be explicitly scoped by interface and documented.

### 3) Configurability Requirements

- Behavior must be controlled by typed config (do not hardcode stage behavior).
- Optional stages must be toggleable via config flags.
- External dependencies (model/provider endpoints, chunking strategy, storage toggles) must be configurable.
- Add config validation checks for contradictory settings and fail fast with clear errors.

### 4) Testing Requirements

- Co-locate domain tests in a dedicated directory (for example, `tests/ingest/`).
- Add/maintain:
  - contract tests (state/config invariants),
  - workflow routing tests (optional branches),
  - regression tests for bug-prone helpers,
  - idempotency/incremental behavior tests when applicable.

### 5) Documentation Requirements

- Update directory `README.md` whenever structure or responsibilities change.
- Create/update an engineering guide in `docs/` for substantial subsystems.
- Document:
  - architecture and module layout,
  - stage-by-stage flow and decision points,
  - configuration keys and behavior toggles,
  - extension steps (how to add a stage),
  - troubleshooting and common failure modes.

### 6) Change Checklist (Before Finish)

- Code follows the separation pattern above.
- Public API exports remain stable.
- New/changed modules include `@summary` and docstrings.
- Tests pass for the affected subsystem.
- README and engineering docs are updated to match implementation.
- If files are moved/refactored, imports are updated and compatibility aliases are preserved or explicitly removed with migration notes.
- If CLI/UI behavior changed, parity was updated and verified for both surfaces.
