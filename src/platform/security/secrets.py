# @summary
# Secret loading helper supporting NAME and NAME_FILE env conventions.
# Exports: get_secret
# Deps: os
# @end-summary
"""Secret loading helpers with explicit fail-fast.

Supports the common `*_FILE` pattern used by container orchestrators to inject
secrets via mounted files.
"""

from __future__ import annotations

import os


def get_secret(name: str, default: str | None = None, required: bool = False) -> str | None:
    """Resolve a secret from environment variables or a `*_FILE` indirection.

    If `<NAME>_FILE` is set, the secret is loaded from the referenced file and
    stripped. Otherwise `<NAME>` is read from the environment.

    Args:
        name: Secret environment variable name (without `_FILE` suffix).
        default: Default value if the env var is not set.
        required: Whether to raise if the resolved value is empty.

    Returns:
        The resolved secret value, or None if not set and not required.

    Raises:
        RuntimeError: If `required=True` and the resolved secret is empty.
    """
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

