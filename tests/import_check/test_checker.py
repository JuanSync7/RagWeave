"""Tests for import_check/checker.py -- Smoke Test Checker.

Covers:
- _resolve_module_to_file: module.py exists, package/__init__.py exists, neither exists
- _extract_imports: regular, from, lazy, TYPE_CHECKING, try/except, relative skipped
- _check_symbol_defined: functions, classes, variables, re-exports, __all__ entries
- _check_encapsulation: external violation, intra-package allowed, __init__ import allowed
- check_imports: integration with tmp_path filesystem
"""

from __future__ import annotations

from pathlib import Path

import pytest

from import_check.checker import (
    _check_encapsulation,
    _check_symbol_defined,
    _extract_imports,
    _resolve_module_to_file,
    check_imports,
)
from import_check.schemas import ImportCheckConfig, ImportErrorType


# ---------------------------------------------------------------------------
# _resolve_module_to_file
# ---------------------------------------------------------------------------


class TestResolveModuleToFile:
    """Tests for _resolve_module_to_file."""

    def test_resolves_to_py_file(self, tmp_path: Path) -> None:
        """Module path resolves to an existing .py file."""
        (tmp_path / "src" / "foo").mkdir(parents=True)
        target = tmp_path / "src" / "foo" / "bar.py"
        target.write_text("x = 1\n")

        result = _resolve_module_to_file("src.foo.bar", tmp_path)
        assert result == target

    def test_resolves_to_package_init(self, tmp_path: Path) -> None:
        """Module path resolves to a package __init__.py."""
        (tmp_path / "src" / "foo").mkdir(parents=True)
        init = tmp_path / "src" / "foo" / "__init__.py"
        init.write_text("from .bar import MyClass\n")

        result = _resolve_module_to_file("src.foo", tmp_path)
        assert result == init

    def test_returns_none_when_neither_exists(self, tmp_path: Path) -> None:
        """Returns None when no .py file or __init__.py matches."""
        result = _resolve_module_to_file("src.nonexistent.module", tmp_path)
        assert result is None

    def test_prefers_py_file_over_package(self, tmp_path: Path) -> None:
        """When both module.py and module/__init__.py exist, .py file wins."""
        (tmp_path / "src").mkdir(parents=True)
        py_file = tmp_path / "src" / "utils.py"
        py_file.write_text("x = 1\n")
        # Also create package form
        (tmp_path / "src" / "utils").mkdir()
        (tmp_path / "src" / "utils" / "__init__.py").write_text("")

        result = _resolve_module_to_file("src.utils", tmp_path)
        assert result == py_file

    def test_single_component_module(self, tmp_path: Path) -> None:
        """Single-component module resolves to top-level .py file."""
        target = tmp_path / "config.py"
        target.write_text("DEBUG = True\n")

        result = _resolve_module_to_file("config", tmp_path)
        assert result == target


# ---------------------------------------------------------------------------
# _extract_imports
# ---------------------------------------------------------------------------


class TestExtractImports:
    """Tests for _extract_imports."""

    def test_from_import(self) -> None:
        """Extracts from X import Y."""
        source = "from src.foo import bar\n"
        result = _extract_imports(source)
        assert ("src.foo", "bar", 1, 0) in result

    def test_bare_import(self) -> None:
        """Extracts import X as (X, '', lineno)."""
        source = "import src.foo\n"
        result = _extract_imports(source)
        assert ("src.foo", "", 1, 0) in result

    def test_aliased_from_import(self) -> None:
        """Aliased imports return the original name, not the alias."""
        source = "from src.foo import bar as baz\n"
        result = _extract_imports(source)
        assert ("src.foo", "bar", 1, 0) in result

    def test_aliased_bare_import(self) -> None:
        """Bare aliased imports: import X as Z -> (X, '', lineno)."""
        source = "import src.foo as sf\n"
        result = _extract_imports(source)
        assert ("src.foo", "", 1, 0) in result

    def test_lazy_import_inside_function(self) -> None:
        """Imports inside functions are captured."""
        source = "def f():\n    from src.foo import bar\n"
        result = _extract_imports(source)
        assert ("src.foo", "bar", 2, 0) in result

    def test_type_checking_import(self) -> None:
        """Imports inside TYPE_CHECKING blocks are captured."""
        source = (
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from src.foo import bar\n"
        )
        result = _extract_imports(source)
        assert ("src.foo", "bar", 3, 0) in result

    def test_try_except_import(self) -> None:
        """Imports inside try/except blocks are captured."""
        source = (
            "try:\n"
            "    from src.foo import bar\n"
            "except ImportError:\n"
            "    pass\n"
        )
        result = _extract_imports(source)
        assert ("src.foo", "bar", 2, 0) in result

    def test_relative_imports_skipped(self) -> None:
        """Relative imports (leading dots) are included with level > 0."""
        source = "from .foo import bar\nfrom ..baz import qux\n"
        result = _extract_imports(source)
        # Relative imports are included with their level (not skipped).
        assert ("foo", "bar", 1, 1) in result
        assert ("baz", "qux", 2, 2) in result
        assert all(level > 0 for _, _, _, level in result)

    def test_empty_source(self) -> None:
        """Empty source returns empty list."""
        assert _extract_imports("") == []

    def test_syntax_error_returns_empty(self) -> None:
        """Unparseable source returns empty list."""
        source = "def broken(\n"
        assert _extract_imports(source) == []

    def test_multiple_names_from_one_module(self) -> None:
        """from X import a, b produces two entries."""
        source = "from src.foo import bar, baz\n"
        result = _extract_imports(source)
        assert ("src.foo", "bar", 1, 0) in result
        assert ("src.foo", "baz", 1, 0) in result
        assert len(result) == 2

    def test_star_import(self) -> None:
        """from X import * is captured."""
        source = "from src.foo import *\n"
        result = _extract_imports(source)
        assert ("src.foo", "*", 1, 0) in result


# ---------------------------------------------------------------------------
# _check_symbol_defined
# ---------------------------------------------------------------------------


class TestCheckSymbolDefined:
    """Tests for _check_symbol_defined."""

    def test_function_defined(self, tmp_path: Path) -> None:
        """Function definition is found."""
        f = tmp_path / "mod.py"
        f.write_text("def my_func():\n    pass\n")
        assert _check_symbol_defined(f, "my_func") is True

    def test_async_function_defined(self, tmp_path: Path) -> None:
        """Async function definition is found."""
        f = tmp_path / "mod.py"
        f.write_text("async def async_handler():\n    pass\n")
        assert _check_symbol_defined(f, "async_handler") is True

    def test_class_defined(self, tmp_path: Path) -> None:
        """Class definition is found."""
        f = tmp_path / "mod.py"
        f.write_text("class MyClass:\n    pass\n")
        assert _check_symbol_defined(f, "MyClass") is True

    def test_variable_assign(self, tmp_path: Path) -> None:
        """Simple variable assignment is found."""
        f = tmp_path / "mod.py"
        f.write_text("MAX_RETRIES = 3\n")
        assert _check_symbol_defined(f, "MAX_RETRIES") is True

    def test_annotated_variable(self, tmp_path: Path) -> None:
        """Annotated assignment is found."""
        f = tmp_path / "mod.py"
        f.write_text("timeout: int = 30\n")
        assert _check_symbol_defined(f, "timeout") is True

    def test_reexport_via_import_from(self, tmp_path: Path) -> None:
        """Symbol re-exported via from X import Y is found."""
        f = tmp_path / "mod.py"
        f.write_text("from .internal import MyHelper\n")
        assert _check_symbol_defined(f, "MyHelper") is True

    def test_all_entries(self, tmp_path: Path) -> None:
        """Symbol listed in __all__ is considered defined."""
        f = tmp_path / "mod.py"
        f.write_text('__all__ = ["bar", "baz"]\n')
        assert _check_symbol_defined(f, "bar") is True
        assert _check_symbol_defined(f, "baz") is True

    def test_symbol_not_found(self, tmp_path: Path) -> None:
        """Symbol that does not exist returns False."""
        f = tmp_path / "mod.py"
        f.write_text("def something_else():\n    pass\n")
        assert _check_symbol_defined(f, "nonexistent") is False

    def test_tuple_unpacking(self, tmp_path: Path) -> None:
        """Symbol defined via tuple unpacking is found."""
        f = tmp_path / "mod.py"
        f.write_text("bar, baz = 1, 2\n")
        assert _check_symbol_defined(f, "bar") is True
        assert _check_symbol_defined(f, "baz") is True

    def test_syntax_error_returns_false(self, tmp_path: Path) -> None:
        """Unparseable module file returns False."""
        f = tmp_path / "mod.py"
        f.write_text("def broken(\n")
        assert _check_symbol_defined(f, "broken") is False

    def test_nonexistent_file_returns_false(self, tmp_path: Path) -> None:
        """Non-existent file returns False (OSError handled)."""
        f = tmp_path / "does_not_exist.py"
        assert _check_symbol_defined(f, "anything") is False

    def test_import_reexport(self, tmp_path: Path) -> None:
        """Symbol re-exported via import X as Y is found."""
        f = tmp_path / "mod.py"
        f.write_text("import utils as my_utils\n")
        assert _check_symbol_defined(f, "my_utils") is True


# ---------------------------------------------------------------------------
# _check_encapsulation
# ---------------------------------------------------------------------------


class TestCheckEncapsulation:
    """Tests for _check_encapsulation."""

    def test_external_caller_violation(self, tmp_path: Path) -> None:
        """External caller importing internal module = violation."""
        # Create package with __init__.py and internal module
        pkg = tmp_path / "src" / "foo"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("from .internal import helper\n")
        (pkg / "internal.py").write_text("def helper(): pass\n")

        # External caller file
        caller_dir = tmp_path / "tests"
        caller_dir.mkdir(parents=True)
        (caller_dir / "test_foo.py").write_text("")

        result = _check_encapsulation(
            module="src.foo.internal",
            file_path="tests/test_foo.py",
            root=tmp_path,
        )
        assert result is not None
        assert result.error_type == ImportErrorType.ENCAPSULATION_VIOLATION
        assert "src.foo.internal" in result.message

    def test_intra_package_import_allowed(self, tmp_path: Path) -> None:
        """Intra-package import is allowed (no violation)."""
        pkg = tmp_path / "src" / "foo"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "internal.py").write_text("def helper(): pass\n")
        (pkg / "consumer.py").write_text("")

        result = _check_encapsulation(
            module="src.foo.internal",
            file_path="src/foo/consumer.py",
            root=tmp_path,
        )
        assert result is None

    def test_importing_from_init_allowed(self, tmp_path: Path) -> None:
        """Importing a package (resolves to __init__.py) is allowed."""
        pkg = tmp_path / "src" / "foo"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("x = 1\n")

        result = _check_encapsulation(
            module="src.foo",
            file_path="tests/test_foo.py",
            root=tmp_path,
        )
        assert result is None

    def test_single_component_module_no_violation(self, tmp_path: Path) -> None:
        """Single-component module path returns None (need at least 2 parts)."""
        (tmp_path / "foo.py").write_text("x = 1\n")

        result = _check_encapsulation(
            module="foo",
            file_path="bar.py",
            root=tmp_path,
        )
        assert result is None

    def test_no_init_py_no_violation(self, tmp_path: Path) -> None:
        """Package without __init__.py -> no public surface to violate."""
        pkg = tmp_path / "src" / "foo"
        pkg.mkdir(parents=True)
        # No __init__.py
        (pkg / "internal.py").write_text("def helper(): pass\n")

        result = _check_encapsulation(
            module="src.foo.internal",
            file_path="tests/test_foo.py",
            root=tmp_path,
        )
        assert result is None

    def test_module_not_found_no_violation(self, tmp_path: Path) -> None:
        """If the module cannot be resolved, returns None."""
        result = _check_encapsulation(
            module="src.foo.nonexistent",
            file_path="tests/test_foo.py",
            root=tmp_path,
        )
        assert result is None


# ---------------------------------------------------------------------------
# check_imports (integration)
# ---------------------------------------------------------------------------


class TestCheckImports:
    """Integration tests for check_imports with tmp_path filesystem."""

    def _setup_project(self, root: Path) -> None:
        """Create a minimal project structure under root."""
        # Create src/foo package
        pkg = root / "src" / "foo"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("from .bar import MyClass\n")
        (pkg / "bar.py").write_text(
            "class MyClass:\n"
            "    pass\n"
            "\n"
            "def helper():\n"
            "    pass\n"
        )
        # Create src/utils.py
        (root / "src" / "utils.py").write_text("MAX_RETRIES = 3\n")

    def test_clean_imports_no_errors(self, tmp_path: Path) -> None:
        """All imports resolve correctly -> empty error list."""
        self._setup_project(tmp_path)

        # File with valid imports
        caller = tmp_path / "src" / "main.py"
        caller.write_text("from src.foo import MyClass\n")

        errors = check_imports(
            files=["src/main.py"],
            root=tmp_path,
        )
        assert errors == []

    def test_module_not_found_error(self, tmp_path: Path) -> None:
        """Import referencing a non-existent module produces MODULE_NOT_FOUND."""
        self._setup_project(tmp_path)

        caller = tmp_path / "src" / "main.py"
        caller.write_text("from src.nonexistent import something\n")

        errors = check_imports(files=["src/main.py"], root=tmp_path)
        assert len(errors) == 1
        assert errors[0].error_type == ImportErrorType.MODULE_NOT_FOUND
        assert errors[0].module == "src.nonexistent"

    def test_symbol_not_defined_error(self, tmp_path: Path) -> None:
        """Import referencing a module that exists but symbol does not -> SYMBOL_NOT_DEFINED."""
        self._setup_project(tmp_path)

        caller = tmp_path / "src" / "main.py"
        caller.write_text("from src.foo.bar import DoesNotExist\n")

        errors = check_imports(files=["src/main.py"], root=tmp_path)
        assert len(errors) >= 1
        sym_errors = [e for e in errors if e.error_type == ImportErrorType.SYMBOL_NOT_DEFINED]
        assert len(sym_errors) == 1
        assert sym_errors[0].name == "DoesNotExist"
        assert sym_errors[0].module == "src.foo.bar"

    def test_encapsulation_violation(self, tmp_path: Path) -> None:
        """External caller importing internal module -> ENCAPSULATION_VIOLATION."""
        self._setup_project(tmp_path)

        # External test file importing internal module directly
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        caller = tests_dir / "test_foo.py"
        caller.write_text("from src.foo.bar import MyClass\n")

        config = ImportCheckConfig(encapsulation_check=True)
        errors = check_imports(
            files=["tests/test_foo.py"],
            root=tmp_path,
            config=config,
        )

        enc_errors = [
            e for e in errors if e.error_type == ImportErrorType.ENCAPSULATION_VIOLATION
        ]
        assert len(enc_errors) == 1
        assert enc_errors[0].module == "src.foo.bar"

    def test_encapsulation_disabled(self, tmp_path: Path) -> None:
        """With encapsulation_check=False, no violations are reported."""
        self._setup_project(tmp_path)

        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        caller = tests_dir / "test_foo.py"
        caller.write_text("from src.foo.bar import MyClass\n")

        config = ImportCheckConfig(encapsulation_check=False)
        errors = check_imports(
            files=["tests/test_foo.py"],
            root=tmp_path,
            config=config,
        )
        enc_errors = [
            e for e in errors if e.error_type == ImportErrorType.ENCAPSULATION_VIOLATION
        ]
        assert len(enc_errors) == 0

    def test_stdlib_imports_skipped(self, tmp_path: Path) -> None:
        """Stdlib imports do not produce errors even if no local file exists."""
        (tmp_path / "src").mkdir(parents=True)
        caller = tmp_path / "src" / "main.py"
        caller.write_text("import os\nfrom pathlib import Path\nimport json\n")

        errors = check_imports(files=["src/main.py"], root=tmp_path)
        assert errors == []

    def test_empty_file_list(self, tmp_path: Path) -> None:
        """Empty file list returns empty error list."""
        errors = check_imports(files=[], root=tmp_path)
        assert errors == []

    def test_config_none_uses_defaults(self, tmp_path: Path) -> None:
        """config=None uses default ImportCheckConfig."""
        self._setup_project(tmp_path)

        caller = tmp_path / "src" / "main.py"
        caller.write_text("from src.foo import MyClass\n")

        errors = check_imports(files=["src/main.py"], root=tmp_path, config=None)
        assert errors == []

    def test_file_with_syntax_error_skipped(self, tmp_path: Path) -> None:
        """File that cannot be parsed has its imports skipped (empty extraction)."""
        (tmp_path / "src").mkdir(parents=True)
        caller = tmp_path / "src" / "broken.py"
        caller.write_text("def broken(\n")

        # Should not crash; just no imports extracted
        errors = check_imports(files=["src/broken.py"], root=tmp_path)
        assert errors == []

    def test_multiple_error_types(self, tmp_path: Path) -> None:
        """A single file can produce multiple error types."""
        self._setup_project(tmp_path)

        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        caller = tests_dir / "test_multi.py"
        caller.write_text(
            "from src.nonexistent import something\n"
            "from src.foo.bar import DoesNotExist\n"
        )

        config = ImportCheckConfig(encapsulation_check=True)
        errors = check_imports(
            files=["tests/test_multi.py"],
            root=tmp_path,
            config=config,
        )

        error_types = {e.error_type for e in errors}
        assert ImportErrorType.MODULE_NOT_FOUND in error_types
        # bar.py exists, so SYMBOL_NOT_DEFINED for DoesNotExist
        assert ImportErrorType.SYMBOL_NOT_DEFINED in error_types
