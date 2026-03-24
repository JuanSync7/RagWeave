<!-- @summary
Drop zone for source documents to be ingested. Supported formats: .txt, .md, .html, .pdf, .docx, .pptx. Run ingest.py to process contents.
@end-summary -->

# documents

## Overview

This directory is the default source location for documents to be ingested into the RAG system.

Place any supported documents here, then run ingestion to process them into vector embeddings and (optionally) knowledge graph triples.

```bash
python ingest.py --dir ./documents
```

## Supported Formats

| Extension | Notes |
| --- | --- |
| `.txt`, `.md`, `.markdown`, `.rst` | Plain text and markup (direct text extraction) |
| `.html`, `.htm` | Web documents (text extraction) |
| `.pdf` | PDF documents (Docling-parsed with layout awareness) |
| `.docx` | Word documents (Docling-parsed) |
| `.pptx` | PowerPoint presentations (Docling-parsed) |

## Notes

- Files placed here are **source documents only** — runtime artifacts (cleaned text, chunks) are written to `processed/` during ingestion.
- Set `RAG_INGESTION_DOCLING_ENABLED=true` for richer PDF/DOCX/PPTX parsing.
- The ingestion pipeline tracks file identity by `source_key` (path-based), so renaming or moving a file is treated as a new source.
- Sample files (`sample_doc_1.txt`, `sample_doc_2.txt`, `sample_doc_3.txt`) are included as ingestion test fixtures.
