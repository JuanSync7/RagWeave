#!/usr/bin/env python3
# @summary
# Runs import_check only on git-tracked .py files under the project source
# directories. Used as the L2 layer of `make precommit-check` so untracked
# WIP does not block commits. `make all-check` still runs the full
# `make import-check` which scans every .py file regardless of git state.
# Exports: main
# Deps: subprocess, import_check
# @end-summary
"""L2 (import resolution + encapsulation) for tracked files only.

The full ``make import-check`` target walks every .py file under
``src/``, ``server/``, ``config/``, and ``import_check/``. That's the
right behaviour for ``make all-check`` — a hygiene sweep should include
work-in-progress. But for ``make precommit-check`` we want a gate that
fires only on files git already knows about, so an uncommitted feature
branch can't block a commit that doesn't touch it.

This script bridges the gap: it asks git for the tracked .py files under
the scanned directories and hands the list to
``import_check.checker.check_imports`` directly.

Exit code:
    0 when no errors are found, 1 when any import error is found.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from import_check.checker import check_imports  # noqa: E402
from import_check.schemas import ImportCheckConfig  # noqa: E402


# The directories scanned by the regular `make import-check` target.
# Keep in sync with `ImportCheckConfig.source_dirs` and the Makefile.
_SCAN_DIRS = ("src", "server", "config", "import_check")


def get_tracked_py_files(root: Path) -> list[str]:
    """Return the list of tracked .py files under the scan directories.

    Uses ``git ls-files`` which lists every file in the git index — that
    is, anything committed plus anything staged for commit. Untracked
    files are excluded. Files modified in the working tree are still
    included (their on-disk content is what we want to check).

    Paths are returned relative to the repo root, matching the format
    ``check_imports`` expects.
    """
    result = subprocess.run(
        ["git", "ls-files", "--", *_SCAN_DIRS],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [
        line
        for line in result.stdout.splitlines()
        if line.endswith(".py")
    ]


def main() -> int:
    root = _REPO_ROOT
    files = get_tracked_py_files(root)
    if not files:
        print(
            f"import-check (tracked): no tracked .py files under {_SCAN_DIRS}",
            file=sys.stderr,
        )
        return 0

    config = ImportCheckConfig(root=root)
    errors = check_imports(files, root, config)

    for err in errors:
        print(
            f"{err.file_path}:{err.lineno}  "
            f"[{err.error_type.value}]  {err.message}",
            file=sys.stderr,
        )

    if errors:
        print(
            f"\nimport-check (tracked): {len(errors)} error(s) in "
            f"{len(files)} tracked file(s)",
            file=sys.stderr,
        )
        return 1

    print(
        f"import-check (tracked): {len(files)} tracked file(s) clean",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
