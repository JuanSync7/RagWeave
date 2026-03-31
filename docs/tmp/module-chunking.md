### `src/ingest/embedding/nodes/chunking.py` — Dual-Path Chunking Node

**Purpose:**

This LangGraph node splits a document into chunks — the fundamental unit for embedding and retrieval. It implements two paths that are selected automatically based on whether a `DoclingDocument` is present in pipeline state:

- **Docling-native path** (`_chunk_with_docling`): uses Docling's `HybridChunker` on the native `DoclingDocument` object. Produces structure-aware, token-aligned chunks that respect document item boundaries (paragraphs, tables, lists, code blocks), carry heading breadcrumb metadata, and repeat table header rows in every table chunk.
- **Markdown fallback path** (`_chunk_with_markdown`): uses `MarkdownHeaderTextSplitter` and `RecursiveCharacterTextSplitter` on the clean markdown text. Identical to the pre-redesign implementation.

Both paths produce `ProcessedChunk` objects with a unified metadata schema. A per-chunk NFC unicode normalization and control character removal step (`_normalize_chunk_text`) is applied on both paths. (FR-2101–FR-2115, FR-2301–FR-2305, FR-2015)

**How it works:**

`chunking_node(state)` is the LangGraph node entry point:

1. Build `base_metadata` from `state["raw_text"]` and source identity fields (`source`, `source_uri`, `source_key`, `source_id`, `connector`, `source_version`).
2. Check `docling_doc = state.get("docling_document")`.
3. If `docling_doc is not None` → attempt `_chunk_with_docling(state, config, base_metadata)`. On any exception: log the error, append `"hybrid_chunker:error"` to the processing log, then call `_chunk_with_markdown` as fallback (appending `"chunking:fallback_to_markdown"`).
4. If `docling_doc is None` → call `_chunk_with_markdown(state, config, base_metadata)`, appending `"chunking:markdown_fallback"`.
5. On any outer exception: return an error state update with the exception message.

**`_chunk_with_docling(state, config, base_metadata)`:**
1. Lazily import `HybridChunker` from `docling_core.transforms.chunker`.
2. Instantiate `HybridChunker(max_tokens=config.hybrid_chunker_max_tokens, merge_peers=True)`.
3. Call `chunker.chunk(dl_doc=state["docling_document"])` and convert to a list.
4. For each chunk: call `_extract_docling_section_metadata(chunk)` to get `section_path`, `heading`, `heading_level`. Apply `_normalize_chunk_text(chunk.text)`. Build a `ProcessedChunk` with merged `base_metadata`, section metadata, `chunk_index`, and `total_chunks`.

**`_extract_docling_section_metadata(chunk)`:**
- Reads `chunk.meta.headings` (list of heading strings, outermost first).
- Returns `{"section_path": " > ".join(headings), "heading": headings[-1] or "", "heading_level": len(headings)}`.

**`_chunk_with_markdown(state, config, base_metadata)`:**
1. Get the text from `state.get("refactored_text") or state.get("cleaned_text", "")`.
2. Call `normalize_headings_to_markdown()` on the text.
3. If `config.semantic_chunking` is `True`: call `chunk_markdown(..., embedder=state["runtime"].embedder)`. Otherwise call `chunk_markdown(..., embedder=None)`.
4. For each raw chunk: apply `_normalize_chunk_text`, build `ProcessedChunk` with `_build_section_metadata(chunk.get("header_metadata", {}))`.

**`_normalize_chunk_text(text)`:**
1. Apply `unicodedata.normalize("NFC", text)` — converts all characters to NFC canonical form.
2. Apply `_CONTROL_CHAR_RE.sub("", normalized)` — removes C0/C1 control characters except `\n` (0x0a), `\t` (0x09), `\r` (0x0d). The regex covers `\x00–\x08`, `\x0b`, `\x0c`, `\x0e–\x1f`, `\x7f`.

```python
# Path selection logic (from actual source):
docling_doc = state.get("docling_document")
if docling_doc is not None:
    try:
        chunks = _chunk_with_docling(state, config, base_metadata)
        processing_log = append_processing_log(state, "hybrid_chunker:ok")
    except Exception as exc:
        logger.error("HybridChunker failed for source=%s: %s — falling back to markdown", ...)
        chunks = _chunk_with_markdown(state_with_error_log, config, base_metadata)
        processing_log = append_processing_log(state_with_error_log, "chunking:fallback_to_markdown")
else:
    chunks = _chunk_with_markdown(state, config, base_metadata)
    processing_log = append_processing_log(state, "chunking:markdown_fallback")
```

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| HybridChunker failure auto-falls-back to markdown (non-fatal) | Fatal error on HybridChunker failure; retry with smaller max_tokens | A single document's chunking failure should not halt a batch run. Markdown fallback produces lower-quality chunks but recovers the document. The error is logged clearly so operators can investigate. |
| `HybridChunker(merge_peers=True)` | `merge_peers=False` | `merge_peers=True` merges undersized adjacent items into coherent chunks, satisfying FR-2113. Without it, short paragraphs and list items produce very small chunks that waste embedding capacity. |
| `docling-core` imported lazily inside `_chunk_with_docling` | Top-level import | Keeps the module importable without Docling installed. Systems that never use the Docling path are not penalized with an import crash. |
| NFC normalization applied to both paths uniformly | Apply only to HybridChunker output | Uniform application ensures embedding consistency across paths. A chunk from either path with a non-NFC sequence should produce the same embedding as a semantically identical NFC-normalized chunk. |
| State error log grafting for fallback logging | Separate logging state; discard intermediate log | The processing log is a list in state. When HybridChunker fails, the fallback code appends to the error log rather than a fresh state. Grafting `state_with_error_log` ensures the fallback log entries appear sequentially after the error entry. |

**Configuration:**

| Parameter | Type | Default | Valid Range / Options | Effect |
|-----------|------|---------|----------------------|--------|
| `config.hybrid_chunker_max_tokens` | `int` | `512` | Positive integer | Passed directly to `HybridChunker(max_tokens=...)`. Controls the maximum token count per chunk on the Docling path. |
| `config.semantic_chunking` | `bool` | `True` (from env) | `True` or `False` | On the markdown path: `True` passes the embedder to `chunk_markdown` for semantic boundary detection; `False` passes `None` for pure character-based splitting. Has no effect on the Docling path. |
| `config.chunk_size` | `int` | `512` (from env) | Positive integer | On the markdown path: character-based chunk size for `RecursiveCharacterTextSplitter`. Has no effect on the Docling path. |
| `config.chunk_overlap` | `int` | `50` (from env) | Non-negative integer | On the markdown path: character overlap between consecutive chunks. Has no effect on the Docling path. |

**Error behavior:**

`_chunk_with_docling` raises any exception from `HybridChunker` — these are caught in `chunking_node` and trigger the markdown fallback. The fallback itself is considered non-fatal at the node level.

`_chunk_with_markdown` exceptions propagate out of `chunking_node`'s inner `try` block and are caught by the outer `except Exception` handler, which returns a state update with `errors: ["chunking:<exc>"]`. The markdown path failure is fatal for this document — there is no further fallback.

`_normalize_chunk_text` never raises. `unicodedata.normalize` and regex substitution are always valid for string inputs.
