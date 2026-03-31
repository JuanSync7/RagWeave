# @summary
# Symbol inventory builder using AST analysis.
# Scans Python source files and extracts top-level symbol definitions
# (functions, classes, module-level variables) into a SymbolInventory.
# Supports building inventories from current files or from git history.
# Exports: build_inventory, build_old_inventory, collect_python_files, get_changed_files
# Deps: ast, subprocess, fnmatch, pathlib, import_check.schemas
# @end-summary

"""Symbol inventory builder using AST analysis.

Scans Python source files and extracts all top-level symbol definitions
(functions, classes, module-level variables) into a SymbolInventory.
Can build inventories from current files or from git history.
"""

from __future__ import annotations

import ast
import fnmatch
import logging
import subprocess
from pathlib import Path

from .schemas import SymbolInfo, SymbolInventory

logger = logging.getLogger("import_check")


def _file_to_module_path(file_path: str, root: Path) -> str:
    """Convert a filesystem path to a dotted Python module path.

    Args:
        file_path: Path to a .py file, relative to root.
        root: Project root directory.

    Returns:
        Dotted module path (e.g., "src.retrieval.engine").
        __init__.py files map to the package path (e.g., "src.retrieval").
    """
    rel = Path(file_path)

    # If file_path is absolute, make it relative to root
    if rel.is_absolute():
        rel = rel.relative_to(root)

    # Strip the .py suffix
    parts = list(rel.parts)

    # Handle __init__.py -> package path (drop the filename)
    if parts and parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        # Strip .py from the last component
        if parts:
            parts[-1] = parts[-1].removesuffix(".py")

    return ".".join(parts)


def _extract_symbols(source: str, file_path: str, module_path: str) -> list[SymbolInfo]:
    """Parse Python source and extract all top-level symbol definitions.

    Extracts FunctionDef, AsyncFunctionDef, ClassDef at module level,
    and simple Assign/AnnAssign targets (Name nodes) at module level.
    Skips private symbols (leading underscore) unless they are __all__.

    Args:
        source: Python source code string.
        file_path: Filesystem path (for SymbolInfo.file_path).
        module_path: Dotted module path (for SymbolInfo.module_path).

    Returns:
        List of SymbolInfo for each discovered symbol.

    Raises:
        SyntaxError: If source cannot be parsed by ast.parse().
    """
    tree = ast.parse(source, filename=file_path)
    symbols: list[SymbolInfo] = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = node.name
            if _is_private(name):
                continue
            symbols.append(SymbolInfo(
                name=name,
                module_path=module_path,
                file_path=file_path,
                lineno=node.lineno,
                symbol_type="function",
            ))

        elif isinstance(node, ast.ClassDef):
            name = node.name
            if _is_private(name):
                continue
            symbols.append(SymbolInfo(
                name=name,
                module_path=module_path,
                file_path=file_path,
                lineno=node.lineno,
                symbol_type="class",
            ))

        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    name = target.id
                    if _is_private(name):
                        continue
                    symbols.append(SymbolInfo(
                        name=name,
                        module_path=module_path,
                        file_path=file_path,
                        lineno=node.lineno,
                        symbol_type="variable",
                    ))

        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                name = node.target.id
                if _is_private(name):
                    continue
                symbols.append(SymbolInfo(
                    name=name,
                    module_path=module_path,
                    file_path=file_path,
                    lineno=node.lineno,
                    symbol_type="variable",
                ))

    return symbols


def _is_private(name: str) -> bool:
    """Check if a symbol name is private (leading underscore).

    The special name ``__all__`` is not considered private.
    """
    if name == "__all__":
        return False
    return name.startswith("_")


def build_inventory(files: list[str], root: Path) -> SymbolInventory:
    """Build a symbol inventory from current filesystem files.

    Reads each file, parses with ast, and collects all top-level symbols.
    Files that fail to parse are logged at WARNING and skipped.

    Args:
        files: List of Python file paths (relative to root).
        root: Project root directory.

    Returns:
        SymbolInventory mapping symbol names to their locations.
    """
    inventory: SymbolInventory = {}

    for file_path in files:
        full_path = root / file_path
        try:
            source = full_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Cannot read %s: %s", file_path, exc)
            continue

        module_path = _file_to_module_path(file_path, root)

        try:
            symbols = _extract_symbols(source, file_path, module_path)
        except SyntaxError as exc:
            logger.warning("Syntax error parsing %s: %s", file_path, exc)
            continue

        for sym in symbols:
            inventory.setdefault(sym.name, []).append(sym)

    return inventory


def build_old_inventory(files: list[str], git_ref: str) -> SymbolInventory:
    """Build a symbol inventory from a previous git state.

    Uses ``git show <ref>:<file>`` to retrieve file contents at the given
    ref. Files that do not exist at the ref are silently skipped.

    Args:
        files: List of Python file paths to retrieve from git.
        git_ref: Git reference (commit SHA, branch, tag, "HEAD").

    Returns:
        SymbolInventory for the historical state.

    Raises:
        RuntimeError: If git is not available or the ref is invalid.
    """
    inventory: SymbolInventory = {}

    for file_path in files:
        result = subprocess.run(
            ["git", "show", f"{git_ref}:{file_path}"],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            # File does not exist at this ref — silently skip
            logger.debug(
                "File %s not found at ref %s, skipping", file_path, git_ref
            )
            continue

        source = result.stdout

        # Derive module path from the file path (root is implicit in git paths)
        module_path = _file_to_module_path(file_path, Path("."))

        try:
            symbols = _extract_symbols(source, file_path, module_path)
        except SyntaxError as exc:
            logger.warning(
                "Syntax error parsing %s at ref %s: %s", file_path, git_ref, exc
            )
            continue

        for sym in symbols:
            inventory.setdefault(sym.name, []).append(sym)

    return inventory


def collect_python_files(
    source_dirs: list[str],
    root: Path,
    exclude_patterns: list[str],
) -> list[str]:
    """Collect all Python files from the specified source directories.

    Walks each source_dir under root, collecting .py files while
    excluding paths matching any of the exclude_patterns (glob-style).

    Args:
        source_dirs: Directory names to scan (relative to root).
        root: Project root directory.
        exclude_patterns: Glob patterns for paths to exclude.

    Returns:
        Sorted list of Python file paths relative to root.
    """
    collected: list[str] = []

    for source_dir in source_dirs:
        dir_path = root / source_dir
        if not dir_path.is_dir():
            logger.debug("Source directory %s does not exist, skipping", source_dir)
            continue

        for py_file in dir_path.rglob("*.py"):
            rel_path = py_file.relative_to(root)
            rel_str = str(rel_path)

            if _matches_any_pattern(rel_str, exclude_patterns):
                continue

            collected.append(rel_str)

    return sorted(collected)


def _matches_any_pattern(path: str, patterns: list[str]) -> bool:
    """Check if a path matches any of the given fnmatch-style patterns.

    Checks each component of the path against each pattern as well as
    the full path, so a pattern like ``__pycache__`` matches any path
    containing a ``__pycache__`` directory segment.
    """
    parts = Path(path).parts
    for pattern in patterns:
        # Match against the full relative path
        if fnmatch.fnmatch(path, pattern):
            return True
        # Match against individual path components (e.g., "__pycache__")
        for part in parts:
            if fnmatch.fnmatch(part, pattern):
                return True
    return False


def get_changed_files(git_ref: str, root: Path) -> list[str]:
    """Get list of Python files changed since the given git ref.

    Uses ``git diff --name-only <ref>`` to find changed files, then
    filters to .py files only.

    Args:
        git_ref: Git reference to diff against.
        root: Project root directory.

    Returns:
        List of changed .py file paths relative to root.

    Raises:
        RuntimeError: If git is not available.
    """
    result = subprocess.run(
        ["git", "diff", "--name-only", git_ref],
        capture_output=True,
        text=True,
        cwd=str(root),
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"git diff failed (exit {result.returncode}): {result.stderr.strip()}"
        )

    changed: list[str] = []
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if line and line.endswith(".py"):
            changed.append(line)

    return changed
