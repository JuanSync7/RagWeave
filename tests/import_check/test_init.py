"""Tests for import_check/__init__.py -- Public API facade.

Tests cover:
- _load_config: defaults, pyproject.toml parsing, CLI overrides, precedence
- _setup_logging: log level, no duplicate handlers
- fix(): pipeline orchestration with mocked submodules
- check(): file collection and checker invocation
- run(): fix-then-check composition
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Resolve the real import_check package (not the tests/import_check/ shadow).
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_REAL_PKG_DIR = _PROJECT_ROOT / "import_check"


def _load_real_module(name: str, file_path: Path, search_paths: list[str] | None = None):
    """Load a module by explicit file path into a private namespace.

    Does NOT modify sys.modules (to avoid breaking pytest collection).
    """
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

fix = _real_ic.fix
check = _real_ic.check
run = _real_ic.run
_load_config = _real_ic._load_config
_setup_logging = _real_ic._setup_logging

from import_check.schemas import (
    FixResult,
    ImportCheckConfig,
    ImportError,
    ImportErrorType,
    MigrationEntry,
    RunResult,
    SymbolInfo,
)


# ---------------------------------------------------------------------------
# Helper: create mock submodules and inject via sys.modules
# ---------------------------------------------------------------------------


def _make_mock_submodules():
    """Create mock objects for inventory, differ, fixer, checker submodules.

    Returns a dict of {module_name: MagicMock} suitable for patch.dict(sys.modules).
    """
    mock_inventory = MagicMock()
    mock_differ = MagicMock()
    mock_fixer = MagicMock()
    mock_checker = MagicMock()

    return {
        "import_check.inventory": mock_inventory,
        "import_check.differ": mock_differ,
        "import_check.fixer": mock_fixer,
        "import_check.checker": mock_checker,
    }, mock_inventory, mock_differ, mock_fixer, mock_checker


# ---------------------------------------------------------------------------
# _load_config tests
# ---------------------------------------------------------------------------


class TestLoadConfig:
    """Tests for _load_config configuration loading."""

    def test_defaults_when_no_pyproject(self, tmp_path: Path) -> None:
        """When no pyproject.toml exists, all defaults apply."""
        config = _load_config(tmp_path)

        assert config.source_dirs == ["src", "server", "config"]
        assert config.exclude_patterns == [".venv", "__pycache__", "node_modules"]
        assert config.git_ref == "HEAD"
        assert config.encapsulation_check is True
        assert config.output_format == "human"
        assert config.log_level == "INFO"
        assert config.root == tmp_path

    def test_reads_tool_import_check_section(self, tmp_path: Path) -> None:
        """Reads [tool.import_check] from pyproject.toml."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[tool.import_check]\n'
            'source_dirs = ["lib", "app"]\n'
            'git_ref = "main"\n'
            'encapsulation_check = false\n'
        )

        config = _load_config(tmp_path)

        assert config.source_dirs == ["lib", "app"]
        assert config.git_ref == "main"
        assert config.encapsulation_check is False
        # Other fields retain defaults.
        assert config.output_format == "human"
        assert config.log_level == "INFO"

    def test_cli_overrides_take_precedence(self, tmp_path: Path) -> None:
        """Keyword overrides beat pyproject.toml values."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[tool.import_check]\n'
            'source_dirs = ["lib"]\n'
            'git_ref = "main"\n'
        )

        config = _load_config(tmp_path, source_dirs=["custom"], git_ref="HEAD~2")

        assert config.source_dirs == ["custom"]
        assert config.git_ref == "HEAD~2"

    def test_ignores_unknown_keys_in_pyproject(self, tmp_path: Path) -> None:
        """Unknown keys in pyproject.toml are silently ignored."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[tool.import_check]\n'
            'source_dirs = ["lib"]\n'
            'bogus_key = "should be ignored"\n'
        )

        config = _load_config(tmp_path)

        assert config.source_dirs == ["lib"]
        assert not hasattr(config, "bogus_key")

    def test_pyproject_with_no_tool_section(self, tmp_path: Path) -> None:
        """pyproject.toml without [tool] section uses defaults."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[build-system]\nrequires = ["setuptools"]\n')

        config = _load_config(tmp_path)

        assert config.source_dirs == ["src", "server", "config"]
        assert config.git_ref == "HEAD"

    def test_pyproject_with_tool_but_no_import_check(self, tmp_path: Path) -> None:
        """pyproject.toml with [tool] but no [tool.import_check] uses defaults."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.black]\nline-length = 88\n')

        config = _load_config(tmp_path)

        assert config.source_dirs == ["src", "server", "config"]

    def test_malformed_pyproject_logs_warning(self, tmp_path: Path, caplog) -> None:
        """Malformed TOML logs a warning and falls back to defaults."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("this is not valid toml [[[")

        with caplog.at_level(logging.WARNING, logger="import_check"):
            config = _load_config(tmp_path)

        assert config.source_dirs == ["src", "server", "config"]
        assert any("Failed to parse pyproject.toml" in r.message for r in caplog.records)

    def test_root_always_set_to_provided_value(self, tmp_path: Path) -> None:
        """root field is always set to the provided path."""
        config = _load_config(tmp_path, source_dirs=["a"])
        assert config.root == tmp_path

    def test_overrides_ignore_unknown_keys(self, tmp_path: Path) -> None:
        """Keyword overrides with unknown field names are silently ignored."""
        config = _load_config(tmp_path, totally_unknown="value")

        # Should not raise; config should have defaults.
        assert config.source_dirs == ["src", "server", "config"]


# ---------------------------------------------------------------------------
# _setup_logging tests
# ---------------------------------------------------------------------------


class TestSetupLogging:
    """Tests for _setup_logging logger configuration."""

    def test_sets_correct_log_level(self) -> None:
        """Logger is set to the level from config."""
        config = ImportCheckConfig(log_level="DEBUG")
        logger = _setup_logging(config)

        assert logger.level == logging.DEBUG
        assert logger.name == "import_check"

    def test_sets_info_level(self) -> None:
        """Logger set to INFO by default."""
        config = ImportCheckConfig(log_level="INFO")
        logger = _setup_logging(config)

        assert logger.level == logging.INFO

    def test_no_duplicate_handlers(self) -> None:
        """Repeated calls do not add duplicate handlers."""
        # Clear existing handlers first.
        logger = logging.getLogger("import_check")
        original_handlers = logger.handlers[:]
        logger.handlers.clear()

        try:
            config = ImportCheckConfig(log_level="WARNING")
            _setup_logging(config)
            first_count = len(logging.getLogger("import_check").handlers)

            _setup_logging(config)
            second_count = len(logging.getLogger("import_check").handlers)

            assert first_count == second_count == 1
        finally:
            # Restore original state.
            logger.handlers.clear()
            logger.handlers.extend(original_handlers)


# ---------------------------------------------------------------------------
# fix() tests
# ---------------------------------------------------------------------------


class TestFix:
    """Tests for fix() pipeline orchestration.

    Submodules (inventory, differ, fixer) are mocked via sys.modules patching
    since fix() uses lazy imports (``from . import inventory``).
    """

    def test_pipeline_orchestration_order(self, tmp_path: Path) -> None:
        """fix() calls inventory -> differ -> fixer in correct order."""
        mods, mock_inv, mock_diff, mock_fix, _ = _make_mock_submodules()
        mock_inv.get_changed_files.return_value = ["src/foo.py"]
        mock_inv.build_old_inventory.return_value = {
            "MyClass": [
                SymbolInfo("MyClass", "src.old", "src/old.py", 1, "class"),
            ],
        }
        mock_inv.build_inventory.return_value = {
            "MyClass": [
                SymbolInfo("MyClass", "src.new", "src/new.py", 1, "class"),
            ],
        }
        migration = MigrationEntry("src.old", "MyClass", "src.new", "MyClass", "move")
        mock_diff.diff_inventories.return_value = [migration]
        mock_inv.collect_python_files.return_value = ["src/consumer.py"]
        mock_fix.apply_fixes.return_value = FixResult(
            files_modified=["src/consumer.py"], fixes_applied=1,
        )

        with patch.dict(sys.modules, mods):
            result = fix(root=tmp_path)

        # Verify call order.
        mock_inv.get_changed_files.assert_called_once()
        mock_inv.build_old_inventory.assert_called_once()
        mock_inv.build_inventory.assert_called_once()
        mock_diff.diff_inventories.assert_called_once()
        mock_inv.collect_python_files.assert_called_once()
        mock_fix.apply_fixes.assert_called_once()

        assert result.files_modified == ["src/consumer.py"]
        assert result.fixes_applied == 1

    def test_early_return_when_no_changed_files(self, tmp_path: Path) -> None:
        """fix() returns empty FixResult when no files changed."""
        mods, mock_inv, _, _, _ = _make_mock_submodules()
        mock_inv.get_changed_files.return_value = []

        with patch.dict(sys.modules, mods):
            result = fix(root=tmp_path)

        assert result.files_modified == []
        assert result.fixes_applied == 0

    def test_early_return_when_no_migrations(self, tmp_path: Path) -> None:
        """fix() returns empty FixResult when differ finds no migrations."""
        mods, mock_inv, mock_diff, mock_fix, _ = _make_mock_submodules()
        mock_inv.get_changed_files.return_value = ["src/foo.py"]
        mock_inv.build_old_inventory.return_value = {
            "func": [SymbolInfo("func", "src.mod", "src/mod.py", 1, "function")],
        }
        mock_inv.build_inventory.return_value = {
            "func": [SymbolInfo("func", "src.mod", "src/mod.py", 1, "function")],
        }
        mock_diff.diff_inventories.return_value = []

        with patch.dict(sys.modules, mods):
            result = fix(root=tmp_path)

        assert result.files_modified == []
        assert result.fixes_applied == 0
        # fixer should never be called.
        mock_fix.apply_fixes.assert_not_called()

    def test_fix_passes_config_to_submodules(self, tmp_path: Path) -> None:
        """fix() passes resolved root and config values to submodule calls."""
        mods, mock_inv, mock_diff, mock_fix, _ = _make_mock_submodules()
        mock_inv.get_changed_files.return_value = ["src/foo.py"]
        mock_inv.build_old_inventory.return_value = {"sym": []}
        mock_inv.build_inventory.return_value = {"sym": []}
        migration = MigrationEntry("a", "sym", "b", "sym", "move")
        mock_diff.diff_inventories.return_value = [migration]
        mock_inv.collect_python_files.return_value = []
        mock_fix.apply_fixes.return_value = FixResult()

        with patch.dict(sys.modules, mods):
            fix(root=tmp_path, git_ref="HEAD~3", source_dirs=["lib"])

        # get_changed_files receives git_ref and resolved root.
        args = mock_inv.get_changed_files.call_args
        assert args[0][0] == "HEAD~3"
        assert args[0][1] == tmp_path.resolve()

        # collect_python_files receives configured source_dirs.
        cp_args = mock_inv.collect_python_files.call_args
        assert cp_args[0][0] == ["lib"]

    def test_fix_with_root_none_uses_cwd(self) -> None:
        """fix(root=None) defaults to cwd and does not raise."""
        mods, mock_inv, _, _, _ = _make_mock_submodules()
        mock_inv.get_changed_files.return_value = []

        with patch.dict(sys.modules, mods):
            result = fix(root=None)

        assert isinstance(result, FixResult)

    def test_fix_with_string_root(self, tmp_path: Path) -> None:
        """fix() accepts string root and converts to Path."""
        mods, mock_inv, _, _, _ = _make_mock_submodules()
        mock_inv.get_changed_files.return_value = []

        with patch.dict(sys.modules, mods):
            result = fix(root=str(tmp_path))

        assert isinstance(result, FixResult)


# ---------------------------------------------------------------------------
# check() tests
# ---------------------------------------------------------------------------


class TestCheck:
    """Tests for check() smoke-test pipeline."""

    def test_check_collects_files_and_calls_checker(self, tmp_path: Path) -> None:
        """check() collects Python files then runs checker.check_imports."""
        mods, mock_inv, _, _, mock_chk = _make_mock_submodules()
        mock_inv.collect_python_files.return_value = ["src/a.py", "src/b.py"]
        mock_chk.check_imports.return_value = []

        with patch.dict(sys.modules, mods):
            errors = check(root=tmp_path)

        mock_inv.collect_python_files.assert_called_once()
        mock_chk.check_imports.assert_called_once()
        assert errors == []

    def test_check_returns_errors_from_checker(self, tmp_path: Path) -> None:
        """check() returns the error list from checker.check_imports."""
        mods, mock_inv, _, _, mock_chk = _make_mock_submodules()
        mock_inv.collect_python_files.return_value = ["src/a.py"]
        err = ImportError(
            file_path="src/a.py",
            lineno=5,
            module="src.missing",
            name="Thing",
            error_type=ImportErrorType.MODULE_NOT_FOUND,
            message="Module src.missing not found",
        )
        mock_chk.check_imports.return_value = [err]

        with patch.dict(sys.modules, mods):
            errors = check(root=tmp_path)

        assert len(errors) == 1
        assert errors[0].error_type == ImportErrorType.MODULE_NOT_FOUND

    def test_check_passes_config_to_checker(self, tmp_path: Path) -> None:
        """check() passes the loaded config to checker.check_imports."""
        mods, mock_inv, _, _, mock_chk = _make_mock_submodules()
        mock_inv.collect_python_files.return_value = []
        mock_chk.check_imports.return_value = []

        with patch.dict(sys.modules, mods):
            check(root=tmp_path, encapsulation_check=False, source_dirs=["custom"])

        # Verify collect_python_files received the custom source_dirs.
        cp_args = mock_inv.collect_python_files.call_args
        assert cp_args[0][0] == ["custom"]

        # Verify check_imports received a config object.
        ci_args = mock_chk.check_imports.call_args
        config_arg = ci_args[0][2]
        assert isinstance(config_arg, ImportCheckConfig)
        assert config_arg.encapsulation_check is False


# ---------------------------------------------------------------------------
# run() tests
# ---------------------------------------------------------------------------


class TestRun:
    """Tests for run() fix-then-check pipeline.

    run() calls fix() and check() at the top level, so we mock those
    directly on the import_check module.
    """

    def test_run_calls_fix_then_check(self, tmp_path: Path) -> None:
        """run() calls fix() first, then check(), returns RunResult."""
        with patch.object(_real_ic, "fix") as mock_fix, \
             patch.object(_real_ic, "check") as mock_check:
            mock_fix.return_value = FixResult(files_modified=["a.py"], fixes_applied=2)
            mock_check.return_value = []

            result = run(root=tmp_path)

            mock_fix.assert_called_once()
            mock_check.assert_called_once()
            assert isinstance(result, RunResult)
            assert result.fix_result.fixes_applied == 2
            assert result.remaining_errors == []

    def test_run_returns_remaining_errors(self, tmp_path: Path) -> None:
        """run() includes errors from check() in remaining_errors."""
        err = ImportError(
            file_path="src/a.py",
            lineno=1,
            module="src.gone",
            name="deleted",
            error_type=ImportErrorType.SYMBOL_NOT_DEFINED,
            message="Symbol deleted not defined in src.gone",
        )
        with patch.object(_real_ic, "fix") as mock_fix, \
             patch.object(_real_ic, "check") as mock_check:
            mock_fix.return_value = FixResult()
            mock_check.return_value = [err]

            result = run(root=tmp_path)

        assert len(result.remaining_errors) == 1
        assert result.remaining_errors[0].name == "deleted"

    def test_run_passes_overrides_to_both(self, tmp_path: Path) -> None:
        """run() forwards config overrides to both fix() and check()."""
        with patch.object(_real_ic, "fix") as mock_fix, \
             patch.object(_real_ic, "check") as mock_check:
            mock_fix.return_value = FixResult()
            mock_check.return_value = []

            run(root=tmp_path, git_ref="HEAD~5", source_dirs=["lib"])

            # Both fix and check should receive the same overrides.
            fix_kwargs = mock_fix.call_args[1]
            check_kwargs = mock_check.call_args[1]
            assert fix_kwargs["git_ref"] == "HEAD~5"
            assert fix_kwargs["source_dirs"] == ["lib"]
            assert check_kwargs["git_ref"] == "HEAD~5"
            assert check_kwargs["source_dirs"] == ["lib"]
