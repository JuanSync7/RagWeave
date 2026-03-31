# Import Check Tool — Design Sketch

## Goal

Build a generic, portable Python tool (`import_check`) that automatically detects and fixes broken imports after code refactoring. The tool runs as a 3-step pipeline: deterministic fix using `ast` + `libcst`, smoke test verification, and LLM-assisted residual fix. It should be plug-and-play for any Python project with git.

## Chosen Approach

**Symbol-level inventory diffing with graduated fix strategy.**

We explored three approaches:
1. **Module-level registry file + watcher** — rejected: too coarse, can't track function-level moves
2. **File-level AST comparison** — rejected: breaks on multi-file refactors (splits, merges)
3. **Symbol-level inventory across codebase** — chosen: handles all refactoring patterns

The key insight: build a complete symbol inventory (function/class/variable → file path) from both old state (via `git show HEAD:<file>`) and new state (current files), then diff the inventories to detect moves, renames, splits, and merges at the symbol level.

## Key Decisions

1. **`ast` for detection, `libcst` for rewriting** — `ast` is stdlib and fast for read-only analysis; `libcst` preserves formatting when rewriting import nodes. No `rope` — it's designed for proactive refactoring, not reactive post-implementation fixing.

2. **Symbol-level inventory, not file-level** — comparing inventories across all changed files handles one-to-many (splits) and many-to-one (merges) correctly. Only changed files are scanned (via `git diff --name-only HEAD`).

3. **Smoke test as zero-cost verification gate** — pure `ast.parse()` + filesystem checks (does module path exist as file? does file define the imported symbol?). No `importlib.import_module()` — avoids loading heavy packages like torch.

4. **LLM as safety net, not primary tool** — deterministic steps handle ~95% of cases. The smoke test catches remaining failures with zero tokens. The LLM only processes the residual error list with a rigid grep → read snippet → edit strategy.

5. **Generic and portable** — no project-specific assumptions. Works on any Python project with git. Single `python -m import_check` entry point.

6. **Config-driven behavior** — all behavior is controllable via config: target directories, exclude patterns, git ref for "before" state, toggle encapsulation checks, logging verbosity, output format.

## Configuration Surface

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `source_dirs` | `list[str]` | `["src", "server", "config"]` | Directories to scan for Python files |
| `exclude_patterns` | `list[str]` | `[".venv", "__pycache__", "node_modules"]` | Glob patterns to exclude from scanning |
| `git_ref` | `str` | `"HEAD"` | Git ref for "before" state (can be a commit SHA, branch, tag) |
| `encapsulation_check` | `bool` | `true` | Enable/disable encapsulation violation reporting |
| `output_format` | `str` | `"human"` | Output format: `"human"` (readable) or `"json"` (machine-parseable) |
| `log_level` | `str` | `"INFO"` | Logging verbosity: DEBUG, INFO, ERROR |

Config can be provided via:
1. `pyproject.toml` under `[tool.import_check]`
2. CLI flags (override pyproject.toml)
3. Programmatic API kwargs (override everything)

## Components

- **`inventory.py`** — builds symbol inventories using `ast`: parses Python files, extracts all `FunctionDef`, `ClassDef`, `Assign` names with their module paths. Builds "before" inventory from `git show HEAD:<file>` and "after" from current files.
- **`differ.py`** — diffs two inventories to produce a migration map: detects moves (same name, different path), renames (different name, same area), splits (one file → many), merges (many → one).
- **`fixer.py`** — uses `libcst` to rewrite imports based on the migration map. Handles: `from x import y`, `import x`, aliased imports, `__all__` lists, `mock.patch()` string arguments, `importlib.import_module()` string literals.
- **`checker.py`** — smoke test: walks all `.py` files, parses imports with `ast`, verifies target module exists on filesystem, verifies imported symbol is defined in target module. Outputs structured error list at ERROR log level. Encapsulation violations are **report-only** (diagnostic output, not auto-fixed).
- **`__init__.py`** — public API: `fix()`, `check()`, `run()` (both). Also contains logging setup.
- **`__main__.py`** — CLI entry point and argument parsing: `python -m import_check [fix|check|run]`.

## Scope Boundary

### In Scope
- Detecting and fixing broken imports from: moves, renames, splits, merges
- All import styles: regular, lazy (inside functions), `TYPE_CHECKING`, conditional (`try/except`)
- String-based references: `mock.patch()`, `importlib.import_module()` with literal args
- `__all__` list updates
- Simple dataflow for variable-held string paths: **bounded to single-assignment string literals in the same function scope only** (e.g., `path = "src.x.y"; importlib.import_module(path)`). No cross-function tracking, no multi-step resolution. Handled in `fixer.py`.
- Encapsulation violation detection: **report-only diagnostic** in `checker.py` output. External callers importing internal modules instead of `__init__.py` are flagged but not auto-fixed.
- Structured error logging for LLM consumption
- CLI and programmatic API

### Out of Scope
- Truly dynamic string construction (`f"src.{runtime_var}"`) — flagged, not fixed
- Proactive refactoring (use IDE/rope for that)
- Non-Python config files referencing Python paths (YAML, JSON, etc.)
- Cross-repository imports
- Step 3 LLM execution (the tool prepares the error list; the LLM skill/agent consumes it separately)

## Open Questions

None — all questions were resolved during brainstorming.

## Coverage Analysis

| Case | Handler | Tokens |
|------|---------|--------|
| Function/class moved between files | ast inventory diff + libcst | 0 |
| Function renamed | ast inventory diff + libcst | 0 |
| One file split into many | ast inventory diff + libcst | 0 |
| Many files merged into one | ast inventory diff + libcst | 0 |
| Lazy imports inside functions | ast scans full tree | 0 |
| `TYPE_CHECKING` imports | ast sees all nodes | 0 |
| `mock.patch()` string paths | ast Call node visitor + libcst | 0 |
| `__all__` lists | ast Assign node + libcst | 0 |
| Simple dynamic: `path = "src.x.y"` | dataflow script | 0 |
| Encapsulation violations | boundary check | 0 |
| Renamed + moved simultaneously | smoke test → LLM | ~100 |
| Symbol split (1→many) | smoke test → LLM | ~100 |
| Truly dynamic string construction | flagged only | 0 |
