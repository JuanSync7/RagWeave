import tempfile
from pathlib import Path

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

