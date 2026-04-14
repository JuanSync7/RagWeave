# Import Check Enhancements — Specification Summary

> Companion spec: `IMPORT_CHECK_ENHANCEMENTS_SPEC.md` v1.0
> Parent spec: `IMPORT_CHECK_SPEC.md` v1.0
> Summary version: aligned to enhancements spec v1.0 | 2026-04-10

---

## 1) Generic System Overview

### Purpose

The import verification checker, as originally specified, contains three accuracy and usability gaps that reduce its value as a reliable verification gate. First, relative imports are silently ignored because the checker cannot determine their absolute target without knowing the importing file's location in the package hierarchy. Second, modules that dynamically expose attributes at runtime — either through a module-level dynamic dispatch hook or through co-located type declaration files — cause the checker to report false positives for symbols that are genuinely available. Third, when the checker does produce a false positive that cannot be resolved by configuration, developers have no per-line mechanism to suppress it. These three enhancements address each gap in the checker stage of the import analysis pipeline, making verification more accurate, more transparent, and more actionable without changing the tool's external contracts or operational profile.

### How It Works

All three enhancements operate exclusively within the checker stage (Step 3 of the pipeline). The two upstream stages — symbol inventory collection and deterministic import rewriting — are unchanged. The downstream output formatting stage is also unchanged.

The first enhancement adds import-level information to the data structure returned by the import extraction function. This function continues to operate on source text alone. The checker stage, which has access to both source text and file paths, uses this level information to convert relative imports into absolute module paths by walking the importing file's ancestry within the package hierarchy. If the file is not inside a recognized package, or if the relative depth exceeds the project boundary, the import is silently skipped and recorded in diagnostic logs rather than flagged as an error.

The second enhancement extends symbol verification with an ordered fallback chain. When a symbol is not found via direct definition in the module's source, the checker optionally checks whether the module declares a module-level dynamic attribute provider (which signals that any attribute name may be available at runtime). If that check also fails, the checker optionally consults a co-located type declaration file for the module to see whether the symbol is declared there. Each fallback step is individually configurable; disabling a step restores strict source-only symbol checking for that mechanism.

The third enhancement filters imports before they enter the verification pipeline. Any import statement on a source line annotated with the designated suppression marker is extracted but immediately set aside. These suppressed imports are recorded in diagnostic logs (with file, line, and import text) and excluded from all error reporting and statistics. The suppression mechanism requires no configuration toggle — it is always active, following the convention established by comparable per-line suppression markers in other Python static analysis tools.

### Tunable Knobs

Operators can independently enable or disable the dynamic-attribute-provider fallback and the type-declaration-file fallback through a layered configuration system. Both default to enabled, which reflects the common case where these mechanisms are intentionally part of a module's API contract. When disabled, symbol verification reverts to strict source-only checking for the corresponding mechanism. Configuration can be set project-wide via a project configuration file, overridden on a per-invocation basis via command-line flags, or overridden programmatically via API arguments, with later layers taking precedence over earlier ones.

### Design Rationale

The enhancements preserve two principles from the parent system. First, the extraction function remains source-only: all filesystem-dependent operations (path resolution, type-declaration-file lookup) are performed by the calling stage, not the extraction function itself. This preserves the function's testability and eliminates the risk of filesystem coupling in the innermost parsing layer. Second, all verification uses only syntax-tree parsing and filesystem path operations — no target modules are imported or executed. This guarantees the checker can run safely in any environment, including constrained CI contexts.

The fallback chain is ordered and explicit: direct definition takes precedence, followed by dynamic-attribute-provider detection, then type-declaration-file lookup. This ordering ensures the cheapest check runs first and that the chain's behavior is predictable. Suppressions are auditable by design — nothing is silently discarded.

### Boundary Semantics

Entry: the checker receives a list of Python source files, each with source text and filesystem path. The enhancements add the expectation that file paths are available so that relative imports can be resolved and type-declaration files can be located. Exit: the checker produces a structured error list in the same schema as before the enhancements. Relative imports, once resolved, produce the same error categories as absolute imports. Suppressed imports are excluded from the error list. The checker's interface contract — error list format and result object schema — is unchanged.

---

## 2) Header

| Field | Value |
|---|---|
| Companion spec | `IMPORT_CHECK_ENHANCEMENTS_SPEC.md` v1.0 |
| Parent spec | `IMPORT_CHECK_SPEC.md` v1.0 |
| Domain | Python Import Analysis — Smoke Test Checker Enhancements |
| Status | Draft |
| See also | `IMPORT_CHECK_ENHANCEMENTS_DESIGN.md`, `IMPORT_CHECK_ENHANCEMENTS_IMPLEMENTATION.md` |

---

## 3) Scope and Boundaries

**Entry point:** The checker receives a list of Python files with source text and filesystem paths.

**Exit point:** The checker produces a structured error list (unchanged schema). Relative imports are now verified; dynamic-provider and stub-declared symbols no longer produce false positives; suppressed imports are excluded from reporting.

**In scope — this spec:**
- Relative import resolution in the smoke test checker (Step 3)
- Dynamic attribute provider detection (`__getattr__`-based suppression) in symbol verification
- Co-located type declaration file (`.pyi` stub) fallback in symbol verification
- Per-line inline suppression via comment marker
- CLI flags to disable stub and `__getattr__` fallbacks
- Configuration fields (`check_stubs`, `check_getattr`) with layered precedence

**Out of scope — this spec:**
- Relative import resolution in the deterministic fixer (Step 2)
- Recursive stub file re-export resolution
- Block-level suppression comments
- `TYPE_CHECKING`-aware automatic suppression
- Third-party stub packages installed in site-packages
- Inline suppression in the fixer
- `py.typed` marker file detection
- Namespace package support (packages without `__init__.py`)

**Out of scope — this project (unchanged from parent spec):**
- Dynamic string-constructed import paths
- Proactive symbol refactoring
- Non-Python config files referencing module paths
- Cross-repository imports
- Runtime import hook analysis

---

## 4) Architecture / Pipeline Overview

```
Developer invokes: import_check [fix|check|run]
        |
        v
+-------------------------------+
| [1] SYMBOL INVENTORY          |  (unchanged)
+-------------------------------+
        | migration map
        v
+-------------------------------+
| [2] DETERMINISTIC FIXER       |  (unchanged)
+-------------------------------+
        | rewritten files
        v
+-------------------------------+
| [3] SMOKE TEST CHECKER  ***   |  ← all enhancements here
|                               |
|  import extraction            |
|    + level field (Enhancement 1)
|                               |
|  suppression filter           |
|    + ignore-marker check (Enhancement 3)
|    → DEBUG log suppressed     |
|                               |
|  relative import resolution   |
|    + path-based (Enhancement 1)
|    → skip if unresolvable     |
|                               |
|  symbol verification          |
|    1. direct definition       |
|    2. __getattr__ fallback (Enhancement 2)
|    3. stub file fallback (Enhancement 2)
+-------------------------------+
        | structured error list
        v
+-------------------------------+
| [4] OUTPUT                    |  (unchanged)
+-------------------------------+
```

---

## 5) Requirement Framework

- **ID convention:** `REQ-NNN` (numeric, continuing parent spec's numbering)
- **Priority keywords:** MUST (mandatory), SHOULD (strongly recommended), MAY (optional)
- **Rationale present:** yes — every requirement includes a `Rationale` block
- **Acceptance criteria present:** yes — every requirement includes concrete `Acceptance Criteria`
- **ID ranges added by this spec:**

| Range | Component |
|---|---|
| REQ-313 – REQ-321 | Relative Import Resolution (Checker) |
| REQ-323 – REQ-333 | Runtime Symbol Suppression (Checker) |
| REQ-335 – REQ-341 | Inline Suppression Comments (Checker) |
| REQ-413 – REQ-415 | CLI Extensions |
| REQ-511 – REQ-515 | Configuration Extensions |
| REQ-915 – REQ-919 | Non-Functional Requirements |

**New requirements in this spec: 23 total — 19 MUST, 4 SHOULD, 0 MAY**

---

## 6) Functional Requirement Domains

**Relative Import Resolution (REQ-313 – REQ-321)**
Covers: extending the extraction function's return type to include import level; resolving relative imports to absolute module paths using the importing file's package hierarchy; handling unresolvable cases (file not in a package, resolution escaping project root) by skipping with DEBUG log; treating bare package-relative imports (`from . import foo`) consistently with module-relative imports.

**Runtime Symbol Suppression (REQ-323 – REQ-333)**
Covers: defining the ordered fallback chain for symbol verification (direct definition → `__getattr__` detection → stub file lookup); constraining `__getattr__` detection to module-level definitions only; limiting `__getattr__` suppression to `SYMBOL_NOT_DEFINED` errors (not `MODULE_NOT_FOUND` or encapsulation violations); specifying co-located stub file resolution by extension substitution; specifying AST-based (non-executing) stub file symbol checks; caching parse results within a single invocation.

**Inline Suppression Comments (REQ-335 – REQ-341)**
Covers: recognizing the `# import_check: ignore` marker on any source line; filtering suppressed imports before verification; logging every suppressed import at DEBUG level with file, line, and import text; requiring no configuration toggle to enable the mechanism.

**CLI Extensions (REQ-413 – REQ-415)**
Covers: `--no-check-stubs` flag to disable stub fallback from the command line; `--no-check-getattr` flag to disable `__getattr__` suppression from the command line.

**Configuration Extensions (REQ-511 – REQ-515)**
Covers: `check_stubs` boolean field (default `True`); `check_getattr` boolean field (default `True`); type validation for both fields; layered precedence (API kwarg > CLI flag > pyproject.toml > built-in default) consistent with parent spec.

---

## 7) Non-Functional and Security Themes

- **Zero-cost verification (REQ-915):** All three enhancements use only AST parsing and filesystem path operations. No runtime imports, subprocess calls, or target-module execution are introduced.
- **Interface stability (REQ-917):** The structured error list format and result object schema are unchanged. Existing consumers parse post-enhancement output without modification.
- **Graceful degradation (REQ-919):** Each enhancement degrades gracefully when its prerequisite is unavailable — unresolvable relative imports are skipped, disabled config reverts to strict mode, malformed stub files trigger a warning and skip (not a crash).

---

## 8) Design Principles

**Source-only extraction** — The extraction function operates on source text alone; all filesystem-dependent operations are performed by the caller, preserving purity and testability.

**Explicit fallback chain** — Symbol verification applies detection mechanisms in a fixed, documented order (direct definition → dynamic provider → type declaration file), with each step clearly separated and individually configurable.

**Auditable suppression** — Suppressed imports are never silently discarded; they are logged at DEBUG level so developers can audit which imports are being skipped.

---

## 9) Key Decisions

- **Import level returned as a field, not a side channel.** The extraction function's return type is extended to a 4-tuple including the import level for every import (0 for absolute, >0 for relative). This preserves a uniform interface and avoids conditional handling in the caller.
- **Filesystem operations belong to the checker stage, not the extraction function.** Relative import resolution and stub file lookup are performed by `check_imports`, not `_extract_imports`. This keeps the extraction function pure and independently testable.
- **Fallback mechanisms are independently configurable.** `check_getattr` and `check_stubs` are separate boolean flags, not a single "permissiveness level" toggle. Operators can enable one without the other.
- **Suppression is always-on, requires no toggle.** Following the convention of comparable per-line suppression markers in the Python ecosystem, the inline suppression mechanism requires no configuration to activate.
- **Stub resolution is co-located only.** The checker looks for stub files only adjacent to their corresponding source files, ensuring deterministic and fast lookup without filesystem traversal. Third-party stub packages are explicitly out of scope.
- **`__getattr__` suppression is module-level only.** Only a `__getattr__` function defined at module scope (not inside a class or nested function) triggers suppression. This prevents class attribute hooks from being misinterpreted as module dynamic providers.

---

## 10) Acceptance and Evaluation

The spec defines six system-level acceptance criteria extending the parent spec:

| Criterion | Related Requirements |
|---|---|
| Relative import coverage — all relative imports in standard packages resolved and verified | REQ-313, REQ-315, REQ-317, REQ-319, REQ-321 |
| False positive reduction — `__getattr__` modules do not produce `SYMBOL_NOT_DEFINED` when enabled | REQ-323, REQ-325, REQ-327 |
| Stub file coverage — co-located stub-declared symbols recognized when enabled | REQ-329, REQ-331 |
| Suppression correctness — `# import_check: ignore` lines excluded from verification and logged | REQ-335, REQ-337, REQ-339 |
| Output contract stability — JSON schema unchanged; existing consumers unaffected | REQ-917 |
| Graceful degradation — all degraded scenarios produce valid output without crashes | REQ-919 |

No standalone evaluation or feedback framework is defined in this spec. Acceptance is verified through per-requirement acceptance criteria and system-level criteria above.

---

## 11) External Dependencies

**Required (inherited from parent spec):**
- Standard library AST parser — used for import extraction, `__getattr__` detection, and stub file symbol lookup
- Standard library path utilities — used for relative import resolution and stub file location

**New contracts added by this spec:**
- Co-located `.pyi` stub files — optional; consulted only when `check_stubs` is enabled and the file exists adjacent to the corresponding `.py` source
- `__init__.py` presence — used to identify package boundaries during relative import resolution; namespace packages (no `__init__.py`) are not supported

**Downstream contract:**
- The structured error list schema is unchanged; downstream consumers (CI pipelines, LLM agents, programmatic callers) require no modification

---

## 12) Companion Documents

| Document | Relationship |
|---|---|
| `IMPORT_CHECK_SPEC.md` (parent) | Defines the base system this spec extends. All requirement IDs and design principles in this spec are additive continuations of the parent. |
| `IMPORT_CHECK_ENHANCEMENTS_SPEC.md` | The companion authoritative spec — this summary is aligned to v1.0. Read the spec for individual requirement text, rationale, and acceptance criteria. |
| `IMPORT_CHECK_ENHANCEMENTS_DESIGN.md` | Technical design document with task decomposition and code contracts for the three enhancements. |
| `IMPORT_CHECK_ENHANCEMENTS_IMPLEMENTATION.md` | Implementation source-of-truth derived from the spec and design. |

This summary is a standalone digest intended for technical stakeholders who need the shape of the enhancements spec without reading every requirement. It does not replace the spec for traceability, acceptance verification, or implementation reference.

---

## 13) Sync Status

| Field | Value |
|---|---|
| Companion spec version | 1.0 |
| Summary last updated | 2026-04-10 |
| Aligned to | `IMPORT_CHECK_ENHANCEMENTS_SPEC.md` v1.0 (Draft) |
| Requirements covered | 23 new (REQ-313 – REQ-919 range additions) |
