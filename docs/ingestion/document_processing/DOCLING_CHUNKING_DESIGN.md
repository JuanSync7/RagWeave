> **Document type:** Technical design document (Layer 4)
> **Companion spec:** `DOCLING_CHUNKING_SPEC.md`
> **Upstream:** DOCLING_CHUNKING_SPEC.md
> **Downstream:** DOCLING_CHUNKING_IMPLEMENTATION.md
> **Last updated:** 2026-03-27

# Docling-Native Chunking Pipeline — Design Document

| Field | Value |
|-------|-------|
| **Document** | Docling-Native Chunking Pipeline Design Document |
| **Version** | 1.0.0 |
| **Status** | Draft |
| **Spec Reference** | `DOCLING_CHUNKING_SPEC.md` v1.0.0 (FR-2001–FR-2603, NFR-2901–NFR-2913) |
| **Companion Documents** | `DOCLING_CHUNKING_SPEC.md`, `DOCUMENT_PROCESSING_DESIGN.md`, `DOCUMENT_PROCESSING_ENGINEERING_GUIDE.md` |
| **Created** | 2026-03-27 |
| **Last Updated** | 2026-03-27 |

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-03-27 | Initial design from spec; task decomposition, code contracts, dependency DAG, error matrix, migration notes. |

> **Document Intent.** This design document translates the requirements in `DOCLING_CHUNKING_SPEC.md`
> into a concrete, agent-executable implementation plan. It defines every code contract that must
> be implemented, describes file-level changes with enough precision that each task can be
> independently coded and tested, and specifies the exact signatures, field types, and default
> values for all new or modified public interfaces.
>
> Implementation agents should treat this document as the authoritative source of truth for
> signatures and contracts. The spec remains the authoritative source for acceptance criteria
> and requirement rationale.

---

# Part A — Task-Oriented Implementation Plan

## Overview

The redesign spans two pipeline phases and touches seven source files. The work is organized
into four groups:

| Group | Theme | Tasks |
|-------|-------|-------|
| 1 — Foundation | Config surface and state contracts | 1.1, 1.2 |
| 2 — Phase 1 (Document Processing) | DoclingDocument preservation through Phase 1 | 2.1, 2.2, 2.3 |
| 3 — Phase 2 (Embedding) | HybridChunker and VLM enrichment | 3.1, 3.2 |
| 4 — Cross-cutting | Validation, settings, observability | 4.1, 4.2, 4.3 |

Tasks within a group often depend on earlier tasks in the same group. Tasks across groups are
mostly parallel once their foundation tasks are complete. See Part C for the full dependency DAG.

---

## Group 1 — Foundation

### Task 1.1 — IngestionConfig: new fields

**Spec requirements:** FR-2401, FR-2403, FR-2405, FR-2407, NFR-2903

**Description:** Add three new fields to `IngestionConfig` in `src/ingest/common/types.py`.
These fields are the primary configuration knobs for the redesigned pipeline. All three must
have defaults that preserve pre-redesign behavior (NFR-2903).

**File changed:** `src/ingest/common/types.py`

**Subtasks:**

1. Add `vlm_mode: str` field with default `"disabled"`. Value must be one of `"disabled"`,
   `"builtin"`, or `"external"`. Read from `RAG_INGESTION_VLM_MODE` env var.
2. Add `hybrid_chunker_max_tokens: int` field with default `512` (bge-m3 maximum input token
   length). Read from `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS` env var.
3. Add `persist_docling_document: bool` field with default `True`. Read from
   `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT` env var.

**Code contract — IngestionConfig additions:**

```python
# In src/ingest/common/types.py, inside IngestionConfig dataclass:

vlm_mode: str = RAG_INGESTION_VLM_MODE                         # "disabled" | "builtin" | "external"
hybrid_chunker_max_tokens: int = RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS  # default 512
persist_docling_document: bool = RAG_INGESTION_PERSIST_DOCLING_DOCUMENT   # default True
```

**Test expectations:**

- `IngestionConfig()` → `vlm_mode == "disabled"`, `hybrid_chunker_max_tokens == 512`,
  `persist_docling_document == True`.
- With env `RAG_INGESTION_VLM_MODE=external` → `vlm_mode == "external"`.
- With env `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS=256` →
  `hybrid_chunker_max_tokens == 256`.
- With env `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT=false` →
  `persist_docling_document == False`.

**Dependencies:** None (foundation task).

---

### Task 1.2 — State contracts: new fields

**Spec requirements:** FR-2501, FR-2503, FR-2505

**Description:** Add `docling_document` to both pipeline state TypedDicts. Add
`docling_document_available` to the `structure` field contract of
`DocumentProcessingState`. No existing fields are modified or removed.

**Files changed:**
- `src/ingest/doc_processing/state.py`
- `src/ingest/embedding/state.py`

**Subtasks:**

1. In `DocumentProcessingState`, add `docling_document: Optional[Any]` field. Default is
   `None`. Use `Optional[Any]` (not `Optional[DoclingDocument]`) to avoid a hard compile-time
   dependency on `docling-core` in modules that never touch the document object.
2. In `EmbeddingPipelineState`, add `docling_document: Optional[Any]` field. Default is
   `None`.
3. Document in `DocumentProcessingState`'s docstring that the `structure` dict will contain
   a `docling_document_available: bool` key after `structure_detection_node` runs.

**Code contract — DocumentProcessingState addition:**

```python
# In src/ingest/doc_processing/state.py

class DocumentProcessingState(TypedDict, total=False):
    # ... existing fields unchanged ...

    docling_document: Optional[Any]
    """Native DoclingDocument object from Docling parse. None if Docling
    parsing was disabled or failed. Propagated to CleanDocumentStore and
    used by Phase 2 HybridChunker path.

    The structure dict will contain docling_document_available: bool
    set by structure_detection_node.
    """
```

**Code contract — EmbeddingPipelineState addition:**

```python
# In src/ingest/embedding/state.py

class EmbeddingPipelineState(TypedDict, total=False):
    # ... existing fields unchanged ...

    docling_document: Optional[Any]
    """Native DoclingDocument object loaded from CleanDocumentStore at
    Phase 2 initialization. None if no .docling.json was stored (fallback
    path). Read by chunking_node to select HybridChunker vs markdown path.
    """
```

**Test expectations:**

- Both TypedDicts accept `docling_document=None` without error.
- Both TypedDicts accept a mock `DoclingDocument` object without error.
- Existing nodes that receive a state dict without `docling_document` continue to work
  (TypedDict `total=False` means the key is optional).

**Dependencies:** None (foundation task, parallel with Task 1.1).

---

## Group 2 — Phase 1: DoclingDocument Preservation

### Task 2.1 — DoclingParseResult: add `docling_document` field; configure builtin VLM at parse time

**Spec requirements:** FR-2001, FR-2211

**Description:** Add a `docling_document` field to `DoclingParseResult` in
`src/ingest/support/docling.py`. Update `parse_with_docling` to accept `vlm_mode` and
configure `DocumentConverter` with `do_picture_description=True` when `vlm_mode="builtin"`.
When builtin VLM is enabled, Docling processes figure images during `DocumentConverter.convert()`
and bakes the VLM-generated figure descriptions into the `DoclingDocument` before it is
returned — no post-chunking VLM step is needed. Retain the existing `text_markdown` export.

**File changed:** `src/ingest/support/docling.py`

**Subtasks:**

1. Add `docling_document: Any` field to `DoclingParseResult` (after the existing `parser_model`
   field). Type is `Any` to keep `docling-core` as an optional import.
2. Update `parse_with_docling` signature to accept `vlm_mode: str = "disabled"`. When
   `vlm_mode == "builtin"`, configure `PdfPipelineOptions` (or `ConvertPipelineOptions`) with
   `do_picture_description=True` and `picture_description_options=PictureDescriptionVlmEngineOptions.from_preset("smolvlm")`
   before constructing `DocumentConverter`. This causes Docling to run SmolVLM on each figure
   image during `convert()`, embedding descriptions directly into the `DoclingDocument`.
   When `vlm_mode != "builtin"`, keep `do_picture_description=False` (existing behavior).
3. In `parse_with_docling`, assign `result.document` (the native `DoclingDocument`) to the new
   field before returning. The `document` object is already available in the existing
   implementation (see line 197: `document = getattr(result, "document", None)`).
4. Update `warmup_docling_models` signature to accept a `with_smolvlm: bool = False` parameter
   and pass it to `download_models(with_smolvlm=with_smolvlm, ...)`. This enables selective
   SmolVLM download for `vlm_mode=builtin` (FR-2211). SmolVLM model artifacts must be present
   before `parse_with_docling` is called with `vlm_mode="builtin"`.

**Code contract — DoclingParseResult after change:**

```python
@dataclass
class DoclingParseResult:
    """Docling parsing output normalized for ingestion nodes.

    Attributes:
        text_markdown: Parsed markdown text.
        has_figures: Whether Docling detected any figures/pictures.
        figures: Lightweight figure identifiers for telemetry/UI.
        headings: Extracted heading text in document order.
        parser_model: Parser model identifier used for telemetry/debugging.
        docling_document: Native DoclingDocument object for HybridChunker.
            When vlm_mode="builtin", figure descriptions are already embedded
            in this document by Docling's picture description pipeline.
            None only when produced by error recovery paths.
    """

    text_markdown: str
    has_figures: bool
    figures: list[str]
    headings: list[str]
    parser_model: str
    docling_document: Any  # docling_core.types.doc.DoclingDocument
```

**Code contract — parse_with_docling updated signature:**

```python
def parse_with_docling(
    file_path: str | Path,
    *,
    config: IngestionConfig,
    vlm_mode: str = "disabled",
) -> DoclingParseResult:
    """Parse a document with Docling and return a normalized result.

    When vlm_mode="builtin", configures DocumentConverter to run SmolVLM
    on figure images during conversion. Figure descriptions are baked into
    the returned DoclingDocument — no post-chunking VLM step is required
    for the builtin mode.

    When vlm_mode="external" or vlm_mode="disabled", do_picture_description
    is False (existing behavior). External VLM enrichment happens post-chunking
    via vlm_enrichment_node.

    Args:
        file_path: Path to the source document.
        config: Ingestion configuration.
        vlm_mode: VLM mode. "builtin" activates Docling's SmolVLM picture
            description at parse time. "external" and "disabled" leave
            do_picture_description=False.

    Raises:
        RuntimeError: If conversion fails and docling_strict=True.
    """
    # When vlm_mode == "builtin":
    #   from docling.datamodel.pipeline_options import (
    #       PdfPipelineOptions, PictureDescriptionVlmEngineOptions
    #   )
    #   pipeline_options = PdfPipelineOptions()
    #   pipeline_options.do_picture_description = True
    #   pipeline_options.picture_description_options = (
    #       PictureDescriptionVlmEngineOptions.from_preset("smolvlm")
    #   )
    #   converter = DocumentConverter(
    #       format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
    #   )
    # Otherwise: converter = DocumentConverter() (existing behavior)
```

**Code contract — warmup_docling_models updated signature:**

```python
def warmup_docling_models(
    *,
    artifacts_path: str = "",
    with_smolvlm: bool = False,
) -> Path:
    """Download and validate core Docling models used by ingestion.

    Args:
        artifacts_path: Optional directory to store downloaded artifacts.
        with_smolvlm: If True, also download SmolVLM model artifacts.
            Must be True when vlm_mode is "builtin"; SmolVLM artifacts
            must be available before parse_with_docling is called with
            vlm_mode="builtin".
    """
    # ... pass with_smolvlm to download_models(with_smolvlm=with_smolvlm) ...
```

**Test expectations:**

- After `parse_with_docling(path, config, vlm_mode="disabled")`, the returned
  `DoclingParseResult.docling_document` is non-`None` and is the same object as
  `converter.convert(path).document`. `DocumentConverter` is constructed without
  `do_picture_description`.
- After `parse_with_docling(path, config, vlm_mode="builtin")`, `DocumentConverter` is
  constructed with `do_picture_description=True` and `from_preset("smolvlm")`.
- `DoclingParseResult` is backward-compatible: callers that only accessed `text_markdown`,
  `has_figures`, `figures`, `headings`, `parser_model` are unaffected.
- `warmup_docling_models(with_smolvlm=False)` does not download SmolVLM artifacts.
- `warmup_docling_models(with_smolvlm=True)` passes `with_smolvlm=True` to `download_models`.
- When SmolVLM artifacts are not present and `vlm_mode="builtin"`, `parse_with_docling` logs
  a warning and falls back to parsing without picture descriptions (non-fatal).

**Dependencies:** Task 1.1 (needs `vlm_mode` config field to be stable before referencing it
in callers).

---

### Task 2.2 — structure_detection_node: propagate DoclingDocument

**Spec requirements:** FR-2003, FR-2005 (partial), FR-2011, FR-2013, FR-2505

**Description:** Modify `structure_detection_node` in
`src/ingest/doc_processing/nodes/structure_detection.py` to:

1. Extract `docling_document` from the `DoclingParseResult` and include it in the returned
   state update.
2. Add `docling_document_available` to the `structure` dict.
3. Drive the routing signals that cause `text_cleaning_node` and `document_refactoring_node`
   to be skipped for Docling-parsed documents (by setting `docling_document_available=True`
   in the `structure` dict; the DAG routing logic reads this flag).

**File changed:** `src/ingest/doc_processing/nodes/structure_detection.py`

**Subtasks:**

1. After a successful `parse_with_docling` call, capture `parsed.docling_document` into a
   local variable `docling_doc`.
2. Return `docling_document: docling_doc` in the state update dict.
3. Add `"docling_document_available": True` to the `structure` dict when Docling parse
   succeeds; `False` in all other branches (fallback regex path, Docling disabled, Docling
   failed in non-strict mode).
4. When Docling fails in non-strict mode (the `except` branch), ensure
   `docling_document_available` is set to `False` in the returned `structure` dict.

**Code contract — updated return dict:**

```python
def structure_detection_node(state: DocumentProcessingState) -> dict[str, Any]:
    # ... existing logic ...

    # On successful Docling parse:
    return {
        "raw_text": parsed_text,
        "docling_document": docling_doc,        # NEW: Optional[Any]
        "structure": {
            "has_figures": bool(figures),
            "figures": figures[:_MAX_FIGURES],
            "heading_count": len(headings),
            "docling_enabled": bool(config.enable_docling_parser),
            "docling_model": str(config.docling_model),
            "docling_document_available": True,  # NEW
        },
        "processing_log": append_processing_log(state, "structure_detection:ok"),
    }

    # On fallback (regex) or Docling disabled:
    return {
        "raw_text": parsed_text,
        # docling_document key absent (defaults to None in TypedDict)
        "structure": {
            "has_figures": bool(figures),
            "figures": figures[:_MAX_FIGURES],
            "heading_count": len(headings),
            "docling_enabled": bool(config.enable_docling_parser),
            "docling_model": str(config.docling_model),
            "docling_document_available": False,  # NEW
        },
        "processing_log": append_processing_log(state, "structure_detection:ok"),
    }
```

**Test expectations:**

- Given Docling enabled and parse success: `state["docling_document"]` is not `None`;
  `state["structure"]["docling_document_available"]` is `True`.
- Given Docling disabled: `"docling_document"` is absent from the returned update (or
  `None`); `structure["docling_document_available"]` is `False`.
- Given Docling fails in non-strict mode: fallback to regex; `docling_document` is `None`;
  `structure["docling_document_available"]` is `False`.
- No changes to the existing `processing_log`, `errors`, `should_skip` behavior.

**Dependencies:** Task 1.2 (state TypedDict), Task 2.1 (DoclingParseResult.docling_document).

---

### Task 2.3 — CleanDocumentStore: write_docling / read_docling

**Spec requirements:** FR-2005, FR-2007, FR-2009, NFR-2911

**Description:** Extend `CleanDocumentStore` in `src/ingest/common/clean_store.py` with two
new methods, `write_docling` and `read_docling`, and update the existing `write` method to
accept an optional `docling_document` parameter that triggers atomic `.docling.json`
persistence when provided and `persist_docling_document=True`.

**File changed:** `src/ingest/common/clean_store.py`

**Subtasks:**

1. Add a `_docling_path` helper method returning `{store_dir}/{safe_key}.docling.json`.
2. Implement `write_docling(source_key, docling_document)`: serialize the
   `DoclingDocument` to JSON using `docling_document.model_dump_json()` (docling-core's Pydantic
   v2 JSON export). Write atomically via `.docling.json.tmp` → rename. Prepend a
   `_schema_version` key to the serialized JSON envelope for format migration support
   (NFR-2911).
3. Implement `read_docling(source_key) -> Optional[Any]`: deserialize from `.docling.json` if
   present. On `FileNotFoundError` or JSON deserialization failure, return `None` and log a
   warning (FR-2603 upstream behavior). Import `DoclingDocument` lazily inside the method
   to keep the module import cheap.
4. Add optional `docling_document` parameter to the existing `write` method signature.
   When `docling_document` is not `None`, call `write_docling` after the existing md + meta
   write. If `write_docling` fails, log the error but do not roll back the md/meta write
   (the markdown path remains usable; Phase 2 will fall back to markdown chunking).
5. Update `delete` to also remove the `.docling.json` file when present.

**Code contract — new and modified signatures:**

```python
class CleanDocumentStore:
    # --- existing methods unchanged (write, read, exists, clean_hash, list_keys) ---

    def _docling_path(self, source_key: str) -> Path:
        """Return the path for the serialized DoclingDocument JSON file."""
        return self._dir / f"{self._safe_key(source_key)}.docling.json"

    def write_docling(self, source_key: str, docling_document: Any) -> None:
        """Atomically serialize and persist a DoclingDocument.

        Writes to a .tmp file first, then renames into place.
        Wraps the serialized document in an envelope with _schema_version.

        Args:
            source_key: Stable source identity key.
            docling_document: Native DoclingDocument object (docling_core
                Pydantic model). Must support .model_dump_json() or
                .to_json() serialization.

        Raises:
            OSError: If the atomic write fails.
            ValueError: If the document cannot be serialized.
        """

    def read_docling(self, source_key: str) -> Any | None:
        """Deserialize and return a DoclingDocument for the given source key.

        Returns:
            The deserialized DoclingDocument, or None if:
            - The .docling.json file does not exist.
            - The file contains invalid JSON.
            - Deserialization fails (schema version mismatch, missing
              docling-core dependency).

        Logs a warning on any deserialization failure.
        """

    def write(
        self,
        source_key: str,
        text: str,
        meta: dict[str, Any],
        docling_document: Any | None = None,   # NEW optional parameter
    ) -> None:
        """Atomically write clean text, metadata, and optional DoclingDocument.

        The docling_document is only written when docling_document is not None.
        A failure to write the DoclingDocument is non-fatal: the markdown and
        metadata files are preserved, and the caller falls back to markdown
        chunking in Phase 2.
        """

    def delete(self, source_key: str) -> None:
        """Remove the clean document entry for this key (all three files)."""
        # Also removes .docling.json when present.
```

**Serialization envelope format (NFR-2911):**

The `.docling.json` file is a JSON object with the following top-level structure:

```json
{
  "_schema_version": "docling-native-v1",
  "document": { <DoclingDocument JSON produced by model_dump_json()> }
}
```

The `_schema_version` key is checked during `read_docling`. If the version does not match the
expected value, a warning is logged and `None` is returned.

**Test expectations:**

- `write_docling` + `read_docling` round-trip returns an equivalent `DoclingDocument`.
- If `write_docling` is interrupted mid-write, no `.docling.json` file exists (the `.tmp`
  is cleaned up by the OS or by the exception handler).
- `read_docling` on a missing key returns `None` without raising.
- `read_docling` on a corrupt JSON file returns `None` and logs a warning.
- `delete` removes all three files (`.md`, `.meta.json`, `.docling.json`).
- `write(docling_document=None)` behaves identically to the pre-redesign `write` (no third
  file is written).

**Dependencies:** Task 1.1 (references `persist_docling_document` config flag indirectly via
the orchestrator layer, not directly in the store). Task 2.2 supplies the `docling_document`
object to pass into `write`.

---

## Group 3 — Phase 2: HybridChunker and VLM Enrichment

### Task 3.1 — chunking_node: dual-path logic

**Spec requirements:** FR-2101, FR-2103, FR-2105, FR-2107, FR-2109, FR-2111, FR-2113, FR-2115,
FR-2301, FR-2303, FR-2305, FR-2307, FR-2601

**Description:** Refactor `chunking_node` in
`src/ingest/embedding/nodes/chunking.py` to select between the Docling-native
(`HybridChunker`) path and the existing markdown fallback path based solely on the presence of
a non-`None` `docling_document` in state (FR-2307). Extract the markdown fallback logic into
a private helper `_chunk_with_markdown` to keep the node function clean.

**File changed:** `src/ingest/embedding/nodes/chunking.py`

**Subtasks:**

1. Add a private helper `_chunk_with_docling(state, config, base_metadata) -> list[ProcessedChunk]`
   that instantiates `HybridChunker`, runs it on `state["docling_document"]`, converts each
   `ChunkWithMetadata` to a `ProcessedChunk`, and attaches `section_path`, `heading`,
   `heading_level`, `chunk_index`, `total_chunks`, and all `base_metadata` keys to each
   chunk's metadata dict.
2. Extract the existing markdown path into `_chunk_with_markdown(state, config, base_metadata) -> list[ProcessedChunk]`.
   This function must be behaviorally identical to the pre-redesign `chunking_node` body
   (FR-2305).
3. In the main `chunking_node` body: check `state.get("docling_document")`. If not `None`,
   call `_chunk_with_docling` inside a `try/except`. On exception, log the error, append
   `hybrid_chunker:error` and `chunking:fallback_to_markdown` to the processing log, and
   call `_chunk_with_markdown` as fallback (FR-2601). If `docling_document` is `None`, call
   `_chunk_with_markdown` directly.
4. Apply unicode normalization (NFC + control character removal) to every chunk's text,
   regardless of path (FR-2015). Implement as a private helper `_normalize_chunk_text(text: str) -> str`.
5. Log `hybrid_chunker:ok` on Docling-native success; `chunking:markdown_fallback` on
   fallback or when Docling document is absent (NFR-2909).

**Code contract — HybridChunker instantiation:**

```python
from docling.chunking import HybridChunker

def _chunk_with_docling(
    state: EmbeddingPipelineState,
    config: IngestionConfig,
    base_metadata: dict[str, Any],
) -> list[ProcessedChunk]:
    """Chunk a DoclingDocument using Docling's HybridChunker.

    Args:
        state: Embedding pipeline state. state["docling_document"] must be
            a valid DoclingDocument instance.
        config: Ingestion configuration. config.hybrid_chunker_max_tokens
            controls the token size limit.
        base_metadata: Pre-built source metadata dict (source, source_uri,
            source_key, source_id, connector, source_version).

    Returns:
        List of ProcessedChunk objects with full metadata.

    Raises:
        Any exception from HybridChunker (caller catches and falls back).
    """
    chunker = HybridChunker(max_tokens=config.hybrid_chunker_max_tokens)
    chunk_iter = chunker.chunk(dl_doc=state["docling_document"])
    raw_chunks = list(chunk_iter)
    total_chunks = len(raw_chunks)
    chunks: list[ProcessedChunk] = []
    for idx, chunk in enumerate(raw_chunks):
        section_meta = _extract_docling_section_metadata(chunk)
        text = _normalize_chunk_text(chunk.text)
        chunks.append(ProcessedChunk(
            text=text,
            metadata={
                **base_metadata,
                **section_meta,
                "chunk_index": idx,
                "total_chunks": total_chunks,
            },
        ))
    return chunks
```

**Code contract — section metadata extractor:**

```python
def _extract_docling_section_metadata(chunk: Any) -> dict[str, Any]:
    """Extract section_path, heading, heading_level from a HybridChunker chunk.

    HybridChunker chunks expose their heading hierarchy via
    chunk.meta.headings (list of heading strings, outermost first).

    Args:
        chunk: A ChunkWithMetadata object from HybridChunker.

    Returns:
        Dict with keys: section_path (str), heading (str), heading_level (int).
    """
    headings: list[str] = []
    meta = getattr(chunk, "meta", None)
    if meta is not None:
        headings = list(getattr(meta, "headings", None) or [])
    heading = headings[-1] if headings else ""
    return {
        "section_path": " > ".join(headings),
        "heading": heading,
        "heading_level": len(headings),
    }
```

**Code contract — unicode normalization helper:**

```python
import unicodedata
import re as _re

_CONTROL_CHAR_RE = _re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

def _normalize_chunk_text(text: str) -> str:
    """Apply NFC unicode normalization and remove control characters.

    Args:
        text: Raw chunk text.

    Returns:
        NFC-normalized text with C0/C1 control characters removed.
        Newlines (0x0a) and carriage returns (0x0d) are preserved.
    """
    normalized = unicodedata.normalize("NFC", text)
    return _CONTROL_CHAR_RE.sub("", normalized)
```

**Code contract — main node signature (unchanged externally):**

```python
def chunking_node(state: EmbeddingPipelineState) -> dict[str, Any]:
    """Split document into chunks using HybridChunker (Docling path) or
    MarkdownHeaderTextSplitter (fallback path).

    Path selection is automatic: if state["docling_document"] is not None,
    HybridChunker is used. Otherwise the existing markdown path is used.
    HybridChunker failures fall back to the markdown path automatically.

    Returns:
        Partial state update containing:
        - chunks: list[ProcessedChunk]
        - processing_log: updated log
    """
```

**Test expectations:**

- Given `docling_document=<DoclingDocument>` in state: node calls `HybridChunker`; chunks
  have `section_path` populated; processing log contains `hybrid_chunker:ok`.
- Given `docling_document=None` in state: node calls `chunk_markdown`; processing log
  contains `chunking:markdown_fallback`.
- Given `docling_document=<DoclingDocument>` but `HybridChunker` raises `ValueError`: node
  falls back to markdown; log contains both `hybrid_chunker:error` and
  `chunking:fallback_to_markdown`; returned chunks are non-empty valid `ProcessedChunk`
  objects.
- All chunks (both paths) pass through `_normalize_chunk_text`.
- All chunks contain all required metadata keys: `source`, `source_uri`, `source_key`,
  `source_id`, `connector`, `source_version`, `section_path`, `heading`, `heading_level`,
  `chunk_index`, `total_chunks`.
- Existing markdown fallback behavior is byte-identical to pre-redesign output except where
  `_normalize_chunk_text` alters non-NFC sequences.

**Dependencies:** Task 1.1, Task 1.2, Task 2.3 (CleanDocumentStore read_docling populates
`docling_document` in EmbeddingPipelineState before this node runs).

---

### Task 3.2 — vlm_enrichment_node: new post-chunking VLM node (external mode only)

**Spec requirements:** FR-2201, FR-2203, FR-2205, FR-2207, FR-2209, FR-2211

**Description:** Implement a new `vlm_enrichment_node` in a new file
`src/ingest/embedding/nodes/vlm_enrichment.py`. This node operates on the chunk list after
`chunking_node` and replaces image placeholders in chunk text with VLM-generated descriptions.

**Mode dispatch — architectural clarification:**

- `vlm_mode="builtin"`: Figure descriptions are generated by Docling's SmolVLM picture
  description pipeline **at parse time** (inside `parse_with_docling` / `DocumentConverter.convert()`).
  Descriptions are already embedded in the `DoclingDocument` before chunking occurs.
  `HybridChunker` then chunks the document with descriptions already present.
  **This node does not run** for `vlm_mode="builtin"` — it returns immediately as a no-op.
- `vlm_mode="external"`: `do_picture_description=False` at parse time. Chunks may contain
  `![...](...)` image reference placeholders. **This node** detects those placeholders and
  calls the external VLM (via LiteLLM) per-chunk to replace them with descriptions.
- `vlm_mode="disabled"`: No VLM enrichment at any stage. This node returns immediately as a no-op.

This is a new node that does not exist in the current pipeline. The existing
`multimodal_processing_node` in Phase 1 is a different node (it processes full document images
before chunking); this new node is post-chunking and operates per-chunk for external mode only.

**File created:** `src/ingest/embedding/nodes/vlm_enrichment.py`

**Subtasks:**

1. Implement `_find_image_placeholders(chunk_text: str) -> list[re.Match]` using the same
   `_IMAGE_REF_PATTERN` from `src/ingest/support/vision.py` to detect `![...](...)` patterns.
2. Implement `_replace_placeholder(chunk_text: str, match: re.Match, description: str) -> str`:
   replace the matched image placeholder with the VLM description, preserving surrounding text.
3. Implement `_enrich_chunk_external(chunk: ProcessedChunk, config: IngestionConfig, figures_processed_count: int) -> tuple[ProcessedChunk, int]`:
   use `src.platform.llm.get_llm_provider()` to call the LiteLLM-routed vision model.
   Respect `config.vision_max_figures` limit per document (FR-2209). On failure after retries,
   return the chunk unchanged and log a warning (FR-2207).
4. Implement `vlm_enrichment_node(state: EmbeddingPipelineState) -> dict[str, Any]`:
   - If `config.vlm_mode != "external"` or `state["chunks"]` is empty or no chunks have
     image placeholders: return immediately with `processing_log` updated to
     `vlm_enrichment:skipped`.
   - When `vlm_mode="builtin"`: log `vlm_enrichment:skipped` — figure descriptions were
     already embedded by Docling at parse time; no action needed here.
   - When `vlm_mode="external"`: iterate over chunks, enrich those with placeholders using
     `_enrich_chunk_external`, leave others unchanged.
   - Log `vlm_enrichment:external:ok` on success.
   - Individual chunk failures are non-fatal; the chunk's original text is preserved.

**Code contract — node signature:**

```python
def vlm_enrichment_node(state: EmbeddingPipelineState) -> dict[str, Any]:
    """Replace image placeholders in chunks with VLM-generated descriptions.

    Only active for vlm_mode="external". For vlm_mode="builtin", figure
    descriptions are already embedded in the DoclingDocument at parse time
    (by Docling's SmolVLM picture description pipeline inside DocumentConverter);
    no post-chunking VLM step is needed. For vlm_mode="disabled", this node
    is a no-op.

    Operates on state["chunks"]. When active (external mode only), calls
    LiteLLM-routed vision model per image placeholder per chunk.

    Per-chunk failures are non-fatal: the original chunk text is preserved
    and a warning is logged. The node never raises; all exceptions are caught.

    Args:
        state: Embedding pipeline state. Must contain "chunks".

    Returns:
        Partial state update:
        - chunks: list[ProcessedChunk] with placeholders replaced where external
            VLM succeeded, original text preserved where VLM failed.
        - processing_log: updated log with enrichment result entry.
    """
```

**Code contract — external path interface:**

The external path reuses the existing `generate_vision_notes` function from
`src/ingest/support/vision.py` adapted for per-chunk operation:

```python
# In _enrich_chunk_external:
from src.ingest.support.vision import _extract_image_candidates, _call_vision_model
# OR call the higher-level generate_vision_notes with the chunk text as input.
```

The exact interface to the external VLM is not redefined here; the existing
`src/ingest/support/vision.py` infrastructure is reused.

**Test expectations:**

- With `vlm_mode="disabled"`: node returns immediately; `chunks` is unchanged; log contains
  `vlm_enrichment:skipped`.
- With `vlm_mode="builtin"`: node returns immediately; `chunks` is unchanged; log contains
  `vlm_enrichment:skipped` (figure descriptions were already applied at parse time by Docling).
- With `vlm_mode="external"` and a chunk containing `![Figure 1](img.png)`: placeholder is
  replaced with description from LiteLLM vision model; surrounding text is unchanged.
- With `vlm_mode="external"` and a VLM API error: chunk retains original placeholder; log
  contains a warning; other chunks processed normally.
- With `vlm_mode="external"` and a document with 20 figures where
  `vision_max_figures=4`: only the first 4 placeholders across all chunks are sent to VLM.
- Node is a no-op when no chunks contain image placeholder patterns.

**Dependencies:** Task 1.1 (vlm_mode config), Task 3.1 (chunking_node produces `chunks`
before this node runs). DAG wiring (Task 4.3).

---

## Group 4 — Cross-Cutting

### Task 4.1 — config/settings.py: new env vars

**Spec requirements:** FR-2405, FR-2407, NFR-2905

**Description:** Add three new environment variable definitions to `config/settings.py`
following the existing `RAG_INGESTION_*` pattern.

**File changed:** `config/settings.py`

**Subtasks:**

1. Add `RAG_INGESTION_VLM_MODE` → `str`, default `"disabled"`.
2. Add `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS` → `int`, default `512`.
3. Add `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT` → `bool`, default `True`.

**Code contract — settings.py additions (to be placed in the ingestion configuration section
after the existing `RAG_INGESTION_DOCLING_*` block):**

```python
# --- Docling-Native Chunking Pipeline ---

RAG_INGESTION_VLM_MODE: str = os.environ.get(
    "RAG_INGESTION_VLM_MODE", "disabled"
)
"""VLM mode for figure image description.
Valid values: "disabled", "builtin", "external".
"builtin" runs SmolVLM at parse time inside DocumentConverter.
"external" calls LiteLLM-routed vision model post-chunking.
"""

RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS: int = int(
    os.environ.get("RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS", "512")
)
"""Maximum token count per chunk for HybridChunker (bge-m3 limit is 512)."""

RAG_INGESTION_PERSIST_DOCLING_DOCUMENT: bool = os.environ.get(
    "RAG_INGESTION_PERSIST_DOCLING_DOCUMENT", "true"
).lower() in ("true", "1", "yes")
"""If True (default), persist DoclingDocument JSON to CleanDocumentStore.
Set to false to trade storage for compute (re-parse in Phase 2)."""
```

**Test expectations:**

- With no env vars set: all three use their documented defaults.
- With `RAG_INGESTION_VLM_MODE=external`: `RAG_INGESTION_VLM_MODE == "external"`.
- With `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS=256`:
  `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS == 256`.
- With `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT=false`:
  `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT == False`.

**Dependencies:** None (pure env-var definitions; foundation for Task 1.1).

---

### Task 4.2 — IngestionDesignCheck: validation rules

**Spec requirements:** FR-2409, NFR-2903

**Description:** Add three new validation rules to the design-check phase (wherever
`IngestionDesignCheck` is populated in the ingestion pipeline startup). This is an additive
change to the existing validation logic, not a new file.

**File changed:** The module that constructs the `IngestionDesignCheck` result. Based on the
existing codebase, locate this in `src/ingest/pipeline/impl.py` or the orchestrator. If no
single design-check function exists, add it to the orchestrator startup path.

**Subtasks:**

1. **Rule A — vlm_mode=builtin without Docling:** If `config.vlm_mode == "builtin"`:
   attempt `from docling.document_converter import DocumentConverter`. If the import fails,
   add an error to `IngestionDesignCheck.errors`: `"vlm_mode=builtin requires docling to be
   installed (uv add docling)"`.
2. **Rule B — vlm_mode=external without LiteLLM Router:** If `config.vlm_mode == "external"`
   and no LiteLLM router config is available (empty `config.vision_model` and no
   `LLM_ROUTER_CONFIG`): add a warning to `IngestionDesignCheck.warnings`:
   `"vlm_mode=external is set but no vision model is configured; VLM enrichment will be
   skipped at runtime"`.
3. **Rule C — hybrid_chunker_max_tokens exceeds known embedding model limit:** If
   `config.hybrid_chunker_max_tokens > 512`: add a warning:
   `"hybrid_chunker_max_tokens ({value}) exceeds bge-m3 maximum input (512); chunks may be
   silently truncated during embedding"`.

**Code contract — check function signature:**

```python
def _check_docling_chunking_config(config: IngestionConfig) -> tuple[list[str], list[str]]:
    """Validate Docling-native chunking configuration.

    Returns:
        Tuple of (errors, warnings). Errors are fatal (block pipeline start);
        warnings are non-fatal (logged but do not halt processing).
    """
```

**Test expectations:**

- `config.vlm_mode="builtin"` + docling not installed → error in `IngestionDesignCheck`.
- `config.vlm_mode="external"` + no vision model configured → warning only.
- `config.hybrid_chunker_max_tokens=1024` → warning with exact value interpolated.
- `config.vlm_mode="disabled"` → no errors, no warnings from these rules.

**Dependencies:** Task 1.1 (config fields must exist).

---

### Task 4.3 — Embedding DAG: wire vlm_enrichment_node

**Spec requirements:** FR-2201 (external VLM must occur post-chunking), NFR-2909

**Description:** Wire the new `vlm_enrichment_node` into the Embedding Pipeline DAG so it
runs after `chunking_node` and before `chunk_enrichment_node`. The node handles its own
skip logic internally: it is a no-op for `vlm_mode="disabled"` and `vlm_mode="builtin"`
(builtin VLM runs at parse time, not here), and only performs work for `vlm_mode="external"`.
No conditional edge is needed in the DAG topology; the node always sits in the graph but
short-circuits when not applicable.

**File changed:** The file that defines the Embedding Pipeline LangGraph DAG. Based on the
existing codebase structure, this is in the embedding pipeline workflow definition file (likely
`src/ingest/embedding/pipeline/workflow.py` or similar; locate via the existing DAG wiring).

**Subtasks:**

1. Import `vlm_enrichment_node` from `src.ingest.embedding.nodes.vlm_enrichment`.
2. Register `vlm_enrichment_node` in the graph between `chunking_node` and the next node
   downstream (currently `chunk_enrichment_node` or equivalent).
3. The node handles all mode dispatch internally:
   - `vlm_mode="disabled"` → immediate no-op, log `vlm_enrichment:skipped`.
   - `vlm_mode="builtin"` → immediate no-op, log `vlm_enrichment:skipped` (descriptions
     already embedded at parse time by Docling's SmolVLM pipeline).
   - `vlm_mode="external"` → perform placeholder replacement via LiteLLM vision model.
   No conditional edge in the DAG is required; the node always executes but is cheap when skipped.
4. Update `PIPELINE_NODE_NAMES` in `src/ingest/common/types.py` to include
   `"vlm_enrichment"` between `"chunking"` and `"chunk_enrichment"`.

**Code contract — PIPELINE_NODE_NAMES update:**

```python
PIPELINE_NODE_NAMES = [
    "document_ingestion",
    "structure_detection",
    "multimodal_processing",
    "text_cleaning",
    "document_refactoring",
    "chunking",
    "vlm_enrichment",          # NEW — post-chunking VLM placeholder replacement (external mode only)
    "chunk_enrichment",
    "metadata_generation",
    "cross_reference_extraction",
    "knowledge_graph_extraction",
    "quality_validation",
    "embedding_storage",
    "knowledge_graph_storage",
]
```

**Test expectations:**

- DAG compiles without errors after wiring.
- A synthetic run with `vlm_mode="disabled"` passes through `vlm_enrichment_node` without
  modifying chunks (log entry `vlm_enrichment:skipped` present).
- The node appears between `chunking_node` output and `chunk_enrichment_node` input in the
  graph topology.

**Dependencies:** Task 3.2 (vlm_enrichment_node implementation), Task 1.1 (PIPELINE_NODE_NAMES
update requires types.py to be stable).

---

# Part B — Code Contracts Reference

This section is the canonical contract reference for each modified or new module. Implementation
agents should implement to exactly these signatures; do not deviate without updating this
document.

---

## B.1 — `src/ingest/support/docling.py`

### `DoclingParseResult` (modified)

```python
@dataclass
class DoclingParseResult:
    text_markdown: str
    has_figures: bool
    figures: list[str]
    headings: list[str]
    parser_model: str
    docling_document: Any          # NEW — docling_core.types.doc.DoclingDocument
```

**Change:** One new field appended at the end. All existing positional or keyword callers
are unaffected (dataclass field defaults are not needed; the field has no default because
`parse_with_docling` always sets it).

### `warmup_docling_models` (modified)

```python
def warmup_docling_models(
    *,
    artifacts_path: str = "",
    with_smolvlm: bool = False,       # NEW parameter
) -> Path:
```

**Change:** New keyword-only parameter `with_smolvlm` with default `False`. All existing call
sites that do not pass this parameter are unaffected.

### `parse_with_docling` (modified — signature and implementation)

```python
def parse_with_docling(
    file_path: str | Path,
    *,
    config: IngestionConfig,
    vlm_mode: str = "disabled",
) -> DoclingParseResult:
```

**Change:** New keyword-only parameter `vlm_mode` with default `"disabled"`. When
`vlm_mode="builtin"`, configures `DocumentConverter` with `do_picture_description=True` and
`PictureDescriptionVlmEngineOptions.from_preset("smolvlm")` before calling `convert()`.
Figure descriptions are embedded in the returned `DoclingDocument` at parse time.
When `vlm_mode != "builtin"`, behavior is identical to the pre-redesign implementation.
The returned `DoclingParseResult` now has `docling_document` populated from `result.document`.
Callers that do not pass `vlm_mode` are unaffected (default `"disabled"`).

---

## B.2 — `src/ingest/doc_processing/state.py`

### `DocumentProcessingState` (modified)

New field added to the TypedDict:

```python
docling_document: Optional[Any]
```

The `structure` dict (type `Dict[str, Any]`) gains a documented key:

```
structure["docling_document_available"]: bool
```

This key is not added as a separate TypedDict field; it is a well-known key within the
existing `structure` dict, consistent with how `has_figures`, `heading_count`, etc. are stored.

---

## B.3 — `src/ingest/embedding/state.py`

### `EmbeddingPipelineState` (modified)

New field added to the TypedDict:

```python
docling_document: Optional[Any]
```

Populated by the orchestrator from `CleanDocumentStore.read_docling(source_key)` before
invoking the Phase 2 graph. `None` if no `.docling.json` file exists or deserialization fails.

---

## B.4 — `src/ingest/common/types.py`

### `IngestionConfig` (modified)

Three new fields at the end of the dataclass (after `ollama_url`):

```python
vlm_mode: str = RAG_INGESTION_VLM_MODE
hybrid_chunker_max_tokens: int = RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS
persist_docling_document: bool = RAG_INGESTION_PERSIST_DOCLING_DOCUMENT
```

### Pre-existing fields referenced by this design

The following `IngestionConfig` fields already exist and are used by `vlm_enrichment_node` (Task 3.2).
Defined in `src/ingest/common/types.py` (lines 107–113), backed by env vars in `config/settings.py`:

```python
vision_max_figures: int = RAG_INGESTION_VISION_MAX_FIGURES  # Max images per doc (external VLM)
vision_timeout_seconds: int = RAG_INGESTION_VISION_TIMEOUT_SECONDS
vision_max_image_bytes: int = RAG_INGESTION_VISION_MAX_IMAGE_BYTES
vision_temperature: float = RAG_INGESTION_VISION_TEMPERATURE
vision_max_tokens: int = RAG_INGESTION_VISION_MAX_TOKENS
```

### `PIPELINE_NODE_NAMES` (modified)

`"vlm_enrichment"` inserted between `"chunking"` and `"chunk_enrichment"`.

---

## B.5 — `src/ingest/common/clean_store.py`

### `CleanDocumentStore` (modified)

New methods:

```python
def _docling_path(self, source_key: str) -> Path

def write_docling(self, source_key: str, docling_document: Any) -> None

def read_docling(self, source_key: str) -> Any | None
```

Modified method:

```python
def write(
    self,
    source_key: str,
    text: str,
    meta: dict[str, Any],
    docling_document: Any | None = None,   # NEW
) -> None
```

Modified method (extended to also remove `.docling.json`):

```python
def delete(self, source_key: str) -> None
```

---

## B.6 — `src/ingest/embedding/nodes/chunking.py`

### `chunking_node` (modified — dual-path logic)

External signature unchanged:

```python
def chunking_node(state: EmbeddingPipelineState) -> dict[str, Any]
```

New private helpers added to the module:

```python
def _chunk_with_docling(
    state: EmbeddingPipelineState,
    config: IngestionConfig,
    base_metadata: dict[str, Any],
) -> list[ProcessedChunk]

def _chunk_with_markdown(
    state: EmbeddingPipelineState,
    config: IngestionConfig,
    base_metadata: dict[str, Any],
) -> list[ProcessedChunk]

def _extract_docling_section_metadata(chunk: Any) -> dict[str, Any]

def _normalize_chunk_text(text: str) -> str
```

---

## B.7 — `src/ingest/embedding/nodes/vlm_enrichment.py` (new file)

**Architectural note:** This node handles **external VLM only**. For `vlm_mode="builtin"`,
figure descriptions are generated by Docling's SmolVLM picture description pipeline at parse
time (inside `parse_with_docling` / `DocumentConverter.convert()`). No builtin VLM helper
exists in this module.

```python
def vlm_enrichment_node(state: EmbeddingPipelineState) -> dict[str, Any]
# Dispatches on config.vlm_mode:
#   "disabled" → immediate no-op, log vlm_enrichment:skipped
#   "builtin"  → immediate no-op, log vlm_enrichment:skipped
#                (descriptions already embedded at parse time)
#   "external" → call _enrich_chunk_external per chunk with placeholders

def _find_image_placeholders(chunk_text: str) -> list[re.Match]

def _replace_placeholder(chunk_text: str, match: re.Match, description: str) -> str

def _enrich_chunk_external(
    chunk: ProcessedChunk,
    config: IngestionConfig,
    figures_processed_count: int,
) -> tuple[ProcessedChunk, int]
```

The `figures_processed_count` parameter and return value allow the caller to track how many
figures have been sent to the external VLM across all chunks, enforcing
`config.vision_max_figures` globally per document.

---

## B.8 — `config/settings.py`

New module-level constants:

```python
RAG_INGESTION_VLM_MODE: str
RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS: int
RAG_INGESTION_PERSIST_DOCLING_DOCUMENT: bool
```

---

# Part C — Dependency DAG

```
                        [settings.py]
                         Task 4.1
                          │
                          ▼
              ┌───────────┴──────────────┐
              │                          │
         Task 1.1                   Task 1.2
      (IngestionConfig)         (State TypedDicts)
              │                          │
              ├──────────────┐           │
              │              │           │
              ▼              │           ▼
         Task 2.1            │      Task 2.2
   (DoclingParseResult)      │  (structure_detection_node)
              │              │           │
              └──────────────┼───────────┘
                             │   │
                             │   ▼
                             │  Task 2.3
                             │ (CleanDocumentStore)
                             │   │
                             │   ▼
                             │  Task 3.1
                             │ (chunking_node)
                             │
                             ▼
                         Task 3.2          Task 4.2
                   (vlm_enrichment_node)  (DesignCheck rules)
                             │
                             ▼
                         Task 4.3
                        (DAG wiring)
```

**Parallel execution opportunities:**

| Wave | Tasks | Prerequisite |
|------|-------|-------------|
| Wave 0 | Task 4.1 | None |
| Wave 1 | Task 1.1, Task 1.2 | Task 4.1 |
| Wave 2 | Task 2.1, Task 2.2 | Task 1.1 + 1.2 |
| Wave 3 | Task 2.3 | Task 2.1 + 2.2 |
| Wave 4 | Task 3.1, Task 3.2 | Task 2.3 (for 3.1); Task 1.1 (for 3.2) |
| Wave 5 | Task 4.2, Task 4.3 | Task 1.1 (for 4.2); Task 3.2 (for 4.3) |

Tasks 3.1 and 3.2 can be developed in parallel: Task 3.1 depends on CleanDocumentStore
(Task 2.3) to know how `docling_document` arrives in state; Task 3.2 only depends on
IngestionConfig (Task 1.1) and the chunk schema.

---

# Part D — Error Handling Matrix

## D.1 Error Categories and Responses

| Error Event | Location | Severity | Response | Log Entry |
|-------------|----------|----------|----------|-----------|
| `docling-core` not installed at import | `parse_with_docling` | Fatal for Docling path | Raise `RuntimeError`; `structure_detection_node` catches and falls back to regex | `structure_detection:failed` (strict) or `structure_detection:ok` with fallback signals |
| `DocumentConverter.convert()` raises | `parse_with_docling` | Fatal for Docling path | Raise `RuntimeError`; handled by `structure_detection_node` | `structure_detection:failed` (strict) or continue with regex fallback |
| SmolVLM model not available / import fails at parse time | `parse_with_docling` (when `vlm_mode="builtin"`) | Non-fatal | Log warning; proceed with `do_picture_description=False`; document parsed without figure descriptions; downstream HybridChunker and VLM enrichment node are unaffected | Warning with source_key and exception detail |
| `warmup_docling_models(with_smolvlm=True)` fails to download SmolVLM | `warmup_docling_models` | Non-fatal warning (pre-flight) | Log warning; pipeline starts; parse-time SmolVLM failure (above) handles the runtime case | Warning at startup / warmup |
| `DoclingDocument` serialization fails | `CleanDocumentStore.write_docling` | Non-fatal | Log error; skip `.docling.json` write; Phase 2 falls back to markdown chunking | Error logged to `processing_log`; no `errors` list entry |
| `.docling.json` corrupt on read | `CleanDocumentStore.read_docling` | Non-fatal | Return `None`; orchestrator sets `docling_document=None`; Phase 2 uses markdown fallback | Warning logged |
| `_schema_version` mismatch on read | `CleanDocumentStore.read_docling` | Non-fatal | Return `None` and log warning; Phase 2 uses markdown fallback | Warning with source_key and expected vs. actual version |
| `HybridChunker` raises any exception | `_chunk_with_docling` | Non-fatal | `chunking_node` catches; falls back to `_chunk_with_markdown` | `hybrid_chunker:error`, `chunking:fallback_to_markdown` |
| External VLM API error | `_enrich_chunk_external` | Non-fatal (per-image) | Return original chunk unchanged after retries; log warning | Warning with chunk index and API error details |
| `vlm_mode` has invalid value | `IngestionDesignCheck` | Fatal at startup | Design-check error message; pipeline does not start | `IngestionDesignCheck.errors` entry |
| `hybrid_chunker_max_tokens` > 512 | `IngestionDesignCheck` | Warning | Non-fatal warning; pipeline starts | `IngestionDesignCheck.warnings` entry |
| `vlm_mode=builtin` + docling not installed | `IngestionDesignCheck` | Fatal at startup | Error message; pipeline does not start | `IngestionDesignCheck.errors` entry |

## D.2 Fallback Cascade

```
vlm_mode=builtin?
  YES → parse_with_docling called with do_picture_description=True
    ├── SmolVLM not available at parse time → log warning, parse without picture descriptions
    │     DoclingDocument returned without figure descriptions
    └── SmolVLM available → figure images processed during DocumentConverter.convert()
          figure descriptions embedded directly in DoclingDocument (before chunking)

Docling parse available?
  YES → write DoclingDocument to CleanDocumentStore
    ├── write_docling fails → skip .docling.json, log error
    │     Phase 2: docling_document=None → markdown chunking path
    └── write_docling succeeds → Phase 2 reads DoclingDocument
          HybridChunker raises?
            YES → log error → _chunk_with_markdown fallback
            NO  → Docling-native chunks produced
                   (if vlm_mode=builtin, figure descriptions already in chunk text)
                   vlm_enrichment_node: skipped (no-op for builtin and disabled)
                   vlm_mode=external? → LiteLLM vision per-chunk placeholder replacement
                     per-image fail   → leave placeholder, log warning

  NO  → docling_document=None → markdown chunking path (unchanged from pre-redesign)
         vlm_mode=external? → vlm_enrichment_node runs per-chunk placeholder replacement
         vlm_mode=builtin or disabled? → vlm_enrichment_node no-op
```

## D.3 What Never Fails a Document

The following errors are non-fatal and will never cause a document to be skipped or fail
the pipeline:

- DoclingDocument serialization failure
- DoclingDocument deserialization failure (corrupt `.docling.json`)
- HybridChunker exception
- SmolVLM not available at parse time (when `vlm_mode="builtin"`): document parsed without
  picture descriptions; downstream chunking and VLM enrichment node are unaffected
- External VLM API error for any individual image chunk
- External VLM API unavailable

The following errors ARE fatal (cause `should_skip=True` or halt the run):

- Docling conversion failure when `docling_strict=True`
- `vlm_mode=builtin` with docling not installed (caught at design-check before any
  documents are processed)

---

# Part E — Migration Notes

## E.1 Backward Compatibility Guarantees

This redesign makes no breaking changes. Every guarantee is enforced by specific spec
requirements (NFR-2903, NFR-2907).

| Interface | Change Type | Backward Compatible? | Notes |
|-----------|-------------|---------------------|-------|
| `DoclingParseResult` | New field added | Yes | New `docling_document` field appended; existing callers unaffected |
| `warmup_docling_models` | New keyword parameter | Yes | `with_smolvlm=False` default preserves current behavior |
| `parse_with_docling` | New keyword parameter + implementation | Yes | New `vlm_mode="disabled"` default preserves current behavior; callers that do not pass `vlm_mode` are unaffected |
| `DocumentProcessingState` | New optional field | Yes | `total=False` TypedDict; existing nodes ignore unknown keys |
| `EmbeddingPipelineState` | New optional field | Yes | Same as above |
| `IngestionConfig` | New fields with defaults | Yes | `IngestionConfig()` produces pre-redesign behavior: `vlm_mode="disabled"`, `hybrid_chunker_max_tokens=512`, `persist_docling_document=True` |
| `CleanDocumentStore.write` | New optional parameter | Yes | `docling_document=None` default preserves current signature |
| `CleanDocumentStore.delete` | Removes extra file | Yes | Backward compatible; if `.docling.json` absent, `unlink(missing_ok=True)` is a no-op |
| `chunking_node` | Dual-path logic added | Yes | External signature unchanged; markdown path behavior unchanged for `docling_document=None` |
| `PIPELINE_NODE_NAMES` | New entry added | Yes | Additive; existing code that reads this list is not broken by a new entry |

## E.2 Default Configuration Preserves Pre-Redesign Behavior

An operator who does not change any environment variables after upgrading gets exactly the
same pipeline behavior as before:

- `vlm_mode="disabled"` → VLM enrichment is skipped; no new image processing occurs.
- `persist_docling_document=True` → DoclingDocument is stored (net new behavior for Docling
  path); this is additive and creates a new `.docling.json` file per document. Operators on
  storage-constrained systems can set `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT=false`.
- `hybrid_chunker_max_tokens=512` → HybridChunker uses the same token limit as bge-m3.
- Docling parsing was already `enable_docling_parser=True` by default; the new behavior is
  that the DoclingDocument is now preserved instead of discarded after markdown export.

## E.3 Existing Test Suite

All existing tests for `chunking_node` should continue to pass without modification because:

- The node's external signature is unchanged.
- When `docling_document` is absent from state (which it is in all existing tests), the node
  takes the `_chunk_with_markdown` path, which is a behavioral copy of the pre-redesign code.
- The only behavior change on the fallback path is the addition of `_normalize_chunk_text`,
  which only alters non-NFC unicode sequences or removes control characters. Existing test
  fixtures that use ASCII or NFC-normalized text are unaffected.

## E.4 Files Modified — Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `config/settings.py` | Additive | Three new env var constants |
| `src/ingest/common/types.py` | Additive | Three new `IngestionConfig` fields; updated `PIPELINE_NODE_NAMES` |
| `src/ingest/support/docling.py` | Additive + Modified | New `DoclingParseResult.docling_document` field; `parse_with_docling` new `vlm_mode` param (configures builtin VLM at parse time); `warmup_docling_models` new `with_smolvlm` param |
| `src/ingest/doc_processing/state.py` | Additive | New `docling_document` field in TypedDict |
| `src/ingest/embedding/state.py` | Additive | New `docling_document` field in TypedDict |
| `src/ingest/common/clean_store.py` | Extended | Two new methods; `write` optional param; `delete` extended |
| `src/ingest/doc_processing/nodes/structure_detection.py` | Extended | Propagate `docling_document`; set `docling_document_available` |
| `src/ingest/embedding/nodes/chunking.py` | Refactored | Dual-path logic; unicode normalization; log entries |
| `src/ingest/embedding/nodes/vlm_enrichment.py` | New file | Post-chunking VLM enrichment node |
| Embedding DAG workflow file | Extended | Wire `vlm_enrichment_node` |
| Orchestrator startup / design-check module | Extended | Three new validation rules |

## E.5 New Dependencies

| Dependency | When Required | Installation |
|-----------|---------------|-------------|
| `docling.chunking.HybridChunker` | When `docling_document` is not `None` in state | Already in `docling` package (existing dep) |
| `docling.datamodel.pipeline_options.PictureDescriptionVlmEngineOptions` | When `vlm_mode="builtin"` (used in `parse_with_docling`) | Already in `docling` package; SmolVLM model artifacts downloaded separately via `warmup_docling_models(with_smolvlm=True)` before first document is processed |
| `unicodedata` (stdlib) | Always (chunk normalization) | Stdlib; no installation needed |

No new third-party packages are introduced. The existing `docling`, `docling-core`, and
`src.platform.llm` infrastructure is reused.

**Note on SmolVLM usage:** SmolVLM runs inside Docling's `DocumentConverter.convert()` pipeline
at parse time (Phase 1). It is not called from `vlm_enrichment_node`. The `warmup_docling_models`
function with `with_smolvlm=True` ensures model artifacts are downloaded before ingestion starts.

---

# Part F — Architecture Overview: Revised Data Flow

```
Source Document File
    │
    ▼
┌──────────────────────────────────────────────────────────────────┐
│ [Phase 1 — Node 2] STRUCTURE DETECTION                          │
│                                                                  │
│  parse_with_docling(vlm_mode=config.vlm_mode)  ← UPDATED SIG   │
│                                                                  │
│  When vlm_mode="builtin":                                        │
│    DocumentConverter configured with:                            │
│      do_picture_description=True                                 │
│      PictureDescriptionVlmEngineOptions.from_preset("smolvlm")   │
│    → SmolVLM runs on each figure image DURING convert()         │
│    → Figure descriptions baked into DoclingDocument             │
│                                                                  │
│  When vlm_mode="external" or "disabled":                         │
│    DocumentConverter configured with do_picture_description=False│
│    → No VLM at parse time                                        │
│                                                                  │
│  Returns DoclingParseResult {                                    │
│    text_markdown,                                                │
│    has_figures,                                                  │
│    figures,                                                      │
│    headings,                                                     │
│    parser_model,                                                 │
│    docling_document  ← NEW (with figure descriptions if builtin)│
│  }                                                               │
│                                                                  │
│  State update: {                                                 │
│    raw_text: text_markdown,                                      │
│    docling_document: DoclingDocument,   ← NEW                   │
│    structure: {                                                  │
│      ...,                                                        │
│      docling_document_available: True,  ← NEW                   │
│    }                                                             │
│  }                                                               │
└───────────────────────────┬──────────────────────────────────────┘
                            │
                ┌───────────▼───────────┐
                │ docling_document_     │
                │ available?            │
                └─────┬─────────────┬──┘
               Yes    │             │  No
                      ▼             ▼
┌──────────────────┐  ┌─────────────────────────┐
│ [Phase 1, Node 3]│  │ [Phase 1, Node 3]        │
│  text_cleaning   │  │  text_cleaning           │
│  SKIPPED         │  │  RUNS (existing behavior)│
├──────────────────┤  ├─────────────────────────┤
│ [Phase 1, Node 4]│  │ [Phase 1, Node 4]        │
│  doc_refactoring │  │  doc_refactoring         │
│  SKIPPED         │  │  RUNS if enabled         │
└────────┬─────────┘  └──────────────┬───────────┘
         │                           │
         ▼                           ▼
┌──────────────────────────────────────────────────────────────────┐
│ CLEAN DOCUMENT STORE (Phase 1/2 boundary)                       │
│                                                                  │
│  {source_key}.md           — markdown text (existing)           │
│  {source_key}.meta.json    — metadata (existing)                │
│  {source_key}.docling.json — DoclingDocument JSON (NEW)         │
│                              written only when:                 │
│                              - docling_document is not None     │
│                              - persist_docling_document=True    │
│                              Note: if vlm_mode=builtin, the     │
│                              stored DoclingDocument already      │
│                              contains SmolVLM figure descriptions│
└───────────────────────────┬──────────────────────────────────────┘
                            │
                            ▼ (Phase 2 orchestrator reads store)
                ┌───────────▼───────────┐
                │ docling_document      │
                │ available in state?   │
                └─────┬─────────────┬──┘
               Yes    │             │  No
                      ▼             ▼
┌──────────────────────┐  ┌─────────────────────────────────┐
│ [Phase 2, Node 6]    │  │ [Phase 2, Node 6]               │
│  chunking_node       │  │  chunking_node                  │
│  HybridChunker path  │  │  Markdown path (unchanged)      │
│                      │  │  MarkdownHeaderTextSplitter +   │
│  max_tokens from     │  │  RecursiveCharacterTextSplitter │
│  config              │  │                                 │
│  section_path from   │  │  section_path from header       │
│  DoclingDocument     │  │  metadata                       │
│  heading hierarchy   │  │                                 │
│                      │  │                                 │
│  (if vlm_mode=builtin│  │                                 │
│   figure descriptions│  │                                 │
│   already in chunks) │  │                                 │
└──────────┬───────────┘  └───────────────┬─────────────────┘
           │                              │
           └──────────────┬───────────────┘
                          │  unicode normalization applied to all chunks
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│ [Phase 2, NEW Node] VLM ENRICHMENT                              │
│                                                                  │
│  vlm_mode=disabled → no-op (skipped)                            │
│  vlm_mode=builtin  → no-op (skipped): figure descriptions were  │
│                       embedded at parse time by Docling SmolVLM  │
│  vlm_mode=external → LiteLLM vision per-chunk placeholder        │
│                       replacement (max_figures cap enforced)     │
│                       Per-image failures: leave placeholder,     │
│                       log warning                                │
└───────────────────────────┬──────────────────────────────────────┘
                            │
                            ▼
                  ProcessedChunk list
                  with consistent metadata schema
                  (section_path, heading, heading_level,
                   chunk_index, total_chunks, source, ...)
                            │
                            ▼
              [chunk_enrichment, metadata_generation,
               embedding_storage, ... — UNCHANGED]
```

---

# Appendix — Traceability Matrix (Design → Spec)

| Task | Spec Requirements |
|------|-------------------|
| 1.1 | FR-2401, FR-2403, FR-2405, FR-2407, NFR-2903 |
| 1.2 | FR-2501, FR-2503, FR-2505 |
| 2.1 | FR-2001, FR-2211 (warmup_docling_models param) |
| 2.2 | FR-2003, FR-2011, FR-2013, FR-2505 |
| 2.3 | FR-2005, FR-2007, FR-2009, NFR-2911 |
| 3.1 | FR-2015, FR-2101, FR-2103, FR-2105, FR-2107, FR-2109, FR-2111, FR-2113, FR-2115, FR-2301, FR-2303, FR-2305, FR-2307, FR-2601, NFR-2907, NFR-2909 |
| 3.2 | FR-2201, FR-2203, FR-2205, FR-2207, FR-2209, FR-2211 |
| 4.1 | FR-2405, NFR-2905 |
| 4.2 | FR-2409, NFR-2903 |
| 4.3 | FR-2201 (post-chunking placement), NFR-2909 |

**Full coverage check — all MUST requirements addressed:**

| FR/NFR ID | Priority | Addressed By |
|-----------|----------|-------------|
| FR-2001 | MUST | Task 2.1 |
| FR-2003 | MUST | Task 2.2 |
| FR-2005 | MUST | Task 2.3 |
| FR-2007 | MUST | Task 2.3 |
| FR-2011 | MUST | Task 2.2 (docling_document_available routing signal) |
| FR-2013 | MUST | Task 2.2 (same signal drives refactoring skip) |
| FR-2015 | MUST | Task 3.1 (_normalize_chunk_text applied to all chunks) |
| FR-2101 | MUST | Task 3.1 (_chunk_with_docling) |
| FR-2103 | MUST | Task 3.1 (HybridChunker max_tokens from config) |
| FR-2105 | MUST | Task 3.1 (_extract_docling_section_metadata) |
| FR-2107 | MUST | Task 3.1 (HybridChunker native behavior) |
| FR-2109 | MUST | Task 3.1 (no _semantic_split on Docling path) |
| FR-2111 | MUST | Task 3.1 (ProcessedChunk metadata schema) |
| FR-2201 | MUST | Task 3.2, Task 4.3 |
| FR-2203 | MUST | Task 3.2 (vlm_mode three-way dispatch) |
| FR-2205 | MUST | Task 3.2 (_replace_placeholder) |
| FR-2207 | MUST | Task 3.2 (per-image non-fatal error handling) |
| FR-2301 | MUST | Task 3.1 (_chunk_with_markdown fallback) |
| FR-2303 | MUST | Task 2.2 (routing signal; text_cleaning/refactoring run on fallback path) |
| FR-2305 | MUST | Task 3.1 (_chunk_with_markdown is behavioral copy of pre-redesign code) |
| FR-2307 | MUST | Task 3.1 (path selection based solely on docling_document presence) |
| FR-2401 | MUST | Task 1.1 (vlm_mode field) |
| FR-2403 | MUST | Task 1.1 (hybrid_chunker_max_tokens field) |
| FR-2405 | MUST | Task 4.1 (env vars) + Task 1.1 (consume them) |
| FR-2407 | MUST | Task 1.1 (persist_docling_document field) |
| FR-2501 | MUST | Task 1.2 (DocumentProcessingState.docling_document) |
| FR-2503 | MUST | Task 1.2 (EmbeddingPipelineState.docling_document) |
| FR-2505 | MUST | Task 2.2 (structure["docling_document_available"]) |
| FR-2601 | MUST | Task 3.1 (HybridChunker try/except fallback) |
| FR-2603 | MUST | Task 2.3 (read_docling returns None on corrupt file) |
| NFR-2903 | MUST | Tasks 1.1, 1.2, 2.1, 2.3, 3.1 (all defaults preserve pre-redesign behavior) |
| NFR-2905 | MUST | Task 4.1 (all new params have env vars) |
| NFR-2907 | MUST | Task 3.1 (ProcessedChunk schema identical for both paths) |
