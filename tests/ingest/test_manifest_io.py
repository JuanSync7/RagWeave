from src.ingest.common.utils import load_manifest, save_manifest


def test_load_manifest_moves_corrupt_file(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{bad json", encoding="utf-8")

    loaded = load_manifest(manifest)

    assert loaded == {}
    assert not manifest.exists()
    moved = list(tmp_path.glob("manifest.json.corrupt.*"))
    assert moved


def test_save_manifest_is_atomic_and_readable(tmp_path):
    manifest = tmp_path / "manifest.json"
    payload = {"source_key": {"content_hash": "abc"}}

    save_manifest(payload, manifest)

    assert load_manifest(manifest) == payload
