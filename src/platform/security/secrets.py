"""Secret loading helpers with explicit fail-fast."""

from __future__ import annotations

import os


def get_secret(name: str, default: str | None = None, required: bool = False) -> str | None:
    """Resolve secret from env or *_FILE convention."""
    file_key = f"{name}_FILE"
    if file_key in os.environ:
        path = os.environ[file_key]
        with open(path, encoding="utf-8") as fh:
            value = fh.read().strip()
            if value:
                return value

    value = os.environ.get(name, default)
    if required and not value:
        raise RuntimeError(f"Missing required secret: {name}")
    return value

