"""Persistent quota policy store by tenant/project."""

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
    path.parent.mkdir(parents=True, exist_ok=True)


def _read_store(path: Path = AUTH_QUOTAS_STORE_PATH) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {"tenants": {}, "projects": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {"tenants": {}, "projects": {}}
    data.setdefault("tenants", {})
    data.setdefault("projects", {})
    return data


def _write_store(payload: dict[str, dict[str, Any]], path: Path = AUTH_QUOTAS_STORE_PATH) -> None:
    _ensure_parent(path)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def get_tenant_quota(tenant_id: str, path: Path = AUTH_QUOTAS_STORE_PATH) -> int:
    with _LOCK:
        data = _read_store(path)
    return int(data["tenants"].get(tenant_id, RATE_LIMIT_DEFAULT_TENANT_RPM))


def set_tenant_quota(
    tenant_id: str,
    requests_per_minute: int,
    path: Path = AUTH_QUOTAS_STORE_PATH,
) -> dict[str, Any]:
    rpm = max(1, int(requests_per_minute))
    with _LOCK:
        data = _read_store(path)
        data["tenants"][tenant_id] = rpm
        _write_store(data, path)
    return {"tenant_id": tenant_id, "requests_per_minute": rpm}


def delete_tenant_quota(tenant_id: str, path: Path = AUTH_QUOTAS_STORE_PATH) -> bool:
    with _LOCK:
        data = _read_store(path)
        existed = tenant_id in data["tenants"]
        data["tenants"].pop(tenant_id, None)
        _write_store(data, path)
    return existed


def list_quotas(path: Path = AUTH_QUOTAS_STORE_PATH) -> dict[str, Any]:
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

