import json

from ingest import _load_manifest, _save_manifest
from src.core.vector_store import build_chunk_id


def test_manifest_roundtrip(tmp_path, monkeypatch):
    manifest_path = tmp_path / "manifest.json"
    monkeypatch.setattr("ingest.INGESTION_MANIFEST_PATH", manifest_path)
    payload = {"a.txt": {"content_hash": "abc", "chunk_count": 2}}
    _save_manifest(payload)
    loaded = _load_manifest()
    assert loaded == payload


def test_chunk_id_changes_with_content():
    old = build_chunk_id("doc.txt", 0, "old")
    new = build_chunk_id("doc.txt", 0, "new")
    assert old != new
