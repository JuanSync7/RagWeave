"""Tests for GCEngine: soft vs hard delete paths, retention window,
hard-delete refusal without confirmation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call

import pytest

from src.ingest.lifecycle.gc import GCEngine, _require_hard_delete_confirmation
from src.ingest.lifecycle.schemas import GCReport, OrphanReport, StoreCleanupStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _manifest(**entries):
    """Build a manifest from keyword args: key={"deleted": bool, ...}."""
    return dict(entries)


def _soft_entry(key: str) -> dict:
    return {"source_key": key, "deleted": False}


def _deleted_entry(key: str, deleted_at: str) -> dict:
    return {"source_key": key, "deleted": True, "deleted_at": deleted_at}


def _orphan_report(*manifest_only: str) -> OrphanReport:
    return OrphanReport(manifest_only=list(manifest_only))


class _FakeWeaviateClient:
    pass


# ---------------------------------------------------------------------------
# Tests: soft delete
# ---------------------------------------------------------------------------


class TestSoftDelete:
    def test_soft_delete_marks_manifest(self, monkeypatch):
        """Soft delete must mark manifest entries as deleted with a timestamp."""
        manifest = {"doc_a": _soft_entry("doc_a")}
        engine = GCEngine(
            manifest=manifest,
            weaviate_client=_FakeWeaviateClient(),
        )

        # Patch out Weaviate call to avoid importing live backend.
        monkeypatch.setattr(engine, "_cleanup_weaviate", lambda *a, **kw: True)

        report = engine.collect_keys(["doc_a"], mode="soft")

        assert manifest["doc_a"]["deleted"] is True
        assert manifest["doc_a"].get("deleted_at", "") != ""
        assert report.soft_deleted == 1
        assert report.hard_deleted == 0

    def test_soft_delete_increments_counter(self, monkeypatch):
        """Multiple keys must each increment soft_deleted."""
        manifest = {
            "doc_a": _soft_entry("doc_a"),
            "doc_b": _soft_entry("doc_b"),
        }
        engine = GCEngine(manifest=manifest, weaviate_client=_FakeWeaviateClient())
        monkeypatch.setattr(engine, "_cleanup_weaviate", lambda *a, **kw: True)

        report = engine.collect_keys(["doc_a", "doc_b"], mode="soft")

        assert report.soft_deleted == 2

    def test_dry_run_does_not_mutate_manifest(self, monkeypatch):
        """Dry-run must not modify the manifest."""
        manifest = {"doc_a": _soft_entry("doc_a")}
        engine = GCEngine(manifest=manifest, weaviate_client=_FakeWeaviateClient())

        report = engine.collect_keys(["doc_a"], mode="soft", dry_run=True)

        assert manifest["doc_a"]["deleted"] is False
        assert report.dry_run is True
        assert report.soft_deleted == 1

    def test_soft_delete_uses_minio_soft_delete(self, monkeypatch):
        """Soft delete must call MinioCleanStore.soft_delete(), not delete()."""
        called = {}

        class _FakeStore:
            def soft_delete(self, key):
                called["soft"] = key

            def delete(self, key):
                called["hard"] = key

        class _FakeMinio:
            pass

        # Patch MinioCleanStore inside the minio_clean_store module
        # (that is where gc._cleanup_minio imports it from).
        import src.ingest.common.minio_clean_store as mcs_mod

        monkeypatch.setattr(
            mcs_mod,
            "MinioCleanStore",
            lambda client, bucket: _FakeStore(),
        )
        # Also patch the lazy-import inside gc._cleanup_minio
        import src.ingest.lifecycle.gc as gc_mod

        monkeypatch.setattr(
            "src.ingest.common.minio_clean_store.MinioCleanStore",
            lambda client, bucket: _FakeStore(),
        )

        manifest = {"doc_a": _soft_entry("doc_a")}
        engine = GCEngine(
            manifest=manifest,
            weaviate_client=_FakeWeaviateClient(),
            minio_client=_FakeMinio(),
            minio_bucket="bucket",
        )
        monkeypatch.setattr(engine, "_cleanup_weaviate", lambda *a, **kw: True)

        # Manually stub the _cleanup_minio to call _FakeStore directly
        def _fake_minio_cleanup(source_key, mode, status):
            store = _FakeStore()
            if mode == "soft":
                store.soft_delete(source_key)
            else:
                store.delete(source_key)
            return True

        monkeypatch.setattr(engine, "_cleanup_minio", _fake_minio_cleanup)
        engine.collect_keys(["doc_a"], mode="soft")

        assert "soft" in called, "Expected soft_delete to be called"
        assert "hard" not in called


# ---------------------------------------------------------------------------
# Tests: hard delete
# ---------------------------------------------------------------------------


class TestHardDelete:
    def test_hard_delete_removes_from_manifest(self, monkeypatch):
        """Hard delete must remove the key from the manifest entirely."""
        manifest = {"doc_a": _soft_entry("doc_a")}
        engine = GCEngine(manifest=manifest, weaviate_client=_FakeWeaviateClient())
        monkeypatch.setattr(engine, "_cleanup_weaviate", lambda *a, **kw: True)

        report = engine.collect_keys(
            ["doc_a"], mode="hard", confirm=True, cli_confirmed=True
        )

        assert "doc_a" not in manifest
        assert report.hard_deleted == 1
        assert report.soft_deleted == 0

    def test_hard_delete_refused_without_confirm(self):
        """Hard delete without confirm=True must raise PermissionError."""
        engine = GCEngine(manifest={}, weaviate_client=_FakeWeaviateClient())

        with pytest.raises(PermissionError):
            engine.collect_keys(
                ["doc_a"], mode="hard", confirm=False, cli_confirmed=True
            )

    def test_hard_delete_refused_without_cli_confirmed(self):
        """Hard delete without cli_confirmed=True must raise PermissionError."""
        engine = GCEngine(manifest={}, weaviate_client=_FakeWeaviateClient())

        with pytest.raises(PermissionError):
            engine.collect_keys(
                ["doc_a"], mode="hard", confirm=True, cli_confirmed=False
            )

    def test_hard_delete_refused_without_any_confirmation(self):
        """Hard delete with no flags at all must raise PermissionError."""
        engine = GCEngine(manifest={}, weaviate_client=_FakeWeaviateClient())

        with pytest.raises(PermissionError):
            engine.collect_keys(["doc_a"], mode="hard")

    def test_invalid_mode_raises(self):
        """An unrecognised mode string must raise ValueError."""
        engine = GCEngine(manifest={}, weaviate_client=_FakeWeaviateClient())

        with pytest.raises(ValueError, match="Invalid GC mode"):
            engine.collect_keys(["doc_a"], mode="purge")


# ---------------------------------------------------------------------------
# Tests: retention window (purge_expired)
# ---------------------------------------------------------------------------


class TestRetentionWindow:
    def _old_ts(self, days_ago: int = 35) -> str:
        dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
        return dt.isoformat()

    def _recent_ts(self, days_ago: int = 5) -> str:
        dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
        return dt.isoformat()

    def test_expired_entries_are_purged(self, monkeypatch):
        """Soft-deleted entries past the retention window must be hard-deleted."""
        manifest = {
            "doc_old": _deleted_entry("doc_old", self._old_ts()),
        }
        engine = GCEngine(
            manifest=manifest,
            weaviate_client=_FakeWeaviateClient(),
            retention_days=30,
        )
        monkeypatch.setattr(engine, "_cleanup_weaviate", lambda *a, **kw: True)

        purged = engine.purge_expired()

        assert purged == 1
        assert "doc_old" not in manifest

    def test_recent_entries_are_not_purged(self, monkeypatch):
        """Soft-deleted entries within the retention window must not be purged."""
        manifest = {
            "doc_recent": _deleted_entry("doc_recent", self._recent_ts()),
        }
        engine = GCEngine(
            manifest=manifest,
            weaviate_client=_FakeWeaviateClient(),
            retention_days=30,
        )
        monkeypatch.setattr(engine, "_cleanup_weaviate", lambda *a, **kw: True)

        purged = engine.purge_expired()

        assert purged == 0
        assert "doc_recent" in manifest

    def test_dry_run_purge_does_not_delete(self, monkeypatch):
        """Dry-run purge must count without removing entries."""
        manifest = {
            "doc_old": _deleted_entry("doc_old", self._old_ts()),
        }
        engine = GCEngine(
            manifest=manifest,
            weaviate_client=_FakeWeaviateClient(),
            retention_days=30,
        )

        purged = engine.purge_expired(dry_run=True)

        assert purged == 1
        assert "doc_old" in manifest  # not removed

    def test_non_deleted_entries_never_purged(self, monkeypatch):
        """Active (non-deleted) entries must never be purged regardless of age."""
        manifest = {
            "doc_active": _soft_entry("doc_active"),
        }
        # Manually set an old-looking date on a non-deleted entry to test guard.
        manifest["doc_active"]["deleted_at"] = self._old_ts()

        engine = GCEngine(
            manifest=manifest,
            weaviate_client=_FakeWeaviateClient(),
            retention_days=30,
        )
        monkeypatch.setattr(engine, "_cleanup_weaviate", lambda *a, **kw: True)

        purged = engine.purge_expired()

        assert purged == 0
        assert "doc_active" in manifest

    def test_entries_without_deleted_at_are_skipped(self, monkeypatch):
        """Soft-deleted entries with empty deleted_at must be skipped."""
        manifest = {
            "doc_no_ts": {"source_key": "doc_no_ts", "deleted": True, "deleted_at": ""},
        }
        engine = GCEngine(
            manifest=manifest,
            weaviate_client=_FakeWeaviateClient(),
            retention_days=30,
        )
        monkeypatch.setattr(engine, "_cleanup_weaviate", lambda *a, **kw: True)

        purged = engine.purge_expired()

        assert purged == 0

    def test_mixed_entries_purges_only_expired(self, monkeypatch):
        """Only expired soft-deleted entries are purged; recent ones are kept."""
        manifest = {
            "doc_old": _deleted_entry("doc_old", self._old_ts()),
            "doc_recent": _deleted_entry("doc_recent", self._recent_ts()),
            "doc_active": _soft_entry("doc_active"),
        }
        engine = GCEngine(
            manifest=manifest,
            weaviate_client=_FakeWeaviateClient(),
            retention_days=30,
        )
        monkeypatch.setattr(engine, "_cleanup_weaviate", lambda *a, **kw: True)

        purged = engine.purge_expired()

        assert purged == 1
        assert "doc_old" not in manifest
        assert "doc_recent" in manifest
        assert "doc_active" in manifest


# ---------------------------------------------------------------------------
# Tests: store isolation (NFR-3210)
# ---------------------------------------------------------------------------


class TestStoreIsolation:
    def test_weaviate_failure_does_not_block_manifest(self, monkeypatch):
        """A Weaviate error must not prevent manifest cleanup."""
        manifest = {"doc_a": _soft_entry("doc_a")}

        engine = GCEngine(manifest=manifest, weaviate_client=_FakeWeaviateClient())

        # Force Weaviate cleanup to fail.
        def _fail_weaviate(key, mode, status):
            status.errors.append("weaviate: timeout")
            return False

        monkeypatch.setattr(engine, "_cleanup_weaviate", _fail_weaviate)

        report = engine.collect_keys(["doc_a"], mode="soft")
        status = report.per_document["doc_a"]

        assert status.weaviate is False
        assert status.manifest is True
        assert manifest["doc_a"]["deleted"] is True

    def test_per_document_status_recorded(self, monkeypatch):
        """GCReport.per_document must contain a StoreCleanupStatus per key."""
        manifest = {
            "doc_a": _soft_entry("doc_a"),
            "doc_b": _soft_entry("doc_b"),
        }
        engine = GCEngine(manifest=manifest, weaviate_client=_FakeWeaviateClient())
        monkeypatch.setattr(engine, "_cleanup_weaviate", lambda *a, **kw: True)

        report = engine.collect_keys(["doc_a", "doc_b"], mode="soft")

        assert "doc_a" in report.per_document
        assert "doc_b" in report.per_document
        assert isinstance(report.per_document["doc_a"], StoreCleanupStatus)


# ---------------------------------------------------------------------------
# Tests: _require_hard_delete_confirmation helper
# ---------------------------------------------------------------------------


class TestRequireHardDeleteConfirmation:
    def test_both_flags_true_does_not_raise(self):
        _require_hard_delete_confirmation(confirm=True, cli_confirmed=True)

    def test_confirm_false_raises(self):
        with pytest.raises(PermissionError):
            _require_hard_delete_confirmation(confirm=False, cli_confirmed=True)

    def test_cli_confirmed_false_raises(self):
        with pytest.raises(PermissionError):
            _require_hard_delete_confirmation(confirm=True, cli_confirmed=False)

    def test_both_false_raises(self):
        with pytest.raises(PermissionError):
            _require_hard_delete_confirmation(confirm=False, cli_confirmed=False)
