# Import Check Enhancements -- Design Document

| Field | Value |
|-------|-------|
| **Document** | Import Check Enhancements Design Document |
| **Version** | 0.1 |
| **Status** | Draft |
| **Spec Reference** | `docs/import_check/IMPORT_CHECK_ENHANCEMENTS_SPEC.md` (REQ-313 through REQ-919) |
| **Companion Documents** | `docs/import_check/IMPORT_CHECK_DESIGN.md` (parent design), `docs/superpowers/specs/2026-03-29-import-check-enhancements-sketch.md` (design sketch) |
| **Output Path** | `docs/import_check/IMPORT_CHECK_ENHANCEMENTS_DESIGN.md` |
| **Produced by** | write-design-docs |
| **Task Decomposition Status** | [x] Approved |

> **Document Intent.** This document provides the technical design with task decomposition
> and contract-grade code appendix for the three import_check checker enhancements specified in
> `docs/import_check/IMPORT_CHECK_ENHANCEMENTS_SPEC.md`. Every task references the requirements
> it satisfies. Part B contract entries are consumed verbatim by the companion implementation docs.

> **Relationship to parent design.** This document extends the Import Check Tool Design Document
> (`IMPORT_CHECK_DESIGN.md`). The parent design covers the full import_check pipeline (inventory,
> differ, fixer, checker, API, CLI). This document covers only the three checker enhancements:
> relative import resolution, runtime symbol suppression, and inline suppression comments. All
> existing code contracts from the parent design remain in effect.

---

# Part A: Task-Oriented Overview

## Phase 1 -- Foundation: Configuration and Schema Extension

### Task 1.1: Config and Schema Extension

**Description:** Extend the `ImportCheckConfig` dataclass with two new boolean fields (`check_stubs`, `check_getattr`) and add corresponding CLI flags (`--no-check-stubs`, `--no-check-getattr`) to the argument parser. Wire the CLI flags to config overrides in the `main()` dispatch. This task establishes the configuration surface that all three enhancement tasks depend on.

**Requirements Covered:** REQ-511, REQ-513, REQ-515, REQ-413, REQ-415

**Dependencies:** None

**Complexity:** S

**Subtasks:**
1. Add `check_stubs: bool = True` field to `ImportCheckConfig` in `import_check/schemas.py` with docstring update.
2. Add `check_getattr: bool = True` field to `ImportCheckConfig` in `import_check/schemas.py` with docstring update.
3. Add `--no-check-stubs` argument to `_build_parser()` in `import_check/__main__.py` using `action="store_false"`, `dest="check_stubs"`, `default=True`.
4. Add `--no-check-getattr` argument to `_build_parser()` in `import_check/__main__.py` using `action="store_false"`, `dest="check_getattr"`, `default=True`.
5. Wire `check_stubs` and `check_getattr` from parsed args into the `config_overrides` dict in `main()`.

**Testing Strategy:** Unit test that `ImportCheckConfig()` defaults produce `check_stubs=True` and `check_getattr=True`. Unit test CLI parser with `--no-check-stubs` and `--no-check-getattr` flags producing `False` values. Verify config precedence: pyproject.toml < CLI flag < API kwarg.

---

## Phase 2 -- Enhancement Implementation (Parallelizable)

### Task 2.1: Relative Import Resolution

**Description:** Modify `_extract_imports` to return 4-tuples `(module, name, lineno, level)` instead of 3-tuples, including relative imports (previously skipped). Add `_resolve_relative_import` helper that converts a relative import to an absolute dotted module path using the importing file's package position. Handle edge cases: files not inside packages, resolution ascending above project root, bare `from . import foo` syntax.

**Requirements Covered:** REQ-313, REQ-315, REQ-317, REQ-319, REQ-321, REQ-915, REQ-917, REQ-919

**Dependencies:** Task 1.1

**Complexity:** M

**Subtasks:**
1. Modify `_extract_imports` return type annotation from `list[tuple[str, str, int]]` to `list[tuple[str | None, str, int, int]]`.
2. Remove the `if node.level and node.level > 0: continue` skip in `_extract_imports`; instead include relative imports with `level = node.level` and `module = node.module` (which may be `None` for bare `from . import foo`).
3. Implement `_resolve_relative_import(module: str | None, level: int, file_path: str, root: Path) -> str | None` helper function.
4. Update `check_imports` to destructure 4-tuples and call `_resolve_relative_import` for imports with `level > 0`, skipping unresolvable imports with DEBUG log.
5. Handle `from . import foo` (REQ-321): resolve to the current package and treat `foo` as the symbol to verify against `__init__.py`.

**Risks:** Namespace packages (directories without `__init__.py`) are out of scope but common in some projects. Mitigation: only resolve when the importing file is inside a directory with `__init__.py` between it and the project root. Fall back to skipping with DEBUG log if resolution fails.

**Testing Strategy:** Unit test `_resolve_relative_import` with: single-level relative (`from .foo import bar`), multi-level relative (`from ..utils import helper`), bare relative (`from . import foo`), file not in package (returns `None`), resolution ascending above root (returns `None`). Unit test updated `_extract_imports` returns 4-tuples for both absolute and relative imports.

---

### Task 2.2: Runtime Symbol Suppression

**Description:** Add `_has_dynamic_getattr` helper that detects module-level `def __getattr__` via AST inspection. Add `_resolve_stub_file` helper that locates co-located `.pyi` stub files. Modify `_check_symbol_defined` to implement the fallback chain: (1) direct `.py` definition, (2) `__getattr__` presence (if `check_getattr` enabled), (3) `.pyi` stub definition (if `check_stubs` enabled). Add per-invocation caching for `__getattr__` detection and stub parsing results.

**Requirements Covered:** REQ-323, REQ-325, REQ-327, REQ-329, REQ-331, REQ-333, REQ-915, REQ-917, REQ-919

**Dependencies:** Task 1.1

**Complexity:** M

**Subtasks:**
1. Implement `_has_dynamic_getattr(module_file: Path) -> bool` that parses the file with `ast` and checks `tree.body` for a `FunctionDef` with name `__getattr__` (module-level only, not nested in classes).
2. Implement `_resolve_stub_file(module_file: Path) -> Path | None` that checks for `.pyi` co-located with the `.py` file (or `__init__.pyi` for packages).
3. Modify `_check_symbol_defined` signature to accept `config: ImportCheckConfig` parameter and implement the ordered fallback chain.
4. Add `_getattr_cache: dict[Path, bool]` and `_stub_symbol_cache: dict[tuple[Path, str], bool]` as module-level caches, with a `_clear_caches()` helper called at the start of each `check_imports` invocation.
5. Handle graceful degradation: if `.pyi` file fails to parse, log WARNING and skip stub fallback for that module (REQ-919).

**Risks:** Caching strategy uses module-level dicts reset per `check_imports` call. If `check_imports` is called concurrently (not the current use case), caches would need thread-safety. Mitigation: document single-threaded assumption; caches are cleared at start of each invocation.

**Testing Strategy:** Unit test `_has_dynamic_getattr` with: module-level `__getattr__` (True), class-level only (False), no `__getattr__` (False). Unit test `_resolve_stub_file` with: `.pyi` exists (returns path), `.pyi` missing (returns None), `__init__.py` to `__init__.pyi`. Unit test fallback chain: symbol in `.py` (passes at step 1), symbol missing but `__getattr__` present (passes at step 2), symbol in `.pyi` only (passes at step 3), all fail (SYMBOL_NOT_DEFINED). Test with `check_getattr=False` and `check_stubs=False` disabling respective fallbacks.

---

### Task 2.3: Inline Suppression Comments

**Description:** Add `_is_suppressed` helper that checks whether a source line contains the `# import_check: ignore` marker. Update `check_imports` to filter out suppressed imports after extraction and before verification, logging each suppressed import at DEBUG level.

**Requirements Covered:** REQ-335, REQ-337, REQ-339, REQ-341, REQ-915, REQ-917, REQ-919

**Dependencies:** Task 1.1

**Complexity:** S

**Subtasks:**
1. Implement `_is_suppressed(source: str, lineno: int) -> bool` that splits source into lines and checks if the line at `lineno` (1-indexed) contains the string `# import_check: ignore`.
2. Update `check_imports` to call `_is_suppressed` for each extracted import and skip suppressed imports before any verification.
3. Add DEBUG-level log entry for each suppressed import: file path, line number, module, and name.
4. Verify that suppression requires no config toggle (always active per REQ-341).

**Testing Strategy:** Unit test `_is_suppressed` with: line containing marker (True), line without marker (False), marker with additional comments on same line (True), marker in a different position on the line (True). Unit test that suppressed imports do not appear in error output. Verify DEBUG log contains suppression entries.

---

## Phase 3 -- Integration: check_imports Orchestration

### Task 3.1: check_imports Orchestration Update

**Description:** Update the `check_imports` main loop to integrate all three enhancements: destructure 4-tuples from the modified `_extract_imports`, resolve relative imports, filter suppressed imports, and pass config through to the enhanced `_check_symbol_defined`. Clear per-invocation caches at the start. This is the convergence point where independently-developed helpers are wired into the main verification flow.

**Requirements Covered:** REQ-337, REQ-917, REQ-919

**Dependencies:** Task 2.1, Task 2.2, Task 2.3

**Complexity:** S

**Subtasks:**
1. Update the `_extract_imports` call site to destructure 4-tuples: `for module, name, lineno, level in imports`.
2. Add relative import resolution block: if `level > 0`, call `_resolve_relative_import` and skip (with DEBUG log) if it returns `None`.
3. Add suppression filtering block: call `_is_suppressed` and `continue` (with DEBUG log) for suppressed imports.
4. Update the `_check_symbol_defined` call to pass `config` for fallback chain control.
5. Add `_clear_caches()` call at the top of `check_imports` to reset per-invocation caches.

**Testing Strategy:** Integration test with a mock project tree containing: relative imports in packages, a module with `__getattr__`, a module with `.pyi` stub, and imports with `# import_check: ignore`. Verify that all three enhancements work together in a single `check_imports` call.

---

## Task Dependency Graph

```
Phase 1 (Foundation)           Phase 2 (Enhancements)          Phase 3 (Integration)

┌──────────────────┐
│  Task 1.1        │ [CRITICAL]
│  Config & Schema │
│  Extension       │
└──────┬───────────┘
       │
       ├───────────────────────────────────────────┐
       │                                           │
       ├──────────────────┐                        │
       │                  │                        │
       v                  v                        v
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  Task 2.1        │  │  Task 2.2        │  │  Task 2.3        │
│  Relative Import │  │  Runtime Symbol  │  │  Inline          │
│  Resolution      │  │  Suppression     │  │  Suppression     │
│  [CRITICAL]      │  │  [CRITICAL]      │  │                  │
└──────┬───────────┘  └──────┬───────────┘  └──────┬───────────┘
       │                     │                     │
       └─────────────────────┼─────────────────────┘
                             │
                             v
                    ┌──────────────────┐
                    │  Task 3.1        │
                    │  check_imports   │
                    │  Orchestration   │
                    │  [CRITICAL]      │
                    └──────────────────┘

Critical path: Task 1.1 → Task 2.1 (or 2.2) → Task 3.1
Parallel wave: Tasks 2.1, 2.2, 2.3 can execute concurrently
```

---

## Task-to-Requirement Mapping

| Task | Requirements Covered |
|------|---------------------|
| Task 1.1 | REQ-511, REQ-513, REQ-515, REQ-413, REQ-415 |
| Task 2.1 | REQ-313, REQ-315, REQ-317, REQ-319, REQ-321, REQ-915, REQ-917, REQ-919 |
| Task 2.2 | REQ-323, REQ-325, REQ-327, REQ-329, REQ-331, REQ-333, REQ-915, REQ-917, REQ-919 |
| Task 2.3 | REQ-335, REQ-337, REQ-339, REQ-341, REQ-915, REQ-917, REQ-919 |
| Task 3.1 | REQ-337, REQ-917, REQ-919 |

### Coverage Verification

Every REQ from the enhancements spec is assigned to at least one task:

| REQ ID | Task(s) | Verified |
|--------|---------|----------|
| REQ-313 | Task 2.1 | Yes |
| REQ-315 | Task 2.1 | Yes |
| REQ-317 | Task 2.1 | Yes |
| REQ-319 | Task 2.1 | Yes |
| REQ-321 | Task 2.1 | Yes |
| REQ-323 | Task 2.2 | Yes |
| REQ-325 | Task 2.2 | Yes |
| REQ-327 | Task 2.2 | Yes |
| REQ-329 | Task 2.2 | Yes |
| REQ-331 | Task 2.2 | Yes |
| REQ-333 | Task 2.2 | Yes |
| REQ-335 | Task 2.3 | Yes |
| REQ-337 | Task 2.3, Task 3.1 | Yes |
| REQ-339 | Task 2.3 | Yes |
| REQ-341 | Task 2.3 | Yes |
| REQ-413 | Task 1.1 | Yes |
| REQ-415 | Task 1.1 | Yes |
| REQ-511 | Task 1.1 | Yes |
| REQ-513 | Task 1.1 | Yes |
| REQ-515 | Task 1.1 | Yes |
| REQ-915 | Task 2.1, Task 2.2, Task 2.3 | Yes |
| REQ-917 | Task 2.1, Task 2.2, Task 2.3, Task 3.1 | Yes |
| REQ-919 | Task 2.1, Task 2.2, Task 2.3, Task 3.1 | Yes |

All 23 requirements covered. No orphan tasks. No uncovered requirements.

---

# Part B: Code Appendix

## B.1: ImportCheckConfig Extension -- Contract

Extends the existing `ImportCheckConfig` dataclass with two new fields for the runtime symbol suppression enhancements. Consumed by Task 1.1 (implementation), Task 2.2 (fallback chain control), Task 3.1 (config passing).

**Tasks:** Task 1.1, Task 2.2, Task 3.1
**Requirements:** REQ-511, REQ-513, REQ-515
**Type:** Contract (exact -- copied to implementation docs Phase 0)

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
    check_stubs: bool = True              # REQ-511 — .pyi stub fallback
    check_getattr: bool = True            # REQ-513 — __getattr__ suppression
```

**Key design decisions:**
- Both fields default to `True`, matching the spec's permissive-by-default stance.
- Fields are added at the end of the dataclass to maintain backward compatibility with any positional construction (though the existing code uses keyword-only construction).
- No validation beyond type -- `bool` fields cannot have invalid values. The existing `_load_config` in `__init__.py` already filters by `valid_fields`, so these new fields are automatically picked up from pyproject.toml.

---

## B.2: CLI Extension -- Contract

Extends the existing CLI argument parser with two new flags for disabling stub and getattr checking. Consumed by Task 1.1.

**Tasks:** Task 1.1
**Requirements:** REQ-413, REQ-415
**Type:** Contract (exact -- copied to implementation docs Phase 0)

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

**Key design decisions:**
- Follows the established `--no-<feature>` pattern from `--no-encapsulation-check` for consistency.
- `default=True` ensures the flags only override when explicitly passed, matching the 3-layer precedence model (REQ-515).
- Flags are wired directly into `config_overrides` (not conditionally), matching the existing pattern for `encapsulation_check`.

---

## B.3: Relative Import Resolution Helpers -- Contract

Defines the new `_resolve_relative_import` function and the modified `_extract_imports` return type. Consumed by Task 2.1 (implementation), Task 3.1 (integration).

**Tasks:** Task 2.1, Task 3.1
**Requirements:** REQ-313, REQ-315, REQ-317, REQ-319, REQ-321
**Type:** Contract (exact -- copied to implementation docs Phase 0)

```python
# import_check/checker.py
# MODIFIED function: _extract_imports — new return type

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

**Key design decisions:**
- `_extract_imports` stays source-only (no filesystem). The `level` field enables the caller to decide how to handle relative imports without burdening the extraction function with path resolution.
- `module` is `str | None` (not `str`) because `from . import foo` produces an AST node with `node.module = None`.
- `_resolve_relative_import` returns `None` for unresolvable cases rather than raising an exception, allowing the caller to skip gracefully with a DEBUG log.
- The function takes `file_path` as a string (not Path) to match the existing `check_imports` iteration pattern where file paths are strings relative to root.

---

## B.4: Runtime Symbol Suppression Helpers -- Contract

Defines the new `_has_dynamic_getattr`, `_resolve_stub_file` helpers and the modified `_check_symbol_defined` signature. Consumed by Task 2.2 (implementation), Task 3.1 (integration).

**Tasks:** Task 2.2, Task 3.1
**Requirements:** REQ-323, REQ-325, REQ-327, REQ-329, REQ-331, REQ-333
**Type:** Contract (exact -- copied to implementation docs Phase 0)

```python
# import_check/checker.py
# NEW helpers and MODIFIED function

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


# ---------------------------------------------------------------------------
# New helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Modified function
# ---------------------------------------------------------------------------

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

**Key design decisions:**
- `_check_symbol_defined` gains an optional `config` parameter (defaulting to `None`) for backward compatibility -- existing callers that pass only `(module_file, symbol_name)` continue to work with all fallbacks enabled.
- Caches are module-level dicts (not instance variables) because `checker.py` functions are module-level, not methods on a class. This matches the existing code style.
- `_clear_caches()` is separated from `check_imports` to keep cache management testable independently.
- `_has_dynamic_getattr` only checks `tree.body` (module-level), never walking into class bodies, per REQ-325.
- `_resolve_stub_file` does simple path manipulation (`.py` -> `.pyi`), no directory traversal.

---

## B.5: Inline Suppression Helper -- Contract

Defines the new `_is_suppressed` function. Consumed by Task 2.3 (implementation), Task 3.1 (integration).

**Tasks:** Task 2.3, Task 3.1
**Requirements:** REQ-335, REQ-337, REQ-339, REQ-341
**Type:** Contract (exact -- copied to implementation docs Phase 0)

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

**Key design decisions:**
- Takes the full source string and a line number rather than a pre-split line, matching the calling pattern in `check_imports` where the source is already available as a string.
- Uses simple string containment (`in`) rather than regex for the marker, matching the convention of `# noqa` and `# type: ignore` detection in other tools.
- No config parameter -- always active per REQ-341.

---

## B.6: Updated check_imports Orchestration -- Contract

Shows the modified `check_imports` function signature and docstring reflecting all three enhancements. Consumed by Task 3.1.

**Tasks:** Task 3.1
**Requirements:** REQ-337, REQ-917, REQ-919
**Type:** Contract (exact -- copied to implementation docs Phase 0)

```python
# import_check/checker.py
# MODIFIED function: check_imports — updated orchestration

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

**Key design decisions:**
- The function signature is unchanged (same positional parameters) to preserve the external interface contract (REQ-917).
- All enhancement logic is internal to the function body -- callers see the same interface.
- Cache clearing at the top of the function ensures each invocation starts clean.
- The ordering of operations within the loop is: extract -> resolve relative -> filter suppressed -> verify module -> verify symbol (with fallback chain) -> check encapsulation.

---

## B.7: Relative Import Resolution Algorithm -- Pattern

Illustrates the resolution algorithm for converting relative imports to absolute dotted paths, including edge case handling for files not in packages and resolution ascending above the project root.

**Tasks:** Task 2.1
**Requirements:** REQ-315, REQ-317, REQ-319, REQ-321
**Type:** Pattern (illustrative -- for implement-code only, never test agents)

```python
# Illustrative pattern — not the final implementation
# import_check/checker.py — _resolve_relative_import internals

from pathlib import Path


def _resolve_relative_import(
    module: str | None,
    level: int,
    file_path: str,
    root: Path,
) -> str | None:
    # Step 1: Compute the importing file's package path
    # Convert file_path to a dotted path relative to root
    # e.g., "src/pkg/sub/mod.py" -> ["src", "pkg", "sub", "mod"]
    fp = Path(file_path)
    parts = list(fp.with_suffix("").parts)

    # If the file is __init__.py, the file IS the package
    # e.g., "src/pkg/__init__.py" -> package is ["src", "pkg"]
    if fp.name == "__init__.py":
        package_parts = parts[:-1]  # remove "__init__"
    else:
        package_parts = parts[:-1]  # remove module name to get package

    # Step 2: Verify the file is inside a package
    # Walk from the file's directory toward root, checking for __init__.py
    # If no __init__.py found, the file is not in a package -> return None
    current = root / Path(*package_parts) if package_parts else root
    if package_parts and not (current / "__init__.py").is_file():
        # Not a standard package — skip
        return None

    # Step 3: Ascend `level` components
    # level=1 means current package, level=2 means parent, etc.
    # For "from .foo import bar" in src/pkg/sub/mod.py:
    #   package_parts = ["src", "pkg", "sub"]
    #   level=1 -> target_parts = ["src", "pkg", "sub"]  (current package)
    #   level=2 -> target_parts = ["src", "pkg"]          (parent package)
    ascend = level - 1  # level 1 = current package (0 ascensions)
    if ascend > len(package_parts):
        # Ascending above project root -> return None
        return None
    target_parts = package_parts[:len(package_parts) - ascend] if ascend > 0 else package_parts

    # Step 4: Append the relative module name
    if module:
        # "from .foo import bar" -> target_parts + ["foo"]
        target_parts = target_parts + module.split(".")
        return ".".join(target_parts)
    else:
        # "from . import bar" -> the target IS the package itself
        # The caller will check "bar" as a symbol in the package's __init__.py
        return ".".join(target_parts) if target_parts else None
```

**Key design decisions:**
- Level 1 means "current package" (zero ascensions), level 2 means "parent package" (one ascension). This matches Python's AST convention where `from .foo` has `level=1`.
- `__init__.py` files are treated as the package itself, not a submodule of the package. This is critical for correct resolution of `from . import foo` inside `__init__.py`.
- The function returns `None` (not raises) for unresolvable cases, giving the caller control over error reporting. This supports the graceful degradation requirement (REQ-919).
- Package validation checks only the immediate directory for `__init__.py`, not every ancestor. Full ancestor validation is left as an implementation detail.

---

## B.8: Symbol Verification Fallback Chain -- Pattern

Illustrates the fallback chain algorithm within `_check_symbol_defined` and the caching strategy for `__getattr__` detection and stub parsing.

**Tasks:** Task 2.2
**Requirements:** REQ-323, REQ-325, REQ-329, REQ-331, REQ-333
**Type:** Pattern (illustrative -- for implement-code only, never test agents)

```python
# Illustrative pattern — not the final implementation
# import_check/checker.py — _check_symbol_defined fallback chain

import ast
from pathlib import Path

# Module-level caches (cleared per check_imports invocation)
_getattr_cache: dict[Path, bool] = {}
_stub_symbol_cache: dict[tuple[Path, str], bool] = {}


def _has_dynamic_getattr(module_file: Path) -> bool:
    """Check module-level __getattr__ with caching."""
    if module_file in _getattr_cache:
        return _getattr_cache[module_file]

    result = False
    try:
        source = module_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(module_file))
    except (SyntaxError, OSError):
        _getattr_cache[module_file] = False
        return False

    # Only check tree.body (top-level), NOT ast.walk
    # This ensures class-level __getattr__ is not detected
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "__getattr__":
            result = True
            break

    _getattr_cache[module_file] = result
    return result


def _check_symbol_defined_with_fallback(module_file, symbol_name, config):
    """Illustrates the 3-step fallback chain."""

    # Step 1: Direct definition in .py (existing logic)
    if _check_symbol_in_source(module_file, symbol_name):
        return True

    # Step 2: __getattr__ presence (if enabled)
    if config is None or config.check_getattr:
        if _has_dynamic_getattr(module_file):
            logger.debug(
                "Symbol '%s' assumed present via __getattr__ in %s",
                symbol_name, module_file,
            )
            return True

    # Step 3: .pyi stub fallback (if enabled)
    if config is None or config.check_stubs:
        stub_file = _resolve_stub_file(module_file)
        if stub_file is not None:
            cache_key = (stub_file, symbol_name)
            if cache_key in _stub_symbol_cache:
                return _stub_symbol_cache[cache_key]
            try:
                # Reuse the SAME AST check logic as _check_symbol_defined
                # but against the .pyi file
                found = _check_symbol_in_source(stub_file, symbol_name)
                _stub_symbol_cache[cache_key] = found
                if found:
                    logger.debug(
                        "Symbol '%s' found in stub %s", symbol_name, stub_file,
                    )
                return found
            except (SyntaxError, OSError) as exc:
                # Graceful degradation: log warning, skip stub (REQ-919)
                logger.warning(
                    "Failed to parse stub file %s: %s", stub_file, exc,
                )

    return False
```

**Key design decisions:**
- The fallback chain is a linear if/elif structure, not a plugin system. Three steps is the design maximum; adding more would require spec revision.
- `_has_dynamic_getattr` only iterates `tree.body` (not `ast.walk`) to ensure class-level `__getattr__` is never detected (REQ-325).
- Stub file symbol checking reuses the same AST logic as `.py` symbol checking. `_check_symbol_in_source` is a factored-out version of the existing `_check_symbol_defined` body. The implementing agent decides whether to factor this out or inline it.
- Cache hits return immediately without re-parsing. Cache misses populate the cache on first access. The cache is never evicted within an invocation -- only cleared between invocations.
- `.pyi` parse failures are caught and logged as WARNING (not ERROR), and the stub fallback is skipped for that module. This satisfies the graceful degradation requirement (REQ-919).

---

## B.9: check_imports Integration Flow -- Pattern

Illustrates how all three enhancements integrate into the `check_imports` main loop, showing the ordering of extraction, resolution, suppression filtering, and enhanced verification.

**Tasks:** Task 3.1
**Requirements:** REQ-337, REQ-917, REQ-919
**Type:** Pattern (illustrative -- for implement-code only, never test agents)

```python
# Illustrative pattern — not the final implementation
# import_check/checker.py — check_imports enhanced main loop

def check_imports(files, root, config=None):
    """Enhanced main loop integrating all three enhancements."""
    if config is None:
        config = ImportCheckConfig()

    root = root.resolve()
    errors = []

    # Clear per-invocation caches (REQ-333)
    _clear_caches()

    for file_path in files:
        full_path = root / file_path
        try:
            source = full_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.error("Cannot read file %s: %s", file_path, exc)
            continue

        # Step 1: Extract imports (now returns 4-tuples with level)
        imports = _extract_imports(source)

        for module, name, lineno, level in imports:

            # Step 2: Suppression filtering (Enhancement 3)
            # Check BEFORE any verification — suppressed imports never enter pipeline
            if _is_suppressed(source, lineno):
                logger.debug(
                    "SUPPRESSED: %s:%d — %s.%s (# import_check: ignore)",
                    file_path, lineno, module or "", name,
                )
                continue

            # Step 3: Relative import resolution (Enhancement 1)
            if level > 0:
                resolved = _resolve_relative_import(module, level, file_path, root)
                if resolved is None:
                    logger.debug(
                        "SKIP: %s:%d — unresolvable relative import (level=%d)",
                        file_path, lineno, level,
                    )
                    continue
                # For "from . import foo": resolved is the package path,
                # name is "foo", and we verify foo in __init__.py
                if module is None:
                    # Bare relative: "from . import foo"
                    module = resolved
                    # name stays as-is — it's the symbol to check
                else:
                    module = resolved

            # Step 4: Skip stdlib/third-party (existing)
            if _is_stdlib_or_thirdparty(module, root):
                continue

            # Step 5: Module resolution (existing)
            resolved_file = _resolve_module_to_file(module, root)
            if resolved_file is None:
                errors.append(ImportError(
                    file_path=file_path, lineno=lineno, module=module,
                    name=name, error_type=ImportErrorType.MODULE_NOT_FOUND,
                    message=f"Module '{module}' not found",
                ))
                continue

            # Step 6: Symbol verification with fallback chain (Enhancement 2)
            if name:
                if not _check_symbol_defined(resolved_file, name, config):
                    errors.append(ImportError(
                        file_path=file_path, lineno=lineno, module=module,
                        name=name, error_type=ImportErrorType.SYMBOL_NOT_DEFINED,
                        message=f"Symbol '{name}' not defined in '{module}'",
                    ))

            # Step 7: Encapsulation check (existing)
            if config.encapsulation_check:
                enc_err = _check_encapsulation(module, file_path, root)
                if enc_err is not None:
                    enc_err = ImportError(
                        file_path=enc_err.file_path, lineno=lineno,
                        module=enc_err.module, name=name,
                        error_type=enc_err.error_type, message=enc_err.message,
                    )
                    errors.append(enc_err)

    return errors
```

**Key design decisions:**
- Suppression filtering runs before relative import resolution. This means `from .foo import bar  # import_check: ignore` is suppressed without needing to resolve the relative path first -- more efficient and simpler.
- Relative import resolution replaces the `module` variable in-place for the rest of the loop iteration. After resolution, a relative import is indistinguishable from an absolute one in the verification pipeline.
- `_check_symbol_defined` receives `config` to control which fallbacks are active. The existing call signature is backward-compatible (`config` defaults to `None` which enables all fallbacks).
- The `_clear_caches()` call at the top ensures no stale data from a previous invocation contaminates the current run.
- The `logger.error` calls from the existing code are replaced with `errors.append` in this pattern to show the flow. The implementing agent should preserve the existing logging alongside error collection.
