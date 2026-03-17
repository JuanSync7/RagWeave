# @summary
# Small validation helpers for common boundary checks (types, ranges, filters, paths).
# Exports: validate_alpha, validate_positive_int, validate_filter_value, validate_documents_dir
# Deps: re, pathlib
# @end-summary
"""Validation helpers for common boundary checks.

This module centralizes small, reusable validation functions used across the
platform and API boundary layers.
"""

import re
from pathlib import Path
from typing import Optional


_SAFE_FILTER = re.compile(r"^[\w.\- /]{1,200}$")


def validate_alpha(alpha: float) -> float:
    """Validate a mixing/weight parameter.

    Args:
        alpha: Value expected to be within [0.0, 1.0].

    Returns:
        The validated `alpha`.

    Raises:
        ValueError: If `alpha` is outside [0.0, 1.0].
    """
    if not (0.0 <= alpha <= 1.0):
        raise ValueError("alpha must be between 0.0 and 1.0")
    return alpha


def validate_positive_int(name: str, value: int) -> int:
    """Validate that an integer is strictly positive.

    Args:
        name: Parameter name to include in error messages.
        value: Integer value to validate.

    Returns:
        The validated `value`.

    Raises:
        ValueError: If `value` is <= 0.
    """
    if value <= 0:
        raise ValueError(f"{name} must be > 0")
    return value


def validate_filter_value(name: str, value: Optional[str]) -> Optional[str]:
    """Validate a user-provided filter string.

    The value is stripped; empty strings become None. Only a conservative set of
    characters is allowed to avoid unsafe query/pattern injection.

    Args:
        name: Parameter name to include in error messages.
        value: Optional raw filter string.

    Returns:
        The normalized filter value, or None if empty.

    Raises:
        ValueError: If the value contains disallowed characters.
    """
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if not _SAFE_FILTER.match(value):
        raise ValueError(f"{name} contains invalid characters")
    return value


def validate_documents_dir(path: Path, project_root: Path) -> Path:
    """Validate that a documents directory is safe and within the project.

    Args:
        path: Candidate documents directory path.
        project_root: Project root boundary for allowed paths.

    Returns:
        The resolved, validated documents directory path.

    Raises:
        ValueError: If the directory is outside the project root or is a symlink.
    """
    resolved = path.resolve()
    project_root_resolved = project_root.resolve()
    if project_root_resolved not in resolved.parents and resolved != project_root_resolved:
        raise ValueError("documents_dir must be within project root")
    if resolved.is_symlink():
        raise ValueError("documents_dir cannot be a symlink")
    return resolved

