<!-- @summary
Generic, portable Python tool that detects and fixes broken imports after code refactoring.
Three-step pipeline: deterministic fix (ast + libcst), smoke test (ast + filesystem), LLM residual fix.
@end-summary -->

# import_check

Automatically detect and fix broken Python imports after code refactoring.

When you move functions between files, rename modules, split large files, or merge small ones,
every `import`, `from ... import`, `mock.patch()` string, `importlib.import_module()` call,
and `__all__` entry that references the moved symbols breaks. This tool fixes them.

## Quick Start

```bash
# Run the full pipeline (fix + check)
python -m import_check

# Or via make
make import-check

# Step 1 only: deterministic fix
python -m import_check fix

# Step 2 only: smoke test
python -m import_check check

# Machine-parseable output (for LLM consumption)
python -m import_check check --format json
```

## Programmatic API

```python
from import_check import fix, check, run

# Fix broken imports deterministically
result = fix()  # FixResult

# Smoke test all imports
errors = check()  # list[ImportError]

# Both: fix then check
result = run()  # RunResult(fix_result, remaining_errors)
```

All functions accept optional `root` and `**config_overrides`:

```python
result = run(
    root="/path/to/project",
    source_dirs=["src", "lib"],
    git_ref="HEAD~3",
    encapsulation_check=False,
)
```

## How It Works

### Step 1: Deterministic Fix (0 tokens)

1. `git diff --name-only HEAD` to find changed files
2. Build symbol inventories (old via `git show`, new via filesystem) using `ast`
3. Diff inventories to detect moves, renames, splits, merges at the symbol level
4. Rewrite imports using `libcst` (preserves formatting)

Handles: `from x import y`, `import x`, aliases, `__all__`, `mock.patch()` strings,
`importlib.import_module()` strings, single-assignment dataflow.

### Step 2: Smoke Test (0 tokens)

For every import in every `.py` file:
- Does the target module exist as a file?
- Does that file define the imported symbol?
- (Optional) Does the import violate encapsulation boundaries?

Pure `ast.parse()` + filesystem check. No `importlib.import_module()`, no heavy package loading.

### Step 3: LLM Fix (minimal tokens, separate tool)

The `--format json` output from step 2 is designed for LLM consumption.
A Claude Code agent reads the error list and applies fixes with a rigid strategy:
1. `grep "def {symbol}"` across `**/*.py` to find the new location
2. Read 3-5 line snippet to confirm
3. Edit the import line

## Configuration

Via `pyproject.toml`:

```toml
[tool.import_check]
source_dirs = ["src", "server", "config"]
exclude_patterns = [".venv", "__pycache__", "node_modules"]
git_ref = "HEAD"
encapsulation_check = true
output_format = "human"  # or "json"
log_level = "INFO"
```

Via CLI flags (override pyproject.toml):

```bash
python -m import_check check \
  --source-dirs src lib \
  --exclude .venv build \
  --git-ref HEAD~5 \
  --no-encapsulation-check \
  --format json \
  --log-level DEBUG
```

## What It Detects and Fixes

| Case | Handled By | Auto-Fixed |
|------|-----------|------------|
| Function/class moved between files | inventory diff + libcst | Yes |
| Function renamed | inventory diff + libcst | Yes |
| File split into multiple | inventory diff + libcst | Yes |
| Files merged into one | inventory diff + libcst | Yes |
| Lazy imports (inside functions) | ast full tree scan | Yes |
| `TYPE_CHECKING` imports | ast full tree scan | Yes |
| `mock.patch()` string paths | ast Call visitor + libcst | Yes |
| `__all__` lists | ast Assign + libcst | Yes |
| `importlib.import_module()` strings | ast Call visitor + libcst | Yes |
| Single-assignment string dataflow | ast + libcst | Yes |
| Encapsulation violations | checker (report-only) | No |
| Renamed + moved simultaneously | checker (flagged) | No (LLM) |
| Dynamic string construction | not detectable | No |

## Module Layout

```
import_check/
  schemas.py       -- Typed contracts (SymbolInfo, MigrationEntry, ImportError, etc.)
  inventory.py     -- AST symbol extraction + git history retrieval
  differ.py        -- Inventory diffing (moves, renames, splits, merges)
  fixer.py         -- libcst import rewriting (3 transformers)
  checker.py       -- Smoke test (filesystem + AST verification)
  __init__.py      -- Public API: fix(), check(), run()
  __main__.py      -- CLI entry point
```

## Requirements

- Python 3.10+
- `libcst` (for import rewriting)
- `git` (for diff and history)
- No other external dependencies

## Documentation

- [Spec](../docs/import_check/IMPORT_CHECK_SPEC.md) -- 39 formal requirements
- [Design](../docs/import_check/IMPORT_CHECK_DESIGN.md) -- Architecture and task decomposition
- [Implementation](../docs/import_check/IMPORT_CHECK_IMPLEMENTATION.md) -- Phased build plan
- [Engineering Guide](../docs/import_check/IMPORT_CHECK_ENGINEERING_GUIDE.md) -- How it works, config, extensions
- [Test Docs](../docs/import_check/IMPORT_CHECK_MODULE_TESTS.md) -- Per-module test specifications
