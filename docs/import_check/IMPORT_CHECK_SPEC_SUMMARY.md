# Import Check Tool — Specification Summary

## 1) Generic System Overview

### Purpose

After a codebase refactoring — whether manual or autonomous — the module locations of functions, classes, and variables shift. Every file that imported those symbols now references a path that no longer exists. The import check tool solves this problem retroactively: it detects all broken import references across a Python project and rewrites them to reflect the new symbol locations, then verifies that the result is clean. Without this tool, post-refactoring import repair is a manual process that scales poorly and consistently misses string-based references that conventional static analysis ignores.

### How It Works

The tool operates as a four-stage pipeline. When invoked, it first builds two snapshots of the codebase: a "before" snapshot reconstructed from version control history (capturing symbol locations prior to refactoring) and an "after" snapshot built from the current working tree. Each snapshot is a mapping of every named symbol to its defining module path, constructed by parsing source files into syntax trees — no code is executed.

The two snapshots are then compared to produce a migration map: a structured record of every symbol that moved, was renamed, split across multiple files, or merged from multiple sources into one. Each migration map entry captures the original path, the new path, the symbol name, any rename, and the refactoring pattern type.

In the third stage, the migration map drives a formatting-preserving rewriter that rewrites all affected import statements in-place. The rewriter handles every common import pattern: standard module imports, named imports, aliased imports, lazy imports inside function bodies, type-annotation-only imports, conditional imports in try/except blocks, public API export lists, and string-based references passed to dynamic module loading or patching utilities. Simple single-assignment variable patterns for string paths are also handled. Changes that cannot be resolved deterministically — dynamic string construction, truly ambiguous renames — are flagged but not modified.

After rewriting, the tool runs a verification pass over every import statement in the project. It checks each import against the filesystem and parsed symbol tables without loading any module at runtime. Imports that resolve successfully pass; those that do not are recorded in a structured error list. The checker also identifies imports that bypass a package's declared public interface and reports them as advisory diagnostics, separate from errors.

### Tunable Knobs

Operators can configure which source directories the tool scans, and which paths to exclude (vendor directories, build artifacts, caches). The version control reference used to reconstruct the pre-refactoring state is configurable, enabling comparison against any historical commit rather than just the immediate prior state. The encapsulation violation check can be toggled on or off for projects where internal imports are intentional. Output can be directed to human-readable text or structured machine-parseable format. Logging verbosity is independently configurable for interactive use, CI, and debugging. All settings have sensible defaults that work for standard Python project layouts with no configuration required.

### Design Rationale

The tool is designed around a deterministic-first principle: syntax-tree analysis and pattern matching handle the overwhelming majority of import repair without invoking any AI or language model. This keeps the common path fast, predictable, and cost-free. The LLM is an optional downstream consumer of the structured residual error list — not a primary fix mechanism.

Verification uses only static filesystem and syntax-tree checks, never runtime module loading. This zero-cost verification principle ensures the tool is safe to run in any environment, including those where importing a module would trigger GPU initialization, database connections, or network calls.

The tool is designed to work on any Python project that uses version control, with no project-specific setup. This generic portability is essential for autonomous agents that operate across diverse repositories.

### Boundary Semantics

**Entry point:** A developer or automated agent invokes the tool after completing a refactoring operation. The tool receives as input the current working tree, version control history, and optional configuration overrides.

**Exit point:** The tool produces one of two outcomes: (a) all fixable imports have been rewritten in-place and the verification pass reports a clean codebase, or (b) a structured error list of residual broken imports is produced for downstream consumption. Advisory diagnostics for encapsulation violations are always reported separately. The tool does not move symbols, rename modules, or modify non-import code — its responsibility ends at import statement correctness.

---

## 2) Header

| Field | Value |
|-------|-------|
| **Companion spec** | [IMPORT_CHECK_SPEC.md](IMPORT_CHECK_SPEC.md) |
| **Spec version** | 1.0 (Draft) |
| **Summary purpose** | Concise digest of intent, scope, structure, and key decisions |
| **Domain** | Python Import Analysis & Repair — Developer Tooling |

---

## 3) Scope and Boundaries

**Entry point:** Developer or agent invokes the tool after completing a refactoring operation, via CLI (`python -m import_check [fix|check|run]`) or programmatic API call.

**Exit point:** The tool has either (a) rewritten all fixable broken imports in-place and reported results, or (b) produced a structured error list of unfixable residual issues for downstream consumption.

**In scope:**
- Building before/after symbol inventories from version control history and working tree
- Diffing inventories to produce a migration map (moves, renames, splits, merges)
- Deterministic in-place rewriting of all import statement styles
- Rewriting string-based references in dynamic module loading and patching utilities
- Updating public API export lists when referenced symbols are renamed
- Smoke test verification using filesystem and syntax-tree checks only (no runtime loading)
- Encapsulation violation detection and reporting (advisory, not auto-fixed)
- Structured error output for residual broken imports
- Public programmatic API and CLI with human and JSON output formats
- Layered configuration via project config file, CLI flags, and API kwargs

**Out of scope — this spec:**
- LLM execution logic for residual fix processing (the structured error format is defined here; the agent that consumes it is specified separately)
- Installation, packaging, and distribution

**Out of scope — this project:**
- Truly dynamic string construction (flagged, not fixed)
- Proactive refactoring (moving symbols to new locations)
- Non-Python configuration files that reference module paths (YAML, JSON, TOML pipelines)
- Cross-repository imports
- Runtime import hook analysis or custom finder/loader mechanisms

---

## 4) Architecture / Pipeline Overview

```
Developer invokes: [fix|check|run]
         │
         ▼
┌─────────────────────────────┐
│ [1] SYMBOL INVENTORY &      │
│     DIFFING                 │
│  Before: from VCS history   │
│  After:  from working tree  │
│  Output: migration map      │
└──────────────┬──────────────┘
               │ migration map
               ▼
┌─────────────────────────────┐
│ [2] DETERMINISTIC FIXER     │
│  Rewrite all import styles  │
│  + string refs + __all__    │
│  Format-preserving (in-place│
└──────────────┬──────────────┘
               │ rewritten files
               ▼
┌─────────────────────────────┐
│ [3] SMOKE TEST CHECKER      │
│  Verify every import via    │
│  filesystem + AST only      │
│  Report encapsulation       │
│  violations (advisory)      │
└──────────────┬──────────────┘
               │ structured error list
               ▼
┌─────────────────────────────┐
│ [4] OUTPUT                  │
│  Human-readable or JSON     │
│  Residual errors for LLM    │
└─────────────────────────────┘
```

**Stage data flow:**

| Stage | Input | Output |
|-------|-------|--------|
| Symbol Inventory & Diffing | VCS ref (before), working tree (after), changed file list | Migration map |
| Deterministic Fixer | Migration map, all Python source files | Rewritten files (in-place) |
| Smoke Test Checker | All Python source files | Structured error list, pass/fail |
| Output | Error list, fix statistics | Human report or JSON |

The `fix()` API runs stages 1–2. The `check()` API runs stage 3. The `run()` API runs all stages in sequence.

---

## 5) Requirement Framework

**ID convention:** All requirements use the `REQ-xxx` prefix. No separate families — one unified prefix, grouped by section.

**Priority keywords:** RFC 2119 — MUST (non-conformant without it), SHOULD (recommended, omittable with justification), MAY (optional).

**Requirement format:** Each requirement includes Description, Rationale, and Acceptance Criteria.

**ID ranges by section:**

| Section | ID Range | Component |
|---------|----------|-----------|
| Section 3 | REQ-1xx | Symbol Inventory & Diffing |
| Section 4 | REQ-2xx | Deterministic Fixer |
| Section 5 | REQ-3xx | Smoke Test Checker |
| Section 6 | REQ-4xx | Public API & CLI |
| Section 7 | REQ-5xx | Configuration |
| Section 10 | REQ-9xx | Non-Functional Requirements |

**Total:** 39 requirements — 31 MUST, 7 SHOULD, 1 MAY.

---

## 6) Functional Requirement Domains

**REQ-1xx — Symbol Inventory & Diffing**
Covers construction of before/after symbol inventories from version control history and working tree, scoping to changed files for performance, migration map generation for moves/renames/splits/merges, and graceful handling of parse failures.

**REQ-2xx — Deterministic Fixer**
Covers rewriting of all import statement forms (module imports, named imports, aliases, lazy imports, TYPE_CHECKING blocks, conditional imports), updating `__all__` export lists, rewriting string-based references in dynamic module loading and patching utilities, single-assignment variable path rewriting, formatting-preserving modification (no whitespace side effects), and flagging of unfixable dynamic string constructions.

**REQ-3xx — Smoke Test Checker**
Covers verification of every import against filesystem and parsed symbol tables (no runtime loading), detection and advisory reporting of encapsulation violations (not auto-fixed), structured error list production for residual broken imports with all required fields, and summary statistics output.

**REQ-4xx — Public API & CLI**
Covers the three-function programmatic API (`fix`, `check`, `run`), the CLI entry point with subcommand selection and default-to-run behavior, dual output formats (human and JSON), configuration override via API kwargs, typed result object returned from API calls, and CI-compatible exit codes.

**REQ-5xx — Configuration**
Covers reading from the standard project configuration file under the tool's namespace, all supported configuration keys with types and defaults, layered precedence (API kwargs > CLI flags > config file > defaults), fail-fast validation with clear error messages, and CLI flag equivalents for all keys.

**REQ-9xx — Non-Functional Requirements**
Covers performance targets for interactive use, generic portability across any Python+VCS project, minimal dependency footprint, config-driven behavior with no hardcoded parameters, structured logging at multiple verbosity levels, graceful degradation when optional features are unavailable or inputs are missing, and optional inventory caching.

---

## 7) Non-Functional and Security Themes

- **Performance:** The tool targets sub-30-second completion on codebases up to 1,000 Python files (excluding any LLM processing), achieved by scoping inventory work to the diff set rather than the full codebase.
- **Portability:** Works on any Python project with a version control repository — no project-specific setup, custom hooks, or pre-registration required.
- **Minimal footprint:** A single external library dependency beyond the standard library; no ML framework or heavy transitive dependencies.
- **Determinism:** The fix pipeline produces identical output for identical inputs; no randomness, no LLM in the primary path.
- **Safe verification:** The checker never executes module code, preventing environmental side effects during CI or automated use.
- **Observability:** Configurable logging verbosity supports debugging, normal operation, and quiet CI modes.
- **Resilience:** Graceful degradation when individual files fail to parse, source directories are missing, or no changed files are detected.

No security-specific requirement family is defined. The zero-runtime-loading constraint (REQ-303) is the primary safety boundary: the tool cannot trigger side effects from the codebases it analyzes.

---

## 8) Design Principles

| Principle | Description |
|-----------|-------------|
| **Deterministic-first** | AST-based analysis and rewriting handles the majority of cases; the LLM is a safety net for residuals, not the primary fix mechanism. |
| **Zero-cost verification** | The smoke test uses only syntax-tree parsing and filesystem checks — no runtime module loading, no side effects. |
| **Generic portability** | No project-specific assumptions; works on any Python project with version control and no required setup. |
| **Report-only diagnostics** | Encapsulation violations and dynamic references are detected and reported but never auto-fixed. |
| **Config-driven behavior** | All behavioral parameters are externalized to configuration; no stage behavior is hardcoded. |

---

## 9) Key Decisions

- **Three-stage pipeline with optional LLM handoff.** The deterministic pipeline covers the common case and produces a structured residual error list. LLM processing of that list is out of scope for this spec and specified separately — keeping concerns cleanly separated.
- **Diff-scoped inventory construction.** Inventory analysis is bounded to files changed in the version control diff (plus new files), keeping runtime proportional to the size of the refactoring rather than the full codebase.
- **Format-preserving rewriter for all source modifications.** A concrete syntax tree library is required for all in-place rewrites to prevent gratuitous formatting changes that would obscure meaningful diffs.
- **Advisory-only encapsulation violations.** Encapsulation violations are intentionally excluded from the auto-fix path because they may be intentional; they are surfaced as a separate diagnostic category requiring human judgment.
- **Unified `REQ-xxx` namespace.** A single requirement prefix with section-based ID ranges (rather than semantic families like `FR-`, `NFR-`) keeps the namespace simple while still allowing grouped traceability.

---

## 10) Acceptance, Evaluation, and Feedback

The spec defines system-level acceptance criteria as a table with explicit thresholds:

| Criterion | Description |
|-----------|-------------|
| Deterministic fix coverage | The fixer resolves at least 90% of broken imports from simple moves, renames, splits, and merges in a test corpus |
| Zero runtime side effects | The checker completes without loading any Python modules at runtime |
| Format preservation | Rewritten files differ from originals only in import path/name tokens |
| Portable execution | Runs on any Python+VCS project without project-specific configuration |
| Configuration completeness | Every behavioral parameter is configurable via the layered config system |
| Structured output fidelity | JSON output is valid and contains all specified fields |

No evaluation framework or feedback loop is defined in this spec. Acceptance is test-based.

---

## 11) External Dependencies

**Required:**
- Python 3.10+ runtime
- Version control (git) installation and a git repository for the target project
- A formatting-preserving concrete syntax tree library (sole required external package)

**Optional:**
- Project configuration file (`[tool.import_check]` section) — tool operates on defaults if absent

**Downstream contract:**
- The structured error list (file path, line number, import statement, error category, original module path) is the interface contract for any downstream LLM agent or CI consumer. That consumer is out of scope for this spec.

**Assumptions:**
- The target codebase uses standard Python import conventions; custom import hooks and finders are not analyzed.
- The version control ref used for the before state contains a valid, parseable codebase; corrupted files at that ref are skipped with a warning.

---

## 12) Companion Documents

This summary is a **Layer 2 — Spec Summary** in the four-layer documentation hierarchy:

```
Layer 1: Platform Spec          (manual — not yet produced)
Layer 2: Spec Summary           ← THIS DOCUMENT
Layer 3: Authoritative Spec     → IMPORT_CHECK_SPEC.md
Layer 4: Implementation Guide   → (not yet produced)
```

**How to use this document:**
- Read this summary to understand the system's shape, scope, and key decisions without reading every requirement.
- Read [IMPORT_CHECK_SPEC.md](IMPORT_CHECK_SPEC.md) for complete requirement text, acceptance criteria, and the full traceability matrix.
- The spec also contains: Section 8 (Interface Contracts — structured error list, migration map, result object schemas), Section 9 (Error Taxonomy), and Appendix A (Glossary).

---

## 13) Sync Status

| Field | Value |
|-------|-------|
| **Spec version** | 1.0 |
| **Spec status** | Draft |
| **Spec date** | 2026-03-28 |
| **Summary date** | 2026-04-10 |
| **Aligned to** | IMPORT_CHECK_SPEC.md v1.0 — full alignment |
