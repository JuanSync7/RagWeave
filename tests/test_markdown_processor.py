from src.ingest.markdown_processor import normalize_headings_to_markdown, process_document_markdown


def test_normalize_headings_to_markdown():
    text = "== Heading ==\n\n1. INTRODUCTION\n\nBody."
    out = normalize_headings_to_markdown(text)
    assert "## Heading" in out
    assert "## Introduction" in out


def test_process_document_markdown_produces_chunks():
    chunks = process_document_markdown("# Title\n\nSome text", source="doc.txt")
    assert chunks
    assert chunks[0].metadata["source"] == "doc.txt"
