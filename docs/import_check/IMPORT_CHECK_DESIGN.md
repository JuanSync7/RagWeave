# Import Check Tool — Design Document

| Field | Value |
|-------|-------|
| **Document** | Import Check Tool Design Document |
| **Version** | 0.1 |
| **Status** | Draft |
| **Spec Reference** | `docs/superpowers/specs/2026-03-28-import-check-tool-sketch.md` (FR-100 through FR-700) |
| **Output Path** | `docs/import_check/IMPORT_CHECK_DESIGN.md` |
| **Produced by** | write-design-docs |
| **Task Decomposition Status** | [x] Approved |

> **Document Intent.** This document provides the technical design with task decomposition
> and contract-grade code appendix for the Import Check Tool specified in
> `docs/superpowers/specs/2026-03-28-import-check-tool-sketch.md`. Every task references
> the requirements it satisfies. Part B contract entries are consumed verbatim by the
> companion implementation docs.

> **Requirement derivation note.** The input spec is a design sketch without formal REQ-xxx
> identifiers. This design document derives functional requirements (FR-xxx) from each
> sketch feature. The mapping is documented in the traceability table (end of Part A).

### Derived Functional Requirements

| FR ID | Source (Sketch Section) | Description | Priority |
|-------|------------------------|-------------|----------|
| FR-101 | Components / inventory.py | Extract FunctionDef symbols from Python AST | MUST |
| FR-102 | Components / inventory.py | Extract ClassDef symbols from Python AST | MUST |
| FR-103 | Components / inventory.py | Extract module-level Assign symbols from Python AST | MUST |
| FR-104 | Components / inventory.py | Record symbol name + module path for each extracted symbol | MUST |
| FR-105 | Components / inventory.py | Build "before" inventory from `git show <ref>:<file>` | MUST |
| FR-106 | Components / inventory.py | Build "after" inventory from current filesystem files | MUST |
| FR-107 | Components / inventory.py | Only scan files changed according to `git diff --name-only` | MUST |
| FR-108 | Components / inventory.py | Respect `source_dirs` and `exclude_patterns` config | MUST |
| FR-201 | Components / differ.py | Detect symbol moves (same name, different module path) | MUST |
| FR-202 | Components / differ.py | Detect symbol renames (different name, same area) | MUST |
| FR-203 | Components / differ.py | Detect file splits (one source file -> many target files) | MUST |
| FR-204 | Components / differ.py | Detect file merges (many source files -> one target file) | MUST |
| FR-205 | Components / differ.py | Produce a structured migration map from inventory diff | MUST |
| FR-301 | Components / fixer.py | Rewrite `from x import y` statements using libcst | MUST |
| FR-302 | Components / fixer.py | Rewrite `import x` statements using libcst | MUST |
| FR-303 | Components / fixer.py | Rewrite aliased imports (`import x as y`, `from x import y as z`) | MUST |
| FR-304 | Components / fixer.py | Update `__all__` list entries | MUST |
| FR-305 | Components / fixer.py | Rewrite `mock.patch()` string arguments | MUST |
| FR-306 | Components / fixer.py | Rewrite `importlib.import_module()` string literals | MUST |
| FR-307 | Scope / In Scope | Handle single-assignment dataflow for variable-held string paths | SHOULD |
| FR-308 | Components / fixer.py | Preserve source formatting when rewriting (libcst) | MUST |
| FR-309 | Scope / In Scope | Handle lazy imports (inside functions) | MUST |
| FR-310 | Scope / In Scope | Handle `TYPE_CHECKING` imports | MUST |
| FR-311 | Scope / In Scope | Handle conditional imports (`try/except`) | MUST |
| FR-312 | Scope / Out of Scope | Flag truly dynamic string construction without fixing | SHOULD |
| FR-401 | Components / checker.py | Parse all `.py` files with `ast.parse()` for import verification | MUST |
| FR-402 | Components / checker.py | Verify target module exists on filesystem | MUST |
| FR-403 | Components / checker.py | Verify imported symbol is defined in target module | MUST |
| FR-404 | Components / checker.py | Detect encapsulation violations (external importing internal) | SHOULD |
| FR-405 | Components / checker.py | Encapsulation violations are report-only (not auto-fixed) | MUST |
| FR-406 | Components / checker.py | Output structured error list at ERROR log level | MUST |
| FR-407 | Key Decisions / #3 | No `importlib.import_module()` during smoke test (zero runtime cost) | MUST |
| FR-501 | Components / __init__.py | Expose `fix()` public API function | MUST |
| FR-502 | Components / __init__.py | Expose `check()` public API function | MUST |
| FR-503 | Components / __init__.py | Expose `run()` public API function (fix + check) | MUST |
| FR-504 | Components / __init__.py | Logging setup with configurable log level | MUST |
| FR-601 | Components / __main__.py | CLI entry point via `python -m import_check` | MUST |
| FR-602 | Components / __main__.py | Subcommands: `fix`, `check`, `run` | MUST |
| FR-603 | Components / __main__.py | CLI flags override pyproject.toml config | MUST |
| FR-604 | Configuration Surface | Human-readable output format (default) | MUST |
| FR-605 | Configuration Surface | JSON machine-parseable output format | MUST |
| FR-701 | Configuration Surface | `source_dirs` config: list of directories to scan | MUST |
| FR-702 | Configuration Surface | `exclude_patterns` config: glob patterns to exclude | MUST |
| FR-703 | Configuration Surface | `git_ref` config: git ref for "before" state | MUST |
| FR-704 | Configuration Surface | `encapsulation_check` config: toggle encapsulation detection | MUST |
| FR-705 | Configuration Surface | `output_format` config: "human" or "json" | MUST |
| FR-706 | Configuration Surface | `log_level` config: DEBUG, INFO, ERROR | MUST |
| FR-707 | Configuration Surface | Config from `pyproject.toml` under `[tool.import_check]` | MUST |
| FR-708 | Configuration Surface | Config from CLI flags (overrides pyproject.toml) | MUST |
| FR-709 | Configuration Surface | Config from programmatic API kwargs (overrides everything) | MUST |

---

# Part A: Task-Oriented Overview

## Phase 1 — Foundation: Types, Config, and Error Contracts

### Task 1.1: Schema Types and Shared Contracts

**Description:** Define all shared typed contracts used across the import_check tool: `SymbolEntry` (symbol name + module path + symbol kind), `SymbolInventory` (mapping of symbol names to entries), `MigrationEntry` (old location -> new location + change kind), `MigrationMap` (collection of migration entries), `FixResult` (per-file fix outcome), and `CheckResult` (per-import verification outcome). All types are dataclasses or TypedDicts with complete type annotations.

**Requirements Covered:** FR-104, FR-205, FR-308, FR-406

**Dependencies:** None

**Complexity:** S

**Subtasks:**
1. Create `import_check/schemas.py` with `SymbolKind` enum (`FUNCTION`, `CLASS`, `VARIABLE`).
2. Define `SymbolEntry` dataclass with `name`, `module_path`, `kind`, and `line_number` fields.
3. Define `SymbolInventory` as `dict[str, list[SymbolEntry]]` type alias (name -> list of entries, since names can appear in multiple modules).
4. Define `MigrationKind` enum (`MOVE`, `RENAME`, `SPLIT`, `MERGE`).
5. Define `MigrationEntry` dataclass with `symbol_name`, `old_module`, `new_module`, `old_name`, `new_name`, `kind` fields.
6. Define `MigrationMap` as `list[MigrationEntry]` type alias.
7. Define `FixResult` dataclass with `file_path`, `changes_made` (count), `entries_applied` (list of MigrationEntry refs).
8. Define `CheckResult` dataclass with `file_path`, `line_number`, `import_target`, `error_kind` (enum: `MODULE_NOT_FOUND`, `SYMBOL_NOT_DEFINED`, `ENCAPSULATION_VIOLATION`, `DYNAMIC_UNFIXABLE`), `message`.
9. Write `@summary` block and module docstring.

---

### Task 1.2: Configuration Dataclass and Loader

**Description:** Define the typed configuration dataclass with all behavior-controlling settings and implement a 3-layer config loader that reads from pyproject.toml, overlays CLI flags, and accepts programmatic kwargs. Includes validation for contradictory settings and fail-fast on invalid values.

**Requirements Covered:** FR-108, FR-701, FR-702, FR-703, FR-704, FR-705, FR-706, FR-707, FR-708, FR-709

**Dependencies:** None

**Complexity:** S

**Subtasks:**
1. Create `import_check/config.py` with frozen `ImportCheckConfig` dataclass.
2. Define fields: `source_dirs: list[str]` (default `["src", "server", "config"]`), `exclude_patterns: list[str]` (default `[".venv", "__pycache__", "node_modules"]`), `git_ref: str` (default `"HEAD"`), `encapsulation_check: bool` (default `True`), `output_format: str` (default `"human"`), `log_level: str` (default `"INFO"`).
3. Implement `load_config(**kwargs) -> ImportCheckConfig` that reads `[tool.import_check]` from `pyproject.toml`, overlays CLI flags, then overlays kwargs.
4. Implement validation: `output_format` must be `"human"` or `"json"`, `log_level` must be `"DEBUG"`, `"INFO"`, or `"ERROR"`, `source_dirs` must be non-empty. Raise `ConfigError` on invalid values.
5. Write `@summary` block and module docstring.

---

### Task 1.3: Exception Types

**Description:** Define all custom exception types for the import_check tool. Each exception documents when it is raised and provides structured context for error reporting.

**Requirements Covered:** FR-406, FR-504

**Dependencies:** None

**Complexity:** S

**Subtasks:**
1. Create `import_check/errors.py` with base `ImportCheckError(Exception)`.
2. Define `ConfigError(ImportCheckError)` — raised on invalid config values.
3. Define `GitError(ImportCheckError)` — raised when git commands fail (missing repo, invalid ref).
4. Define `InventoryError(ImportCheckError)` — raised when AST parsing fails on a source file.
5. Define `FixerError(ImportCheckError)` — raised when libcst rewriting encounters an unrecoverable state.
6. Write `@summary` block and module docstring.

---

## Phase 2 — Core Pipeline: Inventory and Diffing

### Task 2.1: Symbol Inventory Builder

**Description:** Build the AST-based symbol extractor that scans Python files and produces `SymbolEntry` records. Supports two source modes: filesystem (current state) and git-show (historical state via `git show <ref>:<file>`). Only processes files reported as changed by `git diff --name-only`. Respects `source_dirs` and `exclude_patterns` from config.

**Requirements Covered:** FR-101, FR-102, FR-103, FR-104, FR-105, FR-106, FR-107, FR-108

**Dependencies:** Task 1.1, Task 1.2, Task 1.3

**Complexity:** M

**Subtasks:**
1. Create `import_check/inventory.py` with module docstring and `@summary` block.
2. Implement `_extract_symbols(source: str, module_path: str) -> list[SymbolEntry]` — walk AST tree, extract `FunctionDef`, `AsyncFunctionDef`, `ClassDef` names and module-level `Assign` target names.
3. Implement `_get_changed_files(git_ref: str, source_dirs: list[str], exclude_patterns: list[str]) -> list[str]` — run `git diff --name-only <ref>` and filter by source_dirs/exclude_patterns.
4. Implement `_read_git_source(git_ref: str, file_path: str) -> str` — run `git show <ref>:<file>` and return source text. Raise `GitError` on failure.
5. Implement `_file_to_module_path(file_path: str) -> str` — convert filesystem path to dotted module path (e.g., `src/db/backend.py` -> `src.db.backend`).
6. Implement `build_inventory(config: ImportCheckConfig) -> tuple[SymbolInventory, SymbolInventory]` — public function returning `(old_inventory, new_inventory)`.

**Risks:** `git show` may fail on newly added files (no HEAD version). Mitigation: treat missing git source as empty inventory for that file (new file = all symbols are "added", not "moved").

**Testing Strategy:** Unit test `_extract_symbols` with known Python source strings containing functions, classes, and assignments. Test `_file_to_module_path` with edge cases (nested, `__init__.py`). Mock `subprocess` for git commands.

---

### Task 2.2: Inventory Differ

**Description:** Diff two `SymbolInventory` objects to produce a `MigrationMap` detecting moves, renames, splits, and merges at the symbol level. Implements the core detection heuristics: same name at different path = move; different name in same area = rename candidate; one old file's symbols scattered across multiple new files = split; multiple old files' symbols concentrated in one new file = merge.

**Requirements Covered:** FR-201, FR-202, FR-203, FR-204, FR-205

**Dependencies:** Task 1.1

**Complexity:** M

**Subtasks:**
1. Create `import_check/differ.py` with module docstring and `@summary` block.
2. Implement `_detect_moves(old: SymbolInventory, new: SymbolInventory) -> list[MigrationEntry]` — for each symbol name present in both inventories, if module path changed, emit a `MOVE` entry.
3. Implement `_detect_renames(old: SymbolInventory, new: SymbolInventory, moves: list[MigrationEntry]) -> list[MigrationEntry]` — for symbols that disappeared from old but a new symbol appeared in the same module, emit a `RENAME` candidate.
4. Implement `_detect_splits_and_merges(old: SymbolInventory, new: SymbolInventory, moves: list[MigrationEntry]) -> list[MigrationEntry]` — analyze the move set: if symbols from one old module scattered to multiple new modules, tag as `SPLIT`; if symbols from multiple old modules concentrated in one new module, tag as `MERGE`.
5. Implement `diff_inventories(old: SymbolInventory, new: SymbolInventory) -> MigrationMap` — public function that orchestrates detection steps and returns the combined, deduplicated migration map.

**Risks:** Rename detection is inherently heuristic (no guaranteed correct answer when a symbol disappears and a new one appears). Mitigation: rename candidates are lower-confidence and downstream the smoke test (checker) validates whether the fix is correct; unfixed cases become structured errors for LLM consumption.

**Testing Strategy:** Unit test each detection function with crafted inventory pairs: simple move (function `foo` from `a.b` to `a.c`), rename (`foo` disappears from `a.b`, `bar` appears in `a.b`), split (3 functions from `utils.py` scattered to 3 files), merge (3 files' functions all land in `combined.py`).

---

## Phase 3 — Fix and Check

### Task 3.1: Import Fixer (libcst)

**Description:** Build the libcst-based import rewriter that applies `MigrationMap` entries to all Python files in the scanned directories. Handles all import styles: `from x import y`, `import x`, aliased imports, `__all__` list entries, `mock.patch()` string arguments, `importlib.import_module()` string literals, and single-assignment dataflow for variable-held string paths. Preserves source formatting.

**Requirements Covered:** FR-301, FR-302, FR-303, FR-304, FR-305, FR-306, FR-307, FR-308, FR-309, FR-310, FR-311, FR-312

**Dependencies:** Task 1.1, Task 1.2, Task 2.2

**Complexity:** M

**Subtasks:**
1. Create `import_check/fixer.py` with module docstring and `@summary` block.
2. Implement `ImportRewriter(cst.CSTTransformer)` class that receives a `MigrationMap` and rewrites `ImportFrom` and `Import` nodes.
3. Add `visit_ImportFrom` / `leave_ImportFrom` methods to handle `from x import y` rewrites, including aliased imports.
4. Add `visit_Import` / `leave_Import` methods to handle `import x` and `import x as y` rewrites.
5. Implement `__all__` rewriting: detect `Assign` nodes where target is `__all__` and rewrite string elements in the list.
6. Implement string-reference rewriting: detect `mock.patch()` and `importlib.import_module()` `Call` nodes and rewrite string literal arguments matching migration map entries.
7. Implement single-assignment dataflow: within function scope, track `name = "dotted.path"` assignments and rewrite the string if the variable is used in `importlib.import_module(name)`.
8. Implement `fix_file(file_path: str, migration_map: MigrationMap) -> FixResult` — parse file with libcst, apply transformer, write back if changed.
9. Implement `fix_all(config: ImportCheckConfig, migration_map: MigrationMap) -> list[FixResult]` — public function that iterates all Python files in scanned directories.
10. For truly dynamic string construction (f-strings, concatenation), emit a `DYNAMIC_UNFIXABLE` warning in the `FixResult` instead of attempting a rewrite.

**Risks:** libcst parsing may fail on files with syntax errors or Python 2 remnants. Mitigation: wrap `cst.parse_module()` in try/except and skip unparseable files with a warning, recording them in the result. Single-assignment dataflow is intentionally bounded to same-function-scope to avoid complexity explosion.

**Testing Strategy:** Unit test each rewrite case individually: from-import, bare import, alias, `__all__`, `mock.patch()`, `importlib.import_module()`, dataflow. Integration test with a temp directory of Python files and a known migration map, verifying file contents after fix.

---

### Task 3.2: Smoke Test Checker

**Description:** Build the verification layer that walks all `.py` files, parses imports with `ast`, and verifies: (1) target module exists on filesystem, (2) imported symbol is defined in target module. Optionally detects encapsulation violations where external code imports internal modules instead of public `__init__.py` surfaces. All checks are zero-cost (no `importlib.import_module()` calls). Produces structured `CheckResult` list.

**Requirements Covered:** FR-401, FR-402, FR-403, FR-404, FR-405, FR-406, FR-407

**Dependencies:** Task 1.1, Task 1.2

**Complexity:** S

**Subtasks:**
1. Create `import_check/checker.py` with module docstring and `@summary` block.
2. Implement `_module_path_to_file(module_path: str, source_dirs: list[str]) -> str | None` — resolve a dotted module path to a filesystem path, checking for both `module.py` and `module/__init__.py`.
3. Implement `_symbol_defined_in_module(symbol_name: str, file_path: str) -> bool` — parse the file with `ast` and check if the symbol is defined (FunctionDef, ClassDef, Assign, or `__all__` entry).
4. Implement `_check_encapsulation(import_module: str, importing_file: str) -> CheckResult | None` — if `encapsulation_check` is enabled, detect imports that bypass `__init__.py` public surfaces.
5. Implement `check_imports(config: ImportCheckConfig) -> list[CheckResult]` — public function that walks all `.py` files, extracts imports, and runs all checks. Log errors at ERROR level.

**Testing Strategy:** Unit test `_module_path_to_file` with package and module paths. Test `_symbol_defined_in_module` with files containing various definition types. Test encapsulation detection with a mock package structure.

---

## Phase 4 — Public API and CLI

### Task 4.1: Public API Facade

**Description:** Build the thin facade module that exposes the three public functions (`fix()`, `check()`, `run()`) and orchestrates the full pipeline: config loading -> inventory building -> diffing -> fixing -> checking. Includes logging setup with configurable verbosity. Defines `__all__` for the stable import surface.

**Requirements Covered:** FR-501, FR-502, FR-503, FR-504

**Dependencies:** Task 2.1, Task 2.2, Task 3.1, Task 3.2

**Complexity:** S

**Subtasks:**
1. Create `import_check/__init__.py` with module docstring and `@summary` block.
2. Implement `_setup_logging(log_level: str) -> None` — configure the `import_check` logger with the specified level.
3. Implement `fix(**kwargs) -> list[FixResult]` — load config, build inventories, diff, run fixer. Return fix results.
4. Implement `check(**kwargs) -> list[CheckResult]` — load config, run checker. Return check results.
5. Implement `run(**kwargs) -> tuple[list[FixResult], list[CheckResult]]` — run `fix()` then `check()`. Return both result sets.
6. Define `__all__ = ["fix", "check", "run", "ImportCheckConfig", "FixResult", "CheckResult"]`.

---

### Task 4.2: CLI Entry Point

**Description:** Build the CLI entry point for `python -m import_check [fix|check|run]` with argument parsing. CLI flags map to config fields and override pyproject.toml values. Supports human-readable (default) and JSON output formats. Exit code 0 on success (no errors found), exit code 1 on errors found, exit code 2 on tool failure.

**Requirements Covered:** FR-601, FR-602, FR-603, FR-604, FR-605, FR-708

**Dependencies:** Task 4.1

**Complexity:** S

**Subtasks:**
1. Create `import_check/__main__.py` with module docstring and `@summary` block.
2. Implement argument parser with `fix`, `check`, `run` subcommands.
3. Add CLI flags: `--source-dirs`, `--exclude`, `--git-ref`, `--encapsulation-check/--no-encapsulation-check`, `--format {human,json}`, `--log-level {DEBUG,INFO,ERROR}`.
4. Implement `_format_human(fix_results, check_results) -> str` — human-readable output.
5. Implement `_format_json(fix_results, check_results) -> str` — JSON output.
6. Wire subcommand dispatch to facade functions, pass CLI args as kwargs, format output, set exit code.

---

## Task Dependency Graph

```
Phase 1 (Foundation)               Phase 2 (Core)         Phase 3 (Fix/Check)     Phase 4 (API/CLI)

┌──────────────────┐
│  Task 1.1        │ [CRITICAL]
│  Schema Types    │───────────────────────────────────────────────────────────────────┐
│                  │──────────────┬──────────────┐                                     │
└──────────────────┘              │              │                                     │
         │                       │              │                                     │
┌──────────────────┐              │              │                                     │
│  Task 1.2        │              │              │                                     │
│  Config Loader   │──────────────┤              │                                     │
└──────────────────┘              │              │                                     │
         │                       │              │                                     │
┌──────────────────┐              │              │                                     │
│  Task 1.3        │              │              │                                     │
│  Error Types     │──────────────┤              │                                     │
└──────────────────┘              │              │                                     │
                                 │              │                                     │
                    ┌─────────────▼──┐   ┌──────▼───────────┐                         │
                    │  Task 2.1      │   │  Task 2.2        │ [CRITICAL]              │
                    │  Inventory     │   │  Differ          │                         │
                    │  Builder       │   │                  │                         │
                    └─────────────┬──┘   └──────┬───────────┘                         │
                                 │              │                                     │
                                 │    ┌─────────▼────────┐   ┌────────────────────┐   │
                                 │    │  Task 3.1        │   │  Task 3.2          │   │
                                 │    │  Import Fixer    │   │  Smoke Checker     │◄──┘
                                 │    │  [CRITICAL]      │   │                    │
                                 │    └─────────┬────────┘   └────────┬───────────┘
                                 │              │                     │
                                 └──────────────┼─────────────────────┤
                                                │                     │
                                       ┌────────▼─────────────────────▼──┐
                                       │  Task 4.1                       │
                                       │  Public API Facade [CRITICAL]   │
                                       └────────────────┬────────────────┘
                                                        │
                                                        ▼
                                               ┌─────────────────┐
                                               │  Task 4.2       │
                                               │  CLI Entry Point│
                                               └─────────────────┘

[CRITICAL] path: Task 1.1 → Task 2.2 → Task 3.1 → Task 4.1 → Task 4.2
```

---

## Task-to-Requirement Mapping

| Task | Requirements Covered |
|------|---------------------|
| Task 1.1 | FR-104, FR-205, FR-308, FR-406 |
| Task 1.2 | FR-108, FR-701, FR-702, FR-703, FR-704, FR-705, FR-706, FR-707, FR-708, FR-709 |
| Task 1.3 | FR-406, FR-504 |
| Task 2.1 | FR-101, FR-102, FR-103, FR-104, FR-105, FR-106, FR-107, FR-108 |
| Task 2.2 | FR-201, FR-202, FR-203, FR-204, FR-205 |
| Task 3.1 | FR-301, FR-302, FR-303, FR-304, FR-305, FR-306, FR-307, FR-308, FR-309, FR-310, FR-311, FR-312 |
| Task 3.2 | FR-401, FR-402, FR-403, FR-404, FR-405, FR-406, FR-407 |
| Task 4.1 | FR-501, FR-502, FR-503, FR-504 |
| Task 4.2 | FR-601, FR-602, FR-603, FR-604, FR-605, FR-708 |

### Coverage Verification

Every FR from FR-101 through FR-709 is assigned to at least one task. Every task references at least one FR. No orphan tasks or uncovered requirements.

---

# Part B: Code Appendix

## B.1: Schema Types — Contract

Defines all shared typed contracts used across the import_check tool. Consumed by every task as the canonical type surface.

**Tasks:** Task 1.1, Task 2.1, Task 2.2, Task 3.1, Task 3.2, Task 4.1
**Requirements:** FR-104, FR-205, FR-308, FR-406
**Type:** Contract (exact — copied to implementation docs Phase 0)

```python
# import_check/schemas.py
"""Shared typed contracts for the import_check tool.

All types used across modules are defined here. This is the single
source of truth for data structures flowing through the pipeline.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field


class SymbolKind(enum.Enum):
    """Classification of an extracted Python symbol."""

    FUNCTION = "function"       # FunctionDef or AsyncFunctionDef
    CLASS = "class"             # ClassDef
    VARIABLE = "variable"       # Module-level Assign target


@dataclass(frozen=True)
class SymbolEntry:
    """A single symbol extracted from a Python module.

    Attributes:
        name: The symbol name (e.g., 'MyClass', 'my_function').
        module_path: Dotted module path (e.g., 'src.db.backend').  # FR-104
        kind: Classification of the symbol.
        line_number: Line number where the symbol is defined (1-based).
    """

    name: str                   # FR-104
    module_path: str            # FR-104
    kind: SymbolKind            # FR-104
    line_number: int            # FR-104


# Type alias: symbol name -> list of entries (name may appear in multiple modules)
SymbolInventory = dict[str, list[SymbolEntry]]


class MigrationKind(enum.Enum):
    """Classification of a detected symbol change."""

    MOVE = "move"               # Same name, different module path (FR-201)
    RENAME = "rename"           # Different name, same area (FR-202)
    SPLIT = "split"             # One source module -> many targets (FR-203)
    MERGE = "merge"             # Many source modules -> one target (FR-204)


@dataclass(frozen=True)
class MigrationEntry:
    """A single detected symbol migration.

    Attributes:
        symbol_name: Original symbol name in the old inventory.
        old_module: Dotted module path in the old inventory.  # FR-205
        new_module: Dotted module path in the new inventory.  # FR-205
        old_name: Original symbol name (may differ from symbol_name for renames).
        new_name: New symbol name (may differ from old_name for renames).
        kind: Type of migration detected.  # FR-205
    """

    symbol_name: str            # FR-205
    old_module: str             # FR-205
    new_module: str             # FR-205
    old_name: str               # FR-205
    new_name: str               # FR-205
    kind: MigrationKind         # FR-205


# Type alias: ordered list of migration entries
MigrationMap = list[MigrationEntry]


class ErrorKind(enum.Enum):
    """Classification of a check error."""

    MODULE_NOT_FOUND = "module_not_found"               # FR-402
    SYMBOL_NOT_DEFINED = "symbol_not_defined"            # FR-403
    ENCAPSULATION_VIOLATION = "encapsulation_violation"  # FR-404
    DYNAMIC_UNFIXABLE = "dynamic_unfixable"              # FR-312


@dataclass(frozen=True)
class CheckResult:
    """Result of a single import verification check.

    Attributes:
        file_path: Path to the file containing the import.
        line_number: Line number of the import statement (1-based).
        import_target: The full import path being checked.
        error_kind: Classification of the error.  # FR-406
        message: Human-readable description of the error.  # FR-406
    """

    file_path: str              # FR-406
    line_number: int            # FR-406
    import_target: str          # FR-406
    error_kind: ErrorKind       # FR-406
    message: str                # FR-406


@dataclass(frozen=True)
class FixResult:
    """Result of applying migration fixes to a single file.

    Attributes:
        file_path: Path to the file that was (or would be) modified.
        changes_made: Number of import statements rewritten.  # FR-308
        entries_applied: Migration entries that were applied to this file.
        warnings: Non-fatal issues encountered (e.g., dynamic strings).  # FR-312
    """

    file_path: str              # FR-308
    changes_made: int           # FR-308
    entries_applied: list[MigrationEntry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)  # FR-312
```

**Key design decisions:**
- Frozen dataclasses prevent accidental mutation of pipeline data flowing between stages.
- `SymbolInventory` is `dict[str, list[SymbolEntry]]` (not `dict[str, SymbolEntry]`) because the same name can appear in multiple modules — critical for detecting moves.
- `MigrationEntry` carries both `old_name` and `new_name` to support rename detection, even though they are identical for moves.
- `ErrorKind.DYNAMIC_UNFIXABLE` is shared between fixer (which flags it) and checker (which reports it), unifying the error taxonomy.

---

## B.2: Configuration Dataclass — Contract

Defines the typed configuration surface and loader. Consumed by Task 1.2 (implementation), all pipeline tasks (as input).

**Tasks:** Task 1.2, Task 2.1, Task 3.1, Task 3.2, Task 4.1, Task 4.2
**Requirements:** FR-108, FR-701 through FR-709
**Type:** Contract (exact — copied to implementation docs Phase 0)

```python
# import_check/config.py
"""Configuration loading and validation for the import_check tool.

Supports 3-layer config: pyproject.toml -> CLI flags -> programmatic kwargs.
Each layer overrides the previous. Validation fails fast on invalid values.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from import_check.errors import ConfigError


_VALID_OUTPUT_FORMATS = {"human", "json"}
_VALID_LOG_LEVELS = {"DEBUG", "INFO", "ERROR"}


@dataclass(frozen=True)
class ImportCheckConfig:
    """Typed configuration for the import_check tool.

    All behavior is controlled through this config. No hardcoded values
    in pipeline modules.

    Attributes:
        source_dirs: Directories to scan for Python files.  # FR-701
        exclude_patterns: Glob patterns to exclude from scanning.  # FR-702
        git_ref: Git ref for the "before" state.  # FR-703
        encapsulation_check: Enable encapsulation violation detection.  # FR-704
        output_format: Output format — "human" or "json".  # FR-705
        log_level: Logging verbosity — "DEBUG", "INFO", or "ERROR".  # FR-706
    """

    source_dirs: tuple[str, ...] = ("src", "server", "config")  # FR-701
    exclude_patterns: tuple[str, ...] = (".venv", "__pycache__", "node_modules")  # FR-702
    git_ref: str = "HEAD"                         # FR-703
    encapsulation_check: bool = True              # FR-704
    output_format: str = "human"                  # FR-705
    log_level: str = "INFO"                       # FR-706


def _read_pyproject(path: Path | None = None) -> dict[str, Any]:
    """Read [tool.import_check] section from pyproject.toml.

    Args:
        path: Explicit path to pyproject.toml. If None, searches cwd upward.

    Returns:
        Dict of config values from pyproject.toml, or empty dict if not found.

    Raises:
        ConfigError: If pyproject.toml exists but contains invalid TOML.
    """
    raise NotImplementedError("Task 1.2")


def _validate_config(config: ImportCheckConfig) -> None:
    """Validate config values and raise on contradictory/invalid settings.

    Args:
        config: The config to validate.

    Raises:
        ConfigError: If output_format not in {"human", "json"},
            log_level not in {"DEBUG", "INFO", "ERROR"},
            or source_dirs is empty.
    """
    raise NotImplementedError("Task 1.2")


def load_config(
    cli_overrides: dict[str, Any] | None = None,
    **kwargs: Any,
) -> ImportCheckConfig:
    """Load configuration with 3-layer override: pyproject.toml -> CLI -> kwargs.

    Args:
        cli_overrides: Dict of CLI flag values (only non-None values override).
            Maps to FR-708.
        **kwargs: Programmatic API overrides (highest priority). Maps to FR-709.

    Returns:
        Validated ImportCheckConfig instance.

    Raises:
        ConfigError: If resulting config fails validation.
    """
    raise NotImplementedError("Task 1.2")
```

**Key design decisions:**
- Frozen dataclass with tuple fields (not list) ensures config immutability after construction.
- `_read_pyproject` searches upward from cwd to find `pyproject.toml`, matching standard Python tooling behavior.
- Validation is a separate function (not `__post_init__`) because the 3-layer merge produces a dict first, then constructs the dataclass, then validates — `__post_init__` would validate before overrides are applied.
- `cli_overrides` is a separate dict (not merged into kwargs) to preserve the explicit 3-layer precedence model.

---

## B.3: Exception Types — Contract

Defines all custom exceptions for the import_check tool. Each documents when it is raised.

**Tasks:** Task 1.3
**Requirements:** FR-406, FR-504
**Type:** Contract (exact — copied to implementation docs Phase 0)

```python
# import_check/errors.py
"""Custom exception types for the import_check tool.

All exceptions inherit from ImportCheckError. Each exception documents
the conditions under which it is raised and provides structured context.
"""
from __future__ import annotations


class ImportCheckError(Exception):
    """Base exception for all import_check errors.

    Raised: never directly — always use a subclass.
    """


class ConfigError(ImportCheckError):
    """Raised when configuration is invalid.

    Raised when:
    - pyproject.toml contains invalid TOML syntax
    - output_format is not "human" or "json"
    - log_level is not "DEBUG", "INFO", or "ERROR"
    - source_dirs is empty
    - Contradictory settings are detected
    """


class GitError(ImportCheckError):
    """Raised when a git operation fails.

    Raised when:
    - Current directory is not a git repository
    - Specified git_ref does not exist
    - `git show` fails for a specific file at a ref
    - `git diff` fails to list changed files

    Attributes:
        command: The git command that failed.
        returncode: The process return code.
        stderr: The stderr output from git.
    """

    def __init__(
        self,
        message: str,
        command: str = "",
        returncode: int = 1,
        stderr: str = "",
    ) -> None:
        super().__init__(message)
        self.command = command
        self.returncode = returncode
        self.stderr = stderr


class InventoryError(ImportCheckError):
    """Raised when AST parsing fails on a source file.

    Raised when:
    - A Python file has invalid syntax that ast.parse() cannot handle
    - File encoding cannot be determined

    Attributes:
        file_path: Path to the file that failed to parse.
    """

    def __init__(self, message: str, file_path: str = "") -> None:
        super().__init__(message)
        self.file_path = file_path


class FixerError(ImportCheckError):
    """Raised when libcst rewriting encounters an unrecoverable state.

    Raised when:
    - libcst.parse_module() fails on a file
    - A CST transformation produces invalid Python

    Attributes:
        file_path: Path to the file that failed.
    """

    def __init__(self, message: str, file_path: str = "") -> None:
        super().__init__(message)
        self.file_path = file_path
```

**Key design decisions:**
- `GitError` carries structured context (command, returncode, stderr) for debugging — git failures are the most common operational issue.
- `InventoryError` and `FixerError` carry `file_path` so error handlers can report which file caused the problem.
- Base `ImportCheckError` is never raised directly — enforced by convention (no `raise ImportCheckError` in any module).

---

## B.4: Inventory Builder Function Stubs — Contract

Defines the public and private function interfaces for the inventory module.

**Tasks:** Task 2.1
**Requirements:** FR-101 through FR-108
**Type:** Contract (exact — copied to implementation docs Phase 0)

```python
# import_check/inventory.py
"""Symbol inventory builder using Python AST.

Extracts FunctionDef, ClassDef, and module-level Assign symbols from Python
source files. Supports both filesystem (current state) and git-show (historical
state) sources. Only processes files changed according to git diff.
"""
from __future__ import annotations

from import_check.config import ImportCheckConfig
from import_check.errors import GitError, InventoryError
from import_check.schemas import SymbolEntry, SymbolInventory


def _extract_symbols(source: str, module_path: str) -> list[SymbolEntry]:
    """Extract all top-level symbols from Python source using AST.

    Walks the AST tree and extracts:
    - FunctionDef and AsyncFunctionDef names (FR-101)
    - ClassDef names (FR-102)
    - Module-level Assign target names (FR-103)

    Args:
        source: Python source code as a string.
        module_path: Dotted module path for this source (e.g., 'src.db.backend').

    Returns:
        List of SymbolEntry objects, one per extracted symbol.

    Raises:
        InventoryError: If ast.parse() fails on the source.
    """
    raise NotImplementedError("Task 2.1")


def _get_changed_files(
    git_ref: str,
    source_dirs: tuple[str, ...],
    exclude_patterns: tuple[str, ...],
) -> list[str]:
    """Get list of Python files changed since the given git ref.

    Runs `git diff --name-only <ref>` and filters results by source_dirs
    and exclude_patterns (FR-107, FR-108).

    Args:
        git_ref: Git ref for comparison (e.g., 'HEAD', commit SHA).
        source_dirs: Directories to include.
        exclude_patterns: Glob patterns to exclude.

    Returns:
        List of relative file paths (e.g., ['src/db/backend.py']).

    Raises:
        GitError: If git diff command fails.
    """
    raise NotImplementedError("Task 2.1")


def _read_git_source(git_ref: str, file_path: str) -> str:
    """Read file content at a specific git ref.

    Runs `git show <ref>:<file>` to retrieve historical file content (FR-105).

    Args:
        git_ref: Git ref (e.g., 'HEAD').
        file_path: Relative path to the file.

    Returns:
        File content as a string.

    Raises:
        GitError: If the file does not exist at the given ref, or git show fails.
    """
    raise NotImplementedError("Task 2.1")


def _file_to_module_path(file_path: str) -> str:
    """Convert a filesystem path to a dotted module path.

    Handles both regular modules and package __init__.py files.
    Examples:
        'src/db/backend.py' -> 'src.db.backend'
        'src/db/__init__.py' -> 'src.db'

    Args:
        file_path: Relative path to a Python file.

    Returns:
        Dotted module path string.
    """
    raise NotImplementedError("Task 2.1")


def build_inventory(
    config: ImportCheckConfig,
) -> tuple[SymbolInventory, SymbolInventory]:
    """Build old and new symbol inventories from changed files.

    For each changed file (FR-107):
    - Old inventory: read source via git show (FR-105), extract symbols
    - New inventory: read current file (FR-106), extract symbols

    Newly added files (no git history) produce entries only in the new inventory.
    Deleted files produce entries only in the old inventory.

    Args:
        config: Tool configuration with git_ref, source_dirs, exclude_patterns.

    Returns:
        Tuple of (old_inventory, new_inventory).

    Raises:
        GitError: If git operations fail.
        InventoryError: If AST parsing fails and cannot be recovered.
    """
    raise NotImplementedError("Task 2.1")
```

**Key design decisions:**
- `_extract_symbols` takes raw source string (not file path) so it can be used with both filesystem reads and git-show output without duplication.
- `_file_to_module_path` is a separate utility (not inlined) because it is used in both inventory building and the checker module.
- `build_inventory` returns a tuple rather than a custom container to keep the interface simple and compatible with destructuring.

---

## B.5: Differ Function Stubs — Contract

Defines the public and private function interfaces for the differ module.

**Tasks:** Task 2.2
**Requirements:** FR-201 through FR-205
**Type:** Contract (exact — copied to implementation docs Phase 0)

```python
# import_check/differ.py
"""Inventory differ — detects moves, renames, splits, and merges.

Compares old and new SymbolInventory objects to produce a MigrationMap
describing how symbols have moved between modules during refactoring.
"""
from __future__ import annotations

from import_check.schemas import (
    MigrationEntry,
    MigrationMap,
    SymbolInventory,
)


def _detect_moves(
    old: SymbolInventory,
    new: SymbolInventory,
) -> list[MigrationEntry]:
    """Detect symbols that moved between modules (same name, different path).

    A symbol is a MOVE when it exists in both inventories with the same name
    but at a different module path (FR-201).

    Args:
        old: Symbol inventory from the old (git ref) state.
        new: Symbol inventory from the new (current) state.

    Returns:
        List of MigrationEntry objects with kind=MOVE.
    """
    raise NotImplementedError("Task 2.2")


def _detect_renames(
    old: SymbolInventory,
    new: SymbolInventory,
    moves: list[MigrationEntry],
) -> list[MigrationEntry]:
    """Detect symbols that were renamed within the same module area.

    A symbol is a RENAME candidate when it disappeared from a module in the old
    inventory and a new symbol appeared in the same module in the new inventory,
    and neither was already classified as a move (FR-202).

    Args:
        old: Symbol inventory from the old state.
        new: Symbol inventory from the new state.
        moves: Already-detected moves (to exclude from rename candidates).

    Returns:
        List of MigrationEntry objects with kind=RENAME.
    """
    raise NotImplementedError("Task 2.2")


def _detect_splits_and_merges(
    old: SymbolInventory,
    new: SymbolInventory,
    moves: list[MigrationEntry],
) -> list[MigrationEntry]:
    """Detect file splits and merges from the move pattern.

    A SPLIT is when symbols from one old module scattered to multiple new
    modules (FR-203). A MERGE is when symbols from multiple old modules
    concentrated in one new module (FR-204).

    This function re-tags existing MOVE entries as SPLIT or MERGE based on
    the fan-out/fan-in pattern. It does not create new entries.

    Args:
        old: Symbol inventory from the old state.
        new: Symbol inventory from the new state.
        moves: Already-detected moves to analyze for split/merge patterns.

    Returns:
        List of MigrationEntry objects with kind=SPLIT or kind=MERGE
        (replaces the corresponding MOVE entries).
    """
    raise NotImplementedError("Task 2.2")


def diff_inventories(
    old: SymbolInventory,
    new: SymbolInventory,
) -> MigrationMap:
    """Diff two symbol inventories to produce a migration map.

    Orchestrates detection in order: moves first, then renames (excluding
    already-moved symbols), then split/merge re-tagging (FR-205).

    Args:
        old: Symbol inventory from the old (git ref) state.
        new: Symbol inventory from the new (current) state.

    Returns:
        Deduplicated MigrationMap covering all detected changes.
    """
    raise NotImplementedError("Task 2.2")
```

**Key design decisions:**
- Detection runs in a fixed order (moves -> renames -> splits/merges) because each step depends on the previous: renames must exclude already-detected moves, and split/merge analysis operates on the move set.
- `_detect_splits_and_merges` re-tags MOVE entries rather than creating new entries, avoiding double-counting.
- `diff_inventories` is the only public function — all detection helpers are private.

---

## B.6: Fixer Function Stubs — Contract

Defines the public function interfaces for the fixer module. The libcst transformer class is in a pattern entry (B.9) because its internal visit/leave methods are implementation detail.

**Tasks:** Task 3.1
**Requirements:** FR-301 through FR-312
**Type:** Contract (exact — copied to implementation docs Phase 0)

```python
# import_check/fixer.py
"""libcst-based import rewriter.

Applies MigrationMap entries to Python files, rewriting import statements,
__all__ lists, mock.patch() strings, importlib.import_module() strings,
and single-assignment string paths. Preserves source formatting.
"""
from __future__ import annotations

from import_check.config import ImportCheckConfig
from import_check.errors import FixerError
from import_check.schemas import FixResult, MigrationMap


def fix_file(file_path: str, migration_map: MigrationMap) -> FixResult:
    """Apply migration fixes to a single Python file.

    Parses the file with libcst, applies the ImportRewriter transformer,
    and writes back if any changes were made (FR-308). Detects and flags
    dynamic string constructions that cannot be automatically fixed (FR-312).

    Args:
        file_path: Absolute or relative path to the Python file.
        migration_map: Migration entries to apply.

    Returns:
        FixResult with the number of changes made and entries applied.

    Raises:
        FixerError: If libcst cannot parse the file or produces invalid output.
    """
    raise NotImplementedError("Task 3.1")


def fix_all(
    config: ImportCheckConfig,
    migration_map: MigrationMap,
) -> list[FixResult]:
    """Apply migration fixes to all Python files in configured directories.

    Iterates all .py files in source_dirs (respecting exclude_patterns),
    applies fix_file to each, and collects results.

    Args:
        config: Tool configuration for directory scanning.
        migration_map: Migration entries to apply.

    Returns:
        List of FixResult objects, one per file that was processed.
        Files with no applicable changes have changes_made=0.
    """
    raise NotImplementedError("Task 3.1")
```

---

## B.7: Checker Function Stubs — Contract

Defines the public and private function interfaces for the checker module.

**Tasks:** Task 3.2
**Requirements:** FR-401 through FR-407
**Type:** Contract (exact — copied to implementation docs Phase 0)

```python
# import_check/checker.py
"""Smoke test checker — zero-cost import verification.

Walks all Python files, parses imports with ast, and verifies:
1. Target module exists on filesystem
2. Imported symbol is defined in target module
3. (Optional) Encapsulation violations — report only

No importlib.import_module() calls — all checks are static.
"""
from __future__ import annotations

from import_check.config import ImportCheckConfig
from import_check.schemas import CheckResult


def _module_path_to_file(
    module_path: str,
    source_dirs: tuple[str, ...],
) -> str | None:
    """Resolve a dotted module path to a filesystem path.

    Checks for both module.py and module/__init__.py variants (FR-402).

    Args:
        module_path: Dotted path (e.g., 'src.db.backend').
        source_dirs: Directories to search for the module.

    Returns:
        Filesystem path if found, None otherwise.
    """
    raise NotImplementedError("Task 3.2")


def _symbol_defined_in_module(symbol_name: str, file_path: str) -> bool:
    """Check if a symbol is defined in a Python file using AST.

    Parses the file and checks for FunctionDef, ClassDef, Assign,
    or __all__ entry matching the symbol name (FR-403).

    Args:
        symbol_name: Name of the symbol to find.
        file_path: Path to the Python file.

    Returns:
        True if symbol is defined, False otherwise.
    """
    raise NotImplementedError("Task 3.2")


def _check_encapsulation(
    import_module: str,
    importing_file: str,
) -> CheckResult | None:
    """Detect encapsulation violations — report only, no auto-fix.

    An encapsulation violation occurs when external code imports from a
    submodule instead of through the package's __init__.py (FR-404, FR-405).

    Args:
        import_module: The module being imported (dotted path).
        importing_file: The file doing the importing.

    Returns:
        CheckResult with ENCAPSULATION_VIOLATION if detected, None otherwise.
    """
    raise NotImplementedError("Task 3.2")


def check_imports(config: ImportCheckConfig) -> list[CheckResult]:
    """Run all import verification checks on configured directories.

    Walks all .py files in source_dirs, extracts import statements using
    ast, and runs module existence, symbol definition, and optional
    encapsulation checks (FR-401, FR-407).

    Args:
        config: Tool configuration with source_dirs, exclude_patterns,
            encapsulation_check toggle.

    Returns:
        List of CheckResult objects for all errors found.
        Empty list means all imports verified successfully.
    """
    raise NotImplementedError("Task 3.2")
```

---

## B.8: Public API Facade Stubs — Contract

Defines the stable public API surface.

**Tasks:** Task 4.1
**Requirements:** FR-501, FR-502, FR-503, FR-504
**Type:** Contract (exact — copied to implementation docs Phase 0)

```python
# import_check/__init__.py
"""Import Check Tool — public API.

Exposes three functions:
- fix(): detect and fix broken imports
- check(): verify all imports resolve correctly
- run(): fix then check (full pipeline)

Usage:
    import import_check
    results = import_check.run()
    fix_results, check_results = results
"""
from __future__ import annotations

from typing import Any

from import_check.schemas import CheckResult, FixResult, ImportCheckConfig

__all__ = ["fix", "check", "run", "ImportCheckConfig", "FixResult", "CheckResult"]


def _setup_logging(log_level: str) -> None:
    """Configure the import_check logger.

    Args:
        log_level: One of "DEBUG", "INFO", "ERROR" (FR-504).
    """
    raise NotImplementedError("Task 4.1")


def fix(**kwargs: Any) -> list[FixResult]:
    """Detect and fix broken imports after refactoring.

    Pipeline: load config -> build inventories -> diff -> fix.

    Args:
        **kwargs: Config overrides (FR-709). See ImportCheckConfig fields.

    Returns:
        List of FixResult objects, one per processed file.
    """
    raise NotImplementedError("Task 4.1")


def check(**kwargs: Any) -> list[CheckResult]:
    """Verify all imports resolve correctly.

    Args:
        **kwargs: Config overrides (FR-709). See ImportCheckConfig fields.

    Returns:
        List of CheckResult objects for all errors found.
    """
    raise NotImplementedError("Task 4.1")


def run(**kwargs: Any) -> tuple[list[FixResult], list[CheckResult]]:
    """Run the full pipeline: fix then check.

    Args:
        **kwargs: Config overrides (FR-709). See ImportCheckConfig fields.

    Returns:
        Tuple of (fix_results, check_results).
    """
    raise NotImplementedError("Task 4.1")
```

---

## B.9: libcst ImportRewriter Transformer — Pattern

Illustrates the libcst transformer approach for rewriting import statements based on the migration map. Shows the visit/leave pattern for `ImportFrom`, `Import`, `Call` (mock.patch, importlib), and `Assign` (__all__) nodes.

**Tasks:** Task 3.1
**Requirements:** FR-301 through FR-311
**Type:** Pattern (illustrative — for implement-code only, never test agents)

```python
# Illustrative pattern — not the final implementation
# import_check/fixer.py (internal transformer class)

import libcst as cst
from import_check.schemas import MigrationMap, MigrationEntry


class ImportRewriter(cst.CSTTransformer):
    """Rewrites imports based on a migration map.

    Handles:
    - from x import y (including aliases)
    - import x (including aliases)
    - __all__ list entries
    - mock.patch() string arguments
    - importlib.import_module() string literals
    - Single-assignment dataflow in function scope
    """

    def __init__(self, migration_map: MigrationMap) -> None:
        self.migration_map = migration_map
        self.changes_made = 0
        self.warnings: list[str] = []
        # Build lookup: (old_module, old_name) -> MigrationEntry
        self._lookup: dict[tuple[str, str], MigrationEntry] = {
            (e.old_module, e.old_name): e for e in migration_map
        }
        # Build module-level lookup: old_module -> new_module (for bare imports)
        self._module_lookup: dict[str, str] = {
            e.old_module: e.new_module
            for e in migration_map
            if e.old_name == e.new_name  # module moves, not renames
        }
        # Track string variable assignments in current function scope
        self._scope_vars: dict[str, str] = {}

    def leave_ImportFrom(self, original, updated):
        # Reconstruct dotted module name from the ImportFrom node
        # Look up each imported name in _lookup
        # If found, rewrite module and/or name
        # Increment self.changes_made for each rewrite
        ...

    def leave_Import(self, original, updated):
        # For bare `import x.y.z` — check _module_lookup
        # Rewrite the module path if it moved
        ...

    def leave_Call(self, original, updated):
        # Detect mock.patch("old.module.Symbol") calls
        # Detect importlib.import_module("old.module") calls
        # Rewrite string literal arguments using _lookup
        # For variable args, check _scope_vars for resolved paths
        ...

    def visit_FunctionDef(self, node):
        # Reset scope tracking for dataflow analysis
        self._scope_vars = {}

    def leave_Assign(self, original, updated):
        # If in function scope and RHS is a string literal:
        #   Track name -> value in _scope_vars
        # If target is __all__:
        #   Rewrite list elements matching migration entries
        ...

    def visit_FormattedString(self, node):
        # Flag f-strings that contain module paths — DYNAMIC_UNFIXABLE
        # Add to self.warnings, do not attempt rewrite
        ...
```

**Key design decisions:**
- Single lookup dict `(old_module, old_name) -> MigrationEntry` avoids O(n) scan per import node.
- Separate `_module_lookup` for bare `import x` statements, which don't have a symbol name.
- `_scope_vars` is reset per `FunctionDef` to implement bounded single-assignment dataflow without cross-function tracking.
- f-string detection produces warnings rather than attempting risky rewrites.

---

## B.10: Inventory Diffing Algorithm — Pattern

Illustrates the 3-step diffing algorithm: detect moves, detect renames (excluding moves), then re-tag splits/merges from the move pattern.

**Tasks:** Task 2.2
**Requirements:** FR-201 through FR-205
**Type:** Pattern (illustrative — for implement-code only, never test agents)

```python
# Illustrative pattern — not the final implementation
# import_check/differ.py (detection logic)

from collections import defaultdict
from import_check.schemas import (
    MigrationEntry, MigrationKind, SymbolEntry, SymbolInventory,
)


def _detect_moves(old: SymbolInventory, new: SymbolInventory):
    """Step 1: Find symbols with same name but different module path."""
    moves = []
    for name, old_entries in old.items():
        if name not in new:
            continue
        new_entries = new[name]
        # Build module sets for this symbol name
        old_modules = {e.module_path for e in old_entries}
        new_modules = {e.module_path for e in new_entries}
        # Symbols that appeared in new modules (not in old) are move targets
        for old_entry in old_entries:
            if old_entry.module_path not in new_modules:
                # Find the best match in new entries
                for new_entry in new_entries:
                    if new_entry.module_path not in old_modules:
                        moves.append(MigrationEntry(
                            symbol_name=name,
                            old_module=old_entry.module_path,
                            new_module=new_entry.module_path,
                            old_name=name, new_name=name,
                            kind=MigrationKind.MOVE,
                        ))
                        break
    return moves


def _detect_splits_and_merges(old, new, moves):
    """Step 3: Re-tag moves as SPLIT or MERGE based on fan-out/fan-in."""
    # Group moves by old_module
    by_old = defaultdict(list)
    for m in moves:
        by_old[m.old_module].append(m)

    # Group moves by new_module
    by_new = defaultdict(list)
    for m in moves:
        by_new[m.new_module].append(m)

    retagged = []
    for m in moves:
        # SPLIT: one old module -> multiple new modules
        if len({e.new_module for e in by_old[m.old_module]}) > 1:
            retagged.append(MigrationEntry(
                symbol_name=m.symbol_name,
                old_module=m.old_module, new_module=m.new_module,
                old_name=m.old_name, new_name=m.new_name,
                kind=MigrationKind.SPLIT,
            ))
        # MERGE: multiple old modules -> one new module
        elif len({e.old_module for e in by_new[m.new_module]}) > 1:
            retagged.append(MigrationEntry(
                symbol_name=m.symbol_name,
                old_module=m.old_module, new_module=m.new_module,
                old_name=m.old_name, new_name=m.new_name,
                kind=MigrationKind.MERGE,
            ))
        else:
            retagged.append(m)
    return retagged
```

**Key design decisions:**
- Move detection is greedy (first match) because in practice each symbol name resolves to a single move target. If multiple candidates exist, the first match is correct for the common case and the smoke test catches any mismatches.
- Split/merge detection operates on the move set (not raw inventories) to avoid double-counting symbols that were simply added or deleted.
- Re-tagging replaces MOVE entries rather than adding new entries — downstream consumers see each migration exactly once.

---

## B.11: CLI Entry Point — Pattern

Illustrates the argument parser structure and subcommand dispatch for `python -m import_check`.

**Tasks:** Task 4.2
**Requirements:** FR-601 through FR-605, FR-708
**Type:** Pattern (illustrative — for implement-code only, never test agents)

```python
# Illustrative pattern — not the final implementation
# import_check/__main__.py

import argparse
import json
import sys
from import_check import fix, check, run


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="import_check",
        description="Detect and fix broken Python imports after refactoring.",
    )
    parser.add_argument(
        "--source-dirs", nargs="+", default=None,
        help="Directories to scan (overrides pyproject.toml)",
    )
    parser.add_argument(
        "--exclude", nargs="+", default=None, dest="exclude_patterns",
        help="Glob patterns to exclude",
    )
    parser.add_argument("--git-ref", default=None, help="Git ref for before state")
    parser.add_argument(
        "--format", choices=["human", "json"], default=None, dest="output_format",
    )
    parser.add_argument(
        "--log-level", choices=["DEBUG", "INFO", "ERROR"], default=None,
    )
    encap = parser.add_mutually_exclusive_group()
    encap.add_argument("--encapsulation-check", action="store_true", default=None)
    encap.add_argument("--no-encapsulation-check", action="store_false",
                       dest="encapsulation_check")

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fix", help="Detect and fix broken imports")
    sub.add_parser("check", help="Verify all imports resolve")
    sub.add_parser("run", help="Fix then check (full pipeline)")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    # Build CLI overrides dict (only non-None values)
    cli_overrides = {
        k: v for k, v in vars(args).items()
        if v is not None and k != "command"
    }
    dispatch = {"fix": fix, "check": check, "run": run}
    result = dispatch[args.command](cli_overrides=cli_overrides)
    # Format and print output
    # Return exit code: 0=success, 1=errors found, 2=tool failure
    ...


if __name__ == "__main__":
    sys.exit(main())
```

**Key design decisions:**
- Global flags (source-dirs, exclude, etc.) are on the parent parser, not duplicated on each subcommand.
- `cli_overrides` is built by filtering None values from parsed args, preserving the 3-layer config precedence.
- Exit codes follow Unix convention: 0 success, 1 errors found, 2 internal failure.
