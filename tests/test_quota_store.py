import tempfile
from pathlib import Path

from src.platform.security import quota_store


def test_tenant_quota_lifecycle():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "quotas.json"
        updated = quota_store.set_tenant_quota("tenant-a", 123, path=path)
        assert updated["requests_per_minute"] == 123
        assert quota_store.get_tenant_quota("tenant-a", path=path) == 123
        assert quota_store.delete_tenant_quota("tenant-a", path=path) is True

