# @summary
# Import fixer — rewrites broken imports using libcst CST transformers.
# Takes a migration map (from differ.py) and rewrites import statements,
# string-based references (mock.patch, importlib.import_module), and __all__
# lists across target files. Preserves formatting, comments, and whitespace.
# Exports: apply_fixes
# Deps: libcst, pathlib, import_check.schemas
# @end-summary

"""Import fixer — rewrites broken imports using libcst.

Takes a migration map (from differ.py) and rewrites import statements
across target files. Uses libcst to preserve formatting, comments, and
whitespace. Also handles string-based references in mock.patch() and
importlib.import_module() calls, and __all__ list updates.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Union

import libcst as cst

from .schemas import FixResult, MigrationEntry

logger = logging.getLogger("import_check")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dotted_name_to_str(node: Union[cst.Attribute, cst.Name]) -> str:
    """Convert a libcst Attribute/Name chain to a dotted string."""
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        return _dotted_name_to_str(node.value) + "." + node.attr.value
    return ""


def _str_to_dotted_name(dotted: str) -> Union[cst.Attribute, cst.Name]:
    """Convert a dotted string (e.g. 'a.b.c') into a libcst Attribute/Name tree."""
    parts = dotted.split(".")
    node: Union[cst.Attribute, cst.Name] = cst.Name(parts[0])
    for part in parts[1:]:
        node = cst.Attribute(value=node, attr=cst.Name(part))
    return node


def _extract_simple_string_value(node: cst.BaseExpression) -> str | None:
    """Extract the raw string value from a SimpleString or FormattedString node.

    Returns the unquoted content, or None if the node is not a simple string.
    """
    if isinstance(node, cst.SimpleString):
        # Strip quotes (handles ', ", ''', \""")
        raw = node.value
        if raw.startswith(('"""', "'''")):
            return raw[3:-3]
        if raw.startswith(('"', "'")):
            return raw[1:-1]
    if isinstance(node, cst.ConcatenatedString):
        # Only handle the case where both sides are simple strings
        left = _extract_simple_string_value(node.left)
        right = _extract_simple_string_value(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _make_simple_string(value: str, original: cst.BaseExpression) -> cst.BaseExpression:
    """Create a SimpleString node preserving the quote style of the original."""
    if isinstance(original, cst.SimpleString):
        raw = original.value
        if raw.startswith('"""'):
            return original.with_changes(value=f'"""{value}"""')
        if raw.startswith("'''"):
            return original.with_changes(value=f"'''{value}'''")
        if raw.startswith('"'):
            return original.with_changes(value=f'"{value}"')
        if raw.startswith("'"):
            return original.with_changes(value=f"'{value}'")
    # Fallback: double-quoted string
    return cst.SimpleString(f'"{value}"')


# ---------------------------------------------------------------------------
# ImportRewriter
# ---------------------------------------------------------------------------

class ImportRewriter(cst.CSTTransformer):
    """Rewrites ``from X import Y`` and ``import X`` nodes based on a migration map."""

    def __init__(self, migration_map: list[MigrationEntry]) -> None:
        super().__init__()
        self.fixes_applied: int = 0

        # Lookup: (old_module, old_name) -> MigrationEntry
        self._by_module_name: dict[tuple[str, str], MigrationEntry] = {}
        # Lookup: old_module -> list[MigrationEntry]  (for bare `import X`)
        self._by_module: dict[str, list[MigrationEntry]] = {}

        for entry in migration_map:
            self._by_module_name[(entry.old_module, entry.old_name)] = entry
            self._by_module.setdefault(entry.old_module, []).append(entry)

    def leave_ImportFrom(
        self,
        original_node: cst.ImportFrom,
        updated_node: cst.ImportFrom,
    ) -> cst.ImportFrom:
        """Rewrite ``from <module> import <names>`` nodes."""
        if updated_node.module is None:
            return updated_node

        module_str = _dotted_name_to_str(updated_node.module)

        # Handle star import or non-tuple names (edge cases — skip)
        if isinstance(updated_node.names, cst.ImportStar):
            # Check if the module itself needs rewriting
            entries = self._by_module.get(module_str)
            if entries:
                new_module_str = entries[0].new_module
                updated_node = updated_node.with_changes(
                    module=_str_to_dotted_name(new_module_str),
                )
                self.fixes_applied += 1
            return updated_node

        if not isinstance(updated_node.names, (list, tuple)):
            return updated_node

        new_names: list[cst.ImportAlias] = []
        changed = False

        for alias in updated_node.names:
            if not isinstance(alias, cst.ImportAlias):
                new_names.append(alias)
                continue

            name_str = _dotted_name_to_str(alias.name) if isinstance(alias.name, (cst.Attribute, cst.Name)) else ""
            entry = self._by_module_name.get((module_str, name_str))

            if entry is not None:
                changed = True
                self.fixes_applied += 1

                # Build the replacement alias
                new_alias_name = cst.Name(entry.new_name) if entry.new_name != name_str else alias.name
                # If the module changed, we update it at the statement level below
                # For the name, replace it (keep alias/asname if present)
                new_alias = alias.with_changes(name=new_alias_name)
                new_names.append(new_alias)
            else:
                new_names.append(alias)

        if not changed:
            return updated_node

        # Determine the new module: if all entries point to the same new_module, use it.
        # Otherwise, keep the original module (the name-level changes suffice).
        target_modules = set()
        for alias in updated_node.names:
            if isinstance(alias, cst.ImportAlias):
                name_str = _dotted_name_to_str(alias.name) if isinstance(alias.name, (cst.Attribute, cst.Name)) else ""
                entry = self._by_module_name.get((module_str, name_str))
                if entry:
                    target_modules.add(entry.new_module)

        new_module_node = updated_node.module
        if len(target_modules) == 1:
            new_module_str = target_modules.pop()
            if new_module_str != module_str:
                new_module_node = _str_to_dotted_name(new_module_str)

        return updated_node.with_changes(
            module=new_module_node,
            names=new_names,
        )

    def leave_Import(
        self,
        original_node: cst.Import,
        updated_node: cst.Import,
    ) -> cst.Import:
        """Rewrite ``import X`` nodes."""
        if isinstance(updated_node.names, cst.ImportStar):
            return updated_node

        if not isinstance(updated_node.names, (list, tuple)):
            return updated_node

        new_names: list[cst.ImportAlias] = []
        changed = False

        for alias in updated_node.names:
            if not isinstance(alias, cst.ImportAlias):
                new_names.append(alias)
                continue

            module_str = _dotted_name_to_str(alias.name) if isinstance(alias.name, (cst.Attribute, cst.Name)) else ""
            entries = self._by_module.get(module_str)

            if entries:
                # Use the first entry's new_module (bare imports rewrite the module path)
                new_module_str = entries[0].new_module
                if new_module_str != module_str:
                    changed = True
                    self.fixes_applied += 1
                    new_alias = alias.with_changes(
                        name=_str_to_dotted_name(new_module_str),
                    )
                    new_names.append(new_alias)
                else:
                    new_names.append(alias)
            else:
                new_names.append(alias)

        if not changed:
            return updated_node

        return updated_node.with_changes(names=new_names)


# ---------------------------------------------------------------------------
# StringRefRewriter
# ---------------------------------------------------------------------------

class StringRefRewriter(cst.CSTTransformer):
    """Rewrites string arguments in mock.patch() and importlib.import_module() calls."""

    # Function names/attribute chains that take a dotted-path string as first arg
    _PATCH_NAMES = {"patch", "mock.patch", "unittest.mock.patch"}
    _IMPORT_MODULE_NAMES = {"import_module", "importlib.import_module"}
    _ALL_TARGET_NAMES = _PATCH_NAMES | _IMPORT_MODULE_NAMES | {"patch.object"}

    def __init__(self, migration_map: list[MigrationEntry]) -> None:
        super().__init__()
        self.fixes_applied: int = 0

        # Build a lookup for dotted paths:
        # "old_module.old_name" -> (new_module, new_name)
        # Also keep module-only rewrites for import_module calls
        self._path_map: dict[str, str] = {}
        self._module_map: dict[str, str] = {}

        for entry in migration_map:
            # Full dotted path: old_module.old_name -> new_module.new_name
            old_full = f"{entry.old_module}.{entry.old_name}"
            new_full = f"{entry.new_module}.{entry.new_name}"
            self._path_map[old_full] = new_full

            # Module-level mapping for import_module("old.module")
            if entry.old_module != entry.new_module:
                self._module_map[entry.old_module] = entry.new_module

        # Simple dataflow: track variable assignments in function scopes
        # {var_name: (assignment_node_ref, string_value)}
        self._scope_vars: dict[str, str] = {}
        self._scope_depth: int = 0

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        """Enter a function scope — reset tracked variables."""
        self._scope_depth += 1
        if self._scope_depth == 1:
            self._scope_vars = {}
        return True

    def leave_FunctionDef(
        self,
        original_node: cst.FunctionDef,
        updated_node: cst.FunctionDef,
    ) -> cst.FunctionDef:
        """Exit a function scope."""
        self._scope_depth -= 1
        if self._scope_depth == 0:
            self._scope_vars = {}
        return updated_node

    def visit_SimpleStatementLine(self, node: cst.SimpleStatementLine) -> bool:
        """Track simple string assignments for dataflow analysis."""
        if self._scope_depth < 1:
            return True

        for stmt in node.body:
            if isinstance(stmt, cst.Assign) and len(stmt.targets) == 1:
                target = stmt.targets[0].target
                if isinstance(target, cst.Name):
                    str_val = _extract_simple_string_value(stmt.value)
                    if str_val is not None:
                        self._scope_vars[target.value] = str_val
        return True

    def _rewrite_string_arg(
        self, arg_node: cst.BaseExpression, for_import_module: bool = False,
    ) -> cst.BaseExpression | None:
        """Try to rewrite a string argument if it matches the migration map.

        Returns the new node, or None if no match.
        """
        str_val = _extract_simple_string_value(arg_node)
        if str_val is None:
            return None

        # Try full dotted path match first (mock.patch("old.module.Symbol"))
        if str_val in self._path_map:
            new_val = self._path_map[str_val]
            return _make_simple_string(new_val, arg_node)

        # Try module-only match (importlib.import_module("old.module"))
        if for_import_module and str_val in self._module_map:
            new_val = self._module_map[str_val]
            return _make_simple_string(new_val, arg_node)

        # Try prefix match: if the string starts with an old dotted path
        for old_path, new_path in self._path_map.items():
            if str_val.startswith(old_path + ".") or str_val.startswith(old_path + ":"):
                sep = str_val[len(old_path)]
                new_val = new_path + sep + str_val[len(old_path) + 1:]
                return _make_simple_string(new_val, arg_node)

        for old_mod, new_mod in self._module_map.items():
            if str_val.startswith(old_mod + "."):
                new_val = new_mod + str_val[len(old_mod):]
                return _make_simple_string(new_val, arg_node)

        return None

    def _is_target_call(self, func: cst.BaseExpression) -> tuple[bool, bool]:
        """Check if a Call's function matches our target patterns.

        Returns (is_target, is_import_module).
        """
        func_str = ""
        if isinstance(func, cst.Name):
            func_str = func.value
        elif isinstance(func, cst.Attribute):
            func_str = _dotted_name_to_str(func)

        if func_str in self._PATCH_NAMES or func_str == "patch.object":
            return True, False
        if func_str in self._IMPORT_MODULE_NAMES:
            return True, True
        return False, False

    def leave_SimpleStatementLine(
        self,
        original_node: cst.SimpleStatementLine,
        updated_node: cst.SimpleStatementLine,
    ) -> cst.SimpleStatementLine:
        """Rewrite variable assignments whose string values match the migration map.

        This handles simple dataflow:
            path = "old.module.Symbol"
            mock.patch(path)
        We rewrite the assignment itself.
        """
        if self._scope_depth < 1:
            return updated_node

        new_body: list[cst.BaseSmallStatement] = []
        changed = False

        for stmt in updated_node.body:
            if isinstance(stmt, cst.Assign) and len(stmt.targets) == 1:
                target = stmt.targets[0].target
                if isinstance(target, cst.Name):
                    str_val = _extract_simple_string_value(stmt.value)
                    if str_val is not None:
                        # Try both full-path and module-only matches
                        new_node = self._rewrite_string_arg(stmt.value, for_import_module=True)
                        if new_node is not None:
                            changed = True
                            self.fixes_applied += 1
                            stmt = stmt.with_changes(value=new_node)
            new_body.append(stmt)

        if changed:
            return updated_node.with_changes(body=new_body)
        return updated_node

    def leave_Call(
        self,
        original_node: cst.Call,
        updated_node: cst.Call,
    ) -> cst.Call:
        """Rewrite string arguments in mock.patch() and importlib.import_module()."""
        is_target, is_import_module = self._is_target_call(updated_node.func)
        if not is_target:
            return updated_node

        if not updated_node.args:
            return updated_node

        first_arg = updated_node.args[0]

        # Direct string argument
        new_value = self._rewrite_string_arg(first_arg.value, for_import_module=is_import_module)
        if new_value is not None:
            new_args = [first_arg.with_changes(value=new_value)] + list(updated_node.args[1:])
            self.fixes_applied += 1
            return updated_node.with_changes(args=new_args)

        # Variable reference — check scope-tracked variables
        if isinstance(first_arg.value, cst.Name) and self._scope_depth > 0:
            var_name = first_arg.value.value
            if var_name in self._scope_vars:
                # The actual rewrite happens in leave_SimpleStatementLine
                # for the assignment. Here we just note it's tracked.
                pass

        return updated_node


# ---------------------------------------------------------------------------
# AllListRewriter
# ---------------------------------------------------------------------------

class AllListRewriter(cst.CSTTransformer):
    """Rewrites ``__all__ = [...]`` lists to update renamed symbols."""

    def __init__(self, migration_map: list[MigrationEntry]) -> None:
        super().__init__()
        self.fixes_applied: int = 0

        # Lookup: old_name -> new_name (only where names actually changed)
        self._name_map: dict[str, str] = {}
        for entry in migration_map:
            if entry.old_name != entry.new_name:
                self._name_map[entry.old_name] = entry.new_name

    def leave_Assign(
        self,
        original_node: cst.Assign,
        updated_node: cst.Assign,
    ) -> cst.Assign:
        """Rewrite __all__ = [...] if any element names changed."""
        if not self._name_map:
            return updated_node

        # Check that target is __all__
        if len(updated_node.targets) != 1:
            return updated_node

        target = updated_node.targets[0].target
        if not isinstance(target, cst.Name) or target.value != "__all__":
            return updated_node

        value = updated_node.value
        if not isinstance(value, (cst.List, cst.Tuple)):
            return updated_node

        new_elements: list[cst.BaseElement] = []
        changed = False

        for element in value.elements:
            if isinstance(element, cst.Element):
                str_val = _extract_simple_string_value(element.value)
                if str_val is not None and str_val in self._name_map:
                    new_str = self._name_map[str_val]
                    new_element = element.with_changes(
                        value=_make_simple_string(new_str, element.value),
                    )
                    new_elements.append(new_element)
                    changed = True
                    self.fixes_applied += 1
                else:
                    new_elements.append(element)
            else:
                new_elements.append(element)

        if not changed:
            return updated_node

        new_value = value.with_changes(elements=new_elements)
        return updated_node.with_changes(value=new_value)


# ---------------------------------------------------------------------------
# Transformer builders (public interface for testing)
# ---------------------------------------------------------------------------

def _build_import_rewriter(migration_map: list[MigrationEntry]) -> ImportRewriter:
    """Build a libcst transformer that rewrites import statements.

    Creates a CSTTransformer subclass that matches ImportFrom and Import
    nodes against the migration map and produces rewritten nodes.

    Args:
        migration_map: List of migrations to apply.

    Returns:
        A libcst CSTTransformer instance.
    """
    return ImportRewriter(migration_map)


def _build_string_ref_rewriter(migration_map: list[MigrationEntry]) -> StringRefRewriter:
    """Build a libcst transformer that rewrites string-based references.

    Matches:
    - mock.patch("old.module.path") -> mock.patch("new.module.path")
    - importlib.import_module("old.module") -> importlib.import_module("new.module")
    - Simple single-assignment string literals in the same function scope
      (e.g., path = "old.module"; importlib.import_module(path))

    Args:
        migration_map: List of migrations to apply.

    Returns:
        A libcst CSTTransformer instance.
    """
    return StringRefRewriter(migration_map)


def _build_all_rewriter(migration_map: list[MigrationEntry]) -> AllListRewriter:
    """Build a libcst transformer that updates __all__ lists.

    Matches __all__ = [...] assignments and updates string entries
    that correspond to renamed symbols in the migration map.

    Args:
        migration_map: List of migrations to apply.

    Returns:
        A libcst CSTTransformer instance.
    """
    return AllListRewriter(migration_map)


# ---------------------------------------------------------------------------
# File-level application
# ---------------------------------------------------------------------------

def _apply_transformers_to_file(
    file_path: Path,
    transformers: list,
) -> tuple[bool, list[str]]:
    """Parse a file with libcst, apply transformers, and write back if changed.

    Args:
        file_path: Path to the Python source file.
        transformers: List of libcst CSTTransformer instances to apply sequentially.

    Returns:
        Tuple of (was_modified: bool, errors: list[str]).
        errors contains descriptions of any non-fatal issues encountered.
    """
    errors: list[str] = []

    try:
        source = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"Cannot read {file_path}: {exc}")
        return False, errors

    try:
        tree = cst.parse_module(source)
    except cst.ParserSyntaxError as exc:
        errors.append(f"libcst parse failed for {file_path}: {exc}")
        return False, errors

    original_code = tree.code
    modified_tree = tree

    for transformer in transformers:
        try:
            modified_tree = modified_tree.visit(transformer)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Transformer {type(transformer).__name__} failed on {file_path}: {exc}")

    if modified_tree.code != original_code:
        try:
            file_path.write_text(modified_tree.code, encoding="utf-8")
        except OSError as exc:
            errors.append(f"Cannot write {file_path}: {exc}")
            return False, errors
        return True, errors

    return False, errors


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def apply_fixes(
    migration_map: list[MigrationEntry],
    target_files: list[str],
    root: Path,
) -> FixResult:
    """Apply import fixes to target files based on the migration map.

    For each target file:
    1. Parse with libcst.
    2. Walk ImportFrom and Import nodes, matching against migration_map.
    3. Rewrite matched imports to use the new module/name.
    4. Walk Call nodes for mock.patch() and importlib.import_module() string args.
    5. Walk Assign nodes for __all__ list updates.
    6. Write back the modified source if any changes were made.

    Files that fail to parse with libcst are logged and skipped.
    Individual fix failures within a file do not abort the entire file.

    Args:
        migration_map: List of MigrationEntry from differ.diff_inventories().
        target_files: List of Python file paths to fix (relative to root).
        root: Project root directory.

    Returns:
        FixResult summarizing what was changed and what was skipped.
    """
    result = FixResult()

    if not migration_map:
        return result

    for rel_path in target_files:
        file_path = root / rel_path

        if not file_path.exists():
            logger.warning("Target file does not exist: %s", file_path)
            result.skipped.append(f"File not found: {rel_path}")
            continue

        if not file_path.suffix == ".py":
            continue

        # Build fresh transformers per file so fix counts are per-file
        import_rewriter = _build_import_rewriter(migration_map)
        string_rewriter = _build_string_ref_rewriter(migration_map)
        all_rewriter = _build_all_rewriter(migration_map)

        transformers = [import_rewriter, string_rewriter, all_rewriter]

        was_modified, errors = _apply_transformers_to_file(file_path, transformers)

        total_fixes = (
            import_rewriter.fixes_applied
            + string_rewriter.fixes_applied
            + all_rewriter.fixes_applied
        )

        if was_modified:
            result.files_modified.append(str(rel_path))
            result.fixes_applied += total_fixes
            logger.info(
                "Fixed %d import(s) in %s",
                total_fixes,
                rel_path,
            )

        if errors:
            result.errors.extend(errors)
            for err in errors:
                logger.warning("Fix error: %s", err)

    return result
