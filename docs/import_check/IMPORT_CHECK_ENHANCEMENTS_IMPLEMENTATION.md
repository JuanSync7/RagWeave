# Import Check Enhancements -- Implementation Docs

> **For implement-code agents:** This document is your source of truth.
> Read ONLY your assigned task section. Your section contains your FR context,
> Phase 0 contracts inlined, implementation steps, and isolation contract verbatim.
> Do not read the full document, the spec, the design doc, or other task sections.

**Goal:** Enhance the import_check checker with relative import resolution, runtime symbol suppression (`__getattr__` + `.pyi` stubs), and inline suppression comments (`# import_check: ignore`).
**Spec:** `docs/import_check/IMPORT_CHECK_ENHANCEMENTS_SPEC.md`
**Design doc:** `docs/import_check/IMPORT_CHECK_ENHANCEMENTS_DESIGN.md`
**Output path:** `docs/import_check/IMPORT_CHECK_ENHANCEMENTS_IMPLEMENTATION.md`
**Produced by:** write-implementation-docs
**Phase 0 status:** [ ] Awaiting human review

---

## Phase 0: Contract Definitions

> **Human review gate:** Approve this section before any implement-code task begins.
> Every task section inlines these contracts. A mistake here propagates to every task.

This section defines all shared type surfaces, data structures, function stubs, error taxonomy, and integration contracts for the import_check checker enhancements.

---

### Data Structures -- `import_check/schemas.py`

```python
# import_check/schemas.py
# MODIFICATION to existing ImportCheckConfig dataclass.
# Add these two fields after the existing fields.

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Literal


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
```

---

### Function Stubs -- `import_check/checker.py`

#### Modified: `_extract_imports`

```python
# import_check/checker.py
# MODIFIED function: _extract_imports -- new return type

def _extract_imports(source: str) -> list[tuple[str | None, str, int, int]]:
    """Parse Python source and extract all import statements.

    Uses ``ast.walk()`` so that imports at *any* nesting depth are captured:
    lazy imports inside functions, ``TYPE_CHECKING`` blocks, ``try/except``, etc.

    Handles:

    - ``from X import Y``       -> ``(X, Y, lineno, 0)``
    - ``from X import Y as Z``  -> ``(X, Y, lineno, 0)``
    - ``import X``              -> ``(X, "", lineno, 0)``
    - ``import X as Z``         -> ``(X, "", lineno, 0)``
    - ``from .foo import bar``  -> ``("foo", "bar", lineno, 1)``
    - ``from ..foo import bar`` -> ``("foo", "bar", lineno, 2)``
    - ``from . import bar``     -> ``(None, "bar", lineno, 1)``

    Relative imports are included with their level (REQ-313). The module
    field may be ``None`` for bare relative imports (``from . import foo``).

    Args:
        source: Python source code string.

    Returns:
        List of ``(module, name, lineno, level)`` tuples.
    """
    raise NotImplementedError("Task 2.1")
```

#### New: `_resolve_relative_import`

```python
# import_check/checker.py
# NEW function

def _resolve_relative_import(
    module: str | None,
    level: int,
    file_path: str,
    root: Path,
) -> str | None:
    """Resolve a relative import to an absolute dotted module path.

    Uses the importing file's filesystem position and the project root
    to compute the absolute package path (REQ-315).

    Resolution algorithm:
    1. Compute the importing file's package: convert ``file_path`` to a
       dotted path relative to ``root``, then take all but the last component
       (the module name itself).
    2. Ascend ``level`` components from the package path. If this ascends
       above the project root, return ``None`` (REQ-319).
    3. Append ``module`` (if not ``None``) to get the absolute dotted path.
    4. For bare relative imports (``from . import foo``), the resolved path
       is the package itself, and ``foo`` is the symbol to check (REQ-321).

    Only resolves within standard packages (directories with ``__init__.py``
    between the file and the project root). Returns ``None`` if the file
    is not inside a package (REQ-317).

    Args:
        module: The relative module name (e.g., ``"foo"`` from ``from .foo import bar``).
            ``None`` for bare relative imports (``from . import bar``).
        level: Number of dots in the relative import (1 for ``.``, 2 for ``..``).
        file_path: Path of the importing file, relative to ``root``.
        root: Project root directory.

    Returns:
        Absolute dotted module path (e.g., ``"src.pkg.foo"``), or ``None`` if
        resolution fails (file not in package, or ascension above root).
    """
    raise NotImplementedError("Task 2.1")
```

#### New: Per-invocation caches and helpers

```python
# import_check/checker.py
# NEW module-level caches and helpers

from .schemas import ImportCheckConfig, ImportError, ImportErrorType

# ---------------------------------------------------------------------------
# Per-invocation caches (REQ-333)
# ---------------------------------------------------------------------------

_getattr_cache: dict[Path, bool] = {}
_stub_symbol_cache: dict[tuple[Path, str], bool] = {}


def _clear_caches() -> None:
    """Clear per-invocation caches.

    Called at the start of each ``check_imports`` invocation to prevent
    cross-invocation staleness (REQ-333).
    """
    _getattr_cache.clear()
    _stub_symbol_cache.clear()
```

#### New: `_has_dynamic_getattr`

```python
# import_check/checker.py
# NEW function

def _has_dynamic_getattr(module_file: Path) -> bool:
    """Check if a module defines ``__getattr__`` at the module level.

    Parses the module file with ``ast`` and inspects only top-level
    ``FunctionDef`` nodes (REQ-325). Nested ``__getattr__`` definitions
    inside classes or functions do not count.

    Results are cached per file path within a single ``check_imports``
    invocation (REQ-333).

    Args:
        module_file: Path to the module source file.

    Returns:
        ``True`` if a module-level ``def __getattr__`` is found.
    """
    raise NotImplementedError("Task 2.2")
```

#### New: `_resolve_stub_file`

```python
# import_check/checker.py
# NEW function

def _resolve_stub_file(module_file: Path) -> Path | None:
    """Locate the co-located ``.pyi`` stub file for a module.

    For ``module.py``, checks for ``module.pyi`` in the same directory.
    For ``package/__init__.py``, checks for ``package/__init__.pyi`` (REQ-329).

    Does not search any other locations (no site-packages, no typeshed).

    Args:
        module_file: Path to the ``.py`` module file.

    Returns:
        Path to the ``.pyi`` stub file if it exists, ``None`` otherwise.
    """
    raise NotImplementedError("Task 2.2")
```

#### Modified: `_check_symbol_defined`

```python
# import_check/checker.py
# MODIFIED function: _check_symbol_defined -- added config parameter and fallback chain

def _check_symbol_defined(
    module_file: Path,
    symbol_name: str,
    config: ImportCheckConfig | None = None,
) -> bool:
    """Check if a symbol is defined in the given module, with fallback chain.

    Implements the ordered fallback chain (REQ-323):

    1. Check ``.py`` file for direct definition (existing behavior):
       ``FunctionDef``, ``AsyncFunctionDef``, ``ClassDef``, ``Assign``,
       ``AnnAssign``, ``ImportFrom`` re-export, ``__all__`` membership.
    2. If not found and ``config.check_getattr`` is ``True``: check if the
       ``.py`` file defines a module-level ``__getattr__`` (REQ-325).
       If present, return ``True`` (REQ-327 -- suppresses only
       ``SYMBOL_NOT_DEFINED``, not ``MODULE_NOT_FOUND`` or
       ``ENCAPSULATION_VIOLATION``).
    3. If not found and ``config.check_stubs`` is ``True``: locate the
       co-located ``.pyi`` stub file (REQ-329) and check for the symbol
       definition using AST parsing (REQ-331).

    If ``config`` is ``None``, both fallbacks are enabled (backward-compatible
    default).

    Args:
        module_file: Path to the module source file.
        symbol_name: Name to look for.
        config: Configuration controlling which fallbacks are enabled.
            When ``None``, defaults to all fallbacks enabled.

    Returns:
        ``True`` if the symbol is defined or resolvable via the fallback chain.
    """
    raise NotImplementedError("Task 2.2")
```

#### New: `_is_suppressed`

```python
# import_check/checker.py
# NEW function

def _is_suppressed(source: str, lineno: int) -> bool:
    """Check if a source line contains the import_check suppression marker.

    Looks for the string ``# import_check: ignore`` anywhere on the
    source line at the given line number (REQ-335). The marker can appear
    at any position on the line -- it does not need to be at the end.

    This function is always active -- it does not require a configuration
    toggle (REQ-341).

    Args:
        source: Full source text of the file.
        lineno: 1-based line number to check.

    Returns:
        ``True`` if the line contains ``# import_check: ignore``.
    """
    raise NotImplementedError("Task 2.3")
```

#### Modified: `check_imports`

```python
# import_check/checker.py
# MODIFIED function: check_imports -- updated orchestration

def check_imports(
    files: list[str],
    root: Path,
    config: ImportCheckConfig | None = None,
) -> list[ImportError]:
    """Check all imports in the given files for errors.

    For each import statement, verifies:

    1. The target module resolves to an existing ``.py`` file or package
       ``__init__.py``.
    2. For ``from X import Y``, symbol *Y* is defined in module *X*,
       with fallback chain: direct definition -> ``__getattr__`` presence
       -> ``.pyi`` stub definition (REQ-323).
    3. If ``config.encapsulation_check`` is ``True``, flags imports that bypass
       ``__init__.py`` to reach internal modules directly.

    Enhanced behavior:

    - Relative imports are resolved to absolute paths before verification
      (REQ-315). Unresolvable relative imports are skipped with DEBUG log.
    - Imports on lines containing ``# import_check: ignore`` are skipped
      before verification and logged at DEBUG level (REQ-337, REQ-339).
    - Symbol verification uses the fallback chain controlled by
      ``config.check_getattr`` and ``config.check_stubs`` (REQ-323).
    - Per-invocation caches for ``__getattr__`` detection and stub parsing
      are cleared at the start of each call (REQ-333).

    Args:
        files: List of Python file paths to check (relative to *root*).
        root: Project root directory.
        config: Optional configuration. Uses defaults if ``None``.

    Returns:
        List of ``ImportError`` records. Empty if all imports are clean.
    """
    raise NotImplementedError("Task 3.1")
```

### Function Stubs -- `import_check/__main__.py`

#### Modified: `_build_parser` (additions)

```python
# import_check/__main__.py
# ADDITIONS to existing _build_parser() function.
# Add these arguments after the existing --no-encapsulation-check argument.

    parser.add_argument(
        "--no-check-stubs",
        dest="check_stubs",
        action="store_false",
        default=True,
        help="Disable .pyi stub file fallback for symbol checking",
    )  # REQ-413
    parser.add_argument(
        "--no-check-getattr",
        dest="check_getattr",
        action="store_false",
        default=True,
        help="Disable __getattr__-based symbol suppression",
    )  # REQ-415
```

#### Modified: `main` (additions to config_overrides)

```python
# import_check/__main__.py
# ADDITION to existing main() function config_overrides dict.
# Add these entries alongside the existing config override wiring:

    config_overrides: dict = {
        "log_level": args.log_level,
        "output_format": args.format,
        "encapsulation_check": args.encapsulation_check,
        "git_ref": args.git_ref,
        "check_stubs": args.check_stubs,        # REQ-413, REQ-515
        "check_getattr": args.check_getattr,     # REQ-415, REQ-515
    }
```

---

### Error Taxonomy

| Error Type | Trigger Condition | Expected Message Format | Retryable | Raising Module |
|---|---|---|---|---|
| `SyntaxError` (`.pyi` file) | Stub file cannot be parsed by `ast.parse()` | `"Failed to parse stub file {stub_path}: {detail}"` | No | `import_check/checker.py` |
| `OSError` (`.pyi` file) | Stub file cannot be read | `"Cannot read stub file {stub_path}: {detail}"` | No | `import_check/checker.py` |
| `ImportErrorType.MODULE_NOT_FOUND` | Imported module does not resolve to a `.py` file (including resolved relative imports) | `"Module '{module}' not found"` | No | `import_check/checker.py` |
| `ImportErrorType.SYMBOL_NOT_DEFINED` | Symbol not defined in target module after full fallback chain (`.py` + `__getattr__` + `.pyi`) | `"Symbol '{name}' not defined in module '{module}'"` | No | `import_check/checker.py` |
| `ImportErrorType.ENCAPSULATION_VIOLATION` | External import bypasses `__init__.py` (applies to resolved relative imports too) | `"Encapsulation violation: external import from internal module '{module}' -- consider importing from '{package}' instead"` | No | `import_check/checker.py` |

Note: `.pyi` parse failures are handled via graceful degradation (WARNING log, skip stub fallback -- REQ-919). They do not produce `ImportError` records in the output.

---

### Integration Contracts

```
check_imports() -> _clear_caches()
  Called when: at the start of every check_imports invocation
  Purpose: reset per-invocation caches for __getattr__ and stub results (REQ-333)

check_imports() -> _extract_imports(source) -> list[tuple[str | None, str, int, int]]
  Called when: for each file being checked
  Change: returns 4-tuples (was 3-tuples); includes relative imports (was skipping them)

check_imports() -> _is_suppressed(source, lineno) -> bool
  Called when: for each extracted import, before any verification
  On True: skip import, log at DEBUG (REQ-339)

check_imports() -> _resolve_relative_import(module, level, file_path, root) -> str | None
  Called when: for each extracted import with level > 0
  On None: skip import, log at DEBUG (REQ-317, REQ-319)

check_imports() -> _check_symbol_defined(module_file, symbol_name, config) -> bool
  Called when: for each "from X import Y" after module resolution
  Change: now accepts config parameter for fallback chain control
  Fallback chain: .py definition -> __getattr__ (if check_getattr) -> .pyi stub (if check_stubs)

_check_symbol_defined() -> _has_dynamic_getattr(module_file) -> bool
  Called when: step 1 (.py definition) fails and config.check_getattr is True
  Uses _getattr_cache for per-invocation caching

_check_symbol_defined() -> _resolve_stub_file(module_file) -> Path | None
  Called when: step 2 (__getattr__) fails and config.check_stubs is True
  On None: no stub file exists, return False

_check_symbol_defined() -> _check_symbol_defined(stub_file, symbol_name) [reuse AST logic]
  Called when: stub file found, checking for symbol definition
  On SyntaxError/OSError: log WARNING, skip stub fallback for that module (REQ-919)
  Uses _stub_symbol_cache for per-invocation caching
```

---

## Task 1.1: Config and Schema Extension

**Description:** Extend the `ImportCheckConfig` dataclass with two new boolean fields (`check_stubs`, `check_getattr`) and add corresponding CLI flags (`--no-check-stubs`, `--no-check-getattr`) to the argument parser. Wire the CLI flags to config overrides in the `main()` dispatch. This task establishes the configuration surface that all three enhancement tasks depend on.

**Spec requirements:** REQ-511, REQ-513, REQ-515, REQ-413, REQ-415

**Dependencies:** none

**Source files:**
- MODIFY `import_check/schemas.py`
- MODIFY `import_check/__main__.py`

---

**Phase 0 contracts (inlined -- implement these stubs):**

```python
# import_check/schemas.py
# MODIFICATION to existing ImportCheckConfig dataclass.
# Add these two fields after the existing fields.

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
```

```python
# import_check/__main__.py
# ADDITIONS to existing _build_parser() function.
# Add these arguments after the existing --no-encapsulation-check argument.

    parser.add_argument(
        "--no-check-stubs",
        dest="check_stubs",
        action="store_false",
        default=True,
        help="Disable .pyi stub file fallback for symbol checking",
    )  # REQ-413
    parser.add_argument(
        "--no-check-getattr",
        dest="check_getattr",
        action="store_false",
        default=True,
        help="Disable __getattr__-based symbol suppression",
    )  # REQ-415

# ADDITION to existing main() function config_overrides dict.
# Add these entries alongside the existing config override wiring:

    config_overrides: dict = {
        "log_level": args.log_level,
        "output_format": args.format,
        "encapsulation_check": args.encapsulation_check,
        "git_ref": args.git_ref,
        "check_stubs": args.check_stubs,        # REQ-413, REQ-515
        "check_getattr": args.check_getattr,     # REQ-415, REQ-515
    }
```

---

**Implementation steps:**

1. [REQ-511] Add `check_stubs: bool = True` field to `ImportCheckConfig` in `import_check/schemas.py`, placed after the existing `root` field. Add inline comment `# REQ-511 -- .pyi stub fallback`.
2. [REQ-513] Add `check_getattr: bool = True` field to `ImportCheckConfig` in `import_check/schemas.py`, placed after `check_stubs`. Add inline comment `# REQ-513 -- __getattr__ suppression`.
3. [REQ-511, REQ-513] Update the `ImportCheckConfig` docstring `Attributes:` section to document both new fields.
4. [REQ-413] Add `--no-check-stubs` argument to `_build_parser()` in `import_check/__main__.py` using `action="store_false"`, `dest="check_stubs"`, `default=True`. Place after the existing `--no-encapsulation-check` argument.
5. [REQ-415] Add `--no-check-getattr` argument to `_build_parser()` in `import_check/__main__.py` using `action="store_false"`, `dest="check_getattr"`, `default=True`. Place after `--no-check-stubs`.
6. [REQ-515] Add `"check_stubs": args.check_stubs` and `"check_getattr": args.check_getattr` entries to the `config_overrides` dict in `main()`.
7. Update `@summary` blocks in both modified files to reflect the new fields/flags.

**Completion criteria:**
- [ ] `ImportCheckConfig()` defaults produce `check_stubs=True` and `check_getattr=True`
- [ ] CLI parser with `--no-check-stubs` produces `check_stubs=False`
- [ ] CLI parser with `--no-check-getattr` produces `check_getattr=False`
- [ ] Config overrides dict includes both new fields
- [ ] `@summary` blocks updated in both files

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 2.1: Relative Import Resolution

**Description:** Modify `_extract_imports` to return 4-tuples `(module, name, lineno, level)` instead of 3-tuples, including relative imports (previously skipped). Add `_resolve_relative_import` helper that converts a relative import to an absolute dotted module path using the importing file's package position. Handle edge cases: files not inside packages, resolution ascending above project root, bare `from . import foo` syntax.

**Spec requirements:** REQ-313, REQ-315, REQ-317, REQ-319, REQ-321, REQ-915, REQ-917, REQ-919

**Dependencies:** Task 1.1

**Source files:**
- MODIFY `import_check/checker.py`

---

**Phase 0 contracts (inlined -- implement these stubs):**

```python
# import_check/checker.py
# MODIFIED function: _extract_imports -- new return type

def _extract_imports(source: str) -> list[tuple[str | None, str, int, int]]:
    """Parse Python source and extract all import statements.

    Uses ``ast.walk()`` so that imports at *any* nesting depth are captured:
    lazy imports inside functions, ``TYPE_CHECKING`` blocks, ``try/except``, etc.

    Handles:

    - ``from X import Y``       -> ``(X, Y, lineno, 0)``
    - ``from X import Y as Z``  -> ``(X, Y, lineno, 0)``
    - ``import X``              -> ``(X, "", lineno, 0)``
    - ``import X as Z``         -> ``(X, "", lineno, 0)``
    - ``from .foo import bar``  -> ``("foo", "bar", lineno, 1)``
    - ``from ..foo import bar`` -> ``("foo", "bar", lineno, 2)``
    - ``from . import bar``     -> ``(None, "bar", lineno, 1)``

    Relative imports are included with their level (REQ-313). The module
    field may be ``None`` for bare relative imports (``from . import foo``).

    Args:
        source: Python source code string.

    Returns:
        List of ``(module, name, lineno, level)`` tuples.
    """
    raise NotImplementedError("Task 2.1")


# NEW function: _resolve_relative_import

def _resolve_relative_import(
    module: str | None,
    level: int,
    file_path: str,
    root: Path,
) -> str | None:
    """Resolve a relative import to an absolute dotted module path.

    Uses the importing file's filesystem position and the project root
    to compute the absolute package path (REQ-315).

    Resolution algorithm:
    1. Compute the importing file's package: convert ``file_path`` to a
       dotted path relative to ``root``, then take all but the last component
       (the module name itself).
    2. Ascend ``level`` components from the package path. If this ascends
       above the project root, return ``None`` (REQ-319).
    3. Append ``module`` (if not ``None``) to get the absolute dotted path.
    4. For bare relative imports (``from . import foo``), the resolved path
       is the package itself, and ``foo`` is the symbol to check (REQ-321).

    Only resolves within standard packages (directories with ``__init__.py``
    between the file and the project root). Returns ``None`` if the file
    is not inside a package (REQ-317).

    Args:
        module: The relative module name (e.g., ``"foo"`` from ``from .foo import bar``).
            ``None`` for bare relative imports (``from . import bar``).
        level: Number of dots in the relative import (1 for ``.``, 2 for ``..``).
        file_path: Path of the importing file, relative to ``root``.
        root: Project root directory.

    Returns:
        Absolute dotted module path (e.g., ``"src.pkg.foo"``), or ``None`` if
        resolution fails (file not in package, or ascension above root).
    """
    raise NotImplementedError("Task 2.1")
```

---

**Implementation steps:**

1. [REQ-313] Modify the `_extract_imports` return type annotation from `list[tuple[str, str, int]]` to `list[tuple[str | None, str, int, int]]`.
2. [REQ-313] Remove the `if node.level and node.level > 0: continue` skip in the `ast.ImportFrom` branch. Instead, include relative imports: set `level = node.level or 0` and `module_name = node.module` (which may be `None` for bare `from . import foo`). For absolute `ast.ImportFrom`, set `level = 0`. For `ast.Import`, set `level = 0`. Append 4-tuples `(module_name, alias.name, node.lineno, level)`.
3. [REQ-313] Handle the case where `module_name` is `None` for `ast.ImportFrom` with `level > 0` and `node.module is None` (bare relative imports). Do not skip these -- include them with `module = None`.
4. [REQ-315] Implement `_resolve_relative_import`. Step 1: convert `file_path` to parts using `Path(file_path).with_suffix("").parts`. If the file is `__init__.py`, the package is all parts except the last (`__init__`). Otherwise, the package is all parts except the last (the module name).
5. [REQ-317] In `_resolve_relative_import`, verify the file is inside a package by checking that `(root / Path(*package_parts) / "__init__.py").is_file()` for the immediate directory. If not a standard package, return `None`.
6. [REQ-319] In `_resolve_relative_import`, ascend `level - 1` components from the package path (level 1 = current package, level 2 = parent). If `level - 1 > len(package_parts)`, return `None` (ascending above root).
7. [REQ-321, REQ-315] In `_resolve_relative_import`, after ascending, append `module.split(".")` to the target parts if `module` is not `None`. If `module` is `None` (bare relative), return the package path itself (the caller will check the symbol against `__init__.py`). Return `".".join(target_parts)` or `None` if `target_parts` is empty.
8. [REQ-915] Verify no runtime imports, `importlib.import_module()`, `exec()`, or subprocess calls are used in the new code.
9. Update `@summary` block in `import_check/checker.py` to list `_resolve_relative_import` in the Exports line.

**Completion criteria:**
- [ ] `_extract_imports` returns 4-tuples for both absolute and relative imports
- [ ] Relative imports with `level > 0` are no longer skipped
- [ ] `_resolve_relative_import` handles single-level (`from .foo import bar`), multi-level (`from ..utils import helper`), and bare (`from . import foo`) relative imports
- [ ] `_resolve_relative_import` returns `None` for files not in packages and for resolution ascending above root
- [ ] No `NotImplementedError` remaining in `_extract_imports` or `_resolve_relative_import`
- [ ] `@summary` block updated

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 2.2: Runtime Symbol Suppression

**Description:** Add `_has_dynamic_getattr` helper that detects module-level `def __getattr__` via AST inspection. Add `_resolve_stub_file` helper that locates co-located `.pyi` stub files. Modify `_check_symbol_defined` to implement the fallback chain: (1) direct `.py` definition, (2) `__getattr__` presence (if `check_getattr` enabled), (3) `.pyi` stub definition (if `check_stubs` enabled). Add per-invocation caching for `__getattr__` detection and stub parsing results.

**Spec requirements:** REQ-323, REQ-325, REQ-327, REQ-329, REQ-331, REQ-333, REQ-915, REQ-917, REQ-919

**Dependencies:** Task 1.1

**Source files:**
- MODIFY `import_check/checker.py`

---

**Phase 0 contracts (inlined -- implement these stubs):**

```python
# import_check/checker.py
# NEW module-level caches and cache-clearing helper

_getattr_cache: dict[Path, bool] = {}
_stub_symbol_cache: dict[tuple[Path, str], bool] = {}


def _clear_caches() -> None:
    """Clear per-invocation caches.

    Called at the start of each ``check_imports`` invocation to prevent
    cross-invocation staleness (REQ-333).
    """
    _getattr_cache.clear()
    _stub_symbol_cache.clear()


# NEW function: _has_dynamic_getattr

def _has_dynamic_getattr(module_file: Path) -> bool:
    """Check if a module defines ``__getattr__`` at the module level.

    Parses the module file with ``ast`` and inspects only top-level
    ``FunctionDef`` nodes (REQ-325). Nested ``__getattr__`` definitions
    inside classes or functions do not count.

    Results are cached per file path within a single ``check_imports``
    invocation (REQ-333).

    Args:
        module_file: Path to the module source file.

    Returns:
        ``True`` if a module-level ``def __getattr__`` is found.
    """
    raise NotImplementedError("Task 2.2")


# NEW function: _resolve_stub_file

def _resolve_stub_file(module_file: Path) -> Path | None:
    """Locate the co-located ``.pyi`` stub file for a module.

    For ``module.py``, checks for ``module.pyi`` in the same directory.
    For ``package/__init__.py``, checks for ``package/__init__.pyi`` (REQ-329).

    Does not search any other locations (no site-packages, no typeshed).

    Args:
        module_file: Path to the ``.py`` module file.

    Returns:
        Path to the ``.pyi`` stub file if it exists, ``None`` otherwise.
    """
    raise NotImplementedError("Task 2.2")


# MODIFIED function: _check_symbol_defined -- added config parameter and fallback chain

def _check_symbol_defined(
    module_file: Path,
    symbol_name: str,
    config: ImportCheckConfig | None = None,
) -> bool:
    """Check if a symbol is defined in the given module, with fallback chain.

    Implements the ordered fallback chain (REQ-323):

    1. Check ``.py`` file for direct definition (existing behavior):
       ``FunctionDef``, ``AsyncFunctionDef``, ``ClassDef``, ``Assign``,
       ``AnnAssign``, ``ImportFrom`` re-export, ``__all__`` membership.
    2. If not found and ``config.check_getattr`` is ``True``: check if the
       ``.py`` file defines a module-level ``__getattr__`` (REQ-325).
       If present, return ``True`` (REQ-327 -- suppresses only
       ``SYMBOL_NOT_DEFINED``, not ``MODULE_NOT_FOUND`` or
       ``ENCAPSULATION_VIOLATION``).
    3. If not found and ``config.check_stubs`` is ``True``: locate the
       co-located ``.pyi`` stub file (REQ-329) and check for the symbol
       definition using AST parsing (REQ-331).

    If ``config`` is ``None``, both fallbacks are enabled (backward-compatible
    default).

    Args:
        module_file: Path to the module source file.
        symbol_name: Name to look for.
        config: Configuration controlling which fallbacks are enabled.
            When ``None``, defaults to all fallbacks enabled.

    Returns:
        ``True`` if the symbol is defined or resolvable via the fallback chain.
    """
    raise NotImplementedError("Task 2.2")
```

**Existing code context (read-only -- do not re-implement, reuse the logic):**

The existing `_check_symbol_defined` in `import_check/checker.py` contains the direct `.py` AST check logic (step 1 of the fallback chain). This logic checks `tree.body` for `FunctionDef`, `AsyncFunctionDef`, `ClassDef`, `Assign`, `AnnAssign`, `ImportFrom`, `Import`, and `__all__`. The new implementation must preserve this logic as step 1 and add steps 2 and 3 after it. Consider factoring the existing AST check into a private helper (e.g., `_check_symbol_in_ast`) so it can be reused for both `.py` and `.pyi` files.

---

**Implementation steps:**

1. [REQ-333] Add module-level cache dicts `_getattr_cache: dict[Path, bool] = {}` and `_stub_symbol_cache: dict[tuple[Path, str], bool] = {}` to `import_check/checker.py`.
2. [REQ-333] Implement `_clear_caches()` that calls `.clear()` on both cache dicts.
3. [REQ-325] Implement `_has_dynamic_getattr`. Check `_getattr_cache` first. If miss, read the file, `ast.parse()` it, iterate `tree.body` (NOT `ast.walk`) looking for `ast.FunctionDef` with `node.name == "__getattr__"`. Cache the result. On `SyntaxError`/`OSError`, cache `False` and return `False`.
4. [REQ-329] Implement `_resolve_stub_file`. Replace the `.py` extension with `.pyi` using `module_file.with_suffix(".pyi")`. Check if the stub path exists with `.is_file()`. Return the path or `None`.
5. [REQ-323, REQ-331] Refactor the existing `_check_symbol_defined` body: extract the core AST check (the logic that parses a file and checks `tree.body` for definitions + `__all__`) into a private helper (e.g., `_check_symbol_in_ast(file_path: Path, symbol_name: str) -> bool`). This helper will be reused for both `.py` and `.pyi` files.
6. [REQ-323] Implement the modified `_check_symbol_defined` with the 3-step fallback chain: (a) call `_check_symbol_in_ast(module_file, symbol_name)` -- if True, return True; (b) if `config is None or config.check_getattr`, call `_has_dynamic_getattr(module_file)` -- if True, log DEBUG and return True; (c) if `config is None or config.check_stubs`, call `_resolve_stub_file(module_file)` -- if not None, check `_stub_symbol_cache` first, then call `_check_symbol_in_ast(stub_file, symbol_name)`, cache the result.
7. [REQ-919] Wrap the stub file AST check in a try/except for `SyntaxError` and `OSError`. On exception, log WARNING and skip stub fallback for that module (do not cache failure as a definitive False for the symbol -- cache the failure at the file level or skip caching).
8. [REQ-915] Verify no runtime imports, `importlib.import_module()`, `exec()`, or subprocess calls are used.
9. Update `@summary` block to list `_has_dynamic_getattr`, `_resolve_stub_file`, `_clear_caches` in the Exports line.

**Completion criteria:**
- [ ] `_has_dynamic_getattr` detects module-level `__getattr__` and ignores class-level
- [ ] `_resolve_stub_file` finds `.pyi` co-located with `.py` and `__init__.pyi` co-located with `__init__.py`
- [ ] `_check_symbol_defined` implements the 3-step fallback chain controlled by config
- [ ] Caching works: repeated calls for the same module do not re-parse
- [ ] `.pyi` parse failures degrade gracefully (WARNING log, skip stub)
- [ ] No `NotImplementedError` remaining in `_has_dynamic_getattr`, `_resolve_stub_file`, or `_check_symbol_defined`
- [ ] `@summary` block updated

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 2.3: Inline Suppression Comments

**Description:** Add `_is_suppressed` helper that checks whether a source line contains the `# import_check: ignore` marker. This function is always active (no config toggle required). Suppressed imports are skipped before verification and logged at DEBUG level.

**Spec requirements:** REQ-335, REQ-337, REQ-339, REQ-341, REQ-915, REQ-917, REQ-919

**Dependencies:** Task 1.1

**Source files:**
- MODIFY `import_check/checker.py`

---

**Phase 0 contracts (inlined -- implement these stubs):**

```python
# import_check/checker.py
# NEW function

def _is_suppressed(source: str, lineno: int) -> bool:
    """Check if a source line contains the import_check suppression marker.

    Looks for the string ``# import_check: ignore`` anywhere on the
    source line at the given line number (REQ-335). The marker can appear
    at any position on the line -- it does not need to be at the end.

    This function is always active -- it does not require a configuration
    toggle (REQ-341).

    Args:
        source: Full source text of the file.
        lineno: 1-based line number to check.

    Returns:
        ``True`` if the line contains ``# import_check: ignore``.
    """
    raise NotImplementedError("Task 2.3")
```

---

**Implementation steps:**

1. [REQ-335] Implement `_is_suppressed`. Split `source` into lines using `source.splitlines()`. Access the line at index `lineno - 1` (converting 1-based to 0-based). Check if the string `"# import_check: ignore"` appears anywhere in the line using the `in` operator.
2. [REQ-335] Handle edge cases: if `lineno` is less than 1 or greater than the number of lines, return `False` (do not raise).
3. [REQ-341] Verify that `_is_suppressed` has no config parameter -- it is always active.
4. [REQ-915] Verify no runtime imports, `importlib.import_module()`, `exec()`, or subprocess calls are used.
5. Update `@summary` block in `import_check/checker.py` to list `_is_suppressed` in the Exports line.

**Completion criteria:**
- [ ] `_is_suppressed` returns `True` for lines containing `# import_check: ignore`
- [ ] `_is_suppressed` returns `False` for lines without the marker
- [ ] `_is_suppressed` returns `True` when the marker appears alongside other comments (e.g., `# import_check: ignore  # noqa`)
- [ ] `_is_suppressed` handles out-of-range line numbers without raising
- [ ] No config parameter required
- [ ] No `NotImplementedError` remaining in `_is_suppressed`
- [ ] `@summary` block updated

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 3.1: check_imports Orchestration Update

**Description:** Update the `check_imports` main loop to integrate all three enhancements: destructure 4-tuples from the modified `_extract_imports`, resolve relative imports, filter suppressed imports, and pass config through to the enhanced `_check_symbol_defined`. Clear per-invocation caches at the start. This is the convergence point where independently-developed helpers are wired into the main verification flow.

**Spec requirements:** REQ-337, REQ-917, REQ-919

**Dependencies:** Task 2.1, Task 2.2, Task 2.3

**Source files:**
- MODIFY `import_check/checker.py`

---

**Phase 0 contracts (inlined -- implement these stubs):**

```python
# import_check/checker.py
# MODIFIED function: check_imports -- updated orchestration

def check_imports(
    files: list[str],
    root: Path,
    config: ImportCheckConfig | None = None,
) -> list[ImportError]:
    """Check all imports in the given files for errors.

    For each import statement, verifies:

    1. The target module resolves to an existing ``.py`` file or package
       ``__init__.py``.
    2. For ``from X import Y``, symbol *Y* is defined in module *X*,
       with fallback chain: direct definition -> ``__getattr__`` presence
       -> ``.pyi`` stub definition (REQ-323).
    3. If ``config.encapsulation_check`` is ``True``, flags imports that bypass
       ``__init__.py`` to reach internal modules directly.

    Enhanced behavior:

    - Relative imports are resolved to absolute paths before verification
      (REQ-315). Unresolvable relative imports are skipped with DEBUG log.
    - Imports on lines containing ``# import_check: ignore`` are skipped
      before verification and logged at DEBUG level (REQ-337, REQ-339).
    - Symbol verification uses the fallback chain controlled by
      ``config.check_getattr`` and ``config.check_stubs`` (REQ-323).
    - Per-invocation caches for ``__getattr__`` detection and stub parsing
      are cleared at the start of each call (REQ-333).

    Args:
        files: List of Python file paths to check (relative to *root*).
        root: Project root directory.
        config: Optional configuration. Uses defaults if ``None``.

    Returns:
        List of ``ImportError`` records. Empty if all imports are clean.
    """
    raise NotImplementedError("Task 3.1")
```

**Helper signatures available from prior tasks (already implemented -- call these, do not re-implement):**

```python
# From Task 2.1:
def _extract_imports(source: str) -> list[tuple[str | None, str, int, int]]: ...
def _resolve_relative_import(module: str | None, level: int, file_path: str, root: Path) -> str | None: ...

# From Task 2.2:
def _clear_caches() -> None: ...
def _has_dynamic_getattr(module_file: Path) -> bool: ...
def _resolve_stub_file(module_file: Path) -> Path | None: ...
def _check_symbol_defined(module_file: Path, symbol_name: str, config: ImportCheckConfig | None = None) -> bool: ...

# From Task 2.3:
def _is_suppressed(source: str, lineno: int) -> bool: ...

# Existing (unchanged):
def _is_stdlib_or_thirdparty(module: str, root: Path) -> bool: ...
def _resolve_module_to_file(module: str, root: Path) -> Path | None: ...
def _check_encapsulation(module: str, file_path: str, root: Path) -> ImportError | None: ...
```

---

**Implementation steps:**

1. [REQ-333] Add `_clear_caches()` call at the very top of `check_imports`, after config defaulting and root resolution.
2. [REQ-313, REQ-337] Update the `_extract_imports(source)` call site to destructure 4-tuples: `for module, name, lineno, level in imports`.
3. [REQ-337, REQ-339] Add suppression filtering block immediately after destructuring: call `_is_suppressed(source, lineno)`. If True, log at DEBUG level with file path, line number, module, and name, then `continue`. This runs BEFORE any verification.
4. [REQ-315, REQ-317, REQ-319, REQ-321] Add relative import resolution block: if `level > 0`, call `_resolve_relative_import(module, level, file_path, root)`. If it returns `None`, log at DEBUG and `continue`. If `module` was `None` (bare relative), set `module = resolved` (the package path -- `name` stays as-is for symbol verification against `__init__.py`). Otherwise, set `module = resolved`.
5. [REQ-917] Preserve the existing `_is_stdlib_or_thirdparty` check after relative import resolution (resolved relative imports are now absolute and pass through the same filter).
6. [REQ-323] Update the `_check_symbol_defined` call to pass `config` as the third argument: `_check_symbol_defined(resolved_file, name, config)`.
7. [REQ-917] Preserve all existing logging (`logger.error`) alongside error collection. Preserve the existing encapsulation check block. The function signature is unchanged.
8. [REQ-919] Ensure no unhandled exceptions can escape: all new code paths have try/except or return-None guards.
9. Update `@summary` block in `import_check/checker.py` to reflect the enhanced orchestration.

**Completion criteria:**
- [ ] `check_imports` destructures 4-tuples from `_extract_imports`
- [ ] Suppressed imports are filtered before verification
- [ ] Relative imports are resolved to absolute paths
- [ ] Unresolvable relative imports are skipped with DEBUG log
- [ ] `_check_symbol_defined` receives `config` for fallback chain control
- [ ] `_clear_caches()` is called at the start of each invocation
- [ ] The function signature is unchanged (REQ-917)
- [ ] All existing error types and logging patterns are preserved
- [ ] No `NotImplementedError` remaining in `check_imports`
- [ ] `@summary` block updated

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Module Boundary Map

| Task | Source File | Action | Description |
|------|------------|--------|-------------|
| Task 1.1 | `import_check/schemas.py` | MODIFY | Add `check_stubs` and `check_getattr` fields to `ImportCheckConfig` |
| Task 1.1 | `import_check/__main__.py` | MODIFY | Add `--no-check-stubs` and `--no-check-getattr` CLI flags; wire to config overrides |
| Task 2.1 | `import_check/checker.py` | MODIFY | Modify `_extract_imports` return type; add `_resolve_relative_import` |
| Task 2.2 | `import_check/checker.py` | MODIFY | Add `_has_dynamic_getattr`, `_resolve_stub_file`, `_clear_caches`; modify `_check_symbol_defined` |
| Task 2.3 | `import_check/checker.py` | MODIFY | Add `_is_suppressed` |
| Task 3.1 | `import_check/checker.py` | MODIFY | Rewrite `check_imports` main loop to integrate all three enhancements |

**Note:** All changes are modifications to existing files. No new files are created. Tasks 2.1, 2.2, and 2.3 all modify `import_check/checker.py` but touch different functions -- they are parallelizable because their changes do not overlap. Task 3.1 modifies the `check_imports` function which calls the helpers added by Tasks 2.1-2.3, so it must run after all three complete.

---

## Dependency Graph

```
Phase 1 (Foundation)           Phase 2 (Parallel)              Phase 3 (Integration)

┌──────────────────┐
│  Task 1.1        │
│  Config & Schema │
│  Extension       │
└──────┬───────────┘
       │
       ├──────────────────────────────────────────┐
       │                                          │
       ├──────────────────┐                       │
       │                  │                       │
       v                  v                       v
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│  Task 2.1        │ │  Task 2.2        │ │  Task 2.3        │
│  Relative Import │ │  Runtime Symbol  │ │  Inline          │
│  Resolution      │ │  Suppression     │ │  Suppression     │
└──────┬───────────┘ └──────┬───────────┘ └──────┬───────────┘
       │                    │                    │
       └────────────────────┼────────────────────┘
                            │
                            v
                   ┌──────────────────┐
                   │  Task 3.1        │
                   │  check_imports   │
                   │  Orchestration   │
                   └──────────────────┘

Parallel wave 1: Task 1.1 (no dependencies)
Parallel wave 2: Task 2.1, Task 2.2, Task 2.3 (all depend only on Task 1.1)
Parallel wave 3: Task 3.1 (depends on Task 2.1, Task 2.2, Task 2.3)
```

---

## Task-to-REQ Traceability Table

| REQ ID | Description | Task(s) | Source File |
|--------|-------------|---------|-------------|
| REQ-313 | Import extraction returns level for every import | Task 2.1 | `import_check/checker.py` |
| REQ-315 | Resolve relative imports to absolute paths | Task 2.1 | `import_check/checker.py` |
| REQ-317 | Skip unresolvable relative imports (file not in package) | Task 2.1 | `import_check/checker.py` |
| REQ-319 | Skip relative imports ascending above project root | Task 2.1 | `import_check/checker.py` |
| REQ-321 | Handle bare relative imports (`from . import foo`) | Task 2.1 | `import_check/checker.py` |
| REQ-323 | Ordered fallback chain for symbol verification | Task 2.2 | `import_check/checker.py` |
| REQ-325 | `__getattr__` detection at module level only | Task 2.2 | `import_check/checker.py` |
| REQ-327 | `__getattr__` suppresses only SYMBOL_NOT_DEFINED | Task 2.2 | `import_check/checker.py` |
| REQ-329 | Co-located `.pyi` stub file resolution | Task 2.2 | `import_check/checker.py` |
| REQ-331 | AST-based symbol check in `.pyi` stubs | Task 2.2 | `import_check/checker.py` |
| REQ-333 | Per-invocation caching for `__getattr__` and stub results | Task 2.2 | `import_check/checker.py` |
| REQ-335 | Recognize `# import_check: ignore` marker | Task 2.3 | `import_check/checker.py` |
| REQ-337 | Suppression filtering before verification | Task 2.3, Task 3.1 | `import_check/checker.py` |
| REQ-339 | DEBUG log for suppressed imports | Task 2.3, Task 3.1 | `import_check/checker.py` |
| REQ-341 | Suppression always active (no config toggle) | Task 2.3 | `import_check/checker.py` |
| REQ-413 | CLI `--no-check-stubs` flag | Task 1.1 | `import_check/__main__.py` |
| REQ-415 | CLI `--no-check-getattr` flag | Task 1.1 | `import_check/__main__.py` |
| REQ-511 | `check_stubs` config field (bool, default True) | Task 1.1 | `import_check/schemas.py` |
| REQ-513 | `check_getattr` config field (bool, default True) | Task 1.1 | `import_check/schemas.py` |
| REQ-515 | New config fields follow existing precedence rules | Task 1.1 | `import_check/schemas.py`, `import_check/__main__.py` |
| REQ-915 | AST + filesystem only (no runtime imports) | Task 2.1, Task 2.2, Task 2.3 | `import_check/checker.py` |
| REQ-917 | External interface contract unchanged | Task 2.1, Task 2.2, Task 2.3, Task 3.1 | `import_check/checker.py` |
| REQ-919 | Graceful degradation for unavailable enhancements | Task 2.1, Task 2.2, Task 2.3, Task 3.1 | `import_check/checker.py` |

**Coverage verification:** All 23 REQs from the enhancements spec are assigned to at least one task. No orphan tasks -- every task traces to at least one REQ.
