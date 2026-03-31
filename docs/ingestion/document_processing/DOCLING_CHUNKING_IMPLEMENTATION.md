# Docling-Native Chunking Pipeline — Implementation Docs

> **For implement-code agents:** This document is your source of truth.
> Read ONLY your assigned task section. Your section contains your FR context,
> Phase 0 contracts inlined, implementation steps, and isolation contract verbatim.
> Do not read the full document, the spec, the design doc, or other task sections.

**Goal:** Redesign the document processing and chunking pipeline to use Docling's `DoclingDocument` object natively with `HybridChunker`, replacing the current markdown-string-based chunking cascade, while preserving the markdown pipeline as a fallback for non-Docling sources.
**Spec:** `docs/ingestion/document_processing/DOCLING_CHUNKING_SPEC.md`
**Design doc:** `docs/ingestion/document_processing/DOCLING_CHUNKING_DESIGN.md`
**Output path:** `docs/ingestion/document_processing/DOCLING_CHUNKING_IMPLEMENTATION.md`
**Produced by:** write-implementation-docs
**Phase 0 status:** [ ] Awaiting human review

---

## Phase 0: Contract Definitions

> **Human review gate:** Approve this section before any implement-code task begins.
> Every task section inlines these contracts. A mistake here propagates to every task.

This section defines all shared type surfaces, exception classes, function stubs, pure utilities, error taxonomy, and integration contracts for the Docling-Native Chunking Pipeline redesign.

---

### Modified Dataclasses

#### `DoclingParseResult` — `src/ingest/support/docling.py`

```python
from dataclasses import dataclass
from typing import Any

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

**Change:** One new field `docling_document: Any` appended at the end. All existing positional or keyword callers are unaffected. The field has no default — `parse_with_docling` always sets it.

---

### Modified TypedDicts

#### `DocumentProcessingState` addition — `src/ingest/doc_processing/state.py`

```python
from typing import Any, Optional
from typing_extensions import TypedDict

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

The `structure` dict (type `Dict[str, Any]`) gains a documented key — NOT a separate TypedDict field:

```
structure["docling_document_available"]: bool
    Set to True by structure_detection_node when Docling parse succeeds.
    Set to False on fallback (regex path, Docling disabled, Docling failed non-strict).
    Downstream routing logic reads this flag to skip text_cleaning and
    document_refactoring for Docling-parsed documents.
```

#### `EmbeddingPipelineState` addition — `src/ingest/embedding/state.py`

```python
class EmbeddingPipelineState(TypedDict, total=False):
    # ... existing fields unchanged ...

    docling_document: Optional[Any]
    """Native DoclingDocument object loaded from CleanDocumentStore at
    Phase 2 initialization. None if no .docling.json was stored (fallback
    path). Read by chunking_node to select HybridChunker vs markdown path.
    """
```

---

### Modified Dataclass Fields — `IngestionConfig` in `src/ingest/common/types.py`

Three new fields appended at the end of `IngestionConfig` (after existing `ollama_url` field):

```python
from config.settings import (
    RAG_INGESTION_VLM_MODE,
    RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS,
    RAG_INGESTION_PERSIST_DOCLING_DOCUMENT,
)

# Inside IngestionConfig dataclass:
vlm_mode: str = RAG_INGESTION_VLM_MODE
"""VLM mode for figure image description. Valid values: "disabled", "builtin", "external".
"builtin" runs SmolVLM at parse time inside DocumentConverter.
"external" calls LiteLLM-routed vision model post-chunking.
Default: "disabled" (preserves pre-redesign behavior).
"""

hybrid_chunker_max_tokens: int = RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS
"""Maximum token count per chunk for HybridChunker. Default: 512 (bge-m3 limit)."""

persist_docling_document: bool = RAG_INGESTION_PERSIST_DOCLING_DOCUMENT
"""If True (default), persist DoclingDocument JSON to CleanDocumentStore.
Set to False to trade storage for compute (Phase 2 falls back to markdown chunking)."""
```

Also, `PIPELINE_NODE_NAMES` list in `src/ingest/common/types.py` gains `"vlm_enrichment"` inserted between `"chunking"` and `"chunk_enrichment"`:

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

---

### Function Stubs

#### `parse_with_docling` — `src/ingest/support/docling.py`

```python
from pathlib import Path
from typing import Any

def parse_with_docling(
    file_path: str | Path,
    *,
    config: "IngestionConfig",
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

    Returns:
        DoclingParseResult with docling_document populated from result.document.

    Raises:
        RuntimeError: If conversion fails and docling_strict=True.
    """
    raise NotImplementedError("Task 2.1")
```

#### `warmup_docling_models` — `src/ingest/support/docling.py`

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

    Returns:
        Path to the artifacts directory.
    """
    raise NotImplementedError("Task 2.1")
```

#### `structure_detection_node` return contract — `src/ingest/doc_processing/nodes/structure_detection.py`

```python
def structure_detection_node(state: "DocumentProcessingState") -> dict[str, Any]:
    """Detect document structure using Docling or regex fallback.

    On successful Docling parse, returns state update including
    docling_document and structure["docling_document_available"]=True.
    On fallback or disabled Docling, docling_document key is absent
    (or None) and structure["docling_document_available"]=False.

    Args:
        state: Current DocumentProcessingState.

    Returns:
        Partial state update dict. Keys set on success:
            raw_text, docling_document, structure, processing_log.
        Keys set on fallback:
            raw_text, structure, processing_log.
    """
    raise NotImplementedError("Task 2.2")
```

#### `CleanDocumentStore` new methods — `src/ingest/common/clean_store.py`

```python
class CleanDocumentStore:
    # --- existing methods unchanged (write, read, exists, clean_hash, list_keys) ---

    def _docling_path(self, source_key: str) -> Path:
        """Return the path for the serialized DoclingDocument JSON file.

        Args:
            source_key: Stable source identity key.

        Returns:
            Path of the form {store_dir}/{safe_key}.docling.json
        """
        raise NotImplementedError("Task 2.3")

    def write_docling(self, source_key: str, docling_document: Any) -> None:
        """Atomically serialize and persist a DoclingDocument.

        Writes to a .tmp file first, then renames into place.
        Wraps the serialized document in an envelope with _schema_version:
            {"_schema_version": "docling-native-v1", "document": {...}}

        Args:
            source_key: Stable source identity key.
            docling_document: Native DoclingDocument object (docling_core
                Pydantic model). Must support .model_dump_json() serialization.

        Raises:
            OSError: If the atomic write fails (tmp write or rename).
            ValueError: If the document cannot be serialized.
        """
        raise NotImplementedError("Task 2.3")

    def read_docling(self, source_key: str) -> Any | None:
        """Deserialize and return a DoclingDocument for the given source key.

        Checks _schema_version before deserializing. Logs a warning on version
        mismatch and returns None. Imports DoclingDocument lazily inside this
        method to avoid a hard docling-core import at module load time.

        Returns:
            The deserialized DoclingDocument, or None if:
            - The .docling.json file does not exist.
            - The file contains invalid JSON.
            - Deserialization fails (schema version mismatch, missing
              docling-core dependency).

        Logs a warning on any deserialization failure. Never raises.
        """
        raise NotImplementedError("Task 2.3")

    def write(
        self,
        source_key: str,
        text: str,
        meta: dict[str, Any],
        docling_document: Any | None = None,
    ) -> None:
        """Atomically write clean text, metadata, and optional DoclingDocument.

        The docling_document is only written when docling_document is not None.
        A failure to write the DoclingDocument is non-fatal: the markdown and
        metadata files are preserved, and the caller falls back to markdown
        chunking in Phase 2.

        Args:
            source_key: Stable source identity key.
            text: Clean markdown text.
            meta: Metadata dict to serialize as JSON.
            docling_document: Optional native DoclingDocument. When not None,
                calls write_docling after the md + meta write. write_docling
                failure is logged but does not roll back the md/meta write.
        """
        raise NotImplementedError("Task 2.3")

    def delete(self, source_key: str) -> None:
        """Remove the clean document entry for this key (all three files).

        Removes {safe_key}.md, {safe_key}.meta.json, and {safe_key}.docling.json
        when present. Missing files are silently ignored.
        """
        raise NotImplementedError("Task 2.3")
```

#### `chunking_node` and helpers — `src/ingest/embedding/nodes/chunking.py`

```python
import unicodedata
import re as _re
from typing import Any

def chunking_node(state: "EmbeddingPipelineState") -> dict[str, Any]:
    """Split document into chunks using HybridChunker (Docling path) or
    MarkdownHeaderTextSplitter (fallback path).

    Path selection is automatic: if state["docling_document"] is not None,
    HybridChunker is used. Otherwise the existing markdown path is used.
    HybridChunker failures fall back to the markdown path automatically.

    Returns:
        Partial state update containing:
        - chunks: list[ProcessedChunk]
        - processing_log: updated log with path taken
    """
    raise NotImplementedError("Task 3.1")


def _chunk_with_docling(
    state: "EmbeddingPipelineState",
    config: "IngestionConfig",
    base_metadata: dict[str, Any],
) -> list["ProcessedChunk"]:
    """Chunk a DoclingDocument using Docling's HybridChunker.

    Args:
        state: Embedding pipeline state. state["docling_document"] must be
            a valid DoclingDocument instance.
        config: Ingestion configuration. config.hybrid_chunker_max_tokens
            controls the token size limit.
        base_metadata: Pre-built source metadata dict (source, source_uri,
            source_key, source_id, connector, source_version).

    Returns:
        List of ProcessedChunk objects with full metadata including
        section_path, heading, heading_level, chunk_index, total_chunks.

    Raises:
        Any exception from HybridChunker (caller catches and falls back).
    """
    raise NotImplementedError("Task 3.1")


def _chunk_with_markdown(
    state: "EmbeddingPipelineState",
    config: "IngestionConfig",
    base_metadata: dict[str, Any],
) -> list["ProcessedChunk"]:
    """Chunk a markdown string using MarkdownHeaderTextSplitter + RecursiveCharacterTextSplitter.

    Behaviorally identical to the pre-redesign chunking_node body (FR-2305).
    This function is the unchanged fallback path extracted into a helper.

    Args:
        state: Embedding pipeline state. state must contain markdown text.
        config: Ingestion configuration.
        base_metadata: Pre-built source metadata dict.

    Returns:
        List of ProcessedChunk objects. Output is byte-identical to
        pre-redesign output except where _normalize_chunk_text alters
        non-NFC sequences or removes control characters.
    """
    raise NotImplementedError("Task 3.1")
```

#### `vlm_enrichment_node` and helpers — `src/ingest/embedding/nodes/vlm_enrichment.py` (NEW FILE)

```python
import re
from typing import Any

def vlm_enrichment_node(state: "EmbeddingPipelineState") -> dict[str, Any]:
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
        state: Embedding pipeline state. Must contain "chunks" and "config".

    Returns:
        Partial state update:
        - chunks: list[ProcessedChunk] with placeholders replaced where external
            VLM succeeded, original text preserved where VLM failed.
        - processing_log: updated log with enrichment result entry.
    """
    raise NotImplementedError("Task 3.2")


def _find_image_placeholders(chunk_text: str) -> list[re.Match]:
    """Find all image reference placeholders in chunk text.

    Uses the same _IMAGE_REF_PATTERN from src/ingest/support/vision.py
    to detect ![...](...)  patterns.

    Args:
        chunk_text: The text of a single chunk.

    Returns:
        List of re.Match objects for each placeholder found.
    """
    raise NotImplementedError("Task 3.2")


def _replace_placeholder(
    chunk_text: str, match: re.Match, description: str
) -> str:
    """Replace a single image placeholder with the VLM description.

    Preserves all surrounding text exactly. Only the matched placeholder
    span is replaced.

    Args:
        chunk_text: Full chunk text containing the placeholder.
        match: re.Match from _find_image_placeholders identifying the span.
        description: VLM-generated description string.

    Returns:
        Chunk text with the matched placeholder replaced by description.
    """
    raise NotImplementedError("Task 3.2")


def _enrich_chunk_external(
    chunk: "ProcessedChunk",
    config: "IngestionConfig",
    figures_processed_count: int,
) -> tuple["ProcessedChunk", int]:
    """Enrich a single chunk by replacing image placeholders via external VLM.

    Respects config.vision_max_figures limit across the whole document
    (tracked by figures_processed_count). On VLM API failure after retries,
    returns the original chunk unchanged and logs a warning.

    Args:
        chunk: The ProcessedChunk to enrich.
        config: Ingestion configuration (vision_max_figures, vision_timeout_seconds, etc.).
        figures_processed_count: Number of figures already processed in this
            document across all preceding chunks.

    Returns:
        Tuple of (enriched_chunk, new_figures_processed_count).
        enriched_chunk is the original chunk if no placeholders found,
        vision_max_figures reached, or VLM call fails.
    """
    raise NotImplementedError("Task 3.2")
```

#### `_check_docling_chunking_config` — location: startup/design-check path in `src/ingest/pipeline/impl.py`

```python
def _check_docling_chunking_config(
    config: "IngestionConfig",
) -> tuple[list[str], list[str]]:
    """Validate Docling-native chunking configuration.

    Checks for three contradiction patterns:
    - vlm_mode=builtin without docling installed (fatal error)
    - vlm_mode=external without LiteLLM vision model configured (warning)
    - hybrid_chunker_max_tokens > 512 bge-m3 limit (warning)

    Returns:
        Tuple of (errors, warnings). Errors are fatal (block pipeline start);
        warnings are non-fatal (logged but do not halt processing).
    """
    raise NotImplementedError("Task 4.2")
```

---

### Pure Utilities (fully implemented — no stubs)

These functions are deterministic, have no external dependencies, and are safe to use by any task or test agent without waiting for implementation.

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


def _extract_docling_section_metadata(chunk: Any) -> dict[str, Any]:
    """Extract section_path, heading, heading_level from a HybridChunker chunk.

    HybridChunker chunks expose their heading hierarchy via
    chunk.meta.headings (list of heading strings, outermost first).

    Args:
        chunk: A ChunkWithMetadata object from HybridChunker.

    Returns:
        Dict with keys: section_path (str), heading (str), heading_level (int).
        section_path is " > ".join(headings). heading is headings[-1] or "".
        heading_level is len(headings).
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

---

### Serialization Envelope Format

The `.docling.json` file written by `write_docling` uses this top-level structure:

```json
{
  "_schema_version": "docling-native-v1",
  "document": { "<DoclingDocument JSON produced by model_dump_json()>" }
}
```

`read_docling` MUST check `_schema_version` before deserializing. On mismatch, log a warning and return `None`.

---

### Error Taxonomy

| Error Type | Trigger Condition | Expected Message Format | Retryable | Raising Module |
|---|---|---|---|---|
| `RuntimeError` | `DocumentConverter.convert()` fails with `docling_strict=True` | `"Docling conversion failed: {detail}"` | No | `src/ingest/support/docling.py` |
| `OSError` | Atomic write of `.docling.json.tmp` fails or rename fails | `"Failed to write DoclingDocument to {path}: {detail}"` | Unknown — caller decides | `src/ingest/common/clean_store.py` |
| `ValueError` | `DoclingDocument.model_dump_json()` raises (unpicklable object) | `"Failed to serialize DoclingDocument: {detail}"` | No | `src/ingest/common/clean_store.py` |
| `json.JSONDecodeError` | `.docling.json` file contains invalid JSON | Caught internally; returns `None`; logs warning | No | `src/ingest/common/clean_store.py` |
| Any exception from `HybridChunker` | HybridChunker raises on an edge-case document | Caught by `chunking_node`; falls back to markdown | Unknown — caller decides | `src/ingest/embedding/nodes/chunking.py` |
| LiteLLM API error | External VLM timeout or API rejection | Caught by `_enrich_chunk_external`; returns original chunk | Yes — caller retries | `src/ingest/embedding/nodes/vlm_enrichment.py` |
| `ImportError` | `vlm_mode=builtin` with docling not installed | `"vlm_mode=builtin requires docling to be installed (uv add docling)"` | No | `src/ingest/pipeline/impl.py` (design check) |

---

### Integration Contracts

```
structure_detection_node → parse_with_docling(file_path, config=config, vlm_mode=config.vlm_mode)
  Called when: Docling parser is enabled (config.enable_docling_parser=True)
  On RuntimeError (strict=True): node catches, sets docling_document=None, structure["docling_document_available"]=False, logs error
  On RuntimeError (strict=False): node falls back to regex; docling_document absent from state update

structure_detection_node → CleanDocumentStore.write(source_key, text, meta, docling_document=doc)
  Called when: structure detection completes (always)
  On write_docling failure (OSError/ValueError): write() logs error, skips .docling.json, preserves .md and .meta.json
  Phase 2 will find no .docling.json and fall back to markdown chunking

orchestrator (Phase 2 init) → CleanDocumentStore.read_docling(source_key)
  Called when: Phase 2 initializes EmbeddingPipelineState for a document
  On None return (missing file, corrupt JSON, schema mismatch): orchestrator sets docling_document=None in state; logs error
  Result sets state["docling_document"] before the DAG runs

chunking_node → _chunk_with_docling(state, config, base_metadata)
  Called when: state["docling_document"] is not None
  On any exception: chunking_node catches, logs hybrid_chunker:error, calls _chunk_with_markdown as fallback

chunking_node → _chunk_with_markdown(state, config, base_metadata)
  Called when: state["docling_document"] is None OR _chunk_with_docling raises
  On exception: propagates (markdown path failure is fatal for this document)

vlm_enrichment_node → _enrich_chunk_external(chunk, config, figures_processed_count)
  Called when: vlm_mode="external" AND chunk contains image placeholders AND figures_processed_count < vision_max_figures
  On LiteLLM error after retries: return (original_chunk, figures_processed_count); log warning; continue with next chunk
```

---

## Task 4.1: settings.py — New Environment Variable Definitions

**Description:** Add three new module-level constants to `config/settings.py` following the existing `RAG_INGESTION_*` pattern. These constants are imported by `IngestionConfig` in `src/ingest/common/types.py` (Task 1.1). This task has no upstream dependencies and must be completed first because Task 1.1 imports these symbols.

**Spec requirements:** FR-2405, FR-2407, NFR-2905

**Dependencies:** None (Wave 0 — foundation for all other tasks)

**Source files:**
- MODIFY `config/settings.py`

---

**Phase 0 contracts (inlined — implement these stubs):**

No stubs — this task adds pure constant definitions. The target code:

```python
# In config/settings.py — add in the ingestion configuration section
# after the existing RAG_INGESTION_DOCLING_* block

import os

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

---

**Implementation steps:**

1. [FR-2405] Locate the `RAG_INGESTION_DOCLING_*` block in `config/settings.py` and append a new section comment `# --- Docling-Native Chunking Pipeline ---` after it.
2. [FR-2405] Add `RAG_INGESTION_VLM_MODE: str = os.environ.get("RAG_INGESTION_VLM_MODE", "disabled")` with the module-level docstring exactly as specified above.
3. [FR-2403, FR-2405] Add `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS: int = int(os.environ.get("RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS", "512"))` with docstring.
4. [FR-2407, FR-2405] Add `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT: bool = os.environ.get("RAG_INGESTION_PERSIST_DOCLING_DOCUMENT", "true").lower() in ("true", "1", "yes")` with docstring.
5. [NFR-2905] Verify no hardcoded value — all three use `os.environ.get(...)` with documented string defaults.
6. Add `@summary` block update comment if the file has one. Add module-level docstring to the new block.

**Completion criteria:**
- [ ] All three constants defined in `config/settings.py` with correct types and defaults
- [ ] No env var reads default to wrong type (int cast, bool `.lower() in (...)`)
- [ ] `from config.settings import RAG_INGESTION_VLM_MODE, RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS, RAG_INGESTION_PERSIST_DOCLING_DOCUMENT` succeeds without error
- [ ] With no env vars set: `RAG_INGESTION_VLM_MODE == "disabled"`, `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS == 512`, `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT == True`

**Test expectations:**
- `assert RAG_INGESTION_VLM_MODE == "disabled"` (no env var set)
- With `os.environ["RAG_INGESTION_VLM_MODE"] = "external"` → `"external"` after module re-import
- With `os.environ["RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS"] = "256"` → `256` (int)
- With `os.environ["RAG_INGESTION_PERSIST_DOCLING_DOCUMENT"] = "false"` → `False`
- With `os.environ["RAG_INGESTION_PERSIST_DOCLING_DOCUMENT"] = "0"` → `False`
- With `os.environ["RAG_INGESTION_PERSIST_DOCLING_DOCUMENT"] = "yes"` → `True`

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 1.1: IngestionConfig — New Fields

**Description:** Add three new fields to the `IngestionConfig` dataclass in `src/ingest/common/types.py`. These fields are the primary configuration knobs for the redesigned pipeline. All three must have defaults that preserve pre-redesign behavior (NFR-2903). Also update `PIPELINE_NODE_NAMES` in the same file to include `"vlm_enrichment"` between `"chunking"` and `"chunk_enrichment"`. The imports for the three new settings constants must be added to the import block.

**Spec requirements:** FR-2401, FR-2403, FR-2405, FR-2407, NFR-2903

**Dependencies:** Task 4.1 (settings constants must exist before they can be imported here)

**Source files:**
- MODIFY `src/ingest/common/types.py`

---

**Phase 0 contracts (inlined — implement these stubs):**

No function stubs — this task adds dataclass fields and a list entry. The exact target additions:

```python
# In src/ingest/common/types.py — add to imports:
from config.settings import (
    # ... existing imports ...
    RAG_INGESTION_VLM_MODE,
    RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS,
    RAG_INGESTION_PERSIST_DOCLING_DOCUMENT,
)

# Inside IngestionConfig dataclass — append after existing ollama_url field:
vlm_mode: str = RAG_INGESTION_VLM_MODE
"""VLM mode: "disabled" | "builtin" | "external". Default: "disabled"."""

hybrid_chunker_max_tokens: int = RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS
"""Max tokens per HybridChunker chunk. Default: 512 (bge-m3 limit)."""

persist_docling_document: bool = RAG_INGESTION_PERSIST_DOCLING_DOCUMENT
"""If True, persist DoclingDocument JSON to CleanDocumentStore. Default: True."""

# PIPELINE_NODE_NAMES list — insert "vlm_enrichment" between "chunking" and "chunk_enrichment":
PIPELINE_NODE_NAMES = [
    "document_ingestion",
    "structure_detection",
    "multimodal_processing",
    "text_cleaning",
    "document_refactoring",
    "chunking",
    "vlm_enrichment",          # NEW
    "chunk_enrichment",
    "metadata_generation",
    "cross_reference_extraction",
    "knowledge_graph_extraction",
    "quality_validation",
    "embedding_storage",
    "knowledge_graph_storage",
]
```

---

**Implementation steps:**

1. [FR-2405] Read `src/ingest/common/types.py` to locate the existing `from config.settings import ...` block. Add `RAG_INGESTION_VLM_MODE`, `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS`, `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT` to that import.
2. [FR-2401] Locate the `IngestionConfig` dataclass. Append `vlm_mode: str = RAG_INGESTION_VLM_MODE` after the last existing field (after `ollama_url` or equivalent). Add field docstring.
3. [FR-2403] Append `hybrid_chunker_max_tokens: int = RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS`. Add field docstring.
4. [FR-2407] Append `persist_docling_document: bool = RAG_INGESTION_PERSIST_DOCLING_DOCUMENT`. Add field docstring.
5. [NFR-2903] Verify `IngestionConfig()` with no arguments still constructs without error and has the same behavior as before (backward-compatible defaults: `vlm_mode=="disabled"`, etc.).
6. [NFR-2903] Locate `PIPELINE_NODE_NAMES` list and insert `"vlm_enrichment"` between `"chunking"` and `"chunk_enrichment"`.
7. Update `@summary` block in the file to note the new fields.

**Completion criteria:**
- [ ] `IngestionConfig()` succeeds with no arguments; `.vlm_mode == "disabled"`, `.hybrid_chunker_max_tokens == 512`, `.persist_docling_document == True`
- [ ] `IngestionConfig(vlm_mode="external")` produces `vlm_mode == "external"`
- [ ] `"vlm_enrichment"` appears in `PIPELINE_NODE_NAMES` between `"chunking"` and `"chunk_enrichment"`
- [ ] No existing field is renamed, removed, or has its default changed
- [ ] Import from config.settings succeeds

**Test expectations:**
- `assert IngestionConfig().vlm_mode == "disabled"`
- `assert IngestionConfig().hybrid_chunker_max_tokens == 512`
- `assert IngestionConfig().persist_docling_document == True`
- `assert "vlm_enrichment" in PIPELINE_NODE_NAMES`
- `idx = PIPELINE_NODE_NAMES.index; assert idx("chunking") < idx("vlm_enrichment") < idx("chunk_enrichment")`
- Env var `RAG_INGESTION_VLM_MODE=external` → `IngestionConfig().vlm_mode == "external"` (requires module reload)

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 1.2: State TypedDicts — New `docling_document` Fields

**Description:** Add a `docling_document: Optional[Any]` field to both pipeline state TypedDicts. Add documentation to `DocumentProcessingState`'s docstring that the `structure` dict will contain a `docling_document_available: bool` key after `structure_detection_node` runs. No existing fields are modified or removed. Use `Optional[Any]` (not `Optional[DoclingDocument]`) to avoid a hard compile-time dependency on `docling-core` in modules that never touch the document object.

**Spec requirements:** FR-2501, FR-2503, FR-2505

**Dependencies:** None (parallel with Task 1.1 — no cross-dependency)

**Source files:**
- MODIFY `src/ingest/doc_processing/state.py`
- MODIFY `src/ingest/embedding/state.py`

---

**Phase 0 contracts (inlined — implement these stubs):**

No function stubs — this task adds TypedDict fields. The exact target additions:

```python
# In src/ingest/doc_processing/state.py — add to imports if not present:
from typing import Any, Optional

# In DocumentProcessingState TypedDict body — append after last existing field:
docling_document: Optional[Any]
"""Native DoclingDocument object from Docling parse. None if Docling
parsing was disabled or failed. Propagated to CleanDocumentStore and
used by Phase 2 HybridChunker path.

The structure dict will contain docling_document_available: bool
set by structure_detection_node after it runs.
"""
```

```python
# In src/ingest/embedding/state.py — add to imports if not present:
from typing import Any, Optional

# In EmbeddingPipelineState TypedDict body — append after last existing field:
docling_document: Optional[Any]
"""Native DoclingDocument object loaded from CleanDocumentStore at
Phase 2 initialization. None if no .docling.json was stored (fallback
path). Read by chunking_node to select HybridChunker vs markdown path.
"""
```

---

**Implementation steps:**

1. [FR-2501] Open `src/ingest/doc_processing/state.py`. Add `from typing import Any, Optional` to imports if not already present. Append `docling_document: Optional[Any]` field to `DocumentProcessingState` with the docstring above.
2. [FR-2505] Add a paragraph to `DocumentProcessingState`'s class-level docstring: "The `structure` dict will contain `docling_document_available: bool` (set by `structure_detection_node`) indicating whether a `DoclingDocument` was successfully obtained."
3. [FR-2503] Open `src/ingest/embedding/state.py`. Add `from typing import Any, Optional` if not present. Append `docling_document: Optional[Any]` field to `EmbeddingPipelineState` with the docstring above.
4. Verify that `total=False` on both TypedDicts means the new field is optional — callers that do not set it (pre-redesign code) continue to work without `KeyError`.
5. Update `@summary` blocks in both files to note the new field.

**Completion criteria:**
- [ ] `DocumentProcessingState(docling_document=None)` succeeds
- [ ] `DocumentProcessingState(docling_document=<mock_object>)` succeeds
- [ ] `EmbeddingPipelineState(docling_document=None)` succeeds
- [ ] Existing nodes that receive a state dict without `docling_document` key continue to function (TypedDict `total=False` — key is optional)
- [ ] `@summary` blocks updated in both files

**Test expectations:**
- `state: DocumentProcessingState = {}; assert state.get("docling_document") is None`
- `state: DocumentProcessingState = {"docling_document": None}; assert state["docling_document"] is None`
- `mock_doc = object(); state: DocumentProcessingState = {"docling_document": mock_doc}; assert state["docling_document"] is mock_doc`
- Same three assertions for `EmbeddingPipelineState`
- Type check: `mypy src/ingest/doc_processing/state.py` passes without new errors

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 2.1: DoclingParseResult — Add `docling_document` Field; Configure Builtin VLM at Parse Time

**Description:** Add a `docling_document: Any` field to `DoclingParseResult` in `src/ingest/support/docling.py`. Update `parse_with_docling` to accept `vlm_mode: str = "disabled"` and configure `DocumentConverter` with `do_picture_description=True` when `vlm_mode="builtin"`. When builtin VLM is enabled, Docling processes figure images during `DocumentConverter.convert()` and bakes VLM-generated figure descriptions into the `DoclingDocument` before it is returned — no post-chunking VLM step is needed for this mode. Update `warmup_docling_models` to accept `with_smolvlm: bool = False`.

**Spec requirements:** FR-2001, FR-2211

**Dependencies:** Task 1.1 (needs `vlm_mode` config field stable before referencing it in callers)

**Source files:**
- MODIFY `src/ingest/support/docling.py`

---

**Phase 0 contracts (inlined — implement these stubs):**

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


def parse_with_docling(
    file_path: str | Path,
    *,
    config: "IngestionConfig",
    vlm_mode: str = "disabled",
) -> DoclingParseResult:
    """Parse a document with Docling and return a normalized result.

    When vlm_mode="builtin", configures DocumentConverter to run SmolVLM
    on figure images during conversion. Figure descriptions are baked into
    the returned DoclingDocument — no post-chunking VLM step is required.

    When vlm_mode="external" or vlm_mode="disabled", do_picture_description
    is False (existing behavior). External VLM enrichment happens post-chunking
    via vlm_enrichment_node.

    Args:
        file_path: Path to the source document.
        config: Ingestion configuration.
        vlm_mode: "builtin" activates Docling's SmolVLM picture description
            at parse time. "external" and "disabled" leave
            do_picture_description=False.

    Returns:
        DoclingParseResult with docling_document populated from result.document.

    Raises:
        RuntimeError: If conversion fails and docling_strict=True.
    """
    raise NotImplementedError("Task 2.1")


def warmup_docling_models(
    *,
    artifacts_path: str = "",
    with_smolvlm: bool = False,
) -> Path:
    """Download and validate core Docling models used by ingestion.

    Args:
        artifacts_path: Optional directory to store downloaded artifacts.
        with_smolvlm: If True, also download SmolVLM model artifacts.
            Must be True when vlm_mode is "builtin".

    Returns:
        Path to the artifacts directory.
    """
    raise NotImplementedError("Task 2.1")
```

---

**Implementation steps:**

1. [FR-2001] Read current `DoclingParseResult` definition in `src/ingest/support/docling.py`. Append `docling_document: Any` field after `parser_model`. Add field docstring.
2. [FR-2001] In the existing `parse_with_docling` function body, after `DocumentConverter.convert()` succeeds, capture `result.document` (the native `DoclingDocument`) into a local variable and assign it to the new `docling_document` field in the returned `DoclingParseResult`.
3. [FR-2211] Update `parse_with_docling` signature to add `vlm_mode: str = "disabled"` as a keyword-only parameter. When `vlm_mode == "builtin"`:
   - Import `from docling.datamodel.pipeline_options import PdfPipelineOptions, PictureDescriptionVlmEngineOptions`
   - Create `pipeline_options = PdfPipelineOptions()`
   - Set `pipeline_options.do_picture_description = True`
   - Set `pipeline_options.picture_description_options = PictureDescriptionVlmEngineOptions.from_preset("smolvlm")`
   - Construct `converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)})`
   - When `vlm_mode != "builtin"`: keep existing `converter = DocumentConverter()` construction (behavior unchanged).
   - Wrap SmolVLM import/setup in try/except: on `ImportError` or exception, log a warning and proceed with `do_picture_description=False` (non-fatal per error taxonomy).
4. [FR-2211] Update `warmup_docling_models` signature to add `with_smolvlm: bool = False` keyword-only parameter. Pass `with_smolvlm=with_smolvlm` to the existing `download_models(...)` call.
5. Update `@summary` block and module-level docstring.

**Completion criteria:**
- [ ] `DoclingParseResult` has `docling_document: Any` field
- [ ] `parse_with_docling(path, config=cfg, vlm_mode="disabled")` returns result where `docling_document` is non-None (is the `result.document` object)
- [ ] `parse_with_docling(path, config=cfg, vlm_mode="builtin")` constructs `DocumentConverter` with `do_picture_description=True` and `from_preset("smolvlm")`
- [ ] `parse_with_docling(path, config=cfg)` (no vlm_mode) behaves identically to pre-redesign
- [ ] `warmup_docling_models(with_smolvlm=False)` does not download SmolVLM artifacts
- [ ] `warmup_docling_models(with_smolvlm=True)` passes `with_smolvlm=True` to `download_models`
- [ ] Existing callers using only `text_markdown`, `has_figures`, `figures`, `headings`, `parser_model` are unaffected

**Test expectations:**
- `result = parse_with_docling(test_pdf, config=cfg, vlm_mode="disabled")`
  - `assert result.docling_document is not None`
  - `assert result.text_markdown` (non-empty)
- `parse_with_docling(path, config=cfg, vlm_mode="builtin")` — verify `DocumentConverter` constructed with `do_picture_description=True` (mock the constructor)
- `parse_with_docling(path, config=cfg)` — `DocumentConverter` constructed without `do_picture_description` (existing behavior)
- `warmup_docling_models()` — `with_smolvlm` defaults to `False`; existing call sites unaffected
- SmolVLM import failure during `vlm_mode="builtin"` → warning logged; parse proceeds without picture descriptions (non-fatal)

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 2.2: structure_detection_node — Propagate DoclingDocument

**Description:** Modify `structure_detection_node` in `src/ingest/doc_processing/nodes/structure_detection.py` to: (1) extract `docling_document` from `DoclingParseResult` and include it in the returned state update, (2) add `docling_document_available` to the `structure` dict, (3) drive routing signals that cause `text_cleaning_node` and `document_refactoring_node` to be skipped for Docling-parsed documents. The `docling_document_available` flag in `structure` is the routing signal; downstream DAG conditional edges read it.

**Spec requirements:** FR-2003, FR-2005 (partial), FR-2011, FR-2013, FR-2505

**Dependencies:** Task 1.2 (state TypedDict must have `docling_document` field), Task 2.1 (`DoclingParseResult.docling_document` must exist)

**Source files:**
- MODIFY `src/ingest/doc_processing/nodes/structure_detection.py`

---

**Phase 0 contracts (inlined — implement these stubs):**

```python
from typing import Any

def structure_detection_node(state: "DocumentProcessingState") -> dict[str, Any]:
    """Detect document structure using Docling or regex fallback.

    On successful Docling parse, returns state update including
    docling_document and structure["docling_document_available"]=True.
    On fallback or disabled Docling, docling_document key is absent
    (or None) and structure["docling_document_available"]=False.

    Args:
        state: Current DocumentProcessingState.

    Returns:
        Partial state update dict. On Docling success:
            {
              "raw_text": str,
              "docling_document": <DoclingDocument>,
              "structure": {
                  "has_figures": bool,
                  "figures": list[str],
                  "heading_count": int,
                  "docling_enabled": bool,
                  "docling_model": str,
                  "docling_document_available": True,  # NEW
              },
              "processing_log": [...],
            }
        On fallback/disabled:
            {
              "raw_text": str,
              # docling_document key absent
              "structure": {
                  "has_figures": bool,
                  "figures": list[str],
                  "heading_count": int,
                  "docling_enabled": bool,
                  "docling_model": str,
                  "docling_document_available": False,  # NEW
              },
              "processing_log": [...],
            }
    """
    raise NotImplementedError("Task 2.2")
```

---

**Implementation steps:**

1. [FR-2003] Read `structure_detection_node` implementation. After a successful `parse_with_docling` call, capture `parsed.docling_document` into a local variable `docling_doc`.
2. [FR-2003] In the return dict for the success path, add `"docling_document": docling_doc` at the top level (alongside `"raw_text"`, `"structure"`, `"processing_log"`).
3. [FR-2505] In the `structure` dict on the success path, add `"docling_document_available": True`.
4. [FR-2505] In the `structure` dict on ALL fallback paths (regex path, Docling disabled, Docling failed non-strict), add `"docling_document_available": False`. Do NOT include `"docling_document"` in the return dict on fallback paths (TypedDict `total=False` means the key is simply absent — callers use `.get("docling_document")`).
5. [FR-2011, FR-2013] Verify that the existing DAG routing in `workflow.py` (or wherever conditional edges are defined) can read `structure["docling_document_available"]` to decide whether to skip `text_cleaning_node` and `document_refactoring_node`. If routing logic does not yet exist, add a conditional edge function that returns `"skip_cleaning"` when `docling_document_available=True`. Document in a code comment that the router reads this flag.
6. Update `@summary` block and function docstring.

**Completion criteria:**
- [ ] Docling enabled + parse success: `returned_update["docling_document"]` is not `None`; `returned_update["structure"]["docling_document_available"] == True`
- [ ] Docling disabled: `"docling_document"` absent from returned update; `structure["docling_document_available"] == False`
- [ ] Docling fails non-strict: fallback to regex; `"docling_document"` absent; `structure["docling_document_available"] == False`
- [ ] No changes to existing `processing_log`, `errors`, `should_skip` behavior
- [ ] `@summary` block updated

**Test expectations:**
- `state = {"config": cfg_docling_enabled, "source_path": str(test_pdf)}`
  - `update = structure_detection_node(state)`
  - `assert update["docling_document"] is not None`
  - `assert update["structure"]["docling_document_available"] == True`
- `state = {"config": cfg_docling_disabled, "source_path": str(test_pdf)}`
  - `update = structure_detection_node(state)`
  - `assert "docling_document" not in update or update.get("docling_document") is None`
  - `assert update["structure"]["docling_document_available"] == False`
- Docling parse raises (mocked), non-strict mode:
  - `update["structure"]["docling_document_available"] == False`
  - `"hybrid_chunker" not in update.get("processing_log", [])`

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 2.3: CleanDocumentStore — `write_docling` / `read_docling`

**Description:** Extend `CleanDocumentStore` in `src/ingest/common/clean_store.py` with two new methods (`write_docling`, `read_docling`), a private helper (`_docling_path`), and update the existing `write` method to accept an optional `docling_document` parameter and the `delete` method to remove `.docling.json`. The `.docling.json` file uses an envelope format with `_schema_version: "docling-native-v1"` for future migration safety. All writes are atomic (tmp-file-then-rename). All failures on `write_docling` or `read_docling` are non-fatal — the system falls back to markdown chunking.

**Spec requirements:** FR-2005, FR-2007, FR-2009, NFR-2911

**Dependencies:** Task 2.1 (supplies the `docling_document` object), Task 2.2 (orchestrator calls `write` with `docling_document` arg after `structure_detection_node` populates it)

**Source files:**
- MODIFY `src/ingest/common/clean_store.py`

---

**Phase 0 contracts (inlined — implement these stubs):**

```python
from pathlib import Path
from typing import Any

class CleanDocumentStore:
    # --- existing methods unchanged (read, exists, clean_hash, list_keys) ---

    def _docling_path(self, source_key: str) -> Path:
        """Return the path for the serialized DoclingDocument JSON file.

        Args:
            source_key: Stable source identity key.

        Returns:
            Path of the form {store_dir}/{safe_key}.docling.json
        """
        raise NotImplementedError("Task 2.3")

    def write_docling(self, source_key: str, docling_document: Any) -> None:
        """Atomically serialize and persist a DoclingDocument.

        Writes to a .tmp file first, then renames into place.
        Wraps in envelope: {"_schema_version": "docling-native-v1", "document": {...}}

        Args:
            source_key: Stable source identity key.
            docling_document: Native DoclingDocument (docling_core Pydantic model).
                Must support .model_dump_json() serialization.

        Raises:
            OSError: If the atomic write fails (tmp write or rename).
            ValueError: If the document cannot be serialized.
        """
        raise NotImplementedError("Task 2.3")

    def read_docling(self, source_key: str) -> Any | None:
        """Deserialize and return a DoclingDocument for the given source key.

        Checks _schema_version == "docling-native-v1" before deserializing.
        On version mismatch: logs warning, returns None.
        Imports DoclingDocument lazily to avoid a hard docling-core import at
        module load time.

        Returns:
            The deserialized DoclingDocument, or None if:
            - The .docling.json file does not exist.
            - The file contains invalid JSON.
            - _schema_version does not match.
            - Deserialization fails.
        Logs a warning on any failure. Never raises.
        """
        raise NotImplementedError("Task 2.3")

    def write(
        self,
        source_key: str,
        text: str,
        meta: dict[str, Any],
        docling_document: Any | None = None,
    ) -> None:
        """Atomically write clean text, metadata, and optional DoclingDocument.

        Existing behavior for text and meta is unchanged (atomic tmp→rename).
        When docling_document is not None, calls write_docling() after the md + meta
        write. write_docling failure is logged but does NOT roll back md/meta writes.

        Args:
            source_key: Stable source identity key.
            text: Clean markdown text.
            meta: Metadata dict to serialize as JSON.
            docling_document: Optional native DoclingDocument.
        """
        raise NotImplementedError("Task 2.3")

    def delete(self, source_key: str) -> None:
        """Remove the clean document entry for this key (all three files).

        Removes {safe_key}.md, {safe_key}.meta.json, and {safe_key}.docling.json.
        Missing files are silently ignored (no FileNotFoundError raised).
        """
        raise NotImplementedError("Task 2.3")
```

Serialization envelope (must use exactly this structure):

```json
{
  "_schema_version": "docling-native-v1",
  "document": { "<DoclingDocument JSON from model_dump_json()>" }
}
```

---

**Implementation steps:**

1. [FR-2005] Add `_docling_path` helper: return `self._dir / f"{self._safe_key(source_key)}.docling.json"`. (Use the same `_safe_key` method used for `.md` and `.meta.json` paths.)
2. [FR-2007] Implement `write_docling`: serialize `docling_document.model_dump_json()` (docling-core Pydantic v2). Wrap in envelope dict `{"_schema_version": "docling-native-v1", "document": <parsed JSON>}`. Write to `<path>.tmp` first, then `os.replace(<tmp>, <path>)` for atomicity. On any exception, clean up the `.tmp` file if it exists, then re-raise as `OSError` or `ValueError` per error taxonomy.
3. [FR-2005, NFR-2911] Implement `read_docling`: open `.docling.json`, parse JSON, check `data["_schema_version"] == "docling-native-v1"`. On mismatch, log warning, return `None`. On match, do lazy import `from docling_core.types.doc import DoclingDocument` and call `DoclingDocument.model_validate(data["document"])`. Wrap entire function in `try/except (FileNotFoundError, json.JSONDecodeError, Exception)` returning `None` with warning log on any failure.
4. [FR-2007] Update `write` method signature to add `docling_document: Any | None = None`. After existing md + meta atomic writes complete, if `docling_document is not None`, call `self.write_docling(source_key, docling_document)` inside `try/except`. On exception: log error (do NOT re-raise; md/meta are already safely written).
5. [FR-2005] Update `delete` method to also call `self._docling_path(source_key).unlink(missing_ok=True)`.
6. [FR-2009] The `persist_docling_document` config flag is enforced at the CALLER level (the orchestrator decides whether to pass `docling_document` to `write()`). The `CleanDocumentStore` itself does not check this flag — it writes whenever `docling_document is not None`.
7. Update `@summary` block and class docstring.

**Completion criteria:**
- [ ] `write_docling` + `read_docling` round-trip: `read_docling` returns an equivalent `DoclingDocument`
- [ ] Atomic write: if `write_docling` is interrupted mid-write (simulated), no `.docling.json` file remains
- [ ] `read_docling` on a missing key returns `None` without raising
- [ ] `read_docling` on corrupt JSON returns `None` and logs a warning
- [ ] `read_docling` on `_schema_version != "docling-native-v1"` returns `None` and logs a warning
- [ ] `delete` removes all three files; missing files do not raise
- [ ] `write(docling_document=None)` is byte-identical to pre-redesign `write` (no third file written)
- [ ] `write_docling` failure inside `write()` does not raise; md/meta files are preserved

**Test expectations:**
- `store.write(key, "# text", {"k": "v"}, docling_document=mock_doc)`
  - `store._docling_path(key).exists() == True`
  - `doc = store.read_docling(key); assert doc is not None`
- `store.write(key, "# text", {"k": "v"}, docling_document=None)`
  - `store._docling_path(key).exists() == False`
- `path = store._docling_path(key); path.write_text("not json")`
  - `assert store.read_docling(key) is None`  # corrupt JSON returns None
- `store.delete(key); assert not store._docling_path(key).exists()`
- Version mismatch: write envelope with `_schema_version: "old-v0"` → `read_docling` returns `None`, warning logged

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 3.1: chunking_node — Dual-Path Logic (HybridChunker + Markdown Fallback)

**Description:** Refactor `chunking_node` in `src/ingest/embedding/nodes/chunking.py` to select between the Docling-native (`HybridChunker`) path and the existing markdown fallback path based solely on the presence of a non-`None` `docling_document` in state. Extract the existing markdown logic into `_chunk_with_markdown`. Add a new `_chunk_with_docling` helper. Apply `_normalize_chunk_text` (NFC + control char removal) to every chunk's text regardless of path. All HybridChunker failures fall back to `_chunk_with_markdown` automatically (non-fatal). The external node signature is unchanged.

**Spec requirements:** FR-2101, FR-2103, FR-2105, FR-2107, FR-2109, FR-2111, FR-2113, FR-2115, FR-2301, FR-2303, FR-2305, FR-2307, FR-2601

**Dependencies:** Task 1.1 (config fields), Task 1.2 (state TypedDict), Task 2.3 (CleanDocumentStore `read_docling` populates `docling_document` in `EmbeddingPipelineState` before this node runs)

**Source files:**
- MODIFY `src/ingest/embedding/nodes/chunking.py`

---

**Phase 0 contracts (inlined — implement these stubs):**

```python
import unicodedata
import re as _re
from typing import Any

# Pure utility — fully implemented (no stub needed):
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


# Pure utility — fully implemented (no stub needed):
def _extract_docling_section_metadata(chunk: Any) -> dict[str, Any]:
    """Extract section_path, heading, heading_level from a HybridChunker chunk.

    HybridChunker chunks expose heading hierarchy via chunk.meta.headings
    (list of heading strings, outermost first).

    Returns:
        {"section_path": str, "heading": str, "heading_level": int}
        section_path = " > ".join(headings)
        heading = headings[-1] or ""
        heading_level = len(headings)
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


def chunking_node(state: "EmbeddingPipelineState") -> dict[str, Any]:
    """Split document into chunks using HybridChunker (Docling path) or
    MarkdownHeaderTextSplitter (fallback path).

    Path selection: if state["docling_document"] is not None → HybridChunker.
    Otherwise → existing markdown path. HybridChunker failures auto-fallback.

    Returns:
        {"chunks": list[ProcessedChunk], "processing_log": updated_log}
    """
    raise NotImplementedError("Task 3.1")


def _chunk_with_docling(
    state: "EmbeddingPipelineState",
    config: "IngestionConfig",
    base_metadata: dict[str, Any],
) -> list["ProcessedChunk"]:
    """Chunk a DoclingDocument using Docling's HybridChunker.

    Args:
        state: state["docling_document"] must be a valid DoclingDocument.
        config: config.hybrid_chunker_max_tokens controls token size limit.
        base_metadata: source, source_uri, source_key, source_id, connector,
            source_version — pre-built by the caller.

    Returns:
        List of ProcessedChunk with section_path, heading, heading_level,
        chunk_index, total_chunks, and all base_metadata keys.

    Raises:
        Any exception from HybridChunker (caller catches and falls back).
    """
    raise NotImplementedError("Task 3.1")


def _chunk_with_markdown(
    state: "EmbeddingPipelineState",
    config: "IngestionConfig",
    base_metadata: dict[str, Any],
) -> list["ProcessedChunk"]:
    """Chunk markdown text using MarkdownHeaderTextSplitter + RecursiveCharacterTextSplitter.

    Behaviorally identical to the pre-redesign chunking_node body (FR-2305).
    Output is byte-identical to pre-redesign except where _normalize_chunk_text
    alters non-NFC sequences or removes control characters.

    Raises:
        Any exception from the markdown splitters (propagates; markdown path
        failure is fatal for this document unlike HybridChunker failure).
    """
    raise NotImplementedError("Task 3.1")
```

---

**Implementation steps:**

1. [FR-2307] In `chunking_node`, read `docling_doc = state.get("docling_document")`. If `docling_doc is not None`, proceed to HybridChunker path. Otherwise go directly to markdown path.
2. [FR-2101, FR-2601] Implement the HybridChunker path as a try/except wrapping `_chunk_with_docling(state, config, base_metadata)`. On any exception: log error with `append_processing_log(state, "hybrid_chunker:error")`, then call `_chunk_with_markdown(state, config, base_metadata)` as fallback, log `chunking:fallback_to_markdown`.
3. [FR-2101, FR-2103] In `_chunk_with_docling`: `from docling.chunking import HybridChunker`. Instantiate `chunker = HybridChunker(max_tokens=config.hybrid_chunker_max_tokens)`. Call `chunk_iter = chunker.chunk(dl_doc=state["docling_document"])`. Convert to list. Iterate with index; for each chunk: call `_extract_docling_section_metadata(chunk)`, call `_normalize_chunk_text(chunk.text)`, build `ProcessedChunk(text=normalized_text, metadata={**base_metadata, **section_meta, "chunk_index": idx, "total_chunks": total})`.
4. [FR-2105] Verify `section_path` in metadata comes from `_extract_docling_section_metadata` (already implemented as pure utility — use it directly).
5. [FR-2305] In `_chunk_with_markdown`: extract the existing body of `chunking_node` verbatim (before this refactor) into this helper. Apply `_normalize_chunk_text` to each chunk's text. Return `list[ProcessedChunk]`.
6. [FR-2015] Apply `_normalize_chunk_text` in both `_chunk_with_docling` and `_chunk_with_markdown` (both paths).
7. [NFR-2909] Log `"hybrid_chunker:ok"` on Docling-native success. Log `"chunking:markdown_fallback"` when markdown path is used directly (no Docling doc in state). Log `"hybrid_chunker:error"` + `"chunking:fallback_to_markdown"` when HybridChunker raises and we fall back.
8. [FR-2111, NFR-2907] Verify all chunks from both paths include all required metadata keys: `source`, `source_uri`, `source_key`, `source_id`, `connector`, `source_version`, `section_path`, `heading`, `heading_level`, `chunk_index`, `total_chunks`.
9. Update `@summary` block and module docstring.

**Completion criteria:**
- [ ] `docling_document=<DoclingDocument>` in state → `HybridChunker` used; chunks have `section_path`; log has `hybrid_chunker:ok`
- [ ] `docling_document=None` in state → markdown path used; log has `chunking:markdown_fallback`
- [ ] `HybridChunker` raises `ValueError` → fallback to markdown; log has `hybrid_chunker:error` and `chunking:fallback_to_markdown`; chunks are non-empty valid `ProcessedChunk` objects
- [ ] All chunks (both paths) pass through `_normalize_chunk_text`
- [ ] All chunks contain all required metadata keys
- [ ] Existing markdown fallback behavior is byte-identical to pre-redesign (except unicode normalization)
- [ ] External `chunking_node` signature unchanged

**Test expectations:**
- `state = {..., "docling_document": mock_docling_doc}`
  - `result = chunking_node(state)`
  - `assert len(result["chunks"]) > 0`
  - `assert all("section_path" in c.metadata for c in result["chunks"])`
  - `assert "hybrid_chunker:ok" in result["processing_log"]`
- `state = {..., "docling_document": None}`
  - `result = chunking_node(state)`
  - `assert "chunking:markdown_fallback" in result["processing_log"]`
- HybridChunker raises (mocked):
  - `assert "hybrid_chunker:error" in result["processing_log"]`
  - `assert "chunking:fallback_to_markdown" in result["processing_log"]`
  - `assert len(result["chunks"]) > 0`
- Unicode normalization: chunk with `"\u0041\u0301"` (A + combining acute) → NFC `"\u00c1"` in output
- All metadata keys present: `assert all(k in c.metadata for k in ["source", "source_uri", "source_key", "source_id", "connector", "source_version", "section_path", "heading", "heading_level", "chunk_index", "total_chunks"] for c in result["chunks"])`

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 3.2: vlm_enrichment_node — New Post-Chunking VLM Node (External Mode Only)

**Description:** Implement a new `vlm_enrichment_node` in a new file `src/ingest/embedding/nodes/vlm_enrichment.py`. This node operates on the chunk list after `chunking_node` and replaces `![...](...)` image placeholders in chunk text with VLM-generated descriptions. **Architectural clarification:** For `vlm_mode="builtin"`, figure descriptions are generated by Docling's SmolVLM at parse time (inside `parse_with_docling`), already embedded in the `DoclingDocument` before chunking — this node is a no-op for that mode. This node only performs work for `vlm_mode="external"`. For `vlm_mode="disabled"`, it is also a no-op. The node never raises — all per-chunk failures are non-fatal.

**Spec requirements:** FR-2201, FR-2203, FR-2205, FR-2207, FR-2209, FR-2211

**Dependencies:** Task 1.1 (`vlm_mode` config field), Task 3.1 (chunking_node produces `chunks` before this node runs). DAG wiring in Task 4.3.

**Source files:**
- CREATE `src/ingest/embedding/nodes/vlm_enrichment.py`

---

**Phase 0 contracts (inlined — implement these stubs):**

```python
# @summary
# Post-chunking VLM image enrichment node for the Embedding Pipeline.
# Exports: vlm_enrichment_node, _find_image_placeholders, _replace_placeholder,
#          _enrich_chunk_external
# Deps: src.ingest.common.types (IngestionConfig), src.ingest.support.vision,
#       src.platform.llm
# @end-summary

import re
from typing import Any

def vlm_enrichment_node(state: "EmbeddingPipelineState") -> dict[str, Any]:
    """Replace image placeholders in chunks with VLM-generated descriptions.

    Mode dispatch:
    - vlm_mode="disabled": immediate no-op, log vlm_enrichment:skipped
    - vlm_mode="builtin": immediate no-op, log vlm_enrichment:skipped
        (descriptions already embedded in DoclingDocument at parse time by SmolVLM)
    - vlm_mode="external": iterate chunks, call _enrich_chunk_external for
        chunks with image placeholders, respect vision_max_figures limit

    Per-chunk failures are non-fatal: original chunk text preserved, warning logged.
    This node never raises — all exceptions are caught internally.

    Args:
        state: Must contain "chunks" (list[ProcessedChunk]) and "config" (IngestionConfig).

    Returns:
        {"chunks": list[ProcessedChunk], "processing_log": updated_log}
    """
    raise NotImplementedError("Task 3.2")


def _find_image_placeholders(chunk_text: str) -> list[re.Match]:
    """Find all image reference placeholders in chunk text.

    Uses the same _IMAGE_REF_PATTERN from src/ingest/support/vision.py
    to detect ![...](...)  patterns.

    Args:
        chunk_text: Text of a single chunk.

    Returns:
        List of re.Match objects for each placeholder found (may be empty).
    """
    raise NotImplementedError("Task 3.2")


def _replace_placeholder(
    chunk_text: str,
    match: re.Match,
    description: str,
) -> str:
    """Replace a single matched image placeholder with the VLM description.

    Only the matched span is replaced. All surrounding text is preserved exactly.

    Args:
        chunk_text: Full chunk text containing the placeholder.
        match: re.Match from _find_image_placeholders identifying the span.
        description: VLM-generated description text.

    Returns:
        Chunk text with the matched placeholder replaced by description.
    """
    raise NotImplementedError("Task 3.2")


def _enrich_chunk_external(
    chunk: "ProcessedChunk",
    config: "IngestionConfig",
    figures_processed_count: int,
) -> tuple["ProcessedChunk", int]:
    """Enrich a single chunk by replacing image placeholders via LiteLLM vision model.

    Respects config.vision_max_figures limit across whole document.
    On VLM API failure after retries: return original chunk, log warning.

    Args:
        chunk: The ProcessedChunk to enrich.
        config: Ingestion configuration (vision_max_figures, vision_timeout_seconds,
            vision_max_tokens, vision_temperature).
        figures_processed_count: Figures already processed in preceding chunks.

    Returns:
        (enriched_chunk_or_original, new_figures_processed_count)
        Returns original chunk unchanged if no placeholders, limit reached, or VLM fails.
    """
    raise NotImplementedError("Task 3.2")
```

---

**Implementation steps:**

1. [FR-2201, FR-2203] In `vlm_enrichment_node`: read `config = state["config"]`. If `config.vlm_mode != "external"`, append `vlm_enrichment:skipped` to processing log and return `{"chunks": state["chunks"], "processing_log": ...}` immediately (no-op for both `"disabled"` and `"builtin"`).
2. [FR-2205] Implement `_find_image_placeholders`: import `_IMAGE_REF_PATTERN` from `src.ingest.support.vision` (or define the same pattern locally: `re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")`). Return `list(pattern.finditer(chunk_text))`.
3. [FR-2205] Implement `_replace_placeholder`: use `chunk_text[:match.start()] + description + chunk_text[match.end():]` to replace only the matched span.
4. [FR-2207, FR-2209] Implement `_enrich_chunk_external`: check `figures_processed_count >= config.vision_max_figures` → return `(chunk, figures_processed_count)` immediately (limit reached). Find placeholders via `_find_image_placeholders`. For each placeholder (up to `vision_max_figures` remaining budget): call the existing vision infrastructure from `src.ingest.support.vision` (e.g., `generate_vision_notes` or `_call_vision_model`) to get description. On success: apply `_replace_placeholder`. On any exception: log warning with chunk index and error detail; leave placeholder unchanged. Return `(modified_chunk, updated_count)`.
5. [FR-2201] In `vlm_enrichment_node` external path: iterate over `state["chunks"]`. Track `figures_processed_count = 0` across all chunks. For each chunk: call `_enrich_chunk_external(chunk, config, figures_processed_count)`. Update count. Accumulate results. Return `{"chunks": result_chunks, "processing_log": ..., with vlm_enrichment:external:ok}`.
6. [FR-2207] Wrap the entire iteration in try/except to ensure the node never raises. On unexpected exception: log error, return original chunks unchanged.
7. Add `@summary` block and module-level docstring to the new file.

**Completion criteria:**
- [ ] `vlm_mode="disabled"`: node returns immediately; `chunks` unchanged; log has `vlm_enrichment:skipped`
- [ ] `vlm_mode="builtin"`: node returns immediately; `chunks` unchanged; log has `vlm_enrichment:skipped`
- [ ] `vlm_mode="external"` + chunk with `![Figure 1](img.png)`: placeholder replaced with VLM description; surrounding text unchanged
- [ ] `vlm_mode="external"` + VLM API error: chunk retains original placeholder; log has warning; other chunks processed normally
- [ ] `vlm_mode="external"` + 20 figures + `vision_max_figures=4`: only first 4 processed
- [ ] Node is a no-op when no chunks contain image placeholder patterns
- [ ] Node never raises (all exceptions caught internally)
- [ ] `@summary` block at top of new file

**Test expectations:**
- `state = {..."chunks": [], "config": cfg_vlm_disabled}`
  - `result = vlm_enrichment_node(state); assert result["chunks"] == []`
  - `assert "vlm_enrichment:skipped" in result["processing_log"]`
- `state = {..., "config": cfg_vlm_builtin, "chunks": [chunk_with_placeholder]}`
  - `result = vlm_enrichment_node(state)`
  - `assert result["chunks"][0].text == chunk_with_placeholder.text`  # unchanged
- `state = {..., "config": cfg_vlm_external, "chunks": [chunk_with_placeholder]}`
  - Mock LiteLLM vision model to return "Block diagram showing data flow"
  - `result = vlm_enrichment_node(state)`
  - `assert "Block diagram" in result["chunks"][0].text`
  - `assert "![Figure 1](img.png)" not in result["chunks"][0].text`
- Vision API raises → chunk text unchanged; no exception propagated
- `vision_max_figures=4` + 6 chunks each with 1 placeholder → exactly 4 API calls made

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 4.2: IngestionDesignCheck — New Validation Rules

**Description:** Add three new validation rules to the design-check phase in the ingestion pipeline startup (in `src/ingest/pipeline/impl.py` or wherever `IngestionDesignCheck` is populated). Implement as a new private function `_check_docling_chunking_config(config) -> tuple[list[str], list[str]]` returning `(errors, warnings)`. Call this function from the existing startup validation path and add its results to `IngestionDesignCheck`. This is an additive change — no existing checks are modified.

**Spec requirements:** FR-2409, NFR-2903

**Dependencies:** Task 1.1 (config fields `vlm_mode` and `hybrid_chunker_max_tokens` must exist)

**Source files:**
- MODIFY `src/ingest/pipeline/impl.py` (or the file that builds `IngestionDesignCheck`)

---

**Phase 0 contracts (inlined — implement these stubs):**

```python
def _check_docling_chunking_config(
    config: "IngestionConfig",
) -> tuple[list[str], list[str]]:
    """Validate Docling-native chunking configuration.

    Checks three contradiction patterns:
    1. vlm_mode=builtin without docling installed → fatal error
    2. vlm_mode=external without LiteLLM vision model configured → warning
    3. hybrid_chunker_max_tokens > 512 (bge-m3 limit) → warning

    Args:
        config: IngestionConfig to validate.

    Returns:
        Tuple of (errors, warnings). Errors block pipeline start.
        Warnings are logged but do not halt processing.
    """
    raise NotImplementedError("Task 4.2")
```

---

**Implementation steps:**

1. [FR-2409] Implement Rule A in `_check_docling_chunking_config`: `if config.vlm_mode == "builtin"`: attempt `from docling.document_converter import DocumentConverter` inside `try/except ImportError`. On `ImportError`: append error `"vlm_mode=builtin requires docling to be installed (uv add docling)"` to `errors`.
2. [FR-2409] Implement Rule B: `if config.vlm_mode == "external"` and `not config.vision_model` and no `LLM_ROUTER_CONFIG` available: append warning `"vlm_mode=external is set but no vision model is configured; VLM enrichment will be skipped at runtime"` to `warnings`. (Check the existing pattern for how `vision_model` and router config are validated — reuse the same pattern.)
3. [FR-2409] Implement Rule C: `if config.hybrid_chunker_max_tokens > 512`: append warning `f"hybrid_chunker_max_tokens ({config.hybrid_chunker_max_tokens}) exceeds bge-m3 maximum input (512); chunks may be silently truncated during embedding"`.
4. [FR-2409] Locate the existing startup validation path (the function or code block that builds `IngestionDesignCheck`). Call `_check_docling_chunking_config(config)` and extend `design_check.errors` and `design_check.warnings` with the returned lists.
5. [NFR-2903] Verify `config.vlm_mode == "disabled"` → no errors, no warnings from these rules.
6. Update `@summary` block.

**Completion criteria:**
- [ ] `vlm_mode="builtin"` + docling not installed → error in `IngestionDesignCheck.errors`
- [ ] `vlm_mode="external"` + no vision model → warning in `IngestionDesignCheck.warnings`
- [ ] `hybrid_chunker_max_tokens=1024` → warning with exact value interpolated
- [ ] `vlm_mode="disabled"` → no errors, no warnings from these rules
- [ ] Existing validation rules unchanged

**Test expectations:**
- `cfg = IngestionConfig(vlm_mode="builtin"); errors, warnings = _check_docling_chunking_config(cfg)`
  - Mock `from docling.document_converter import DocumentConverter` to raise `ImportError`
  - `assert len(errors) == 1; assert "uv add docling" in errors[0]`
- `cfg = IngestionConfig(vlm_mode="external", vision_model=""); errors, warnings = _check_docling_chunking_config(cfg)`
  - `assert len(warnings) >= 1; assert "no vision model" in warnings[0]`
- `cfg = IngestionConfig(hybrid_chunker_max_tokens=1024); errors, warnings = _check_docling_chunking_config(cfg)`
  - `assert any("1024" in w for w in warnings)`
- `cfg = IngestionConfig(vlm_mode="disabled"); errors, warnings = _check_docling_chunking_config(cfg)`
  - `assert errors == []; assert not any("hybrid_chunker" in w for w in warnings)`

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 4.3: Embedding DAG — Wire vlm_enrichment_node

**Description:** Wire the new `vlm_enrichment_node` into the Embedding Pipeline LangGraph DAG so it runs after `chunking_node` and before the next downstream node (typically `chunk_enrichment_node` or equivalent). The node handles all mode dispatch internally — no conditional edge is needed. The node always sits in the graph but short-circuits when `vlm_mode` is not `"external"`. Also update `PIPELINE_NODE_NAMES` in `src/ingest/common/types.py` to include `"vlm_enrichment"` (if not already done by Task 1.1).

**Spec requirements:** FR-2201 (external VLM must occur post-chunking), NFR-2909

**Dependencies:** Task 3.2 (`vlm_enrichment_node` implementation must exist), Task 1.1 (`PIPELINE_NODE_NAMES` update)

**Source files:**
- MODIFY `src/ingest/embedding/pipeline/workflow.py` (or equivalent DAG definition file — locate via the existing `chunking_node` registration)

---

**Phase 0 contracts (inlined — implement these stubs):**

No function stubs — this task modifies DAG wiring. The target state:

```python
# In the Embedding Pipeline DAG builder (workflow.py or equivalent):
from src.ingest.embedding.nodes.vlm_enrichment import vlm_enrichment_node

# Registration (exact API depends on whether StateGraph or equivalent is used):
graph.add_node("vlm_enrichment", vlm_enrichment_node)

# Edge from chunking_node to vlm_enrichment_node:
graph.add_edge("chunking", "vlm_enrichment")

# Edge from vlm_enrichment_node to the next downstream node:
graph.add_edge("vlm_enrichment", "chunk_enrichment")
# (Remove the pre-existing direct edge from "chunking" to "chunk_enrichment")
```

---

**Implementation steps:**

1. [FR-2201] Read the Embedding Pipeline DAG definition file (locate it by finding `chunking_node` registration). Identify the existing edge `"chunking" → <next_node>`.
2. [FR-2201] Add import: `from src.ingest.embedding.nodes.vlm_enrichment import vlm_enrichment_node`.
3. [FR-2201] Register the new node: `graph.add_node("vlm_enrichment", vlm_enrichment_node)`.
4. [FR-2201] Replace the existing `"chunking" → <next_node>` edge with two edges: `"chunking" → "vlm_enrichment"` and `"vlm_enrichment" → <next_node>`.
5. [NFR-2909] Verify that `PIPELINE_NODE_NAMES` already contains `"vlm_enrichment"` (Task 1.1 sets this). If not, add it here as a fallback.
6. Compile the graph (`graph.compile()`) and verify it produces no errors. Add a compilation smoke test.
7. Update `@summary` block in the workflow file.

**Completion criteria:**
- [ ] DAG compiles without errors after wiring
- [ ] `"vlm_enrichment"` node appears between `"chunking"` and `"chunk_enrichment"` in graph topology
- [ ] A synthetic pipeline run with `vlm_mode="disabled"` passes through `vlm_enrichment_node` without modifying chunks (log entry `vlm_enrichment:skipped` present)
- [ ] No conditional edge required in the DAG — the node handles skip logic internally

**Test expectations:**
- DAG compilation: `graph = build_embedding_graph(); assert graph is not None` (no compile error)
- Topology check: inspect graph edges to verify `"chunking" → "vlm_enrichment" → "chunk_enrichment"` (or equivalent next node) exists
- Synthetic run `vlm_mode="disabled"`: `"vlm_enrichment:skipped" in processing_log`
- Pre-existing DAG runs (integration tests that test the full embedding pipeline) still pass

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Module Boundary Map

| Task | Source File | Action | Notes |
|------|------------|--------|-------|
| Task 4.1 | `config/settings.py` | MODIFY | Add 3 env var constants |
| Task 1.1 | `src/ingest/common/types.py` | MODIFY | Add 3 `IngestionConfig` fields; update `PIPELINE_NODE_NAMES` |
| Task 1.2 | `src/ingest/doc_processing/state.py` | MODIFY | Add `docling_document: Optional[Any]` field |
| Task 1.2 | `src/ingest/embedding/state.py` | MODIFY | Add `docling_document: Optional[Any]` field |
| Task 2.1 | `src/ingest/support/docling.py` | MODIFY | Add `docling_document` field to `DoclingParseResult`; update `parse_with_docling` and `warmup_docling_models` signatures |
| Task 2.2 | `src/ingest/doc_processing/nodes/structure_detection.py` | MODIFY | Propagate `docling_document`; add `docling_document_available` to `structure` dict |
| Task 2.3 | `src/ingest/common/clean_store.py` | MODIFY | Add `_docling_path`, `write_docling`, `read_docling`; update `write` and `delete` |
| Task 3.1 | `src/ingest/embedding/nodes/chunking.py` | MODIFY | Add dual-path logic; add `_chunk_with_docling`, `_chunk_with_markdown`, `_normalize_chunk_text`, `_extract_docling_section_metadata` helpers |
| Task 3.2 | `src/ingest/embedding/nodes/vlm_enrichment.py` | CREATE | New post-chunking VLM enrichment node (external mode only) |
| Task 4.2 | `src/ingest/pipeline/impl.py` | MODIFY | Add `_check_docling_chunking_config`; wire into startup validation |
| Task 4.3 | `src/ingest/embedding/pipeline/workflow.py` | MODIFY | Wire `vlm_enrichment_node` between `chunking` and `chunk_enrichment` |

---

## Dependency Graph

```
Wave 0 (no prerequisites):
  Task 4.1 (config/settings.py env vars)
      │
      ▼
Wave 1 (requires Wave 0):
  ┌───────────────────────┐
  Task 1.1                Task 1.2
  (IngestionConfig fields) (State TypedDicts)
  │         │              │
  │         │              │
  ▼         └──────┬───────┘
Wave 2 (requires Tasks 1.1 + 1.2):
  ┌──────────────────────────┐
  Task 2.1                   Task 2.2
  (DoclingParseResult;       (structure_detection_node
   parse_with_docling;        propagates docling_document
   warmup_docling_models)     + docling_document_available)
  │                           │
  └──────────┬────────────────┘
             │
             ▼
Wave 3 (requires Tasks 2.1 + 2.2):
  Task 2.3
  (CleanDocumentStore write_docling / read_docling)
  │               │
  │               │
  ▼               ▼
Wave 4 (Task 3.1 requires 2.3; Task 3.2 requires only 1.1):
  Task 3.1              Task 3.2
  (chunking_node        (vlm_enrichment_node
   dual-path logic)      new file, external mode only)
  │                      │
  │         Task 4.2     │
  │         (DesignCheck  │
  │          rules; req   │
  │          Task 1.1)    │
  └──────────┬────────────┘
             │
             ▼
Wave 5 (requires Tasks 3.2 + 1.1):
  Task 4.3
  (Embedding DAG wiring: insert vlm_enrichment_node
   between chunking and chunk_enrichment)
```

**Valid DAG — no cycles confirmed.** Parallel execution opportunities:
- Wave 1: Tasks 1.1 and 1.2 run in parallel
- Wave 2: Tasks 2.1 and 2.2 run in parallel
- Wave 4: Tasks 3.1 and 3.2 run in parallel; Task 4.2 runs in parallel with both

---

## Task-to-FR Traceability Table

| FR / NFR | Priority | Task | Source File |
|---|---|---|---|
| FR-2001 | MUST | Task 2.1 | `src/ingest/support/docling.py` |
| FR-2003 | MUST | Task 2.2 | `src/ingest/doc_processing/nodes/structure_detection.py` |
| FR-2005 | MUST | Task 2.3 | `src/ingest/common/clean_store.py` |
| FR-2007 | MUST | Task 2.3 | `src/ingest/common/clean_store.py` |
| FR-2009 | SHOULD | Task 2.3 | `src/ingest/common/clean_store.py` (enforced at caller level) |
| FR-2011 | MUST | Task 2.2 | `src/ingest/doc_processing/nodes/structure_detection.py` |
| FR-2013 | MUST | Task 2.2 | `src/ingest/doc_processing/nodes/structure_detection.py` |
| FR-2015 | MUST | Task 3.1 | `src/ingest/embedding/nodes/chunking.py` |
| FR-2101 | MUST | Task 3.1 | `src/ingest/embedding/nodes/chunking.py` |
| FR-2103 | MUST | Task 3.1 | `src/ingest/embedding/nodes/chunking.py` |
| FR-2105 | MUST | Task 3.1 | `src/ingest/embedding/nodes/chunking.py` |
| FR-2107 | MUST | Task 3.1 | `src/ingest/embedding/nodes/chunking.py` (via HybridChunker native behavior) |
| FR-2109 | MUST | Task 3.1 | `src/ingest/embedding/nodes/chunking.py` (via HybridChunker + semchunk) |
| FR-2111 | MUST | Task 3.1 | `src/ingest/embedding/nodes/chunking.py` |
| FR-2113 | SHOULD | Task 3.1 | `src/ingest/embedding/nodes/chunking.py` (via HybridChunker native behavior) |
| FR-2115 | SHOULD | Task 3.1 | `src/ingest/embedding/nodes/chunking.py` (via HybridChunker native behavior) |
| FR-2201 | MUST | Task 3.2, Task 4.3 | `src/ingest/embedding/nodes/vlm_enrichment.py`, `workflow.py` |
| FR-2203 | MUST | Task 3.2 | `src/ingest/embedding/nodes/vlm_enrichment.py` |
| FR-2205 | MUST | Task 3.2 | `src/ingest/embedding/nodes/vlm_enrichment.py` |
| FR-2207 | MUST | Task 3.2 | `src/ingest/embedding/nodes/vlm_enrichment.py` |
| FR-2209 | SHOULD | Task 3.2 | `src/ingest/embedding/nodes/vlm_enrichment.py` |
| FR-2211 | SHOULD | Task 2.1 | `src/ingest/support/docling.py` |
| FR-2301 | MUST | Task 3.1 | `src/ingest/embedding/nodes/chunking.py` |
| FR-2303 | MUST | Task 2.2 | `src/ingest/doc_processing/nodes/structure_detection.py` |
| FR-2305 | MUST | Task 3.1 | `src/ingest/embedding/nodes/chunking.py` |
| FR-2307 | MUST | Task 3.1 | `src/ingest/embedding/nodes/chunking.py` |
| FR-2401 | MUST | Task 1.1 | `src/ingest/common/types.py` |
| FR-2403 | MUST | Task 1.1 | `src/ingest/common/types.py` |
| FR-2405 | MUST | Task 4.1, Task 1.1 | `config/settings.py`, `src/ingest/common/types.py` |
| FR-2407 | MUST | Task 1.1 | `src/ingest/common/types.py` |
| FR-2409 | SHOULD | Task 4.2 | `src/ingest/pipeline/impl.py` |
| FR-2501 | MUST | Task 1.2 | `src/ingest/doc_processing/state.py` |
| FR-2503 | MUST | Task 1.2 | `src/ingest/embedding/state.py` |
| FR-2505 | MUST | Task 1.2, Task 2.2 | `src/ingest/doc_processing/state.py`, `src/ingest/doc_processing/nodes/structure_detection.py` |
| FR-2601 | MUST | Task 3.1 | `src/ingest/embedding/nodes/chunking.py` |
| FR-2603 | MUST | Task 2.3 | `src/ingest/common/clean_store.py` |
| NFR-2901 | SHOULD | Task 3.1, Task 2.3 | Performance targets; no code gate — verified by benchmarks |
| NFR-2903 | MUST | Task 1.1, Task 4.1 | Backward-compat defaults in `IngestionConfig` and `settings.py` |
| NFR-2905 | MUST | Task 4.1 | `config/settings.py` |
| NFR-2907 | MUST | Task 3.1 | `src/ingest/embedding/nodes/chunking.py` (ProcessedChunk contract) |
| NFR-2909 | SHOULD | Task 3.1, Task 3.2, Task 4.3 | Processing log entries in chunking and VLM nodes |
| NFR-2911 | SHOULD | Task 2.3 | `src/ingest/common/clean_store.py` (`_schema_version` envelope) |
| NFR-2913 | MAY | Task 3.2 | `src/ingest/embedding/nodes/vlm_enrichment.py` (optional parallel VLM) |

**Total FRs covered: 43** (33 MUST, 9 SHOULD, 1 MAY) — matches spec count.
**No orphan tasks** — every task traces to at least one FR.
