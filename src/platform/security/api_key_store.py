# @summary
# Persistent API key lifecycle store (create/list/revoke/lookup) backed by a JSON file.
# Exports: create_api_key, list_api_keys, revoke_api_key, lookup_api_key
# Deps: config.settings, hashlib, json, secrets, threading, time, pathlib
# @end-summary
"""Persistent API key lifecycle store.

This module stores API keys in a local JSON file (for dev/small deployments),
keeping only a SHA-256 hash of the raw key at rest.
"""

from __future__ import annotations

import hashlib
import orjson
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from config.settings import AUTH_API_KEYS_STORE_PATH, DEFAULT_TENANT_ID

_LOCK = threading.Lock()


def _ensure_parent(path: Path) -> None:
    """Create parent directories for a store file if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)


def _read_store(path: Path = AUTH_API_KEYS_STORE_PATH) -> dict[str, dict[str, Any]]:
    """Read the JSON key store from disk.

    Args:
        path: Store file path.

    Returns:
        Mapping of key id to stored record.
    """
    if not path.exists():
        return {}
    data = orjson.loads(path.read_bytes())
    if isinstance(data, dict):
        return data
    return {}


def _write_store(payload: dict[str, dict[str, Any]], path: Path = AUTH_API_KEYS_STORE_PATH) -> None:
    """Atomically write the JSON key store to disk.

    Args:
        payload: Store contents to write.
        path: Store file path.
    """
    _ensure_parent(path)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS))
    tmp.replace(path)


def _hash_key(raw: str) -> str:
    """Hash a raw API key for storage."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_api_key(
    *,
    subject: str,
    tenant_id: str | None = None,
    roles: list[str] | None = None,
    description: str = "",
    path: Path = AUTH_API_KEYS_STORE_PATH,
) -> dict[str, Any]:
    """Create and persist a new API key record.

    Args:
        subject: Subject identifier (user/service).
        tenant_id: Optional tenant id (defaults to configured default tenant).
        roles: Optional list of roles assigned to the key.
        description: Optional human-readable description.
        path: Store file path.

    Returns:
        A dict containing the `api_key` (raw secret) and record metadata.
    """
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


def list_api_keys(
    include_revoked: bool = False, path: Path = AUTH_API_KEYS_STORE_PATH
) -> list[dict[str, Any]]:
    """List API keys stored on disk.

    Args:
        include_revoked: Whether to include revoked keys.
        path: Store file path.

    Returns:
        A list of key records with `key_hash` removed.
    """
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
    """Revoke an API key by id.

    Args:
        key_id: Key identifier to revoke.
        path: Store file path.

    Returns:
        True if the key was revoked; False if not found or already revoked.
    """
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
    """Look up an API key record by raw key value.

    Args:
        raw_key: Raw API key presented by a client.
        path: Store file path.

    Returns:
        The matching record (including `key_id`) if found and not revoked; otherwise None.
    """
    hashed = _hash_key(raw_key)
    with _LOCK:
        data = _read_store(path)
    for key_id, rec in data.items():
        if rec.get("revoked_at"):
            continue
        if rec.get("key_hash") == hashed:
            return {"key_id": key_id, **rec}
    return None

