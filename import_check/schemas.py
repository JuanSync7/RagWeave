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
"""Symbol name -> list of locations where that symbol is defined.

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
        output_format: Output format -- "human" or "json".
        log_level: Logging verbosity.
        root: Project root directory (resolved at runtime).
        check_stubs: Enable .pyi stub fallback for symbol checking.
        check_getattr: Enable __getattr__ suppression for SYMBOL_NOT_DEFINED.
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
    check_stubs: bool = True              # REQ-511 -- .pyi stub fallback
    check_getattr: bool = True            # REQ-513 -- __getattr__ suppression
