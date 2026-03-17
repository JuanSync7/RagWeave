"""Persistent API key lifecycle store."""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from config.settings import AUTH_API_KEYS_STORE_PATH, DEFAULT_TENANT_ID

_LOCK = threading.Lock()


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _read_store(path: Path = AUTH_API_KEYS_STORE_PATH) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data
    return {}


def _write_store(payload: dict[str, dict[str, Any]], path: Path = AUTH_API_KEYS_STORE_PATH) -> None:
    _ensure_parent(path)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_api_key(
    *,
    subject: str,
    tenant_id: str | None = None,
    roles: list[str] | None = None,
    description: str = "",
    path: Path = AUTH_API_KEYS_STORE_PATH,
) -> dict[str, Any]:
    tenant = tenant_id or DEFAULT_TENANT_ID
    key_id = f"key_{secrets.token_hex(8)}"
    secret = secrets.token_urlsafe(32)
    raw_key = f"ragk_{key_id}.{secret}"
    now = int(time.time())
    record = {
        "subject": subject,
        "tenant_id": tenant,
        "roles": roles or ["query"],
        "description": description,
        "key_hash": _hash_key(raw_key),
        "created_at": now,
        "revoked_at": None,
    }
    with _LOCK:
        data = _read_store(path)
        data[key_id] = record
        _write_store(data, path)
    return {"key_id": key_id, "api_key": raw_key, **record}


def list_api_keys(include_revoked: bool = False, path: Path = AUTH_API_KEYS_STORE_PATH) -> list[dict[str, Any]]:
    with _LOCK:
        data = _read_store(path)
    out = []
    for key_id, record in sorted(data.items()):
        if record.get("revoked_at") and not include_revoked:
            continue
        item = {"key_id": key_id, **record}
        item.pop("key_hash", None)
        out.append(item)
    return out


def revoke_api_key(key_id: str, path: Path = AUTH_API_KEYS_STORE_PATH) -> bool:
    with _LOCK:
        data = _read_store(path)
        if key_id not in data:
            return False
        if data[key_id].get("revoked_at") is not None:
            return False
        data[key_id]["revoked_at"] = int(time.time())
        _write_store(data, path)
    return True


def lookup_api_key(raw_key: str, path: Path = AUTH_API_KEYS_STORE_PATH) -> dict[str, Any] | None:
    hashed = _hash_key(raw_key)
    with _LOCK:
        data = _read_store(path)
    for key_id, rec in data.items():
        if rec.get("revoked_at"):
            continue
        if rec.get("key_hash") == hashed:
            return {"key_id": key_id, **rec}
    return None

