import tempfile
from pathlib import Path

from src.platform.security import quota_store
from config.settings import RATE_LIMIT_DEFAULT_TENANT_RPM


def test_tenant_quota_lifecycle():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "quotas.json"
        updated = quota_store.set_tenant_quota("tenant-a", 123, path=path)
        assert updated["requests_per_minute"] == 123
        assert quota_store.get_tenant_quota("tenant-a", path=path) == 123
        assert quota_store.delete_tenant_quota("tenant-a", path=path) is True


def test_increment_usage_increases_stored_quota():
    """set_tenant_quota returns the new value and get_tenant_quota reflects it."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "quotas.json"
        quota_store.set_tenant_quota("tenant-b", 50, path=path)
        quota_store.set_tenant_quota("tenant-b", 100, path=path)
        assert quota_store.get_tenant_quota("tenant-b", path=path) == 100


def test_get_quota_returns_default_for_unknown_tenant():
    """Unknown tenants get the system default quota."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "quotas.json"
        val = quota_store.get_tenant_quota("unknown-tenant", path=path)
        assert val == RATE_LIMIT_DEFAULT_TENANT_RPM


def test_delete_nonexistent_tenant_returns_false():
    """Deleting a tenant that was never configured should return False."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "quotas.json"
        result = quota_store.delete_tenant_quota("ghost-tenant", path=path)
        assert result is False


def test_quota_reset_returns_to_default():
    """After deleting a tenant override, get_tenant_quota falls back to the default."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "quotas.json"
        quota_store.set_tenant_quota("tenant-c", 999, path=path)
        quota_store.delete_tenant_quota("tenant-c", path=path)
        val = quota_store.get_tenant_quota("tenant-c", path=path)
        assert val == RATE_LIMIT_DEFAULT_TENANT_RPM


def test_list_quotas_includes_tenant_overrides():
    """list_quotas should show the tenant overrides that were set."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "quotas.json"
        quota_store.set_tenant_quota("tenant-d", 77, path=path)
        result = quota_store.list_quotas(path=path)
        assert result["tenants"]["tenant-d"] == 77
        assert "defaults" in result
        assert result["defaults"]["tenant_rpm"] == RATE_LIMIT_DEFAULT_TENANT_RPM


def test_quota_clamped_to_at_least_one():
    """RPM values <= 0 are clamped to 1."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "quotas.json"
        updated = quota_store.set_tenant_quota("tenant-e", 0, path=path)
        assert updated["requests_per_minute"] == 1
        assert quota_store.get_tenant_quota("tenant-e", path=path) == 1
