#!/usr/bin/env python3
# @summary
# AST-based safety validator for pytest test files. Analyzes test code via
# ast.parse() without importing or executing it. Detects dangerous calls
# (subprocess, os.system, eval/exec), dangerous imports (socket, ctypes, etc.),
# filesystem writes outside tmp_path, process/signal manipulation, database
# access, and network library usage. Supports conftest.py exemptions, import
# alias tracking, per-group --allow overrides, --strict mode, and JSON output.
# Exports: SafetyValidator, Violation, ValidationResult, discover_files, main
# Deps: ast, json, sys, os, pathlib, argparse, dataclasses, datetime (stdlib only)
# @end-summary
"""
AST Safety Validator for pytest test files.

Performs static analysis on test files using Python's ast module to detect
dangerous patterns before test execution. This script is a security boundary:
it NEVER imports or executes the code it analyzes.

Exit codes:
    0 - All files pass validation (no BLOCK violations)
    1 - At least one BLOCK violation detected
    2 - Validator internal error (parse failure, I/O error, invalid arguments)

Usage:
    python scripts/check_pytest.py <path-or-files...> [--json] [--strict] [--allow PATTERNS]
"""
from __future__ import annotations

import argparse
import ast
import dataclasses
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Category 1: Dangerous calls -- NEVER overridable
# ---------------------------------------------------------------------------
DANGEROUS_CALLS: dict[str, str] = {
    # subprocess family
    "subprocess.run": "dangerous_call",
    "subprocess.call": "dangerous_call",
    "subprocess.Popen": "dangerous_call",
    "subprocess.check_output": "dangerous_call",
    "subprocess.check_call": "dangerous_call",
    # os process execution
    "os.system": "dangerous_call",
    "os.popen": "dangerous_call",
    "os.execl": "dangerous_call",
    "os.execle": "dangerous_call",
    "os.execlp": "dangerous_call",
    "os.execlpe": "dangerous_call",
    "os.execv": "dangerous_call",
    "os.execve": "dangerous_call",
    "os.execvp": "dangerous_call",
    "os.execvpe": "dangerous_call",
    # builtins
    "eval": "dangerous_call",
    "exec": "dangerous_call",
    "compile": "dangerous_call",
    "__import__": "dangerous_call",
}

# ---------------------------------------------------------------------------
# Category 2: Dangerous imports -- overridable via --allow
# ---------------------------------------------------------------------------
DANGEROUS_IMPORTS: set[str] = {
    "subprocess",
    "socket",
    "http.client",
    "http.server",
    "ftplib",
    "smtplib",
    "telnetlib",
    "ctypes",
    "multiprocessing",
}

# ---------------------------------------------------------------------------
# Category 3: Filesystem danger calls
# ---------------------------------------------------------------------------
FILESYSTEM_DANGER_CALLS: dict[str, str] = {
    "shutil.rmtree": "filesystem_write",
    "os.remove": "filesystem_write",
    "os.unlink": "filesystem_write",
}

# ---------------------------------------------------------------------------
# Category 4: Process/signal manipulation calls
# ---------------------------------------------------------------------------
PROCESS_SIGNAL_CALLS: dict[str, str] = {
    "os.kill": "process_signal",
    "signal.signal": "process_signal",
    "sys.exit": "process_signal",
    "os._exit": "process_signal",
    "os.fork": "process_signal",
}

# ---------------------------------------------------------------------------
# Category 5: Database block calls
# ---------------------------------------------------------------------------
DATABASE_BLOCK_CALLS: dict[str, str] = {
    "psycopg2.connect": "database_access",
    "pymongo.MongoClient": "database_access",
}

# ---------------------------------------------------------------------------
# Category 6: Network libraries (module-level=BLOCK, function-level=WARN)
# ---------------------------------------------------------------------------
NETWORK_LIBRARIES: set[str] = {
    "requests",
    "httpx",
    "aiohttp",
    "urllib.request",
}

# ---------------------------------------------------------------------------
# conftest.py exemption patterns
# ---------------------------------------------------------------------------
CONFTEST_EXEMPT_IMPORTS: set[str] = {
    "importlib.util",
    "importlib",
}

CONFTEST_EXEMPT_CALLS: set[str] = {
    "importlib.util.spec_from_file_location",
    "importlib.util.module_from_spec",
    "types.ModuleType",
}


# ===================================================================
# Data classes
# ===================================================================

@dataclass
class Violation:
    """A single safety violation found during AST analysis."""

    file: str
    line: int
    category: str  # dangerous_call, dangerous_import, filesystem_write,
    # process_manipulation, database_access, network_library, parse_error
    pattern: str
    severity: str  # block, warn, error
    message: str


@dataclass
class ConftestExemption:
    """A pattern that was exempted because it appears in a conftest.py file."""

    file: str
    line: int
    pattern: str
    reason: str


@dataclass
class OverrideApplied:
    """An import-level override applied via --allow flag."""

    pattern: str
    action: str  # "allow"
    source: str  # "group_config"


@dataclass
class ValidationResult:
    """Complete result of validating a set of test files."""

    status: str  # "passed", "blocked", "error"
    timestamp: str
    files_scanned: int
    files_passed: int
    files_blocked: int
    violations: list[Violation] = field(default_factory=list)
    conftest_exemptions: list[ConftestExemption] = field(default_factory=list)
    overrides_applied: list[OverrideApplied] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "status": self.status,
            "timestamp": self.timestamp,
            "files_scanned": self.files_scanned,
            "files_passed": self.files_passed,
            "files_blocked": self.files_blocked,
            "violations": [dataclasses.asdict(v) for v in self.violations],
            "conftest_exemptions": [
                dataclasses.asdict(e) for e in self.conftest_exemptions
            ],
            "overrides_applied": [
                dataclasses.asdict(o) for o in self.overrides_applied
            ],
        }

    def to_json(self) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_dict(), indent=2)


# ===================================================================
# File discovery
# ===================================================================

def discover_files(paths: list[str]) -> tuple[list[Path], list[Path]]:
    """Discover test files and conftest files from given paths.

    Args:
        paths: List of file paths or directory paths.

    Returns:
        Tuple of (test_files, conftest_files). Both lists contain
        absolute Path objects, deduplicated and sorted.
    """
    test_files: set[Path] = set()
    conftest_files: set[Path] = set()

    for path_str in paths:
        p = Path(path_str).resolve()

        if p.is_file():
            if p.name == "conftest.py":
                conftest_files.add(p)
            elif p.name.startswith("test_") or p.name.endswith("_test.py"):
                test_files.add(p)
            else:
                # Explicit file path -- validate it even if naming is unusual
                test_files.add(p)
        elif p.is_dir():
            for child in p.rglob("test_*.py"):
                test_files.add(child.resolve())
            for child in p.rglob("*_test.py"):
                test_files.add(child.resolve())
            for child in p.rglob("conftest.py"):
                conftest_files.add(child.resolve())

    # Walk upward from each test file to find ancestor conftest.py files
    # up to the nearest "tests/" directory root.
    tests_root = _find_tests_root(test_files | conftest_files)
    if tests_root:
        for tf in list(test_files):
            current = tf.parent
            while current >= tests_root:
                candidate = current / "conftest.py"
                if candidate.is_file():
                    conftest_files.add(candidate.resolve())
                if current == tests_root:
                    break
                current = current.parent

    return sorted(test_files), sorted(conftest_files)


def _find_tests_root(file_set: set[Path]) -> Path | None:
    """Find the ancestor directory named 'tests' from the given file paths."""
    for f in file_set:
        for parent in f.parents:
            if parent.name == "tests":
                return parent
    return None


# ===================================================================
# Safety Validator
# ===================================================================

class SafetyValidator:
    """AST-based safety validator for pytest test files.

    Analyzes Python source files using the ast module to detect dangerous
    patterns without importing or executing the code.

    Args:
        allowed_patterns: Set of module names whose imports are allowed
            (overrides DANGEROUS_IMPORTS and NETWORK_LIBRARIES for
            import-level checks only; never overrides dangerous calls).
        strict: If True, upgrades all WARN-severity violations to BLOCK.
    """

    def __init__(
        self,
        allowed_patterns: set[str] | None = None,
        strict: bool = False,
    ) -> None:
        self.allowed_patterns: set[str] = allowed_patterns or set()
        self.strict: bool = strict
        # Tracking overrides across all files in a validation scope
        self._overrides_applied: list[OverrideApplied] = []
        self._overrides_seen: set[str] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_file(self, file_path: str) -> list[Violation]:
        """Validate a single file for dangerous patterns.

        Args:
            file_path: Path to the Python file to validate.

        Returns:
            List of Violation objects found in the file.
        """
        source_text = Path(file_path).read_text(encoding="utf-8")
        try:
            tree = ast.parse(source_text, filename=file_path)
        except SyntaxError as exc:
            return [
                Violation(
                    file=file_path,
                    line=exc.lineno or 0,
                    category="parse_error",
                    pattern="SyntaxError",
                    severity="error",
                    message=f"Failed to parse: {exc.msg}",
                )
            ]

        is_conftest = Path(file_path).name == "conftest.py"
        aliases = self._build_alias_table(tree)
        parent_map = self._build_parent_map(tree)

        violations: list[Violation] = []
        conftest_exemptions: list[ConftestExemption] = []

        for node in ast.walk(tree):
            # --- Import nodes ---
            if isinstance(node, ast.Import):
                self._check_import(
                    node, file_path, is_conftest, parent_map,
                    violations, conftest_exemptions,
                )
            elif isinstance(node, ast.ImportFrom):
                self._check_import_from(
                    node, file_path, is_conftest, parent_map,
                    violations, conftest_exemptions,
                )

            # --- Call nodes ---
            elif isinstance(node, ast.Call):
                resolved = self._resolve_call_name(node, aliases)
                if resolved is None:
                    continue

                # conftest exemptions for calls
                if is_conftest and self._is_conftest_exempt_call(
                    resolved, node, file_path, conftest_exemptions
                ):
                    continue

                # Category 1: Dangerous calls (NEVER overridable)
                if resolved in DANGEROUS_CALLS:
                    violations.append(Violation(
                        file=file_path,
                        line=node.lineno,
                        category=DANGEROUS_CALLS[resolved],
                        pattern=resolved,
                        severity="block",
                        message=f"Dangerous call: {resolved}()",
                    ))
                    continue

                # Category 4: Process/signal manipulation
                if resolved in PROCESS_SIGNAL_CALLS:
                    violations.append(Violation(
                        file=file_path,
                        line=node.lineno,
                        category=PROCESS_SIGNAL_CALLS[resolved],
                        pattern=resolved,
                        severity="block",
                        message=f"Process/signal manipulation: {resolved}()",
                    ))
                    continue

                # Category 3: Filesystem danger calls
                if resolved in FILESYSTEM_DANGER_CALLS:
                    func_params = self._get_enclosing_function_params(
                        node, parent_map
                    )
                    if node.args and self._is_tmp_path_derived(
                        node.args[0], func_params
                    ):
                        continue  # safe: tmp_path derived
                    violations.append(Violation(
                        file=file_path,
                        line=node.lineno,
                        category=FILESYSTEM_DANGER_CALLS[resolved],
                        pattern=resolved,
                        severity="block",
                        message=f"Filesystem write: {resolved}() on non-tmp path",
                    ))
                    continue

                # Category 3b: open() with write mode
                if resolved in ("open", "builtins.open"):
                    self._check_open_call(
                        node, file_path, parent_map, violations
                    )
                    continue

                # Category 3c: Path.write_text / Path.write_bytes / Path.unlink
                if resolved.endswith((".write_text", ".write_bytes")):
                    func_params = self._get_enclosing_function_params(
                        node, parent_map
                    )
                    if self._is_path_method_on_tmp(node, func_params):
                        continue  # safe
                    violations.append(Violation(
                        file=file_path,
                        line=node.lineno,
                        category="filesystem_write",
                        pattern=resolved,
                        severity="warn",
                        message=(
                            f"Filesystem write: {resolved}() -- "
                            "unable to verify tmp_path derivation"
                        ),
                    ))
                    continue

                # Category 5: Database access -- sqlite3.connect special case
                if resolved == "sqlite3.connect":
                    self._check_sqlite_connect(
                        node, file_path, violations
                    )
                    continue

                # Category 5: Database block calls
                if resolved in DATABASE_BLOCK_CALLS:
                    violations.append(Violation(
                        file=file_path,
                        line=node.lineno,
                        category=DATABASE_BLOCK_CALLS[resolved],
                        pattern=resolved,
                        severity="block",
                        message=f"Database access: {resolved}()",
                    ))
                    continue

            # --- Assignment nodes: sys.modules[...] = ... in conftest ---
            elif isinstance(node, (ast.Assign, ast.AugAssign)):
                if is_conftest:
                    self._check_sys_modules_assignment(
                        node, file_path, aliases, conftest_exemptions
                    )

        # Store conftest exemptions (they'll be collected in validate_scope)
        self._last_conftest_exemptions = conftest_exemptions

        return violations

    def validate_scope(self, paths: list[str]) -> ValidationResult:
        """Validate a set of paths (files and/or directories).

        Discovers test files and conftest files, validates each, and
        produces a consolidated ValidationResult.

        Args:
            paths: List of file or directory paths to validate.

        Returns:
            ValidationResult with aggregated findings.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Reset scope-level tracking
        self._overrides_applied = []
        self._overrides_seen = set()

        # Discover files
        test_files, conftest_files = discover_files(paths)
        all_files = sorted(set(test_files) | set(conftest_files))

        all_violations: list[Violation] = []
        all_exemptions: list[ConftestExemption] = []
        files_with_blocks: set[str] = set()

        for fpath in all_files:
            fpath_str = str(fpath)
            try:
                self._last_conftest_exemptions = []
                file_violations = self.validate_file(fpath_str)
                all_violations.extend(file_violations)
                all_exemptions.extend(self._last_conftest_exemptions)

                for v in file_violations:
                    if v.severity == "block":
                        files_with_blocks.add(v.file)
            except Exception as exc:
                all_violations.append(Violation(
                    file=fpath_str,
                    line=0,
                    category="parse_error",
                    pattern="Exception",
                    severity="error",
                    message=f"Validator error: {exc}",
                ))

        # Apply strict mode: upgrade WARN -> BLOCK
        if self.strict:
            for v in all_violations:
                if v.severity == "warn":
                    v.severity = "block"
                    files_with_blocks.add(v.file)

        # Determine status
        has_blocks = any(v.severity == "block" for v in all_violations)
        has_errors = any(v.severity == "error" for v in all_violations)

        if has_blocks:
            status = "blocked"
        elif has_errors:
            status = "error"
        else:
            status = "passed"

        files_scanned = len(all_files)
        files_blocked = len(files_with_blocks)
        files_passed = files_scanned - files_blocked

        return ValidationResult(
            status=status,
            timestamp=timestamp,
            files_scanned=files_scanned,
            files_passed=files_passed,
            files_blocked=files_blocked,
            violations=all_violations,
            conftest_exemptions=all_exemptions,
            overrides_applied=list(self._overrides_applied),
        )

    # ------------------------------------------------------------------
    # Alias table construction
    # ------------------------------------------------------------------

    @staticmethod
    def _build_alias_table(tree: ast.Module) -> dict[str, str]:
        """Build a per-file alias table from Import and ImportFrom nodes.

        Maps local names to their fully-qualified originals:
            import subprocess as sp   ->  {"sp": "subprocess"}
            from os import system     ->  {"system": "os.system"}
            from os import system as s ->  {"s": "os.system"}
            import os                 ->  {"os": "os"}
        """
        aliases: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    local_name = alias.asname if alias.asname else alias.name
                    aliases[local_name] = alias.name
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    local_name = alias.asname if alias.asname else alias.name
                    full_name = f"{module}.{alias.name}" if module else alias.name
                    aliases[local_name] = full_name
        return aliases

    # ------------------------------------------------------------------
    # Parent map construction
    # ------------------------------------------------------------------

    @staticmethod
    def _build_parent_map(tree: ast.Module) -> dict[int, ast.AST]:
        """Build a mapping from node id to parent node for the entire tree.

        Returns dict keyed by id(child) -> parent node.
        """
        parent_map: dict[int, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parent_map[id(child)] = node
        return parent_map

    # ------------------------------------------------------------------
    # Call name resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_call_name(
        node: ast.Call, aliases: dict[str, str]
    ) -> str | None:
        """Resolve the fully-qualified name of a function call.

        Handles:
            - Bare names: eval(...) -> "eval"
            - Dotted names: os.system(...) -> "os.system"
            - Aliased names: sp.run(...) where sp -> subprocess -> "subprocess.run"
            - Chained attributes: a.b.c(...) resolved via leftmost alias

        Returns None if the call target is not a resolvable name
        (e.g., computed calls like getattr(obj, name)(...)).
        """
        func = node.func

        # Bare name: eval(), exec(), __import__(), or aliased single name
        if isinstance(func, ast.Name):
            name = func.id
            if name in aliases:
                return aliases[name]
            return name

        # Dotted name: os.system(), subprocess.run(), etc.
        if isinstance(func, ast.Attribute):
            parts: list[str] = []
            current: ast.expr = func
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
                parts.reverse()

                # Resolve the leftmost part via alias table
                leftmost = parts[0]
                if leftmost in aliases:
                    resolved_base = aliases[leftmost]
                    return resolved_base + "." + ".".join(parts[1:])
                return ".".join(parts)

        return None

    # ------------------------------------------------------------------
    # Import checks
    # ------------------------------------------------------------------

    def _check_import(
        self,
        node: ast.Import,
        file_path: str,
        is_conftest: bool,
        parent_map: dict[int, ast.AST],
        violations: list[Violation],
        conftest_exemptions: list[ConftestExemption],
    ) -> None:
        """Check an ast.Import node for dangerous or network library imports."""
        is_function_level = self._is_inside_function(node, parent_map)

        for alias in node.names:
            module_name = alias.name

            # conftest exemptions for importlib.util etc.
            if is_conftest and module_name in CONFTEST_EXEMPT_IMPORTS:
                conftest_exemptions.append(ConftestExemption(
                    file=file_path,
                    line=node.lineno,
                    pattern=module_name,
                    reason="conftest exemption: standard importlib pattern",
                ))
                continue

            # Dangerous imports (FR-103)
            if module_name in DANGEROUS_IMPORTS:
                if module_name in self.allowed_patterns:
                    self._record_override(module_name)
                    continue
                violations.append(Violation(
                    file=file_path,
                    line=node.lineno,
                    category="dangerous_import",
                    pattern=module_name,
                    severity="block",
                    message=f"Dangerous import: {module_name}",
                ))
                continue

            # Network libraries (FR-107)
            if module_name in NETWORK_LIBRARIES:
                if module_name in self.allowed_patterns:
                    self._record_override(module_name)
                    continue
                severity = "warn" if is_function_level else "block"
                violations.append(Violation(
                    file=file_path,
                    line=node.lineno,
                    category="network_library",
                    pattern=module_name,
                    severity=severity,
                    message=(
                        f"Network library import: {module_name}"
                        f" ({'function-level' if is_function_level else 'module-level'})"
                    ),
                ))
                continue

    def _check_import_from(
        self,
        node: ast.ImportFrom,
        file_path: str,
        is_conftest: bool,
        parent_map: dict[int, ast.AST],
        violations: list[Violation],
        conftest_exemptions: list[ConftestExemption],
    ) -> None:
        """Check an ast.ImportFrom node for dangerous or network library imports."""
        module_name = node.module or ""
        is_function_level = self._is_inside_function(node, parent_map)

        # conftest exemptions: from importlib.util import ...
        if is_conftest and (
            module_name in CONFTEST_EXEMPT_IMPORTS
            or module_name.startswith("importlib.util")
        ):
            conftest_exemptions.append(ConftestExemption(
                file=file_path,
                line=node.lineno,
                pattern=module_name,
                reason="conftest exemption: standard importlib pattern",
            ))
            return

        # Check both the module name and parent modules against dangerous imports
        # e.g., "from subprocess import run" -> module_name = "subprocess"
        # e.g., "from http.client import HTTPConnection" -> module_name = "http.client"
        matched_dangerous = None
        if module_name in DANGEROUS_IMPORTS:
            matched_dangerous = module_name
        else:
            # Check parent module: "from http.client import X" where
            # "http.client" is dangerous
            for dangerous in DANGEROUS_IMPORTS:
                if module_name == dangerous or module_name.startswith(
                    dangerous + "."
                ):
                    matched_dangerous = dangerous
                    break
            # Check constructed names: "from urllib import request" where
            # "urllib.request" is dangerous
            if matched_dangerous is None and node.names:
                for alias in node.names:
                    constructed = f"{module_name}.{alias.name}" if module_name else alias.name
                    if constructed in DANGEROUS_IMPORTS:
                        matched_dangerous = constructed
                        break
                    for dangerous in DANGEROUS_IMPORTS:
                        if constructed == dangerous or constructed.startswith(
                            dangerous + "."
                        ):
                            matched_dangerous = dangerous
                            break
                    if matched_dangerous is not None:
                        break

        if matched_dangerous is not None:
            if matched_dangerous in self.allowed_patterns:
                self._record_override(matched_dangerous)
                return
            violations.append(Violation(
                file=file_path,
                line=node.lineno,
                category="dangerous_import",
                pattern=matched_dangerous,
                severity="block",
                message=f"Dangerous import: from {module_name} import ...",
            ))
            return

        # Network libraries check
        matched_network = None
        if module_name in NETWORK_LIBRARIES:
            matched_network = module_name
        else:
            for net_lib in NETWORK_LIBRARIES:
                if module_name == net_lib or module_name.startswith(
                    net_lib + "."
                ):
                    matched_network = net_lib
                    break
            # Check constructed names: "from urllib import request" where
            # "urllib.request" is a network library
            if matched_network is None and node.names:
                for alias in node.names:
                    constructed = f"{module_name}.{alias.name}" if module_name else alias.name
                    if constructed in NETWORK_LIBRARIES:
                        matched_network = constructed
                        break
                    for net_lib in NETWORK_LIBRARIES:
                        if constructed == net_lib or constructed.startswith(
                            net_lib + "."
                        ):
                            matched_network = net_lib
                            break
                    if matched_network is not None:
                        break

        if matched_network is not None:
            if matched_network in self.allowed_patterns:
                self._record_override(matched_network)
                return
            severity = "warn" if is_function_level else "block"
            violations.append(Violation(
                file=file_path,
                line=node.lineno,
                category="network_library",
                pattern=matched_network,
                severity=severity,
                message=(
                    f"Network library import: from {module_name} import ..."
                    f" ({'function-level' if is_function_level else 'module-level'})"
                ),
            ))
            return

    # ------------------------------------------------------------------
    # conftest exemption helpers
    # ------------------------------------------------------------------

    def _is_conftest_exempt_call(
        self,
        resolved_name: str,
        node: ast.Call,
        file_path: str,
        conftest_exemptions: list[ConftestExemption],
    ) -> bool:
        """Check if a resolved call name is exempt for conftest.py files.

        Handles:
            - importlib.util.spec_from_file_location(...)
            - importlib.util.module_from_spec(...)
            - types.ModuleType(...)
            - *.loader.exec_module(...)
        """
        # Direct match against known exempt calls
        if resolved_name in CONFTEST_EXEMPT_CALLS:
            conftest_exemptions.append(ConftestExemption(
                file=file_path,
                line=node.lineno,
                pattern=resolved_name,
                reason="conftest exemption: standard importlib/types pattern",
            ))
            return True

        # Pattern match: *.loader.exec_module(...)
        if resolved_name.endswith(".loader.exec_module"):
            conftest_exemptions.append(ConftestExemption(
                file=file_path,
                line=node.lineno,
                pattern=resolved_name,
                reason="conftest exemption: importlib exec_module pattern",
            ))
            return True

        return False

    def _check_sys_modules_assignment(
        self,
        node: ast.Assign | ast.AugAssign,
        file_path: str,
        aliases: dict[str, str],
        conftest_exemptions: list[ConftestExemption],
    ) -> None:
        """Check for sys.modules[...] = ... assignments in conftest files."""
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        else:
            targets = [node.target]

        for target in targets:
            if isinstance(target, ast.Subscript):
                # Check if target.value resolves to sys.modules
                if self._is_sys_modules(target.value, aliases):
                    conftest_exemptions.append(ConftestExemption(
                        file=file_path,
                        line=node.lineno,
                        pattern="sys.modules",
                        reason="conftest exemption: sys.modules manipulation for test bootstrap",
                    ))

    @staticmethod
    def _is_sys_modules(node: ast.expr, aliases: dict[str, str]) -> bool:
        """Check if an expression resolves to sys.modules."""
        if isinstance(node, ast.Attribute):
            if (
                isinstance(node.value, ast.Name)
                and node.attr == "modules"
            ):
                base = node.value.id
                resolved = aliases.get(base, base)
                return resolved == "sys"
        return False

    # ------------------------------------------------------------------
    # Filesystem write checks
    # ------------------------------------------------------------------

    def _check_open_call(
        self,
        node: ast.Call,
        file_path: str,
        parent_map: dict[int, ast.AST],
        violations: list[Violation],
    ) -> None:
        """Check open() calls for write mode outside tmp_path."""
        # Determine the mode argument
        mode = self._get_open_mode(node)
        if mode is None:
            return  # read mode or unable to determine -> safe by default

        # Check if the mode contains write flags
        write_flags = {"w", "a", "x"}
        if not any(flag in mode for flag in write_flags):
            return  # read-only mode

        # Check if the path argument is tmp_path derived
        if not node.args:
            return  # no path argument

        func_params = self._get_enclosing_function_params(node, parent_map)
        path_arg = node.args[0]

        if self._is_tmp_path_derived(path_arg, func_params):
            return  # safe: writing to tmp_path

        violations.append(Violation(
            file=file_path,
            line=node.lineno,
            category="filesystem_write",
            pattern="open",
            severity="block",
            message=f"Filesystem write: open() with mode '{mode}' on non-tmp path",
        ))

    @staticmethod
    def _get_open_mode(node: ast.Call) -> str | None:
        """Extract the mode string from an open() call.

        Returns the mode string, or None if the call is read-only or
        the mode cannot be determined statically.
        """
        mode_arg = None

        # Positional: open(path, mode, ...)
        if len(node.args) >= 2:
            mode_arg = node.args[1]

        # Keyword: open(path, mode=...)
        for kw in node.keywords:
            if kw.arg == "mode":
                mode_arg = kw.value
                break

        if mode_arg is None:
            return None  # default mode is 'r' -> safe

        if isinstance(mode_arg, ast.Constant) and isinstance(
            mode_arg.value, str
        ):
            return mode_arg.value

        # Non-literal mode: unable to determine statically
        return "unknown"

    def _check_sqlite_connect(
        self,
        node: ast.Call,
        file_path: str,
        violations: list[Violation],
    ) -> None:
        """Check sqlite3.connect() calls for safe vs unsafe paths."""
        if node.args:
            first_arg = node.args[0]
            if isinstance(first_arg, ast.Constant) and isinstance(
                first_arg.value, str
            ):
                value = first_arg.value
                if value == ":memory:" or value.startswith("/tmp"):
                    return  # safe

        # Check keyword argument
        for kw in node.keywords:
            if kw.arg == "database":
                if isinstance(kw.value, ast.Constant) and isinstance(
                    kw.value.value, str
                ):
                    value = kw.value.value
                    if value == ":memory:" or value.startswith("/tmp"):
                        return  # safe

        violations.append(Violation(
            file=file_path,
            line=node.lineno,
            category="database_access",
            pattern="sqlite3.connect",
            severity="warn",
            message="Database access: sqlite3.connect() with non-memory/non-tmp path",
        ))

    @staticmethod
    def _is_tmp_path_derived(
        node: ast.expr, func_params: list[str]
    ) -> bool:
        """Heuristic: check if a node is derived from tmp_path or /tmp.

        Looks for:
            - Name node: tmp_path
            - String constant starting with /tmp
            - BinOp (/) with tmp_path on the left
            - Attribute access on tmp_path
            - Any subtree containing tmp_path Name node
        """
        has_tmp_param = "tmp_path" in func_params or "tmp_path_factory" in func_params

        # Direct name reference
        if isinstance(node, ast.Name):
            if node.id == "tmp_path" and has_tmp_param:
                return True

        # String literal starting with /tmp
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith("/tmp"):
                return True

        # BinOp: tmp_path / "file.txt"
        if isinstance(node, ast.BinOp):
            if _ast_subtree_contains_name(node, "tmp_path") and has_tmp_param:
                return True

        # JoinedStr (f-string) containing tmp_path reference
        if isinstance(node, ast.JoinedStr):
            if has_tmp_param and _ast_subtree_contains_name(node, "tmp_path"):
                return True

        # Attribute access: tmp_path.something
        if isinstance(node, ast.Attribute):
            if _ast_subtree_contains_name(node, "tmp_path") and has_tmp_param:
                return True

        # Call: str(tmp_path), tmp_path.joinpath(), etc.
        if isinstance(node, ast.Call):
            if has_tmp_param and _ast_subtree_contains_name(node, "tmp_path"):
                return True

        return False

    @staticmethod
    def _is_path_method_on_tmp(
        node: ast.Call, func_params: list[str]
    ) -> bool:
        """Check if a Path.write_text/write_bytes call is on a tmp_path object."""
        has_tmp_param = "tmp_path" in func_params or "tmp_path_factory" in func_params
        if not has_tmp_param:
            return False

        # node.func should be an ast.Attribute (the .write_text part)
        if isinstance(node.func, ast.Attribute):
            receiver = node.func.value
            if _ast_subtree_contains_name(receiver, "tmp_path"):
                return True

        return False

    # ------------------------------------------------------------------
    # Tree navigation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_inside_function(
        node: ast.AST, parent_map: dict[int, ast.AST]
    ) -> bool:
        """Check if a node is inside a function definition (not module level)."""
        current_id = id(node)
        while current_id in parent_map:
            parent = parent_map[current_id]
            if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return True
            current_id = id(parent)
        return False

    @staticmethod
    def _get_enclosing_function_params(
        node: ast.AST, parent_map: dict[int, ast.AST]
    ) -> list[str]:
        """Get parameter names from the nearest enclosing function definition."""
        current_id = id(node)
        while current_id in parent_map:
            parent = parent_map[current_id]
            if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return [arg.arg for arg in parent.args.args]
            current_id = id(parent)
        return []

    # ------------------------------------------------------------------
    # Override tracking
    # ------------------------------------------------------------------

    def _record_override(self, pattern: str) -> None:
        """Record an applied override (deduplicated across files)."""
        if pattern not in self._overrides_seen:
            self._overrides_seen.add(pattern)
            self._overrides_applied.append(OverrideApplied(
                pattern=pattern,
                action="allow",
                source="group_config",
            ))


# ===================================================================
# Module-level helper
# ===================================================================

def _ast_subtree_contains_name(node: ast.AST, name: str) -> bool:
    """Check if any ast.Name node in the subtree has the given id."""
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id == name:
            return True
    return False


# ===================================================================
# CLI
# ===================================================================

def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        description="AST safety validator for pytest test files.",
        epilog="Exit codes: 0=pass, 1=blocked, 2=error",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        metavar="PATH",
        help="One or more file paths or directory paths to validate.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        dest="json_output",
        help="Output JSON to stdout (default behavior; kept for explicitness).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Upgrade WARN-severity violations to BLOCK.",
    )
    parser.add_argument(
        "--allow",
        type=str,
        default="",
        metavar="PATTERNS",
        help=(
            "Comma-separated module names whose imports are allowed "
            "(overrides import-level blocks only, never call-level)."
        ),
    )
    return parser


def _print_human_summary(result: ValidationResult) -> None:
    """Print a human-readable summary of validation results to stderr."""
    print(f"\n{'=' * 60}", file=sys.stderr)
    print(
        f"Safety Validation: {result.status.upper()}",
        file=sys.stderr,
    )
    print(
        f"Files scanned: {result.files_scanned}  |  "
        f"Passed: {result.files_passed}  |  "
        f"Blocked: {result.files_blocked}",
        file=sys.stderr,
    )

    if result.violations:
        print(f"\nViolations ({len(result.violations)}):", file=sys.stderr)
        for v in result.violations:
            marker = "BLOCK" if v.severity == "block" else "WARN"
            if v.severity == "error":
                marker = "ERROR"
            print(
                f"  [{marker}] {v.file}:{v.line} -- {v.message}",
                file=sys.stderr,
            )

    if result.conftest_exemptions:
        print(
            f"\nconftest.py exemptions ({len(result.conftest_exemptions)}):",
            file=sys.stderr,
        )
        for e in result.conftest_exemptions:
            print(
                f"  [EXEMPT] {e.file}:{e.line} -- {e.pattern}: {e.reason}",
                file=sys.stderr,
            )

    if result.overrides_applied:
        print(
            f"\nOverrides applied ({len(result.overrides_applied)}):",
            file=sys.stderr,
        )
        for o in result.overrides_applied:
            print(
                f"  [ALLOW] {o.pattern} (source: {o.source})",
                file=sys.stderr,
            )

    print(f"{'=' * 60}\n", file=sys.stderr)


def main(args: list[str] | None = None) -> int:
    """CLI entry point. Returns exit code (0, 1, or 2)."""
    parser = _build_parser()
    parsed = parser.parse_args(args)

    # Parse --allow patterns
    allowed: set[str] = set()
    if parsed.allow:
        allowed = {p.strip() for p in parsed.allow.split(",") if p.strip()}

    # Verify paths exist
    for p in parsed.paths:
        if not os.path.exists(p):
            print(
                json.dumps({
                    "status": "error",
                    "timestamp": datetime.now(timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                    "files_scanned": 0,
                    "files_passed": 0,
                    "files_blocked": 0,
                    "violations": [{
                        "file": p,
                        "line": 0,
                        "category": "parse_error",
                        "pattern": "FileNotFoundError",
                        "severity": "error",
                        "message": f"Path does not exist: {p}",
                    }],
                    "conftest_exemptions": [],
                    "overrides_applied": [],
                }, indent=2)
            )
            return 2

    try:
        validator = SafetyValidator(
            allowed_patterns=allowed,
            strict=parsed.strict,
        )
        result = validator.validate_scope(parsed.paths)
    except Exception as exc:
        error_result = ValidationResult(
            status="error",
            timestamp=datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            files_scanned=0,
            files_passed=0,
            files_blocked=0,
            violations=[Violation(
                file="<validator>",
                line=0,
                category="parse_error",
                pattern="Exception",
                severity="error",
                message=f"Validator internal error: {exc}",
            )],
        )
        print(error_result.to_json())
        _print_human_summary(error_result)
        return 2

    # Output
    print(result.to_json())
    _print_human_summary(result)

    # Exit code
    if result.status == "blocked":
        return 1
    elif result.status == "error":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
