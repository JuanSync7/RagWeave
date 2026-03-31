# Import Check Tool -- Test Docs

> **For write-module-tests agents:** This document is your source of truth.
> Read ONLY your assigned module section. Do not read source files, implementation code,
> or other modules' test specs.

**Spec:** `docs/import_check/IMPORT_CHECK_SPEC.md`
**Design doc:** `docs/import_check/IMPORT_CHECK_DESIGN.md`
**Phase 0 contracts:** `docs/import_check/IMPORT_CHECK_IMPLEMENTATION.md` (Phase 0 section)
**Produced by:** write-test-docs
**Test file location:** `tests/import_check/`

---

## Mock/Stub Interface Specifications

### Mock: Git subprocess calls

**What it replaces:** `subprocess.run()` calls to `git diff --name-only` and `git show <ref>:<file>`.

**Interface to mock:**
```python
# Used in inventory.get_changed_files
subprocess.run(
    ["git", "diff", "--name-only", git_ref],
    capture_output=True, text=True, cwd=str(root),
) -> subprocess.CompletedProcess

# Used in inventory.build_old_inventory
subprocess.run(
    ["git", "show", f"{git_ref}:{file_path}"],
    capture_output=True, text=True,
) -> subprocess.CompletedProcess
```

**Happy path return:**
```python
# git diff --name-only
subprocess.CompletedProcess(args=..., returncode=0, stdout="src/foo.py\nsrc/bar.py\n", stderr="")

# git show
subprocess.CompletedProcess(args=..., returncode=0, stdout="def my_func():\n    pass\n", stderr="")
```

**Error path return:**
```python
# git diff fails (invalid ref)
subprocess.CompletedProcess(args=..., returncode=128, stdout="", stderr="fatal: bad revision 'invalid_ref'")

# git show file not found at ref
subprocess.CompletedProcess(args=..., returncode=128, stdout="", stderr="fatal: path 'src/deleted.py' does not exist in 'HEAD'")
```

**Used by modules:** `import_check/inventory.py`

---

### Mock: Filesystem (tmp_path)

**What it replaces:** Real filesystem operations for reading Python source files and resolving module paths.

**Interface to mock:** Use pytest `tmp_path` fixture to create temporary directory structures with `.py` files. Create `pyproject.toml` files for config loading tests.

**Happy path setup:**
```python
# Create a package structure
(tmp_path / "src" / "foo").mkdir(parents=True)
(tmp_path / "src" / "foo" / "__init__.py").write_text("from .bar import MyClass\n")
(tmp_path / "src" / "foo" / "bar.py").write_text("class MyClass:\n    pass\n")
```

**Used by modules:** `import_check/inventory.py`, `import_check/checker.py`, `import_check/fixer.py`, `import_check/__init__.py`

---

### Mock: libcst parse/write

**What it replaces:** `libcst.parse_module()` and file write-back in fixer.

**Interface to mock:** For unit tests of individual transformers, use `libcst.parse_module(source_code)` directly on string inputs and assert on `modified_tree.code` output. For `apply_fixes` integration, use `tmp_path` with real files.

**Happy path:**
```python
import libcst as cst
tree = cst.parse_module("from src.old import foo\n")
# Apply transformer, check tree.code
```

**Error path:**
```python
# Unparseable file
cst.ParserSyntaxError  # raised on invalid Python syntax
```

**Used by modules:** `import_check/fixer.py`

---

## Per-Module Test Specifications

---

### `import_check/inventory.py` -- Symbol Inventory Builder

**Module purpose:** Builds symbol inventories from Python source files using AST analysis, supporting both current filesystem and historical git states.

**In scope:**
- Converting filesystem paths to dotted module paths (`_file_to_module_path`)
- Extracting top-level symbols (functions, classes, variables) from Python source (`_extract_symbols`)
- Building inventories from current filesystem files (`build_inventory`)
- Building inventories from git history via `git show` (`build_old_inventory`)
- Collecting Python files from configured source directories (`collect_python_files`)
- Getting changed files from git diff (`get_changed_files`)
- Filtering by exclude patterns (`_matches_any_pattern`)
- Skipping private symbols (leading underscore) except `__all__`

**Out of scope:**
- Diffing inventories (owned by `differ.py`)
- Configuration loading (owned by `__init__.py`)
- Import verification (owned by `checker.py`)

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Simple file to module path | `file_path="src/foo/bar.py", root=Path("/project")` | `"src.foo.bar"` |
| `__init__.py` to package path | `file_path="src/foo/__init__.py", root=Path("/project")` | `"src.foo"` |
| Nested module path | `file_path="src/db/minio/store.py", root=Path("/project")` | `"src.db.minio.store"` |
| Extract function symbol | Source: `"def my_func():\n    pass\n"` | `[SymbolInfo(name="my_func", symbol_type="function", ...)]` |
| Extract async function | Source: `"async def async_handler():\n    pass\n"` | `[SymbolInfo(name="async_handler", symbol_type="function", ...)]` |
| Extract class symbol | Source: `"class MyClass:\n    pass\n"` | `[SymbolInfo(name="MyClass", symbol_type="class", ...)]` |
| Extract variable (Assign) | Source: `"MAX_RETRIES = 3\n"` | `[SymbolInfo(name="MAX_RETRIES", symbol_type="variable", ...)]` |
| Extract variable (AnnAssign) | Source: `"timeout: int = 30\n"` | `[SymbolInfo(name="timeout", symbol_type="variable", ...)]` |
| Extract `__all__` | Source: `'__all__ = ["foo", "bar"]\n'` | `[SymbolInfo(name="__all__", symbol_type="variable", ...)]` |
| Multiple symbols in one file | Source with function + class + variable | List of 3 `SymbolInfo` entries with correct types |
| Build inventory from filesystem | Two `.py` files in `tmp_path` with known symbols | `SymbolInventory` dict mapping symbol names to `SymbolInfo` lists |
| Build old inventory from git | Mock `git show` returning source with function `foo` | Inventory contains `foo` with correct module path |
| Collect Python files | `tmp_path` with `src/a.py`, `src/b.py`, `src/__pycache__/c.py` | `["src/a.py", "src/b.py"]` (sorted, `__pycache__` excluded) |
| Get changed files | Mock `git diff` returning `"src/foo.py\nsrc/bar.py\nREADME.md\n"` | `["src/foo.py", "src/bar.py"]` (non-.py filtered out) |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| `SyntaxError` in `_extract_symbols` | Unparseable Python source string | Raises `SyntaxError` (caller handles) |
| File read failure in `build_inventory` | `OSError` reading a file | Logs WARNING, skips file, continues with remaining files |
| Syntax error in `build_inventory` | File contains invalid Python | Logs WARNING, skips file, continues with remaining files |
| Git show file not found | `subprocess` returns non-zero for `git show` | Logs DEBUG, skips file, continues with remaining files |
| Git diff failure | `subprocess` returns non-zero for `git diff --name-only` | Raises `RuntimeError` with stderr message |

#### Boundary conditions

- **Empty file list** to `build_inventory` -> returns empty `SymbolInventory` (`{}`)
- **Empty file list** to `build_old_inventory` -> returns empty `SymbolInventory` (`{}`)
- **Empty source string** to `_extract_symbols` -> returns empty list `[]`
- **File with only private symbols** (e.g., `_helper`, `_Config`) -> returns empty list (private symbols skipped)
- **File with only `__all__`** -> returns `[SymbolInfo(name="__all__", ...)]` (`__all__` is not private)
- **Root-level file** (`file_path="setup.py"`) to `_file_to_module_path` -> `"setup"`
- **Absolute path** to `_file_to_module_path` -> correctly made relative to root
- **No source directories exist** in `collect_python_files` -> returns empty list `[]`
- **All files excluded** by patterns in `collect_python_files` -> returns empty list `[]`
- **Git diff returns empty stdout** -> `get_changed_files` returns empty list `[]`
- **Multiple variables in one Assign** (e.g., `x = y = 5`) -> each `Name` target is extracted
- **Tuple unpacking Assign** (e.g., `a, b = 1, 2`) -> skipped (only `ast.Name` targets extracted)

#### Integration points

- Called by `__init__.py` functions: `fix()` calls `get_changed_files`, `build_old_inventory`, `build_inventory`, `collect_python_files`
- Called by `__init__.py` functions: `check()` calls `collect_python_files`
- Returns `SymbolInventory` consumed by `differ.diff_inventories()`
- Returns `list[str]` (file list) consumed by `fixer.apply_fixes()` and `checker.check_imports()`

#### Mocking strategy

- **`subprocess.run`**: Mock with `unittest.mock.patch("import_check.inventory.subprocess.run")` for all git commands. Return `CompletedProcess` objects with controlled `returncode`, `stdout`, `stderr`.
- **Filesystem**: Use `tmp_path` fixture with real files for `build_inventory` and `collect_python_files`. No need to mock `Path` operations.
- **`_extract_symbols`**: Test directly with source strings -- no mocking needed (pure function except for `ast.parse`).

#### Known test gaps

- **Large codebase performance** (REQ-901: 1000 files in under 30s) -- requires benchmark test, not a unit test. Note as out of scope for module tests.
- **Binary/non-UTF-8 files** -- behavior when encountering non-UTF-8 encoded `.py` files is not documented. The `OSError` handler should catch this but it is an edge case worth noting.

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only -- do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files, Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

### `import_check/differ.py` -- Inventory Differ

**Module purpose:** Compares old and new SymbolInventory objects to detect symbol migrations (moves, renames, splits, merges) between refactor states, producing a list of MigrationEntry records.

**In scope:**
- Detecting moves: same symbol name, different module path (`_detect_moves`)
- Detecting renames: symbol disappeared, new symbol appeared in same file with same type and close line number (`_detect_renames`)
- Detecting splits: symbols from one old file scattered across multiple new files (`_detect_splits_and_merges`)
- Detecting merges: symbols from multiple old files consolidated into one new file (`_detect_splits_and_merges`)
- Orchestrating all detection phases with deduplication (`diff_inventories`)
- Handling ambiguous cases (multiple departures/arrivals) conservatively

**Out of scope:**
- Building inventories (owned by `inventory.py`)
- Applying fixes based on migration map (owned by `fixer.py`)
- Configuration loading (owned by `__init__.py`)

#### Happy path scenarios

| Scenario | Input (old inventory, new inventory) | Expected output |
|----------|--------------------------------------|-----------------|
| Simple move | old: `{"foo": [SymbolInfo(name="foo", module_path="src.old", ...)]}`; new: `{"foo": [SymbolInfo(name="foo", module_path="src.new", ...)]}` | `[MigrationEntry(old_module="src.old", old_name="foo", new_module="src.new", new_name="foo", migration_type="move")]` |
| Simple rename | old: `{"old_name": [SymbolInfo(name="old_name", module_path="src.mod", file_path="src/mod.py", lineno=10, symbol_type="function")]}`; new: `{"new_name": [SymbolInfo(name="new_name", module_path="src.mod", file_path="src/mod.py", lineno=10, symbol_type="function")]}` | `[MigrationEntry(old_module="src.mod", old_name="old_name", new_module="src.mod", new_name="new_name", migration_type="rename")]` |
| File split | old: `{"func_a": [SI(mod="src.big", file="src/big.py")], "func_b": [SI(mod="src.big", file="src/big.py")]}`; new: `{"func_a": [SI(mod="src.part_a", file="src/part_a.py")], "func_b": [SI(mod="src.part_b", file="src/part_b.py")]}` | Two MigrationEntry with `migration_type="split"` |
| File merge | old: `{"func_a": [SI(mod="src.a", file="src/a.py")], "func_b": [SI(mod="src.b", file="src/b.py")]}`; new: `{"func_a": [SI(mod="src.combined", file="src/combined.py")], "func_b": [SI(mod="src.combined", file="src/combined.py")]}` | Two MigrationEntry with `migration_type="merge"` |
| No changes | old and new are identical inventories | Empty list `[]` |
| Symbol only in old (deleted) | old has `"foo"`, new does not | Empty list `[]` (deletion is not a migration) |
| Symbol only in new (added) | new has `"bar"`, old does not | Empty list `[]` (addition is not a migration) |
| Move + rename in same diff | old: `{"old_fn": [SI(mod="src.a")]}`, new: `{"old_fn": [SI(mod="src.b")]}` plus separately `{"x": [SI(mod="src.c", lineno=5)]}` disappears and `{"y": [SI(mod="src.c", lineno=5)]}` appears | One move entry + one rename entry |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| (No exceptions documented) | `diff_inventories` is a pure function operating on dicts | Returns empty list on empty/trivial inputs -- no exceptions raised |

#### Boundary conditions

- **Both inventories empty** -> returns `[]`
- **One inventory empty, other non-empty** -> returns `[]` (all symbols are pure additions or deletions, not migrations)
- **Symbol exists in multiple modules in old** (ambiguous departure, e.g., `foo` in `src.a` and `src.b`) with single arrival -> skipped as ambiguous (conservative)
- **Symbol exists in multiple modules in new** (ambiguous arrival) -> skipped as ambiguous
- **Rename candidate outside proximity threshold** (line numbers differ by more than 30) -> not matched as rename
- **Rename candidate with different symbol_type** (e.g., function disappeared, class appeared at same line) -> not matched as rename
- **Rename candidate with different file_path** -> not matched as rename
- **Already-matched symbols** passed to `_detect_renames` -> skipped (no double-counting)
- **Already-matched symbols** passed to `_detect_splits_and_merges` -> skipped
- **Single file to single file move** (not a split) -> detected as move, not split
- **Deduplication**: a migration should not appear both as a split and a merge entry

#### Integration points

- Receives `SymbolInventory` from `inventory.build_inventory()` and `inventory.build_old_inventory()`
- Returns `list[MigrationEntry]` consumed by `fixer.apply_fixes()`
- Called by `__init__.fix()` as the diffing step between inventory and fix

#### Mocking strategy

- **No mocking needed**: `diff_inventories` and its internal helpers are pure functions operating on `SymbolInventory` dicts and `SymbolInfo` dataclasses. Construct test inventories directly in test code.
- Build helper factory functions for creating `SymbolInfo` instances with defaults to reduce test boilerplate.

#### Known test gaps

- **Rename heuristic accuracy**: The proximity-based rename detection is inherently heuristic. Edge cases where a symbol is both moved and renamed simultaneously are not detectable by the differ and will become residual errors for the checker. This is by design per the spec.
- **Large-scale split/merge**: Testing splits/merges with many symbols (>10) across many files has combinatorial complexity. Tests cover 2-3 symbol cases; larger cases are assumed to follow the same logic.

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only -- do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files, Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

### `import_check/checker.py` -- Smoke Test Checker

**Module purpose:** Parses Python files with `ast`, verifies every import resolves to an existing module and that the imported symbol is defined in that module. Optionally detects encapsulation violations.

**In scope:**
- Resolving dotted module paths to filesystem paths (`_resolve_module_to_file`)
- Extracting all import statements from Python source including nested (lazy, TYPE_CHECKING, try/except) (`_extract_imports`)
- Checking whether a symbol is defined in a module file via AST (`_check_symbol_defined`)
- Detecting encapsulation violations (`_check_encapsulation`)
- Orchestrating all checks across a file list (`check_imports`)
- Skipping stdlib and third-party imports
- Zero-runtime-cost verification (no `importlib.import_module()`)

**Out of scope:**
- Fixing imports (owned by `fixer.py`)
- Building symbol inventories (owned by `inventory.py`)
- Configuration loading (owned by `__init__.py`)

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Resolve module to .py file | `module="src.foo.bar", root` where `src/foo/bar.py` exists | `Path("src/foo/bar.py")` |
| Resolve module to package | `module="src.foo", root` where `src/foo/__init__.py` exists | `Path("src/foo/__init__.py")` |
| Extract `from X import Y` | Source: `"from src.foo import bar\n"` | `[("src.foo", "bar", 1)]` |
| Extract `import X` | Source: `"import src.foo\n"` | `[("src.foo", "", 1)]` |
| Extract aliased import | Source: `"from src.foo import bar as baz\n"` | `[("src.foo", "bar", 1)]` (alias ignored for checking) |
| Extract lazy import (inside function) | Source: `"def f():\n    from src.foo import bar\n"` | `[("src.foo", "bar", 2)]` |
| Extract TYPE_CHECKING import | Source: `"from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from src.foo import bar\n"` | Includes `("src.foo", "bar", 3)` |
| Extract try/except import | Source: `"try:\n    from src.foo import bar\nexcept ImportError:\n    pass\n"` | Includes `("src.foo", "bar", 2)` |
| Symbol defined as function | Module file contains `def bar(): pass` | `_check_symbol_defined` returns `True` |
| Symbol defined as class | Module file contains `class Bar: pass` | Returns `True` |
| Symbol defined as Assign | Module file contains `bar = 42` | Returns `True` |
| Symbol defined as AnnAssign | Module file contains `bar: int = 42` | Returns `True` |
| Symbol re-exported via import | Module file contains `from .internal import bar` | Returns `True` |
| Symbol in `__all__` | Module file contains `__all__ = ["bar"]` | Returns `True` |
| Symbol defined via tuple unpack | Module file contains `bar, baz = 1, 2` | Returns `True` for `bar` |
| No encapsulation violation (package import) | `from src.foo import bar` where `src/foo/__init__.py` exists | No `ImportError` returned |
| Encapsulation violation detected | External file imports `from src.foo.internal import helper` where `src/foo/__init__.py` exists | `ImportError` with `ENCAPSULATION_VIOLATION` type |
| Intra-package import allowed | File inside `src/foo/` imports `from src.foo.internal import helper` | No violation (intra-package) |
| check_imports clean run | All imports resolve correctly | Returns empty list `[]` |
| check_imports with errors | Some imports point to missing modules | Returns list of `ImportError` records |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| `MODULE_NOT_FOUND` | Import references a module path that does not exist as a file | Returns `ImportError` with `error_type=MODULE_NOT_FOUND` |
| `SYMBOL_NOT_DEFINED` | `from X import Y` where `X` exists but `Y` is not defined in it | Returns `ImportError` with `error_type=SYMBOL_NOT_DEFINED` |
| `ENCAPSULATION_VIOLATION` | External import from internal module bypassing `__init__.py` | Returns `ImportError` with `error_type=ENCAPSULATION_VIOLATION` |
| File read failure | `OSError` reading a target file | Logs error, continues checking remaining files |
| Syntax error in source | File with invalid Python syntax passed to `_extract_imports` | Returns empty list `[]` (graceful degradation) |
| Syntax/OS error in `_check_symbol_defined` | Target module file is unreadable or unparseable | Returns `False` (symbol considered not defined) |

#### Boundary conditions

- **Empty file list** to `check_imports` -> returns empty list `[]`
- **Empty source string** to `_extract_imports` -> returns empty list `[]`
- **Relative imports** (`from .foo import bar`) in `_extract_imports` -> skipped (not checked)
- **Stdlib imports** (e.g., `import os`, `from pathlib import Path`) -> skipped by `check_imports`
- **Third-party imports** (e.g., `import numpy`) -> skipped by `check_imports`
- **Module resolves to neither .py file nor `__init__.py`** -> `_resolve_module_to_file` returns `None`
- **Single-component module path** (e.g., `import foo`) to `_check_encapsulation` -> returns `None` (need at least 2 components)
- **Package without `__init__.py`** -> `_check_encapsulation` returns `None` (no public surface to violate)
- **`encapsulation_check=False`** in config -> encapsulation violations not checked
- **`config=None`** passed to `check_imports` -> uses default `ImportCheckConfig()`
- **`import *`** (`from X import *`) in `_extract_imports` -> extracted with `name="*"` per `ast.alias`

#### Integration points

- Called by `__init__.check()` and `__init__.run()` with file list from `inventory.collect_python_files()`
- Receives `ImportCheckConfig` for encapsulation toggle
- Returns `list[ImportError]` consumed by `__init__.py` for output formatting
- `_resolve_module_to_file` operates on the real filesystem under `root`

#### Mocking strategy

- **Filesystem**: Use `tmp_path` fixture to create package structures with `__init__.py`, module files, and known symbol definitions. No subprocess mocking needed.
- **`_extract_imports`**: Test directly with source strings -- pure function on AST.
- **`_check_symbol_defined`**: Test with real temporary files containing known definitions.
- **`_check_encapsulation`**: Test with `tmp_path` package structures (needs `__init__.py` to exist).
- **`_is_stdlib_or_thirdparty`**: May need to account for its behavior -- it checks `sys.stdlib_module_names` and filesystem existence. Test by ensuring project-local modules are detected correctly in `tmp_path`.

#### Known test gaps

- **`sys.stdlib_module_names` availability**: On Python < 3.10, the fallback hardcoded list is used. Testing both paths requires mocking `sys.stdlib_module_names` existence, which is fragile.
- **Deeply nested conditional imports**: While `ast.walk()` captures all nesting depths, extremely complex nesting (e.g., imports inside list comprehensions) is not explicitly tested.

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only -- do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files, Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

### `import_check/fixer.py` -- Import Fixer

**Module purpose:** Rewrites broken imports using libcst CST transformers based on a migration map, handling import statements, string-based references (mock.patch, importlib.import_module), and `__all__` list updates while preserving formatting.

**In scope:**
- `ImportRewriter`: rewriting `from X import Y` and `import X` statements
- `StringRefRewriter`: rewriting string arguments in `mock.patch()` and `importlib.import_module()` calls
- `StringRefRewriter`: single-assignment dataflow for variable-held string paths within function scope
- `AllListRewriter`: updating `__all__` list entries for renamed symbols
- `apply_fixes`: orchestrating all three transformers across target files
- Preserving formatting, comments, and whitespace (libcst guarantee)
- Handling aliased imports (preserving `as` clause)
- Handling star imports (`from X import *`)
- Graceful handling of unparseable files

**Out of scope:**
- Building migration maps (owned by `differ.py`)
- Building inventories (owned by `inventory.py`)
- Import verification (owned by `checker.py`)
- Dynamic string construction (f-strings) -- flagged but not fixed

#### Happy path scenarios -- ImportRewriter

| Scenario | Source input | Migration map | Expected output |
|----------|------------|---------------|-----------------|
| Simple `from` import move | `from src.old import foo` | `MigrationEntry(old_module="src.old", old_name="foo", new_module="src.new", new_name="foo", migration_type="move")` | `from src.new import foo` |
| Symbol rename | `from src.mod import old_name` | `MigrationEntry(old_module="src.mod", old_name="old_name", new_module="src.mod", new_name="new_name", migration_type="rename")` | `from src.mod import new_name` |
| Move + rename | `from src.old import old_fn` | `MigrationEntry(old_module="src.old", old_name="old_fn", new_module="src.new", new_name="new_fn", ...)` | `from src.new import new_fn` |
| Aliased import preserved | `from src.old import foo as f` | Move `foo` from `src.old` to `src.new` | `from src.new import foo as f` |
| Bare `import X` rewrite | `import src.old.utils` | Module `src.old.utils` moved to `src.new.helpers` | `import src.new.helpers` |
| Star import module rewrite | `from src.old import *` | Module `src.old` has entries moving to `src.new` | `from src.new import *` |
| Multiple names, one moved | `from src.old import foo, bar` | Only `foo` moved to `src.new` | Module updated to `src.new` with both names, or split (depends on implementation) |

#### Happy path scenarios -- StringRefRewriter

| Scenario | Source input | Migration map | Expected output |
|----------|------------|---------------|-----------------|
| mock.patch string | `mock.patch("src.old.module.MyClass")` | Move `MyClass` from `src.old.module` to `src.new.module` | `mock.patch("src.new.module.MyClass")` |
| importlib.import_module | `importlib.import_module("src.old.utils")` | Module `src.old.utils` moved to `src.new.helpers` | `importlib.import_module("src.new.helpers")` |
| unittest.mock.patch | `unittest.mock.patch("src.old.Cls")` | Move of `src.old.Cls` | `unittest.mock.patch("src.new.Cls")` |
| Variable-held path (dataflow) | `def f():\n    path = "src.old.module.Sym"\n    mock.patch(path)` | Move of `src.old.module.Sym` | Assignment rewritten to `path = "src.new.module.Sym"` |
| Prefix match | `mock.patch("src.old.module.Cls.method")` | Move `Cls` from `src.old.module` to `src.new.module` | `mock.patch("src.new.module.Cls.method")` |
| Quote style preserved | `mock.patch('src.old.Foo')` (single quotes) | Move of `src.old.Foo` | `mock.patch('src.new.Foo')` (single quotes preserved) |

#### Happy path scenarios -- AllListRewriter

| Scenario | Source input | Migration map | Expected output |
|----------|------------|---------------|-----------------|
| Simple rename in `__all__` | `__all__ = ["old_name", "other"]` | Rename `old_name` to `new_name` | `__all__ = ["new_name", "other"]` |
| No rename (move only) | `__all__ = ["foo"]` | Move `foo` (name unchanged) | `__all__ = ["foo"]` (unchanged) |
| Multiple renames | `__all__ = ["a", "b"]` | Both renamed | Both updated |

#### Happy path scenarios -- apply_fixes

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Fix single file | One `.py` file with broken import, matching migration | `FixResult(files_modified=["path"], fixes_applied=1, ...)` |
| No matches in file | File imports do not match migration map | `FixResult(files_modified=[], fixes_applied=0)` |
| Empty migration map | Any files | `FixResult(files_modified=[], fixes_applied=0)` |
| Multiple files fixed | Three files with broken imports | `FixResult` with all three in `files_modified`, correct total `fixes_applied` |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| libcst parse failure | File with syntax errors passed to `_apply_transformers_to_file` | Error message added to `FixResult.errors`, file skipped, processing continues |
| File read failure | `OSError` reading target file | Error message added to `FixResult.errors`, file skipped |
| File write failure | `OSError` writing modified file | Error message added to `FixResult.errors`, returns `(False, errors)` |
| Transformer exception | Unexpected error in a CST transformer | Error logged, processing continues with remaining transformers |
| Non-existent target file | File path in `target_files` does not exist | Added to `FixResult.skipped` with "File not found" message |
| Non-.py file | Non-Python file in target list | Silently skipped (`.py` suffix check) |

#### Boundary conditions

- **Empty migration map** to `apply_fixes` -> returns default `FixResult()` immediately
- **Empty target files list** -> returns default `FixResult()`
- **Migration map with no name change** (pure move, `old_name == new_name`) -> `AllListRewriter` makes no changes
- **Import with no module** (edge case in libcst) -> `leave_ImportFrom` returns unchanged
- **Triple-quoted string in mock.patch** -> quote style preserved
- **ConcatenatedString** in mock.patch -> only handled if both parts are simple strings
- **Variable assigned in one function, used in another** -> NOT rewritten (scope isolation)
- **Nested function scope** -> scope tracking resets at depth 0

#### Integration points

- Receives `list[MigrationEntry]` from `differ.diff_inventories()`
- Receives `list[str]` (target files) from `inventory.collect_python_files()`
- Receives `Path` (root) from `__init__.fix()`
- Returns `FixResult` to `__init__.fix()`
- Depends on `libcst` for CST parsing and transformation

#### Mocking strategy

- **Individual transformer tests**: Use `libcst.parse_module(source)` directly on string inputs, apply transformer, assert on `modified_tree.code`. No file I/O mocking needed.
- **`apply_fixes` tests**: Use `tmp_path` with real `.py` files. Write known source content, run `apply_fixes`, read files back and assert content.
- **Transformer construction**: Test `_build_import_rewriter`, `_build_string_ref_rewriter`, `_build_all_rewriter` to verify they return correct transformer types.

#### Known test gaps

- **Complex multi-name imports**: When `from X import a, b, c` has names pointing to different new modules, the behavior is complex (module-level vs. name-level rewriting). Edge cases with divergent module targets are difficult to specify exhaustively.
- **Deeply nested string references**: String references inside list comprehensions, decorator arguments, or other complex expressions are not explicitly tested beyond the documented patterns.

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only -- do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files, Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

### `import_check/__init__.py` -- Public API Facade

**Module purpose:** Provides three public entry points (`fix()`, `check()`, `run()`) that orchestrate the full pipeline, plus configuration loading from `pyproject.toml` with programmatic overrides.

**In scope:**
- `_load_config`: loading configuration with resolution order defaults < pyproject.toml < overrides
- `_setup_logging`: configuring the `import_check` logger
- `fix()`: inventory + diff + fixer pipeline
- `check()`: collect files + checker pipeline
- `run()`: fix then check pipeline
- Config precedence: defaults < pyproject.toml `[tool.import_check]` < keyword overrides

**Out of scope:**
- Internal implementation of inventory building, diffing, fixing, checking (delegated to submodules)
- CLI argument parsing (owned by `__main__.py`)
- Schema definitions (owned by `schemas.py`)

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| `_load_config` with no pyproject.toml | `root` with no `pyproject.toml` | `ImportCheckConfig` with all defaults |
| `_load_config` with pyproject.toml | `pyproject.toml` contains `[tool.import_check]\nsource_dirs = ["lib"]` | `ImportCheckConfig(source_dirs=["lib"], ...)` |
| `_load_config` with overrides | `root` + `source_dirs=["custom"]` override | Override takes precedence over pyproject.toml |
| `_load_config` ignores unknown keys | `pyproject.toml` has `unknown_key = "value"` | Unknown key ignored, valid fields loaded |
| `fix()` with no changes | No changed files from git diff | Returns `FixResult()` with zero fixes |
| `fix()` with migrations | Changed files with moved symbols | Returns `FixResult` with `files_modified` and `fixes_applied` |
| `fix()` with no migrations | Changed files but symbols at same locations | Returns `FixResult()` with zero fixes |
| `check()` clean | All imports resolve | Returns empty `list[ImportError]` |
| `check()` with errors | Broken imports in files | Returns non-empty `list[ImportError]` |
| `run()` pipeline | Fix + check combined | Returns `RunResult(fix_result=..., remaining_errors=...)` |
| `fix()` default root | `root=None` | Uses `Path.cwd()` |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| Malformed pyproject.toml | `pyproject.toml` exists but contains invalid TOML | Logs WARNING, uses defaults |
| Missing `[tool]` section | `pyproject.toml` exists but has no `[tool]` section | Uses defaults (`.get("tool", {})` returns empty dict) |
| `RuntimeError` from git | `get_changed_files` raises `RuntimeError` | Propagates to caller |

#### Boundary conditions

- **`root` as string** to `fix()` / `check()` / `run()` -> converted to `Path` and resolved
- **`root` as `Path`** -> resolved with `.resolve()`
- **`root=None`** -> defaults to `Path.cwd().resolve()`
- **Empty `source_dirs`** after config loading -> `collect_python_files` returns empty list
- **Override with `None` value** -> should not override (only valid fields applied)
- **pyproject.toml with `[tool]` but no `[tool.import_check]`** -> empty dict, defaults used
- **Repeated `_setup_logging` calls** -> no duplicate handlers (handler check in implementation)

#### Integration points

- Calls `inventory.get_changed_files(config.git_ref, root)` -> receives `list[str]`
- Calls `inventory.build_old_inventory(changed_files, config.git_ref)` -> receives `SymbolInventory`
- Calls `inventory.build_inventory(changed_files, root)` -> receives `SymbolInventory`
- Calls `differ.diff_inventories(old_inv, new_inv)` -> receives `list[MigrationEntry]`
- Calls `inventory.collect_python_files(config.source_dirs, root, config.exclude_patterns)` -> receives `list[str]`
- Calls `fixer.apply_fixes(migration_map, all_files, root)` -> receives `FixResult`
- Calls `checker.check_imports(all_files, root, config)` -> receives `list[ImportError]`

#### Mocking strategy

- **Submodule calls**: Mock `import_check.inventory`, `import_check.differ`, `import_check.fixer`, `import_check.checker` at the module level. Each mock returns controlled return values matching the Phase 0 contract types.
- **pyproject.toml**: Use `tmp_path` with real `pyproject.toml` files for `_load_config` tests. Use `tomllib`/`tomli` to verify the parsing path.
- **Logging**: Use `caplog` fixture to verify log messages at expected levels.

#### Known test gaps

- **`tomllib` vs `tomli` fallback**: The import fallback (`import tomllib` -> `import tomli`) is environment-dependent. Testing both paths requires mocking the import mechanism, which is fragile.
- **Full pipeline end-to-end**: Testing `fix()` and `run()` with real git operations is an integration test concern, not a unit test concern for this module.

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only -- do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files, Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

### `import_check/__main__.py` -- CLI Entry Point

**Module purpose:** CLI entry point for `python -m import_check [fix|check|run]` with argument parsing, output formatting (human/JSON), and exit code management.

**In scope:**
- `_build_parser`: argument parser construction with subcommands and flags
- `main()`: CLI dispatch to `fix()`, `check()`, `run()` with config overrides
- `_format_output`: routing to human or JSON formatters
- `_format_json`: JSON serialization of `FixResult`, `list[ImportError]`, `RunResult`
- `_format_human`: human-readable text output
- Exit codes: 0 on success, 1 on remaining import errors
- Default subcommand: `run` when no subcommand provided

**Out of scope:**
- Actual fix/check/run logic (delegated to `import_check` facade)
- Configuration loading from pyproject.toml (owned by `__init__.py._load_config`)

#### Happy path scenarios

| Scenario | CLI args | Expected behavior |
|----------|---------|-------------------|
| Default (no subcommand) | `[]` | Runs `run()`, formats output, exit 0 if no errors |
| Explicit `fix` | `["fix"]` | Calls `fix()`, formats FixResult, exit 0 |
| Explicit `check` | `["check"]` | Calls `check()`, exit 0 if no errors, exit 1 if errors |
| Explicit `run` | `["run"]` | Calls `run()`, exit 0 if no errors, exit 1 if errors |
| JSON format | `["check", "--format", "json"]` | Output is valid JSON parseable by `json.loads()` |
| Human format (default) | `["check"]` | Output is human-readable text |
| Source dirs override | `["fix", "--source-dirs", "lib", "src"]` | `source_dirs=["lib", "src"]` passed to fix() |
| Exclude override | `["fix", "--exclude", "test_*"]` | `exclude_patterns=["test_*"]` passed |
| Git ref override | `["check", "--git-ref", "HEAD~2"]` | `git_ref="HEAD~2"` passed |
| No encapsulation check | `["check", "--no-encapsulation-check"]` | `encapsulation_check=False` passed |
| Log level override | `["run", "--log-level", "DEBUG"]` | `log_level="DEBUG"` passed |
| Root override | `["fix", "--root", "/tmp/project"]` | Root resolved to `/tmp/project` |

#### Happy path scenarios -- Output formatting

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Format FixResult (human) | `FixResult(files_modified=["a.py"], fixes_applied=3)` | `"Fix: 3 imports rewritten across 1 files"` |
| Format FixResult (JSON) | Same FixResult | Valid JSON with `files_modified`, `fixes_applied`, `errors`, `skipped` fields |
| Format empty check (human) | Empty list `[]` | `"Check: all imports OK"` |
| Format check errors (human) | List of ImportError | `"Check: N import errors found"` with per-error lines |
| Format check errors (JSON) | List of ImportError | JSON array of error objects with `file_path`, `lineno`, `module`, `name`, `error_type`, `message` |
| Format RunResult (human) | RunResult with fix + no remaining errors | Fix summary + `"All imports OK after fix."` |
| Format RunResult (JSON) | RunResult | JSON with `fix_result` and `remaining_errors` fields |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| Invalid subcommand | `["invalid"]` | argparse prints error and exits (standard argparse behavior) |
| Invalid format | `["check", "--format", "xml"]` | argparse rejects (choices are "human" and "json") |
| Invalid log level | `["run", "--log-level", "TRACE"]` | argparse rejects (choices are DEBUG, INFO, ERROR) |

#### Boundary conditions

- **No arguments** -> `command` defaults to `None`, treated as `"run"`
- **`--source-dirs` not provided** -> `args.source_dirs` is `None`, not included in overrides
- **`--exclude` not provided** -> `args.exclude` is `None`, not included in overrides
- **FixResult with zero fixes** -> human format shows `"Fix: 0 imports rewritten across 0 files"`
- **RunResult with remaining errors** -> exit code 1
- **RunResult with no remaining errors** -> exit code 0
- **`fix` subcommand** -> always exit 0 (fix does not have error-based exit codes)
- **Unknown result type** in `_format_json` -> falls back to `json.dumps(str(result))`
- **Unknown result type** in `_format_human` -> falls back to `str(result)`

#### Integration points

- Calls `import_check.fix(root, **config_overrides)` -> receives `FixResult`
- Calls `import_check.check(root, **config_overrides)` -> receives `list[ImportError]`
- Calls `import_check.run(root, **config_overrides)` -> receives `RunResult`
- Uses `import_check.schemas.FixResult`, `ImportError`, `RunResult` for isinstance checks in formatters

#### Mocking strategy

- **`import_check.fix`, `import_check.check`, `import_check.run`**: Mock all three facade functions. Return controlled `FixResult`, `list[ImportError]`, and `RunResult` instances.
- **argparse**: Test `_build_parser().parse_args(args_list)` directly with controlled argument lists.
- **Output capture**: Use `capsys` fixture to capture `print()` output and verify formatting.
- **Exit code**: Call `main()` with mocked facade functions and assert return value.

#### Known test gaps

- **`sys.argv` manipulation**: Testing the full `python -m import_check` invocation requires subprocess execution, which is an integration test concern.
- **Encoding issues in JSON output**: Non-ASCII characters in file paths or error messages are not explicitly tested.

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only -- do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files, Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

### `import_check/schemas.py` -- Shared Data Structures

**Module purpose:** Defines all shared typed contracts (dataclasses, enums, type aliases) used across the import_check pipeline modules.

**In scope:**
- `SymbolInfo` dataclass (frozen): immutability, field types, field values
- `SymbolInventory` type alias: structure validation
- `MigrationEntry` dataclass (frozen): immutability, field types
- `ImportErrorType` enum: value correctness
- `ImportError` dataclass (frozen): field types
- `FixResult` dataclass: mutable fields with defaults
- `RunResult` dataclass: composition of FixResult + errors
- `ImportCheckConfig` dataclass: default values, field types

**Out of scope:**
- Business logic using these types (owned by other modules)
- Configuration loading (owned by `__init__.py`)

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Create SymbolInfo | `SymbolInfo(name="foo", module_path="src.bar", file_path="src/bar.py", lineno=10, symbol_type="function")` | Frozen dataclass with all fields accessible |
| Create MigrationEntry | All fields provided | Frozen dataclass, `migration_type` is a string literal |
| Create ImportError | All fields including `ImportErrorType` enum | Frozen dataclass |
| FixResult defaults | `FixResult()` | `files_modified=[], fixes_applied=0, errors=[], skipped=[]` |
| RunResult creation | `RunResult(fix_result=FixResult())` | `remaining_errors` defaults to `[]` |
| ImportCheckConfig defaults | `ImportCheckConfig()` | `source_dirs=["src","server","config"], exclude_patterns=[".venv","__pycache__","node_modules"], git_ref="HEAD", encapsulation_check=True, output_format="human", log_level="INFO"` |
| ImportErrorType values | All enum members | `MODULE_NOT_FOUND`, `SYMBOL_NOT_DEFINED`, `ENCAPSULATION_VIOLATION` |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| Frozen dataclass mutation | Attempting to set field on `SymbolInfo` | Raises `FrozenInstanceError` |
| Frozen dataclass mutation | Attempting to set field on `MigrationEntry` | Raises `FrozenInstanceError` |
| Frozen dataclass mutation | Attempting to set field on `ImportError` | Raises `FrozenInstanceError` |

#### Boundary conditions

- **SymbolInventory with duplicate names**: Multiple `SymbolInfo` entries under the same key in the dict (expected pattern for symbols in multiple modules)
- **FixResult accumulation**: `fixes_applied` can be incremented; `files_modified` and `errors` lists can be appended to (mutable dataclass)
- **`ImportCheckConfig.root`**: Defaults to `Path.cwd` (a callable, not a static value)
- **`output_format` Literal type**: Only `"human"` or `"json"` are valid at the type level

#### Integration points

- Imported by all other modules: `inventory.py`, `differ.py`, `checker.py`, `fixer.py`, `__init__.py`, `__main__.py`
- `SymbolInventory` type alias used as the primary data structure flowing between inventory and differ
- `MigrationEntry` flows from differ to fixer
- `ImportError` flows from checker to facade and CLI
- `FixResult` flows from fixer to facade and CLI
- `RunResult` flows from facade to CLI

#### Mocking strategy

- **No mocking needed**: All types are pure dataclasses/enums. Test by direct construction and assertion. No external dependencies.

#### Known test gaps

- None. Schema types are fully testable without external dependencies.

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only -- do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files, Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

---

## Integration Test Specifications

---

### Integration: Fix-then-Check Happy Path

**Scenario:** A symbol is moved from one module to another. The fix stage rewrites all imports, and the check stage verifies no broken imports remain.

**Entry point:** `import_check.run(root=tmp_path)`

**Setup:**
1. Create `tmp_path` with:
   - `src/old_module.py` containing `def moved_func(): pass`
   - `src/new_module.py` containing `def moved_func(): pass` (the function was moved here)
   - `src/consumer.py` containing `from src.old_module import moved_func`
   - `pyproject.toml` with `[tool.import_check]\nsource_dirs = ["src"]`
2. Initialize a git repo in `tmp_path`, commit the "before" state (with `moved_func` in `old_module`), then modify to the "after" state.

**Flow:**
1. `run()` calls `fix(root=tmp_path)`
2. `fix()` calls `inventory.get_changed_files("HEAD", tmp_path)` -> returns changed files
3. `fix()` builds old and new inventories, diffs them -> migration map with one move entry
4. `fix()` calls `fixer.apply_fixes()` -> rewrites `consumer.py`
5. `run()` calls `check(root=tmp_path)`
6. `check()` verifies all imports resolve -> returns empty error list

**What to assert:**
- `RunResult.fix_result.fixes_applied >= 1`
- `RunResult.fix_result.files_modified` contains `"src/consumer.py"`
- `RunResult.remaining_errors` is empty
- `src/consumer.py` content now reads `from src.new_module import moved_func`

**Mocks required:** Real git repo in `tmp_path` (no subprocess mocking for integration test)

---

### Integration: Fix Leaves Residual Errors

**Scenario:** A symbol is deleted (not moved) from a module. The fix stage finds no migration for it. The check stage reports it as a broken import.

**Entry point:** `import_check.run(root=tmp_path)`

**Setup:**
1. Create `tmp_path` with:
   - `src/module.py` that no longer defines `deleted_func`
   - `src/consumer.py` containing `from src.module import deleted_func`
2. Git repo where `src/module.py` previously defined `deleted_func`.

**Flow:**
1. `fix()` builds inventories, diffs them -> `deleted_func` only in old, not in new -> no migration entry (deletion, not move)
2. `fix()` returns `FixResult` with zero fixes
3. `check()` finds `from src.module import deleted_func` -> `deleted_func` not defined -> `SYMBOL_NOT_DEFINED` error

**What to assert:**
- `RunResult.fix_result.fixes_applied == 0`
- `RunResult.remaining_errors` has one entry with `error_type == ImportErrorType.SYMBOL_NOT_DEFINED`
- `RunResult.remaining_errors[0].name == "deleted_func"`

**Mocks required:** Real git repo in `tmp_path`

---

### Integration: Encapsulation Violation Reported but Not Fixed

**Scenario:** An external file imports from an internal module. The checker reports it as an encapsulation violation but does not auto-fix it.

**Entry point:** `import_check.check(root=tmp_path, encapsulation_check=True)`

**Setup:**
1. Create `tmp_path` with:
   - `src/pkg/__init__.py` (empty or with re-exports)
   - `src/pkg/internal.py` containing `def helper(): pass`
   - `src/consumer.py` containing `from src.pkg.internal import helper`

**Flow:**
1. `check()` collects all `.py` files
2. For `src/consumer.py`, finds `from src.pkg.internal import helper`
3. `_check_encapsulation` detects external caller importing internal module
4. Reports `ENCAPSULATION_VIOLATION`

**What to assert:**
- Result contains one `ImportError` with `error_type == ImportErrorType.ENCAPSULATION_VIOLATION`
- `src/consumer.py` file content is NOT modified (report-only)

**Mocks required:** Filesystem via `tmp_path` only

---

## FR-to-Test Traceability Matrix

| REQ/FR | Acceptance Criteria Summary | Module Test | Integration Test |
|--------|----------------------------|-------------|-----------------|
| REQ-101 / FR-101 | Build symbol inventory from ast (FunctionDef) | `inventory` -- happy path (extract function symbol) | -- |
| REQ-101 / FR-102 | Build symbol inventory from ast (ClassDef) | `inventory` -- happy path (extract class symbol) | -- |
| REQ-101 / FR-103 | Build symbol inventory from ast (Assign) | `inventory` -- happy path (extract variable) | -- |
| FR-104 | Record symbol name + module path | `inventory` -- happy path, `schemas` -- SymbolInfo creation | -- |
| REQ-103 / FR-105 | Build "before" inventory from git ref | `inventory` -- happy path (build_old_inventory) | integration_happy_path |
| REQ-105 / FR-106 | Build "after" inventory from filesystem | `inventory` -- happy path (build_inventory) | integration_happy_path |
| REQ-107 / FR-107 | Only scan changed files from git diff | `inventory` -- happy path (get_changed_files) | integration_happy_path |
| FR-108 | Respect source_dirs and exclude_patterns | `inventory` -- happy path (collect_python_files), boundary (exclusions) | -- |
| REQ-109 / FR-201 | Detect moves (same name, different path) | `differ` -- happy path (simple move) | integration_happy_path |
| FR-202 | Detect renames (different name, same area) | `differ` -- happy path (simple rename) | -- |
| FR-203 | Detect splits (one file to many) | `differ` -- happy path (file split) | -- |
| FR-204 | Detect merges (many files to one) | `differ` -- happy path (file merge) | -- |
| FR-205 | Produce structured migration map | `differ` -- happy path (diff_inventories) | integration_happy_path |
| REQ-201 / FR-301 | Rewrite `from X import Y` | `fixer` -- ImportRewriter happy path | integration_happy_path |
| FR-302 | Rewrite `import X` | `fixer` -- ImportRewriter (bare import rewrite) | -- |
| FR-303 | Rewrite aliased imports | `fixer` -- ImportRewriter (aliased import preserved) | -- |
| FR-304 / REQ-209 | Update `__all__` list entries | `fixer` -- AllListRewriter happy path | -- |
| FR-305 / REQ-211 | Rewrite mock.patch() strings | `fixer` -- StringRefRewriter (mock.patch) | -- |
| FR-306 / REQ-211 | Rewrite importlib.import_module() strings | `fixer` -- StringRefRewriter (importlib) | -- |
| FR-307 / REQ-213 | Single-assignment dataflow | `fixer` -- StringRefRewriter (variable-held path) | -- |
| FR-308 / REQ-215 | Preserve formatting (libcst) | `fixer` -- all transformer tests verify output formatting | -- |
| FR-309 / REQ-207 | Handle lazy imports (inside functions) | `checker` -- happy path (extract lazy import) | -- |
| FR-310 / REQ-207 | Handle TYPE_CHECKING imports | `checker` -- happy path (extract TYPE_CHECKING import) | -- |
| FR-311 / REQ-207 | Handle conditional imports (try/except) | `checker` -- happy path (extract try/except import) | -- |
| FR-312 / REQ-217 | Flag dynamic string construction | Known gap -- fixer does not yet emit DYNAMIC_UNFIXABLE warnings in tests |
| REQ-301 / FR-401 | Verify every import resolves | `checker` -- check_imports happy path and error scenarios | integration_residual_errors |
| FR-402 | Verify target module exists on filesystem | `checker` -- _resolve_module_to_file happy path | integration_residual_errors |
| FR-403 | Verify imported symbol is defined | `checker` -- _check_symbol_defined happy path | integration_residual_errors |
| FR-404 / REQ-305 | Detect encapsulation violations | `checker` -- _check_encapsulation happy path | integration_encapsulation |
| FR-405 / REQ-307 | Encapsulation violations report-only | `checker` -- encapsulation test verifies no file modification | integration_encapsulation |
| FR-406 | Structured error list at ERROR log level | `checker` -- error scenarios produce ImportError records | integration_residual_errors |
| FR-407 / REQ-303 | No importlib.import_module() in smoke test | `checker` -- all tests use ast.parse only (design constraint) | -- |
| FR-501 / REQ-401 | Expose fix() API | `__init__` -- fix() happy path | integration_happy_path |
| FR-502 / REQ-401 | Expose check() API | `__init__` -- check() happy path | integration_encapsulation |
| FR-503 / REQ-401 | Expose run() API | `__init__` -- run() happy path | integration_happy_path |
| FR-504 | Logging with configurable level | `__init__` -- _setup_logging test | -- |
| FR-601 / REQ-403 | CLI entry point via python -m import_check | `__main__` -- main() dispatch | -- |
| FR-602 / REQ-403 | Subcommands: fix, check, run | `__main__` -- _build_parser tests for each subcommand | -- |
| FR-603 / REQ-403 | CLI flags override pyproject.toml | `__main__` -- config_overrides dict construction | -- |
| FR-604 / REQ-405 | Human output format | `__main__` -- _format_human tests | -- |
| FR-605 / REQ-405 | JSON output format | `__main__` -- _format_json tests (valid JSON) | -- |
| FR-701 / REQ-503 | source_dirs config | `__init__` -- _load_config, `schemas` -- ImportCheckConfig defaults | -- |
| FR-702 / REQ-503 | exclude_patterns config | `__init__` -- _load_config, `schemas` -- ImportCheckConfig defaults | -- |
| FR-703 / REQ-503 | git_ref config | `__init__` -- _load_config default "HEAD" | -- |
| FR-704 / REQ-503 | encapsulation_check config | `__init__` -- _load_config, `checker` -- toggle behavior | -- |
| FR-705 / REQ-503 | output_format config | `schemas` -- ImportCheckConfig defaults | -- |
| FR-706 / REQ-503 | log_level config | `__init__` -- _setup_logging | -- |
| FR-707 / REQ-501 | Config from pyproject.toml | `__init__` -- _load_config with pyproject.toml | -- |
| FR-708 / REQ-505 | CLI flags override pyproject.toml | `__main__` -- config override precedence | -- |
| FR-709 / REQ-505 | Programmatic kwargs override everything | `__init__` -- _load_config with overrides | -- |
| REQ-411 | Exit code 0 on success, 1 on errors | `__main__` -- main() return values | -- |
| REQ-507 | Validate config, fail fast | Known gap -- validation not implemented in current facade (no `ConfigError` raised) |
| REQ-901 | Performance: 1000 files in 30s | Known gap -- benchmark test, out of scope for unit tests |
| REQ-903 | Generic portability (any git project) | integration_happy_path (works on fresh tmp_path repo) | -- |
| REQ-905 | Only libcst as external dep | Not testable via module tests -- verify via dependency manifest |
| REQ-907 | All params externalized to config | `schemas` -- ImportCheckConfig field verification | -- |
| REQ-909 | Configurable logging verbosity | `__init__` -- _setup_logging tests | -- |
| REQ-111 | Graceful handling of parse errors | `inventory` -- error scenarios (syntax error skipped) | -- |

### Known Traceability Gaps

| REQ/FR | Reason |
|--------|--------|
| FR-312 / REQ-217 | Dynamic string flagging (DYNAMIC_UNFIXABLE) is specified but the current implementation does not emit this warning type. Test should verify the behavior if/when implemented. |
| REQ-507 | Config validation with fail-fast behavior is specified but `_load_config` in `__init__.py` does not currently raise `ConfigError`. Tests should verify the graceful behavior that exists (WARNING log on bad TOML). |
| REQ-901 | Performance requirement -- benchmark testing is out of scope for unit/module tests. |
| REQ-905 | Dependency constraint -- verified by inspecting `pyproject.toml`, not by code test. |
