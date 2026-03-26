from src.ingest.common.utils import load_manifest, save_manifest
from src.vector_db import build_chunk_id


def test_manifest_roundtrip(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    payload = {"a.txt": {"content_hash": "abc", "chunk_count": 2}}
    save_manifest(payload, manifest_path)
    loaded = load_manifest(manifest_path)
    assert loaded == payload


def test_chunk_id_changes_with_content():
    old = build_chunk_id("doc.txt", 0, "old")
    new = build_chunk_id("doc.txt", 0, "new")
    assert old != new


def test_chunk_id_changes_with_source_key():
    left = build_chunk_id("local_fs:1:100", 0, "same content")
    right = build_chunk_id("local_fs:1:101", 0, "same content")
    assert left != right
