# Import Check Enhancements Specification

**RAG Project -- Developer Tooling**
Version: 1.0 | Status: Draft | Domain: Python Import Analysis & Repair

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-29 | Autonomous Pipeline | Initial draft -- 3 checker enhancements |

---

## Relationship to Parent Spec

This document extends the **Import Check Tool Specification** (`IMPORT_CHECK_SPEC.md`, v1.0). All requirement IDs continue from the parent spec's numbering. Requirements defined here are additive -- they do not modify or supersede any existing requirement in the parent spec.

**Parent spec ID ranges in use:**

| Section | ID Range | Component |
|---------|----------|-----------|
| Section 3 | REQ-101 through REQ-111 | Symbol Inventory & Diffing |
| Section 4 | REQ-201 through REQ-217 | Deterministic Fixer |
| Section 5 | REQ-301 through REQ-311 | Smoke Test Checker |
| Section 6 | REQ-401 through REQ-411 | Public API & CLI |
| Section 7 | REQ-501 through REQ-509 | Configuration |
| Section 10 | REQ-901 through REQ-913 | Non-Functional Requirements |

**This spec adds:**

| Section | ID Range | Component |
|---------|----------|-----------|
| Section 3 | REQ-313 through REQ-321 | Relative Import Resolution (Checker) |
| Section 4 | REQ-323 through REQ-333 | Runtime Symbol Suppression (Checker) |
| Section 5 | REQ-335 through REQ-341 | Inline Suppression Comments (Checker) |
| Section 6 | REQ-413 through REQ-415 | CLI Extensions |
| Section 7 | REQ-511 through REQ-515 | Configuration Extensions |
| Section 8 | REQ-915 through REQ-919 | Non-Functional Requirements |

All new IDs fall within the parent spec's established ranges (3xx for Checker, 4xx for CLI, 5xx for Configuration, 9xx for NFR) and use gaps left by the parent spec's odd-numbered convention.

---

## 1. Scope & Definitions

### 1.1 Problem Statement

The smoke test checker (Step 3 of the import_check pipeline) has three accuracy and usability gaps:

1. **Relative imports are skipped.** The checker's import extraction function receives only source text, not the importing file's path. When it encounters `from .foo import bar` or `from ..utils import helper`, it cannot determine the absolute module path and silently skips the import. This means relative imports receive no verification at all -- a blind spot that grows with codebase size and is especially problematic for projects that use relative imports throughout.

2. **Dynamic symbol providers cause false positives.** Modules that define `__getattr__` at module scope can dynamically provide any attribute name at runtime. The checker, which performs static AST analysis only, reports `SYMBOL_NOT_DEFINED` for symbols imported from such modules even when those symbols are intentionally provided via `__getattr__`. Similarly, some modules define their public API in `.pyi` stub files rather than (or in addition to) the `.py` source. The checker does not consult stub files, producing false positives for stub-defined symbols.

3. **No per-line suppression mechanism exists.** When the checker reports a false positive that cannot be resolved by configuration (e.g., a symbol provided by a C extension, a conditional re-export, or a runtime-generated attribute not covered by `__getattr__`), developers have no way to suppress it. The only option is to ignore the entire checker output, which defeats its purpose as a verification gate.

### 1.2 Scope

This specification defines requirements for three enhancements to the **smoke test checker** component of the import_check tool:

- **Entry point:** The checker receives a list of Python files to verify, each with its source text and file path.
- **Exit point:** The checker produces a structured error list, with relative imports now verified, dynamic symbol providers recognized, and suppressed imports logged but excluded from the error list.

All three enhancements are scoped to the checker (Step 3). They do not modify the symbol inventory (Step 1), the deterministic fixer (Step 2), or the output formatting (Step 4).

### 1.3 Additional Terminology

These terms supplement the terminology defined in the parent spec (Section 1.3).

| Term | Definition |
|------|-----------|
| **Relative import** | A Python import statement that uses dot notation to reference a module relative to the importing file's package position (e.g., `from .foo import bar`, `from ..utils import helper`). The `level` attribute on the AST node indicates the number of dots. |
| **Import level** | The integer depth of a relative import: 0 for absolute imports, 1 for `from .` (current package), 2 for `from ..` (parent package), and so on. |
| **`__getattr__`** | A module-level function (`def __getattr__(name: str) -> Any`) that Python calls when an attribute is not found via normal lookup. Modules defining this function can dynamically provide any attribute name. |
| **Stub file** | A `.pyi` file that provides type annotations and symbol declarations for a corresponding `.py` module. Stub files follow PEP 484 conventions and are recognized by type checkers and IDEs. |
| **Inline suppression** | A per-line comment (`# import_check: ignore`) that instructs the checker to skip verification of all imports on that source line. Analogous to `# noqa` (flake8) and `# type: ignore` (mypy). |
| **Suppressed import** | An import that appears on a source line containing an inline suppression comment. Suppressed imports are extracted but excluded from verification. |

### 1.4 Design Principles

These principles supplement the parent spec's design principles (Section 1.7).

| Principle | Description |
|-----------|-------------|
| **Source-only extraction** | The import extraction function (`_extract_imports`) operates on source text alone. Filesystem-dependent operations (path resolution, stub file lookup) are performed by the caller, preserving the extraction function's purity and testability. |
| **Explicit fallback chain** | When multiple detection mechanisms can resolve a symbol (direct definition, `__getattr__`, stub file), they are applied in a defined order with each step clearly separated. The chain is: `.py` definition, then `__getattr__` presence, then `.pyi` stub definition. |
| **Auditable suppression** | Suppressed imports are never silently discarded. They are logged at DEBUG level so developers can audit which imports are being skipped and verify that suppression comments are correctly applied. |

### 1.5 Out of Scope

**Out of scope -- this spec:**

- Relative import resolution in the **deterministic fixer** (Step 2). The fixer operates on migration maps and absolute module paths, not raw relative imports.
- Recursive `.pyi` stub resolution (following re-exports within stub files). Only direct symbol definitions in the stub are checked.
- Block-level suppression comments (e.g., `# import_check: ignore-block` covering multiple consecutive lines).
- `TYPE_CHECKING`-aware suppression (automatically suppressing all imports inside `if TYPE_CHECKING:` blocks).
- Third-party `.pyi` stub packages (e.g., `types-requests`, `types-PyYAML`). Only project-local `.pyi` files co-located with their `.py` counterparts are consulted.
- Inline suppression in the fixer. The fixer rewrites imports based on migration maps; suppression applies only to the checker.
- `py.typed` marker file detection.
- Namespace package support for relative import resolution. Only standard packages (directories with `__init__.py`) are supported.

**Out of scope -- this project (unchanged from parent spec):**

- Truly dynamic string construction (e.g., `f"src.{runtime_var}"`).
- Proactive refactoring (moving symbols to new locations).
- Non-Python configuration files that reference Python module paths.
- Cross-repository imports.
- Runtime import hook analysis or custom finder/loader mechanisms.

---

## 2. System Overview

### 2.1 Enhancement Placement in Pipeline

```
Developer invokes: python -m import_check [fix|check|run]
    |
    v
+---------------------------------------------------------+
| [1] SYMBOL INVENTORY & DIFFING  (unchanged)             |
+-----------------------+---------------------------------+
                        | migration map
                        v
+---------------------------------------------------------+
| [2] DETERMINISTIC FIXER  (unchanged)                    |
+-----------------------+---------------------------------+
                        | rewritten files
                        v
+---------------------------------------------------------+
| [3] SMOKE TEST CHECKER  *** ENHANCED ***                |
|                                                         |
|   _extract_imports:                                     |
|     - Returns 4-tuple with import level  [Enhancement 1]|
|     - Still source-only (no filesystem)                 |
|                                                         |
|   check_imports:                                        |
|     - Resolves relative imports to       [Enhancement 1]|
|       absolute paths via file location                  |
|     - Filters suppressed imports before  [Enhancement 3]|
|       verification, logs at DEBUG                       |
|     - Falls back to __getattr__ and     [Enhancement 2]|
|       .pyi stubs for symbol checking                    |
|                                                         |
|   New helpers:                                          |
|     _resolve_relative_import             [Enhancement 1]|
|     _has_dynamic_getattr                 [Enhancement 2]|
|     _resolve_stub_file                   [Enhancement 2]|
|     _is_suppressed                       [Enhancement 3]|
+-----------------------+---------------------------------+
                        | structured error list
                        v
+---------------------------------------------------------+
| [4] OUTPUT  (unchanged)                                 |
+---------------------------------------------------------+
```

### 2.2 Data Flow for Enhanced Checker

| Step | Input | Output | Enhancement |
|------|-------|--------|-------------|
| Import extraction | Source text of a Python file | List of 4-tuples: `(module, name, lineno, level)` | 1 (level field added) |
| Relative import resolution | 4-tuple with `level > 0`, importing file path, project root | Absolute dotted module path (or `None` if unresolvable) | 1 |
| Inline suppression filtering | List of extracted imports, source text | Filtered list (suppressed imports removed), DEBUG log entries for suppressed imports | 3 |
| Module resolution | Absolute dotted module path | Filesystem path to `.py` file (or module-not-found error) | -- (existing) |
| Symbol verification | Module `.py` file path, symbol name | Symbol found (True/False), with fallback chain: direct definition, `__getattr__` presence, `.pyi` stub definition | 2 |
| Error assembly | Verification results | Structured error list (suppressed imports excluded, relative imports now included) | 1, 2, 3 |

---

## 3. Relative Import Resolution

> **REQ-313** | Priority: MUST
>
> **Description:** The import extraction function MUST return the import level for every extracted import, where the level is 0 for absolute imports and greater than 0 for relative imports. Relative imports MUST NOT be skipped or discarded during extraction.
>
> **Rationale:** The parent spec's checker silently skips relative imports because the extraction function has no mechanism to distinguish them from absolute imports or pass the level information to the caller. Without the level, the caller cannot resolve relative imports to absolute paths. Returning the level for all imports (including absolute, where level is 0) provides a uniform interface.
>
> **Acceptance Criteria:** Given source text containing `from .foo import bar`, the extraction function returns a tuple where the module is `foo`, the name is `bar`, and the level is 1. Given `from ..utils import helper`, the level is 2 and the module is `utils`. Given `from src.foo import bar` (absolute), the level is 0. Given `from . import baz` (bare relative with no module), the module is empty or `None` and the level is 1.

> **REQ-315** | Priority: MUST
>
> **Description:** The checker MUST resolve relative imports to absolute dotted module paths before performing module and symbol verification. Resolution MUST use the importing file's filesystem path and the project root to compute the absolute package path.
>
> **Rationale:** Relative imports cannot be verified against the filesystem without first converting them to absolute paths. The resolution logic must be external to the extraction function (which operates on source text only) and must use the importing file's position in the package hierarchy to compute the correct absolute path.
>
> **Acceptance Criteria:** Given file `/project/src/foo/bar.py` containing `from .baz import helper` with project root `/project`, the checker resolves the import to absolute path `src.foo.baz` and verifies that `src/foo/baz.py` exists and defines `helper`. Given file `/project/src/foo/sub/mod.py` containing `from ..baz import helper`, the checker resolves to `src.foo.baz`. Given a file at the project root (not inside any package), a relative import is unresolvable and the checker skips it with a DEBUG log.

> **REQ-317** | Priority: MUST
>
> **Description:** When relative import resolution fails because the importing file is not inside a package (no `__init__.py` in any ancestor directory between the file and the project root), the checker MUST skip the import without reporting an error and MUST log the skip at DEBUG level.
>
> **Rationale:** Relative imports are only valid inside packages. A file at the top level of a project (not inside a package directory) cannot have its relative imports resolved. Reporting an error for this case would produce false positives. Logging at DEBUG level makes the skip auditable without cluttering normal output.
>
> **Acceptance Criteria:** Given file `/project/script.py` (no `__init__.py` in `/project/`) containing `from .utils import foo`, the checker does not report an error for this import. The DEBUG log contains an entry indicating the import was skipped because the file is not inside a package.

> **REQ-319** | Priority: MUST
>
> **Description:** When relative import resolution produces an absolute path that points to a module outside the project root, the checker MUST skip the import without reporting an error and MUST log the skip at DEBUG level.
>
> **Rationale:** A relative import with a level that ascends above the project root (e.g., `from ....` in a shallow package) cannot be resolved within the project. Reporting an error would be misleading since the import may resolve correctly at runtime via installed packages or path manipulation.
>
> **Acceptance Criteria:** Given file `/project/src/foo.py` containing `from ...bar import baz` (level 3, but `src/foo.py` is only 1 level deep inside `src`), the checker does not report an error. The DEBUG log contains an entry indicating the import was skipped because resolution ascended above the project root.

> **REQ-321** | Priority: SHOULD
>
> **Description:** The checker SHOULD treat package-relative imports (`from . import foo`) the same as module-relative imports (`from .foo import bar`), resolving `from . import foo` to the current package's `__init__.py` and verifying that `foo` is defined or re-exported there.
>
> **Rationale:** `from . import foo` is equivalent to importing `foo` from the current package's `__init__.py`. Treating it differently from `from .foo import bar` would leave a class of relative imports unverified.
>
> **Acceptance Criteria:** Given file `/project/src/pkg/mod.py` containing `from . import utils` where `/project/src/pkg/__init__.py` re-exports `utils`, the check passes. Given `from . import nonexistent` where `nonexistent` is not defined in `__init__.py`, the checker reports a `SYMBOL_NOT_DEFINED` error.

---

## 4. Runtime Symbol Suppression

> **REQ-323** | Priority: MUST
>
> **Description:** When verifying that a symbol is defined in a target module, the checker MUST apply a fallback chain in the following order: (1) check for direct definition in the `.py` source file (existing behavior), (2) if not found and `check_getattr` is enabled, check whether the `.py` source file defines a module-level `__getattr__` function, (3) if not found and `check_stubs` is enabled, check for the symbol in the corresponding `.pyi` stub file. If any step in the chain succeeds, the symbol is considered defined.
>
> **Rationale:** A single static check against the `.py` source is insufficient for modules that provide symbols dynamically (`__getattr__`) or declare their API in stub files (`.pyi`). The ordered fallback chain ensures that the cheapest check (direct definition) runs first, with progressively more expensive checks applied only when needed. Making each fallback configurable ensures operators can control the checker's permissiveness.
>
> **Acceptance Criteria:** Given a module `src/lazy.py` that defines `def __getattr__(name): ...` at module level but does not define `Widget`, `from src.lazy import Widget` passes the check when `check_getattr` is enabled. Given a module `src/typed.py` that does not define `Config` in its `.py` source, but `src/typed.pyi` declares `Config: TypeAlias = ...`, `from src.typed import Config` passes the check when `check_stubs` is enabled. Given a module that fails all three checks, the checker reports `SYMBOL_NOT_DEFINED`.

> **REQ-325** | Priority: MUST
>
> **Description:** The `__getattr__` detection MUST examine only module-level `FunctionDef` nodes in the AST. Nested `__getattr__` definitions (inside classes or other functions) MUST NOT trigger suppression.
>
> **Rationale:** Only a module-level `__getattr__` acts as a dynamic attribute provider for the module's import namespace. A `__getattr__` defined inside a class is the class's attribute hook, not the module's, and does not affect what symbols can be imported from the module.
>
> **Acceptance Criteria:** Given a module containing only `class Foo: def __getattr__(self, name): ...` (class-level `__getattr__` with no module-level `__getattr__`), importing an undefined symbol from that module reports `SYMBOL_NOT_DEFINED`. Given a module containing `def __getattr__(name): ...` at the top level (not inside any class or function), importing an undefined symbol from that module passes when `check_getattr` is enabled.

> **REQ-327** | Priority: MUST
>
> **Description:** The `__getattr__` presence MUST suppress only `SYMBOL_NOT_DEFINED` errors. It MUST NOT suppress `MODULE_NOT_FOUND` or `ENCAPSULATION_VIOLATION` diagnostics.
>
> **Rationale:** `__getattr__` affects which symbols a module can provide, not whether the module file exists or whether the import path respects encapsulation boundaries. Suppressing module-level or encapsulation errors based on `__getattr__` would mask genuine problems.
>
> **Acceptance Criteria:** Given `from src.nonexistent import foo` where `src/nonexistent.py` does not exist, the checker reports `MODULE_NOT_FOUND` regardless of whether any other module defines `__getattr__`. Given an import that constitutes an encapsulation violation, the violation is reported regardless of `__getattr__` presence in the target module.

> **REQ-329** | Priority: MUST
>
> **Description:** Stub file resolution MUST locate the `.pyi` file by replacing the `.py` extension of the module file path with `.pyi`. For package `__init__.py` files, the corresponding stub MUST be `__init__.pyi` in the same directory. The checker MUST NOT search for stub files in any other location.
>
> **Rationale:** Limiting stub resolution to co-located files ensures deterministic, fast lookup without filesystem traversal. Third-party stub packages (e.g., `types-requests`) installed in site-packages are out of scope because the checker operates on project-local files only, consistent with the zero-cost verification principle.
>
> **Acceptance Criteria:** Given module file `/project/src/foo.py`, the checker looks for `/project/src/foo.pyi`. Given package init `/project/src/pkg/__init__.py`, the checker looks for `/project/src/pkg/__init__.pyi`. Given that neither co-located stub path exists, the checker does not search elsewhere and proceeds to the next fallback (or reports the symbol as not found).

> **REQ-331** | Priority: MUST
>
> **Description:** When checking a stub file for symbol definitions, the checker MUST parse the `.pyi` file with `ast` and check for top-level definitions (`FunctionDef`, `ClassDef`, `Assign`, `AnnAssign`) matching the symbol name. The checker MUST NOT execute or import the stub file.
>
> **Rationale:** Stub files are Python syntax and can be parsed with `ast` like any other Python file. Executing them would violate the zero-cost verification principle. `AnnAssign` (annotated assignment) must be checked in addition to `Assign` because stub files commonly declare symbols as `name: Type` without a value.
>
> **Acceptance Criteria:** Given `src/foo.pyi` containing `class Widget: ...`, checking for symbol `Widget` in the stub returns True. Given `src/foo.pyi` containing `API_VERSION: int`, checking for `API_VERSION` returns True. Given `src/foo.pyi` containing `def process(data: bytes) -> str: ...`, checking for `process` returns True. The check completes without importing or executing `src/foo.pyi`.

> **REQ-333** | Priority: SHOULD
>
> **Description:** The checker SHOULD cache the results of `__getattr__` detection and stub file parsing for each module file within a single `check_imports` invocation, so that repeated imports from the same module do not re-parse the file.
>
> **Rationale:** A codebase may contain many imports from the same module across different files. Re-parsing the module's AST for each import is wasteful. Caching within a single invocation avoids redundant work without introducing cross-invocation staleness risks.
>
> **Acceptance Criteria:** Given 10 files that each import a different symbol from `src/lazy.py` (which defines `__getattr__`), the checker parses `src/lazy.py` once (verifiable via DEBUG logging showing a single parse event for the file). Subsequent checks for that module use the cached result.

---

## 5. Inline Suppression Comments

> **REQ-335** | Priority: MUST
>
> **Description:** The checker MUST recognize the comment marker `# import_check: ignore` on any source line. When an import statement appears on a line containing this marker, the checker MUST skip verification of all imports on that line.
>
> **Rationale:** Developers need a per-line escape hatch for imports that the checker cannot verify statically (C extensions, runtime-generated attributes, conditional re-exports). The `# import_check: ignore` convention follows established Python tooling patterns (`# noqa`, `# type: ignore`), minimizing learning curve.
>
> **Acceptance Criteria:** Given `from src.native import fast_func  # import_check: ignore`, the checker does not verify whether `src/native.py` exists or defines `fast_func`. Given `from src.foo import bar  # import_check: ignore  # noqa`, the suppression still applies (other comments on the same line do not interfere). Given `from src.foo import bar  # this is not suppressed`, the checker verifies the import normally.

> **REQ-337** | Priority: MUST
>
> **Description:** Suppression filtering MUST occur after import extraction and before module/symbol verification. Suppressed imports MUST NOT enter the verification pipeline.
>
> **Rationale:** Filtering before verification ensures that suppressed imports cannot generate errors, warnings, or encapsulation violations. Filtering after extraction (rather than during) preserves the extraction function's source-only purity and enables DEBUG-level auditing of what was suppressed.
>
> **Acceptance Criteria:** Given a file with 5 import statements, 2 of which have `# import_check: ignore`, the checker runs verification on exactly 3 imports. The 2 suppressed imports do not appear in the error list, the encapsulation violation list, or the summary statistics for verified imports.

> **REQ-339** | Priority: MUST
>
> **Description:** The checker MUST log every suppressed import at DEBUG level. The log entry MUST include the file path, line number, and the suppressed import text.
>
> **Rationale:** Silent suppression creates a maintenance hazard -- developers may forget which imports are suppressed and why. DEBUG-level logging makes suppressions visible during troubleshooting without cluttering normal INFO-level output. This follows the auditable suppression design principle.
>
> **Acceptance Criteria:** Given `from src.native import fast_func  # import_check: ignore` in file `src/caller.py` at line 5, the DEBUG log contains an entry with text identifying `src/caller.py`, line 5, and the import `from src.native import fast_func` as suppressed. At INFO and ERROR log levels, no output is produced for suppressed imports.

> **REQ-341** | Priority: MUST
>
> **Description:** Inline suppression MUST be always available without requiring a configuration toggle. No configuration field or CLI flag is required to enable or disable the suppression mechanism.
>
> **Rationale:** Per-line suppression is a developer escape hatch, not a behavioral mode. Requiring configuration to enable it would add friction without benefit. This follows the convention established by `# noqa` (flake8) and `# type: ignore` (mypy), neither of which require configuration to recognize their suppression markers.
>
> **Acceptance Criteria:** Given a default configuration with no suppression-related fields set, `# import_check: ignore` comments are recognized and respected. There is no `enable_suppression` or similar configuration key.

---

## 6. CLI Extensions

> **REQ-413** | Priority: SHOULD
>
> **Description:** The CLI SHOULD support a `--no-check-stubs` flag that disables `.pyi` stub file fallback for symbol verification, mapping to `check_stubs=False` in the configuration.
>
> **Rationale:** Developers working on projects without stub files, or who want strict symbol checking without stub fallback, need a quick way to disable the feature from the command line without editing `pyproject.toml`.
>
> **Acceptance Criteria:** `python -m import_check check --no-check-stubs` runs the checker with stub fallback disabled. An import that would pass only via stub file resolution is reported as `SYMBOL_NOT_DEFINED`. `python -m import_check check --help` lists the `--no-check-stubs` flag with a description.

> **REQ-415** | Priority: SHOULD
>
> **Description:** The CLI SHOULD support a `--no-check-getattr` flag that disables `__getattr__`-based symbol suppression, mapping to `check_getattr=False` in the configuration.
>
> **Rationale:** Developers who want strict symbol checking -- treating `__getattr__` modules the same as any other module -- need a way to opt out of the permissive behavior from the command line.
>
> **Acceptance Criteria:** `python -m import_check check --no-check-getattr` runs the checker with `__getattr__` suppression disabled. An import from a module that defines `__getattr__` but does not directly define the symbol is reported as `SYMBOL_NOT_DEFINED`. `python -m import_check check --help` lists the `--no-check-getattr` flag with a description.

---

## 7. Configuration Extensions

> **REQ-511** | Priority: MUST
>
> **Description:** The configuration system MUST support a `check_stubs` field of type `bool` with a default value of `True`. When `True`, the checker falls back to `.pyi` stub files for symbol definition checking. When `False`, stub files are not consulted and only the `.py` source is used for symbol verification.
>
> **Rationale:** Stub file fallback changes the checker's behavior from strict to permissive for stub-declared symbols. Making this configurable allows operators to choose the appropriate strictness level for their project. The default of `True` reflects the common case where stub files are part of the project's API contract.
>
> **Acceptance Criteria:** Given `pyproject.toml` containing `[tool.import_check]` with `check_stubs = false`, the checker does not consult `.pyi` files. Given `check_stubs = true` (or no setting, using the default), the checker consults `.pyi` files as part of the symbol verification fallback chain. Given `check_stubs = "yes"` (wrong type), the system produces a clear validation error at startup.

> **REQ-513** | Priority: MUST
>
> **Description:** The configuration system MUST support a `check_getattr` field of type `bool` with a default value of `True`. When `True`, `__getattr__` presence in a module suppresses `SYMBOL_NOT_DEFINED` errors for imports from that module. When `False`, `__getattr__` presence is ignored and missing symbols are reported strictly.
>
> **Rationale:** `__getattr__` suppression introduces permissive behavior that may not be desired in all contexts. For example, a CI pipeline enforcing strict symbol resolution may want to disable it. Making this configurable allows operators to choose their strictness level. The default of `True` reflects the common case where `__getattr__` modules intentionally provide dynamic attributes.
>
> **Acceptance Criteria:** Given `pyproject.toml` containing `[tool.import_check]` with `check_getattr = false`, the checker reports `SYMBOL_NOT_DEFINED` for symbols not directly defined in a module's `.py` source, even if that module defines `__getattr__`. Given `check_getattr = true` (or no setting, using the default), `__getattr__` presence suppresses `SYMBOL_NOT_DEFINED`. Given `check_getattr = 42` (wrong type), the system produces a clear validation error at startup.

> **REQ-515** | Priority: MUST
>
> **Description:** The new configuration fields (`check_stubs`, `check_getattr`) MUST follow the same precedence rules defined in the parent spec (REQ-505): programmatic API kwargs override CLI flags, which override `pyproject.toml` values, which override built-in defaults.
>
> **Rationale:** Consistency with the existing layered configuration model ensures that developers do not need to learn a different precedence scheme for the new fields. This is an extension of REQ-505, not a new precedence model.
>
> **Acceptance Criteria:** Given `pyproject.toml` sets `check_stubs = false`, a CLI flag `--no-check-stubs` is not passed, and an API kwarg `check_stubs=True` is provided: the API call uses `True`. Given `pyproject.toml` sets `check_getattr = true` and the CLI passes `--no-check-getattr`: the CLI invocation uses `False`.

---

## 8. Non-Functional Requirements

> **REQ-915** | Priority: MUST
>
> **Description:** All three enhancements MUST use only `ast.parse()` and filesystem operations for verification. No enhancement MUST introduce runtime imports, network calls, or execution of target module code.
>
> **Rationale:** This extends the parent spec's zero-cost verification principle (REQ-303) to the new functionality. Relative import resolution, `__getattr__` detection, and stub file parsing are all achievable with AST parsing and path manipulation alone. Introducing runtime behavior would violate the safety guarantee that the checker can run in any environment.
>
> **Acceptance Criteria:** The implementation of all three enhancements uses only `ast`, `pathlib`, and standard string operations. No `importlib.import_module()`, `exec()`, `eval()`, or subprocess calls are used in any new code path.

> **REQ-917** | Priority: MUST
>
> **Description:** The enhancements MUST NOT change the checker's external interface contract. The structured error list format (parent spec Section 8.1) and the result object format (parent spec Section 8.3) MUST remain unchanged. New information (e.g., resolved absolute paths for relative imports) MUST be reflected in the existing fields.
>
> **Rationale:** Downstream consumers (LLM agents, CI pipelines, programmatic callers) depend on the existing error list and result object schemas. Changing these contracts would break existing integrations. Relative imports, once resolved, produce the same error categories (`MODULE_NOT_FOUND`, `SYMBOL_NOT_DEFINED`) as absolute imports and fit naturally into the existing schema.
>
> **Acceptance Criteria:** The JSON output schema after the enhancements contains the same top-level fields and error entry fields as before. A consumer that parses the pre-enhancement JSON output can parse the post-enhancement JSON output without modification. Relative import errors appear with the resolved absolute module path in the `original_module_path` field.

> **REQ-919** | Priority: MUST
>
> **Description:** The checker MUST degrade gracefully when enhancement-specific conditions are unavailable:
>
> | Condition | Degraded Behavior |
> |-----------|-------------------|
> | Relative import resolution fails (file not in a package) | Skip the import, log at DEBUG, no error reported |
> | `check_getattr` disabled via config | `__getattr__` presence is ignored; symbol checking is strict |
> | `check_stubs` disabled via config | `.pyi` files are not consulted; symbol checking uses `.py` only |
> | `.pyi` file exists but fails to parse | Log a warning, skip stub fallback for that module, continue |
>
> The checker MUST NOT crash or return an unhandled error when any enhancement-specific input is unavailable or malformed.
>
> **Rationale:** Each enhancement adds an optional detection capability. When that capability is unavailable (misconfigured, malformed input, missing files), the checker must fall back to its pre-enhancement behavior rather than failing entirely. This extends the parent spec's graceful degradation principle (REQ-911).
>
> **Acceptance Criteria:** Each degraded scenario listed above is tested. The checker produces valid output in all cases. A `.pyi` file with a syntax error causes a WARNING log and the checker continues without stub fallback for that module.

---

## 9. Interface Contracts

### 9.1 Extended Import Extraction Return Type

The import extraction function's return type changes from a 3-tuple to a 4-tuple:

| Field | Type | Description |
|-------|------|-------------|
| `module` | `str` or `None` | Dotted module path (relative or absolute). `None` for bare relative imports (`from . import foo`). |
| `name` | `str` | The symbol name being imported. |
| `lineno` | `int` | 1-based line number of the import statement. |
| `level` | `int` | Import level: 0 for absolute, >0 for relative (number of dots). |

### 9.2 Configuration Surface

| Field | Type | Default | Description | Config Sources |
|-------|------|---------|-------------|----------------|
| `check_stubs` | `bool` | `True` | Enable `.pyi` stub fallback for symbol checking | pyproject.toml, CLI (`--no-check-stubs`), API kwarg |
| `check_getattr` | `bool` | `True` | Enable `__getattr__` suppression for `SYMBOL_NOT_DEFINED` | pyproject.toml, CLI (`--no-check-getattr`), API kwarg |

These fields extend the `ImportCheckConfig` dataclass defined in the parent spec (REQ-503).

### 9.3 Suppression Comment Contract

| Property | Value |
|----------|-------|
| Marker string | `# import_check: ignore` |
| Scope | All imports on the same source line |
| Position | Anywhere on the line (not required to be at the end) |
| Interaction with other comments | Independent. Other comments on the same line (e.g., `# noqa`) do not affect suppression. |
| Configuration | Always enabled. No toggle required. |
| Logging | DEBUG level: file path, line number, suppressed import text |

---

## 10. Error Taxonomy Extension

This extends the parent spec's error taxonomy (Section 9).

| Category | Examples | Severity | Expected Behavior |
|----------|----------|----------|-------------------|
| Unresolvable relative import | `from .foo import bar` in a file not inside any package | Informational | Skip import, log at DEBUG. Not included in error list. |
| Stub parse error | `src/foo.pyi` contains a syntax error | Recoverable | Log warning, skip stub fallback for that module, continue checking |
| Suppressed import | `from src.native import func  # import_check: ignore` | Informational | Skip verification, log at DEBUG. Not included in error list. |

---

## 11. System-Level Acceptance Criteria

These extend the parent spec's system-level acceptance criteria (Section 11).

| Criterion | Threshold | Related Requirements |
|-----------|-----------|---------------------|
| Relative import coverage | All relative imports in files within standard packages (directories with `__init__.py`) are resolved and verified | REQ-313, REQ-315, REQ-317, REQ-319, REQ-321 |
| False positive reduction | Imports from modules defining `__getattr__` do not produce `SYMBOL_NOT_DEFINED` when `check_getattr` is enabled | REQ-323, REQ-325, REQ-327 |
| Stub file coverage | Symbols declared in co-located `.pyi` stubs are recognized when `check_stubs` is enabled | REQ-329, REQ-331 |
| Suppression correctness | Lines with `# import_check: ignore` are excluded from verification and logged at DEBUG | REQ-335, REQ-337, REQ-339 |
| Output contract stability | JSON output schema is unchanged; existing consumers parse post-enhancement output without modification | REQ-917 |
| Graceful degradation | All degraded scenarios (unresolvable relative imports, disabled config, malformed stubs) produce valid output without crashes | REQ-919 |

---

## 12. Requirements Traceability Matrix

| REQ ID | Section | Priority | Component |
|--------|---------|----------|-----------|
| REQ-313 | 3 | MUST | Relative Import Resolution |
| REQ-315 | 3 | MUST | Relative Import Resolution |
| REQ-317 | 3 | MUST | Relative Import Resolution |
| REQ-319 | 3 | MUST | Relative Import Resolution |
| REQ-321 | 3 | SHOULD | Relative Import Resolution |
| REQ-323 | 4 | MUST | Runtime Symbol Suppression |
| REQ-325 | 4 | MUST | Runtime Symbol Suppression |
| REQ-327 | 4 | MUST | Runtime Symbol Suppression |
| REQ-329 | 4 | MUST | Runtime Symbol Suppression |
| REQ-331 | 4 | MUST | Runtime Symbol Suppression |
| REQ-333 | 4 | SHOULD | Runtime Symbol Suppression |
| REQ-335 | 5 | MUST | Inline Suppression Comments |
| REQ-337 | 5 | MUST | Inline Suppression Comments |
| REQ-339 | 5 | MUST | Inline Suppression Comments |
| REQ-341 | 5 | MUST | Inline Suppression Comments |
| REQ-413 | 6 | SHOULD | CLI Extensions |
| REQ-415 | 6 | SHOULD | CLI Extensions |
| REQ-511 | 7 | MUST | Configuration Extensions |
| REQ-513 | 7 | MUST | Configuration Extensions |
| REQ-515 | 7 | MUST | Configuration Extensions |
| REQ-915 | 8 | MUST | Non-Functional (Zero-Cost) |
| REQ-917 | 8 | MUST | Non-Functional (Interface Stability) |
| REQ-919 | 8 | MUST | Non-Functional (Graceful Degradation) |

**Total New Requirements: 23**
- MUST: 19
- SHOULD: 4
- MAY: 0

**Combined with Parent Spec (39 existing): 62 total requirements**
- MUST: 50
- SHOULD: 11
- MAY: 1

---

## Appendix A. Additional Glossary

These terms supplement the parent spec's Glossary (Appendix A).

| Term | Definition |
|------|-----------|
| **PEP 484** | Python Enhancement Proposal defining type hints for Python, including the `.pyi` stub file convention. |
| **AnnAssign** | An AST node type representing an annotated assignment (`name: Type` or `name: Type = value`). Common in stub files. |
| **Namespace package** | A Python package without an `__init__.py` file (PEP 420). Not supported by the relative import resolution enhancement. |
| **Fallback chain** | An ordered sequence of checks where each subsequent check runs only if the preceding check did not find the symbol. |

---

## Appendix B. Document References

| Document | Purpose |
|----------|---------|
| Parent Spec: `docs/import_check/IMPORT_CHECK_SPEC.md` | The base specification that this document extends. All existing requirements remain in effect. |
| Design Sketch: `docs/superpowers/specs/2026-03-29-import-check-enhancements-sketch.md` | Brainstorming artifact that informed this specification. Contains approach selection rationale, implementation detail choices, and risk assessment. |
| CLAUDE.md (project root) | Project conventions for code structure, testing, configuration, and documentation. |

---

## Appendix C. Open Questions

None. All design decisions were resolved during the brainstorming phase as documented in the design sketch.
