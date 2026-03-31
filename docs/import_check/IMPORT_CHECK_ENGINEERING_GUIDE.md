# Import Check Tool -- Engineering Guide

| Field | Value |
|-------|-------|
| **System** | import_check |
| **Source** | `import_check/` |
| **Companion Spec** | `docs/import_check/IMPORT_CHECK_SPEC.md` |
| **Companion Design** | `docs/import_check/IMPORT_CHECK_DESIGN.md` |
| **Last Updated** | 2026-03-29 |
| **Companion Enhancements Spec** | `docs/import_check/IMPORT_CHECK_ENHANCEMENTS_SPEC.md` |

---

## 1. System Overview

### Purpose

The import_check tool automatically detects and fixes broken Python import statements after code refactoring. When developers move functions between files, rename modules, split large files, or merge small ones, every `import`, `from ... import`, `mock.patch()` string path, `importlib.import_module()` call, and `__all__` entry that references the moved symbols breaks. This tool fixes those breakages deterministically using AST analysis and git history, without executing any Python modules at runtime.

### Architecture

The tool is a standalone Python package at `import_check/` with seven source files:

```
import_check/
  schemas.py       -- Typed contracts: SymbolInfo, MigrationEntry, ImportError, FixResult, etc.
  inventory.py     -- AST-based symbol extraction + git history retrieval
  differ.py        -- Inventory diffing to detect moves, renames, splits, merges
  fixer.py         -- libcst-based import rewriting (3 transformers)
  checker.py       -- Smoke test: filesystem + AST verification of all imports
                      (with relative import resolution, __getattr__/.pyi fallback,
                      and inline suppression support)
  __init__.py      -- Public API facade: fix(), check(), run() + config loading
  __main__.py      -- CLI entry point: argument parsing + output formatting
```

### 3-Step Pipeline

```
Step 1: FIX (deterministic)         Step 2: CHECK (zero-cost)              Step 3: LLM (residual)
+---------------------------------+ +------------------------------------+ +---------------------+
| inventory.py: build old+new     | | checker.py: parse all imports      | | External consumer   |
| differ.py: diff -> migration map| | Resolve relative imports to abs    | | reads structured    |
| fixer.py: rewrite imports       | | Filter inline suppressions         | | error list (JSON)   |
|                                 | | Verify module exists on disk       | |                     |
|                                 | | Verify symbol: .py -> __getattr__ | |                     |
|                                 | |   -> .pyi stub (fallback chain)   | |                     |
+---------------------------------+ +------------------------------------+ +---------------------+
     ast + libcst, 0 tokens              ast + filesystem, 0 tokens             ~100 tokens/error
```

Step 1 handles ~95% of broken imports through deterministic AST diffing and libcst rewriting. Step 2 catches anything Step 1 missed using zero-cost filesystem verification, now with three enhancements: (a) relative imports are resolved to absolute paths and verified, (b) symbol verification uses a fallback chain through `__getattr__` presence and `.pyi` stub definitions to reduce false positives, and (c) per-line `# import_check: ignore` comments suppress individual imports from verification. Step 3 is external -- the tool outputs a structured error list that an LLM agent or developer consumes separately.

### Design Goals

| Goal | Implementation |
|------|----------------|
| **Deterministic-first** | All fixing uses `ast` + `libcst` with zero LLM tokens. The LLM is a safety net, not the primary mechanism. |
| **Zero-cost verification** | The checker uses only `ast.parse()` and `Path.is_file()`. No `importlib.import_module()`, no runtime execution, no side effects. The `__getattr__` and `.pyi` stub fallback chain uses the same AST-only approach. |
| **Generic portability** | No project-specific assumptions. Works on any Python project with git. Single `python -m import_check` entry point. |
| **Config-driven** | All behavior controlled by typed config: source dirs, exclude patterns, git ref, encapsulation toggle, stub/getattr fallback toggles, output format, log level. |
| **Explicit fallback chain** | Symbol verification applies checks in a defined order: `.py` direct definition, then `__getattr__` presence, then `.pyi` stub definition. Each step is configurable. |
| **Auditable suppression** | Suppressed imports (via `# import_check: ignore`) are logged at DEBUG level so developers can audit which imports are being skipped. |

### Technology Choices

| Technology | Role |
|------------|------|
| `ast` (stdlib) | Read-only AST parsing for symbol extraction and import analysis. Fast, no dependencies. |
| `libcst` (external) | Formatting-preserving CST transformation for import rewriting. The sole external dependency. |
| `subprocess` (stdlib) | Git operations: `git diff --name-only`, `git show <ref>:<file>`. |
| `tomllib` / `tomli` | Configuration loading from `pyproject.toml`. `tomllib` is stdlib on Python 3.11+; `tomli` is the backport. |

---

## 2. Architecture Decisions

### Decision: ast for detection, libcst for rewriting

**Context:** The tool needs to both read Python source (symbol extraction, import parsing) and write Python source (import rewriting). Two distinct libraries serve these two needs.

**Options considered:**
1. **ast for both reading and writing** -- `ast` is stdlib and fast for reading, but it discards formatting information. Using `ast.unparse()` for writing would destroy comments, whitespace, and trailing commas throughout the modified file.
2. **libcst for both reading and writing** -- libcst preserves formatting perfectly, but is slower than `ast` for read-only operations and is an external dependency.
3. **ast for reading, libcst for writing** -- Uses stdlib speed for the read-heavy inventory/checker phases, and libcst's formatting preservation only for the write phase (fixer).

**Choice:** Option 3 -- ast for reading, libcst for writing.

**Rationale:** The inventory builder and checker are read-only and process many files. Using `ast` (stdlib, faster) for these keeps the tool lightweight. The fixer is the only phase that modifies source files, and it must preserve formatting to avoid noisy diffs. libcst is used only there. This also means `libcst` is the sole external dependency.

**Consequences:**
- **Positive:** Minimal dependency footprint. Fast read-only phases.
- **Negative:** Two different AST representations in the codebase (ast trees vs libcst trees). Developers must understand which to use where.
- **Watch for:** If libcst adds features that make read-only analysis faster, consolidating to libcst-only could simplify the codebase.

### Decision: Symbol-level inventory, not file-level

**Context:** After a refactoring, the tool must determine what moved where. The granularity of tracking determines which refactoring patterns can be detected.

**Options considered:**
1. **Module-level registry file + watcher** -- Maintain a registry of module locations, updated by a watcher. Rejected: too coarse, cannot track function-level moves within a file split.
2. **File-level AST comparison** -- Compare AST trees of individual files before and after. Rejected: breaks on multi-file refactors (splits, merges) because there is no single file pair to compare.
3. **Symbol-level inventory across codebase** -- Build a complete mapping of every symbol (function, class, variable) to its module path, for both old and new states. Diff the two inventories.

**Choice:** Option 3 -- Symbol-level inventory.

**Rationale:** Symbol-level granularity handles all refactoring patterns correctly: moves (same name, different module), renames (different name, same area), splits (one file to many), and merges (many files to one). File-level comparison cannot detect cross-file symbol movements.

**Consequences:**
- **Positive:** Handles all refactoring patterns uniformly. The migration map is a flat list of symbol-level entries regardless of the refactoring pattern.
- **Negative:** More data to track per file (every public symbol vs. just the file path). Larger inventories for symbol-rich files.
- **Watch for:** Very large codebases (10,000+ files) may want lazy or cached inventories.

### Decision: Three separate libcst transformers

**Context:** The fixer must rewrite three different kinds of references: import statements, string-based references (`mock.patch()`, `importlib.import_module()`), and `__all__` lists. These could be handled by one large transformer or multiple focused ones.

**Options considered:**
1. **Single monolithic transformer** -- One `CSTTransformer` handles all cases. Simpler dispatch but harder to test and extend.
2. **Three focused transformers** -- `ImportRewriter`, `StringRefRewriter`, `AllListRewriter`, applied sequentially to each file.

**Choice:** Option 2 -- Three focused transformers.

**Rationale:** Each transformer has a distinct concern and distinct node types to visit. Separating them makes testing easier (each can be unit-tested independently), makes the code more navigable, and makes it straightforward to add a fourth transformer for new reference types.

**Consequences:**
- **Positive:** Clean separation of concerns. Each transformer is independently testable. Adding new reference patterns means adding a new transformer class.
- **Negative:** Three sequential passes over the CST per file. Minor performance cost that is negligible in practice.

### Decision: Scoping to git-changed files only

**Context:** The tool must decide which files to include in inventory construction. Scanning every Python file on every run would be safe but slow.

**Options considered:**
1. **Full codebase scan** -- Build inventories from all Python files. Correct but slow for large projects.
2. **Git diff scoping** -- Only build inventories for files reported by `git diff --name-only <ref>`. Proportional to refactoring size, not codebase size.

**Choice:** Option 2 -- Git diff scoping.

**Rationale:** Only changed files can introduce or resolve broken imports. Scanning unchanged files adds cost without information. This keeps runtime proportional to the size of the refactoring operation, meeting the performance target of under 30 seconds for 1,000-file codebases with 50 changed files (REQ-901).

**Consequences:**
- **Positive:** Fast on large codebases with small refactoring operations.
- **Negative:** If a symbol was moved in a previous (already-committed) refactoring, and imports were not fixed before the commit, the tool will not detect it on a subsequent run unless the git ref is adjusted to point before the original move.
- **Watch for:** Users who make incremental commits during a multi-step refactoring need to set `git_ref` to the commit before the refactoring started, not just `HEAD`.

---

## 3. Module Reference

### `import_check/schemas.py` -- Typed Contracts

**Purpose:**

Defines all shared data structures used across the import_check tool. Every module imports its types from this single file, ensuring a consistent contract surface. This is the canonical location for `SymbolInfo`, `MigrationEntry`, `ImportError`, `FixResult`, `RunResult`, and `ImportCheckConfig`.

**Key types:**

```python
@dataclass(frozen=True)
class SymbolInfo:
    name: str                                           # e.g. "MyClass"
    module_path: str                                    # e.g. "src.retrieval.engine"
    file_path: str                                      # e.g. "src/retrieval/engine.py"
    lineno: int                                         # 1-based line number
    symbol_type: Literal["function", "class", "variable"]

SymbolInventory = dict[str, list[SymbolInfo]]           # symbol name -> locations

@dataclass(frozen=True)
class MigrationEntry:
    old_module: str
    old_name: str
    new_module: str
    new_name: str                                       # same as old_name for pure moves
    migration_type: Literal["move", "rename", "split", "merge"]

class ImportErrorType(Enum):
    MODULE_NOT_FOUND = "module_not_found"
    SYMBOL_NOT_DEFINED = "symbol_not_defined"
    ENCAPSULATION_VIOLATION = "encapsulation_violation"

@dataclass(frozen=True)
class ImportError:
    file_path: str
    lineno: int
    module: str
    name: str                                           # empty for bare `import X`
    error_type: ImportErrorType
    message: str

@dataclass
class FixResult:
    files_modified: list[str]                           # files that were rewritten
    fixes_applied: int                                  # total import rewrites
    errors: list[str]                                   # non-fatal issues during fixing
    skipped: list[str]                                  # locations that could not be auto-fixed

@dataclass
class RunResult:
    fix_result: FixResult
    remaining_errors: list[ImportError]

@dataclass
class ImportCheckConfig:
    source_dirs: list[str]          # default: ["src", "server", "config"]
    exclude_patterns: list[str]     # default: [".venv", "__pycache__", "node_modules"]
    check_stubs: bool               # default: True -- .pyi stub fallback (REQ-511)
    check_getattr: bool             # default: True -- __getattr__ suppression (REQ-513)
    git_ref: str                    # default: "HEAD"
    encapsulation_check: bool       # default: True
    output_format: Literal["human", "json"]  # default: "human"
    log_level: str                  # default: "INFO"
    root: Path                      # resolved at runtime
```

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| `SymbolInfo` and `MigrationEntry` are frozen dataclasses | Mutable dataclasses, TypedDict, NamedTuple | Frozen dataclasses are hashable (needed for set-based dedup in differ) and immutable (prevents accidental mutation during multi-phase processing). |
| `SymbolInventory` is `dict[str, list[SymbolInfo]]` not `dict[str, SymbolInfo]` | Single-value dict | A symbol name can exist in multiple modules (common after splits or with identically-named helpers). The list-valued dict handles this without special-casing. |
| `FixResult` and `RunResult` are mutable dataclasses | Frozen | These are accumulated during processing -- the fixer appends to `files_modified` and increments `fixes_applied` as it processes files. Mutability is intentional. |
| `ImportError` shadows the Python builtin | Rename to `ImportCheckError`, use a prefix | The name `ImportError` is semantically accurate for the domain. Since the tool is a standalone package (not imported into arbitrary user code), the shadowing risk is contained. Users who need the builtin can access it via `builtins.ImportError`. |

---

### `import_check/inventory.py` -- Symbol Inventory Builder

**Purpose:**

Builds symbol inventories by scanning Python source files with `ast`. Produces two inventories: an "old" inventory from a git ref (the state before refactoring) and a "new" inventory from the current filesystem (the state after refactoring). Also provides utilities for collecting Python files and querying git for changed files. This module addresses REQ-101, REQ-103, REQ-105, REQ-107, REQ-111 from the spec.

**How it works:**

1. **`get_changed_files(git_ref, root)`** runs `git diff --name-only <ref>` via `subprocess.run()`, filters the output to `.py` files only, and returns a list of relative paths. This scopes all subsequent work to only the files that changed.

2. **`collect_python_files(source_dirs, root, exclude_patterns)`** walks each directory in `source_dirs` using `Path.rglob("*.py")`, filters out paths matching any `exclude_patterns` using `fnmatch`, and returns a sorted list of relative paths. The pattern matching checks each path component individually (not just the full path), so a pattern like `__pycache__` matches any path containing that directory segment.

3. **`build_old_inventory(files, git_ref)`** retrieves the historical content of each changed file using `git show <ref>:<file>`. For each file:
   - Runs `subprocess.run(["git", "show", f"{git_ref}:{file_path}"])`.
   - If the file did not exist at that ref (non-zero return code), silently skips it.
   - Parses the source with `_extract_symbols()` and adds entries to the inventory dict.

4. **`build_inventory(files, root)`** reads each file from the current filesystem, parses it, and builds the inventory the same way. Files that fail to read (OSError) or parse (SyntaxError) are logged at WARNING and skipped.

5. **`_extract_symbols(source, file_path, module_path)`** is the core AST extraction function. It calls `ast.parse()` and iterates over top-level child nodes of the module:
   - `FunctionDef` / `AsyncFunctionDef` -- extracts the function name.
   - `ClassDef` -- extracts the class name.
   - `Assign` -- extracts `Name` targets (e.g., `MY_CONST = 42`).
   - `AnnAssign` -- extracts the `Name` target (e.g., `MY_CONST: int = 42`).
   - Private symbols (names starting with `_`) are skipped, except `__all__`.

6. **`_file_to_module_path(file_path, root)`** converts a filesystem path to a dotted module path. `src/retrieval/engine.py` becomes `src.retrieval.engine`. `src/retrieval/__init__.py` becomes `src.retrieval` (the `__init__.py` filename is dropped).

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Use `subprocess.run()` for git operations | `gitpython` library, `dulwich` library | Keeps the tool dependency-free (stdlib only for git). `subprocess` is fast and the git CLI is universally available. |
| Skip private symbols (leading `_`) | Include all symbols | Private symbols are implementation details that should not appear in imports from other modules. Including them would create false-positive migration entries when internal helpers are renamed. The exception is `__all__`, which is a public contract. |
| Silent skip for files not found at git ref | Raise an error, log a warning | A file that does not exist at the ref is a newly created file. It has no "old" state to inventory. This is a normal condition (not an error), so silent skip at DEBUG level is appropriate. |

**Configuration:**

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `source_dirs` | `list[str]` | `["src", "server", "config"]` | Directories passed to `collect_python_files()`. Only files under these directories are collected. |
| `exclude_patterns` | `list[str]` | `[".venv", "__pycache__", "node_modules"]` | Glob patterns passed to `collect_python_files()`. Matched against each path component. |
| `git_ref` | `str` | `"HEAD"` | The git reference used by `get_changed_files()` and `build_old_inventory()` to retrieve the "before" state. |

**Error behavior:**

- **`RuntimeError`** from `get_changed_files()` if `git diff` fails (git not installed, not a repo, invalid ref). This is non-recoverable and propagates to the caller.
- **`SyntaxError`** from `_extract_symbols()` when a Python file cannot be parsed. Caught internally by `build_inventory()` and `build_old_inventory()`, logged at WARNING, and the file is skipped.
- **`OSError`** when reading a file from the filesystem. Caught internally by `build_inventory()`, logged at WARNING, and the file is skipped.

---

### `import_check/differ.py` -- Inventory Differ

**Purpose:**

Compares two `SymbolInventory` objects (old and new) to detect how symbols migrated between modules. Produces a list of `MigrationEntry` records that the fixer uses to rewrite imports. This module addresses REQ-109 from the spec, and FR-201 through FR-205 from the design document.

**How it works:**

Detection runs in three ordered phases. Each phase feeds an `already_matched` set into subsequent phases so that a single symbol is never double-counted.

**Phase 1: Move detection (`_detect_moves`)**

For each symbol name present in both inventories, compares the sets of module paths:
- `departed` = modules the symbol was in (old) but is no longer in (new).
- `arrived` = modules the symbol is in (new) but was not in (old).

If there is exactly one departed and one arrived module, this is a simple 1-to-1 move. If the counts match but are greater than 1, the function attempts positional matching by file basename via `_match_modules_by_file()`. If matching is ambiguous, the move is skipped (logged at DEBUG) to avoid false positives.

**Phase 2: Rename detection (`_detect_renames`)**

Finds symbols that disappeared from a module and new symbols that appeared in the same module:
- For each module, builds lists of "disappeared" old symbols and "appeared" new symbols.
- Matches disappeared to appeared using heuristics: same file, same `symbol_type`, and line number within `_RENAME_LINE_PROXIMITY` (30 lines).
- Greedy matching: processes disappeared symbols in line-number order, picks the closest-matching new symbol.

```python
_RENAME_LINE_PROXIMITY = 30  # Maximum line distance for rename candidates
```

**Phase 3: Split and merge detection (`_detect_splits_and_merges`)**

For remaining unmatched symbols (same name, different file between old and new):
- Groups by old file: if symbols from one old file now appear in 2+ new files, these are splits.
- Groups by new file: if one new file received symbols from 2+ old files, these are merges.
- Uses a `dedup_key` tuple `(old_module, old_name, new_module, new_name)` to prevent duplicate entries when a migration qualifies as both a split and a merge.

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Three-phase ordered detection | Single-pass pattern matching, graph-based matching | Ordered phases with an `already_matched` set prevent double-counting. Moves are detected first (highest confidence), then renames (heuristic), then splits/merges (structural). Each phase has well-defined preconditions. |
| Rename heuristic: same file + same type + line proximity | Name similarity (Levenshtein), structural similarity (AST subtree matching) | Line proximity within the same file and symbol type is a strong signal for renames after refactoring. It avoids false positives from name similarity (e.g., `get_user` and `get_users` are similar strings but unrelated symbols). The 30-line threshold is generous enough to catch most renames while avoiding spurious matches across unrelated symbols. |
| Skip ambiguous moves instead of guessing | Use the first match, use scoring | False positives in the migration map cause the fixer to rewrite correct imports to incorrect ones. Skipping ambiguous cases and letting the smoke test catch them is safer than guessing wrong. |

**Configuration:**

This module has no configurable parameters. The `_RENAME_LINE_PROXIMITY` threshold (30 lines) is a compile-time constant. To change it, modify the value in `differ.py`.

**Error behavior:**

This module does not raise exceptions. It operates entirely on in-memory data structures (the two inventories). All edge cases (empty inventories, no common symbols, ambiguous matches) result in empty or partial output, never exceptions.

---

### `import_check/fixer.py` -- Import Rewriter

**Purpose:**

Rewrites broken imports in Python source files using `libcst`. Takes the migration map from `differ.py` and applies three types of transformations: import statement rewriting, string-based reference rewriting (for `mock.patch()` and `importlib.import_module()`), and `__all__` list updates. This is the only module that modifies source files. It addresses REQ-201 through REQ-217 from the spec.

**How it works:**

The module defines three `libcst.CSTTransformer` subclasses and a file-level application function:

**1. `ImportRewriter` -- rewrites `from X import Y` and `import X`**

- Builds two lookup tables from the migration map:
  - `_by_module_name: dict[(old_module, old_name), MigrationEntry]` -- for `from X import Y` matching.
  - `_by_module: dict[old_module, list[MigrationEntry]]` -- for bare `import X` matching.

- `leave_ImportFrom()`: For each `from X import Y` node, looks up `(X, Y)` in `_by_module_name`. If found, replaces the symbol name and (if all matched entries point to the same new module) the module path. Handles star imports by checking the module-level lookup.

- `leave_Import()`: For each `import X` node, looks up `X` in `_by_module`. If found, replaces the module name with the new module path.

- Aliases (`as` clauses) are preserved automatically because libcst's `ImportAlias.with_changes()` only modifies the fields explicitly changed.

**2. `StringRefRewriter` -- rewrites string arguments in function calls**

- Builds two lookup tables:
  - `_path_map: dict[str, str]` -- maps `"old_module.old_name"` to `"new_module.new_name"` (full dotted paths for `mock.patch()`).
  - `_module_map: dict[str, str]` -- maps `"old_module"` to `"new_module"` (module-only for `importlib.import_module()`).

- Tracks function-scope variable assignments for simple dataflow analysis: when a string literal is assigned to a variable inside a function, the rewriter records it in `_scope_vars`. If that variable is later passed to a target call, the assignment site is rewritten.

- Target call patterns: `patch`, `mock.patch`, `unittest.mock.patch`, `patch.object`, `import_module`, `importlib.import_module`.

- `leave_Call()`: Checks if the call matches a target pattern, then tries to rewrite the first argument string. Uses prefix matching for hierarchical paths (e.g., `"old.module.Symbol.method"` rewrites the `old.module.Symbol` prefix).

- `leave_SimpleStatementLine()`: Rewrites string variable assignments whose values match the migration map (the dataflow handling).

**3. `AllListRewriter` -- updates `__all__` lists**

- Builds a `_name_map: dict[str, str]` of old-name to new-name for renamed symbols only.
- `leave_Assign()`: Finds `__all__ = [...]` assignments and replaces string elements that match old names with new names. Preserves quote style.

**4. `apply_fixes()` -- the main entry point**

For each target file:
1. Creates fresh instances of all three transformers (per-file fix counting).
2. Calls `_apply_transformers_to_file()` which: reads the file, parses it with `cst.parse_module()`, applies each transformer sequentially, and writes back only if the CST code changed.
3. Accumulates results into a `FixResult`.

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Fresh transformer instances per file | Shared transformer instances across files | Per-file instances ensure clean state (no cross-file contamination in scope tracking) and enable per-file fix counting. |
| Prefix matching for string paths | Exact match only | `mock.patch("src.old.module.MyClass.method")` needs to match even though the migration map only records `MyClass` at the module level. Prefix matching handles chained attribute access in mock targets. |
| Simple dataflow bounded to single-function scope | Cross-function dataflow, no dataflow | Single-function scope covers the common pattern (`path = "src.x"; mock.patch(path)`) without the complexity and false-positive risk of cross-function analysis. The `_scope_vars` dict is reset on each `visit_FunctionDef` / `leave_FunctionDef`. |
| Quote style preservation | Always use double quotes | `_make_simple_string()` inspects the original string node's quote style and applies the same style to the replacement. This avoids formatting noise in diffs. |

**Configuration:**

This module has no configurable parameters. It operates entirely based on the migration map passed to `apply_fixes()`.

**Error behavior:**

- **`cst.ParserSyntaxError`** when a file cannot be parsed by libcst. Caught in `_apply_transformers_to_file()`, added to the errors list, and the file is skipped.
- **`OSError`** when reading or writing a file. Caught internally, added to the errors list. Read failures skip the file; write failures are reported but the in-memory transform is lost.
- **General `Exception`** from a transformer. Caught per-transformer in `_apply_transformers_to_file()`. The file processing continues with the remaining transformers. This prevents one transformer's bug from blocking all fixes on a file.
- All errors are non-fatal at the file level -- processing continues with the next file. Errors are accumulated in `FixResult.errors`.

---

### `import_check/checker.py` -- Smoke Test Checker

**Purpose:**

Verifies every import statement in the codebase by checking that (a) the target module resolves to an existing file on disk, and (b) the imported symbol is defined in that target file. Optionally detects encapsulation violations. Enhanced with relative import resolution (REQ-313 through REQ-321), runtime symbol suppression via `__getattr__` and `.pyi` stubs (REQ-323 through REQ-333), and inline suppression comments (REQ-335 through REQ-341). This is the verification gate that catches anything the fixer missed. It addresses REQ-301 through REQ-311 and REQ-313 through REQ-341 from the spec.

**How it works:**

1. **`check_imports(files, root, config)`** iterates over all Python files, extracts imports, and checks each one. At the start of each invocation, per-run caches are cleared via `_clear_caches()`. The processing pipeline for each import is:
   - Filter suppressed imports (lines with `# import_check: ignore`) before any verification.
   - Resolve relative imports to absolute dotted module paths via `_resolve_relative_import()`.
   - Skip stdlib and third-party imports.
   - Verify module exists on disk via `_resolve_module_to_file()`.
   - Verify symbol is defined via `_check_symbol_defined()` (with fallback chain).
   - Check encapsulation violations if enabled.

2. **`_extract_imports(source)`** parses source with `ast.parse()` and walks the entire AST tree (including nested scopes) using `ast.walk()`. Returns 4-tuples `(module, name, lineno, level)`. Captures:
   - `from X import Y` -- produces `(X, Y, lineno, 0)`.
   - `from X import Y as Z` -- produces `(X, Y, lineno, 0)` (the original name, not the alias).
   - `import X` -- produces `(X, "", lineno, 0)`.
   - `from .foo import bar` -- produces `("foo", "bar", lineno, 1)` (relative imports are now included with their level).
   - `from ..utils import helper` -- produces `("utils", "helper", lineno, 2)`.
   - `from . import bar` -- produces `(None, "bar", lineno, 1)` (bare relative import).

3. **`_resolve_relative_import(module, level, file_path, root) -> str | None`** resolves a relative import to an absolute dotted module path. Algorithm:
   - Converts `file_path` to package components (strips `.py` suffix, splits on `/`).
   - Handles `__init__.py` by treating the parent directory as the package.
   - Ascends `level - 1` components from the package. If this exceeds the package depth, returns `None` with a DEBUG log.
   - Verifies the base is a valid package by checking for `__init__.py`.
   - Appends `module` (if not `None`) to build the absolute path.
   - Returns `None` if resolution fails for any reason (file not in a package, ascends above root).

4. **`_is_stdlib_or_thirdparty(module, root)`** filters out imports that are not project-local. A module is considered project-local if its top-level component (e.g., `src` in `src.retrieval.engine`) corresponds to an existing directory or `.py` file under the project root. Otherwise, it is assumed to be stdlib or third-party and skipped.

   The stdlib check uses `sys.stdlib_module_names` (Python 3.10+) with a hardcoded fallback for older versions.

5. **`_resolve_module_to_file(module, root)`** converts a dotted module path to a filesystem path by checking two candidates:
   - `root/<path>/<to>/<module>.py` (file module)
   - `root/<path>/<to>/<module>/__init__.py` (package module)
   Returns the first that exists, or `None`.

6. **`_check_symbol_defined(module_file, symbol_name, config)`** parses the target module file with `ast` and applies a three-step fallback chain:

   **Step 1 -- Direct definition in `.py` source** (always active): Checks top-level AST nodes for:
   - `FunctionDef` / `AsyncFunctionDef` / `ClassDef` with matching name.
   - `Assign` targets (including tuple unpacking).
   - `AnnAssign` targets.
   - `ImportFrom` re-exports (e.g., `from X import symbol_name`).
   - `Import` re-exports (e.g., `import X as symbol_name`).
   - `__all__` list literal entries.

   **Step 2 -- `__getattr__` presence** (when `config.check_getattr` is `True`): If Step 1 fails, calls `_has_dynamic_getattr(module_file)`. If the module defines a module-level `__getattr__`, the symbol is assumed present and the check passes. Logged at DEBUG level.

   **Step 3 -- `.pyi` stub definition** (when `config.check_stubs` is `True`): If Steps 1 and 2 fail, calls `_resolve_stub_file(module_file)` to locate a co-located `.pyi` file. If found, parses it with `ast` and checks for the symbol using the same top-level AST node checks as Step 1. Results are cached per `(stub_path, symbol_name)` pair.

7. **`_has_dynamic_getattr(module_file) -> bool`** checks if a module defines `__getattr__` at the module level. Only inspects top-level `FunctionDef` and `AsyncFunctionDef` nodes -- nested `__getattr__` inside classes or other functions does not count. Results are cached per file path within a single `check_imports` invocation.

8. **`_resolve_stub_file(module_file) -> Path | None`** locates the co-located `.pyi` stub file by replacing the `.py` extension with `.pyi`. For `module.py`, checks for `module.pyi`. For `package/__init__.py`, checks for `package/__init__.pyi`. Does not search any other location.

9. **`_is_suppressed(source, lineno) -> bool`** checks if a source line contains the suppression marker `# import_check: ignore`. The marker can appear at any position on the line. Always active -- no configuration toggle required. Follows the same convention as `# noqa` and `# type: ignore`.

10. **`_clear_caches() -> None`** clears per-invocation caches for `__getattr__` detection and stub symbol results. Called at the start of each `check_imports()` invocation to prevent cross-invocation staleness.

11. **`_check_encapsulation(module, file_path, root)`** detects when an external caller imports from an internal module instead of from the package's `__init__.py`:
   - Only applies to multi-component module paths (e.g., `src.retrieval.engine`, not `src`).
   - Checks that the resolved file is NOT `__init__.py` (if it is, the import is already going through the package surface).
   - Checks that the importing file is NOT inside the target package (intra-package imports are allowed).
   - Checks that the package has an `__init__.py` (if it does not, there is no public surface to import from).

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| `ast.walk()` for import extraction (all nesting depths) | `ast.iter_child_nodes()` (top-level only) | `ast.walk()` captures lazy imports inside functions, `TYPE_CHECKING` block imports, and `try/except` conditional imports. Top-level-only extraction would miss a significant class of imports (REQ-207). |
| 4-tuple return with level field | Separate function for relative imports, filter in caller | Including the level in the extraction tuple keeps the extraction function's contract uniform. All imports (absolute and relative) flow through the same pipeline, with resolution handled by the caller. |
| Resolve relative imports in `check_imports`, not in `_extract_imports` | Add file_path parameter to extraction | Keeps `_extract_imports` source-only (no filesystem dependency). Resolution requires the importing file's path and project root -- filesystem concerns that belong in the orchestration layer (REQ-313 design principle). |
| Three-step fallback chain for symbol verification | Single check, parallel checks | Ordered fallback ensures the cheapest check runs first. `__getattr__` is cheaper than stub parsing. Each step is independently configurable via `check_getattr` and `check_stubs`. |
| Per-invocation cache clearing | LRU cache, persistent cache | Clearing caches at the start of each `check_imports()` call prevents stale results across invocations while avoiding memory growth. |
| `# import_check: ignore` always active | Require config toggle to enable | Follows the `# noqa` and `# type: ignore` convention. A per-line escape hatch should not require configuration to enable. |
| Intra-package imports exempt from encapsulation check | Flag all internal module imports | Intra-package imports are normal and expected (a module within `src.retrieval` importing from `src.retrieval.engine` is standard practice). Only external callers bypassing `__init__.py` represent a design concern. |
| Hardcoded stdlib fallback list | Require Python 3.10+, use `isort`'s classification | The fallback ensures the tool works on Python 3.10 (as specified in assumption A-1) even if `sys.stdlib_module_names` is unavailable. The list covers the most common stdlib packages. Third-party packages not in the list are classified by the "does a directory exist locally" heuristic. |

**Configuration:**

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `encapsulation_check` | `bool` | `True` | When `False`, the `_check_encapsulation()` call is skipped entirely. Encapsulation violations will not appear in the error list. |
| `check_stubs` | `bool` | `True` | When `False`, `.pyi` stub file fallback is disabled. Symbol checking uses only the `.py` source. (REQ-511) |
| `check_getattr` | `bool` | `True` | When `False`, `__getattr__` presence is ignored. Missing symbols are reported strictly even if the module defines `__getattr__`. (REQ-513) |

**Error behavior:**

- **`SyntaxError`** in `_extract_imports()` -- caught internally, returns an empty list. The file is effectively skipped for import checking.
- **`SyntaxError` / `OSError`** in `_check_symbol_defined()` -- caught internally, returns `False` (symbol not found). This is conservative: an unparseable module file is treated as if it does not define the symbol.
- **`SyntaxError` / `OSError`** in `_has_dynamic_getattr()` -- caught internally, returns `False` (no `__getattr__` detected). Cached as `False` to avoid repeated parse attempts.
- **`SyntaxError` / `OSError`** in `.pyi` stub parsing -- caught internally, logged at WARNING level. The stub fallback is skipped for that module and cached as `False`.
- **`OSError`** when reading a target file in `check_imports()` -- logged at ERROR, the file is skipped.
- **Unresolvable relative imports** -- logged at DEBUG, the import is skipped without reporting an error.
- **Suppressed imports** -- logged at DEBUG with file path, line number, and import text.
- All errors are logged with the structured format `IMPORT_ERROR: <file>:<line> -- <message>` at ERROR level, designed for downstream consumption by LLM agents or CI parsers.

---

### `import_check/__init__.py` -- Public API Facade

**Purpose:**

Provides the three public entry points (`fix()`, `check()`, `run()`) and handles configuration loading. This is the stable import surface for programmatic callers. All orchestration logic (resolving root, loading config, calling inventory/differ/fixer/checker) lives here. It addresses REQ-401, REQ-407, REQ-501, REQ-505 from the spec.

**How it works:**

1. **`_load_config(root, **overrides)`** implements the three-layer config resolution:
   - **Layer 1 (defaults):** `ImportCheckConfig` dataclass field defaults.
   - **Layer 2 (file):** Reads `pyproject.toml` at `root`, extracts `[tool.import_check]` section using `tomllib` (Python 3.11+) or `tomli` (backport).
   - **Layer 3 (overrides):** Keyword arguments passed by the caller. Only recognized field names (from `dataclasses.fields()`) are applied.
   - Precedence: overrides > pyproject.toml > defaults.

2. **`_setup_logging(config)`** configures the `import_check` logger with the level from config. Uses a simple `%(levelname)s: %(message)s` format. Avoids duplicate handlers on repeated calls by checking `logger.handlers`.

3. **`fix(root, **config_overrides)`** runs the deterministic fix pipeline:
   - Resolves root (defaults to cwd).
   - Loads config, sets up logging.
   - Gets changed files via `inventory.get_changed_files()`.
   - Builds old and new inventories.
   - Diffs inventories to produce the migration map.
   - Collects all Python files across source dirs.
   - Applies fixes via `fixer.apply_fixes()`.
   - Returns `FixResult`.

4. **`check(root, **config_overrides)`** runs the smoke test:
   - Resolves root, loads config, sets up logging.
   - Collects all Python files.
   - Runs `checker.check_imports()`.
   - Returns `list[ImportError]`.

5. **`run(root, **config_overrides)`** runs fix then check:
   - Calls `fix()`, then `check()`.
   - Returns `RunResult(fix_result=..., remaining_errors=...)`.

Internal imports (`from . import differ, fixer, inventory`) are deferred to inside the function bodies. This avoids circular import issues and keeps the module's top-level import surface minimal.

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Deferred internal imports inside function bodies | Top-level imports | Avoids circular imports and keeps the facade module lightweight at import time. The internal modules are only loaded when a public function is actually called. |
| Config field filtering via `dataclasses.fields()` | Accept all kwargs blindly, use a schema validator | Filtering against known field names prevents typos from silently being ignored. Using the dataclass's own field list as the source of truth avoids maintaining a separate whitelist. |
| `tomllib` with `tomli` fallback | Require Python 3.11+, use `toml` package | Maximizes compatibility: stdlib on 3.11+, lightweight backport on 3.10. No heavy dependency. |

**Configuration:**

All configuration parameters from `ImportCheckConfig` are loaded here. See the Configuration Reference (Section 5) for the complete table.

**Error behavior:**

- **`RuntimeError`** from `inventory.get_changed_files()` if git operations fail. Propagated to the caller.
- **Malformed `pyproject.toml`**: Caught with a broad `except Exception`, logged at WARNING, and defaults are used instead. This is intentionally lenient -- a broken TOML file should not prevent the tool from running with defaults.
- All other errors from internal modules (fixer, checker) are captured in their respective result objects, not raised as exceptions.

---

### `import_check/__main__.py` -- CLI Entry Point

**Purpose:**

Provides the command-line interface for the import_check tool, invocable as `python -m import_check [fix|check|run]`. Handles argument parsing, dispatches to the public API, formats output for terminal display, and returns appropriate exit codes. It addresses REQ-403, REQ-405, REQ-409, REQ-411, REQ-509 from the spec.

**How it works:**

1. **`_build_parser()`** constructs an `argparse.ArgumentParser` with:
   - Positional `command` argument: `fix`, `check`, or `run` (default: `run` when omitted).
   - `--source-dirs` (nargs="+"), `--exclude` (nargs="+"), `--git-ref`, `--no-encapsulation-check` (store_false), `--format` (human/json), `--log-level` (DEBUG/INFO/ERROR), `--root`.

2. **`main()`** parses args, builds config overrides dict, and dispatches:
   - `fix` -- calls `fix()`, prints formatted output, returns 0.
   - `check` -- calls `check()`, prints formatted output, returns 1 if errors found, 0 otherwise.
   - `run` (default) -- calls `run()`, prints formatted output, returns 1 if remaining errors, 0 otherwise.

3. **`_format_output(result, fmt)`** routes to either `_format_json()` or `_format_human()`.

4. **`_format_json(result)`** serializes `FixResult`, `list[ImportError]`, or `RunResult` to indented JSON. Uses `isinstance` dispatch on the result type. Enum values are serialized via `.value`.

5. **`_format_human(result)`** produces human-readable text:
   - `FixResult`: `"Fix: N imports rewritten across M files"` + optional error/skip lists.
   - `list[ImportError]`: `"Check: all imports OK"` or `"Check: N import errors found"` with per-error lines.
   - `RunResult`: combines fix summary + remaining errors.

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Default command is `run` (fix + check) | Default to `check` only, require explicit command | `run` is the most useful default for developers: fix what can be fixed, then report what remains. Requiring an explicit command adds friction for the most common use case. |
| Exit code 1 for remaining errors, 0 otherwise | Non-zero for encapsulation violations too | Encapsulation violations are advisory diagnostics, not breakages. Making them fail CI would be overly strict. Only actual broken imports (module not found, symbol not defined) produce a non-zero exit. |
| `--no-encapsulation-check` as store_false | `--encapsulation-check` as store_true | Encapsulation checking is on by default. The opt-out flag (`--no-`) matches the convention used by tools like `pytest --no-header` and `black --no-diff`. |

**Configuration:**

CLI flags map directly to `ImportCheckConfig` fields:

| CLI Flag | Config Field | Notes |
|----------|-------------|-------|
| `--source-dirs` | `source_dirs` | Only set if explicitly provided (avoids overriding pyproject.toml default) |
| `--exclude` | `exclude_patterns` | Only set if explicitly provided |
| `--git-ref` | `git_ref` | Always set (defaults to "HEAD") |
| `--no-encapsulation-check` | `encapsulation_check` | Boolean flag |
| `--format` | `output_format` | Choices: human, json |
| `--log-level` | `log_level` | Choices: DEBUG, INFO, ERROR |
| `--root` | Resolved via `Path(args.root).resolve()` | Defaults to "." |

**Error behavior:**

- Invalid CLI arguments are handled by argparse (prints usage and exits with code 2).
- All runtime errors from the public API propagate as unhandled exceptions with a stack trace. The CLI does not add error wrapping beyond what argparse provides.

---

## 4. End-to-End Data Flow

### Scenario 1: Happy path -- function moved between files

A developer moves `calculate_score` from `src/old_utils.py` to `src/new_utils.py`. Several files import it via `from src.old_utils import calculate_score`.

**Input:** `python -m import_check run`

**Step 1: Inventory & Diff**

```
get_changed_files("HEAD", root)
  -> git diff --name-only HEAD
  -> ["src/old_utils.py", "src/new_utils.py"]

build_old_inventory(["src/old_utils.py", "src/new_utils.py"], "HEAD")
  -> {"calculate_score": [SymbolInfo(name="calculate_score", module_path="src.old_utils", ...)]}

build_inventory(["src/old_utils.py", "src/new_utils.py"], root)
  -> {"calculate_score": [SymbolInfo(name="calculate_score", module_path="src.new_utils", ...)]}

diff_inventories(old, new)
  -> Phase 1 (moves): departed={"src.old_utils"}, arrived={"src.new_utils"}
  -> [MigrationEntry(old_module="src.old_utils", old_name="calculate_score",
                      new_module="src.new_utils", new_name="calculate_score",
                      migration_type="move")]
```

**Step 2: Fix**

```
collect_python_files(["src", "server", "config"], root, [...])
  -> ["src/main.py", "src/old_utils.py", "src/new_utils.py", "server/api.py", ...]

apply_fixes(migration_map, all_files, root)
  For src/main.py:
    ImportRewriter: from src.old_utils import calculate_score
                 -> from src.new_utils import calculate_score
    StringRefRewriter: (no matches)
    AllListRewriter: (no matches)
  -> FixResult(files_modified=["src/main.py"], fixes_applied=1, errors=[], skipped=[])
```

**Step 3: Check**

```
check_imports(all_files, root, config)
  For each import in each file:
    _is_stdlib_or_thirdparty() -> skip stdlib/third-party
    _resolve_module_to_file("src.new_utils", root) -> Path("src/new_utils.py") (exists)
    _check_symbol_defined(Path("src/new_utils.py"), "calculate_score") -> True
  -> []  (no errors)
```

**Output:**
```
Fix: 1 imports rewritten across 1 files

All imports OK after fix.
```

Exit code: 0.

### Scenario 2: Error path -- symbol renamed and moved simultaneously

A developer renames `process_data` to `transform_data` AND moves it from `src/pipeline.py` to `src/transforms.py`. The differ cannot match this deterministically (it is both a rename and a move).

**Input:** `python -m import_check run`

**Step 1: Inventory & Diff**

```
build_old_inventory(...)
  -> {"process_data": [SymbolInfo(module_path="src.pipeline", ...)]}

build_inventory(...)
  -> {"transform_data": [SymbolInfo(module_path="src.transforms", ...)]}

diff_inventories(old, new)
  Phase 1 (moves): "process_data" not in new inventory at all -> no move
  Phase 2 (renames): "process_data" disappeared from src.pipeline,
                     "transform_data" appeared in src.transforms (different file)
                     -> file_path mismatch, no rename detected
  Phase 3 (splits/merges): names differ -> no cross-reference
  -> []  (empty migration map)
```

**Step 2: Fix**

```
apply_fixes([], all_files, root)
  -> FixResult(files_modified=[], fixes_applied=0)  (nothing to fix)
```

**Step 3: Check**

```
check_imports(all_files, root, config)
  For src/main.py:
    from src.pipeline import process_data
    _resolve_module_to_file("src.pipeline", root) -> None  (file was removed or emptied)
    -> ImportError(file_path="src/main.py", lineno=3, module="src.pipeline",
                   name="process_data", error_type=MODULE_NOT_FOUND,
                   message="Module 'src.pipeline' not found")
```

**Output:**
```
Fix: 0 imports rewritten across 0 files

Remaining errors: 1
  src/main.py:3 -- Module 'src.pipeline' not found
```

Exit code: 1. The structured error list (available in JSON with `--format json`) is consumed by an LLM agent for Step 3 residual fix.

### Scenario 3: Edge case -- file split with encapsulation violation

`src/big_module.py` is split into `src/big_module/parser.py` and `src/big_module/renderer.py`, with `src/big_module/__init__.py` re-exporting the public symbols. An external file `server/handler.py` imports directly from `src.big_module.parser` instead of from `src.big_module`.

**Step 1:** The differ detects the split and produces migration entries mapping each symbol to its new sub-module.

**Step 2:** The fixer rewrites `from src.big_module import parse_doc` to `from src.big_module.parser import parse_doc` based on the migration map.

**Step 3:** The checker finds that `server/handler.py` has `from src.big_module.parser import parse_doc`. Since `src/big_module/__init__.py` exists and `server/handler.py` is outside `src/big_module/`, this is flagged as an encapsulation violation:

```
IMPORT_ERROR: server/handler.py:5 -- Encapsulation violation: external import from
internal module 'src.big_module.parser' -- consider importing from 'src.big_module' instead
```

This is an advisory diagnostic. The import itself works (the symbol exists at the internal path), so the exit code is 0 (no broken imports). The encapsulation violation appears in the output but does not cause CI failure.

---

## 5. Configuration Reference

All parameters are defined in `ImportCheckConfig` (`import_check/schemas.py`) and loaded by `_load_config()` in `import_check/__init__.py`.

### Configuration Sources (Precedence: highest to lowest)

1. **Programmatic API kwargs** -- `import_check.fix(source_dirs=["lib"])` overrides everything.
2. **CLI flags** -- `--source-dirs lib` overrides pyproject.toml.
3. **pyproject.toml** -- `[tool.import_check]` section.
4. **Built-in defaults** -- `ImportCheckConfig` dataclass field defaults.

### Parameter Table

| Parameter | Type | Default | Valid Options | Effect |
|-----------|------|---------|---------------|--------|
| `source_dirs` | `list[str]` | `["src", "server", "config"]` | Any directory names relative to project root | Directories scanned for Python files by `collect_python_files()` and `check_imports()`. Directories that do not exist are silently skipped (logged at DEBUG). |
| `exclude_patterns` | `list[str]` | `[".venv", "__pycache__", "node_modules"]` | Any fnmatch-style glob patterns | Paths matching any pattern are excluded from file collection. Patterns are checked against each path component individually, so `"__pycache__"` matches `src/__pycache__/module.pyc`. |
| `git_ref` | `str` | `"HEAD"` | Any valid git ref (SHA, branch, tag, `HEAD~N`) | The "before" state for inventory construction. Change this when comparing against a specific commit (e.g., before a multi-step refactoring). |
| `encapsulation_check` | `bool` | `True` | `True` / `False` | When `False`, encapsulation violation detection is skipped entirely. Use this to suppress advisory noise in projects that intentionally use direct internal imports. |
| `output_format` | `Literal["human", "json"]` | `"human"` | `"human"`, `"json"` | `"human"` produces readable text for terminal display. `"json"` produces machine-parseable JSON for CI pipelines and LLM consumers. |
| `log_level` | `str` | `"INFO"` | `"DEBUG"`, `"INFO"`, `"ERROR"` | Controls the `import_check` logger verbosity. `DEBUG` logs every file scanned and every migration detected. `INFO` logs summary statistics. `ERROR` logs only the structured error list. |
| `root` | `Path` | `Path.cwd()` | Any valid directory path | Project root directory. Resolved at runtime. All relative paths (source_dirs, file paths) are relative to this. |

### pyproject.toml Example

```toml
[tool.import_check]
source_dirs = ["src", "server", "lib"]
exclude_patterns = [".venv", "__pycache__", "node_modules", "migrations"]
git_ref = "HEAD"
encapsulation_check = true
output_format = "human"
log_level = "INFO"
```

---

## 6. Integration Contracts

### Programmatic API

**Entry points:** `import_check.fix()`, `import_check.check()`, `import_check.run()`

**Input contract:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `root` | `str | Path | None` | No (defaults to cwd) | Project root directory. Must be a git repository. |
| `**config_overrides` | keyword args | No | Any `ImportCheckConfig` field name. Unknown keys are silently ignored. |

**Output contract:**

| Function | Return Type | Fields |
|----------|-------------|--------|
| `fix()` | `FixResult` | `files_modified: list[str]`, `fixes_applied: int`, `errors: list[str]`, `skipped: list[str]` |
| `check()` | `list[ImportError]` | Each: `file_path, lineno, module, name, error_type, message` |
| `run()` | `RunResult` | `fix_result: FixResult`, `remaining_errors: list[ImportError]` |

All list fields are empty lists (never `None`) when there are no items.

### CLI Contract

**Entry point:** `python -m import_check [fix|check|run] [options]`

**Exit codes:**

| Code | Meaning |
|------|---------|
| 0 | No broken imports remaining (encapsulation violations do NOT cause non-zero) |
| 1 | Broken imports remain after fix |
| 2 | Invalid CLI arguments (from argparse) |

**JSON output contract** (with `--format json`):

```json
{
  "fix_result": {
    "files_modified": ["src/main.py"],
    "fixes_applied": 3,
    "errors": [],
    "skipped": []
  },
  "remaining_errors": [
    {
      "file_path": "src/broken.py",
      "lineno": 7,
      "module": "src.old_module",
      "name": "missing_func",
      "error_type": "module_not_found",
      "message": "Module 'src.old_module' not found"
    }
  ]
}
```

### External Dependencies

| Dependency | Version | Purpose | Failure Mode |
|------------|---------|---------|--------------|
| `git` | Any | `git diff --name-only`, `git show <ref>:<file>` | `RuntimeError` from `get_changed_files()`. Tool cannot operate without git. |
| `libcst` | Any compatible | CST parsing and transformation in `fixer.py` | `ImportError` at import time. Fix step cannot run without libcst. Check step does not require it. |
| `tomllib` (3.11+) / `tomli` | stdlib / any | Config loading from pyproject.toml | Falls through to defaults with a WARNING log. Tool still runs. |

---

## 7. Operational Notes

### Running the Tool

```bash
# Full pipeline: fix imports, then verify
python -m import_check run

# Fix only (skip verification)
python -m import_check fix

# Check only (CI gate -- no modifications)
python -m import_check check

# With options
python -m import_check run --source-dirs src lib --git-ref HEAD~3 --format json --log-level DEBUG

# Programmatic usage
from import_check import run
result = run(root="/path/to/project", source_dirs=["src"], git_ref="abc123")
```

### CI Integration (make dep-check style)

The tool is designed to integrate into CI pipelines as a check gate. The `check` subcommand is the primary CI target: it does not modify files and returns exit code 1 if broken imports exist.

```makefile
# In Makefile
import-check:
	python -m import_check check --format json --log-level ERROR

# Or as part of an existing all-check target
all-check:
	$(MAKE) py-compile-check
	$(MAKE) import-check
```

For CI pipelines that want automatic fixing followed by verification:

```makefile
import-fix-and-check:
	python -m import_check run --format json
```

The JSON output from `--format json` is suitable for downstream processing by CI reporting tools or LLM agents.

### Monitoring Signals

The tool uses the `import_check` logger. Key log patterns:

| Level | Pattern | Meaning |
|-------|---------|---------|
| INFO | `Found N changed files` | Number of files in the git diff (input scope) |
| INFO | `Built old inventory: N symbols` | Symbols extracted from git history |
| INFO | `Built new inventory: N symbols` | Symbols extracted from current files |
| INFO | `Migration map: N entries` | Number of detected symbol migrations |
| INFO | `Applying fixes to N files` | Files that will be processed by the fixer |
| INFO | `Fixed N import(s) in <file>` | Per-file fix summary |
| INFO | `Checking imports in N files` | Files that will be smoke-tested |
| INFO | `Found N import errors` | Total errors from the checker |
| ERROR | `IMPORT_ERROR: <file>:<line> -- <message>` | Individual broken import (structured for LLM consumption) |
| DEBUG | `move detected: <name> <old> -> <new>` | Individual migration detection |
| DEBUG | `rename detected: <old_name> -> <new_name> in <module>` | Rename detection |
| WARNING | `Syntax error parsing <file>: <details>` | File skipped due to parse failure |
| WARNING | `Cannot read <file>: <details>` | File skipped due to read failure |

### Failure Modes and Debug Paths

| Symptom | Likely Cause | Debug Path |
|---------|-------------|------------|
| `RuntimeError: git diff failed` | Not a git repo, invalid ref, git not installed | Verify `git status` works in the project root. Check that the `git_ref` value resolves (`git rev-parse <ref>`). |
| `Migration map: 0 entries` but imports are broken | Git ref is wrong (changes already committed) | Set `git_ref` to the commit before the refactoring started. Example: `--git-ref HEAD~5` or a specific SHA. |
| Fixer modifies nothing but checker finds errors | The broken import pattern is not in the migration map (e.g., rename + move simultaneously) | Run with `--log-level DEBUG` to see what the differ detected. The missing migration is a residual for Step 3 (LLM). |
| `libcst parse failed for <file>` | File uses syntax libcst cannot parse (rare edge cases) | Check libcst version. The file is skipped; other files are still processed. |
| Encapsulation violations reported but unwanted | Project intentionally uses direct internal imports | Disable with `--no-encapsulation-check` or set `encapsulation_check = false` in pyproject.toml. |
| Checker reports false positive (symbol exists but reported as missing) | Symbol is defined via dynamic mechanisms (metaclass, `__getattr__`, import hook) | The checker only sees static AST definitions. Symbols created at runtime are invisible. Add the module to `exclude_patterns` or fix the import to use the static re-export path. |

---

## 8. Known Limitations

1. **Rename + move simultaneously is not detected.** If a symbol is both renamed and moved to a different file in the same refactoring, the differ cannot match old to new (the name changed and the location changed). This is a residual for Step 3 (LLM fix). The checker will report it as a broken import.

2. **Dynamic string construction is flagged but not fixed.** `importlib.import_module(f"src.{name}.module")` and similar dynamic constructions cannot be resolved statically. The fixer does not attempt to rewrite them.

3. **Cross-function dataflow is not tracked.** The simple dataflow analysis for string variable assignments is bounded to single-assignment literals within the same function scope. A variable assigned in one function and used in another is not tracked.

4. **Non-Python config files are not scanned.** YAML, JSON, or TOML files that reference Python module paths (e.g., Temporal workflow definitions, Django settings) are not checked or fixed.

5. **Runtime-defined symbols are invisible to the checker.** Symbols created by metaclasses, `__getattr__` on modules, or import hooks are not visible to `ast.parse()`. The checker may report false positives for imports of such symbols.

6. **`_RENAME_LINE_PROXIMITY` is not configurable.** The 30-line threshold for rename detection is a compile-time constant. Projects with very long files where renamed symbols move far from their original line may not have renames detected.

7. **Relative imports are skipped entirely.** The checker does not verify relative imports (`from .foo import bar`). These are assumed to be correct since they resolve within the package.

8. **No incremental caching.** The tool rebuilds inventories from scratch on every run. For very large codebases with frequent small refactorings, caching the inventory between runs could improve performance.

---

## 9. Extension Guide

### Adding Support for a New Import Pattern

To add detection/fixing for a new pattern (e.g., Django `urlpatterns` string references):

1. **Identify the AST/CST node type** for the pattern. Use `ast.dump()` or `libcst.parse_module().children` to inspect how the pattern appears in the tree.

2. **Add a new libcst transformer** in `import_check/fixer.py`:
   - Create a class inheriting from `cst.CSTTransformer`.
   - Implement `leave_<NodeType>()` methods that match the pattern and rewrite using the migration map.
   - Follow the existing pattern: constructor takes `migration_map`, builds a lookup table, and tracks `fixes_applied` count.

3. **Register the transformer** in `apply_fixes()`:
   ```python
   new_rewriter = _build_new_rewriter(migration_map)
   transformers = [import_rewriter, string_rewriter, all_rewriter, new_rewriter]
   ```

4. **Add detection to the checker** if the pattern can also be verified (optional):
   - Add a new check in `check_imports()` after the existing import/symbol/encapsulation checks.
   - Use `ast.walk()` to find the relevant nodes.

5. **Update schemas** if a new error type is needed:
   - Add a value to `ImportErrorType` enum in `schemas.py`.

6. **Common pitfalls:**
   - Always create fresh transformer instances per file (not shared across files).
   - Use `_extract_simple_string_value()` for string extraction -- it handles quote styles and concatenation.
   - Use `_make_simple_string()` for string replacement -- it preserves the original quote style.
   - Test with files that contain the pattern at various nesting depths (top-level, inside functions, inside classes).

### Adding a New Migration Detection Pattern

To add a new pattern to the differ (e.g., detecting symbol type changes):

1. **Add a new migration type** to `MigrationEntry.migration_type` literal in `schemas.py`.

2. **Add a detection phase** in `differ.py`:
   - Create `_detect_<pattern>(old, new, already_matched)` following the existing phase structure.
   - Update `already_matched` with detected entries to prevent double-counting.
   - Insert the call in `diff_inventories()` after the existing phases.

3. **Ensure the fixer handles the new type.** Check that `ImportRewriter`, `StringRefRewriter`, and `AllListRewriter` lookup tables include entries of the new type. In most cases, the existing transformers handle any `MigrationEntry` regardless of `migration_type` -- the type field is informational.

### Adding a New Configuration Parameter

1. **Add the field** to `ImportCheckConfig` in `schemas.py` with a default value.

2. **Add the CLI flag** in `__main__.py`'s `_build_parser()`.

3. **Map the CLI arg** to the config override dict in `main()`.

4. **Use the config value** in the module that needs it (access via `config.<field_name>`).

5. **Document** the parameter in the pyproject.toml example and this engineering guide's Configuration Reference.

---

## Appendix: Requirement Coverage

| Spec Requirement | Covered By (Module Section) |
|------------------|-----------------------------|
| REQ-101 | `import_check/inventory.py` -- Symbol Inventory Builder |
| REQ-103 | `import_check/inventory.py` -- Symbol Inventory Builder |
| REQ-105 | `import_check/inventory.py` -- Symbol Inventory Builder |
| REQ-107 | `import_check/inventory.py` -- Symbol Inventory Builder |
| REQ-109 | `import_check/differ.py` -- Inventory Differ |
| REQ-111 | `import_check/inventory.py` -- Symbol Inventory Builder |
| REQ-201 | `import_check/fixer.py` -- Import Rewriter |
| REQ-203 | `import_check/fixer.py` -- Import Rewriter |
| REQ-205 | `import_check/fixer.py` -- Import Rewriter |
| REQ-207 | `import_check/fixer.py` -- Import Rewriter (libcst walks all depths) + `import_check/checker.py` (ast.walk for detection) |
| REQ-209 | `import_check/fixer.py` -- Import Rewriter (AllListRewriter) |
| REQ-211 | `import_check/fixer.py` -- Import Rewriter (StringRefRewriter) |
| REQ-213 | `import_check/fixer.py` -- Import Rewriter (StringRefRewriter dataflow) |
| REQ-215 | `import_check/fixer.py` -- Import Rewriter (libcst formatting preservation) |
| REQ-217 | Not fully implemented -- dynamic string references are not flagged in output. See Known Limitations. |
| REQ-301 | `import_check/checker.py` -- Smoke Test Checker |
| REQ-303 | `import_check/checker.py` -- Smoke Test Checker (ast-only, no runtime imports) |
| REQ-305 | `import_check/checker.py` -- Smoke Test Checker (encapsulation check) |
| REQ-307 | `import_check/checker.py` -- Smoke Test Checker (report-only, no auto-fix) |
| REQ-309 | `import_check/checker.py` -- Smoke Test Checker (structured ImportError records) |
| REQ-311 | Partially implemented -- individual errors are reported but aggregate summary statistics (total_checked, passed, broken) are not computed as separate fields. |
| REQ-401 | `import_check/__init__.py` -- Public API Facade |
| REQ-403 | `import_check/__main__.py` -- CLI Entry Point |
| REQ-405 | `import_check/__main__.py` -- CLI Entry Point (human + json formats) |
| REQ-407 | `import_check/__init__.py` -- Public API Facade (kwargs override) |
| REQ-409 | `import_check/__init__.py` -- Public API Facade (typed result objects) |
| REQ-411 | `import_check/__main__.py` -- CLI Entry Point (exit codes 0/1) |
| REQ-501 | `import_check/__init__.py` -- Public API Facade (pyproject.toml loading) |
| REQ-503 | `import_check/schemas.py` -- Typed Contracts (ImportCheckConfig fields) |
| REQ-505 | `import_check/__init__.py` -- Public API Facade (3-layer precedence) |
| REQ-507 | Partially implemented -- invalid output_format and log_level values are constrained by Literal types and argparse choices, but non-existent source_dirs are silently skipped rather than failing fast. Invalid git refs raise RuntimeError. |
| REQ-509 | `import_check/__main__.py` -- CLI Entry Point (all flags implemented) |
| REQ-901 | Architecture: git-diff scoping keeps runtime proportional to refactoring size |
| REQ-903 | Architecture: no project-specific assumptions, works on any git-based Python project |
| REQ-905 | Architecture: sole external dependency is libcst |
| REQ-907 | `import_check/schemas.py` -- all parameters externalized to ImportCheckConfig |
| REQ-909 | All modules: structured logging at DEBUG/INFO/ERROR levels |
