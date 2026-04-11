# @summary
# Import checker: parses Python files with ast, verifies every import resolves
# to an existing module and that the imported symbol is defined in that module.
# Optionally detects encapsulation violations (importing internal modules
# instead of going through __init__.py).
# Exports: check_imports, _resolve_module_to_file, _extract_imports,
#          _resolve_relative_import, _check_symbol_defined, _check_encapsulation
# Deps: ast, pathlib, logging, import_check.schemas
# @end-summary
"""Import checker module.

Walks Python source files, parses imports using ``ast``, and verifies that:

1. Each imported module resolves to an existing ``.py`` file or package
   ``__init__.py`` under the project root.
2. For ``from X import Y`` statements, the symbol *Y* is actually defined
   (or re-exported) in module *X*.
3. (Optional) External callers do not reach into internal package modules,
   bypassing the package's ``__init__.py`` public surface.

All parsing is AST-based -- no runtime imports are executed.
"""

from __future__ import annotations

import ast
import logging
import sys
from pathlib import Path

from .schemas import ImportCheckConfig, ImportError, ImportErrorType

logger = logging.getLogger("import_check")

# ---------------------------------------------------------------------------
# Stdlib module cache
# ---------------------------------------------------------------------------

_STDLIB_MODULES: frozenset[str] | None = None


def _stdlib_module_names() -> frozenset[str]:
    """Return a cached frozenset of known standard-library top-level module names."""
    global _STDLIB_MODULES  # noqa: PLW0603
    if _STDLIB_MODULES is not None:
        return _STDLIB_MODULES

    # Python 3.10+ exposes sys.stdlib_module_names
    if hasattr(sys, "stdlib_module_names"):
        _STDLIB_MODULES = frozenset(sys.stdlib_module_names)
    else:
        # Fallback: a conservative list covering the most common stdlib packages.
        _STDLIB_MODULES = frozenset(
            {
                "abc", "argparse", "ast", "asyncio", "atexit", "base64",
                "bisect", "builtins", "calendar", "cmath", "codecs",
                "collections", "colorsys", "compileall", "concurrent",
                "configparser", "contextlib", "copy", "csv", "ctypes",
                "dataclasses", "datetime", "decimal", "difflib", "dis",
                "distutils", "doctest", "email", "encodings", "enum",
                "errno", "faulthandler", "filecmp", "fileinput", "fnmatch",
                "fractions", "ftplib", "functools", "gc", "getpass",
                "gettext", "glob", "gzip", "hashlib", "heapq", "hmac",
                "html", "http", "idlelib", "imaplib", "importlib",
                "inspect", "io", "ipaddress", "itertools", "json",
                "keyword", "lib2to3", "linecache", "locale", "logging",
                "lzma", "mailbox", "marshal", "math", "mimetypes",
                "multiprocessing", "numbers", "operator", "os", "pathlib",
                "pdb", "pickle", "pkgutil", "platform", "plistlib",
                "poplib", "posixpath", "pprint", "profile", "pstats",
                "py_compile", "pyclbr", "pydoc", "queue", "quopri",
                "random", "re", "readline", "reprlib", "resource",
                "rlcompleter", "runpy", "sched", "secrets", "select",
                "shelve", "shlex", "shutil", "signal", "site", "smtplib",
                "socket", "socketserver", "sqlite3", "ssl", "stat",
                "statistics", "string", "struct", "subprocess", "sunau",
                "symtable", "sys", "sysconfig", "syslog", "tabnanny",
                "tarfile", "tempfile", "test", "textwrap", "threading",
                "time", "timeit", "tkinter", "token", "tokenize", "trace",
                "traceback", "tracemalloc", "tty", "turtle", "types",
                "typing", "unicodedata", "unittest", "urllib", "uuid",
                "venv", "warnings", "wave", "weakref", "webbrowser",
                "wsgiref", "xml", "xmlrpc", "zipapp", "zipfile",
                "zipimport", "zlib", "_thread", "__future__",
            }
        )
    return _STDLIB_MODULES


def _is_stdlib_or_thirdparty(module: str, root: Path) -> bool:
    """Return True if *module* is a stdlib or third-party import (not project-local).

    A module is considered project-local if its top-level component corresponds
    to an existing directory or ``.py`` file under *root*.
    """
    top = module.split(".")[0]

    # Known stdlib
    if top in _stdlib_module_names():
        return True

    # Check if a matching directory or file exists in the project root
    if (root / top).is_dir() or (root / f"{top}.py").is_file():
        return False

    # Not found locally -- assume third-party
    return True


# ---------------------------------------------------------------------------
# Per-invocation caches (cleared at start of each check_imports call)
# ---------------------------------------------------------------------------

_getattr_cache: dict[Path, bool] = {}
_stub_symbol_cache: dict[tuple[Path, str], bool] = {}


def _clear_caches() -> None:
    """Clear per-invocation caches for __getattr__ and stub results."""
    _getattr_cache.clear()
    _stub_symbol_cache.clear()


def _has_dynamic_getattr(module_file: Path) -> bool:
    """Check if a module defines __getattr__ at the module level.

    Only inspects top-level FunctionDef nodes — nested __getattr__
    inside classes or functions does not count.

    Results are cached per file path within a single check_imports invocation.

    Args:
        module_file: Path to the module source file.

    Returns:
        True if a module-level def __getattr__ is found.
    """
    if module_file in _getattr_cache:
        return _getattr_cache[module_file]

    result = False
    try:
        source = module_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(module_file))
    except (SyntaxError, OSError):
        _getattr_cache[module_file] = False
        return False

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "__getattr__":
                result = True
                break

    _getattr_cache[module_file] = result
    return result


def _resolve_stub_file(module_file: Path) -> Path | None:
    """Locate the co-located .pyi stub file for a module.

    For module.py, checks for module.pyi in the same directory.
    For package/__init__.py, checks for package/__init__.pyi.

    Args:
        module_file: Path to the .py module file.

    Returns:
        Path to the .pyi stub file if it exists, None otherwise.
    """
    stub_path = module_file.with_suffix(".pyi")
    if stub_path.is_file():
        return stub_path
    return None


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def _resolve_module_to_file(module: str, root: Path) -> Path | None:
    """Resolve a dotted module path to a filesystem path.

    Checks for both ``module/as/path.py`` and ``module/as/path/__init__.py``.
    Returns ``None`` if the module cannot be resolved to an existing file.

    Args:
        module: Dotted module path (e.g., ``src.retrieval.engine``).
        root: Project root directory.

    Returns:
        Path to the source file, or ``None`` if not found.
    """
    parts = module.split(".")
    relative = Path(*parts)

    # Try as a .py file first: root/src/retrieval/engine.py
    candidate_file = root / relative.with_suffix(".py")
    if candidate_file.is_file():
        return candidate_file

    # Try as a package: root/src/retrieval/engine/__init__.py
    candidate_pkg = root / relative / "__init__.py"
    if candidate_pkg.is_file():
        return candidate_pkg

    return None


def _extract_imports(source: str) -> list[tuple[str | None, str, int, int]]:
    """Parse Python source and extract all import statements.

    Uses ``ast.walk()`` so that imports at *any* nesting depth are captured:
    lazy imports inside functions, ``TYPE_CHECKING`` blocks, ``try/except``, etc.

    Handles:

    - ``from X import Y``       -> ``(X, Y, lineno, 0)``
    - ``from X import Y as Z``  -> ``(X, Y, lineno, 0)``
    - ``from .X import Y``      -> ``(X, Y, lineno, 1)``
    - ``from . import Y``       -> ``(None, Y, lineno, 1)``
    - ``import X``              -> ``(X, "", lineno, 0)``
    - ``import X as Z``         -> ``(X, "", lineno, 0)``

    The 4th element is the import level: 0 for absolute imports, >0 for
    relative imports (number of leading dots).

    Args:
        source: Python source code string.

    Returns:
        List of ``(module, name, lineno, level)`` tuples. For relative imports,
        ``module`` may be ``None`` (e.g., ``from . import foo``).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    results: list[tuple[str | None, str, int, int]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            level = node.level or 0
            module_name = node.module  # May be None for bare relative imports

            if level > 0:
                # Relative import — include with its level
                for alias in node.names:
                    results.append((module_name, alias.name, node.lineno, level))
            else:
                # Absolute import — module_name must be present
                if not module_name:
                    continue
                for alias in node.names:
                    results.append((module_name, alias.name, node.lineno, 0))

        elif isinstance(node, ast.Import):
            for alias in node.names:
                results.append((alias.name, "", node.lineno, 0))

    return results


def _resolve_relative_import(
    module: str | None,
    level: int,
    file_path: str,
    root: Path,
) -> str | None:
    """Resolve a relative import to an absolute dotted module path.

    Algorithm:
    1. Convert file_path to package components (strip .py suffix, split on /).
    2. The importing file's package = all components except the last (filename).
    3. Ascend `level` components. If this goes above root (empty), return None.
    4. Append `module` (if not None) to get the absolute path.

    For bare relative imports (``from . import foo``), the resolved module is
    the package itself — the caller checks ``foo`` as a symbol or submodule.

    Only resolves within standard packages (directories with __init__.py).
    Returns None if resolution fails.

    Args:
        module: Relative module name (e.g., "foo" from "from .foo import bar").
            None for bare relative imports ("from . import bar").
        level: Number of dots (1 for ".", 2 for "..", etc.).
        file_path: Path of importing file, relative to root.
        root: Project root directory.

    Returns:
        Absolute dotted module path, or None if resolution fails.
    """
    # Convert file_path to parts: "src/pkg/sub/module.py" -> ["src", "pkg", "sub", "module"]
    parts = file_path.replace("\\", "/").removesuffix(".py").split("/")

    # Handle __init__.py: "src/pkg/__init__.py" -> package is ["src", "pkg"]
    if parts and parts[-1] == "__init__":
        pkg_parts = parts[:-1]
    else:
        # Regular file: package is all but the last component
        pkg_parts = parts[:-1]

    # Ascend `level` components from the package
    # level=1 means current package (no ascent needed for the first dot)
    ascend = level - 1
    if ascend > len(pkg_parts):
        # Would go above project root
        logger.debug(
            "relative import resolution failed: level=%d exceeds package depth for %s",
            level, file_path,
        )
        return None

    if ascend > 0:
        base_parts = pkg_parts[:-ascend]
    else:
        base_parts = pkg_parts

    # Verify the base is a valid package (has __init__.py)
    if base_parts:
        init_path = root / Path(*base_parts) / "__init__.py"
        if not init_path.is_file():
            logger.debug(
                "relative import resolution failed: no __init__.py at %s",
                init_path,
            )
            return None

    # Append module if present
    if module:
        result_parts = base_parts + module.split(".")
    else:
        result_parts = base_parts

    if not result_parts:
        return None

    return ".".join(result_parts)


def _check_symbol_defined(
    module_file: Path, symbol_name: str, config: ImportCheckConfig | None = None,
) -> bool:
    """Check if a symbol is defined in the given module file.

    Parses the file with ``ast`` and checks top-level statements for:

    - ``FunctionDef`` / ``AsyncFunctionDef`` with matching name
    - ``ClassDef`` with matching name
    - ``Assign`` where any ``Name`` target matches
    - ``AnnAssign`` where the target ``Name`` matches
    - ``ImportFrom`` that re-exports the symbol (``from X import symbol_name``)

    Also checks ``__all__`` if present -- if ``symbol_name`` appears in the
    ``__all__`` list literal, the symbol is considered defined.

    Fallback chain (in order) when the AST walk above finds nothing:

    1. Sub-module fallback — if *module_file* is a package's ``__init__.py``
       and ``symbol_name`` names an actual sub-module file
       (``package/symbol_name.py`` or ``package/symbol_name/__init__.py``),
       consider it defined. This is the ``from package import submodule``
       idiom — valid Python that the AST walk misses because sub-modules
       aren't AST nodes in the package's ``__init__.py``.
    2. ``__getattr__`` — if the module defines a top-level ``__getattr__``
       function, assume dynamic name resolution may provide the symbol.
    3. ``.pyi`` stub — if a co-located type stub exists, re-run the AST
       symbol check against the stub file.

    Args:
        module_file: Path to the module source file.
        symbol_name: Name to look for.

    Returns:
        ``True`` if the symbol is defined, re-exported, or satisfied by
        one of the fallbacks above.
    """
    try:
        source = module_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(module_file))
    except (SyntaxError, OSError):
        return False

    for node in tree.body:
        # FunctionDef / AsyncFunctionDef
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == symbol_name:
                return True

        # ClassDef
        elif isinstance(node, ast.ClassDef):
            if node.name == symbol_name:
                return True

        # Assign -- check all Name targets (handles `x = ...` and `x, y = ...`)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == symbol_name:
                    return True
                # Handle tuple unpacking: x, y = ...
                if isinstance(target, ast.Tuple):
                    for elt in target.elts:
                        if isinstance(elt, ast.Name) and elt.id == symbol_name:
                            return True

        # AnnAssign -- e.g. `x: int = 5`
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == symbol_name:
                return True

        # ImportFrom re-export -- `from X import symbol_name`
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                exported_name = alias.asname if alias.asname else alias.name
                if exported_name == symbol_name:
                    return True

        # Import re-export -- `import X as symbol_name`
        elif isinstance(node, ast.Import):
            for alias in node.names:
                exported_name = alias.asname if alias.asname else alias.name
                if exported_name == symbol_name:
                    return True

    # Check __all__ if present
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    # Try to extract list literal values
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and elt.value == symbol_name:
                                return True

    # --- Fallback chain ---

    # Step 1: sub-module fallback. When the AST walk fails to find the
    # symbol and *module_file* is a package's __init__.py, the name may
    # actually be a sub-module file inside that package rather than a
    # symbol defined in __init__. This is the `from package import
    # submodule` idiom — valid Python that the checks above miss because
    # sub-modules aren't AST nodes in __init__.py.
    if module_file.name == "__init__.py":
        package_dir = module_file.parent
        # `package/submodule.py`
        if (package_dir / f"{symbol_name}.py").is_file():
            return True
        # `package/submodule/__init__.py` (sub-package)
        if (package_dir / symbol_name / "__init__.py").is_file():
            return True

    # Step 2: __getattr__ check
    _config = config or ImportCheckConfig()
    if _config.check_getattr and _has_dynamic_getattr(module_file):
        logger.debug(
            "symbol '%s' assumed present via __getattr__ in %s",
            symbol_name, module_file,
        )
        return True

    # Step 3: .pyi stub fallback
    if _config.check_stubs:
        stub_file = _resolve_stub_file(module_file)
        if stub_file is not None:
            cache_key = (stub_file, symbol_name)
            if cache_key in _stub_symbol_cache:
                return _stub_symbol_cache[cache_key]
            try:
                stub_source = stub_file.read_text(encoding="utf-8")
                stub_tree = ast.parse(stub_source, filename=str(stub_file))
            except (SyntaxError, OSError) as exc:
                logger.warning("Failed to parse stub file %s: %s", stub_file, exc)
                _stub_symbol_cache[cache_key] = False
                return False
            # Check stub for the symbol using the same AST logic
            for node in stub_tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name == symbol_name:
                        _stub_symbol_cache[cache_key] = True
                        return True
                elif isinstance(node, ast.ClassDef):
                    if node.name == symbol_name:
                        _stub_symbol_cache[cache_key] = True
                        return True
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == symbol_name:
                            _stub_symbol_cache[cache_key] = True
                            return True
                elif isinstance(node, ast.AnnAssign):
                    if isinstance(node.target, ast.Name) and node.target.id == symbol_name:
                        _stub_symbol_cache[cache_key] = True
                        return True
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        exported = alias.asname if alias.asname else alias.name
                        if exported == symbol_name:
                            _stub_symbol_cache[cache_key] = True
                            return True
            _stub_symbol_cache[cache_key] = False

    return False


def _check_encapsulation(
    module: str, file_path: str, root: Path
) -> ImportError | None:
    """Check if an import violates encapsulation boundaries.

    An encapsulation violation occurs when an external caller imports from an
    internal module instead of from the package's ``__init__.py``.

    Only applies to imports that cross package boundaries -- intra-package
    imports (where the importing file is inside the target package) are allowed.

    Args:
        module: Dotted module path being imported (e.g., ``src.retrieval.engine``).
        file_path: File containing the import statement (relative to *root*).
        root: Project root directory.

    Returns:
        ``ImportError`` if encapsulation is violated, ``None`` otherwise.
    """
    parts = module.split(".")

    # Only relevant for sub-module imports (need at least package.module)
    if len(parts) < 2:
        return None

    # Determine the package portion (all but the last component)
    package_parts = parts[:-1]
    package_module = ".".join(package_parts)

    # Check if the target resolves to a non-__init__ file
    resolved = _resolve_module_to_file(module, root)
    if resolved is None:
        return None

    # If the module resolves to an __init__.py, this is already a package import
    if resolved.name == "__init__.py":
        return None

    # Determine if the importing file is inside the target package
    importer_path = Path(file_path)
    package_dir = root / Path(*package_parts)

    # Resolve to absolute for reliable comparison
    try:
        importer_abs = (root / importer_path).resolve()
        package_abs = package_dir.resolve()
    except (OSError, ValueError):
        return None

    # If the importer is inside the package directory, this is an intra-package
    # import and is allowed.
    try:
        importer_abs.relative_to(package_abs)
        return None  # Intra-package -- allowed
    except ValueError:
        pass  # External caller -- check further

    # External caller is importing a non-__init__ internal module.
    # Check whether the package has an __init__.py (if it doesn't, there's
    # no public surface to import from, so skip the warning).
    package_init = package_dir / "__init__.py"
    if not package_init.is_file():
        return None

    return ImportError(
        file_path=file_path,
        lineno=0,  # Lineno filled by caller
        module=module,
        name="",
        error_type=ImportErrorType.ENCAPSULATION_VIOLATION,
        message=(
            f"Encapsulation violation: external import from internal module "
            f"'{module}' — consider importing from '{package_module}' instead"
        ),
    )


def _is_suppressed(source: str, lineno: int) -> bool:
    """Check if a source line contains the import_check suppression marker.

    Looks for ``# import_check: ignore`` anywhere on the source line at
    the given line number. The marker can appear at any position on the line.

    This function is always active — no configuration toggle required.
    Follows the same convention as ``# noqa`` and ``# type: ignore``.

    Args:
        source: Full source text of the file.
        lineno: 1-based line number to check.

    Returns:
        True if the line contains ``# import_check: ignore``.
    """
    lines = source.splitlines()
    if lineno < 1 or lineno > len(lines):
        return False
    return "# import_check: ignore" in lines[lineno - 1]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


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
       -> ``.pyi`` stub definition.
    3. If ``config.encapsulation_check`` is ``True``, flags imports that bypass
       ``__init__.py`` to reach internal modules directly.

    Enhanced behavior:

    - Relative imports are resolved to absolute paths before verification.
      Unresolvable relative imports are skipped with DEBUG log.
    - Imports on lines containing ``# import_check: ignore`` are skipped
      before verification and logged at DEBUG level.
    - Symbol verification uses the fallback chain controlled by
      ``config.check_getattr`` and ``config.check_stubs``.
    - Per-invocation caches are cleared at the start of each call.

    Args:
        files: List of Python file paths to check (relative to *root*).
        root: Project root directory.
        config: Optional configuration. Uses defaults if ``None``.

    Returns:
        List of ``ImportError`` records. Empty if all imports are clean.
    """
    if config is None:
        config = ImportCheckConfig()

    root = root.resolve()
    errors: list[ImportError] = []

    # Clear per-invocation caches (REQ-333)
    _clear_caches()

    for file_path in files:
        full_path = root / file_path
        try:
            source = full_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.error("IMPORT_ERROR: %s:0 — cannot read file: %s", file_path, exc)
            continue

        imports = _extract_imports(source)

        for module, name, lineno, level in imports:
            # Filter suppressed imports (REQ-335, REQ-337, REQ-339)
            if _is_suppressed(source, lineno):
                logger.debug(
                    "SUPPRESSED: %s:%d — %s.%s (# import_check: ignore)",
                    file_path, lineno, module or "", name,
                )
                continue

            # Resolve relative imports to absolute paths (REQ-313, REQ-315)
            if level > 0:
                resolved_module = _resolve_relative_import(
                    module, level, file_path, root,
                )
                if resolved_module is None:
                    logger.debug(
                        "skipping unresolvable relative import: %s:%d level=%d module=%s",
                        file_path, lineno, level, module,
                    )
                    continue
                module = resolved_module

            # Skip stdlib and third-party imports
            if module is None:
                continue
            if _is_stdlib_or_thirdparty(module, root):
                continue

            # 1. Resolve module to file
            resolved = _resolve_module_to_file(module, root)
            if resolved is None:
                err = ImportError(
                    file_path=file_path,
                    lineno=lineno,
                    module=module,
                    name=name,
                    error_type=ImportErrorType.MODULE_NOT_FOUND,
                    message=f"Module '{module}' not found",
                )
                errors.append(err)
                logger.error(
                    "IMPORT_ERROR: %s:%d — %s", file_path, lineno, err.message
                )
                continue

            # 2. Check symbol is defined (only for `from X import Y`)
            if name:
                if not _check_symbol_defined(resolved, name, config):
                    err = ImportError(
                        file_path=file_path,
                        lineno=lineno,
                        module=module,
                        name=name,
                        error_type=ImportErrorType.SYMBOL_NOT_DEFINED,
                        message=(
                            f"Symbol '{name}' not defined in module '{module}'"
                        ),
                    )
                    errors.append(err)
                    logger.error(
                        "IMPORT_ERROR: %s:%d — %s",
                        file_path,
                        lineno,
                        err.message,
                    )

            # 3. Encapsulation check
            if config.encapsulation_check:
                enc_err = _check_encapsulation(module, file_path, root)
                if enc_err is not None:
                    # Fill in the lineno from the actual import statement
                    enc_err = ImportError(
                        file_path=enc_err.file_path,
                        lineno=lineno,
                        module=enc_err.module,
                        name=name,
                        error_type=enc_err.error_type,
                        message=enc_err.message,
                    )
                    errors.append(enc_err)
                    logger.error(
                        "IMPORT_ERROR: %s:%d — %s",
                        file_path,
                        lineno,
                        enc_err.message,
                    )

    return errors
