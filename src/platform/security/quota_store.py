# @summary
# Persistent rate-limit quota policy store keyed by tenant and project.
# Exports: get_tenant_quota, set_tenant_quota, delete_tenant_quota, list_quotas
# Deps: config.settings, json, threading, pathlib
# @end-summary
"""Persistent rate-limit quota policy store.

This module stores per-tenant and per-project request-per-minute quotas in a
local JSON file for small deployments and development.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from config.settings import (
    AUTH_QUOTAS_STORE_PATH,
    RATE_LIMIT_DEFAULT_PROJECT_RPM,
    RATE_LIMIT_DEFAULT_TENANT_RPM,
)

_LOCK = threading.Lock()


def _ensure_parent(path: Path) -> None:
    """Create parent directories for a store file if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)


def _read_store(path: Path = AUTH_QUOTAS_STORE_PATH) -> dict[str, dict[str, Any]]:
    """Read the quota store from disk.

    Args:
        path: Store file path.

    Returns:
        Store payload with `tenants` and `projects` keys present.
    """
    if not path.exists():
        return {"tenants": {}, "projects": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {"tenants": {}, "projects": {}}
    data.setdefault("tenants", {})
    data.setdefault("projects", {})
    return data


def _write_store(payload: dict[str, dict[str, Any]], path: Path = AUTH_QUOTAS_STORE_PATH) -> None:
    """Atomically write the quota store to disk.

    Args:
        payload: Store payload to write.
        path: Store file path.
    """
    _ensure_parent(path)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def get_tenant_quota(tenant_id: str, path: Path = AUTH_QUOTAS_STORE_PATH) -> int:
    """Get the configured request-per-minute quota for a tenant.

    Args:
        tenant_id: Tenant identifier.
        path: Store file path.

    Returns:
        Requests-per-minute quota for the tenant, falling back to the default.
    """
    with _LOCK:
        data = _read_store(path)
    return int(data["tenants"].get(tenant_id, RATE_LIMIT_DEFAULT_TENANT_RPM))


def set_tenant_quota(
    tenant_id: str,
    requests_per_minute: int,
    path: Path = AUTH_QUOTAS_STORE_PATH,
) -> dict[str, Any]:
    """Set the request-per-minute quota for a tenant.

    Args:
        tenant_id: Tenant identifier.
        requests_per_minute: Requested RPM value (clamped to at least 1).
        path: Store file path.

    Returns:
        A JSON-serializable payload describing the updated quota.
    """
    rpm = max(1, int(requests_per_minute))
    with _LOCK:
        data = _read_store(path)
        data["tenants"][tenant_id] = rpm
        _write_store(data, path)
    return {"tenant_id": tenant_id, "requests_per_minute": rpm}


def delete_tenant_quota(tenant_id: str, path: Path = AUTH_QUOTAS_STORE_PATH) -> bool:
    """Delete any configured quota override for a tenant.

    Args:
        tenant_id: Tenant identifier.
        path: Store file path.

    Returns:
        True if an override existed and was removed; otherwise False.
    """
    with _LOCK:
        data = _read_store(path)
        existed = tenant_id in data["tenants"]
        data["tenants"].pop(tenant_id, None)
        _write_store(data, path)
    return existed


def list_quotas(path: Path = AUTH_QUOTAS_STORE_PATH) -> dict[str, Any]:
    """List all quota overrides and defaults.

    Args:
        path: Store file path.

    Returns:
        JSON-serializable payload containing defaults and overrides.
    """
    with _LOCK:
        data = _read_store(path)
    return {
        "defaults": {
            "tenant_rpm": RATE_LIMIT_DEFAULT_TENANT_RPM,
            "project_rpm": RATE_LIMIT_DEFAULT_PROJECT_RPM,
        },
        "tenants": data.get("tenants", {}),
        "projects": data.get("projects", {}),
    }

