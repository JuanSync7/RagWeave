#!/usr/bin/env python3
# @summary
# One-off tool that repairs encapsulation violations flagged by import_check
# by (1) promoting reached-into symbols to package-level __init__.py re-exports
# and (2) rewriting violating imports to use the package path.
# Exports: main, collect_violations, generate_reexports, rewrite_imports
# Deps: ast, import_check
# @end-summary
"""Auto-fix encapsulation violations reported by ``import_check``.

For each violating import of the form ``from pkg.sub import sym``, this
script:

1. Groups violations by the target package ``pkg``.
2. Writes a re-export block to ``pkg/__init__.py`` so ``sym`` becomes
   importable from ``pkg`` directly. Existing content is preserved.
3. Rewrites each violating import statement in-place so it imports
   ``sym`` from ``pkg`` instead of ``pkg.sub``.
4. Re-runs ``import_check`` to verify the violations are gone, and
   ``compileall`` to verify every rewritten file still parses.

Usage::

    python scripts/fix_encapsulation.py              # apply fixes
    python scripts/fix_encapsulation.py --dry-run    # preview only
    python scripts/fix_encapsulation.py --only src.vector_db.common
        # limit the fix to a single target package (useful for debugging)

This tool is intentionally idempotent: running it a second time on a
clean codebase should be a no-op.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

# Ensure we can import import_check when run from any CWD.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from import_check import check  # noqa: E402
from import_check.schemas import ImportError as CheckError  # noqa: E402
from import_check.schemas import ImportErrorType  # noqa: E402


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ViolatingImport:
    """One violating import statement, normalized.

    A single ``from X.sub import A, B, C`` statement may yield multiple
    violations from the checker (one per symbol). This object represents the
    statement-level view: one entry per (file, lineno) pair, carrying every
    symbol that statement brings in from the violating submodule.
    """

    file_path: Path  # absolute path to the file containing the import
    lineno: int  # 1-based line number of the `from` keyword
    source_submodule: str  # e.g. "src.vector_db.common.schemas"
    target_package: str  # e.g. "src.vector_db.common"
    symbols: tuple[str, ...]  # sorted tuple of symbol names


# ---------------------------------------------------------------------------
# Step 1: collect violations from import_check and normalize
# ---------------------------------------------------------------------------


def collect_violations(
    root: Path, only_package: str | None = None
) -> tuple[list[ViolatingImport], list[tuple[str, int, str]]]:
    """Run import_check and return normalized per-statement violations.

    Returns ``(auto_fixable, bare_imports)``. ``bare_imports`` is the list
    of ``(file, lineno, module)`` entries that could not be auto-fixed
    because they use ``import X.Y.Z`` form — these are reported separately
    at the end so the user can handle them manually.

    Multiple symbols reached from the same submodule on the same line are
    collapsed into a single ``ViolatingImport``.
    """
    errors = check(root=root)

    bare_imports: list[tuple[str, int, str]] = []

    # Group by (file, lineno, source_submodule) so multi-symbol imports
    # collapse to one entry.
    grouped: dict[tuple[str, int, str], set[str]] = defaultdict(set)
    for err in errors:
        if err.error_type != ImportErrorType.ENCAPSULATION_VIOLATION:
            continue
        # Bare module imports (`import X.Y.Z` / `import X.Y.Z as alias`)
        # have an empty `name` in the checker output. We skip them here
        # because the mechanical fix for them is different (you have to
        # rewrite every attribute access `_alias.foo` too), and they're
        # reported at the end for human triage.
        if not err.name:
            bare_imports.append((err.file_path, err.lineno, err.module))
            continue
        parts = err.module.split(".")
        target = ".".join(parts[:-1])
        if only_package is not None and target != only_package:
            continue
        grouped[(err.file_path, err.lineno, err.module)].add(err.name)

    result: list[ViolatingImport] = []
    for (file_path, lineno, source_submodule), symbols in grouped.items():
        target_parts = source_submodule.split(".")[:-1]
        target_package = ".".join(target_parts)
        result.append(
            ViolatingImport(
                file_path=(root / file_path).resolve(),
                lineno=lineno,
                source_submodule=source_submodule,
                target_package=target_package,
                symbols=tuple(sorted(symbols)),
            )
        )

    # Stable ordering: by file then line.
    result.sort(key=lambda v: (str(v.file_path), v.lineno))
    # Deduplicate bare imports (checker may report each module once per
    # line even for a single `import` statement).
    bare_imports = sorted(set(bare_imports))
    return result, bare_imports


# ---------------------------------------------------------------------------
# Step 2: generate / update __init__.py re-exports
# ---------------------------------------------------------------------------

REEXPORT_MARKER = "# --- Auto-generated re-exports (fix_encapsulation.py) ---"


def _existing_exports_in_init(init_path: Path) -> set[str]:
    """Return the set of names already importable from this __init__.py.

    Scans top-level ``from X import Y`` and assignments (``__all__``, module
    constants, etc.). Conservative: anything the AST sees as a top-level
    binding counts as "already exported".
    """
    if not init_path.is_file():
        return set()
    try:
        tree = ast.parse(init_path.read_text(encoding="utf-8"))
    except SyntaxError:
        return set()

    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    names.add(tgt.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


def _format_reexport_block(
    target_package: str, symbols_by_submodule: dict[str, set[str]]
) -> str:
    """Build the re-export block for a package's __init__.py.

    Uses absolute imports (matching the rest of the codebase).
    """
    lines = [REEXPORT_MARKER]
    for submodule in sorted(symbols_by_submodule.keys()):
        syms = sorted(symbols_by_submodule[submodule])
        if not syms:
            continue
        if len(syms) == 1:
            lines.append(f"from {submodule} import {syms[0]}")
        else:
            lines.append(f"from {submodule} import (")
            for s in syms:
                lines.append(f"    {s},")
            lines.append(")")
    return "\n".join(lines) + "\n"


def plan_reexports(
    violations: list[ViolatingImport], root: Path
) -> dict[Path, tuple[str, dict[str, set[str]]]]:
    """For each target package, determine which symbols need re-exporting.

    Returns a mapping ``{__init__.py path: (package_dotted, {submodule: {symbols}})}``.
    Skips symbols that are already exported from the package (idempotent).
    """
    # First pass: collect all (submodule, symbol) pairs per target package.
    per_pkg: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for v in violations:
        for sym in v.symbols:
            per_pkg[v.target_package][v.source_submodule].add(sym)

    # Second pass: filter out symbols already exported.
    result: dict[Path, tuple[str, dict[str, set[str]]]] = {}
    for pkg, by_sub in per_pkg.items():
        init_path = root / Path(*pkg.split(".")) / "__init__.py"
        already = _existing_exports_in_init(init_path)
        filtered: dict[str, set[str]] = {}
        for submodule, syms in by_sub.items():
            missing = {s for s in syms if s not in already}
            if missing:
                filtered[submodule] = missing
        if filtered:
            result[init_path] = (pkg, filtered)
    return result


def apply_reexport_plan(
    plan: dict[Path, tuple[str, dict[str, set[str]]]], dry_run: bool
) -> int:
    """Write re-export blocks to __init__.py files.

    Returns the number of symbols promoted (sum across all packages).
    """
    total_symbols = 0
    for init_path, (pkg, by_sub) in plan.items():
        block = _format_reexport_block(pkg, by_sub)
        n_syms = sum(len(s) for s in by_sub.values())
        total_symbols += n_syms
        rel = init_path.relative_to(_REPO_ROOT)
        print(
            f"  + re-exports in {rel} ({n_syms} symbols from "
            f"{len(by_sub)} submodule{'s' if len(by_sub) != 1 else ''})"
        )
        if dry_run:
            continue
        init_path.parent.mkdir(parents=True, exist_ok=True)
        existing = init_path.read_text(encoding="utf-8") if init_path.is_file() else ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        if existing and REEXPORT_MARKER in existing:
            # Already has a managed block — replace it. Find the marker and
            # replace everything from it to the end of the file (the managed
            # block always lives at the bottom of __init__.py).
            idx = existing.index(REEXPORT_MARKER)
            existing = existing[:idx].rstrip() + "\n\n"
        new = existing + ("\n" if existing and not existing.endswith("\n\n") else "") + block
        init_path.write_text(new, encoding="utf-8")
    return total_symbols


# ---------------------------------------------------------------------------
# Step 3: rewrite violating imports in source files
# ---------------------------------------------------------------------------


def _find_importfrom_span(
    source_lines: list[str], lineno: int
) -> tuple[int, int] | None:
    """Return the (start_line, end_line) span of the ImportFrom at *lineno*.

    Both bounds are 0-indexed and inclusive. Handles parenthesized
    multi-line imports by parsing a source snippet and letting ast report
    ``end_lineno``.
    """
    full_source = "".join(source_lines)
    try:
        tree = ast.parse(full_source)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.lineno == lineno:
            end = node.end_lineno or node.lineno
            return (node.lineno - 1, end - 1)
    return None


def _rewrite_statement(
    source_lines: list[str], start: int, end: int, violation: ViolatingImport
) -> tuple[list[str], bool]:
    """Replace the import statement with one targeting the package.

    This is a minimal rewrite that preserves the statement's indentation
    (for imports nested inside TYPE_CHECKING / try / functions) but drops
    any trailing comment on the original line — acceptable for mechanical
    cleanup.

    Returns ``(new_lines, changed)``.
    """
    # Capture the original indentation from the first line.
    original_first = source_lines[start]
    indent = original_first[: len(original_first) - len(original_first.lstrip())]

    # Also preserve any leading "# type: ignore" / similar markers on the
    # last line by refusing to rewrite if we see one. The rewrite might
    # break type-checker suppressions.
    joined = "".join(source_lines[start : end + 1])
    if "# type:" in joined and "ignore" in joined:
        return source_lines, False

    # Build the replacement line.
    sorted_syms = list(violation.symbols)
    if len(sorted_syms) == 1:
        new_line = (
            f"{indent}from {violation.target_package} import {sorted_syms[0]}\n"
        )
    else:
        new_line_parts = [f"{indent}from {violation.target_package} import ("]
        for sym in sorted_syms:
            new_line_parts.append(f"{indent}    {sym},")
        new_line_parts.append(f"{indent})")
        new_line = "\n".join(new_line_parts) + "\n"

    new_lines = source_lines[:start] + [new_line] + source_lines[end + 1 :]
    return new_lines, True


def _extract_statement_symbols(
    source_lines: list[str], lineno: int
) -> tuple[str | None, set[str]]:
    """Parse the ImportFrom at *lineno* and return its module + symbol names.

    Returns ``(module_dotted, {symbol_names})``. Used to confirm that the
    statement on disk actually matches what the checker flagged — we only
    rewrite when the set of symbols in the file exactly equals the set of
    violating symbols (so we never silently drop a symbol).
    """
    try:
        tree = ast.parse("".join(source_lines))
    except SyntaxError:
        return None, set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.lineno == lineno:
            names: set[str] = set()
            for alias in node.names:
                # We record the source name (not the alias target) so that
                # `from X.sub import A as AA` stays matched against the
                # checker's report of violating symbol `A`.
                names.add(alias.name)
            return node.module, names
    return None, set()


def apply_import_rewrites(
    violations: list[ViolatingImport], dry_run: bool
) -> tuple[int, int, list[str]]:
    """Rewrite violating imports in-place.

    Returns ``(rewrote, skipped, notes)``. ``notes`` is a list of
    human-readable reasons for each skip so the user can triage remainders
    manually.
    """
    # Group by file so we only read/write each file once, and by descending
    # lineno so earlier rewrites don't shift later linenos.
    by_file: dict[Path, list[ViolatingImport]] = defaultdict(list)
    for v in violations:
        by_file[v.file_path].append(v)

    rewrote = 0
    skipped = 0
    notes: list[str] = []

    for file_path, file_violations in sorted(by_file.items()):
        if not file_path.is_file():
            for v in file_violations:
                skipped += 1
                notes.append(
                    f"  - {file_path}:{v.lineno}  (file not found)"
                )
            continue

        source = file_path.read_text(encoding="utf-8")
        source_lines = source.splitlines(keepends=True)

        # Descending lineno so we can edit in place without re-indexing.
        file_violations.sort(key=lambda x: x.lineno, reverse=True)

        for v in file_violations:
            # Verify the statement on disk matches our expectations.
            stmt_module, stmt_symbols = _extract_statement_symbols(
                source_lines, v.lineno
            )
            if stmt_module != v.source_submodule:
                skipped += 1
                notes.append(
                    f"  - {file_path.relative_to(_REPO_ROOT)}:{v.lineno}  "
                    f"(statement module mismatch: file has "
                    f"{stmt_module!r}, checker flagged {v.source_submodule!r})"
                )
                continue
            if set(v.symbols) != stmt_symbols:
                skipped += 1
                notes.append(
                    f"  - {file_path.relative_to(_REPO_ROOT)}:{v.lineno}  "
                    f"(symbol-set mismatch; statement imports "
                    f"{sorted(stmt_symbols)}, checker flagged "
                    f"{list(v.symbols)} — mixed violating+non-violating "
                    f"symbols not auto-rewritten)"
                )
                continue

            span = _find_importfrom_span(source_lines, v.lineno)
            if span is None:
                skipped += 1
                notes.append(
                    f"  - {file_path.relative_to(_REPO_ROOT)}:{v.lineno}  "
                    f"(could not locate AST node)"
                )
                continue
            start, end = span
            source_lines, changed = _rewrite_statement(
                source_lines, start, end, v
            )
            if changed:
                rewrote += 1
            else:
                skipped += 1
                notes.append(
                    f"  - {file_path.relative_to(_REPO_ROOT)}:{v.lineno}  "
                    f"(rewrite refused — likely has # type: ignore)"
                )

        if not dry_run:
            file_path.write_text("".join(source_lines), encoding="utf-8")

    return rewrote, skipped, notes


# ---------------------------------------------------------------------------
# Step 4: verify
# ---------------------------------------------------------------------------


def run_compile_check(root: Path) -> bool:
    """Run ``python -m compileall`` across the project source tree."""
    print("\n[verify] running compileall on src/ server/ config/ import_check/ ...")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "compileall",
            "-q",
            "src",
            "server",
            "config",
            "import_check",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("  FAILED:")
        print(result.stdout)
        print(result.stderr)
        return False
    print("  ok")
    return True


def run_import_check(root: Path) -> tuple[int, int]:
    """Return ``(total_errors, encapsulation_errors)`` after the rewrite."""
    errors = check(root=root)
    encap = sum(
        1
        for e in errors
        if e.error_type == ImportErrorType.ENCAPSULATION_VIOLATION
    )
    return len(errors), encap


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="preview changes without writing any files",
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help="restrict the fix to a single target package (dotted path)",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="skip the compile + re-run import_check verification step",
    )
    args = parser.parse_args()

    root = _REPO_ROOT

    # --- Step 0: snapshot the "before" counts so the final verify has
    # something honest to compare against. ---
    before_total, before_encap = run_import_check(root)

    # --- Step 1: collect ---
    print(">>> collecting encapsulation violations from import_check ...")
    violations, bare_imports = collect_violations(root, only_package=args.only)
    if not violations and not bare_imports:
        print("  nothing to do — no encapsulation violations found.")
        return 0
    if not violations:
        print(
            "  no auto-fixable violations, but "
            f"{len(bare_imports)} bare `import X.Y.Z` violation(s) remain."
        )
        _print_bare_imports(bare_imports)
        return 0

    # Summary
    distinct_files = len({v.file_path for v in violations})
    distinct_targets = len({v.target_package for v in violations})
    total_symbols = sum(len(v.symbols) for v in violations)
    print(
        f"  found {len(violations)} violating statement(s) across "
        f"{distinct_files} file(s), {distinct_targets} target package(s), "
        f"promoting {total_symbols} symbol(s)"
    )
    if bare_imports:
        print(
            f"  (also found {len(bare_imports)} bare `import X.Y.Z` "
            "violation(s) — reported at the end, require manual fix)"
        )

    # --- Step 2: plan re-exports ---
    print("\n>>> planning __init__.py re-export updates ...")
    plan = plan_reexports(violations, root)
    if not plan:
        print("  nothing to promote — every symbol is already re-exported.")
    else:
        print(f"  will update {len(plan)} __init__.py file(s):")
        promoted = apply_reexport_plan(plan, dry_run=args.dry_run)
        print(f"  total symbols promoted: {promoted}")

    # --- Step 3: rewrite imports ---
    print("\n>>> rewriting violating import statements ...")
    rewrote, skipped, notes = apply_import_rewrites(violations, dry_run=args.dry_run)
    print(f"  rewrote:  {rewrote}")
    print(f"  skipped:  {skipped}")
    if notes:
        print("\n  skip details:")
        for note in notes[:20]:
            print(note)
        if len(notes) > 20:
            print(f"  ... and {len(notes) - 20} more")

    if args.dry_run:
        print("\n[dry-run] no files were modified.")
        return 0

    # --- Step 4: verify ---
    if args.skip_verify:
        print("\n[skip-verify] not running compile/import_check verification.")
        return 0

    ok = run_compile_check(root)
    if not ok:
        print("\n!!! compile check FAILED after rewrite — inspect the output above.")
        return 2

    print("\n[verify] running import_check ...")
    after_total, after_encap = run_import_check(root)
    print(
        f"  encapsulation violations (project-wide): "
        f"{before_encap} -> {after_encap}  (delta: {before_encap - after_encap})"
    )
    print(
        f"  total import_check errors (project-wide): "
        f"{before_total} -> {after_total}  (delta: {before_total - after_total})"
    )

    # Sanity: we should have made at least some progress proportional to
    # the number of rewritten statements.
    if rewrote > 0 and after_encap >= before_encap:
        print(
            "!!! rewrote statements but encapsulation count did not drop — "
            "something is wrong. Inspect manually."
        )
        return 2

    # Surface any bare-import violations for manual triage.
    if bare_imports:
        _print_bare_imports(bare_imports)

    print("\n✓ encapsulation repair complete.")
    return 0


def _print_bare_imports(bare_imports: list[tuple[str, int, str]]) -> None:
    """Render the list of non-auto-fixable `import X.Y.Z` violations."""
    print(
        f"\n--- {len(bare_imports)} bare `import X.Y.Z` violation(s) "
        "(NOT auto-fixed — require manual decision) ---"
    )
    for file_path, lineno, module in bare_imports:
        print(f"  {file_path}:{lineno}  import {module}")
    print(
        "\nOptions for each:\n"
        "  (a) leave as-is and add `# import_check: ignore` on the line\n"
        "  (b) rewrite as `from <parent> import <submodule> as alias` "
        "(requires the parent __init__ to re-export the submodule)\n"
        "  (c) refactor the module-object usage entirely to import "
        "the symbols you actually need."
    )


if __name__ == "__main__":
    sys.exit(main())
