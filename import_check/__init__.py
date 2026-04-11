# @summary
# Public API facade for the import_check tool.
# Provides three entry points: fix() for deterministic import rewriting,
# check() for smoke-testing all imports, and run() for fix-then-check.
# Loads configuration from pyproject.toml [tool.import_check] with overrides.
# Exports: fix, check, run, ImportCheckConfig, RunResult, FixResult, ImportError
# Deps: tomllib/tomli, logging, pathlib, import_check.schemas,
#       import_check.inventory, import_check.differ, import_check.fixer,
#       import_check.checker
# @end-summary

"""Public API facade for the import_check tool.

Provides three entry points:

- :func:`fix` — deterministic import rewriting based on git-diff inventory.
- :func:`check` — smoke-test all imports for resolution and encapsulation.
- :func:`run` — fix then check (the full pipeline).

Configuration is loaded from ``pyproject.toml`` ``[tool.import_check]`` section
with programmatic overrides applied on top.
"""

from __future__ import annotations

import logging
from dataclasses import fields
from pathlib import Path

from .schemas import (
    FixResult,
    ImportCheckConfig,
    ImportError,
    RunResult,
)

__all__ = [
    "fix",
    "check",
    "run",
    "ImportCheckConfig",
    "RunResult",
    "FixResult",
    "ImportError",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_config(root: Path, **overrides: object) -> ImportCheckConfig:
    """Load configuration with resolution order: defaults < pyproject.toml < overrides.

    Reads ``[tool.import_check]`` from ``pyproject.toml`` at *root* (if it exists),
    merges with dataclass defaults, then applies any keyword overrides.

    Args:
        root: Project root directory containing ``pyproject.toml``.
        **overrides: Keyword arguments that override both defaults and file values.

    Returns:
        Fully resolved :class:`ImportCheckConfig`.
    """
    # --- 1. Start with dataclass defaults (implicit via constructor) ---
    defaults: dict[str, object] = {}

    # --- 2. Read pyproject.toml if present ---
    pyproject_path = root / "pyproject.toml"
    file_values: dict[str, object] = {}

    if pyproject_path.is_file():
        try:
            import tomllib  # Python 3.11+
        except ModuleNotFoundError:
            import tomli as tomllib  # type: ignore[no-redef]

        try:
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)
            file_values = data.get("tool", {}).get("import_check", {})
        except Exception:  # noqa: BLE001
            logging.getLogger("import_check").warning(
                "Failed to parse pyproject.toml at %s, using defaults", pyproject_path,
            )

    # --- 3. Merge: defaults < file < overrides ---
    # Collect valid field names from the dataclass.
    valid_fields = {f.name for f in fields(ImportCheckConfig)}

    merged: dict[str, object] = {}

    # Apply file values (only recognised keys).
    for key, value in file_values.items():
        if key in valid_fields:
            merged[key] = value

    # Apply programmatic overrides (highest priority).
    for key, value in overrides.items():
        if key in valid_fields:
            merged[key] = value

    # Always set root.
    merged["root"] = root

    return ImportCheckConfig(**merged)  # type: ignore[arg-type]


def _setup_logging(config: ImportCheckConfig) -> logging.Logger:
    """Configure the ``import_check`` logger with the level from *config*.

    Format: ``%(levelname)s: %(message)s``.

    Args:
        config: Configuration with ``log_level`` field.

    Returns:
        The configured :class:`logging.Logger`.
    """
    logger = logging.getLogger("import_check")
    logger.setLevel(config.log_level.upper())

    # Avoid duplicate handlers on repeated calls.
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger.addHandler(handler)

    return logger


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def fix(root: str | Path | None = None, **config_overrides: object) -> FixResult:
    """Deterministic fix pipeline: diff git inventories, then rewrite imports.

    Steps:
        1. Resolve *root* (defaults to cwd).
        2. Load configuration.
        3. Setup logging.
        4. Get changed files since ``git_ref``.
        5. Build old (git) and new (filesystem) symbol inventories.
        6. Diff inventories to produce a migration map.
        7. If no migrations, return an empty :class:`FixResult`.
        8. Collect all Python files across configured source directories.
        9. Apply import fixes using the migration map.
        10. Return the :class:`FixResult`.

    Args:
        root: Project root directory. Defaults to the current working directory.
        **config_overrides: Overrides forwarded to :func:`_load_config`.

    Returns:
        :class:`FixResult` summarising files modified and fixes applied.
    """
    from . import differ, fixer, inventory  # import_check: ignore (submodule imports)

    # 1. Resolve root.
    resolved_root = Path(root).resolve() if root is not None else Path.cwd().resolve()

    # 2. Load config.
    config = _load_config(resolved_root, **config_overrides)

    # 3. Setup logging.
    logger = _setup_logging(config)

    # 4. Get changed files.
    changed_files = inventory.get_changed_files(config.git_ref, resolved_root)
    logger.info("Found %d changed files", len(changed_files))

    if not changed_files:
        return FixResult()

    # 5. Build old and new inventories.
    old_inv = inventory.build_old_inventory(changed_files, config.git_ref)
    logger.info("Built old inventory: %d symbols", sum(len(v) for v in old_inv.values()))

    new_inv = inventory.build_inventory(changed_files, resolved_root)
    logger.info("Built new inventory: %d symbols", sum(len(v) for v in new_inv.values()))

    # 6. Diff inventories.
    migration_map = differ.diff_inventories(old_inv, new_inv)
    logger.info("Migration map: %d entries", len(migration_map))

    # 7. If no migrations, return empty result.
    if not migration_map:
        return FixResult()

    # 8. Collect all Python files.
    all_files = inventory.collect_python_files(
        config.source_dirs, resolved_root, config.exclude_patterns,
    )
    logger.info("Applying fixes to %d files", len(all_files))

    # 9. Apply fixes.
    result = fixer.apply_fixes(migration_map, all_files, resolved_root)

    return result


def check(
    root: str | Path | None = None, **config_overrides: object
) -> list[ImportError]:
    """Smoke-test all imports for resolution and encapsulation errors.

    Steps:
        1. Resolve *root* (defaults to cwd).
        2. Load configuration.
        3. Setup logging.
        4. Collect all Python files across configured source directories.
        5. Run import checks.

    Args:
        root: Project root directory. Defaults to the current working directory.
        **config_overrides: Overrides forwarded to :func:`_load_config`.

    Returns:
        List of :class:`ImportError` records. Empty if all imports are clean.
    """
    from . import checker, inventory  # import_check: ignore (submodule imports)

    # 1. Resolve root.
    resolved_root = Path(root).resolve() if root is not None else Path.cwd().resolve()

    # 2. Load config.
    config = _load_config(resolved_root, **config_overrides)

    # 3. Setup logging.
    logger = _setup_logging(config)

    # 4. Collect all Python files.
    all_files = inventory.collect_python_files(
        config.source_dirs, resolved_root, config.exclude_patterns,
    )
    logger.info("Checking imports in %d files", len(all_files))

    # 5. Run checker.
    errors = checker.check_imports(all_files, resolved_root, config)

    logger.info("Found %d import errors", len(errors))

    return errors


def run(root: str | Path | None = None, **config_overrides: object) -> RunResult:
    """Run the full pipeline: fix imports, then check for remaining errors.

    Args:
        root: Project root directory. Defaults to the current working directory.
        **config_overrides: Overrides forwarded to :func:`_load_config`.

    Returns:
        :class:`RunResult` containing the fix result and any remaining errors.
    """
    fix_result = fix(root=root, **config_overrides)
    remaining_errors = check(root=root, **config_overrides)

    return RunResult(fix_result=fix_result, remaining_errors=remaining_errors)
