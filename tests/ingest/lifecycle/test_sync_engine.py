"""Tests for SyncEngine: inventory and diff logic.

All external stores (Weaviate, MinIO, Neo4j) are replaced with lightweight
mocks so that these tests are pure-unit and have no I/O dependencies.
"""

from __future__ import annotations

import pytest

from src.ingest.lifecycle.schemas import OrphanReport, StoreInventory
from src.ingest.lifecycle.sync import SyncEngine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _manifest(*source_keys: str, deleted_keys: list[str] | None = None) -> dict:
    """Build a minimal manifest with the given source_keys."""
    manifest: dict = {}
    for key in source_keys:
        manifest[key] = {"source_key": key, "deleted": False}
    for key in deleted_keys or []:
        manifest[key] = {"source_key": key, "deleted": True}
    return manifest


class _MockWeaviateClient:
    """Stub that returns a fixed set of source_keys via aggregate_by_source."""

    def __init__(self, keys: list[str]) -> None:
        self._keys = keys


class _MockMinioClient:
    """Stub MinIO client whose list_objects returns nothing."""

    def list_objects(self, bucket, prefix="", recursive=False):
        return []


class _MockMinioClientWithKeys:
    """Stub MinIO client that simulates stored clean objects."""

    def __init__(self, keys: list[str]) -> None:
        import types

        self._keys = keys
        self._bucket = "test-bucket"

    def list_objects(self, bucket, prefix="", recursive=False):
        import types

        objects = []
        for key in self._keys:
            obj = types.SimpleNamespace(object_name=f"{prefix}{key}.meta.json")
            objects.append(obj)
        return objects

    def stat_object(self, bucket, key):
        return True


class _MockNeo4jClient:
    """Stub KG backend with list_source_keys."""

    def __init__(self, keys: list[str]) -> None:
        self._keys = keys

    def list_source_keys(self) -> list[str]:
        return list(self._keys)


# ---------------------------------------------------------------------------
# Helper: patch aggregate_by_source
# ---------------------------------------------------------------------------


def _make_sync_engine(
    manifest: dict,
    weaviate_keys: list[str] | None = None,
    minio_keys: list[str] | None = None,
    neo4j_keys: list[str] | None = None,
    monkeypatch=None,
) -> SyncEngine:
    """Build a SyncEngine with patched store enumeration."""
    weaviate_client = _MockWeaviateClient(weaviate_keys or [])
    minio_client = _MockMinioClientWithKeys(minio_keys) if minio_keys is not None else None
    neo4j_client = _MockNeo4jClient(neo4j_keys) if neo4j_keys is not None else None

    engine = SyncEngine(
        manifest=manifest,
        weaviate_client=weaviate_client,
        minio_client=minio_client,
        minio_bucket="test-bucket",
        neo4j_client=neo4j_client,
    )

    if monkeypatch is not None and weaviate_keys is not None:
        _patch_aggregate(monkeypatch, weaviate_keys)

    return engine


def _patch_aggregate(monkeypatch, keys: list[str]):
    """Patch src.vector_db.aggregate_by_source to return fixed keys."""
    import src.vector_db as vdb

    def _fake_aggregate(client, collection=None, source_filter=None, connector_filter=None):
        return [{"source_key": k} for k in keys]

    monkeypatch.setattr(vdb, "aggregate_by_source", _fake_aggregate)


# ---------------------------------------------------------------------------
# Tests: inventory()
# ---------------------------------------------------------------------------


class TestInventory:
    def test_manifest_keys_exclude_deleted(self, monkeypatch):
        """Deleted manifest entries must not appear in inventory.manifest_keys."""
        manifest = _manifest("doc_a", "doc_b", deleted_keys=["doc_c"])
        engine = _make_sync_engine(manifest, weaviate_keys=[], monkeypatch=monkeypatch)

        inv = engine.inventory()

        assert "doc_a" in inv.manifest_keys
        assert "doc_b" in inv.manifest_keys
        assert "doc_c" not in inv.manifest_keys

    def test_weaviate_keys_populated(self, monkeypatch):
        """Weaviate keys from aggregate_by_source must appear in inventory."""
        manifest = _manifest("doc_a")
        engine = _make_sync_engine(
            manifest,
            weaviate_keys=["doc_a", "doc_orphan"],
            monkeypatch=monkeypatch,
        )

        inv = engine.inventory()

        assert "doc_a" in inv.weaviate_keys
        assert "doc_orphan" in inv.weaviate_keys

    def test_minio_keys_populated(self, monkeypatch):
        """MinIO keys returned by list_keys must appear in inventory."""
        manifest = _manifest("doc_a")
        engine = _make_sync_engine(
            manifest,
            weaviate_keys=[],
            minio_keys=["doc_a", "doc_minio_orphan"],
            monkeypatch=monkeypatch,
        )

        inv = engine.inventory()

        assert "doc_a" in inv.minio_keys
        assert "doc_minio_orphan" in inv.minio_keys

    def test_neo4j_keys_populated(self, monkeypatch):
        """Neo4j client.list_source_keys() must appear in inventory."""
        manifest = _manifest("doc_a")
        engine = _make_sync_engine(
            manifest,
            weaviate_keys=[],
            neo4j_keys=["doc_a", "doc_kg_orphan"],
            monkeypatch=monkeypatch,
        )

        inv = engine.inventory()

        assert "doc_a" in inv.neo4j_keys
        assert "doc_kg_orphan" in inv.neo4j_keys

    def test_weaviate_error_recorded(self, monkeypatch):
        """Weaviate enumeration errors must be captured in weaviate_error."""
        manifest = _manifest("doc_a")

        def _fail_aggregate(*args, **kwargs):
            raise RuntimeError("weaviate down")

        import src.vector_db as vdb
        monkeypatch.setattr(vdb, "aggregate_by_source", _fail_aggregate)

        engine = SyncEngine(
            manifest=manifest,
            weaviate_client=_MockWeaviateClient([]),
        )
        inv = engine.inventory()

        assert inv.weaviate_error is not None
        assert "weaviate down" in inv.weaviate_error
        assert inv.weaviate_keys == set()

    def test_no_minio_client_skips_minio(self, monkeypatch):
        """When minio_client is None, minio_keys must remain empty with no error."""
        manifest = _manifest("doc_a")
        engine = _make_sync_engine(
            manifest, weaviate_keys=[], minio_keys=None, monkeypatch=monkeypatch
        )
        inv = engine.inventory()

        assert inv.minio_keys == set()
        assert inv.minio_error is None

    def test_no_neo4j_client_skips_neo4j(self, monkeypatch):
        """When neo4j_client is None, neo4j_keys must remain empty with no error."""
        manifest = _manifest("doc_a")
        engine = _make_sync_engine(
            manifest, weaviate_keys=[], neo4j_keys=None, monkeypatch=monkeypatch
        )
        inv = engine.inventory()

        assert inv.neo4j_keys == set()
        assert inv.neo4j_error is None

    def test_empty_manifest_and_stores(self, monkeypatch):
        """All empty inputs produce a fully empty inventory."""
        engine = _make_sync_engine({}, weaviate_keys=[], monkeypatch=monkeypatch)
        inv = engine.inventory()

        assert inv.manifest_keys == set()
        assert inv.weaviate_keys == set()
        assert inv.minio_keys == set()
        assert inv.neo4j_keys == set()


# ---------------------------------------------------------------------------
# Tests: diff()
# ---------------------------------------------------------------------------


class TestDiff:
    def _build_inventory(
        self,
        manifest_keys: set[str],
        weaviate_keys: set[str] | None = None,
        minio_keys: set[str] | None = None,
        neo4j_keys: set[str] | None = None,
    ) -> StoreInventory:
        return StoreInventory(
            manifest_keys=manifest_keys,
            weaviate_keys=weaviate_keys or set(),
            minio_keys=minio_keys or set(),
            neo4j_keys=neo4j_keys or set(),
        )

    def test_weaviate_orphan_detected(self):
        """Key in Weaviate but not in manifest -> weaviate_orphans."""
        inv = self._build_inventory(
            manifest_keys={"doc_a"},
            weaviate_keys={"doc_a", "doc_orphan"},
        )
        engine = SyncEngine(manifest={}, weaviate_client=None)
        report = engine.diff(inv)

        assert "doc_orphan" in report.weaviate_orphans
        assert "doc_a" not in report.weaviate_orphans

    def test_minio_orphan_detected(self):
        """Key in MinIO but not in manifest -> minio_orphans."""
        inv = self._build_inventory(
            manifest_keys={"doc_a"},
            minio_keys={"doc_a", "minio_ghost"},
        )
        engine = SyncEngine(manifest={}, weaviate_client=None)
        report = engine.diff(inv)

        assert "minio_ghost" in report.minio_orphans

    def test_neo4j_orphan_detected(self):
        """Key in Neo4j but not in manifest -> neo4j_orphans."""
        inv = self._build_inventory(
            manifest_keys={"doc_a"},
            neo4j_keys={"doc_a", "kg_ghost"},
        )
        engine = SyncEngine(manifest={}, weaviate_client=None)
        report = engine.diff(inv)

        assert "kg_ghost" in report.neo4j_orphans

    def test_manifest_only_detected(self):
        """Key in manifest but in no store -> manifest_only."""
        inv = self._build_inventory(
            manifest_keys={"doc_a", "doc_b"},
            weaviate_keys={"doc_a"},
            minio_keys={"doc_a"},
        )
        engine = SyncEngine(manifest={}, weaviate_client=None)
        report = engine.diff(inv)

        assert "doc_b" in report.manifest_only
        assert "doc_a" not in report.manifest_only

    def test_no_orphans_when_all_match(self):
        """No orphans when all store keys exactly match manifest keys."""
        inv = self._build_inventory(
            manifest_keys={"doc_a", "doc_b"},
            weaviate_keys={"doc_a", "doc_b"},
            minio_keys={"doc_a", "doc_b"},
            neo4j_keys={"doc_a", "doc_b"},
        )
        engine = SyncEngine(manifest={}, weaviate_client=None)
        report = engine.diff(inv)

        assert report.weaviate_orphans == []
        assert report.minio_orphans == []
        assert report.neo4j_orphans == []
        assert report.manifest_only == []

    def test_orphan_lists_are_sorted(self):
        """Orphan lists in the report must be lexicographically sorted."""
        inv = self._build_inventory(
            manifest_keys=set(),
            weaviate_keys={"z_key", "a_key", "m_key"},
        )
        engine = SyncEngine(manifest={}, weaviate_client=None)
        report = engine.diff(inv)

        assert report.weaviate_orphans == sorted(report.weaviate_orphans)

    def test_empty_inventory_produces_empty_report(self):
        """All-empty inventory produces an empty OrphanReport."""
        inv = self._build_inventory(manifest_keys=set())
        engine = SyncEngine(manifest={}, weaviate_client=None)
        report = engine.diff(inv)

        assert isinstance(report, OrphanReport)
        assert report.weaviate_orphans == []
        assert report.manifest_only == []


# ---------------------------------------------------------------------------
# Tests: Neo4j client missing list_source_keys
# ---------------------------------------------------------------------------


class TestNeo4jFallback:
    def test_neo4j_without_list_source_keys_returns_empty(self, monkeypatch):
        """A Neo4j client lacking list_source_keys() is gracefully skipped."""

        class _NoListClient:
            pass  # no list_source_keys

        manifest = _manifest("doc_a")
        engine = SyncEngine(
            manifest=manifest,
            weaviate_client=_MockWeaviateClient([]),
            neo4j_client=_NoListClient(),
        )
        _patch_aggregate(monkeypatch, [])
        inv = engine.inventory()

        assert inv.neo4j_keys == set()
        assert inv.neo4j_error is None
