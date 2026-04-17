from src.ingest.common.utils import load_manifest, save_manifest


def test_save_manifest_is_atomic_and_readable(tmp_path):
    manifest = tmp_path / "manifest.json"
    payload = {"source_key": {"content_hash": "abc"}}

    save_manifest(payload, manifest)

    assert load_manifest(manifest) == payload


# ---------------------------------------------------------------------------
# Extended manifest I/O regression tests
# ---------------------------------------------------------------------------

def test_save_manifest_no_partial_state_visible(tmp_path):
    """save_manifest must write atomically: tmp file renamed, never partially visible."""
    manifest = tmp_path / "manifest.json"
    payload = {"key1": {"content_hash": "hash1"}, "key2": {"content_hash": "hash2"}}

    save_manifest(payload, manifest)

    tmp_file = tmp_path / "manifest.json.tmp"
    assert not tmp_file.exists()
    assert load_manifest(manifest) == payload


def test_save_manifest_second_write_wins(tmp_path):
    """Two sequential saves to the same path — last write wins without corruption."""
    manifest = tmp_path / "manifest.json"
    first = {"key_a": {"content_hash": "first"}}
    second = {"key_b": {"content_hash": "second"}}

    save_manifest(first, manifest)
    save_manifest(second, manifest)

    loaded = load_manifest(manifest)
    assert loaded == second


def test_load_manifest_missing_file_returns_empty(tmp_path):
    """load_manifest on a non-existent path must return {} without raising."""
    manifest = tmp_path / "nonexistent_manifest.json"
    assert load_manifest(manifest) == {}


def test_load_manifest_corrupt_renamed_with_timestamp(tmp_path):
    """Corrupt manifest must be renamed to .corrupt.<timestamp> (not deleted)."""
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(b"<<<not json>>>")

    load_manifest(manifest)

    # Original path must be gone
    assert not manifest.exists()
    # A .corrupt.* backup must exist
    backups = list(tmp_path.glob("manifest.json.corrupt.*"))
    assert len(backups) == 1
    # The backup must contain the original corrupt content
    assert backups[0].read_bytes() == b"<<<not json>>>"


def test_save_manifest_creates_parent_dirs(tmp_path):
    """save_manifest must create parent directories if they do not exist."""
    nested = tmp_path / "a" / "b" / "manifest.json"
    payload = {"x": {"content_hash": "y"}}

    save_manifest(payload, nested)

    assert load_manifest(nested) == payload


def test_manifest_roundtrip_preserves_all_fields(tmp_path):
    """Round-trip save/load must preserve all fields without data loss."""
    manifest = tmp_path / "manifest.json"
    payload = {
        "local_fs:12:34": {
            "source_key": "local_fs:12:34",
            "content_hash": "abc123",
            "chunk_count": 5,
            "source_version": "1234567890",
        }
    }

    save_manifest(payload, manifest)
    loaded = load_manifest(manifest)

    assert loaded == payload
