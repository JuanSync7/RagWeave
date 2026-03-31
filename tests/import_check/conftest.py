"""Conftest for import_check tests.

Resolves namespace collision: tests/import_check/ (with __init__.py)
shadows the real import_check/ package at the project root.

The solution is to manipulate sys.modules and sys.path so that
``from import_check.checker import ...`` resolves to the project-root
package, not to this test directory.

This conftest runs before pytest collects test modules in this directory.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_REAL_PKG_DIR = _PROJECT_ROOT / "import_check"

# Ensure project root is in sys.path
_root_str = str(_PROJECT_ROOT)
if _root_str not in sys.path:
    sys.path.insert(0, _root_str)

# The critical fix: register all import_check submodules from the real
# package directory so that test files can do ``from import_check.checker import ...``.
# We do NOT touch the top-level ``import_check`` entry in sys.modules
# (that would break pytest's own collection), but we pre-load the submodules.
for _name in ("schemas", "checker", "fixer", "inventory", "differ"):
    _mod_key = f"import_check.{_name}"
    if _mod_key in sys.modules:
        continue
    _mod_file = _REAL_PKG_DIR / f"{_name}.py"
    if not _mod_file.is_file():
        continue
    _spec = importlib.util.spec_from_file_location(_mod_key, str(_mod_file))
    if _spec and _spec.loader:
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules[_mod_key] = _mod
        try:
            _spec.loader.exec_module(_mod)
        except Exception:
            # Non-fatal: some submodules may have unresolved deps (e.g., inventory
            # needs subprocess mocking). Only checker, fixer, schemas are needed here.
            del sys.modules[_mod_key]
