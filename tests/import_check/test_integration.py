"""Integration tests for import_check tool.

These tests create real mini Python projects in tmp_path with actual files,
a real git repo (for the "before" state), and run the full pipelines.

Tests cover:
- Fix-then-check happy path (moved symbol -> fix rewrites -> check passes)
- Residual errors (deleted symbol -> no fix available -> check reports error)
- Encapsulation violation (external import of internal module -> check reports it)
"""

from __future__ import annotations

import importlib
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Resolve the real import_check package (not the tests/import_check/ shadow).
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_REAL_PKG_DIR = _PROJECT_ROOT / "import_check"


def _load_real_module(name: str, file_path: Path, search_paths: list[str] | None = None):
    """Load a module by explicit file path into a private namespace."""
    spec = importlib.util.spec_from_file_location(
        name, str(file_path),
        submodule_search_locations=search_paths,
    )
    mod = importlib.util.module_from_spec(spec)
    if search_paths:
        mod.__path__ = search_paths
    # Temporarily register so relative imports inside the module work.
    _prev = sys.modules.get(name)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        # Restore previous registration so pytest collection isn't broken.
        if _prev is not None:
            sys.modules[name] = _prev
        else:
            sys.modules.pop(name, None)
    return mod


# Force-load the real import_check package.
_real_ic = _load_real_module(
    "import_check",
    _REAL_PKG_DIR / "__init__.py",
    [str(_REAL_PKG_DIR)],
)

_fix_real = _real_ic.fix
_check_real = _real_ic.check
_run_real = _real_ic.run


def _with_real_ic(func, *args, **kwargs):
    """Call a function with sys.modules['import_check'] pointing to the real package.

    The real functions use ``from . import inventory`` etc., which requires
    the real package to be registered during execution.
    """
    prev = sys.modules.get("import_check")
    sys.modules["import_check"] = _real_ic
    try:
        return func(*args, **kwargs)
    finally:
        if prev is not None:
            sys.modules["import_check"] = prev
        else:
            sys.modules.pop("import_check", None)


def fix(*args, **kwargs):
    return _with_real_ic(_fix_real, *args, **kwargs)


def check(*args, **kwargs):
    return _with_real_ic(_check_real, *args, **kwargs)


def run(*args, **kwargs):
    return _with_real_ic(_run_real, *args, **kwargs)

from import_check.schemas import (
    FixResult,
    ImportErrorType,
    RunResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git_init(root: Path) -> None:
    """Initialize a git repo, configure user, and make an initial commit."""
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=root, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=root, check=True, capture_output=True,
    )


def _git_add_commit(root: Path, message: str) -> None:
    """Stage all files and commit."""
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", message, "--allow-empty"],
        cwd=root, check=True, capture_output=True,
    )


def _write_file(path: Path, content: str) -> None:
    """Create parent dirs and write content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Integration: Fix-then-Check Happy Path
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not importlib.util.find_spec("libcst"),
    reason="libcst not installed (required by import_check.fixer)",
)
class TestFixThenCheckHappyPath:
    """A symbol is moved from one module to another.

    The fix stage rewrites all imports, and the check stage verifies
    no broken imports remain.
    """

    def test_moved_symbol_fixed_and_clean_check(self, tmp_path: Path) -> None:
        """Full pipeline: move symbol -> fix rewrites import -> check passes."""
        src = tmp_path / "src"

        # --- "Before" state: moved_func lives in old_module ---
        _write_file(
            src / "__init__.py",
            "",
        )
        _write_file(
            src / "old_module.py",
            "def moved_func():\n    return 'old'\n",
        )
        _write_file(
            src / "consumer.py",
            "from src.old_module import moved_func\n",
        )
        # pyproject.toml to configure source_dirs
        _write_file(
            tmp_path / "pyproject.toml",
            '[tool.import_check]\nsource_dirs = ["src"]\n',
        )

        # Initialize git and commit "before" state.
        _git_init(tmp_path)
        _git_add_commit(tmp_path, "initial: moved_func in old_module")

        # --- "After" state: moved_func moved to new_module ---
        _write_file(
            src / "new_module.py",
            "def moved_func():\n    return 'new'\n",
        )
        # Remove from old_module (or leave it empty).
        _write_file(src / "old_module.py", "# moved_func was moved to new_module\n")

        # Consumer still has the old import (this is what fix should rewrite).
        # Do NOT update consumer.py -- that is the fixer's job.

        # --- Run the full pipeline ---
        result = run(root=tmp_path, source_dirs=["src"])

        # Assertions.
        assert isinstance(result, RunResult)
        assert result.fix_result.fixes_applied >= 1
        assert any(
            "consumer.py" in f for f in result.fix_result.files_modified
        )
        assert result.remaining_errors == []

        # Verify file was actually rewritten.
        consumer_content = (src / "consumer.py").read_text(encoding="utf-8")
        assert "new_module" in consumer_content
        assert "old_module" not in consumer_content


# ---------------------------------------------------------------------------
# Integration: Residual Errors (deleted symbol)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not importlib.util.find_spec("libcst"),
    reason="libcst not installed (required by import_check.fixer)",
)
class TestResidualErrors:
    """A symbol is deleted (not moved). The fix stage finds no migration.

    The check stage reports a broken import.
    """

    def test_deleted_symbol_produces_remaining_error(self, tmp_path: Path) -> None:
        """Deleted symbol cannot be fixed, appears in remaining_errors."""
        src = tmp_path / "src"

        # --- "Before" state: deleted_func exists ---
        _write_file(src / "__init__.py", "")
        _write_file(
            src / "module.py",
            "def deleted_func():\n    return 42\n\ndef kept_func():\n    return 1\n",
        )
        _write_file(
            src / "consumer.py",
            "from src.module import deleted_func\n",
        )
        _write_file(
            tmp_path / "pyproject.toml",
            '[tool.import_check]\nsource_dirs = ["src"]\n',
        )

        _git_init(tmp_path)
        _git_add_commit(tmp_path, "initial: deleted_func exists")

        # --- "After" state: deleted_func removed ---
        _write_file(
            src / "module.py",
            "def kept_func():\n    return 1\n",
        )

        # --- Run full pipeline ---
        result = run(root=tmp_path, source_dirs=["src"])

        assert isinstance(result, RunResult)
        # No migrations should be generated for a deletion (only in old, not in new).
        assert result.fix_result.fixes_applied == 0

        # Check should find the broken import.
        assert len(result.remaining_errors) >= 1
        deleted_errors = [
            e for e in result.remaining_errors
            if e.name == "deleted_func"
        ]
        assert len(deleted_errors) == 1
        assert deleted_errors[0].error_type == ImportErrorType.SYMBOL_NOT_DEFINED


# ---------------------------------------------------------------------------
# Integration: Encapsulation Violation
# ---------------------------------------------------------------------------


class TestEncapsulationViolation:
    """An external file imports from an internal module, bypassing __init__.py.

    The checker reports it as an encapsulation violation but does not modify files.
    """

    def test_external_import_of_internal_module_reported(
        self, tmp_path: Path,
    ) -> None:
        """External caller importing internal module is flagged."""
        src = tmp_path / "src"
        pkg = src / "pkg"

        # Package with __init__.py (public surface).
        _write_file(src / "__init__.py", "")
        _write_file(pkg / "__init__.py", "")
        _write_file(
            pkg / "internal.py",
            "def helper():\n    return 'internal'\n",
        )
        # External consumer imports the internal module directly.
        _write_file(
            src / "consumer.py",
            "from src.pkg.internal import helper\n",
        )
        _write_file(
            tmp_path / "pyproject.toml",
            '[tool.import_check]\nsource_dirs = ["src"]\n',
        )

        # Save consumer content before check.
        consumer_before = (src / "consumer.py").read_text(encoding="utf-8")

        # Run check only (no git repo needed for check).
        errors = check(root=tmp_path, source_dirs=["src"], encapsulation_check=True)

        # Should find at least one encapsulation violation.
        encap_errors = [
            e for e in errors
            if e.error_type == ImportErrorType.ENCAPSULATION_VIOLATION
        ]
        assert len(encap_errors) >= 1
        assert any("src.pkg.internal" in e.module for e in encap_errors)

        # File content must NOT be modified (report-only).
        consumer_after = (src / "consumer.py").read_text(encoding="utf-8")
        assert consumer_before == consumer_after

    def test_no_encapsulation_violation_for_intra_package_import(
        self, tmp_path: Path,
    ) -> None:
        """Intra-package imports are allowed and not flagged."""
        src = tmp_path / "src"
        pkg = src / "pkg"

        _write_file(src / "__init__.py", "")
        _write_file(pkg / "__init__.py", "")
        _write_file(
            pkg / "internal.py",
            "def helper():\n    return 'internal'\n",
        )
        # Intra-package consumer: file is inside the same package.
        _write_file(
            pkg / "consumer.py",
            "from src.pkg.internal import helper\n",
        )
        _write_file(
            tmp_path / "pyproject.toml",
            '[tool.import_check]\nsource_dirs = ["src"]\n',
        )

        errors = check(root=tmp_path, source_dirs=["src"], encapsulation_check=True)

        encap_errors = [
            e for e in errors
            if e.error_type == ImportErrorType.ENCAPSULATION_VIOLATION
        ]
        assert len(encap_errors) == 0

    def test_encapsulation_check_disabled(self, tmp_path: Path) -> None:
        """When encapsulation_check=False, violations are not reported."""
        src = tmp_path / "src"
        pkg = src / "pkg"

        _write_file(src / "__init__.py", "")
        _write_file(pkg / "__init__.py", "")
        _write_file(
            pkg / "internal.py",
            "def helper():\n    return 'internal'\n",
        )
        _write_file(
            src / "consumer.py",
            "from src.pkg.internal import helper\n",
        )
        _write_file(
            tmp_path / "pyproject.toml",
            '[tool.import_check]\nsource_dirs = ["src"]\n',
        )

        errors = check(root=tmp_path, source_dirs=["src"], encapsulation_check=False)

        encap_errors = [
            e for e in errors
            if e.error_type == ImportErrorType.ENCAPSULATION_VIOLATION
        ]
        assert len(encap_errors) == 0
