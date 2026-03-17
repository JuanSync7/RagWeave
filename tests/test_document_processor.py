from src.ingest.support.document import clean_text, process_document


def test_clean_text_removes_boilerplate():
    raw = "Title: Sample\nPage 1\n\nHello world."
    cleaned = clean_text(raw)
    assert "Title:" not in cleaned
    assert "Page 1" not in cleaned
    assert "Hello world." in cleaned


def test_process_document_adds_chunk_metadata():
    chunks = process_document("Simple content for testing.", source="a.txt")
    assert chunks
    assert chunks[0].metadata["source"] == "a.txt"
    assert "chunk_index" in chunks[0].metadata
