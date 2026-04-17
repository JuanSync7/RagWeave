import time

from src.ingest.common.utils import load_manifest, save_manifest
from src.vector_db import build_chunk_id
from src.ingest.impl import _local_source_identity


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


# ---------------------------------------------------------------------------
# Source identity stability — regression tests
# ---------------------------------------------------------------------------

def test_source_key_stable_on_repeated_calls(tmp_path):
    """Same file path and content must produce the same source_key on repeated calls."""
    doc = tmp_path / "document.txt"
    doc.write_text("hello world", encoding="utf-8")

    identity1 = _local_source_identity(doc, tmp_path)
    identity2 = _local_source_identity(doc, tmp_path)

    assert identity1["source_key"] == identity2["source_key"]


def test_source_key_uses_dev_inode(tmp_path):
    """source_key must encode device:inode so renames do not change it."""
    doc = tmp_path / "original.txt"
    doc.write_text("stable content", encoding="utf-8")

    identity_before = _local_source_identity(doc, tmp_path)

    renamed = tmp_path / "renamed.txt"
    doc.rename(renamed)

    identity_after = _local_source_identity(renamed, tmp_path)

    assert identity_before["source_key"] == identity_after["source_key"]
    assert identity_before["source_id"] == identity_after["source_id"]


def test_source_identity_contains_required_fields(tmp_path):
    """source identity dict must contain all required fields."""
    doc = tmp_path / "test.txt"
    doc.write_text("content", encoding="utf-8")

    identity = _local_source_identity(doc, tmp_path)

    required_fields = (
        "source_path", "source_name", "source_uri",
        "source_id", "source_key", "connector", "source_version",
    )
    for field in required_fields:
        assert field in identity, f"Missing field: {field}"


def test_source_key_changes_for_different_files(tmp_path):
    """Two different files (different inodes) must have different source_keys."""
    doc_a = tmp_path / "a.txt"
    doc_b = tmp_path / "b.txt"
    doc_a.write_text("file a", encoding="utf-8")
    doc_b.write_text("file b", encoding="utf-8")

    identity_a = _local_source_identity(doc_a, tmp_path)
    identity_b = _local_source_identity(doc_b, tmp_path)

    assert identity_a["source_key"] != identity_b["source_key"]


def test_source_version_changes_after_content_update(tmp_path):
    """source_version (mtime_ns) must change after the file is modified."""
    doc = tmp_path / "mutable.txt"
    doc.write_text("original content", encoding="utf-8")

    identity_before = _local_source_identity(doc, tmp_path)

    # Ensure a distinct mtime_ns for the second write.
    # tmpfs on Linux has nanosecond resolution but the kernel may batch flushes;
    # 20 ms gives comfortable headroom without slowing the suite.
    time.sleep(0.02)
    doc.write_text("updated content", encoding="utf-8")

    identity_after = _local_source_identity(doc, tmp_path)

    assert identity_after["source_version"] != identity_before["source_version"]


# ---------------------------------------------------------------------------
# Chunk ID stability for incremental re-processing
# ---------------------------------------------------------------------------

def test_chunk_id_stable_for_unchanged_content():
    """Same source_key, same index, same text must produce the same chunk_id."""
    source_key = "local_fs:5:42"
    text = "The timing budget requires 2ns slack."
    id1 = build_chunk_id(source_key, 0, text)
    id2 = build_chunk_id(source_key, 0, text)
    assert id1 == id2


def test_chunk_id_changes_for_updated_chunk():
    """When chunk text changes (partial file update), chunk_id must change."""
    source_key = "local_fs:5:42"
    old_id = build_chunk_id(source_key, 1, "Old paragraph content.")
    new_id = build_chunk_id(source_key, 1, "New paragraph content after edit.")
    assert old_id != new_id


def test_chunk_id_unchanged_chunk_skipped_on_reimport():
    """Unchanged chunks must produce the same ID — enabling skip-if-present semantics."""
    source_key = "local_fs:7:99"
    unchanged_text = "This paragraph did not change."
    changed_text_old = "This paragraph changed."
    changed_text_new = "This paragraph has been updated."

    # Simulate first ingest
    id_unchanged_v1 = build_chunk_id(source_key, 0, unchanged_text)
    id_changed_v1 = build_chunk_id(source_key, 1, changed_text_old)

    # Simulate re-ingest after partial file update
    id_unchanged_v2 = build_chunk_id(source_key, 0, unchanged_text)
    id_changed_v2 = build_chunk_id(source_key, 1, changed_text_new)

    # Unchanged chunk: ID must be identical (can be skipped)
    assert id_unchanged_v1 == id_unchanged_v2
    # Changed chunk: ID must differ (must be re-processed)
    assert id_changed_v1 != id_changed_v2
