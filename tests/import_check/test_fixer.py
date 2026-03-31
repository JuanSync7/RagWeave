"""Tests for import_check/fixer.py -- Import Fixer.

Covers:
- ImportRewriter: from-import moves, renames, aliases, bare imports
- StringRefRewriter: mock.patch strings, importlib.import_module strings
- AllListRewriter: __all__ list renames
- apply_fixes: integration with tmp_path files
- Edge cases: syntax errors, no changes, empty migration map
"""

from __future__ import annotations

from pathlib import Path

import libcst as cst
import pytest

from import_check.fixer import (
    AllListRewriter,
    ImportRewriter,
    StringRefRewriter,
    apply_fixes,
)
from import_check.schemas import MigrationEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _transform(source: str, transformer: cst.CSTTransformer) -> str:
    """Parse source, apply transformer, return modified code."""
    tree = cst.parse_module(source)
    modified = tree.visit(transformer)
    return modified.code


def _move_entry(
    old_module: str = "src.old",
    old_name: str = "foo",
    new_module: str = "src.new",
    new_name: str = "foo",
    migration_type: str = "move",
) -> MigrationEntry:
    """Create a MigrationEntry with convenient defaults."""
    return MigrationEntry(
        old_module=old_module,
        old_name=old_name,
        new_module=new_module,
        new_name=new_name,
        migration_type=migration_type,
    )


# ---------------------------------------------------------------------------
# ImportRewriter
# ---------------------------------------------------------------------------


class TestImportRewriter:
    """Tests for the ImportRewriter CST transformer."""

    def test_simple_from_import_move(self) -> None:
        """Rewrites `from src.old import foo` to `from src.new import foo`."""
        source = "from src.old import foo\n"
        entry = _move_entry()
        rewriter = ImportRewriter([entry])

        result = _transform(source, rewriter)
        assert "from src.new import foo" in result
        assert rewriter.fixes_applied == 1

    def test_symbol_rename(self) -> None:
        """Rewrites `from src.mod import old_name` to `from src.mod import new_name`."""
        source = "from src.mod import old_name\n"
        entry = _move_entry(
            old_module="src.mod",
            old_name="old_name",
            new_module="src.mod",
            new_name="new_name",
            migration_type="rename",
        )
        rewriter = ImportRewriter([entry])

        result = _transform(source, rewriter)
        assert "from src.mod import new_name" in result
        assert "old_name" not in result
        assert rewriter.fixes_applied == 1

    def test_move_and_rename(self) -> None:
        """Rewrites module path and symbol name together."""
        source = "from src.old import old_fn\n"
        entry = _move_entry(
            old_module="src.old",
            old_name="old_fn",
            new_module="src.new",
            new_name="new_fn",
        )
        rewriter = ImportRewriter([entry])

        result = _transform(source, rewriter)
        assert "from src.new import new_fn" in result
        assert rewriter.fixes_applied == 1

    def test_aliased_import_preserved(self) -> None:
        """Alias `as f` is preserved when the import is rewritten."""
        source = "from src.old import foo as f\n"
        entry = _move_entry()
        rewriter = ImportRewriter([entry])

        result = _transform(source, rewriter)
        assert "from src.new import foo as f" in result
        assert rewriter.fixes_applied == 1

    def test_bare_import_rewrite(self) -> None:
        """Rewrites `import src.old.utils` to `import src.new.helpers`."""
        source = "import src.old.utils\n"
        entry = _move_entry(
            old_module="src.old.utils",
            old_name="anything",
            new_module="src.new.helpers",
            new_name="anything",
        )
        rewriter = ImportRewriter([entry])

        result = _transform(source, rewriter)
        assert "import src.new.helpers" in result
        assert rewriter.fixes_applied == 1

    def test_star_import_module_rewrite(self) -> None:
        """Rewrites `from src.old import *` module path."""
        source = "from src.old import *\n"
        entry = _move_entry()
        rewriter = ImportRewriter([entry])

        result = _transform(source, rewriter)
        assert "from src.new import *" in result
        assert rewriter.fixes_applied == 1

    def test_no_match_unchanged(self) -> None:
        """Imports not in the migration map are left unchanged."""
        source = "from src.other import bar\n"
        entry = _move_entry()  # targets src.old.foo
        rewriter = ImportRewriter([entry])

        result = _transform(source, rewriter)
        assert result == source
        assert rewriter.fixes_applied == 0

    def test_multiple_names_one_moved(self) -> None:
        """When one of multiple imported names matches, it is rewritten."""
        source = "from src.old import foo, bar\n"
        entry = _move_entry(old_module="src.old", old_name="foo",
                            new_module="src.new", new_name="foo")
        rewriter = ImportRewriter([entry])

        result = _transform(source, rewriter)
        # foo should be rewritten; bar stays
        assert "foo" in result
        assert "bar" in result
        assert rewriter.fixes_applied == 1


# ---------------------------------------------------------------------------
# StringRefRewriter
# ---------------------------------------------------------------------------


class TestStringRefRewriter:
    """Tests for the StringRefRewriter CST transformer."""

    def test_mock_patch_string_rewrite(self) -> None:
        """Rewrites string in mock.patch('src.old.module.MyClass')."""
        source = 'mock.patch("src.old.module.MyClass")\n'
        entry = _move_entry(
            old_module="src.old.module",
            old_name="MyClass",
            new_module="src.new.module",
            new_name="MyClass",
        )
        rewriter = StringRefRewriter([entry])

        result = _transform(source, rewriter)
        assert '"src.new.module.MyClass"' in result
        assert rewriter.fixes_applied == 1

    def test_importlib_import_module_rewrite(self) -> None:
        """Rewrites importlib.import_module('src.old.utils') module path."""
        source = 'importlib.import_module("src.old.utils")\n'
        entry = _move_entry(
            old_module="src.old.utils",
            old_name="helper",
            new_module="src.new.helpers",
            new_name="helper",
        )
        rewriter = StringRefRewriter([entry])

        result = _transform(source, rewriter)
        assert '"src.new.helpers"' in result
        assert rewriter.fixes_applied == 1

    def test_single_quote_preserved(self) -> None:
        """Single-quote style is preserved."""
        source = "mock.patch('src.old.module.Foo')\n"
        entry = _move_entry(
            old_module="src.old.module",
            old_name="Foo",
            new_module="src.new.module",
            new_name="Foo",
        )
        rewriter = StringRefRewriter([entry])

        result = _transform(source, rewriter)
        assert "'src.new.module.Foo'" in result

    def test_no_match_unchanged(self) -> None:
        """Strings not matching the migration map are left alone."""
        source = 'mock.patch("unrelated.module.Cls")\n'
        entry = _move_entry(
            old_module="src.old",
            old_name="Foo",
            new_module="src.new",
            new_name="Foo",
        )
        rewriter = StringRefRewriter([entry])

        result = _transform(source, rewriter)
        assert result == source
        assert rewriter.fixes_applied == 0

    def test_prefix_match(self) -> None:
        """Rewrites mock.patch('src.old.module.Cls.method') via prefix matching."""
        source = 'mock.patch("src.old.module.Cls.method")\n'
        entry = _move_entry(
            old_module="src.old.module",
            old_name="Cls",
            new_module="src.new.module",
            new_name="Cls",
        )
        rewriter = StringRefRewriter([entry])

        result = _transform(source, rewriter)
        assert '"src.new.module.Cls.method"' in result

    def test_variable_held_path_rewritten(self) -> None:
        """Variable assignment rewritten when holding a matching path in function scope."""
        source = (
            'def test_it():\n'
            '    path = "src.old.module.Symbol"\n'
            '    mock.patch(path)\n'
        )
        entry = _move_entry(
            old_module="src.old.module",
            old_name="Symbol",
            new_module="src.new.module",
            new_name="Symbol",
        )
        rewriter = StringRefRewriter([entry])

        result = _transform(source, rewriter)
        assert '"src.new.module.Symbol"' in result
        assert rewriter.fixes_applied >= 1


# ---------------------------------------------------------------------------
# AllListRewriter
# ---------------------------------------------------------------------------


class TestAllListRewriter:
    """Tests for the AllListRewriter CST transformer."""

    def test_simple_rename_in_all(self) -> None:
        """Updates __all__ entry from old_name to new_name."""
        source = '__all__ = ["old_name", "other"]\n'
        entry = _move_entry(
            old_module="src.mod",
            old_name="old_name",
            new_module="src.mod",
            new_name="new_name",
            migration_type="rename",
        )
        rewriter = AllListRewriter([entry])

        result = _transform(source, rewriter)
        assert '"new_name"' in result
        assert '"other"' in result
        assert '"old_name"' not in result
        assert rewriter.fixes_applied == 1

    def test_no_rename_move_only_unchanged(self) -> None:
        """Move-only migration (name unchanged) leaves __all__ unchanged."""
        source = '__all__ = ["foo"]\n'
        entry = _move_entry(
            old_module="src.old",
            old_name="foo",
            new_module="src.new",
            new_name="foo",
        )
        rewriter = AllListRewriter([entry])

        result = _transform(source, rewriter)
        assert result == source
        assert rewriter.fixes_applied == 0

    def test_multiple_renames(self) -> None:
        """Multiple entries in __all__ are updated."""
        source = '__all__ = ["alpha", "beta"]\n'
        entries = [
            _move_entry(old_module="m", old_name="alpha",
                        new_module="m", new_name="ALPHA", migration_type="rename"),
            _move_entry(old_module="m", old_name="beta",
                        new_module="m", new_name="BETA", migration_type="rename"),
        ]
        rewriter = AllListRewriter(entries)

        result = _transform(source, rewriter)
        assert '"ALPHA"' in result
        assert '"BETA"' in result
        assert rewriter.fixes_applied == 2

    def test_empty_migration_map(self) -> None:
        """Empty migration map means no changes."""
        source = '__all__ = ["foo"]\n'
        rewriter = AllListRewriter([])

        result = _transform(source, rewriter)
        assert result == source
        assert rewriter.fixes_applied == 0

    def test_non_all_assign_unchanged(self) -> None:
        """Assign to a variable other than __all__ is not touched."""
        source = 'EXPORTS = ["old_name"]\n'
        entry = _move_entry(
            old_module="m", old_name="old_name",
            new_module="m", new_name="new_name", migration_type="rename",
        )
        rewriter = AllListRewriter([entry])

        result = _transform(source, rewriter)
        assert result == source
        assert rewriter.fixes_applied == 0


# ---------------------------------------------------------------------------
# apply_fixes (integration)
# ---------------------------------------------------------------------------


class TestApplyFixes:
    """Integration tests for apply_fixes using tmp_path."""

    def test_fix_single_file(self, tmp_path: Path) -> None:
        """Applies migration to a single file with a broken import."""
        target = tmp_path / "consumer.py"
        target.write_text("from src.old import foo\n")

        migration_map = [_move_entry()]
        result = apply_fixes(
            migration_map=migration_map,
            target_files=["consumer.py"],
            root=tmp_path,
        )

        assert result.files_modified == ["consumer.py"]
        assert result.fixes_applied >= 1

        # Verify file contents
        content = target.read_text()
        assert "from src.new import foo" in content

    def test_no_matches_no_modification(self, tmp_path: Path) -> None:
        """File with no matching imports is not modified."""
        target = tmp_path / "consumer.py"
        target.write_text("from src.other import bar\n")

        migration_map = [_move_entry()]
        result = apply_fixes(
            migration_map=migration_map,
            target_files=["consumer.py"],
            root=tmp_path,
        )

        assert result.files_modified == []
        assert result.fixes_applied == 0

    def test_empty_migration_map(self, tmp_path: Path) -> None:
        """Empty migration map returns default FixResult immediately."""
        target = tmp_path / "consumer.py"
        target.write_text("from src.old import foo\n")

        result = apply_fixes(
            migration_map=[],
            target_files=["consumer.py"],
            root=tmp_path,
        )

        assert result.files_modified == []
        assert result.fixes_applied == 0
        # File should be unchanged
        assert target.read_text() == "from src.old import foo\n"

    def test_syntax_error_file_skipped(self, tmp_path: Path) -> None:
        """File with syntax errors is skipped with error logged."""
        broken = tmp_path / "broken.py"
        broken.write_text("def broken(\n")

        migration_map = [_move_entry()]
        result = apply_fixes(
            migration_map=migration_map,
            target_files=["broken.py"],
            root=tmp_path,
        )

        assert result.files_modified == []
        assert len(result.errors) >= 1

    def test_nonexistent_file_skipped(self, tmp_path: Path) -> None:
        """Non-existent target file is added to skipped."""
        migration_map = [_move_entry()]
        result = apply_fixes(
            migration_map=migration_map,
            target_files=["does_not_exist.py"],
            root=tmp_path,
        )

        assert result.files_modified == []
        assert len(result.skipped) >= 1

    def test_non_py_file_skipped(self, tmp_path: Path) -> None:
        """Non-.py files are silently skipped."""
        txt_file = tmp_path / "readme.txt"
        txt_file.write_text("some text")

        migration_map = [_move_entry()]
        result = apply_fixes(
            migration_map=migration_map,
            target_files=["readme.txt"],
            root=tmp_path,
        )

        assert result.files_modified == []
        assert result.fixes_applied == 0

    def test_multiple_files_fixed(self, tmp_path: Path) -> None:
        """Multiple files with broken imports are all fixed."""
        for name in ["a.py", "b.py", "c.py"]:
            (tmp_path / name).write_text("from src.old import foo\n")

        migration_map = [_move_entry()]
        result = apply_fixes(
            migration_map=migration_map,
            target_files=["a.py", "b.py", "c.py"],
            root=tmp_path,
        )

        assert len(result.files_modified) == 3
        assert result.fixes_applied >= 3

        for name in ["a.py", "b.py", "c.py"]:
            content = (tmp_path / name).read_text()
            assert "from src.new import foo" in content

    def test_string_ref_and_import_combined(self, tmp_path: Path) -> None:
        """Both import statements and string refs are rewritten in one pass."""
        target = tmp_path / "test_mod.py"
        target.write_text(
            "from src.old import foo\n"
            "\n"
            'mock.patch("src.old.foo")\n'
        )

        migration_map = [_move_entry()]
        result = apply_fixes(
            migration_map=migration_map,
            target_files=["test_mod.py"],
            root=tmp_path,
        )

        assert result.files_modified == ["test_mod.py"]
        content = target.read_text()
        assert "from src.new import foo" in content
        assert '"src.new.foo"' in content

    def test_all_list_rewrite_combined(self, tmp_path: Path) -> None:
        """__all__ list entries are updated alongside import rewrites."""
        target = tmp_path / "pkg_init.py"
        target.write_text(
            "from src.old import old_name\n"
            '__all__ = ["old_name"]\n'
        )

        entry = _move_entry(
            old_module="src.old",
            old_name="old_name",
            new_module="src.new",
            new_name="new_name",
            migration_type="rename",
        )

        result = apply_fixes(
            migration_map=[entry],
            target_files=["pkg_init.py"],
            root=tmp_path,
        )

        assert result.files_modified == ["pkg_init.py"]
        content = target.read_text()
        assert "from src.new import new_name" in content
        assert '"new_name"' in content
        assert '"old_name"' not in content

    def test_empty_target_files(self, tmp_path: Path) -> None:
        """Empty target file list returns default FixResult."""
        migration_map = [_move_entry()]
        result = apply_fixes(
            migration_map=migration_map,
            target_files=[],
            root=tmp_path,
        )

        assert result.files_modified == []
        assert result.fixes_applied == 0
