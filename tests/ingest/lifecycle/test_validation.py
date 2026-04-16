"""Tests for E2EValidator.

Covers:
- validate_by_trace_id: all stores consistent; one store missing; KG disabled.
- validate_all: bulk validation with full consistency and mixed results.
- validate_all with sample_size.
- Disabled stores reported as None (not False).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.ingest.lifecycle import E2EValidator, ValidationReport


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _manifest(
    trace_id: str = "trace-0001",
    source_key: str = "local:doc_a.md",
    deleted: bool = False,
) -> dict:
    return {
        source_key: {
            "source_key": source_key,
            "trace_id": trace_id,
            "schema_version": "1.0.0",
            "deleted": deleted,
        }
    }


def _patch_weaviate_count(monkeypatch, count: int):
    """Inject count_by_trace_id into the vector_db facade (raising=False handles missing attr)."""
    import src.vector_db as vdb_module

    monkeypatch.setattr(
        vdb_module,
        "count_by_trace_id",
        lambda client, tid, collection=None: count,
        raising=False,
    )


# ---------------------------------------------------------------------------
# validate_by_trace_id — all stores consistent
# ---------------------------------------------------------------------------


class TestValidateByTraceIdConsistent:
    def test_consistent_when_all_stores_ok(self, monkeypatch) -> None:
        """All stores report data — consistent=True."""
        trace_id = "trace-0001"
        source_key = "local:doc_a.md"
        manifest = _manifest(trace_id=trace_id, source_key=source_key)

        _patch_weaviate_count(monkeypatch, count=5)

        minio_stub = MagicMock()
        minio_stub.exists.return_value = True

        client = MagicMock()
        validator = E2EValidator(client=client, minio=minio_stub)
        report = validator.validate_by_trace_id(trace_id, manifest=manifest)

        assert report.consistent is True
        assert len(report.findings) == 1
        f = report.findings[0]
        assert f.weaviate_ok is True
        assert f.minio_ok is True
        assert f.neo4j_ok is None  # KG disabled
        assert f.manifest_ok is True
        assert f.missing_stores == []


class TestValidateByTraceIdMissingStore:
    def test_weaviate_missing_makes_inconsistent(self, monkeypatch) -> None:
        """Zero chunks in Weaviate => weaviate_ok=False, consistent=False."""
        trace_id = "trace-0002"
        source_key = "local:doc_b.md"
        manifest = _manifest(trace_id=trace_id, source_key=source_key)

        _patch_weaviate_count(monkeypatch, count=0)

        minio_stub = MagicMock()
        minio_stub.exists.return_value = True

        client = MagicMock()
        validator = E2EValidator(client=client, minio=minio_stub)
        report = validator.validate_by_trace_id(trace_id, manifest=manifest)

        assert report.consistent is False
        assert report.findings[0].weaviate_ok is False
        assert "weaviate" in report.findings[0].missing_stores

    def test_minio_missing_makes_inconsistent(self, monkeypatch) -> None:
        """MinIO exists() returns False => minio_ok=False, consistent=False."""
        trace_id = "trace-0003"
        source_key = "local:doc_c.md"
        manifest = _manifest(trace_id=trace_id, source_key=source_key)

        _patch_weaviate_count(monkeypatch, count=3)

        minio_stub = MagicMock()
        minio_stub.exists.return_value = False

        client = MagicMock()
        validator = E2EValidator(client=client, minio=minio_stub)
        report = validator.validate_by_trace_id(trace_id, manifest=manifest)

        assert report.consistent is False
        assert report.findings[0].minio_ok is False
        assert "minio" in report.findings[0].missing_stores

    def test_manifest_missing_makes_inconsistent(self, monkeypatch) -> None:
        """trace_id not in manifest => manifest_ok=False, consistent=False."""
        trace_id = "trace-unknown"
        # Empty manifest — trace_id won't resolve to any source_key.
        manifest: dict = {}

        _patch_weaviate_count(monkeypatch, count=2)

        minio_stub = MagicMock()
        minio_stub.exists.return_value = True

        client = MagicMock()
        validator = E2EValidator(client=client, minio=minio_stub)
        report = validator.validate_by_trace_id(trace_id, manifest=manifest)

        assert report.consistent is False
        assert report.findings[0].manifest_ok is False


class TestValidateByTraceIdKgDisabled:
    def test_kg_none_reports_neo4j_ok_as_none(self, monkeypatch) -> None:
        """When kg=None, neo4j_ok is None (not False) per FR-3062."""
        trace_id = "trace-0004"
        source_key = "local:doc_d.md"
        manifest = _manifest(trace_id=trace_id, source_key=source_key)

        _patch_weaviate_count(monkeypatch, count=4)

        minio_stub = MagicMock()
        minio_stub.exists.return_value = True

        client = MagicMock()
        # No kg= passed — defaults to None.
        validator = E2EValidator(client=client, minio=minio_stub, kg=None)
        report = validator.validate_by_trace_id(trace_id, manifest=manifest)

        assert report.findings[0].neo4j_ok is None
        # Should still be consistent when KG is disabled.
        assert report.consistent is True

    def test_kg_enabled_with_triples_is_consistent(self, monkeypatch) -> None:
        """When KG is enabled and has triples, neo4j_ok=True."""
        trace_id = "trace-0005"
        source_key = "local:doc_e.md"
        manifest = _manifest(trace_id=trace_id, source_key=source_key)

        _patch_weaviate_count(monkeypatch, count=6)

        minio_stub = MagicMock()
        minio_stub.exists.return_value = True

        kg_stub = MagicMock()
        kg_stub.count_triples_by_trace_id.return_value = 12

        client = MagicMock()
        validator = E2EValidator(client=client, minio=minio_stub, kg=kg_stub)
        report = validator.validate_by_trace_id(trace_id, manifest=manifest)

        assert report.findings[0].neo4j_ok is True
        assert report.findings[0].kg_triple_count == 12
        assert report.consistent is True


# ---------------------------------------------------------------------------
# validate_all — bulk validation
# ---------------------------------------------------------------------------


class TestValidateAll:
    def _build_manifest_multi(self) -> dict:
        return {
            "local:doc_a.md": {
                "source_key": "local:doc_a.md",
                "trace_id": "trace-a",
                "schema_version": "1.0.0",
                "deleted": False,
            },
            "local:doc_b.md": {
                "source_key": "local:doc_b.md",
                "trace_id": "trace-b",
                "schema_version": "1.0.0",
                "deleted": False,
            },
            "local:doc_c.md": {
                "source_key": "local:doc_c.md",
                "trace_id": "",  # No trace_id — should be skipped.
                "schema_version": "1.0.0",
                "deleted": False,
            },
            "local:doc_deleted.md": {
                "source_key": "local:doc_deleted.md",
                "trace_id": "trace-deleted",
                "schema_version": "1.0.0",
                "deleted": True,
            },
        }

    def test_validate_all_consistent(self, monkeypatch) -> None:
        manifest = self._build_manifest_multi()

        _patch_weaviate_count(monkeypatch, count=3)

        minio_stub = MagicMock()
        minio_stub.exists.return_value = True

        client = MagicMock()
        validator = E2EValidator(client=client, minio=minio_stub)
        report = validator.validate_all(manifest=manifest)

        # Only doc_a and doc_b have trace_ids; doc_c is empty, doc_deleted is deleted.
        assert report.total_checked == 2
        assert report.consistent is True
        assert report.inconsistent_count == 0

    def test_validate_all_one_inconsistent(self, monkeypatch) -> None:
        manifest = self._build_manifest_multi()

        call_count = {"n": 0}

        def count_fn(client, tid, collection=None):
            call_count["n"] += 1
            # Return 0 for the second call to simulate a missing store.
            return 0 if call_count["n"] == 2 else 3

        import src.vector_db as vdb_module

        monkeypatch.setattr(
            vdb_module, "count_by_trace_id", count_fn, raising=False
        )

        minio_stub = MagicMock()
        minio_stub.exists.return_value = True

        client = MagicMock()
        validator = E2EValidator(client=client, minio=minio_stub)
        report = validator.validate_all(manifest=manifest)

        assert report.total_checked == 2
        assert report.inconsistent_count == 1
        assert report.consistent is False

    def test_validate_all_with_sample_size(self, monkeypatch) -> None:
        """sample_size limits the number of entries validated."""
        manifest = {}
        for i in range(10):
            key = f"local:doc_{i}.md"
            manifest[key] = {
                "source_key": key,
                "trace_id": f"trace-{i:04d}",
                "schema_version": "1.0.0",
                "deleted": False,
            }

        _patch_weaviate_count(monkeypatch, count=2)

        minio_stub = MagicMock()
        minio_stub.exists.return_value = True

        client = MagicMock()
        validator = E2EValidator(client=client, minio=minio_stub)
        report = validator.validate_all(sample_size=3, manifest=manifest)

        assert report.total_checked == 3
        assert len(report.findings) == 3

    def test_validate_all_empty_manifest(self, monkeypatch) -> None:
        _patch_weaviate_count(monkeypatch, count=0)

        client = MagicMock()
        validator = E2EValidator(client=client)
        report = validator.validate_all(manifest={})

        assert report.total_checked == 0
        assert report.consistent is True
        assert report.findings == []

    def test_validate_all_minio_disabled_is_none(self, monkeypatch) -> None:
        """When minio=None, minio_ok is None (not False) for all findings."""
        manifest = {
            "local:doc_x.md": {
                "source_key": "local:doc_x.md",
                "trace_id": "trace-x",
                "schema_version": "1.0.0",
                "deleted": False,
            }
        }

        _patch_weaviate_count(monkeypatch, count=5)

        client = MagicMock()
        # No minio — minio_ok should be None.
        validator = E2EValidator(client=client, minio=None)
        report = validator.validate_all(manifest=manifest)

        assert report.findings[0].minio_ok is None
