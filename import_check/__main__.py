# @summary
# CLI entry point for import_check tool.
# Exports: main
# Deps: argparse, json, sys, pathlib, import_check
# @end-summary
"""CLI entry point for import_check.

Usage:
    python -m import_check [fix|check|run] [options]

Subcommands:
    fix    -- apply deterministic import fixes
    check  -- smoke test all imports
    run    -- fix then check (default)

Options are mapped to ImportCheckConfig fields.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    """Parse CLI arguments and dispatch to the appropriate command.

    Returns:
        Exit code: 0 if no errors, 1 if import errors remain after fix.
    """
    parser = _build_parser()
    args = parser.parse_args()

    from import_check import fix, check, run

    root = Path(args.root).resolve()

    config_overrides: dict = {
        "log_level": args.log_level,
        "output_format": args.format,
        "encapsulation_check": args.encapsulation_check,
        "git_ref": args.git_ref,
        "check_stubs": args.check_stubs,
        "check_getattr": args.check_getattr,
    }
    if args.source_dirs is not None:
        config_overrides["source_dirs"] = args.source_dirs
    if args.exclude is not None:
        config_overrides["exclude_patterns"] = args.exclude

    command = args.command or "run"

    if command == "fix":
        result = fix(root, **config_overrides)
        output = _format_output(result, args.format)
        if output:
            print(output)
        return 0

    if command == "check":
        errors = check(root, **config_overrides)
        output = _format_output(errors, args.format)
        if output:
            print(output)
        return 1 if errors else 0

    # Default: run (fix + check)
    run_result = run(root, **config_overrides)
    output = _format_output(run_result, args.format)
    if output:
        print(output)
    return 1 if run_result.remaining_errors else 0


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for import_check CLI.

    Subcommands: fix, check, run (default).
    Global options: --source-dirs, --exclude, --git-ref,
        --no-encapsulation-check, --format, --log-level, --root.

    Returns:
        Configured ArgumentParser.
    """
    parser = argparse.ArgumentParser(
        prog="import_check",
        description="Detect and fix broken Python imports after refactoring.",
    )

    parser.add_argument(
        "command",
        nargs="?",
        choices=["fix", "check", "run"],
        default=None,
        help="Subcommand to run (default: run)",
    )
    parser.add_argument(
        "--source-dirs",
        nargs="+",
        default=None,
        help="Directories to scan for Python files",
    )
    parser.add_argument(
        "--exclude",
        nargs="+",
        default=None,
        help="Glob patterns to exclude from scanning",
    )
    parser.add_argument(
        "--git-ref",
        default="HEAD",
        help="Git ref for 'before' state (default: HEAD)",
    )
    parser.add_argument(
        "--no-encapsulation-check",
        dest="encapsulation_check",
        action="store_false",
        default=True,
        help="Disable encapsulation violation reporting",
    )
    parser.add_argument(
        "--no-check-stubs",
        dest="check_stubs",
        action="store_false",
        default=True,
        help="Disable .pyi stub file fallback for symbol checking",
    )
    parser.add_argument(
        "--no-check-getattr",
        dest="check_getattr",
        action="store_false",
        default=True,
        help="Disable __getattr__-based symbol suppression",
    )
    parser.add_argument(
        "--format",
        choices=["human", "json"],
        default="human",
        help="Output format (default: human)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "ERROR"],
        default="INFO",
        help="Logging verbosity (default: INFO)",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Project root directory (default: current directory)",
    )

    return parser


def _format_output(result: object, fmt: str) -> str:
    """Format a result object for terminal output.

    Args:
        result: The result to format (FixResult, list[ImportError], or RunResult).
        fmt: Output format -- "human" or "json".

    Returns:
        Formatted string ready for print().
    """
    from import_check.schemas import FixResult, ImportError, RunResult

    if fmt == "json":
        return _format_json(result)
    return _format_human(result)


def _format_json(result: object) -> str:
    """Serialize result to JSON."""
    from import_check.schemas import FixResult, ImportError, RunResult

    if isinstance(result, FixResult):
        return json.dumps({
            "files_modified": result.files_modified,
            "fixes_applied": result.fixes_applied,
            "errors": result.errors,
            "skipped": result.skipped,
        }, indent=2)

    if isinstance(result, list):
        return json.dumps([
            {
                "file_path": e.file_path,
                "lineno": e.lineno,
                "module": e.module,
                "name": e.name,
                "error_type": e.error_type.value,
                "message": e.message,
            }
            for e in result
        ], indent=2)

    if isinstance(result, RunResult):
        return json.dumps({
            "fix_result": {
                "files_modified": result.fix_result.files_modified,
                "fixes_applied": result.fix_result.fixes_applied,
                "errors": result.fix_result.errors,
                "skipped": result.fix_result.skipped,
            },
            "remaining_errors": [
                {
                    "file_path": e.file_path,
                    "lineno": e.lineno,
                    "module": e.module,
                    "name": e.name,
                    "error_type": e.error_type.value,
                    "message": e.message,
                }
                for e in result.remaining_errors
            ],
        }, indent=2)

    return json.dumps(str(result))


def _format_human(result: object) -> str:
    """Format result as human-readable text."""
    from import_check.schemas import FixResult, ImportError, RunResult

    lines: list[str] = []

    if isinstance(result, FixResult):
        lines.append(f"Fix: {result.fixes_applied} imports rewritten across {len(result.files_modified)} files")
        if result.errors:
            lines.append(f"Errors: {len(result.errors)}")
            for err in result.errors:
                lines.append(f"  {err}")
        if result.skipped:
            lines.append(f"Skipped: {len(result.skipped)}")
            for skip in result.skipped:
                lines.append(f"  {skip}")
        return "\n".join(lines)

    if isinstance(result, list):
        if not result:
            return "Check: all imports OK"
        lines.append(f"Check: {len(result)} import errors found")
        for err in result:
            lines.append(f"  {err.file_path}:{err.lineno} -- {err.message}")
        return "\n".join(lines)

    if isinstance(result, RunResult):
        fix_summary = _format_human(result.fix_result)
        lines.append(fix_summary)
        if result.remaining_errors:
            lines.append(f"\nRemaining errors: {len(result.remaining_errors)}")
            for err in result.remaining_errors:
                lines.append(f"  {err.file_path}:{err.lineno} -- {err.message}")
        else:
            lines.append("\nAll imports OK after fix.")
        return "\n".join(lines)

    return str(result)


if __name__ == "__main__":
    sys.exit(main())
