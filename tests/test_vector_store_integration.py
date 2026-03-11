from src.core.vector_store import build_chunk_id


def test_chunk_id_is_deterministic():
    a = build_chunk_id("doc.txt", 0, "hello")
    b = build_chunk_id("doc.txt", 0, "hello")
    c = build_chunk_id("doc.txt", 1, "hello")
    assert a == b
    assert a != c
