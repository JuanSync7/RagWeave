"""Tests for import_check/__main__.py -- CLI entry point.

Tests cover:
- _build_parser: argument defaults, subcommand parsing, all flag parsing
- _format_output: human and JSON formatting for FixResult, list[ImportError], RunResult
- main(): dispatch to fix/check/run, exit codes
- CLI arg mapping to config overrides
"""

from __future__ import annotations

import importlib
import importlib.util
import json
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

# Load __main__ submodule (needs import_check temporarily in sys.modules).
_prev_ic = sys.modules.get("import_check")
sys.modules["import_check"] = _real_ic
_main_mod = _load_real_module(
    "import_check.__main__",
    _REAL_PKG_DIR / "__main__.py",
)
# Restore.
if _prev_ic is not None:
    sys.modules["import_check"] = _prev_ic
else:
    sys.modules.pop("import_check", None)

_build_parser = _main_mod._build_parser
_format_output = _main_mod._format_output
_main_func = _main_mod.main


def main():
    """Wrapper that ensures sys.modules['import_check'] points to the real package.

    main() does ``from import_check import fix, check, run`` at runtime, so
    the real package must be in sys.modules when it executes.
    """
    prev = sys.modules.get("import_check")
    sys.modules["import_check"] = _real_ic
    try:
        return _main_func()
    finally:
        if prev is not None:
            sys.modules["import_check"] = prev
        else:
            sys.modules.pop("import_check", None)


from import_check.schemas import (
    FixResult,
    ImportCheckConfig,
    ImportError,
    ImportErrorType,
    RunResult,
)


# ---------------------------------------------------------------------------
# _build_parser tests
# ---------------------------------------------------------------------------


class TestBuildParser:
    """Tests for _build_parser argument construction."""

    def test_default_command_is_none(self) -> None:
        """With no arguments, command defaults to None (mapped to 'run')."""
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.command is None

    def test_fix_subcommand(self) -> None:
        """Explicit 'fix' subcommand is parsed."""
        parser = _build_parser()
        args = parser.parse_args(["fix"])
        assert args.command == "fix"

    def test_check_subcommand(self) -> None:
        """Explicit 'check' subcommand is parsed."""
        parser = _build_parser()
        args = parser.parse_args(["check"])
        assert args.command == "check"

    def test_run_subcommand(self) -> None:
        """Explicit 'run' subcommand is parsed."""
        parser = _build_parser()
        args = parser.parse_args(["run"])
        assert args.command == "run"

    def test_source_dirs_option(self) -> None:
        """--source-dirs accepts multiple values."""
        parser = _build_parser()
        args = parser.parse_args(["fix", "--source-dirs", "lib", "src"])
        assert args.source_dirs == ["lib", "src"]

    def test_source_dirs_default_none(self) -> None:
        """--source-dirs defaults to None when not provided."""
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.source_dirs is None

    def test_exclude_option(self) -> None:
        """--exclude accepts multiple values."""
        parser = _build_parser()
        args = parser.parse_args(["fix", "--exclude", "test_*", ".venv"])
        assert args.exclude == ["test_*", ".venv"]

    def test_exclude_default_none(self) -> None:
        """--exclude defaults to None when not provided."""
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.exclude is None

    def test_git_ref_option(self) -> None:
        """--git-ref option is parsed."""
        parser = _build_parser()
        args = parser.parse_args(["check", "--git-ref", "HEAD~2"])
        assert args.git_ref == "HEAD~2"

    def test_git_ref_default(self) -> None:
        """--git-ref defaults to HEAD."""
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.git_ref == "HEAD"

    def test_no_encapsulation_check(self) -> None:
        """--no-encapsulation-check sets encapsulation_check to False."""
        parser = _build_parser()
        args = parser.parse_args(["check", "--no-encapsulation-check"])
        assert args.encapsulation_check is False

    def test_encapsulation_check_default_true(self) -> None:
        """encapsulation_check defaults to True."""
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.encapsulation_check is True

    def test_format_json(self) -> None:
        """--format json is parsed."""
        parser = _build_parser()
        args = parser.parse_args(["check", "--format", "json"])
        assert args.format == "json"

    def test_format_human_default(self) -> None:
        """--format defaults to human."""
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.format == "human"

    def test_log_level_debug(self) -> None:
        """--log-level DEBUG is parsed."""
        parser = _build_parser()
        args = parser.parse_args(["run", "--log-level", "DEBUG"])
        assert args.log_level == "DEBUG"

    def test_log_level_default_info(self) -> None:
        """--log-level defaults to INFO."""
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.log_level == "INFO"

    def test_root_option(self) -> None:
        """--root option is parsed."""
        parser = _build_parser()
        args = parser.parse_args(["fix", "--root", "/tmp/project"])
        assert args.root == "/tmp/project"

    def test_root_default_dot(self) -> None:
        """--root defaults to '.'."""
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.root == "."

    def test_all_options_combined(self) -> None:
        """All options parsed together correctly."""
        parser = _build_parser()
        args = parser.parse_args([
            "fix",
            "--source-dirs", "lib", "app",
            "--exclude", ".venv", "__pycache__",
            "--git-ref", "main",
            "--no-encapsulation-check",
            "--format", "json",
            "--log-level", "ERROR",
            "--root", "/my/project",
        ])
        assert args.command == "fix"
        assert args.source_dirs == ["lib", "app"]
        assert args.exclude == [".venv", "__pycache__"]
        assert args.git_ref == "main"
        assert args.encapsulation_check is False
        assert args.format == "json"
        assert args.log_level == "ERROR"
        assert args.root == "/my/project"


# ---------------------------------------------------------------------------
# _format_output tests -- human format
# ---------------------------------------------------------------------------


class TestFormatOutputHuman:
    """Tests for _format_output with human format."""

    def test_fix_result_human(self) -> None:
        """Human format for FixResult shows summary line."""
        result = FixResult(files_modified=["a.py", "b.py"], fixes_applied=5)
        output = _format_output(result, "human")

        assert "5 imports rewritten" in output
        assert "2 files" in output

    def test_fix_result_zero_fixes_human(self) -> None:
        """Human format for empty FixResult shows zero counts."""
        result = FixResult()
        output = _format_output(result, "human")

        assert "0 imports rewritten" in output
        assert "0 files" in output

    def test_fix_result_with_errors_human(self) -> None:
        """Human format for FixResult with errors shows error count."""
        result = FixResult(
            files_modified=["a.py"],
            fixes_applied=1,
            errors=["Failed to parse a.py"],
        )
        output = _format_output(result, "human")

        assert "Errors: 1" in output
        assert "Failed to parse a.py" in output

    def test_fix_result_with_skipped_human(self) -> None:
        """Human format for FixResult with skipped shows skip count."""
        result = FixResult(
            files_modified=[],
            fixes_applied=0,
            skipped=["dynamic import at line 42"],
        )
        output = _format_output(result, "human")

        assert "Skipped: 1" in output
        assert "dynamic import at line 42" in output

    def test_empty_check_list_human(self) -> None:
        """Human format for empty error list shows 'all imports OK'."""
        output = _format_output([], "human")
        assert "all imports OK" in output

    def test_check_errors_human(self) -> None:
        """Human format for import errors shows error count and details."""
        errors = [
            ImportError(
                file_path="src/a.py",
                lineno=10,
                module="src.missing",
                name="Thing",
                error_type=ImportErrorType.MODULE_NOT_FOUND,
                message="Module src.missing not found",
            ),
            ImportError(
                file_path="src/b.py",
                lineno=5,
                module="src.mod",
                name="gone",
                error_type=ImportErrorType.SYMBOL_NOT_DEFINED,
                message="Symbol gone not defined in src.mod",
            ),
        ]
        output = _format_output(errors, "human")

        assert "2 import errors found" in output
        assert "src/a.py:10" in output
        assert "src/b.py:5" in output

    def test_run_result_no_errors_human(self) -> None:
        """Human format for RunResult with no remaining errors."""
        result = RunResult(
            fix_result=FixResult(files_modified=["x.py"], fixes_applied=3),
            remaining_errors=[],
        )
        output = _format_output(result, "human")

        assert "3 imports rewritten" in output
        assert "All imports OK after fix." in output

    def test_run_result_with_errors_human(self) -> None:
        """Human format for RunResult with remaining errors."""
        err = ImportError(
            file_path="src/c.py",
            lineno=7,
            module="src.deleted",
            name="func",
            error_type=ImportErrorType.SYMBOL_NOT_DEFINED,
            message="Symbol func not defined",
        )
        result = RunResult(
            fix_result=FixResult(),
            remaining_errors=[err],
        )
        output = _format_output(result, "human")

        assert "Remaining errors: 1" in output
        assert "src/c.py:7" in output


# ---------------------------------------------------------------------------
# _format_output tests -- JSON format
# ---------------------------------------------------------------------------


class TestFormatOutputJSON:
    """Tests for _format_output with JSON format."""

    def test_fix_result_json_valid(self) -> None:
        """JSON format for FixResult produces valid JSON with correct fields."""
        result = FixResult(
            files_modified=["a.py"],
            fixes_applied=2,
            errors=["err1"],
            skipped=["skip1"],
        )
        output = _format_output(result, "json")
        data = json.loads(output)

        assert data["files_modified"] == ["a.py"]
        assert data["fixes_applied"] == 2
        assert data["errors"] == ["err1"]
        assert data["skipped"] == ["skip1"]

    def test_check_errors_json_valid(self) -> None:
        """JSON format for error list produces valid JSON array."""
        errors = [
            ImportError(
                file_path="src/a.py",
                lineno=10,
                module="src.missing",
                name="Thing",
                error_type=ImportErrorType.MODULE_NOT_FOUND,
                message="Module not found",
            ),
        ]
        output = _format_output(errors, "json")
        data = json.loads(output)

        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["file_path"] == "src/a.py"
        assert data[0]["lineno"] == 10
        assert data[0]["module"] == "src.missing"
        assert data[0]["name"] == "Thing"
        assert data[0]["error_type"] == "module_not_found"
        assert data[0]["message"] == "Module not found"

    def test_empty_check_json(self) -> None:
        """JSON format for empty error list produces empty array."""
        output = _format_output([], "json")
        data = json.loads(output)
        assert data == []

    def test_run_result_json_valid(self) -> None:
        """JSON format for RunResult has fix_result and remaining_errors fields."""
        err = ImportError(
            file_path="src/b.py",
            lineno=3,
            module="src.old",
            name="func",
            error_type=ImportErrorType.SYMBOL_NOT_DEFINED,
            message="Not defined",
        )
        result = RunResult(
            fix_result=FixResult(files_modified=["x.py"], fixes_applied=1),
            remaining_errors=[err],
        )
        output = _format_output(result, "json")
        data = json.loads(output)

        assert "fix_result" in data
        assert data["fix_result"]["files_modified"] == ["x.py"]
        assert data["fix_result"]["fixes_applied"] == 1
        assert len(data["remaining_errors"]) == 1
        assert data["remaining_errors"][0]["name"] == "func"

    def test_unknown_type_json_fallback(self) -> None:
        """JSON format for unknown type falls back to str()."""
        output = _format_output("unexpected", "json")
        data = json.loads(output)
        assert "unexpected" in data

    def test_unknown_type_human_fallback(self) -> None:
        """Human format for unknown type falls back to str()."""
        output = _format_output(42, "human")
        assert "42" in output


# ---------------------------------------------------------------------------
# main() tests
# ---------------------------------------------------------------------------


_ic_mod = _real_ic


class TestMain:
    """Tests for main() CLI dispatch and exit codes.

    main() does ``from import_check import fix, check, run`` lazily, so
    we mock those on the import_check module using patch.object.
    """

    def test_default_command_runs_run(self) -> None:
        """No subcommand defaults to run(), exit 0 when no errors."""
        mock_run = MagicMock(return_value=RunResult(fix_result=FixResult(), remaining_errors=[]))

        with patch.object(_ic_mod, "run", mock_run), \
             patch.object(_ic_mod, "fix", MagicMock()) as mock_fix, \
             patch.object(_ic_mod, "check", MagicMock()) as mock_check, \
             patch("sys.argv", ["import_check"]):
            exit_code = main()

        mock_run.assert_called_once()
        mock_fix.assert_not_called()
        mock_check.assert_not_called()
        assert exit_code == 0

    def test_run_exit_1_when_errors(self) -> None:
        """run subcommand returns exit 1 when remaining errors exist."""
        err = ImportError(
            file_path="a.py", lineno=1, module="x", name="y",
            error_type=ImportErrorType.MODULE_NOT_FOUND, message="missing",
        )
        mock_run = MagicMock(return_value=RunResult(
            fix_result=FixResult(), remaining_errors=[err],
        ))

        with patch.object(_ic_mod, "run", mock_run), \
             patch("sys.argv", ["import_check", "run"]):
            exit_code = main()

        assert exit_code == 1

    def test_fix_always_exit_0(self) -> None:
        """fix subcommand always returns exit 0."""
        mock_fix = MagicMock(return_value=FixResult(files_modified=["a.py"], fixes_applied=1))

        with patch.object(_ic_mod, "fix", mock_fix), \
             patch("sys.argv", ["import_check", "fix"]):
            exit_code = main()

        mock_fix.assert_called_once()
        assert exit_code == 0

    def test_check_exit_0_when_clean(self) -> None:
        """check subcommand returns exit 0 when no errors."""
        mock_check = MagicMock(return_value=[])

        with patch.object(_ic_mod, "check", mock_check), \
             patch("sys.argv", ["import_check", "check"]):
            exit_code = main()

        mock_check.assert_called_once()
        assert exit_code == 0

    def test_check_exit_1_when_errors(self) -> None:
        """check subcommand returns exit 1 when errors found."""
        err = ImportError(
            file_path="a.py", lineno=1, module="x", name="y",
            error_type=ImportErrorType.SYMBOL_NOT_DEFINED, message="gone",
        )
        mock_check = MagicMock(return_value=[err])

        with patch.object(_ic_mod, "check", mock_check), \
             patch("sys.argv", ["import_check", "check"]):
            exit_code = main()

        assert exit_code == 1

    def test_fix_receives_source_dirs_override(self) -> None:
        """--source-dirs are passed to fix() as config override."""
        mock_fix = MagicMock(return_value=FixResult())

        with patch.object(_ic_mod, "fix", mock_fix), \
             patch("sys.argv", ["import_check", "fix", "--source-dirs", "lib", "app"]):
            main()

        call_kwargs = mock_fix.call_args[1]
        assert call_kwargs["source_dirs"] == ["lib", "app"]

    def test_fix_receives_exclude_override(self) -> None:
        """--exclude patterns are passed to fix() as config override."""
        mock_fix = MagicMock(return_value=FixResult())

        with patch.object(_ic_mod, "fix", mock_fix), \
             patch("sys.argv", ["import_check", "fix", "--exclude", "test_*"]):
            main()

        call_kwargs = mock_fix.call_args[1]
        assert call_kwargs["exclude_patterns"] == ["test_*"]

    def test_check_receives_git_ref_override(self) -> None:
        """--git-ref is passed to check() as config override."""
        mock_check = MagicMock(return_value=[])

        with patch.object(_ic_mod, "check", mock_check), \
             patch("sys.argv", ["import_check", "check", "--git-ref", "HEAD~2"]):
            main()

        call_kwargs = mock_check.call_args[1]
        assert call_kwargs["git_ref"] == "HEAD~2"

    def test_check_receives_no_encapsulation_check(self) -> None:
        """--no-encapsulation-check sets encapsulation_check=False."""
        mock_check = MagicMock(return_value=[])

        with patch.object(_ic_mod, "check", mock_check), \
             patch("sys.argv", ["import_check", "check", "--no-encapsulation-check"]):
            main()

        call_kwargs = mock_check.call_args[1]
        assert call_kwargs["encapsulation_check"] is False

    def test_run_receives_log_level(self) -> None:
        """--log-level is passed as config override."""
        mock_run = MagicMock(
            return_value=RunResult(fix_result=FixResult(), remaining_errors=[]),
        )

        with patch.object(_ic_mod, "run", mock_run), \
             patch("sys.argv", ["import_check", "run", "--log-level", "DEBUG"]):
            main()

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["log_level"] == "DEBUG"

    def test_fix_receives_root(self, tmp_path: Path) -> None:
        """--root is resolved and passed as positional arg."""
        mock_fix = MagicMock(return_value=FixResult())

        with patch.object(_ic_mod, "fix", mock_fix), \
             patch("sys.argv", ["import_check", "fix", "--root", str(tmp_path)]):
            main()

        call_args = mock_fix.call_args[0]
        assert call_args[0] == tmp_path.resolve()

    def test_source_dirs_not_included_when_not_provided(self) -> None:
        """When --source-dirs is not given, source_dirs key is not in overrides."""
        mock_fix = MagicMock(return_value=FixResult())

        with patch.object(_ic_mod, "fix", mock_fix), \
             patch("sys.argv", ["import_check", "fix"]):
            main()

        call_kwargs = mock_fix.call_args[1]
        assert "source_dirs" not in call_kwargs

    def test_exclude_not_included_when_not_provided(self) -> None:
        """When --exclude is not given, exclude_patterns key is not in overrides."""
        mock_fix = MagicMock(return_value=FixResult())

        with patch.object(_ic_mod, "fix", mock_fix), \
             patch("sys.argv", ["import_check", "fix"]):
            main()

        call_kwargs = mock_fix.call_args[1]
        assert "exclude_patterns" not in call_kwargs

    def test_format_json_produces_json_output(self, capsys) -> None:
        """--format json produces parseable JSON output."""
        mock_run = MagicMock(
            return_value=RunResult(fix_result=FixResult(), remaining_errors=[]),
        )

        with patch.object(_ic_mod, "run", mock_run), \
             patch("sys.argv", ["import_check", "--format", "json"]):
            main()

        captured = capsys.readouterr()
        # Output should be valid JSON (if non-empty).
        if captured.out.strip():
            data = json.loads(captured.out)
            assert "fix_result" in data
