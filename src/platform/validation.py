"""Centralized boundary validation utilities."""

import re
from pathlib import Path
from typing import Optional


_SAFE_FILTER = re.compile(r"^[\w.\- /]{1,200}$")


def validate_alpha(alpha: float) -> float:
    if not (0.0 <= alpha <= 1.0):
        raise ValueError("alpha must be between 0.0 and 1.0")
    return alpha


def validate_positive_int(name: str, value: int) -> int:
    if value <= 0:
        raise ValueError(f"{name} must be > 0")
    return value


def validate_filter_value(name: str, value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if not _SAFE_FILTER.match(value):
        raise ValueError(f"{name} contains invalid characters")
    return value


def validate_documents_dir(path: Path, project_root: Path) -> Path:
    resolved = path.resolve()
    project_root_resolved = project_root.resolve()
    if project_root_resolved not in resolved.parents and resolved != project_root_resolved:
        raise ValueError("documents_dir must be within project root")
    if resolved.is_symlink():
        raise ValueError("documents_dir cannot be a symlink")
    return resolved

