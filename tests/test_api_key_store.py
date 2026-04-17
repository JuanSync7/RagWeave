import tempfile
from pathlib import Path

import pytest

from src.platform.security import api_key_store


def test_api_key_lifecycle():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "api_keys.json"
        created = api_key_store.create_api_key(
            subject="svc-a",
            tenant_id="t1",
            roles=["query"],
            description="test",
            path=path,
        )
        assert created["api_key"].startswith("ragk_")

        hit = api_key_store.lookup_api_key(created["api_key"], path=path)
        assert hit is not None
        assert hit["tenant_id"] == "t1"

        revoked = api_key_store.revoke_api_key(created["key_id"], path=path)
        assert revoked is True
        miss = api_key_store.lookup_api_key(created["api_key"], path=path)
        assert miss is None


def test_valid_key_format_passes():
    """Created API key has the expected `ragk_` prefix format."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "api_keys.json"
        result = api_key_store.create_api_key(
            subject="svc-format",
            tenant_id="t-fmt",
            roles=["query"],
            path=path,
        )
        raw_key = result["api_key"]
        assert raw_key.startswith("ragk_"), f"Expected ragk_ prefix, got: {raw_key}"
        # Should contain a dot separating key_id and secret parts
        assert "." in raw_key


def test_invalid_key_format_rejected():
    """A raw string that does not match any stored key is rejected (returns None)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "api_keys.json"
        result = api_key_store.lookup_api_key("not-a-valid-key-format", path=path)
        assert result is None


def test_tenant_isolation():
    """A key created for tenant A cannot be used to read tenant B's resource."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "api_keys.json"
        key_a = api_key_store.create_api_key(
            subject="svc-a",
            tenant_id="tenant-a",
            roles=["query"],
            path=path,
        )
        key_b = api_key_store.create_api_key(
            subject="svc-b",
            tenant_id="tenant-b",
            roles=["query"],
            path=path,
        )

        hit_a = api_key_store.lookup_api_key(key_a["api_key"], path=path)
        hit_b = api_key_store.lookup_api_key(key_b["api_key"], path=path)

        assert hit_a is not None
        assert hit_a["tenant_id"] == "tenant-a"

        assert hit_b is not None
        assert hit_b["tenant_id"] == "tenant-b"


def test_revoked_key_returns_none():
    """After revocation the key no longer resolves to a principal."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "api_keys.json"
        created = api_key_store.create_api_key(
            subject="svc-rev",
            tenant_id="t-rev",
            path=path,
        )
        raw_key = created["api_key"]

        # Key works before revocation
        assert api_key_store.lookup_api_key(raw_key, path=path) is not None

        # Revoke it
        assert api_key_store.revoke_api_key(created["key_id"], path=path) is True

        # Key is rejected after revocation
        assert api_key_store.lookup_api_key(raw_key, path=path) is None

