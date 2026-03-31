# Import Check Tool Specification

**RAG Project — Developer Tooling**
Version: 1.0 | Status: Draft | Domain: Python Import Analysis & Repair

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-28 | Autonomous Pipeline | Initial draft |

---

## 1. Scope & Definitions

### 1.1 Problem Statement

After code refactoring -- moving functions between files, renaming modules, splitting or merging files -- Python import statements throughout the codebase break. Developers must manually track down every broken `import` and `from ... import` statement, every `mock.patch()` string path, every `importlib.import_module()` call, and every `__all__` list that references the moved symbols. This is tedious, error-prone, and scales poorly with codebase size.

Existing approaches fall short:

- **IDE refactoring tools** (e.g., rope, PyCharm) are designed for proactive refactoring -- they move the symbol and update references in the same operation. They cannot retroactively fix imports after a manual or autonomous refactoring has already occurred.
- **Static type checkers** (mypy, pyright) detect broken imports but do not fix them.
- **Manual grep-and-replace** misses string-based references, conditional imports, and `TYPE_CHECKING` blocks.

The import_check tool solves this by analyzing git history to determine what moved where, then deterministically rewriting all import statements to reflect the new locations.

### 1.2 Scope

This specification defines the requirements for the **import_check** tool. The boundary is:

- **Entry point:** Developer invokes the tool after completing a refactoring operation (via CLI command `python -m import_check [fix|check|run]` or programmatic API call).
- **Exit point:** The tool has either (a) rewritten all fixable broken imports in-place and reported results, or (b) produced a structured error list of unfixable residual issues for downstream consumption.

Everything between these two points is in scope.

### 1.3 Terminology

| Term | Definition |
|------|-----------|
| **Symbol** | A named Python entity (function, class, or module-level variable) defined in a source file. |
| **Symbol inventory** | A mapping of every symbol name to its defining module path, built by parsing Python source files with `ast`. |
| **Migration map** | A data structure produced by diffing the "before" and "after" symbol inventories, recording which symbols moved, were renamed, split, or merged. |
| **Smoke test** | A lightweight verification pass that checks whether each import statement in the codebase resolves to an existing file and symbol, using only `ast.parse()` and filesystem checks -- no runtime imports. |
| **Encapsulation violation** | An import that bypasses a package's `__init__.py` public API to import directly from an internal module. |
| **Deterministic fix** | An import rewrite that can be computed without LLM assistance, using only the migration map and syntactic analysis. |
| **Residual error** | A broken import that the deterministic fixer cannot resolve (e.g., a symbol that was both renamed and moved simultaneously). |
| **Before state** | The symbol inventory constructed from the git ref (default: HEAD) representing the codebase before refactoring. |
| **After state** | The symbol inventory constructed from the current working tree. |

### 1.4 Requirement Priority Levels

This document uses RFC 2119 language:

- **MUST** — Absolute requirement. The system is non-conformant without it.
- **SHOULD** — Recommended. May be omitted only with documented justification.
- **MAY** — Optional. Included at the implementor's discretion.

### 1.5 Requirement Format

Each requirement follows this structure:

> **REQ-xxx** | Priority: MUST/SHOULD/MAY
> **Description:** What the system shall do.
> **Rationale:** Why this requirement exists.
> **Acceptance Criteria:** How to verify conformance.

Requirements use the REQ-xxx prefix throughout. They are grouped by section with the following ID ranges:

| Section | ID Range | Component |
|---------|----------|-----------|
| Section 3 | REQ-1xx | Symbol Inventory & Diffing |
| Section 4 | REQ-2xx | Deterministic Fixer |
| Section 5 | REQ-3xx | Smoke Test Checker |
| Section 6 | REQ-4xx | Public API & CLI |
| Section 7 | REQ-5xx | Configuration |
| Section 10 | REQ-9xx | Non-Functional Requirements |

### 1.6 Assumptions & Constraints

| ID | Assumption / Constraint | Impact if Violated |
|----|------------------------|--------------------|
| A-1 | Python 3.10+ runtime available | Type union syntax and match statements may not parse correctly on older versions |
| A-2 | Git is installed and the target project is a git repository | The "before" state cannot be constructed without git history |
| A-3 | The `libcst` package is available in the tool's environment | Import rewriting cannot preserve formatting without libcst |
| A-4 | The target codebase uses standard Python import conventions | Non-standard import mechanisms (import hooks, custom finders) are not detected |
| A-5 | The git ref used for "before" state contains a valid, parseable codebase | Corrupted or non-Python files at the git ref will cause inventory construction to skip those files |

### 1.7 Design Principles

| Principle | Description |
|-----------|-------------|
| **Deterministic-first** | Deterministic AST-based analysis and rewriting handles the vast majority of cases. The LLM is a safety net for residual errors, not the primary fix mechanism. This minimizes cost, latency, and non-determinism. |
| **Zero-cost verification** | The smoke test uses only `ast.parse()` and filesystem checks. It never loads Python modules at runtime, avoiding side effects from heavy dependencies (e.g., torch, tensorflow). |
| **Generic portability** | The tool makes no project-specific assumptions. It works on any Python project with git, requiring no project-specific configuration to produce useful results. |
| **Report-only diagnostics** | Some issues (encapsulation violations, truly dynamic string construction) are detected and reported but not auto-fixed. The tool clearly distinguishes actionable fixes from advisory diagnostics. |
| **Config-driven behavior** | All behavioral parameters are externalized to configuration. No stage behavior is hardcoded. |

### 1.8 Out of Scope

**Out of scope -- this spec:**

- LLM execution logic for Step 3 residual fixes. This spec defines the structured error output format that the LLM consumes; the LLM skill/agent that processes those errors is specified separately.
- Installation, packaging, and distribution of the tool (pip, conda, etc.).

**Out of scope -- this project:**

- Truly dynamic string construction (e.g., `f"src.{runtime_var}"`) -- these are flagged in output but not fixed.
- Proactive refactoring (moving symbols to new locations). Use IDE/rope for that.
- Non-Python configuration files that reference Python module paths (YAML, JSON, TOML pipelines).
- Cross-repository imports.
- Runtime import hook analysis or custom finder/loader mechanisms.

---

## 2. System Overview

### 2.1 Architecture Diagram

```
Developer invokes: python -m import_check [fix|check|run]
    │
    ▼
┌──────────────────────────────────────────────────────┐
│ [1] SYMBOL INVENTORY & DIFFING                       │
│     inventory.py: Build "before" inventory from      │
│       git ref, "after" from working tree (ast)       │
│     differ.py: Diff inventories to produce           │
│       migration map (moves, renames, splits, merges) │
└──────────────────────┬───────────────────────────────┘
                       │ migration map
                       ▼
┌──────────────────────────────────────────────────────┐
│ [2] DETERMINISTIC FIXER                              │
│     fixer.py: Rewrite imports in-place using         │
│       libcst based on migration map. Handles all     │
│       import styles + string refs + __all__          │
└──────────────────────┬───────────────────────────────┘
                       │ rewritten files
                       ▼
┌──────────────────────────────────────────────────────┐
│ [3] SMOKE TEST CHECKER                               │
│     checker.py: Verify every import resolves         │
│       (ast.parse + filesystem). Report encapsulation │
│       violations. Output structured error list.      │
└──────────────────────┬───────────────────────────────┘
                       │ structured error list (if any)
                       ▼
┌──────────────────────────────────────────────────────┐
│ [4] OUTPUT                                           │
│     Human-readable summary or JSON report.           │
│     Residual errors formatted for LLM consumption.   │
└──────────────────────────────────────────────────────┘
```

### 2.2 Data Flow Summary

| Stage | Input | Output |
|-------|-------|--------|
| Symbol Inventory & Diffing | Git ref (before state), current working tree (after state), list of changed files from `git diff --name-only` | Migration map: symbol-to-new-location mappings for moves, renames, splits, merges |
| Deterministic Fixer | Migration map, all Python files in configured source directories | Rewritten Python files with updated imports (in-place) |
| Smoke Test Checker | All Python files in configured source directories | Structured error list (broken imports, encapsulation violations), pass/fail status |
| Output | Error list, fix summary statistics | Human-readable report or JSON-formatted report |

---

## 3. Symbol Inventory & Diffing

> **REQ-101** | Priority: MUST
>
> **Description:** The system MUST build a symbol inventory from Python source files by parsing them with `ast`, extracting all `FunctionDef`, `ClassDef`, and module-level `Assign` names along with their fully-qualified module paths.
>
> **Rationale:** The symbol inventory is the foundational data structure. Without symbol-level granularity, the tool cannot distinguish between a function move and a file rename, and cannot handle splits or merges where individual symbols move to different destinations.
>
> **Acceptance Criteria:** Given a file `src/foo/bar.py` containing `class MyClass:` and `def helper():`, the inventory contains entries mapping `MyClass` to `src.foo.bar` and `helper` to `src.foo.bar`. Given a file with no public symbols (only `_private` names), those private symbols are still inventoried.

> **REQ-103** | Priority: MUST
>
> **Description:** The system MUST construct the "before" inventory by reading file contents from the configured git ref (default: `HEAD`) using `git show <ref>:<path>` for each file that appears in the git diff.
>
> **Rationale:** The "before" state must reflect the codebase prior to refactoring. Using git history rather than a cached state file ensures correctness without requiring users to pre-register state before refactoring.
>
> **Acceptance Criteria:** Given a file `src/utils.py` that was modified in the working tree, the "before" inventory reflects the version at `HEAD` (or the configured git ref). Given a file that was deleted in the working tree, the "before" inventory still contains its symbols. Given a newly created file, it does not appear in the "before" inventory.

> **REQ-105** | Priority: MUST
>
> **Description:** The system MUST construct the "after" inventory by parsing current working-tree files in the configured source directories.
>
> **Rationale:** The "after" state represents the post-refactoring codebase. Scanning current files ensures the inventory reflects the developer's intended final layout.
>
> **Acceptance Criteria:** Given a new file `src/foo/new_module.py` with a function `moved_func`, the "after" inventory maps `moved_func` to `src.foo.new_module`. Given a file excluded by the exclude patterns configuration, it does not appear in the "after" inventory.

> **REQ-107** | Priority: MUST
>
> **Description:** The system MUST scope inventory construction to only files reported as changed by `git diff --name-only` against the configured git ref, plus any new (untracked) Python files in the configured source directories.
>
> **Rationale:** Scanning the entire codebase on every run wastes time. Since only changed files can introduce broken imports, scoping to the diff set keeps performance proportional to the size of the refactoring, not the size of the codebase.
>
> **Acceptance Criteria:** Given a repository with 500 Python files where 3 files changed, inventory construction processes only those 3 files (plus any new files). Given a new untracked file in a configured source directory, it is included in the "after" inventory.

> **REQ-109** | Priority: MUST
>
> **Description:** The system MUST produce a migration map by diffing the "before" and "after" inventories, detecting the following refactoring patterns: moves (same symbol name, different module path), renames (different symbol name, same enclosing area), splits (symbols from one source file distributed across multiple destination files), and merges (symbols from multiple source files consolidated into one destination file).
>
> **Rationale:** Each refactoring pattern requires a different import-rewriting strategy. Without explicit pattern detection, the fixer cannot determine whether to update the module path, the symbol name, or both.
>
> **Acceptance Criteria:** Given `func_a` moved from `src.old` to `src.new`, the migration map contains a "move" entry mapping `src.old.func_a` to `src.new.func_a`. Given `src/big.py` split into `src/part_a.py` and `src/part_b.py` with symbols distributed between them, the migration map contains individual move entries for each symbol to its correct destination. Given `src/a.py` and `src/b.py` merged into `src/combined.py`, the migration map contains move entries for each symbol.

> **REQ-111** | Priority: SHOULD
>
> **Description:** The system SHOULD handle files that fail to parse (syntax errors) gracefully by logging a warning and excluding them from the inventory, rather than aborting the entire inventory construction.
>
> **Rationale:** A single syntax-error file should not prevent the tool from fixing imports across the rest of the codebase. Partial results are more useful than no results.
>
> **Acceptance Criteria:** Given a file `src/broken.py` with a syntax error, the system logs a warning identifying the file and the parse error, and continues building the inventory from all other files. The final report indicates that one file was skipped.

---

## 4. Deterministic Fixer

> **REQ-201** | Priority: MUST
>
> **Description:** The system MUST rewrite `from X import Y` statements where `Y` has moved to a different module according to the migration map, updating `X` to the new module path while preserving `Y` (or updating `Y` if it was renamed).
>
> **Rationale:** `from ... import` is the most common Python import style. Failing to rewrite these statements would leave the majority of broken imports unresolved.
>
> **Acceptance Criteria:** Given `from src.old import func_a` and a migration map entry moving `func_a` from `src.old` to `src.new`, the system rewrites the statement to `from src.new import func_a`. Given a migration map entry renaming `func_a` to `func_b` in the same module, the system rewrites `from src.mod import func_a` to `from src.mod import func_b`.

> **REQ-203** | Priority: MUST
>
> **Description:** The system MUST rewrite `import X` statements where module `X` has been moved or renamed according to the migration map.
>
> **Rationale:** Absolute imports (`import X`) are used for module-level access patterns (e.g., `X.func()`). These must be updated when the module itself is moved.
>
> **Acceptance Criteria:** Given `import src.old.utils` and a migration map indicating `src.old.utils` was moved to `src.new.helpers`, the system rewrites the statement to `import src.new.helpers`.

> **REQ-205** | Priority: MUST
>
> **Description:** The system MUST preserve import aliases when rewriting. If the original import uses `as`, the alias MUST be retained in the rewritten import.
>
> **Rationale:** Aliases propagate throughout the consuming file. Removing an alias during rewriting would break all downstream references to that alias within the file.
>
> **Acceptance Criteria:** Given `from src.old import func_a as fa` and a migration map moving `func_a` to `src.new`, the system rewrites to `from src.new import func_a as fa`. The alias `fa` is unchanged.

> **REQ-207** | Priority: MUST
>
> **Description:** The system MUST detect and rewrite import statements that appear inside function bodies (lazy imports), inside `if TYPE_CHECKING:` blocks, and inside `try/except` conditional import blocks.
>
> **Rationale:** Lazy imports, TYPE_CHECKING imports, and conditional imports are common Python patterns. A tool that only rewrites top-level imports would leave a significant class of breakages unresolved.
>
> **Acceptance Criteria:** Given a lazy import `from src.old import MyClass` inside a function body, the system rewrites it. Given an import inside `if TYPE_CHECKING:`, the system rewrites it. Given an import inside a `try` block with an `except ImportError` fallback, the system rewrites the `try` branch.

> **REQ-209** | Priority: MUST
>
> **Description:** The system MUST update `__all__` list entries when the symbols they reference have been renamed according to the migration map.
>
> **Rationale:** `__all__` controls the public API surface of a module. Stale entries in `__all__` cause `ImportError` when consumers use `from module import *` or when documentation generators enumerate public symbols.
>
> **Acceptance Criteria:** Given `__all__ = ["func_a", "ClassB"]` and a migration map renaming `func_a` to `func_alpha`, the system rewrites the list to `__all__ = ["func_alpha", "ClassB"]`.

> **REQ-211** | Priority: MUST
>
> **Description:** The system MUST detect and rewrite string literal arguments to `mock.patch()` and `importlib.import_module()` that reference module paths present in the migration map.
>
> **Rationale:** `mock.patch("src.old.MyClass")` and `importlib.import_module("src.old.utils")` are string-based references that static analysis tools typically miss. These are common sources of runtime failures after refactoring.
>
> **Acceptance Criteria:** Given `mock.patch("src.old.module.MyClass")` and a migration map moving `MyClass` from `src.old.module` to `src.new.module`, the system rewrites the string to `"src.new.module.MyClass"`. Given `importlib.import_module("src.old.utils")` and a move of `src.old.utils` to `src.new.helpers`, the system rewrites to `importlib.import_module("src.new.helpers")`.

> **REQ-213** | Priority: MUST
>
> **Description:** The system MUST handle simple dataflow for variable-held string paths, bounded to single-assignment string literals within the same function scope. When a variable is assigned a string literal and then passed to `importlib.import_module()` or `mock.patch()` within the same function, the system MUST rewrite the string literal at the assignment site.
>
> **Rationale:** Developers sometimes store module paths in local variables for readability. Handling this common single-assignment pattern increases fix coverage without introducing complex cross-scope dataflow analysis.
>
> **Acceptance Criteria:** Given `path = "src.old.module"; importlib.import_module(path)` in the same function body, and a migration map entry for `src.old.module`, the system rewrites to `path = "src.new.module"`. Given a variable assigned in one function and used in another, the system does NOT attempt to rewrite it (out of scope).

> **REQ-215** | Priority: MUST
>
> **Description:** The system MUST use a formatting-preserving rewriter (libcst) for all source file modifications, ensuring that whitespace, comments, trailing commas, and other non-semantic formatting are not altered outside the rewritten import nodes.
>
> **Rationale:** Gratuitous formatting changes create noisy diffs that obscure the meaningful import fixes, making code review difficult and increasing the risk of merge conflicts.
>
> **Acceptance Criteria:** Given a file with specific indentation, trailing comments on import lines, and blank lines between import groups, the system modifies only the import path/name tokens. A diff of the rewritten file shows changes only to the import module paths and symbol names, not to surrounding formatting.

> **REQ-217** | Priority: SHOULD
>
> **Description:** The system SHOULD flag string-based references that use dynamic string construction (e.g., f-strings, string concatenation with variables) as "unfixable" in the output report, without attempting to rewrite them.
>
> **Rationale:** Dynamic string paths cannot be resolved statically. Attempting to rewrite them risks introducing incorrect module paths. Flagging them alerts the developer to manually review these locations.
>
> **Acceptance Criteria:** Given `importlib.import_module(f"src.{name}.module")`, the system includes this location in the output report with a category indicating it is a dynamic string reference that requires manual review. The system does not modify the string.

---

## 5. Smoke Test Checker

> **REQ-301** | Priority: MUST
>
> **Description:** The system MUST verify every import statement in every Python file within the configured source directories by checking that (a) the target module path resolves to an existing file on the filesystem, and (b) the imported symbol name is defined in that target file.
>
> **Rationale:** The smoke test is the verification gate that catches any imports the deterministic fixer missed or introduced incorrectly. Without this gate, the tool cannot guarantee that its fixes are correct.
>
> **Acceptance Criteria:** Given `from src.foo import bar` where `src/foo.py` exists and defines `bar`, the check passes. Given `from src.foo import bar` where `src/foo.py` exists but does not define `bar`, the check fails and reports a "symbol not found" error. Given `from src.nonexistent import bar` where `src/nonexistent.py` does not exist, the check fails and reports a "module not found" error.

> **REQ-303** | Priority: MUST
>
> **Description:** The system MUST perform verification using only `ast.parse()` and filesystem path resolution. The system MUST NOT use `importlib.import_module()` or any mechanism that executes the target module's code.
>
> **Rationale:** Runtime imports can trigger side effects (database connections, GPU initialization, network calls) and may require dependencies not available in the tool's environment. The zero-cost verification principle requires that checking is safe to run in any environment.
>
> **Acceptance Criteria:** Given a file that imports `torch`, the verification check completes without loading the `torch` package. The check determines whether `torch` is resolvable by filesystem path and AST parsing alone.

> **REQ-305** | Priority: MUST
>
> **Description:** The system MUST detect encapsulation violations -- imports that bypass a package's `__init__.py` to import directly from an internal module -- and report them as advisory diagnostics separate from broken-import errors.
>
> **Rationale:** Encapsulation violations are code quality issues, not broken imports. Mixing them with broken-import errors would confuse the developer and the downstream LLM consumer. Separating them allows developers to address them at their discretion.
>
> **Acceptance Criteria:** Given `from src.foo.internal_module import helper` where `src/foo/__init__.py` exists and does not re-export `helper`, the system reports this as an encapsulation violation in a separate diagnostic section. The violation is NOT included in the broken-import error list. Given `from src.foo import helper` where `src/foo/__init__.py` re-exports `helper`, no violation is reported.

> **REQ-307** | Priority: MUST
>
> **Description:** The system MUST NOT auto-fix encapsulation violations. They MUST appear only as report-only diagnostics in the output.
>
> **Rationale:** Encapsulation violations may be intentional (performance, circular import avoidance). Auto-fixing them risks breaking working code. The report-only design principle requires these to be flagged for human judgment.
>
> **Acceptance Criteria:** After a full `run()` execution, no encapsulation violations have been modified in the source files. The output report contains encapsulation violations in a clearly labeled advisory section.

> **REQ-309** | Priority: MUST
>
> **Description:** The system MUST produce a structured error list for all broken imports that remain after the deterministic fix. Each error entry MUST include: the file path, line number, the broken import statement, the error category (module not found, symbol not found, dynamic reference), and the original module path.
>
> **Rationale:** The structured error list is the interface contract between the tool and the downstream LLM fix step. Without structured, machine-parseable errors, the LLM cannot efficiently process residual issues.
>
> **Acceptance Criteria:** Given two residual broken imports after the deterministic fix, the error list contains exactly two entries. Each entry includes all five specified fields. The error list is serializable to JSON format.

> **REQ-311** | Priority: SHOULD
>
> **Description:** The system SHOULD report the total count of imports checked, the count of imports that passed, the count of broken imports found, and the count of encapsulation violations detected, as summary statistics in the output.
>
> **Rationale:** Summary statistics give the developer a quick assessment of codebase health and the tool's fix coverage, without requiring them to read through every individual result.
>
> **Acceptance Criteria:** After a check run, the output includes a summary line (or JSON object) with fields: `total_checked`, `passed`, `broken`, `encapsulation_violations`.

---

## 6. Public API & CLI

> **REQ-401** | Priority: MUST
>
> **Description:** The system MUST expose three public functions as the programmatic API: `fix()` (runs inventory, diff, and deterministic fixer), `check()` (runs smoke test checker), and `run()` (runs fix followed by check).
>
> **Rationale:** Separating fix and check into independent operations allows callers to use them independently. `fix()` alone is useful when the developer wants to apply fixes without verification. `check()` alone is useful as a CI gate.
>
> **Acceptance Criteria:** Calling `import_check.fix()` executes the inventory, diff, and fixer stages without running the checker. Calling `import_check.check()` runs only the smoke test. Calling `import_check.run()` runs fix followed by check.

> **REQ-403** | Priority: MUST
>
> **Description:** The system MUST provide a CLI entry point invocable as `python -m import_check [fix|check|run]`, where the subcommand selects which pipeline stages to execute. When no subcommand is provided, the default MUST be `run`.
>
> **Rationale:** The CLI is the primary interface for interactive developer use. The `python -m` convention is the standard Python approach for runnable packages, requiring no installation step beyond having the package on the Python path.
>
> **Acceptance Criteria:** `python -m import_check fix` executes only the fix stages. `python -m import_check check` executes only the check stage. `python -m import_check run` executes fix then check. `python -m import_check` (no subcommand) executes fix then check.

> **REQ-405** | Priority: MUST
>
> **Description:** The system MUST support two output formats: `human` (human-readable text) and `json` (machine-parseable JSON). The output format MUST be selectable via configuration.
>
> **Rationale:** Human format is for interactive developer use. JSON format is for CI pipelines, downstream LLM consumers, and programmatic integration.
>
> **Acceptance Criteria:** With `output_format="human"`, the output is a human-readable text report listing fixes applied, broken imports remaining, and encapsulation violations. With `output_format="json"`, the output is valid JSON containing the same information in a structured format. The JSON output can be parsed by `json.loads()` without error.

> **REQ-407** | Priority: MUST
>
> **Description:** The programmatic API MUST accept configuration as keyword arguments that override all other configuration sources (pyproject.toml and CLI flags).
>
> **Rationale:** Programmatic callers need full control over behavior without depending on file-based or CLI-based configuration. This enables embedding import_check in larger automated workflows.
>
> **Acceptance Criteria:** Calling `import_check.fix(source_dirs=["lib"], git_ref="HEAD~2")` uses `["lib"]` as source directories and `HEAD~2` as the git ref, regardless of what pyproject.toml or CLI flags specify.

> **REQ-409** | Priority: MUST
>
> **Description:** The system MUST return a structured result object from the programmatic API containing: the list of files modified, the list of fixes applied (with before/after for each), the structured error list from the checker, and encapsulation violations.
>
> **Rationale:** Programmatic callers need machine-readable results to make decisions (e.g., fail a CI build, trigger an LLM fix step, generate a report).
>
> **Acceptance Criteria:** The return value of `run()` is a typed object (dataclass or TypedDict) with fields: `files_modified: list[str]`, `fixes_applied: list[FixEntry]`, `errors: list[ErrorEntry]`, `encapsulation_violations: list[ViolationEntry]`. Each list is empty (not None) when there are no items.

> **REQ-411** | Priority: SHOULD
>
> **Description:** The system SHOULD exit with return code 0 when all imports pass the smoke test, and return code 1 when broken imports remain after the fix stage.
>
> **Rationale:** Standard exit codes enable integration with CI/CD pipelines, shell scripts, and make targets. A non-zero exit code on failure is the Unix convention for indicating that a tool detected problems.
>
> **Acceptance Criteria:** After `python -m import_check run` completes with no remaining broken imports, `echo $?` returns 0. After a run with one or more remaining broken imports, `echo $?` returns 1. Encapsulation violations (report-only) do NOT cause a non-zero exit code.

---

## 7. Configuration

> **REQ-501** | Priority: MUST
>
> **Description:** The system MUST read configuration from `pyproject.toml` under the `[tool.import_check]` section when present, using it as the base configuration layer.
>
> **Rationale:** `pyproject.toml` is the standard Python project configuration file. Storing import_check configuration there keeps it co-located with other project tooling (black, ruff, mypy) and version-controlled with the project.
>
> **Acceptance Criteria:** Given a `pyproject.toml` containing `[tool.import_check]` with `source_dirs = ["lib"]`, calling `import_check.check()` without overrides scans only the `lib` directory.

> **REQ-503** | Priority: MUST
>
> **Description:** The system MUST support the following configuration keys with the specified types and defaults:
>
> | Key | Type | Default | Description |
> |-----|------|---------|-------------|
> | `source_dirs` | `list[str]` | `["src", "server", "config"]` | Directories to scan for Python files |
> | `exclude_patterns` | `list[str]` | `[".venv", "__pycache__", "node_modules"]` | Glob patterns to exclude from scanning |
> | `git_ref` | `str` | `"HEAD"` | Git ref for the "before" state |
> | `encapsulation_check` | `bool` | `true` | Enable or disable encapsulation violation reporting |
> | `output_format` | `str` | `"human"` | Output format: `"human"` or `"json"` |
> | `log_level` | `str` | `"INFO"` | Logging verbosity: `"DEBUG"`, `"INFO"`, `"ERROR"` |
>
> **Rationale:** Typed, defaulted configuration keys ensure the tool works out-of-the-box on typical Python projects while allowing customization for non-standard layouts.
>
> **Acceptance Criteria:** Running the tool with no configuration file and no CLI flags uses all listed default values. Each key accepts values of the specified type. Providing a value of the wrong type (e.g., `source_dirs = "src"` instead of a list) produces a clear validation error.

> **REQ-505** | Priority: MUST
>
> **Description:** The system MUST enforce the following configuration precedence (highest to lowest): programmatic API kwargs, CLI flags, `pyproject.toml` values, built-in defaults.
>
> **Rationale:** The layered precedence model lets developers set project-wide defaults in pyproject.toml, override them for specific CI runs via CLI flags, and override everything when calling the API programmatically.
>
> **Acceptance Criteria:** Given `pyproject.toml` sets `git_ref = "main"`, a CLI flag `--git-ref HEAD~1`, and an API kwarg `git_ref="abc123"`: the API call uses `"abc123"`, a CLI invocation with the flag uses `"HEAD~1"`, and a CLI invocation without the flag uses `"main"`.

> **REQ-507** | Priority: MUST
>
> **Description:** The system MUST validate configuration values at startup and fail fast with a clear error message when invalid values are detected. Invalid values include: non-existent source directories, unrecognized output format values, unrecognized log level values, and invalid git refs that do not resolve.
>
> **Rationale:** Fail-fast validation prevents the tool from partially executing with bad configuration and producing misleading results. Clear error messages reduce debugging time.
>
> **Acceptance Criteria:** Given `output_format = "xml"`, the system exits with an error message stating that `"xml"` is not a valid output format and listing the valid options. Given `source_dirs = ["nonexistent_dir"]`, the system exits with an error message identifying the missing directory. Given `git_ref = "invalid_ref_abc"`, the system exits with an error message stating the ref could not be resolved.

> **REQ-509** | Priority: SHOULD
>
> **Description:** The system SHOULD support CLI flag equivalents for all configuration keys, using `--kebab-case` naming convention (e.g., `--source-dirs`, `--exclude-patterns`, `--git-ref`, `--encapsulation-check`, `--output-format`, `--log-level`).
>
> **Rationale:** CLI flags enable one-off overrides without modifying pyproject.toml, which is useful for CI pipelines and quick testing.
>
> **Acceptance Criteria:** `python -m import_check run --source-dirs src lib --git-ref HEAD~2 --output-format json` executes with the specified overrides. `python -m import_check run --help` lists all available flags with descriptions and defaults.

---

## 8. Interface Contracts

### 8.1 Structured Error List -- Outbound

The structured error list is the output contract between the smoke test checker and any downstream consumer (LLM agent, CI pipeline, human developer).

| Field | Type | Description |
|-------|------|-------------|
| `file_path` | `str` | Absolute or project-relative path to the file containing the broken import |
| `line_number` | `int` | Line number of the broken import statement |
| `import_statement` | `str` | The full text of the broken import statement |
| `error_category` | `str` | One of: `"module_not_found"`, `"symbol_not_found"`, `"dynamic_reference"` |
| `original_module_path` | `str` | The module path that the import was attempting to resolve |

### 8.2 Migration Map -- Internal

The migration map is the internal contract between the differ and the fixer.

| Field | Type | Description |
|-------|------|-------------|
| `old_path` | `str` | Fully-qualified module path before refactoring |
| `new_path` | `str` | Fully-qualified module path after refactoring |
| `symbol_name` | `str` | Name of the symbol (function, class, variable) |
| `new_symbol_name` | `str` or `null` | New name if renamed; null if only moved |
| `pattern` | `str` | One of: `"move"`, `"rename"`, `"split"`, `"merge"` |

### 8.3 Result Object -- Outbound (API)

| Field | Type | Description |
|-------|------|-------------|
| `files_modified` | `list[str]` | Paths to files that were rewritten |
| `fixes_applied` | `list[FixEntry]` | Each entry: file, line, before import, after import |
| `errors` | `list[ErrorEntry]` | Structured error list from the checker |
| `encapsulation_violations` | `list[ViolationEntry]` | Advisory diagnostics for encapsulation bypasses |

---

## 9. Error Taxonomy

| Category | Examples | Severity | Expected Behavior |
|----------|----------|----------|-------------------|
| Parse error | Syntax error in a Python source file | Recoverable | Log warning, skip file, continue processing remaining files |
| Git error | Invalid git ref, git not installed, not a git repository | Non-recoverable | Fail fast with clear error message identifying the issue |
| Config error | Invalid output format, missing source directory, wrong type | Non-recoverable | Fail fast with clear error message and valid options |
| Module not found | Import references a module path that does not exist as a file | Diagnostic | Report in structured error list; do not abort |
| Symbol not found | Import references a symbol not defined in the target module | Diagnostic | Report in structured error list; do not abort |
| Dynamic reference | String-based module path uses dynamic construction (f-string, concatenation) | Advisory | Flag in output report as requiring manual review; do not modify |
| Encapsulation violation | Import bypasses `__init__.py` to access internal module directly | Advisory | Report in separate diagnostic section; do not modify |

---

## 10. Non-Functional Requirements

> **REQ-901** | Priority: SHOULD
>
> **Description:** The system SHOULD complete a full `run()` (fix + check) on a codebase of up to 1,000 Python files in under 30 seconds, excluding any LLM calls.
>
> **Rationale:** The tool is intended for interactive developer use after refactoring. Latency beyond 30 seconds discourages adoption. The deterministic-first principle ensures that the vast majority of work is zero-token AST processing, making this target achievable.
>
> **Acceptance Criteria:** On a codebase with 1,000 Python files and 50 changed files, `run()` completes in under 30 seconds on a machine with a standard SSD and 8GB RAM. The time measurement excludes any optional LLM processing.

> **REQ-903** | Priority: MUST
>
> **Description:** The system MUST work on any Python project that uses git for version control, without requiring project-specific configuration, custom hooks, or pre-registration of state.
>
> **Rationale:** The generic portability principle requires that the tool be plug-and-play. Requiring project-specific setup creates adoption friction and limits the tool's utility for autonomous agents operating across diverse repositories.
>
> **Acceptance Criteria:** Given a fresh clone of any open-source Python project using git, `python -m import_check check` executes without errors (assuming default source directories exist). If default source directories do not exist, the tool reports which directories were not found and exits cleanly.

> **REQ-905** | Priority: MUST
>
> **Description:** The system MUST depend only on Python standard library modules (`ast`, `json`, `pathlib`, `logging`, `subprocess`, `argparse`) plus `libcst` as the sole required external dependency. The system MUST NOT depend on `rope`, `importlib.import_module()` for runtime loading, or any ML/AI framework.
>
> **Rationale:** Minimal dependencies reduce installation friction, version conflicts, and supply-chain risk. The tool must be lightweight enough to install in any Python environment without pulling in heavy transitive dependencies.
>
> **Acceptance Criteria:** The tool's dependency manifest lists only `libcst` as an external dependency. The tool runs successfully in a virtual environment with only `libcst` installed (beyond stdlib).

> **REQ-907** | Priority: MUST
>
> **Description:** All configurable parameters (source directories, exclude patterns, git ref, encapsulation check toggle, output format, log level) MUST be externalized to configuration. No behavioral parameter MUST be hardcoded in source code.
>
> **Rationale:** Hardcoded values require code changes to adjust behavior. The config-driven behavior principle requires that operators can tune the tool for their specific project layout without modifying tool source code.
>
> **Acceptance Criteria:** Every threshold, pattern, and behavioral toggle referenced in this specification is loaded from the configuration system (pyproject.toml, CLI flags, or API kwargs). Changing any configuration value takes effect on the next invocation without code changes.

> **REQ-909** | Priority: SHOULD
>
> **Description:** The system SHOULD log all operations at configurable verbosity levels. At `DEBUG` level, the system SHOULD log: each file scanned, each symbol inventoried, each migration map entry, each import rewrite applied. At `INFO` level, the system SHOULD log: summary statistics and any warnings. At `ERROR` level, the system SHOULD log only errors and the structured error list.
>
> **Rationale:** Structured logging at multiple verbosity levels supports debugging (DEBUG), normal operation monitoring (INFO), and quiet CI usage (ERROR). The structured error logging at ERROR level specifically supports downstream LLM consumption.
>
> **Acceptance Criteria:** With `log_level="DEBUG"`, the log output includes per-file and per-symbol entries. With `log_level="INFO"`, the log output includes only summary statistics and warnings. With `log_level="ERROR"`, the log output includes only errors and the structured error list.

> **REQ-911** | Priority: MUST
>
> **Description:** The system MUST degrade gracefully when optional features are unavailable:
>
> | Feature Unavailable | Degraded Behavior |
> |---------------------|-------------------|
> | `encapsulation_check` disabled via config | Encapsulation violations are not checked or reported; all other features work normally |
> | No changed files detected by git diff | The system reports "no changes detected" and exits with code 0 |
> | A source directory in `source_dirs` does not exist | The system logs a warning for the missing directory and continues scanning remaining directories |
>
> The system MUST NOT crash or return an unhandled error when any single optional feature or expected input is unavailable.
>
> **Rationale:** Robust degradation ensures the tool is safe to run in automated pipelines where environmental conditions vary.
>
> **Acceptance Criteria:** Each degraded scenario listed above is tested. The system logs a warning for each degraded condition. The system continues processing and produces a valid output for the remaining features.

> **REQ-913** | Priority: MAY
>
> **Description:** The system MAY cache the "before" symbol inventory to avoid re-reading files from git on repeated runs against the same git ref.
>
> **Rationale:** Caching avoids redundant git subprocess calls when the developer runs the tool multiple times during iterative fixing. This is an optimization that improves the interactive development experience.
>
> **Acceptance Criteria:** If caching is implemented: running the tool twice against the same git ref uses the cached inventory on the second run (verifiable via DEBUG logging). The cache is invalidated when the git ref changes or when `--no-cache` is passed.

---

## 11. System-Level Acceptance Criteria

| Criterion | Threshold | Related Requirements |
|-----------|-----------|---------------------|
| Deterministic fix coverage | The deterministic fixer resolves at least 90% of broken imports caused by simple moves, renames, splits, and merges in a test corpus | REQ-201, REQ-203, REQ-205, REQ-207, REQ-209, REQ-211, REQ-213 |
| Zero runtime side effects | The smoke test checker completes without loading any Python modules at runtime | REQ-303 |
| Format preservation | Rewritten files differ from originals only in import path/name tokens; no formatting changes outside rewritten nodes | REQ-215 |
| Portable execution | The tool runs successfully on any Python+git project without project-specific configuration | REQ-903 |
| Configuration completeness | Every behavioral parameter in this specification is configurable via the layered config system | REQ-503, REQ-505, REQ-907 |
| Structured output fidelity | JSON output from check and run operations is valid JSON and contains all specified fields | REQ-405, REQ-409, REQ-309 |

---

## 12. Requirements Traceability Matrix

| REQ ID | Section | Priority | Component/Stage |
|--------|---------|----------|----------------|
| REQ-101 | 3 | MUST | Symbol Inventory & Diffing |
| REQ-103 | 3 | MUST | Symbol Inventory & Diffing |
| REQ-105 | 3 | MUST | Symbol Inventory & Diffing |
| REQ-107 | 3 | MUST | Symbol Inventory & Diffing |
| REQ-109 | 3 | MUST | Symbol Inventory & Diffing |
| REQ-111 | 3 | SHOULD | Symbol Inventory & Diffing |
| REQ-201 | 4 | MUST | Deterministic Fixer |
| REQ-203 | 4 | MUST | Deterministic Fixer |
| REQ-205 | 4 | MUST | Deterministic Fixer |
| REQ-207 | 4 | MUST | Deterministic Fixer |
| REQ-209 | 4 | MUST | Deterministic Fixer |
| REQ-211 | 4 | MUST | Deterministic Fixer |
| REQ-213 | 4 | MUST | Deterministic Fixer |
| REQ-215 | 4 | MUST | Deterministic Fixer |
| REQ-217 | 4 | SHOULD | Deterministic Fixer |
| REQ-301 | 5 | MUST | Smoke Test Checker |
| REQ-303 | 5 | MUST | Smoke Test Checker |
| REQ-305 | 5 | MUST | Smoke Test Checker |
| REQ-307 | 5 | MUST | Smoke Test Checker |
| REQ-309 | 5 | MUST | Smoke Test Checker |
| REQ-311 | 5 | SHOULD | Smoke Test Checker |
| REQ-401 | 6 | MUST | Public API & CLI |
| REQ-403 | 6 | MUST | Public API & CLI |
| REQ-405 | 6 | MUST | Public API & CLI |
| REQ-407 | 6 | MUST | Public API & CLI |
| REQ-409 | 6 | MUST | Public API & CLI |
| REQ-411 | 6 | SHOULD | Public API & CLI |
| REQ-501 | 7 | MUST | Configuration |
| REQ-503 | 7 | MUST | Configuration |
| REQ-505 | 7 | MUST | Configuration |
| REQ-507 | 7 | MUST | Configuration |
| REQ-509 | 7 | SHOULD | Configuration |
| REQ-901 | 10 | SHOULD | Non-Functional |
| REQ-903 | 10 | MUST | Non-Functional |
| REQ-905 | 10 | MUST | Non-Functional |
| REQ-907 | 10 | MUST | Non-Functional |
| REQ-909 | 10 | SHOULD | Non-Functional |
| REQ-911 | 10 | MUST | Non-Functional |
| REQ-913 | 10 | MAY | Non-Functional |

**Total Requirements: 39**
- MUST: 31
- SHOULD: 7
- MAY: 1

---

## Appendix A. Glossary

| Term | Definition |
|------|-----------|
| **ast** | Python standard library module for parsing source code into Abstract Syntax Trees. Used for read-only analysis. |
| **libcst** | Third-party library (Concrete Syntax Tree) that parses Python source while preserving formatting, enabling precise source code modifications. |
| **git ref** | A git reference (branch name, tag, commit SHA) that identifies a specific state of the repository. |
| **FunctionDef** | An AST node type representing a Python function definition (`def func():`). |
| **ClassDef** | An AST node type representing a Python class definition (`class MyClass:`). |
| **Assign** | An AST node type representing a Python assignment statement. Used to detect module-level variable definitions. |
| **TYPE_CHECKING** | A constant from the `typing` module. Imports inside `if TYPE_CHECKING:` blocks are only executed by type checkers, not at runtime. |
| **`__all__`** | A module-level list that defines the public API of a Python module, controlling what is exported by `from module import *`. |
| **mock.patch()** | A function from `unittest.mock` that temporarily replaces a named object with a mock. Takes a string path as its primary argument. |
| **pyproject.toml** | The standard Python project configuration file (PEP 518/621). Tool-specific configuration is stored under `[tool.<name>]` sections. |

---

## Appendix B. Document References

| Document | Purpose |
|----------|---------|
| Design Sketch: `docs/superpowers/specs/2026-03-28-import-check-tool-sketch.md` | Brainstorming artifact that informed this specification. Contains approach selection rationale and coverage analysis. |
| CLAUDE.md (project root) | Project conventions for code structure, testing, configuration, and documentation. |

---

## Appendix C. Open Questions

None. All design decisions were resolved during the brainstorming phase as documented in the design sketch.
