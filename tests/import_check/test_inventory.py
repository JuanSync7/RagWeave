"""Tests for import_check/inventory.py -- Symbol Inventory Builder.

Tests cover:
- _file_to_module_path: regular files, __init__.py, nested paths, absolute paths
- _extract_symbols: functions, classes, variables, async functions, private symbol filtering, __all__
- build_inventory: multiple files, syntax errors logged and skipped
- build_old_inventory: mock git show subprocess calls, missing files skipped
- collect_python_files: include/exclude patterns, nested directories
- get_changed_files: mock git diff subprocess, filter to .py only, RuntimeError on failure
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from import_check.inventory import (
    _extract_symbols,
    _file_to_module_path,
    build_inventory,
    build_old_inventory,
    collect_python_files,
    get_changed_files,
)

# ===================================================================
# _file_to_module_path
# ===================================================================


class TestFileToModulePath:
    """Tests for converting filesystem paths to dotted module paths."""

    def test_simple_file(self, tmp_path: Path) -> None:
        result = _file_to_module_path("src/foo/bar.py", tmp_path)
        assert result == "src.foo.bar"

    def test_init_file_maps_to_package(self, tmp_path: Path) -> None:
        result = _file_to_module_path("src/foo/__init__.py", tmp_path)
        assert result == "src.foo"

    def test_nested_path(self, tmp_path: Path) -> None:
        result = _file_to_module_path("src/db/minio/store.py", tmp_path)
        assert result == "src.db.minio.store"

    def test_root_level_file(self, tmp_path: Path) -> None:
        result = _file_to_module_path("setup.py", tmp_path)
        assert result == "setup"

    def test_absolute_path_made_relative(self, tmp_path: Path) -> None:
        abs_path = str(tmp_path / "src" / "foo" / "bar.py")
        result = _file_to_module_path(abs_path, tmp_path)
        assert result == "src.foo.bar"

    def test_deeply_nested_init(self, tmp_path: Path) -> None:
        result = _file_to_module_path("src/db/minio/__init__.py", tmp_path)
        assert result == "src.db.minio"


# ===================================================================
# _extract_symbols
# ===================================================================


class TestExtractSymbols:
    """Tests for AST-based symbol extraction."""

    def test_extract_function(self) -> None:
        source = "def my_func():\n    pass\n"
        symbols = _extract_symbols(source, "src/mod.py", "src.mod")
        assert len(symbols) == 1
        assert symbols[0].name == "my_func"
        assert symbols[0].symbol_type == "function"
        assert symbols[0].module_path == "src.mod"
        assert symbols[0].file_path == "src/mod.py"
        assert symbols[0].lineno == 1

    def test_extract_async_function(self) -> None:
        source = "async def async_handler():\n    pass\n"
        symbols = _extract_symbols(source, "src/mod.py", "src.mod")
        assert len(symbols) == 1
        assert symbols[0].name == "async_handler"
        assert symbols[0].symbol_type == "function"

    def test_extract_class(self) -> None:
        source = "class MyClass:\n    pass\n"
        symbols = _extract_symbols(source, "src/mod.py", "src.mod")
        assert len(symbols) == 1
        assert symbols[0].name == "MyClass"
        assert symbols[0].symbol_type == "class"

    def test_extract_variable_assign(self) -> None:
        source = "MAX_RETRIES = 3\n"
        symbols = _extract_symbols(source, "src/mod.py", "src.mod")
        assert len(symbols) == 1
        assert symbols[0].name == "MAX_RETRIES"
        assert symbols[0].symbol_type == "variable"

    def test_extract_variable_ann_assign(self) -> None:
        source = "timeout: int = 30\n"
        symbols = _extract_symbols(source, "src/mod.py", "src.mod")
        assert len(symbols) == 1
        assert symbols[0].name == "timeout"
        assert symbols[0].symbol_type == "variable"

    def test_private_symbols_skipped(self) -> None:
        source = (
            "def _helper():\n    pass\n"
            "class _Config:\n    pass\n"
            "_private_var = 42\n"
        )
        symbols = _extract_symbols(source, "src/mod.py", "src.mod")
        assert len(symbols) == 0

    def test_dunder_all_preserved(self) -> None:
        source = '__all__ = ["foo", "bar"]\n'
        symbols = _extract_symbols(source, "src/mod.py", "src.mod")
        assert len(symbols) == 1
        assert symbols[0].name == "__all__"
        assert symbols[0].symbol_type == "variable"

    def test_multiple_symbols_in_one_file(self) -> None:
        source = (
            "def my_func():\n    pass\n\n"
            "class MyClass:\n    pass\n\n"
            "MAX_RETRIES = 3\n"
        )
        symbols = _extract_symbols(source, "src/mod.py", "src.mod")
        assert len(symbols) == 3
        names = {s.name for s in symbols}
        assert names == {"my_func", "MyClass", "MAX_RETRIES"}
        types = {s.name: s.symbol_type for s in symbols}
        assert types["my_func"] == "function"
        assert types["MyClass"] == "class"
        assert types["MAX_RETRIES"] == "variable"

    def test_empty_source(self) -> None:
        symbols = _extract_symbols("", "src/mod.py", "src.mod")
        assert symbols == []

    def test_syntax_error_raises(self) -> None:
        with pytest.raises(SyntaxError):
            _extract_symbols("def bad(:\n", "src/mod.py", "src.mod")

    def test_multiple_targets_in_assign(self) -> None:
        """Multiple Name targets in one Assign (e.g., x = y = 5)."""
        source = "x = y = 5\n"
        symbols = _extract_symbols(source, "src/mod.py", "src.mod")
        names = {s.name for s in symbols}
        assert "x" in names
        assert "y" in names

    def test_tuple_unpacking_skipped(self) -> None:
        """Tuple unpacking (a, b = 1, 2) uses ast.Tuple, not ast.Name."""
        source = "a, b = 1, 2\n"
        symbols = _extract_symbols(source, "src/mod.py", "src.mod")
        # Tuple targets are not ast.Name nodes, so they are skipped
        assert len(symbols) == 0

    def test_only_private_symbols_returns_empty(self) -> None:
        source = (
            "def _internal():\n    pass\n"
            "_counter = 0\n"
        )
        symbols = _extract_symbols(source, "src/mod.py", "src.mod")
        assert symbols == []

    def test_lineno_is_correct(self) -> None:
        source = "# comment\n\ndef second_func():\n    pass\n"
        symbols = _extract_symbols(source, "src/mod.py", "src.mod")
        assert len(symbols) == 1
        assert symbols[0].lineno == 3


# ===================================================================
# build_inventory
# ===================================================================


class TestBuildInventory:
    """Tests for building inventory from current filesystem files."""

    def test_single_file(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "engine.py").write_text("def run():\n    pass\n")

        inv = build_inventory(["src/engine.py"], tmp_path)
        assert "run" in inv
        assert len(inv["run"]) == 1
        assert inv["run"][0].module_path == "src.engine"

    def test_multiple_files(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "a.py").write_text("def alpha():\n    pass\n")
        (src_dir / "b.py").write_text("class Beta:\n    pass\n")

        inv = build_inventory(["src/a.py", "src/b.py"], tmp_path)
        assert "alpha" in inv
        assert "Beta" in inv
        assert inv["alpha"][0].symbol_type == "function"
        assert inv["Beta"][0].symbol_type == "class"

    def test_syntax_error_skipped(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "good.py").write_text("def good_func():\n    pass\n")
        (src_dir / "bad.py").write_text("def bad(:\n    pass\n")

        inv = build_inventory(["src/good.py", "src/bad.py"], tmp_path)
        assert "good_func" in inv
        # bad.py symbols are not present
        assert len(inv) == 1

    def test_unreadable_file_skipped(self, tmp_path: Path) -> None:
        inv = build_inventory(["src/nonexistent.py"], tmp_path)
        assert inv == {}

    def test_empty_file_list(self, tmp_path: Path) -> None:
        inv = build_inventory([], tmp_path)
        assert inv == {}

    def test_same_symbol_name_in_multiple_files(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "a.py").write_text("def helper():\n    pass\n")
        (src_dir / "b.py").write_text("def helper():\n    pass\n")

        inv = build_inventory(["src/a.py", "src/b.py"], tmp_path)
        assert "helper" in inv
        assert len(inv["helper"]) == 2
        modules = {si.module_path for si in inv["helper"]}
        assert modules == {"src.a", "src.b"}


# ===================================================================
# build_old_inventory
# ===================================================================


class TestBuildOldInventory:
    """Tests for building inventory from git history via mocked subprocess."""

    @patch("import_check.inventory.subprocess.run")
    def test_happy_path(self, mock_run) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["git", "show", "HEAD:src/engine.py"],
            returncode=0,
            stdout="def run():\n    pass\n",
            stderr="",
        )

        inv = build_old_inventory(["src/engine.py"], "HEAD")
        assert "run" in inv
        assert inv["run"][0].module_path == "src.engine"
        assert inv["run"][0].symbol_type == "function"
        mock_run.assert_called_once()

    @patch("import_check.inventory.subprocess.run")
    def test_file_not_found_at_ref_skipped(self, mock_run) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["git", "show", "HEAD:src/deleted.py"],
            returncode=128,
            stdout="",
            stderr="fatal: path 'src/deleted.py' does not exist in 'HEAD'",
        )

        inv = build_old_inventory(["src/deleted.py"], "HEAD")
        assert inv == {}

    @patch("import_check.inventory.subprocess.run")
    def test_multiple_files_mixed(self, mock_run) -> None:
        """One file exists at ref, another does not."""
        def side_effect(cmd, **kwargs):
            file_arg = cmd[2]  # e.g., "HEAD:src/a.py"
            if "a.py" in file_arg:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0,
                    stdout="class Alpha:\n    pass\n", stderr="",
                )
            return subprocess.CompletedProcess(
                args=cmd, returncode=128,
                stdout="", stderr="fatal: not found",
            )

        mock_run.side_effect = side_effect
        inv = build_old_inventory(["src/a.py", "src/missing.py"], "HEAD")
        assert "Alpha" in inv
        assert len(inv) == 1

    @patch("import_check.inventory.subprocess.run")
    def test_syntax_error_in_old_file_skipped(self, mock_run) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["git", "show", "HEAD:src/bad.py"],
            returncode=0,
            stdout="def bad(:\n    pass\n",
            stderr="",
        )

        inv = build_old_inventory(["src/bad.py"], "HEAD")
        assert inv == {}

    @patch("import_check.inventory.subprocess.run")
    def test_empty_file_list(self, mock_run) -> None:
        inv = build_old_inventory([], "HEAD")
        assert inv == {}
        mock_run.assert_not_called()


# ===================================================================
# collect_python_files
# ===================================================================


class TestCollectPythonFiles:
    """Tests for collecting Python files from source directories."""

    def test_basic_collection(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "a.py").write_text("")
        (src_dir / "b.py").write_text("")

        result = collect_python_files(["src"], tmp_path, [])
        assert result == ["src/a.py", "src/b.py"]

    def test_nested_directories(self, tmp_path: Path) -> None:
        nested = tmp_path / "src" / "sub" / "deep"
        nested.mkdir(parents=True)
        (nested / "module.py").write_text("")

        result = collect_python_files(["src"], tmp_path, [])
        assert "src/sub/deep/module.py" in result

    def test_exclude_pycache(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "a.py").write_text("")
        cache_dir = src_dir / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "a.cpython-311.pyc").write_text("")
        (cache_dir / "cached.py").write_text("")

        result = collect_python_files(["src"], tmp_path, ["__pycache__"])
        assert all("__pycache__" not in f for f in result)
        assert "src/a.py" in result

    def test_exclude_multiple_patterns(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "good.py").write_text("")
        venv_dir = src_dir / ".venv"
        venv_dir.mkdir()
        (venv_dir / "pkg.py").write_text("")
        cache_dir = src_dir / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "c.py").write_text("")

        result = collect_python_files(["src"], tmp_path, [".venv", "__pycache__"])
        assert result == ["src/good.py"]

    def test_nonexistent_source_dir_skipped(self, tmp_path: Path) -> None:
        result = collect_python_files(["nonexistent"], tmp_path, [])
        assert result == []

    def test_results_sorted(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "z.py").write_text("")
        (src_dir / "a.py").write_text("")
        (src_dir / "m.py").write_text("")

        result = collect_python_files(["src"], tmp_path, [])
        assert result == sorted(result)

    def test_all_files_excluded(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "test.py").write_text("")

        result = collect_python_files(["src"], tmp_path, ["*.py"])
        assert result == []

    def test_multiple_source_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.py").write_text("")
        (tmp_path / "server").mkdir()
        (tmp_path / "server" / "b.py").write_text("")

        result = collect_python_files(["src", "server"], tmp_path, [])
        assert "src/a.py" in result
        assert "server/b.py" in result

    def test_no_source_dirs_exist(self, tmp_path: Path) -> None:
        result = collect_python_files(["missing1", "missing2"], tmp_path, [])
        assert result == []


# ===================================================================
# get_changed_files
# ===================================================================


class TestGetChangedFiles:
    """Tests for getting changed Python files from git diff."""

    @patch("import_check.inventory.subprocess.run")
    def test_happy_path(self, mock_run, tmp_path: Path) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["git", "diff", "--name-only", "HEAD"],
            returncode=0,
            stdout="src/foo.py\nsrc/bar.py\nREADME.md\n",
            stderr="",
        )

        result = get_changed_files("HEAD", tmp_path)
        assert result == ["src/foo.py", "src/bar.py"]
        mock_run.assert_called_once_with(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

    @patch("import_check.inventory.subprocess.run")
    def test_filters_non_python_files(self, mock_run, tmp_path: Path) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["git", "diff", "--name-only", "HEAD"],
            returncode=0,
            stdout="README.md\nMakefile\nsrc/engine.py\ndocs/guide.rst\n",
            stderr="",
        )

        result = get_changed_files("HEAD", tmp_path)
        assert result == ["src/engine.py"]

    @patch("import_check.inventory.subprocess.run")
    def test_empty_diff(self, mock_run, tmp_path: Path) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["git", "diff", "--name-only", "HEAD"],
            returncode=0,
            stdout="",
            stderr="",
        )

        result = get_changed_files("HEAD", tmp_path)
        assert result == []

    @patch("import_check.inventory.subprocess.run")
    def test_git_failure_raises_runtime_error(self, mock_run, tmp_path: Path) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["git", "diff", "--name-only", "invalid_ref"],
            returncode=128,
            stdout="",
            stderr="fatal: bad revision 'invalid_ref'",
        )

        with pytest.raises(RuntimeError, match="git diff failed"):
            get_changed_files("invalid_ref", tmp_path)

    @patch("import_check.inventory.subprocess.run")
    def test_only_py_files_returned(self, mock_run, tmp_path: Path) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["git", "diff", "--name-only", "HEAD"],
            returncode=0,
            stdout="a.py\nb.txt\nc.py\nd.json\ne.py\n",
            stderr="",
        )

        result = get_changed_files("HEAD", tmp_path)
        assert result == ["a.py", "c.py", "e.py"]
