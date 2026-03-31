# Import Check Tool — Implementation Docs

> **For implement-code agents:** This document is your source of truth.
> Read ONLY your assigned task section. Your section contains your FR context,
> Phase 0 contracts inlined, implementation steps, and isolation contract verbatim.
> Do not read the full document, the spec, the design doc, or other task sections.

**Goal:** Build a generic, portable Python tool (`import_check`) that automatically detects and fixes broken imports after code refactoring, using a 3-step pipeline: deterministic fix using `ast` + `libcst`, smoke test verification, and structured error output for LLM-assisted residual fix.
**Spec:** `docs/superpowers/specs/2026-03-28-import-check-tool-sketch.md`
**Design doc:** `docs/superpowers/specs/2026-03-28-import-check-tool-sketch.md` (sketch serves as combined spec/design)
**Output path:** `docs/import_check/IMPORT_CHECK_IMPLEMENTATION.md`
**Produced by:** write-implementation-docs
**Phase 0 status:** [ ] Awaiting human review

---

## Phase 0: Contract Definitions

> **Human review gate:** Approve this section before any implement-code task begins.
> Every task section inlines these contracts. A mistake here propagates to every task.

This section defines all shared type surfaces, data structures, function stubs, error taxonomy, and integration contracts for the import_check tool.

---

### Data Structures — `import_check/schemas.py`

```python
"""Shared data structures for the import_check tool.

All typed contracts used across inventory, differ, checker, and fixer modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Literal


# ---------------------------------------------------------------------------
# Symbol inventory types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SymbolInfo:
    """A single exported symbol discovered by AST scanning.

    Attributes:
        name: Symbol name as it appears in source (e.g., "MyClass").
        module_path: Dotted module path (e.g., "src.retrieval.engine").
        file_path: Absolute or root-relative filesystem path to the source file.
        lineno: 1-based line number where the symbol is defined.
        symbol_type: Category of the symbol.
    """

    name: str
    module_path: str
    file_path: str
    lineno: int
    symbol_type: Literal["function", "class", "variable"]


# Key is symbol name; value is list of SymbolInfo (handles same name in multiple modules).
SymbolInventory = dict[str, list[SymbolInfo]]
"""Symbol name → list of locations where that symbol is defined.

Multiple entries for the same name means the symbol exists in more than one module
(common after splits or when different modules define identically-named helpers).
"""


# ---------------------------------------------------------------------------
# Migration types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MigrationEntry:
    """One symbol's migration from old location to new location.

    Attributes:
        old_module: Dotted module path before the refactor.
        old_name: Symbol name before the refactor.
        new_module: Dotted module path after the refactor.
        new_name: Symbol name after the refactor (same as old_name for pure moves).
        migration_type: Category of change detected by the differ.
    """

    old_module: str
    old_name: str
    new_module: str
    new_name: str
    migration_type: Literal["move", "rename", "split", "merge"]


# ---------------------------------------------------------------------------
# Import error types
# ---------------------------------------------------------------------------

class ImportErrorType(Enum):
    """Categories of import errors detected by the checker."""

    MODULE_NOT_FOUND = "module_not_found"
    SYMBOL_NOT_DEFINED = "symbol_not_defined"
    ENCAPSULATION_VIOLATION = "encapsulation_violation"


@dataclass(frozen=True)
class ImportError:
    """A single broken or suspicious import detected by the checker.

    Attributes:
        file_path: File containing the broken import.
        lineno: 1-based line number of the import statement.
        module: The module being imported from.
        name: The symbol name being imported (empty string for bare module imports).
        error_type: Category of the error.
        message: Human-readable description of the problem.
    """

    file_path: str
    lineno: int
    module: str
    name: str
    error_type: ImportErrorType
    message: str


# ---------------------------------------------------------------------------
# Fix result types
# ---------------------------------------------------------------------------

@dataclass
class FixResult:
    """Result of applying fixes to a set of files.

    Attributes:
        files_modified: List of file paths that were rewritten.
        fixes_applied: Number of individual import statements rewritten.
        errors: List of issues encountered during fixing (non-fatal).
        skipped: List of import locations that could not be auto-fixed
            (e.g., dynamic string construction).
    """

    files_modified: list[str] = field(default_factory=list)
    fixes_applied: int = 0
    errors: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


@dataclass
class RunResult:
    """Combined result of fix + check pipeline.

    Attributes:
        fix_result: Result from the fix phase.
        remaining_errors: Errors that persist after fixing.
    """

    fix_result: FixResult
    remaining_errors: list[ImportError] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class ImportCheckConfig:
    """Configuration for the import_check tool.

    All fields have sensible defaults. Can be populated from pyproject.toml
    [tool.import_check], CLI flags, or programmatic kwargs.

    Attributes:
        source_dirs: Directories to scan for Python files.
        exclude_patterns: Glob patterns to exclude from scanning.
        git_ref: Git ref for the "before" state inventory.
        encapsulation_check: Enable encapsulation violation reporting.
        output_format: Output format — "human" or "json".
        log_level: Logging verbosity.
        root: Project root directory (resolved at runtime).
    """

    source_dirs: list[str] = field(default_factory=lambda: ["src", "server", "config"])
    exclude_patterns: list[str] = field(
        default_factory=lambda: [".venv", "__pycache__", "node_modules"]
    )
    git_ref: str = "HEAD"
    encapsulation_check: bool = True
    output_format: Literal["human", "json"] = "human"
    log_level: str = "INFO"
    root: Path = field(default_factory=Path.cwd)
```

---

### Function Stubs

#### `inventory.py` — `import_check/inventory.py`

```python
"""Symbol inventory builder using AST analysis.

Scans Python source files and extracts all top-level symbol definitions
(functions, classes, module-level variables) into a SymbolInventory.
Can build inventories from current files or from git history.
"""

from __future__ import annotations

import ast
from pathlib import Path

from .schemas import SymbolInfo, SymbolInventory


def _file_to_module_path(file_path: str, root: Path) -> str:
    """Convert a filesystem path to a dotted Python module path.

    Args:
        file_path: Path to a .py file, relative to root.
        root: Project root directory.

    Returns:
        Dotted module path (e.g., "src.retrieval.engine").
        __init__.py files map to the package path (e.g., "src.retrieval").
    """
    raise NotImplementedError("Task 1")


def _extract_symbols(source: str, file_path: str, module_path: str) -> list[SymbolInfo]:
    """Parse Python source and extract all top-level symbol definitions.

    Extracts FunctionDef, AsyncFunctionDef, ClassDef at module level,
    and simple Assign/AnnAssign targets (Name nodes) at module level.
    Skips private symbols (leading underscore) unless they are __all__.

    Args:
        source: Python source code string.
        file_path: Filesystem path (for SymbolInfo.file_path).
        module_path: Dotted module path (for SymbolInfo.module_path).

    Returns:
        List of SymbolInfo for each discovered symbol.

    Raises:
        SyntaxError: If source cannot be parsed by ast.parse().
    """
    raise NotImplementedError("Task 1")


def build_inventory(files: list[str], root: Path) -> SymbolInventory:
    """Build a symbol inventory from current filesystem files.

    Reads each file, parses with ast, and collects all top-level symbols.
    Files that fail to parse are logged at WARNING and skipped.

    Args:
        files: List of Python file paths (relative to root).
        root: Project root directory.

    Returns:
        SymbolInventory mapping symbol names to their locations.
    """
    raise NotImplementedError("Task 1")


def build_old_inventory(files: list[str], git_ref: str) -> SymbolInventory:
    """Build a symbol inventory from a previous git state.

    Uses `git show <ref>:<file>` to retrieve file contents at the given
    ref. Files that do not exist at the ref are silently skipped.

    Args:
        files: List of Python file paths to retrieve from git.
        git_ref: Git reference (commit SHA, branch, tag, "HEAD").

    Returns:
        SymbolInventory for the historical state.

    Raises:
        RuntimeError: If git is not available or the ref is invalid.
    """
    raise NotImplementedError("Task 1")


def collect_python_files(source_dirs: list[str], root: Path, exclude_patterns: list[str]) -> list[str]:
    """Collect all Python files from the specified source directories.

    Walks each source_dir under root, collecting .py files while
    excluding paths matching any of the exclude_patterns (glob-style).

    Args:
        source_dirs: Directory names to scan (relative to root).
        root: Project root directory.
        exclude_patterns: Glob patterns for paths to exclude.

    Returns:
        Sorted list of Python file paths relative to root.
    """
    raise NotImplementedError("Task 1")


def get_changed_files(git_ref: str, root: Path) -> list[str]:
    """Get list of Python files changed since the given git ref.

    Uses `git diff --name-only <ref>` to find changed files, then
    filters to .py files only.

    Args:
        git_ref: Git reference to diff against.
        root: Project root directory.

    Returns:
        List of changed .py file paths relative to root.

    Raises:
        RuntimeError: If git is not available.
    """
    raise NotImplementedError("Task 1")
```

#### `differ.py` — `import_check/differ.py`

```python
"""Inventory differ — detects symbol migrations between old and new states.

Compares two SymbolInventory objects and produces a list of MigrationEntry
records describing how symbols moved, were renamed, split, or merged.
"""

from __future__ import annotations

from .schemas import MigrationEntry, SymbolInventory


def diff_inventories(old: SymbolInventory, new: SymbolInventory) -> list[MigrationEntry]:
    """Diff two symbol inventories to detect migrations.

    Detection strategy:
    1. MOVE: Symbol with same name exists in old and new but different module_path.
    2. RENAME: Symbol disappeared from old module; a new symbol appeared in
       the same module with no other explanation. Uses heuristic: same file,
       same symbol_type, close line number.
    3. SPLIT: Symbol from one old module now appears in multiple new modules.
    4. MERGE: Symbols from multiple old modules now appear in one new module.

    Symbols present in both inventories at the same location are ignored
    (no migration needed). Symbols only in old (deleted) or only in new
    (added) are not migrations — they are not included in the output.

    Args:
        old: Symbol inventory from the previous git state.
        new: Symbol inventory from the current filesystem state.

    Returns:
        List of MigrationEntry records. Empty if no migrations detected.
    """
    raise NotImplementedError("Task 2")


def _detect_moves(old: SymbolInventory, new: SymbolInventory) -> list[MigrationEntry]:
    """Detect symbols that moved between modules (same name, different path).

    Args:
        old: Old inventory.
        new: New inventory.

    Returns:
        List of move MigrationEntry records.
    """
    raise NotImplementedError("Task 2")


def _detect_renames(
    old: SymbolInventory, new: SymbolInventory, already_matched: set[tuple[str, str]]
) -> list[MigrationEntry]:
    """Detect symbols that were renamed within the same module.

    Uses heuristics: same file, same symbol_type, close line number,
    and the old symbol no longer exists while a new one appeared.

    Args:
        old: Old inventory.
        new: New inventory.
        already_matched: Set of (name, module_path) tuples already explained
            by move detection — skip these.

    Returns:
        List of rename MigrationEntry records.
    """
    raise NotImplementedError("Task 2")


def _detect_splits_and_merges(
    old: SymbolInventory, new: SymbolInventory, already_matched: set[tuple[str, str]]
) -> list[MigrationEntry]:
    """Detect one-to-many (split) and many-to-one (merge) migrations.

    A split is when symbols from one old file now appear across multiple
    new files. A merge is the reverse.

    Args:
        old: Old inventory.
        new: New inventory.
        already_matched: Already-explained migrations to skip.

    Returns:
        List of split/merge MigrationEntry records.
    """
    raise NotImplementedError("Task 2")
```

#### `checker.py` — `import_check/checker.py`

```python
"""Import checker — smoke test for broken imports.

Walks Python files, parses imports with ast, and verifies:
1. The target module exists as a file on the filesystem.
2. The imported symbol is defined in the target module.
3. (Optional) The import does not violate encapsulation boundaries.

No importlib.import_module() calls — purely filesystem + AST based.
"""

from __future__ import annotations

import ast
from pathlib import Path

from .schemas import ImportCheckConfig, ImportError, ImportErrorType


def check_imports(files: list[str], root: Path, config: ImportCheckConfig | None = None) -> list[ImportError]:
    """Check all imports in the given files for errors.

    For each import statement, verifies:
    1. The target module resolves to an existing .py file or package __init__.py.
    2. For `from X import Y`, symbol Y is defined in module X.
    3. If config.encapsulation_check is True, flags imports that bypass
       __init__.py to reach internal modules directly.

    Args:
        files: List of Python file paths to check (relative to root).
        root: Project root directory.
        config: Optional configuration. Uses defaults if None.

    Returns:
        List of ImportError records. Empty if all imports are clean.
    """
    raise NotImplementedError("Task 3")


def _resolve_module_to_file(module: str, root: Path) -> Path | None:
    """Resolve a dotted module path to a filesystem path.

    Checks for both `module/as/path.py` and `module/as/path/__init__.py`.
    Returns None if the module cannot be resolved to an existing file.

    Args:
        module: Dotted module path (e.g., "src.retrieval.engine").
        root: Project root directory.

    Returns:
        Path to the source file, or None if not found.
    """
    raise NotImplementedError("Task 3")


def _extract_imports(source: str) -> list[tuple[str, str, int]]:
    """Parse Python source and extract all import statements.

    Handles:
    - `from X import Y` → (X, Y, lineno)
    - `from X import Y as Z` → (X, Y, lineno) (alias ignored for checking)
    - `import X` → (X, "", lineno)
    - Imports inside functions (lazy imports)
    - Imports inside TYPE_CHECKING blocks
    - Imports inside try/except blocks

    Args:
        source: Python source code string.

    Returns:
        List of (module, name, lineno) tuples.
    """
    raise NotImplementedError("Task 3")


def _check_symbol_defined(module_file: Path, symbol_name: str) -> bool:
    """Check if a symbol is defined in the given module file.

    Parses the file with ast and checks for FunctionDef, ClassDef,
    Assign, AnnAssign, and ImportFrom (re-exports) at module level.
    Also checks __all__ if present.

    Args:
        module_file: Path to the module source file.
        symbol_name: Name to look for.

    Returns:
        True if the symbol is defined or re-exported in the module.
    """
    raise NotImplementedError("Task 3")


def _check_encapsulation(module: str, file_path: str, root: Path) -> ImportError | None:
    """Check if an import violates encapsulation boundaries.

    An encapsulation violation is when an external caller imports from an
    internal module (e.g., `from src.retrieval.nodes.query import X`) instead
    of from the package's __init__.py (e.g., `from src.retrieval import X`).

    Only applies to imports that cross package boundaries — intra-package
    imports are allowed.

    Args:
        module: Dotted module path being imported.
        file_path: File containing the import statement.
        root: Project root directory.

    Returns:
        ImportError if encapsulation is violated, None otherwise.
    """
    raise NotImplementedError("Task 3")
```

#### `fixer.py` — `import_check/fixer.py`

```python
"""Import fixer — rewrites broken imports using libcst.

Takes a migration map (from differ.py) and rewrites import statements
across target files. Uses libcst to preserve formatting, comments, and
whitespace. Also handles string-based references in mock.patch() and
importlib.import_module() calls, and __all__ list updates.
"""

from __future__ import annotations

from pathlib import Path

from .schemas import FixResult, MigrationEntry


def apply_fixes(
    migration_map: list[MigrationEntry],
    target_files: list[str],
    root: Path,
) -> FixResult:
    """Apply import fixes to target files based on the migration map.

    For each target file:
    1. Parse with libcst.
    2. Walk ImportFrom and Import nodes, matching against migration_map.
    3. Rewrite matched imports to use the new module/name.
    4. Walk Call nodes for mock.patch() and importlib.import_module() string args.
    5. Walk Assign nodes for __all__ list updates.
    6. Write back the modified source if any changes were made.

    Files that fail to parse with libcst are logged and skipped.
    Individual fix failures within a file do not abort the entire file.

    Args:
        migration_map: List of MigrationEntry from differ.diff_inventories().
        target_files: List of Python file paths to fix (relative to root).
        root: Project root directory.

    Returns:
        FixResult summarizing what was changed and what was skipped.
    """
    raise NotImplementedError("Task 4")


def _build_import_rewriter(migration_map: list[MigrationEntry]) -> "ImportRewriter":
    """Build a libcst transformer that rewrites import statements.

    Creates a CSTTransformer subclass that matches ImportFrom and Import
    nodes against the migration map and produces rewritten nodes.

    Args:
        migration_map: List of migrations to apply.

    Returns:
        A libcst CSTTransformer instance.
    """
    raise NotImplementedError("Task 4")


def _build_string_ref_rewriter(migration_map: list[MigrationEntry]) -> "StringRefRewriter":
    """Build a libcst transformer that rewrites string-based references.

    Matches:
    - mock.patch("old.module.path") → mock.patch("new.module.path")
    - importlib.import_module("old.module") → importlib.import_module("new.module")
    - Simple single-assignment string literals in the same function scope
      (e.g., path = "old.module"; importlib.import_module(path))

    Args:
        migration_map: List of migrations to apply.

    Returns:
        A libcst CSTTransformer instance.
    """
    raise NotImplementedError("Task 4")


def _build_all_rewriter(migration_map: list[MigrationEntry]) -> "AllListRewriter":
    """Build a libcst transformer that updates __all__ lists.

    Matches __all__ = [...] assignments and updates string entries
    that correspond to renamed symbols in the migration map.

    Args:
        migration_map: List of migrations to apply.

    Returns:
        A libcst CSTTransformer instance.
    """
    raise NotImplementedError("Task 4")


def _apply_transformers_to_file(
    file_path: Path,
    transformers: list,
) -> tuple[bool, list[str]]:
    """Parse a file with libcst, apply transformers, and write back if changed.

    Args:
        file_path: Path to the Python source file.
        transformers: List of libcst CSTTransformer instances to apply sequentially.

    Returns:
        Tuple of (was_modified: bool, errors: list[str]).
        errors contains descriptions of any non-fatal issues encountered.
    """
    raise NotImplementedError("Task 4")
```

#### `__init__.py` — `import_check/__init__.py`

```python
"""import_check — detect and fix broken Python imports after refactoring.

Public API:
    fix(root, **config)   — apply deterministic fixes from symbol inventory diff
    check(root, **config) — smoke test all imports for remaining errors
    run(root, **config)   — fix then check (full pipeline)

Exports: fix, check, run, ImportCheckConfig, RunResult, FixResult, ImportError
Deps: import_check.inventory, import_check.differ, import_check.checker, import_check.fixer
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .schemas import (
    FixResult,
    ImportCheckConfig,
    ImportError,
    RunResult,
)


def _load_config(root: Path, **overrides: Any) -> ImportCheckConfig:
    """Load configuration from pyproject.toml and apply overrides.

    Resolution order (highest priority first):
    1. Keyword argument overrides
    2. pyproject.toml [tool.import_check] section
    3. ImportCheckConfig defaults

    Args:
        root: Project root directory (used to locate pyproject.toml).
        **overrides: Keyword arguments matching ImportCheckConfig fields.

    Returns:
        Fully resolved ImportCheckConfig.
    """
    raise NotImplementedError("Task 5")


def _setup_logging(config: ImportCheckConfig) -> None:
    """Configure logging for the import_check tool.

    Sets up a logger named "import_check" with the configured log level.
    Uses a simple format: "%(levelname)s: %(message)s".

    Args:
        config: Configuration containing log_level.
    """
    raise NotImplementedError("Task 5")


def fix(root: Path | str | None = None, **config_overrides: Any) -> FixResult:
    """Apply deterministic import fixes based on symbol inventory diff.

    Pipeline:
    1. Resolve root directory (default: cwd).
    2. Load config from pyproject.toml + overrides.
    3. Collect changed Python files via git diff.
    4. Build old inventory (from git_ref) and new inventory (from filesystem).
    5. Diff inventories to produce migration map.
    6. Apply fixes to all Python files in source_dirs.

    Args:
        root: Project root directory. Defaults to Path.cwd().
        **config_overrides: Override any ImportCheckConfig field.

    Returns:
        FixResult summarizing changes made.

    Raises:
        RuntimeError: If git is not available.
    """
    raise NotImplementedError("Task 5")


def check(root: Path | str | None = None, **config_overrides: Any) -> list[ImportError]:
    """Smoke test all imports for errors.

    Scans all Python files in source_dirs and verifies every import
    statement resolves to an existing module and symbol.

    Args:
        root: Project root directory. Defaults to Path.cwd().
        **config_overrides: Override any ImportCheckConfig field.

    Returns:
        List of ImportError records. Empty if all imports are clean.
    """
    raise NotImplementedError("Task 5")


def run(root: Path | str | None = None, **config_overrides: Any) -> RunResult:
    """Full pipeline: fix then check.

    Runs fix() first, then check() to find remaining errors.
    Returns combined result.

    Args:
        root: Project root directory. Defaults to Path.cwd().
        **config_overrides: Override any ImportCheckConfig field.

    Returns:
        RunResult with fix_result and remaining_errors.
    """
    raise NotImplementedError("Task 5")
```

#### `__main__.py` — `import_check/__main__.py`

```python
"""CLI entry point for import_check.

Usage:
    python -m import_check [fix|check|run] [options]

Subcommands:
    fix    — apply deterministic import fixes
    check  — smoke test all imports
    run    — fix then check (default)

Options are mapped to ImportCheckConfig fields.
"""

from __future__ import annotations


def main() -> int:
    """Parse CLI arguments and dispatch to the appropriate command.

    Returns:
        Exit code: 0 if no errors, 1 if import errors remain after fix.
    """
    raise NotImplementedError("Task 6")


def _build_parser() -> "argparse.ArgumentParser":
    """Build the argument parser for import_check CLI.

    Subcommands: fix, check, run (default).
    Global options: --source-dirs, --exclude, --git-ref,
        --no-encapsulation-check, --format, --log-level, --root.

    Returns:
        Configured ArgumentParser.
    """
    raise NotImplementedError("Task 6")


def _format_output(result: "RunResult | FixResult | list[ImportError]", fmt: str) -> str:
    """Format a result object for terminal output.

    Args:
        result: The result to format.
        fmt: Output format — "human" or "json".

    Returns:
        Formatted string ready for print().
    """
    raise NotImplementedError("Task 6")
```

---

### Error Taxonomy

| Error Type | Trigger Condition | Expected Message Format | Retryable | Raising Module |
|---|---|---|---|---|
| `SyntaxError` | Python file cannot be parsed by `ast.parse()` | `"Failed to parse {file_path}: {detail}"` | No | `import_check/inventory.py`, `import_check/checker.py` |
| `RuntimeError` | Git not available or git ref invalid | `"Git error: {detail}"` | No | `import_check/inventory.py` |
| `RuntimeError` | Git `show` fails for a file at a ref | `"Cannot retrieve {file} at ref {ref}: {detail}"` | No | `import_check/inventory.py` |
| `ImportErrorType.MODULE_NOT_FOUND` | Imported module does not resolve to a .py file | `"Module '{module}' not found on filesystem"` | No | `import_check/checker.py` |
| `ImportErrorType.SYMBOL_NOT_DEFINED` | Symbol not defined in target module | `"Symbol '{name}' not defined in module '{module}'"` | No | `import_check/checker.py` |
| `ImportErrorType.ENCAPSULATION_VIOLATION` | External import bypasses `__init__.py` | `"Encapsulation violation: '{module}' should be imported via package __init__"` | No | `import_check/checker.py` |
| `libcst.ParserSyntaxError` | File cannot be parsed by libcst | `"libcst parse failed for {file_path}: {detail}"` | No | `import_check/fixer.py` |
| `ValueError` | Invalid config values (contradictory settings) | `"Invalid config: {detail}"` | No | `import_check/__init__.py` |

---

### Integration Contracts

```
__init__.fix() → inventory.get_changed_files(git_ref, root) → list[str]
  Called when: at pipeline start to determine scope
  On RuntimeError: fix() surfaces to caller unchanged

__init__.fix() → inventory.collect_python_files(source_dirs, root, exclude) → list[str]
  Called when: to determine full file set for fixing
  On error: fix() surfaces to caller unchanged

__init__.fix() → inventory.build_old_inventory(changed_files, git_ref) → SymbolInventory
  Called when: after collecting changed files
  On RuntimeError: fix() surfaces to caller unchanged

__init__.fix() → inventory.build_inventory(changed_files, root) → SymbolInventory
  Called when: after building old inventory
  On SyntaxError in individual files: inventory logs WARNING and skips file (non-fatal)

__init__.fix() → differ.diff_inventories(old_inv, new_inv) → list[MigrationEntry]
  Called when: after both inventories are built
  On empty result: fix() returns FixResult with 0 fixes (no migration detected)

__init__.fix() → fixer.apply_fixes(migration_map, all_files, root) → FixResult
  Called when: after migration map is produced
  On libcst parse failures: fixer logs error and skips file (non-fatal, reported in FixResult.errors)

__init__.check() → inventory.collect_python_files(source_dirs, root, exclude) → list[str]
  Called when: at check start

__init__.check() → checker.check_imports(files, root, config) → list[ImportError]
  Called when: after collecting files
  On SyntaxError in individual files: checker logs WARNING and skips file (non-fatal)

__init__.run() → __init__.fix(root, **overrides) → FixResult
  Called when: first phase of run
  On RuntimeError: run() surfaces to caller unchanged

__init__.run() → __init__.check(root, **overrides) → list[ImportError]
  Called when: after fix phase completes
  Returns: remaining errors as RunResult.remaining_errors
```

---

### Pure Utilities

```python
def module_path_to_file_candidates(module: str, root: Path) -> list[Path]:
    """Convert a dotted module path to possible filesystem paths.

    Returns two candidates:
    1. root / module.replace(".", "/") + ".py"
    2. root / module.replace(".", "/") / "__init__.py"

    Args:
        module: Dotted module path.
        root: Project root directory.

    Returns:
        List of candidate Path objects (not checked for existence).
    """
    parts = module.replace(".", "/")
    return [
        root / (parts + ".py"),
        root / parts / "__init__.py",
    ]
```

---

## Task 1: Symbol Inventory Builder

**Description:** Implement the symbol inventory module that scans Python source files using `ast` to extract all top-level symbol definitions (functions, classes, module-level variables) and builds a `SymbolInventory` mapping. The module also supports building inventories from historical git states using `git show`, and provides utilities for collecting Python files and detecting changed files.

**Spec requirements:** FR-1, FR-2

**Dependencies:** none

**Source files:**
- CREATE `import_check/schemas.py`
- CREATE `import_check/inventory.py`

---

**Phase 0 contracts (inlined -- implement these stubs):**

```python
# --- import_check/schemas.py (full implementation — data structures) ---

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class SymbolInfo:
    """A single exported symbol discovered by AST scanning.

    Attributes:
        name: Symbol name as it appears in source (e.g., "MyClass").
        module_path: Dotted module path (e.g., "src.retrieval.engine").
        file_path: Absolute or root-relative filesystem path to the source file.
        lineno: 1-based line number where the symbol is defined.
        symbol_type: Category of the symbol.
    """

    name: str
    module_path: str
    file_path: str
    lineno: int
    symbol_type: Literal["function", "class", "variable"]


SymbolInventory = dict[str, list[SymbolInfo]]


@dataclass(frozen=True)
class MigrationEntry:
    """One symbol's migration from old location to new location."""

    old_module: str
    old_name: str
    new_module: str
    new_name: str
    migration_type: Literal["move", "rename", "split", "merge"]


class ImportErrorType(Enum):
    MODULE_NOT_FOUND = "module_not_found"
    SYMBOL_NOT_DEFINED = "symbol_not_defined"
    ENCAPSULATION_VIOLATION = "encapsulation_violation"


@dataclass(frozen=True)
class ImportError:
    """A single broken or suspicious import detected by the checker."""

    file_path: str
    lineno: int
    module: str
    name: str
    error_type: ImportErrorType
    message: str


@dataclass
class FixResult:
    files_modified: list[str] = field(default_factory=list)
    fixes_applied: int = 0
    errors: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


@dataclass
class RunResult:
    fix_result: FixResult
    remaining_errors: list[ImportError] = field(default_factory=list)


@dataclass
class ImportCheckConfig:
    source_dirs: list[str] = field(default_factory=lambda: ["src", "server", "config"])
    exclude_patterns: list[str] = field(
        default_factory=lambda: [".venv", "__pycache__", "node_modules"]
    )
    git_ref: str = "HEAD"
    encapsulation_check: bool = True
    output_format: Literal["human", "json"] = "human"
    log_level: str = "INFO"
    root: Path = field(default_factory=Path.cwd)
```

```python
# --- import_check/inventory.py stubs ---

from __future__ import annotations

import ast
from pathlib import Path

from .schemas import SymbolInfo, SymbolInventory


def _file_to_module_path(file_path: str, root: Path) -> str:
    """Convert a filesystem path to a dotted Python module path.

    Args:
        file_path: Path to a .py file, relative to root.
        root: Project root directory.

    Returns:
        Dotted module path (e.g., "src.retrieval.engine").
        __init__.py files map to the package path (e.g., "src.retrieval").
    """
    raise NotImplementedError("Task 1")


def _extract_symbols(source: str, file_path: str, module_path: str) -> list[SymbolInfo]:
    """Parse Python source and extract all top-level symbol definitions.

    Extracts FunctionDef, AsyncFunctionDef, ClassDef at module level,
    and simple Assign/AnnAssign targets (Name nodes) at module level.
    Skips private symbols (leading underscore) unless they are __all__.

    Args:
        source: Python source code string.
        file_path: Filesystem path (for SymbolInfo.file_path).
        module_path: Dotted module path (for SymbolInfo.module_path).

    Returns:
        List of SymbolInfo for each discovered symbol.

    Raises:
        SyntaxError: If source cannot be parsed by ast.parse().
    """
    raise NotImplementedError("Task 1")


def build_inventory(files: list[str], root: Path) -> SymbolInventory:
    """Build a symbol inventory from current filesystem files.

    Reads each file, parses with ast, and collects all top-level symbols.
    Files that fail to parse are logged at WARNING and skipped.

    Args:
        files: List of Python file paths (relative to root).
        root: Project root directory.

    Returns:
        SymbolInventory mapping symbol names to their locations.
    """
    raise NotImplementedError("Task 1")


def build_old_inventory(files: list[str], git_ref: str) -> SymbolInventory:
    """Build a symbol inventory from a previous git state.

    Uses `git show <ref>:<file>` to retrieve file contents at the given
    ref. Files that do not exist at the ref are silently skipped.

    Args:
        files: List of Python file paths to retrieve from git.
        git_ref: Git reference (commit SHA, branch, tag, "HEAD").

    Returns:
        SymbolInventory for the historical state.

    Raises:
        RuntimeError: If git is not available or the ref is invalid.
    """
    raise NotImplementedError("Task 1")


def collect_python_files(source_dirs: list[str], root: Path, exclude_patterns: list[str]) -> list[str]:
    """Collect all Python files from the specified source directories.

    Walks each source_dir under root, collecting .py files while
    excluding paths matching any of the exclude_patterns (glob-style).

    Args:
        source_dirs: Directory names to scan (relative to root).
        root: Project root directory.
        exclude_patterns: Glob patterns for paths to exclude.

    Returns:
        Sorted list of Python file paths relative to root.
    """
    raise NotImplementedError("Task 1")


def get_changed_files(git_ref: str, root: Path) -> list[str]:
    """Get list of Python files changed since the given git ref.

    Uses `git diff --name-only <ref>` to find changed files, then
    filters to .py files only.

    Args:
        git_ref: Git reference to diff against.
        root: Project root directory.

    Returns:
        List of changed .py file paths relative to root.

    Raises:
        RuntimeError: If git is not available.
    """
    raise NotImplementedError("Task 1")
```

---

**Implementation steps:**

1. [FR-1] Implement `schemas.py` with all data structures: `SymbolInfo`, `SymbolInventory`, `MigrationEntry`, `ImportErrorType`, `ImportError`, `FixResult`, `RunResult`, `ImportCheckConfig`. These are pure dataclasses/TypedDicts with no logic.
2. [FR-1] Implement `_file_to_module_path()` — convert filesystem path to dotted module path, handling `__init__.py` as package path.
3. [FR-1] Implement `_extract_symbols()` — use `ast.parse()` + `ast.walk()` or `ast.NodeVisitor` to find `FunctionDef`, `AsyncFunctionDef`, `ClassDef`, and module-level `Assign`/`AnnAssign` targets. Build `SymbolInfo` for each. Skip private names (leading `_`) except `__all__`.
4. [FR-1] Implement `build_inventory()` — iterate files, read source, call `_extract_symbols()`, aggregate into `SymbolInventory`. Log and skip files that raise `SyntaxError`.
5. [FR-2] Implement `build_old_inventory()` — use `subprocess.run(["git", "show", f"{git_ref}:{file}"])` to get historical source, then call `_extract_symbols()`. Skip files that don't exist at the ref.
6. [FR-1] Implement `collect_python_files()` — walk source directories, collect `.py` files, apply exclude patterns using `fnmatch` or `pathlib.match()`.
7. [FR-2] Implement `get_changed_files()` — run `git diff --name-only <ref>`, filter to `.py`, return list.
8. Add `@summary` block and module-level docstrings to both `schemas.py` and `inventory.py`.

**Completion criteria:**
- [ ] All stubs implemented -- no `NotImplementedError` remaining in `schemas.py` or `inventory.py`
- [ ] Integration contracts honored: `build_inventory` and `build_old_inventory` return `SymbolInventory`
- [ ] `@summary` block at top of each new file
- [ ] Module-level docstring present on each file

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 2: Inventory Differ

**Description:** Implement the inventory differ that compares two `SymbolInventory` objects (old and new) and produces a list of `MigrationEntry` records describing how symbols moved between modules, were renamed, split across files, or merged into fewer files.

**Spec requirements:** FR-3

**Dependencies:** Task 1

**Source files:**
- CREATE `import_check/differ.py`

---

**Phase 0 contracts (inlined -- implement these stubs):**

```python
# --- Dependent types from Task 1 (import, do not re-implement) ---
from .schemas import MigrationEntry, SymbolInventory
```

```python
# --- import_check/differ.py stubs ---

from __future__ import annotations

from .schemas import MigrationEntry, SymbolInventory


def diff_inventories(old: SymbolInventory, new: SymbolInventory) -> list[MigrationEntry]:
    """Diff two symbol inventories to detect migrations.

    Detection strategy:
    1. MOVE: Symbol with same name exists in old and new but different module_path.
    2. RENAME: Symbol disappeared from old module; a new symbol appeared in
       the same module with no other explanation. Uses heuristic: same file,
       same symbol_type, close line number.
    3. SPLIT: Symbol from one old module now appears in multiple new modules.
    4. MERGE: Symbols from multiple old modules now appear in one new module.

    Symbols present in both inventories at the same location are ignored.
    Symbols only in old (deleted) or only in new (added) are not migrations.

    Args:
        old: Symbol inventory from the previous git state.
        new: Symbol inventory from the current filesystem state.

    Returns:
        List of MigrationEntry records. Empty if no migrations detected.
    """
    raise NotImplementedError("Task 2")


def _detect_moves(old: SymbolInventory, new: SymbolInventory) -> list[MigrationEntry]:
    """Detect symbols that moved between modules (same name, different path).

    Args:
        old: Old inventory.
        new: New inventory.

    Returns:
        List of move MigrationEntry records.
    """
    raise NotImplementedError("Task 2")


def _detect_renames(
    old: SymbolInventory, new: SymbolInventory, already_matched: set[tuple[str, str]]
) -> list[MigrationEntry]:
    """Detect symbols that were renamed within the same module.

    Uses heuristics: same file, same symbol_type, close line number,
    and the old symbol no longer exists while a new one appeared.

    Args:
        old: Old inventory.
        new: New inventory.
        already_matched: Set of (name, module_path) tuples already explained
            by move detection — skip these.

    Returns:
        List of rename MigrationEntry records.
    """
    raise NotImplementedError("Task 2")


def _detect_splits_and_merges(
    old: SymbolInventory, new: SymbolInventory, already_matched: set[tuple[str, str]]
) -> list[MigrationEntry]:
    """Detect one-to-many (split) and many-to-one (merge) migrations.

    Args:
        old: Old inventory.
        new: New inventory.
        already_matched: Already-explained migrations to skip.

    Returns:
        List of split/merge MigrationEntry records.
    """
    raise NotImplementedError("Task 2")
```

---

**Implementation steps:**

1. [FR-3] Implement `_detect_moves()` — for each symbol name present in both old and new inventories, compare module_paths. If the name exists in old at module A and in new at module B (and not at A), create a `MigrationEntry(migration_type="move")`.
2. [FR-3] Implement `_detect_renames()` — for symbols only in old, find candidates in the new inventory in the same file with the same `symbol_type` and within a configurable line-number proximity threshold. Track matched pairs in `already_matched` to avoid double-counting.
3. [FR-3] Implement `_detect_splits_and_merges()` — group old symbols by source file and new symbols by source file. If symbols from one old file map to multiple new files, create `migration_type="split"` entries. If symbols from multiple old files map to one new file, create `migration_type="merge"` entries.
4. [FR-3] Implement `diff_inventories()` — orchestrate the three detection functions in order (moves first, then renames, then splits/merges), passing the `already_matched` set through to avoid duplicates. Return the combined list.
5. Add `@summary` block and module-level docstring to `differ.py`.

**Completion criteria:**
- [ ] All stubs implemented -- no `NotImplementedError` remaining in `differ.py`
- [ ] `diff_inventories` returns `list[MigrationEntry]` matching the Phase 0 contract
- [ ] Move, rename, split, and merge cases each handled
- [ ] `@summary` block at top of file
- [ ] Module-level docstring present

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 3: Import Checker

**Description:** Implement the import checker (smoke test) that walks Python files, parses imports using `ast`, and verifies that each import resolves to an existing module file and that the imported symbol is defined in the target module. Optionally detects encapsulation violations where external callers import from internal modules instead of through `__init__.py`.

**Spec requirements:** FR-4, FR-5, FR-13

**Dependencies:** none

**Source files:**
- CREATE `import_check/checker.py`

---

**Phase 0 contracts (inlined -- implement these stubs):**

```python
# --- Dependent types (import from schemas.py created in Task 1) ---
from .schemas import ImportCheckConfig, ImportError, ImportErrorType
```

```python
# --- import_check/checker.py stubs ---

from __future__ import annotations

import ast
from pathlib import Path

from .schemas import ImportCheckConfig, ImportError, ImportErrorType


def check_imports(files: list[str], root: Path, config: ImportCheckConfig | None = None) -> list[ImportError]:
    """Check all imports in the given files for errors.

    For each import statement, verifies:
    1. The target module resolves to an existing .py file or package __init__.py.
    2. For `from X import Y`, symbol Y is defined in module X.
    3. If config.encapsulation_check is True, flags imports that bypass
       __init__.py to reach internal modules directly.

    Args:
        files: List of Python file paths to check (relative to root).
        root: Project root directory.
        config: Optional configuration. Uses defaults if None.

    Returns:
        List of ImportError records. Empty if all imports are clean.
    """
    raise NotImplementedError("Task 3")


def _resolve_module_to_file(module: str, root: Path) -> Path | None:
    """Resolve a dotted module path to a filesystem path.

    Checks for both `module/as/path.py` and `module/as/path/__init__.py`.
    Returns None if the module cannot be resolved to an existing file.

    Args:
        module: Dotted module path.
        root: Project root directory.

    Returns:
        Path to the source file, or None if not found.
    """
    raise NotImplementedError("Task 3")


def _extract_imports(source: str) -> list[tuple[str, str, int]]:
    """Parse Python source and extract all import statements.

    Handles:
    - `from X import Y` → (X, Y, lineno)
    - `from X import Y as Z` → (X, Y, lineno)
    - `import X` → (X, "", lineno)
    - Imports inside functions (lazy imports)
    - Imports inside TYPE_CHECKING blocks
    - Imports inside try/except blocks

    Args:
        source: Python source code string.

    Returns:
        List of (module, name, lineno) tuples.
    """
    raise NotImplementedError("Task 3")


def _check_symbol_defined(module_file: Path, symbol_name: str) -> bool:
    """Check if a symbol is defined in the given module file.

    Parses the file with ast and checks for FunctionDef, ClassDef,
    Assign, AnnAssign, and ImportFrom (re-exports) at module level.
    Also checks __all__ if present.

    Args:
        module_file: Path to the module source file.
        symbol_name: Name to look for.

    Returns:
        True if the symbol is defined or re-exported in the module.
    """
    raise NotImplementedError("Task 3")


def _check_encapsulation(module: str, file_path: str, root: Path) -> ImportError | None:
    """Check if an import violates encapsulation boundaries.

    An encapsulation violation is when an external caller imports from an
    internal module instead of from the package's __init__.py.

    Only applies to imports that cross package boundaries.

    Args:
        module: Dotted module path being imported.
        file_path: File containing the import statement.
        root: Project root directory.

    Returns:
        ImportError if encapsulation is violated, None otherwise.
    """
    raise NotImplementedError("Task 3")
```

---

**Implementation steps:**

1. [FR-4] Implement `_resolve_module_to_file()` — convert dotted module path to filesystem candidates (`module.py` and `module/__init__.py`), return first that exists or `None`.
2. [FR-4] Implement `_extract_imports()` — use `ast.parse()` + full tree walk to find `Import` and `ImportFrom` nodes at all nesting levels (module top, function bodies, TYPE_CHECKING blocks, try/except). Return `(module, name, lineno)` tuples.
3. [FR-4] Implement `_check_symbol_defined()` — parse target module with `ast`, walk for `FunctionDef`, `ClassDef`, `Assign`, `AnnAssign`, and `ImportFrom` (re-exports). Check `__all__` if present.
4. [FR-5] Implement `_check_encapsulation()` — determine if the importing file is outside the target package; if so, check whether the import bypasses `__init__.py`. Flag as `ENCAPSULATION_VIOLATION` if it does.
5. [FR-4, FR-13] Implement `check_imports()` — iterate files, extract imports, resolve modules, check symbols, collect encapsulation violations. Return structured `ImportError` list. Log errors at ERROR level per the error taxonomy.
6. Add `@summary` block and module-level docstring to `checker.py`.

**Completion criteria:**
- [ ] All stubs implemented -- no `NotImplementedError` remaining in `checker.py`
- [ ] `check_imports` returns `list[ImportError]` matching the Phase 0 contract
- [ ] All import styles handled: regular, lazy, TYPE_CHECKING, try/except
- [ ] Encapsulation check is report-only (diagnostic, not auto-fix)
- [ ] `@summary` block at top of file
- [ ] Module-level docstring present

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 4: Import Fixer

**Description:** Implement the import fixer that uses `libcst` to rewrite broken import statements based on a migration map from the differ. Handles all import styles (`from X import Y`, `import X`, aliased imports), string-based references in `mock.patch()` and `importlib.import_module()` calls, `__all__` list updates, and simple single-assignment string literal dataflow within function scope.

**Spec requirements:** FR-6, FR-7, FR-8, FR-9

**Dependencies:** Task 2

**Source files:**
- CREATE `import_check/fixer.py`

---

**Phase 0 contracts (inlined -- implement these stubs):**

```python
# --- Dependent types from Task 1/2 (import, do not re-implement) ---
from .schemas import FixResult, MigrationEntry
```

```python
# --- import_check/fixer.py stubs ---

from __future__ import annotations

from pathlib import Path

from .schemas import FixResult, MigrationEntry


def apply_fixes(
    migration_map: list[MigrationEntry],
    target_files: list[str],
    root: Path,
) -> FixResult:
    """Apply import fixes to target files based on the migration map.

    For each target file:
    1. Parse with libcst.
    2. Walk ImportFrom and Import nodes, matching against migration_map.
    3. Rewrite matched imports to use the new module/name.
    4. Walk Call nodes for mock.patch() and importlib.import_module() string args.
    5. Walk Assign nodes for __all__ list updates.
    6. Write back the modified source if any changes were made.

    Files that fail to parse with libcst are logged and skipped.

    Args:
        migration_map: List of MigrationEntry from differ.diff_inventories().
        target_files: List of Python file paths to fix (relative to root).
        root: Project root directory.

    Returns:
        FixResult summarizing what was changed and what was skipped.
    """
    raise NotImplementedError("Task 4")


def _build_import_rewriter(migration_map: list[MigrationEntry]) -> "ImportRewriter":
    """Build a libcst transformer that rewrites import statements.

    Creates a CSTTransformer subclass that matches ImportFrom and Import
    nodes against the migration map and produces rewritten nodes.

    Args:
        migration_map: List of migrations to apply.

    Returns:
        A libcst CSTTransformer instance.
    """
    raise NotImplementedError("Task 4")


def _build_string_ref_rewriter(migration_map: list[MigrationEntry]) -> "StringRefRewriter":
    """Build a libcst transformer that rewrites string-based references.

    Matches:
    - mock.patch("old.module.path") → mock.patch("new.module.path")
    - importlib.import_module("old.module") → importlib.import_module("new.module")
    - Simple single-assignment string literals in same function scope.

    Args:
        migration_map: List of migrations to apply.

    Returns:
        A libcst CSTTransformer instance.
    """
    raise NotImplementedError("Task 4")


def _build_all_rewriter(migration_map: list[MigrationEntry]) -> "AllListRewriter":
    """Build a libcst transformer that updates __all__ lists.

    Matches __all__ = [...] assignments and updates string entries
    that correspond to renamed symbols in the migration map.

    Args:
        migration_map: List of migrations to apply.

    Returns:
        A libcst CSTTransformer instance.
    """
    raise NotImplementedError("Task 4")


def _apply_transformers_to_file(
    file_path: Path,
    transformers: list,
) -> tuple[bool, list[str]]:
    """Parse a file with libcst, apply transformers, and write back if changed.

    Args:
        file_path: Path to the Python source file.
        transformers: List of libcst CSTTransformer instances to apply sequentially.

    Returns:
        Tuple of (was_modified: bool, errors: list[str]).
    """
    raise NotImplementedError("Task 4")
```

---

**Implementation steps:**

1. [FR-6] Implement `_build_import_rewriter()` — create a `libcst.CSTTransformer` subclass (`ImportRewriter`) that visits `ImportFrom` and `Import` nodes. Build a lookup dict from `migration_map` keyed by `(old_module, old_name)`. On match, rewrite the node's module and/or name attributes. Handle aliased imports (preserve the alias, update the source).
2. [FR-7] Implement `_build_string_ref_rewriter()` — create a `libcst.CSTTransformer` subclass (`StringRefRewriter`) that visits `Call` nodes. Match calls to `mock.patch`, `unittest.mock.patch`, `patch`, `importlib.import_module` by checking the function name/attribute chain. If the first argument is a `SimpleString` or `ConcatenatedString` containing a dotted path from the migration map, rewrite it. For simple dataflow: track single-assignment string variables in the current function scope and rewrite their values if they match.
3. [FR-8] Implement `_build_all_rewriter()` — create a `libcst.CSTTransformer` subclass (`AllListRewriter`) that visits `Assign` nodes where the target is `__all__`. Walk the list elements (string literals) and rewrite any that match `old_name` in the migration map.
4. [FR-9] Extend `StringRefRewriter` to handle simple dataflow — in the `visit_FunctionDef` scope, maintain a dict of `{var_name: string_value}` for simple `var = "literal"` assignments. When a `Call` node uses a variable as argument (Name node), look it up in the scope dict and rewrite the assignment if it matches.
5. [FR-6] Implement `_apply_transformers_to_file()` — read file, `libcst.parse_module()`, apply each transformer in sequence via `module.visit()`, compare output to original, write back if different. Collect non-fatal errors.
6. [FR-6] Implement `apply_fixes()` — iterate target files, build all three transformers from migration_map, call `_apply_transformers_to_file()` for each. Aggregate into `FixResult`.
7. Add `@summary` block and module-level docstring to `fixer.py`.

**Completion criteria:**
- [ ] All stubs implemented -- no `NotImplementedError` remaining in `fixer.py`
- [ ] `apply_fixes` returns `FixResult` matching the Phase 0 contract
- [ ] `ImportRewriter` handles `from X import Y`, `import X`, aliased imports
- [ ] `StringRefRewriter` handles `mock.patch()` and `importlib.import_module()` string args
- [ ] `AllListRewriter` handles `__all__` list updates
- [ ] Simple dataflow (single-assignment string literals in function scope) handled
- [ ] Dynamic string construction (`f"..."`) flagged in `FixResult.skipped`, not fixed
- [ ] `@summary` block at top of file
- [ ] Module-level docstring present

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 5: Public API Orchestrator

**Description:** Implement the public API module (`__init__.py`) that orchestrates all internal modules. Provides three entry points: `fix()` (deterministic fixing), `check()` (smoke testing), and `run()` (fix then check). Handles configuration loading from `pyproject.toml` and keyword overrides, logging setup, and result aggregation.

**Spec requirements:** FR-10, FR-12

**Dependencies:** Task 1, Task 2, Task 3, Task 4

**Source files:**
- CREATE `import_check/__init__.py`

---

**Phase 0 contracts (inlined -- implement these stubs):**

```python
# --- Dependent modules (import, do not re-implement) ---
# from .inventory import build_inventory, build_old_inventory, collect_python_files, get_changed_files
# from .differ import diff_inventories
# from .checker import check_imports
# from .fixer import apply_fixes
# from .schemas import FixResult, ImportCheckConfig, ImportError, RunResult
```

```python
# --- import_check/__init__.py stubs ---

from __future__ import annotations

from pathlib import Path
from typing import Any

from .schemas import FixResult, ImportCheckConfig, ImportError, RunResult


def _load_config(root: Path, **overrides: Any) -> ImportCheckConfig:
    """Load configuration from pyproject.toml and apply overrides.

    Resolution order (highest priority first):
    1. Keyword argument overrides
    2. pyproject.toml [tool.import_check] section
    3. ImportCheckConfig defaults

    Args:
        root: Project root directory (used to locate pyproject.toml).
        **overrides: Keyword arguments matching ImportCheckConfig fields.

    Returns:
        Fully resolved ImportCheckConfig.
    """
    raise NotImplementedError("Task 5")


def _setup_logging(config: ImportCheckConfig) -> None:
    """Configure logging for the import_check tool.

    Sets up a logger named "import_check" with the configured log level.
    Uses a simple format: "%(levelname)s: %(message)s".

    Args:
        config: Configuration containing log_level.
    """
    raise NotImplementedError("Task 5")


def fix(root: Path | str | None = None, **config_overrides: Any) -> FixResult:
    """Apply deterministic import fixes based on symbol inventory diff.

    Pipeline:
    1. Resolve root directory (default: cwd).
    2. Load config from pyproject.toml + overrides.
    3. Collect changed Python files via git diff.
    4. Build old inventory (from git_ref) and new inventory (from filesystem).
    5. Diff inventories to produce migration map.
    6. Apply fixes to all Python files in source_dirs.

    Args:
        root: Project root directory. Defaults to Path.cwd().
        **config_overrides: Override any ImportCheckConfig field.

    Returns:
        FixResult summarizing changes made.

    Raises:
        RuntimeError: If git is not available.
    """
    raise NotImplementedError("Task 5")


def check(root: Path | str | None = None, **config_overrides: Any) -> list[ImportError]:
    """Smoke test all imports for errors.

    Args:
        root: Project root directory. Defaults to Path.cwd().
        **config_overrides: Override any ImportCheckConfig field.

    Returns:
        List of ImportError records. Empty if all imports are clean.
    """
    raise NotImplementedError("Task 5")


def run(root: Path | str | None = None, **config_overrides: Any) -> RunResult:
    """Full pipeline: fix then check.

    Args:
        root: Project root directory. Defaults to Path.cwd().
        **config_overrides: Override any ImportCheckConfig field.

    Returns:
        RunResult with fix_result and remaining_errors.
    """
    raise NotImplementedError("Task 5")
```

---

**Implementation steps:**

1. [FR-10] Implement `_load_config()` — read `pyproject.toml` from root directory using `tomllib` (Python 3.11+) or `tomli` fallback. Parse `[tool.import_check]` section. Merge with `ImportCheckConfig` defaults, then apply keyword overrides. Validate: fail fast with `ValueError` on unknown keys or contradictory settings (e.g., empty `source_dirs`).
2. [FR-10] Implement `_setup_logging()` — create/get logger named `"import_check"`, set level from `config.log_level`, add a `StreamHandler` with `"%(levelname)s: %(message)s"` format if no handlers exist.
3. [FR-12] Implement `fix()` — resolve root to `Path`, call `_load_config()`, call `_setup_logging()`, call `get_changed_files()`, call `build_old_inventory()` and `build_inventory()`, call `diff_inventories()`, call `collect_python_files()` for the full target set, call `apply_fixes()`. Return `FixResult`.
4. [FR-12] Implement `check()` — resolve root, load config, setup logging, collect all Python files, call `check_imports()`. Return the error list.
5. [FR-12] Implement `run()` — call `fix()` then `check()`, combine into `RunResult`.
6. Add `@summary` block, module-level docstring, and `__all__` exports to `__init__.py`.

**Completion criteria:**
- [ ] All stubs implemented -- no `NotImplementedError` remaining in `__init__.py`
- [ ] `fix()`, `check()`, `run()` match the Phase 0 contract signatures
- [ ] Config loaded from pyproject.toml with CLI/API override support
- [ ] Config validation fails fast on contradictory settings
- [ ] Logging configured per config
- [ ] `@summary` block at top of file
- [ ] Module-level docstring present
- [ ] `__all__` exports `fix`, `check`, `run`, `ImportCheckConfig`, `RunResult`, `FixResult`, `ImportError`

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 6: CLI Entry Point

**Description:** Implement the CLI entry point (`__main__.py`) that parses command-line arguments and dispatches to the public API functions (`fix`, `check`, `run`). Supports subcommands, all configuration keys as CLI flags, and both human-readable and JSON output formats.

**Spec requirements:** FR-11, FR-13

**Dependencies:** Task 5

**Source files:**
- CREATE `import_check/__main__.py`

---

**Phase 0 contracts (inlined -- implement these stubs):**

```python
# --- Dependent modules (import, do not re-implement) ---
# from . import fix, check, run
# from .schemas import FixResult, ImportError, RunResult
```

```python
# --- import_check/__main__.py stubs ---

from __future__ import annotations


def main() -> int:
    """Parse CLI arguments and dispatch to the appropriate command.

    Returns:
        Exit code: 0 if no errors, 1 if import errors remain after fix.
    """
    raise NotImplementedError("Task 6")


def _build_parser() -> "argparse.ArgumentParser":
    """Build the argument parser for import_check CLI.

    Subcommands: fix, check, run (default).
    Global options: --source-dirs, --exclude, --git-ref,
        --no-encapsulation-check, --format, --log-level, --root.

    Returns:
        Configured ArgumentParser.
    """
    raise NotImplementedError("Task 6")


def _format_output(result: "RunResult | FixResult | list[ImportError]", fmt: str) -> str:
    """Format a result object for terminal output.

    Args:
        result: The result to format.
        fmt: Output format — "human" or "json".

    Returns:
        Formatted string ready for print().
    """
    raise NotImplementedError("Task 6")
```

---

**Implementation steps:**

1. [FR-11] Implement `_build_parser()` — use `argparse.ArgumentParser` with subparsers for `fix`, `check`, `run`. Set `run` as default. Add global options: `--source-dirs` (nargs="+"), `--exclude` (nargs="+"), `--git-ref`, `--no-encapsulation-check` (store_false), `--format` (choices=["human", "json"]), `--log-level` (choices=["DEBUG", "INFO", "ERROR"]), `--root`.
2. [FR-13] Implement `_format_output()` — for `"human"` format, produce readable text with file paths, line numbers, and error descriptions. For `"json"` format, serialize result objects using `dataclasses.asdict()` + `json.dumps()` with `default=str` for Path/Enum handling.
3. [FR-11] Implement `main()` — parse args, map CLI flags to `config_overrides` dict, dispatch to `fix()`, `check()`, or `run()` based on subcommand. Print formatted output. Return 0 if no remaining errors, 1 otherwise.
4. Add `if __name__ == "__main__": sys.exit(main())` guard.
5. Add `@summary` block and module-level docstring to `__main__.py`.

**Completion criteria:**
- [ ] All stubs implemented -- no `NotImplementedError` remaining in `__main__.py`
- [ ] `python -m import_check` works with default subcommand `run`
- [ ] All three subcommands (`fix`, `check`, `run`) functional
- [ ] All config keys available as CLI flags
- [ ] Human and JSON output formats both work
- [ ] Exit code 0 for clean, 1 for remaining errors
- [ ] `@summary` block at top of file
- [ ] Module-level docstring present

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Module Boundary Map

| Task | Source File | Action |
|---|---|---|
| Task 1 | `import_check/schemas.py` | CREATE |
| Task 1 | `import_check/inventory.py` | CREATE |
| Task 2 | `import_check/differ.py` | CREATE |
| Task 3 | `import_check/checker.py` | CREATE |
| Task 4 | `import_check/fixer.py` | CREATE |
| Task 5 | `import_check/__init__.py` | CREATE |
| Task 6 | `import_check/__main__.py` | CREATE |

---

## Dependency Graph

```
Task 1: inventory.py (schemas.py)     Task 3: checker.py
     │                                     │
     ▼                                     │
Task 2: differ.py                          │
     │                                     │
     ▼                                     ▼
Task 4: fixer.py ─────────────────────────►│
     │                                     │
     ▼                                     ▼
Task 5: __init__.py ◄─────────────────────┘
     │
     ▼
Task 6: __main__.py
```

**Parallel execution waves:**

| Wave | Tasks | Rationale |
|---|---|---|
| Wave 1 | Task 1, Task 3 | No inter-task dependencies; Task 1 creates schemas + inventory, Task 3 creates checker |
| Wave 2 | Task 2 | Depends on Task 1 (needs SymbolInventory and MigrationEntry types) |
| Wave 3 | Task 4 | Depends on Task 2 (needs MigrationEntry from differ) |
| Wave 4 | Task 5 | Depends on Tasks 1, 2, 3, 4 (orchestrates all modules) |
| Wave 5 | Task 6 | Depends on Task 5 (CLI dispatches to public API) |

---

## Task-to-FR Traceability Table

| FR | Description | Task(s) | Source File(s) |
|---|---|---|---|
| FR-1 | Symbol inventory building from Python files using ast | Task 1 | `import_check/schemas.py`, `import_check/inventory.py` |
| FR-2 | Git-based "before" inventory from git show | Task 1 | `import_check/inventory.py` |
| FR-3 | Inventory diffing to detect moves, renames, splits, merges | Task 2 | `import_check/differ.py` |
| FR-4 | Import checking/smoke testing (module exists, symbol defined) | Task 3 | `import_check/checker.py` |
| FR-5 | Encapsulation violation detection (report-only) | Task 3 | `import_check/checker.py` |
| FR-6 | Import fixing using libcst based on migration map | Task 4 | `import_check/fixer.py` |
| FR-7 | String-based reference fixing (mock.patch, importlib.import_module) | Task 4 | `import_check/fixer.py` |
| FR-8 | __all__ list updates | Task 4 | `import_check/fixer.py` |
| FR-9 | Simple dataflow for variable-held string paths | Task 4 | `import_check/fixer.py` |
| FR-10 | Config-driven behavior (pyproject.toml, CLI, API) | Task 5 | `import_check/__init__.py` |
| FR-11 | CLI entry point (python -m import_check) | Task 6 | `import_check/__main__.py` |
| FR-12 | Public programmatic API (fix, check, run) | Task 5 | `import_check/__init__.py` |
| FR-13 | Structured error output (human + JSON formats) | Task 3, Task 6 | `import_check/checker.py`, `import_check/__main__.py` |
