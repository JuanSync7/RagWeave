# Import Check Enhancements -- Design Sketch

**Date:** 2026-03-29
**Stage:** Brainstorm
**Scope:** 3 targeted enhancements to `import_check/checker.py`

---

## Goal Statement

Improve the accuracy and usability of the import_check smoke test checker by:
1. Resolving relative imports (currently skipped entirely) so they are verified like absolute imports.
2. Reducing false positives for modules that define symbols dynamically via `__getattr__` or `.pyi` stubs.
3. Supporting per-line suppression comments so developers can silence known-good imports.

All three enhancements are scoped to the **checker** (Step 2 smoke test). They do not affect the fixer (Step 1) or the LLM residual step (Step 3).

---

## Enhancement 1: Relative Import Resolution

### Clarifying Questions (Self-Answered)

**Q1: How prevalent are relative imports in this project?**
A: The main project directories (`src/`, `server/`, `config/`) use exclusively absolute imports. Relative imports are used only within `import_check/` itself (5 files, each with `from .schemas import ...` or similar). However, the tool is designed to be **generically portable** -- other Python projects that adopt it will have relative imports throughout. This is the right enhancement for generic correctness.

**Q2: Does `_extract_imports` have access to the importing file's path?**
A: No. Currently `_extract_imports(source: str)` receives only source code. The file path is available in the caller (`check_imports`), which iterates `for file_path in files`. The signature must change or a new helper must resolve relative paths externally.

### Approaches

**Approach A: Expand `_extract_imports` signature to accept file path and root.**
- Change to `_extract_imports(source: str, file_path: str | None = None, root: Path | None = None)`.
- When `node.level > 0`, compute the package of the importing file from `file_path`, then resolve the relative import to an absolute dotted path.
- Return the resolved absolute path in the same `(module, name, lineno)` tuple.
- Trade-off: Mutates a core helper signature. But the alternative (external resolution) duplicates the AST walk.

**Approach B: Keep `_extract_imports` unchanged; add a separate `_resolve_relative_import` helper called from `check_imports`.**
- `_extract_imports` returns relative imports as-is with a marker (e.g., `level` in the tuple).
- `check_imports` calls `_resolve_relative_import(module, level, file_path, root)` to convert to absolute.
- Trade-off: Cleaner separation of concerns. `_extract_imports` stays pure (source-only). Resolution logic is in the caller.

### Chosen Approach: B

Rationale: `_extract_imports` is a pure source-parsing function. Adding filesystem awareness to it violates its single responsibility. Better to extend the return type to include relative import data, and let the caller resolve. This also keeps the function testable without filesystem fixtures.

### Implementation Details

- Change `_extract_imports` return type from `list[tuple[str, str, int]]` to `list[tuple[str, str, int, int]]` where the 4th element is the `level` (0 for absolute imports, >0 for relative).
- Add `_resolve_relative_import(module: str | None, level: int, file_path: str, root: Path) -> str | None`:
  - Compute the package of the importing file: `file_path` -> dotted path, then strip the last N components based on `level`.
  - Append `module` (if any) to get the absolute dotted path.
  - Return `None` if resolution fails (file is not inside a package).
- In `check_imports`, after extracting imports, resolve relative ones before running the module/symbol checks.

---

## Enhancement 2: Runtime Symbol Suppression (`__getattr__` + `.pyi` Stub Fallback)

### Clarifying Questions (Self-Answered)

**Q1: How common are `__getattr__` modules in practice?**
A: In this project's `src/` tree: zero occurrences. But third-party-wrapping packages and lazy-loading patterns use `__getattr__` heavily (e.g., `numpy`, `pandas` use it for deprecation shims). Since the checker already skips stdlib/third-party, the practical impact is on **project-local** modules that use `__getattr__`. This is a correctness improvement for the general case, as noted in Known Limitation #5.

**Q2: Should `__getattr__` suppress ALL symbol checks or just SYMBOL_NOT_DEFINED?**
A: Only `SYMBOL_NOT_DEFINED`. If a module defines `__getattr__`, it can dynamically provide any name, so we cannot statically verify whether a specific symbol exists. `MODULE_NOT_FOUND` and `ENCAPSULATION_VIOLATION` are unaffected -- those are about the module file existing and import paths, not symbol presence.

### Approaches

**Approach A: Inline detection in `_check_symbol_defined`.**
- Before returning `False`, scan for `def __getattr__` in the module's top-level AST. If found, return `True` (symbol assumed to exist).
- If not found and symbol is missing, check for `module.pyi` alongside `module.py`. Parse the `.pyi` and check for the symbol there.
- Trade-off: Simple, minimal code change. But mixes two distinct concerns (runtime dispatch detection and stub fallback) into one function.

**Approach B: Add `_has_dynamic_getattr(module_file: Path) -> bool` and `_check_stub_defined(module_file: Path, symbol: str) -> bool` as separate helpers.**
- `_check_symbol_defined` calls them as fallback chain: defined in `.py` -> `__getattr__` present -> defined in `.pyi`.
- Trade-off: More functions, but each has a clear single purpose. Testable independently.

### Chosen Approach: B (separate helpers, fallback chain)

Rationale: Two distinct detection mechanisms (dynamic dispatch vs. stub files) should be two distinct functions. This follows the project's pattern of small, single-purpose helpers in `checker.py`. The fallback chain is explicit and configurable.

### Implementation Details

- Add `_has_dynamic_getattr(module_file: Path) -> bool`:
  - Parse the file with `ast`. Walk `tree.body` for `FunctionDef` with name `__getattr__`.
  - Cache results per file path within a single `check_imports` run (avoid re-parsing).
- Add `_resolve_stub_file(module_file: Path) -> Path | None`:
  - Given `module.py`, check for `module.pyi` in the same directory.
  - Given `package/__init__.py`, check for `package/__init__.pyi`.
  - Return the stub path if it exists, `None` otherwise.
- Modify `_check_symbol_defined` (or add a wrapping function `_check_symbol_exists`) to implement the fallback chain:
  1. Check `.py` file (existing logic).
  2. If not found: check `__getattr__` in `.py` file. If present, return `True`.
  3. If not found: check `.pyi` stub. If stub exists and defines the symbol, return `True`.
  4. Otherwise return `False`.
- Add config fields `check_stubs: bool = True` and `check_getattr: bool = True` to `ImportCheckConfig`. The `check_getattr` field controls whether `__getattr__` presence suppresses `SYMBOL_NOT_DEFINED`. When `False`, the checker reports missing symbols strictly even if `__getattr__` is defined.

---

## Enhancement 3: Inline Suppression Comments (`# import_check: ignore`)

### Clarifying Questions (Self-Answered)

**Q1: Should suppression work at the line level or the statement level?**
A: Line level. A `from X import A, B, C  # import_check: ignore` suppresses ALL symbols on that line. This matches the behavior of `# noqa`, `# type: ignore`, and other Python tooling conventions. Statement-level (suppressing a specific symbol) adds complexity without clear value.

**Q2: Where in the pipeline should suppression be checked -- in `_extract_imports` or in `check_imports`?**
A: In `_extract_imports`. The function already has access to the source text and the AST line numbers. Filtering at extraction time means the suppressed import never enters the checking pipeline at all, which is the simplest and most efficient approach. Alternatively, we could filter in `check_imports` after extraction -- this would allow us to still report suppressed imports in debug/verbose mode. The second approach is slightly better for diagnostics.

### Approaches

**Approach A: Filter in `_extract_imports` (never yield suppressed imports).**
- After parsing, for each import node, check if the source line contains `# import_check: ignore`.
- If so, skip the import entirely.
- Trade-off: Simplest. But suppressed imports are invisible -- no way to audit what was suppressed.

**Approach B: Filter in `check_imports` (extract all, then skip suppressed before checking).**
- `_extract_imports` returns all imports including suppressed ones.
- `check_imports` reads the source line for each import and checks for the suppression comment.
- Suppressed imports are logged at DEBUG level but not checked.
- Trade-off: Slightly more code, but enables diagnostics and auditing.

### Chosen Approach: B (filter in `check_imports`)

Rationale: Suppression should be visible and auditable. The stakeholder priorities favor correctness over performance, and being able to log "skipped N suppressed imports" at DEBUG level helps developers verify their suppressions are being applied. The source text is already available in `check_imports`.

### Implementation Details

- Add helper `_is_suppressed(source: str, lineno: int) -> bool`:
  - Get the source line at `lineno` (1-indexed).
  - Check if it contains the marker string `# import_check: ignore`.
  - Support the marker anywhere on the line (not just at the end, to handle multi-line import formatting).
- In `check_imports`, after extracting imports, filter out suppressed ones before the module/symbol/encapsulation checks.
- Log suppressed imports at DEBUG level: `"SUPPRESSED: %s:%d — %s (# import_check: ignore)"`.
- No config field needed -- suppression is always available. This matches `# noqa` and `# type: ignore` conventions (no config toggle required to enable per-line suppression).

---

## Key Decisions

1. **`_extract_imports` stays source-only.** Relative import resolution is handled externally by the caller. This preserves the function's purity and testability.

2. **Relative imports return `level` in the tuple.** The return type changes from 3-tuple to 4-tuple. Callers that destructure must be updated. Since `_extract_imports` is a private function (prefixed `_`), this is safe.

3. **`__getattr__` detection and `.pyi` fallback are separate helpers.** Two distinct mechanisms, two distinct functions. The fallback chain in `_check_symbol_defined` is: `.py` definition -> `__getattr__` presence -> `.pyi` stub definition.

4. **Suppression filtering happens in `check_imports`, not `_extract_imports`.** This enables DEBUG-level logging of suppressed imports for auditing.

5. **Two new config fields: `check_stubs: bool` and `check_getattr: bool`.** Both default to `True`. The `__getattr__` suppression changes checker behavior to be more permissive, so it should be toggleable (consistent with `encapsulation_check` and `check_stubs` patterns). Relative import checking is always-on (fixing a bug, not optional behavior). Inline suppression is always available (standard `# noqa` pattern, no toggle needed).

---

## Component Changes

### `import_check/schemas.py`

| Change | Detail |
|--------|--------|
| Add `check_stubs` field to `ImportCheckConfig` | `check_stubs: bool = True` -- enables `.pyi` stub fallback for symbol checking |
| Add `check_getattr` field to `ImportCheckConfig` | `check_getattr: bool = True` -- enables `__getattr__` presence to suppress SYMBOL_NOT_DEFINED |

### `import_check/checker.py`

| Function | Change |
|----------|--------|
| `_extract_imports` | Return 4-tuple `(module, name, lineno, level)` instead of 3-tuple. Stop skipping relative imports; return them with `level > 0`. |
| `_resolve_relative_import` | **New.** Convert relative import to absolute dotted path using importing file's package location. |
| `_has_dynamic_getattr` | **New.** Parse module file for `def __getattr__` at top level. |
| `_resolve_stub_file` | **New.** Given a `.py` module path, return the corresponding `.pyi` path if it exists. |
| `_check_symbol_defined` | Add fallback chain: existing logic -> `__getattr__` check -> `.pyi` stub check. |
| `_is_suppressed` | **New.** Check if a source line contains `# import_check: ignore`. |
| `check_imports` | (1) Resolve relative imports after extraction. (2) Filter suppressed imports before checking. (3) Pass config to symbol check for `check_stubs` toggle. |

### `import_check/__main__.py`

| Change | Detail |
|--------|--------|
| Add `--no-check-stubs` CLI flag | Maps to `check_stubs=False` config override |

### `import_check/__init__.py`

No changes to public API surface. The `check()` function passes config through to `checker.check_imports()` which already receives the config object.

---

## Scope Boundary

### In Scope

- Relative import resolution for `from .foo import bar` and `from ..foo import bar` in the checker.
- `__getattr__` detection to suppress `SYMBOL_NOT_DEFINED` false positives.
- `.pyi` stub file fallback for symbol definition checking.
- `# import_check: ignore` per-line suppression in the checker.
- Config field for stub checking toggle.
- CLI flag for stub checking toggle.
- DEBUG-level logging for suppressed imports.
- Unit tests for all new helpers.

### Out of Scope

- Relative import resolution in the **fixer** (Step 1). The fixer operates on migration maps, not raw imports.
- Recursive `.pyi` stub resolution (following re-exports in stubs). Only direct definition in the stub is checked.
- Block-level suppression comments (e.g., `# import_check: ignore-block` covering multiple lines).
- `TYPE_CHECKING`-aware suppression (suppressing all imports inside `if TYPE_CHECKING:` blocks). This is a separate feature.
- Third-party `.pyi` stub packages (e.g., `types-requests`). Only project-local `.pyi` files are checked.
- Suppression in the fixer (the fixer rewrites imports; suppression only affects the checker).
- `py.typed` marker file detection.

---

## Configuration Surface

### New Fields in `ImportCheckConfig`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `check_stubs` | `bool` | `True` | When True, fall back to `.pyi` stub files for symbol definition checking if the `.py` file does not define the symbol. |
| `check_getattr` | `bool` | `True` | When True, `__getattr__` presence in a module suppresses SYMBOL_NOT_DEFINED for imports from that module. When False, missing symbols are reported strictly. |

### New CLI Flags

| Flag | Maps To | Description |
|------|---------|-------------|
| `--no-check-stubs` | `check_stubs=False` | Disable `.pyi` stub fallback for symbol checking. |
| `--no-check-getattr` | `check_getattr=False` | Disable `__getattr__`-based symbol suppression. |

### pyproject.toml Addition

```toml
[tool.import_check]
check_stubs = true    # default; set false to disable .pyi fallback
check_getattr = true  # default; set false to disable __getattr__ suppression
```

---

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Relative import resolution produces wrong absolute path for edge cases (namespace packages, `__init__`-less directories) | Medium | Only resolve when the importing file is inside a directory with `__init__.py`. Fall back to skipping if resolution fails. |
| `__getattr__` suppression hides real missing symbols | Low | `__getattr__` is a deliberate API pattern. If a module defines it, the module author intends dynamic dispatch. The checker respects that intent. |
| `.pyi` stub is stale relative to `.py` source | Low | `.pyi` stubs are a standard Python pattern with understood staleness risks. Out of scope to validate stub freshness. |
| `# import_check: ignore` is overused, hiding real errors | Low | DEBUG-level logging makes suppressions visible. This is the same risk profile as `# noqa` -- accepted industry pattern. |
