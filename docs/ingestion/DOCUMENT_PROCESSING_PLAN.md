# Document Processing Pipeline — Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Document Processing Pipeline (FR-101 through FR-587) as a LangGraph StateGraph DAG that transforms source documents into clean Markdown persisted to the Clean Document Store.

**Architecture:** Five-node LangGraph StateGraph DAG processing one document at a time. Nodes are plain functions (`def node_name(state: DocumentProcessingState) -> dict`) sharing a single `DocumentProcessingState` TypedDict. Two conditional routing points: post-structure-detection (multimodal if figures detected + enabled) and post-cleaning (refactoring if enabled). The Clean Document Store (`{source_key}.md` + `{source_key}.meta.json`) is the persistent storage boundary between this pipeline and the downstream Embedding Pipeline.

**Tech Stack:** Python 3.11+, LangGraph (`StateGraph`), `dataclasses` (frozen), `TypedDict`, SHA-256 hashing, `argparse`/`click` CLI, `pytest`.

---

## File Structure

```
src/ingest/
├── pipeline_types.py              # DocumentProcessingState, PipelineConfig, CleanDocumentMetadata, exceptions
├── pipeline_shared.py             # generate_source_key, compute_source_hash, compute_clean_hash
├── pipeline_workflow.py           # build_document_processing_graph(), routing functions
├── clean_store.py                 # CleanDocumentStore class (atomic write/read)
├── config_loader.py               # Config loading, merging, validation
├── exceptions.py                  # Pipeline-specific exception types
├── nodes/
│   ├── document_ingestion.py      # Node 1: format detection, extraction, hashing
│   ├── structure_detection.py     # Node 2: section tree, tables, figures, confidence
│   ├── multimodal_processing.py   # Node 3: VLM figure descriptions (optional)
│   ├── text_cleaning.py           # Node 4: whitespace, boilerplate, integration
│   └── document_refactoring.py    # Node 5: self-contained paragraphs (optional)
├── pipeline/
│   └── __init__.py                # Public API facade
└── ingest.py                      # CLI entry point

tests/ingest/
├── test_pipeline_config.py        # Task A-1.1
├── test_dag_skeleton.py           # Task A-1.2
├── test_document_ingestion.py     # Task A-1.3
├── test_structure_detection.py    # Task A-1.4
├── test_text_cleaning.py          # Task A-1.5
├── test_cli.py                    # Task A-1.11
├── test_clean_store.py            # Task A-S.1
├── test_document_refactoring.py   # Task A-2.3
├── test_multimodal_processing.py  # Task A-3.1
└── test_pptx_xlsx_extractors.py   # Task A-3.5
```

---

## Phase 0 — Contract Definitions

**Purpose:** Define all TypedDicts, dataclasses, function signatures, and exception types BEFORE any tests or implementation. This is the shared contract that both test and implementation agents work against. No business logic is implemented in this phase — only type definitions, signatures, and `raise NotImplementedError` stubs.

**Review gate:** Phase 0 output must be human-reviewed and approved before Phase A begins. Any contract change after approval requires re-review.

---

### Task 0.1 — State and Config Contracts

**Files:**
- Create: `src/ingest/pipeline_types.py`

- [ ] Step 1: Define `DocumentProcessingState` TypedDict with ALL fields:

```python
# src/ingest/pipeline_types.py

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict


class DocumentProcessingState(TypedDict, total=False):
    """Shared state flowing through every node in the Document Processing DAG.

    Each node reads from upstream-populated fields and writes only to its own
    designated output fields. The TypedDict is NOT a class — nodes return plain
    dicts that are merged by LangGraph.
    """

    # Populated by config loader and passed on the initial call
    config: PipelineConfig

    # Populated by Node 1 — Document Ingestion
    source_path: str                          # Absolute path to source file
    source_key: str                           # Deterministic identity: SHA-256(path)[:24] (FR-107)
    source_hash: str                          # SHA-256 of source file bytes (FR-106)
    format: str                               # Detected document format, e.g. "pdf", "docx" (FR-102)
    raw_text: str                             # Format-converted plain text (FR-103)
    domain_vocabulary: dict[str, str]         # Abbreviation dictionary loaded at startup (FR-109)

    # Populated by Node 2 — Structure Detection
    section_tree: dict[str, Any]              # Hierarchical section structure (FR-201)
    tables: list[dict[str, Any]]             # Extracted tables with markdown (FR-202)
    figures: list[dict[str, Any]]            # Figures with bounding boxes + captions (FR-203)
    has_figures: bool                          # True if any figures detected
    extraction_confidence: float              # 0.0–1.0 quality score (FR-206)
    requires_manual_review: bool              # Set when confidence < threshold (FR-207)

    # Populated by Node 3 — Multimodal Processing (optional)
    figure_descriptions: list[dict[str, Any]]  # VLM descriptions per figure (FR-301)

    # Populated by Node 4 — Text Cleaning
    cleaned_text: str                          # Whitespace-normalised, boilerplate-free, figures integrated

    # Populated by Node 5 — Document Refactoring (optional)
    refactored_text: str                       # Self-contained paragraph version (FR-501)

    # Cross-cutting
    errors: list[dict[str, Any]]              # Stage errors: {"stage": str, "error": str, "timestamp": str}
    timings: dict[str, float]                 # Per-node wall-clock durations: {"node_name": seconds}
```

- [ ] Step 2: Define `PipelineConfig` frozen dataclass:

```python
@dataclass(frozen=True)
class PipelineConfig:
    """Master configuration for a Document Processing Pipeline run.

    Controls stage enablement, provider selection, thresholds, and runtime
    overrides. Validated at startup — contradictory settings produce a startup
    error before any documents are processed.
    """

    clean_docs_dir: Path = field(default_factory=lambda: Path("data/clean_docs"))
    enable_multimodal: bool = False
    enable_refactoring: bool = False
    structure_detection_provider: str = "docling"
    vlm_provider: str = "openai"
    domain_vocabulary_path: Path | None = None
    boilerplate_patterns: list[str] = field(default_factory=list)
    confidence_threshold: float = 0.5
    max_refactoring_iterations: int = 3
    llm_provider: str | None = None
```

- [ ] Step 3: Define `CleanDocumentMetadata` frozen dataclass:

```python
@dataclass(frozen=True)
class CleanDocumentMetadata:
    """Metadata envelope written alongside each clean Markdown file (FR-583).

    Serialized to {source_key}.meta.json in the Clean Document Store.
    """

    source_key: str                            # Deterministic ID from source path
    source_path: str                           # Original source file path
    source_hash: str                           # SHA-256 of source file — change detection key
    clean_hash: str                            # SHA-256 of clean Markdown — Embedding Pipeline change key
    processing_timestamp: str                  # ISO 8601 timestamp
    extraction_confidence: float               # 0.0–1.0 from Structure Detection
    review_tier: str                           # "Fully Reviewed" | "Partially Reviewed" | "Self Reviewed"
    section_tree_depth: int                    # Max depth of section tree hierarchy
    table_count: int                           # Number of tables extracted
    has_figures: bool                          # Whether figures were detected
    figure_count: int                          # Number of figures extracted
    processing_flags: dict[str, bool] = field( # Runtime flags for this processing run
        default_factory=lambda: {
            "multimodal_enabled": False,
            "refactoring_enabled": False,
        }
    )
```

---

### Task 0.2 — Exception Types

**Files:**
- Create: `src/ingest/exceptions.py`

- [ ] Step 1: Define all exception classes:

```python
# src/ingest/exceptions.py

"""Pipeline-specific exception types for the Document Processing Pipeline.

All exceptions inherit from DocumentProcessingError to enable catch-all
handling at the pipeline orchestration layer while preserving specific
error types for node-level handling.
"""


class DocumentProcessingError(Exception):
    """Base exception for all Document Processing Pipeline errors."""


class ConfigValidationError(DocumentProcessingError):
    """Raised when pipeline configuration contains contradictory or invalid settings.

    Examples: refactoring enabled with no LLM provider, unknown provider name,
    invalid confidence threshold range.
    """


class FormatDetectionError(DocumentProcessingError):
    """Raised when document format cannot be determined from file extension (FR-102)."""


class ExtractionError(DocumentProcessingError):
    """Raised when format-specific text extraction fails (FR-103).

    Includes the format that was detected and the underlying cause.
    """

    def __init__(self, message: str, format: str, cause: Exception | None = None):
        super().__init__(message)
        self.format = format
        self.cause = cause


class EncodingFallbackError(DocumentProcessingError):
    """Raised when all encoding fallback attempts fail (FR-108).

    Should not normally occur since the final fallback uses UTF-8 with
    replacement characters, but is defined for defensive completeness.
    """


class StructureDetectionError(DocumentProcessingError):
    """Raised when structure detection fails for a document (FR-201–FR-208)."""


class VLMProcessingError(DocumentProcessingError):
    """Raised when VLM figure description fails (FR-307).

    Per spec, this is non-fatal: the figure is recorded without a description.
    """

    def __init__(self, message: str, figure_id: str, cause: Exception | None = None):
        super().__init__(message)
        self.figure_id = figure_id
        self.cause = cause


class RefactoringValidationError(DocumentProcessingError):
    """Raised when a refactoring iteration fails fact-check or completeness validation.

    This is an internal control-flow exception used within the self-correcting
    loop — it does not escape the node. After max_iterations, the fail-safe
    fallback returns the original text (FR-507).
    """


class CleanStoreWriteError(DocumentProcessingError):
    """Raised when atomic write to the Clean Document Store fails (FR-586)."""
```

---

### Task 0.3 — Node Function Signatures (Stubs)

**Files:**
- Create: `src/ingest/nodes/document_ingestion.py` (stub)
- Create: `src/ingest/nodes/structure_detection.py` (stub)
- Create: `src/ingest/nodes/multimodal_processing.py` (stub)
- Create: `src/ingest/nodes/text_cleaning.py` (stub)
- Create: `src/ingest/nodes/document_refactoring.py` (stub)
- Create: `src/ingest/clean_store.py` (stub)

- [ ] Step 1: Create stub for Node 1 — Document Ingestion:

```python
# src/ingest/nodes/document_ingestion.py

"""Node 1: Document Ingestion.

Accepts a file path, detects document format from extension, converts the
file to raw text using format-specific extractors, computes SHA-256 content
hash, generates deterministic source_key, and applies encoding fallback chain.

Requirements: FR-101, FR-102, FR-103, FR-106, FR-107, FR-108, FR-109,
              FR-110, FR-111, FR-112, FR-113
"""

from src.ingest.pipeline_types import DocumentProcessingState


def document_ingestion_node(state: DocumentProcessingState) -> dict:
    """Ingest a source document: detect format, extract text, compute hashes.

    Args:
        state: Pipeline state containing at minimum 'config' and 'source_path'.

    Returns:
        Dict with keys: source_key, source_hash, format, raw_text,
        domain_vocabulary, errors, timings.

    Raises:
        FormatDetectionError: If format cannot be determined.
        ExtractionError: If text extraction fails for the detected format.
    """
    raise NotImplementedError("Task B-1.3")
```

- [ ] Step 2: Create stub for Node 2 — Structure Detection:

```python
# src/ingest/nodes/structure_detection.py

"""Node 2: Structure Detection.

Parses raw text into a hierarchical section tree, extracts tables and figures
with metadata, computes extraction confidence score, and auto-detects
abbreviation definitions for merging with domain vocabulary.

Requirements: FR-201, FR-202, FR-203, FR-204, FR-205, FR-206, FR-207, FR-208
"""

from src.ingest.pipeline_types import DocumentProcessingState


def structure_detection_node(state: DocumentProcessingState) -> dict:
    """Detect document structure: section tree, tables, figures, confidence.

    Args:
        state: Pipeline state containing 'raw_text', 'config', 'domain_vocabulary'.

    Returns:
        Dict with keys: section_tree, tables, figures, has_figures,
        extraction_confidence, requires_manual_review, domain_vocabulary
        (updated with auto-detected abbreviations), errors, timings.
    """
    raise NotImplementedError("Task B-1.4")
```

- [ ] Step 3: Create stub for Node 3 — Multimodal Processing:

```python
# src/ingest/nodes/multimodal_processing.py

"""Node 3: Multimodal Processing (optional).

Uses a Vision-Language Model to generate text descriptions of figures detected
in Node 2. Only executes when figures were detected and multimodal is enabled.
VLM provider is swappable via configuration. Per-figure failures are non-fatal.

Requirements: FR-301, FR-302, FR-303, FR-304, FR-305, FR-306, FR-307
"""

from src.ingest.pipeline_types import DocumentProcessingState


def multimodal_processing_node(state: DocumentProcessingState) -> dict:
    """Generate VLM text descriptions for detected figures.

    Args:
        state: Pipeline state containing 'figures', 'config'.

    Returns:
        Dict with keys: figure_descriptions, errors, timings.
    """
    raise NotImplementedError("Task B-3.1")
```

- [ ] Step 4: Create stub for Node 4 — Text Cleaning:

```python
# src/ingest/nodes/text_cleaning.py

"""Node 4: Text Cleaning.

Normalises whitespace, removes boilerplate using configurable patterns,
reduces repeated headers/footers, and integrates VLM-generated figure
descriptions and table Markdown representations at their original positions.

Requirements: FR-401, FR-402, FR-403, FR-404, FR-405
"""

from src.ingest.pipeline_types import DocumentProcessingState


def text_cleaning_node(state: DocumentProcessingState) -> dict:
    """Clean extracted text: normalise, remove boilerplate, integrate figures/tables.

    Args:
        state: Pipeline state containing 'raw_text', 'config',
               'figure_descriptions' (optional), 'tables'.

    Returns:
        Dict with keys: cleaned_text, errors, timings.
    """
    raise NotImplementedError("Task B-1.5")
```

- [ ] Step 5: Create stub for Node 5 — Document Refactoring:

```python
# src/ingest/nodes/document_refactoring.py

"""Node 5: Document Refactoring (optional).

Uses an LLM to restructure document paragraphs into self-contained units by
resolving implicit references. Uses a self-correcting bounded iteration loop
with fact-check and completeness validation. Falls back to original text if
all iterations fail.

Requirements: FR-501, FR-502, FR-503, FR-504, FR-505, FR-506, FR-507,
              FR-508, FR-509, FR-510, FR-511
"""

from src.ingest.pipeline_types import DocumentProcessingState


def document_refactoring_node(state: DocumentProcessingState) -> dict:
    """Refactor document paragraphs into self-contained units.

    Args:
        state: Pipeline state containing 'cleaned_text', 'config',
               'domain_vocabulary', 'section_tree'.

    Returns:
        Dict with keys: refactored_text, errors, timings.
    """
    raise NotImplementedError("Task B-2.3")
```

- [ ] Step 6: Create stub for Clean Document Store writer:

```python
# src/ingest/clean_store.py

"""Clean Document Store — writer and reader.

Writes {source_key}.md (clean Markdown) and {source_key}.meta.json (metadata
envelope) atomically. Atomic write uses temp-file-then-rename to prevent
partial state. On failure mid-write, existing clean documents are preserved.

Requirements: FR-581, FR-582, FR-583, FR-584, FR-585, FR-586, FR-587
"""

from pathlib import Path

from src.ingest.pipeline_types import CleanDocumentMetadata, DocumentProcessingState


class CleanDocumentStore:
    """Manages reading and writing clean documents to the store.

    Args:
        root_dir: Root directory for the Clean Document Store.
    """

    def __init__(self, root_dir: Path) -> None:
        raise NotImplementedError("Task B-S.1")

    def write(self, source_key: str, md_content: str, metadata: CleanDocumentMetadata) -> None:
        """Atomically write a clean document and its metadata.

        Writes to temp files first, then renames. If metadata write fails
        after Markdown write succeeds, the Markdown file is rolled back.

        Args:
            source_key: Deterministic document identifier.
            md_content: Clean Markdown content.
            metadata: Metadata envelope to serialize as JSON.

        Raises:
            CleanStoreWriteError: If atomic write fails.
        """
        raise NotImplementedError("Task B-S.1")

    def read(self, source_key: str) -> tuple[str, CleanDocumentMetadata]:
        """Read a clean document and its metadata.

        Args:
            source_key: Deterministic document identifier.

        Returns:
            Tuple of (markdown_content, metadata).

        Raises:
            FileNotFoundError: If the document does not exist.
        """
        raise NotImplementedError("Task B-S.1")

    def exists(self, source_key: str) -> bool:
        """Check whether a clean document exists for the given source_key.

        Args:
            source_key: Deterministic document identifier.

        Returns:
            True if both .md and .meta.json files exist.
        """
        raise NotImplementedError("Task B-S.1")

    def list_all(self) -> list[str]:
        """List all source_keys in the store.

        Returns:
            Sorted list of source_key strings.
        """
        raise NotImplementedError("Task B-S.1")


def write_clean_document(state: DocumentProcessingState) -> dict:
    """DAG node wrapper: write the processed document to the Clean Document Store.

    Derives review_tier from extraction_confidence:
    - > 0.8: "Fully Reviewed"
    - 0.5–0.8: "Partially Reviewed"
    - < 0.5 or unavailable: "Self Reviewed" (default)

    Args:
        state: Pipeline state containing cleaned/refactored text and metadata.

    Returns:
        Dict with keys: errors, timings.
    """
    raise NotImplementedError("Task B-S.1")
```

---

### Task 0.4 — Shared Utilities Signatures

**Files:**
- Create: `src/ingest/pipeline_shared.py` (stub)

- [ ] Step 1: Define utility function signatures:

```python
# src/ingest/pipeline_shared.py

"""Shared utility functions for the Document Processing Pipeline.

Provides deterministic ID generation and hash computation used by
multiple nodes and the Clean Document Store.

Exports: generate_source_key, compute_source_hash, compute_clean_hash
"""

import hashlib


def generate_source_key(source_path: str) -> str:
    """Derive a deterministic source key from the source file path (FR-107).

    The source_key is stable across re-ingestion of the same file at the
    same path. Used as the filename stem in the Clean Document Store
    ({source_key}.md and {source_key}.meta.json).

    Formula: SHA-256(source_path.encode("utf-8")).hexdigest()[:24]

    Args:
        source_path: Absolute or relative path to the source file.

    Returns:
        24-character hex string derived from SHA-256 of the path.
    """
    return hashlib.sha256(source_path.encode("utf-8")).hexdigest()[:24]


def compute_source_hash(file_path: str) -> str:
    """Compute SHA-256 hash of source file content (FR-106).

    Used for change detection: if source_hash in stored .meta.json matches
    this value, the source document has not changed and processing can be skipped.

    Reads the file in 8192-byte blocks for memory efficiency.

    Args:
        file_path: Path to the source file.

    Returns:
        Full SHA-256 hex digest of the file content.
    """
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for block in iter(lambda: f.read(8192), b""):
            hasher.update(block)
    return hasher.hexdigest()


def compute_clean_hash(clean_markdown: str) -> str:
    """Compute SHA-256 hash of clean Markdown content (FR-583).

    Used by the Embedding Pipeline for its own independent change detection:
    if clean_hash matches, re-embedding can be skipped even if pipeline
    configuration changed.

    Args:
        clean_markdown: The clean Markdown content string.

    Returns:
        Full SHA-256 hex digest of the Markdown content.
    """
    return hashlib.sha256(clean_markdown.encode("utf-8")).hexdigest()
```

---

### Task 0.5 — Workflow Stub

**Files:**
- Create: `src/ingest/pipeline_workflow.py` (stub)

- [ ] Step 1: Define the graph builder signature with routing function stubs:

```python
# src/ingest/pipeline_workflow.py

"""Document Processing DAG — LangGraph StateGraph builder.

Constructs the 5-node Document Processing graph with two conditional
routing points: post-structure (multimodal optional) and post-cleaning
(refactoring optional).

Requirements: FR-302, FR-502
"""

from langgraph.graph import StateGraph

from src.ingest.pipeline_types import DocumentProcessingState, PipelineConfig


def _route_after_structure(state: DocumentProcessingState) -> str:
    """Route to VLM node only if figures were detected and multimodal is enabled (FR-302).

    Returns:
        "multimodal_processing" if figures detected and enabled, else "text_cleaning".
    """
    raise NotImplementedError("Task B-1.2")


def _route_after_cleaning(state: DocumentProcessingState) -> str:
    """Route to refactoring stage only if enabled in config (FR-502).

    Returns:
        "document_refactoring" if enabled, else "write_clean_store".
    """
    raise NotImplementedError("Task B-1.2")


def build_document_processing_graph(config: PipelineConfig) -> StateGraph:
    """Construct the Document Processing DAG.

    Flow:
        document_ingestion
            -> structure_detection
            -> [multimodal_processing]  (conditional: figures detected + enabled)
            -> text_cleaning
            -> [document_refactoring]   (conditional: enabled in config)
            -> write_clean_store        -> END

    Args:
        config: Pipeline configuration controlling stage enablement.

    Returns:
        Configured StateGraph ready to be compiled.
    """
    raise NotImplementedError("Task B-1.2")
```

---

## Phase A — Tests (Isolated from Implementation)

**Agent isolation contract:** The test agent receives ONLY:
1. The spec requirements (FR numbers + acceptance criteria from `DOCUMENT_PROCESSING_SPEC_SUMMARY.md`)
2. The contract files from Phase 0 (`pipeline_types.py`, `exceptions.py`, `pipeline_shared.py`, node stubs, `clean_store.py` stub, `pipeline_workflow.py` stub)
3. The task description from the implementation guide (`DOCUMENT_PROCESSING_IMPLEMENTATION.md`)

**Must NOT receive:** Any `src/ingest/nodes/*.py` implementation code beyond the stub signatures, any `src/ingest/clean_store.py` implementation beyond the stub, any `src/ingest/pipeline_workflow.py` implementation beyond the stub, or any Part B code appendix snippets from `DOCUMENT_PROCESSING_IMPLEMENTATION.md`. The test agent works ONLY against contracts and spec requirements.

---

### Task A-1.1 — Tests for Pipeline Configuration System

**Agent input (ONLY these):**
- FR-109 (domain vocabulary loading), FR-208 (swappable structure detection provider), FR-306 (swappable VLM provider), FR-502 (refactoring toggle), FR-587 (configurable clean store root) from spec
- `PipelineConfig` dataclass from `src/ingest/pipeline_types.py` (Phase 0)
- Task 1.1 description and subtasks from `DOCUMENT_PROCESSING_IMPLEMENTATION.md`

**Must NOT receive:** Any implementation of config loading/merging logic, any `config_loader.py` source code, any Part B code appendix snippets.

**Files:**
- Create: `tests/ingest/test_pipeline_config.py`

- [ ] Step 1: Write tests covering:
  - Default config construction — all fields have valid defaults
  - `PipelineConfig` is frozen (immutable after creation)
  - `clean_docs_dir` defaults to `Path("data/clean_docs")` (FR-587)
  - `enable_multimodal` defaults to `False`
  - `enable_refactoring` defaults to `False`
  - `confidence_threshold` defaults to `0.5` and accepts values in [0.0, 1.0]
  - `max_refactoring_iterations` defaults to `3` and accepts positive integers
  - `structure_detection_provider` defaults to `"docling"` (FR-208)
  - `vlm_provider` defaults to `"openai"` (FR-306)
  - `domain_vocabulary_path` defaults to `None` (FR-109)
  - `boilerplate_patterns` defaults to empty list
  - `llm_provider` defaults to `None`
  - Environment variable override precedence (env vars override file values)
  - File config override precedence (file values override built-in defaults)
  - Invalid value rejection: `confidence_threshold` outside [0.0, 1.0] raises `ConfigValidationError`
  - Invalid value rejection: `max_refactoring_iterations` <= 0 raises `ConfigValidationError`
  - Contradictory settings rejection: `enable_refactoring=True` with `llm_provider=None` raises `ConfigValidationError`
  - Missing vocabulary fallback: `domain_vocabulary_path` pointing to non-existent file raises error
  - Empty vocabulary file: returns empty dict, no error (FR-109)
  - Valid vocabulary file: loads and returns populated dict

- [ ] Step 2: Run tests to confirm stubs produce expected failures:

```bash
pytest tests/ingest/test_pipeline_config.py -v
```

Expected: FAIL (tests exercise config loading/validation logic that is not yet implemented)

---

### Task A-1.2 — Tests for DAG Skeleton

**Agent input (ONLY these):**
- FR-302 (conditional multimodal execution), FR-502 (conditional refactoring execution) from spec
- `DocumentProcessingState` TypedDict and `PipelineConfig` dataclass from `src/ingest/pipeline_types.py` (Phase 0)
- `build_document_processing_graph` signature from `src/ingest/pipeline_workflow.py` (Phase 0 stub)
- Node function signatures from Phase 0 stubs (names and argument types only)
- Task 1.2 description and subtasks from `DOCUMENT_PROCESSING_IMPLEMENTATION.md`

**Must NOT receive:** Any routing function implementation, any `build_document_processing_graph` implementation, any Part B code appendix snippets (especially B.1 — Document Processing DAG).

**Files:**
- Create: `tests/ingest/test_dag_skeleton.py`

- [ ] Step 1: Write tests covering:
  - Graph compiles without error when given a valid `PipelineConfig`
  - Graph has exactly 6 nodes: `document_ingestion`, `structure_detection`, `multimodal_processing`, `text_cleaning`, `document_refactoring`, `write_clean_store`
  - Entry point is `document_ingestion`
  - `document_ingestion` connects to `structure_detection`
  - `structure_detection` has conditional edges to `multimodal_processing` and `text_cleaning`
  - `multimodal_processing` connects to `text_cleaning`
  - `text_cleaning` has conditional edges to `document_refactoring` and `write_clean_store`
  - `document_refactoring` connects to `write_clean_store`
  - `write_clean_store` connects to `END`
  - Routing: when `has_figures=True` and `config.enable_multimodal=True`, route goes to `multimodal_processing`
  - Routing: when `has_figures=False` or `config.enable_multimodal=False`, route skips to `text_cleaning`
  - Routing: when `config.enable_refactoring=True`, route goes to `document_refactoring`
  - Routing: when `config.enable_refactoring=False`, route skips to `write_clean_store`
  - All state keys are preserved end-to-end when running a synthetic document through the stub graph

- [ ] Step 2: Run tests to confirm stubs produce expected failures:

```bash
pytest tests/ingest/test_dag_skeleton.py -v
```

Expected: FAIL (NotImplementedError from `build_document_processing_graph` stub)

---

### Task A-1.3 — Tests for Document Ingestion (Node 1)

**Agent input (ONLY these):**
- FR-101 (8 supported formats), FR-102 (format detection from extension with UNKNOWN fallback), FR-103 (format-specific text extraction), FR-106 (SHA-256 content hash), FR-107 (deterministic source_key from path), FR-108 (encoding fallback chain: UTF-8 -> Latin-1 -> CP1252 -> UTF-8 with replacement), FR-109 (domain vocabulary attachment), FR-110 (open extractor interface), FR-111 (`.log` file exclusion), FR-112 (local filesystem path validation), FR-113 (SharePoint adapter interface — SHOULD) from spec
- `DocumentProcessingState` TypedDict and `PipelineConfig` dataclass from `src/ingest/pipeline_types.py` (Phase 0)
- `document_ingestion_node` signature from `src/ingest/nodes/document_ingestion.py` (Phase 0 stub)
- `generate_source_key`, `compute_source_hash` signatures from `src/ingest/pipeline_shared.py` (Phase 0)
- Exception types from `src/ingest/exceptions.py` (Phase 0)
- Task 1.3 description and subtasks from `DOCUMENT_PROCESSING_IMPLEMENTATION.md`

**Must NOT receive:** Any extractor implementation code, any encoding fallback implementation, any Part B code appendix snippets (especially B.2 sample node, B.3 ID generation).

**Files:**
- Create: `tests/ingest/test_document_ingestion.py`

- [ ] Step 1: Write tests covering:
  - Format detection from `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.md`, `.html`, `.rst`, `.txt` extensions (FR-102)
  - UNKNOWN fallback for unrecognized extension (FR-102)
  - `.log` files are excluded/rejected early (FR-111)
  - Missing file raises clear error with path in message (FR-112)
  - `source_key` is deterministic: same path always produces same key (FR-107)
  - `source_key` differs for different paths (FR-107)
  - `source_key` is 24 hex characters (FR-107)
  - `source_hash` is a valid SHA-256 hex digest (FR-106)
  - `source_hash` changes when file content changes (FR-106)
  - `source_hash` is stable for identical file content (FR-106)
  - `raw_text` is non-empty for a valid document (FR-103)
  - Encoding fallback: UTF-8 file is read correctly (FR-108)
  - Encoding fallback: Latin-1 file is read correctly (FR-108)
  - Encoding fallback: CP1252 file is read correctly (FR-108)
  - Encoding fallback: binary file uses UTF-8 with replacement characters (FR-108)
  - `domain_vocabulary` from config is attached to state (FR-109)
  - Empty domain vocabulary produces empty dict, no error (FR-109)
  - Returned dict contains expected keys: `source_key`, `source_hash`, `format`, `raw_text`, `domain_vocabulary`
  - `timings` dict includes `"document_ingestion"` key with a float value
  - Node returns a plain dict, not a TypedDict instance

- [ ] Step 2: Create minimal fixture files for each format in `tests/fixtures/`:
  - `sample.pdf`, `sample.docx`, `sample.md`, `sample.html`, `sample.rst`, `sample.txt`
  - `sample_latin1.txt` (Latin-1 encoded), `sample_cp1252.txt` (CP1252 encoded)
  - `excluded.log`

- [ ] Step 3: Run tests to confirm stubs produce expected failures:

```bash
pytest tests/ingest/test_document_ingestion.py -v
```

Expected: FAIL (NotImplementedError from `document_ingestion_node` stub)

---

### Task A-1.4 — Tests for Structure Detection (Node 2)

**Agent input (ONLY these):**
- FR-201 (hierarchical section tree with heading levels and parent-child relationships), FR-202 (table extraction with header detection and Markdown conversion), FR-203 (figure detection: bounding boxes, captions, surrounding text), FR-204 (figure image export when multimodal enabled), FR-205 (abbreviation auto-detection and vocabulary merge, document-local precedence), FR-206 (extraction confidence score 0.0–1.0), FR-207 (requires_manual_review flag when below threshold, pipeline continues), FR-208 (swappable structure detection provider) from spec
- `DocumentProcessingState` TypedDict and `PipelineConfig` dataclass from `src/ingest/pipeline_types.py` (Phase 0)
- `structure_detection_node` signature from `src/ingest/nodes/structure_detection.py` (Phase 0 stub)
- Task 1.4 description and subtasks from `DOCUMENT_PROCESSING_IMPLEMENTATION.md`

**Must NOT receive:** Any structure detection provider implementation, any section tree parsing logic, any Part B code appendix snippets.

**Files:**
- Create: `tests/ingest/test_structure_detection.py`

- [ ] Step 1: Write tests covering:
  - Well-structured Markdown produces a hierarchical section tree with correct depth (FR-201)
  - Section tree preserves heading levels and parent-child relationships (FR-201)
  - Tables are extracted with headers and converted to Markdown (FR-202)
  - Table count matches expected number of tables in input (FR-202)
  - Figures are detected with bounding boxes and captions (FR-203)
  - `has_figures` is `True` when figures are present, `False` otherwise (FR-203)
  - Figure images are exported to disk when `config.enable_multimodal=True` (FR-204)
  - Figure images are NOT exported when `config.enable_multimodal=False` (FR-204)
  - Abbreviation auto-detection: "Natural Language Processing (NLP)" in text is detected (FR-205)
  - Document-local abbreviation definitions take precedence over global vocabulary (FR-205)
  - Domain vocabulary is updated/merged with auto-detected abbreviations (FR-205)
  - Extraction confidence is a float in [0.0, 1.0] (FR-206)
  - Well-structured document produces higher confidence than flat plain text (FR-206)
  - `requires_manual_review=True` when confidence < `config.confidence_threshold` (FR-207)
  - `requires_manual_review=False` when confidence >= `config.confidence_threshold` (FR-207)
  - Pipeline continues (no exception) when `requires_manual_review=True` (FR-207)
  - Different `structure_detection_provider` config values are accepted (FR-208)
  - Returned dict contains expected keys: `section_tree`, `tables`, `figures`, `has_figures`, `extraction_confidence`, `requires_manual_review`
  - `timings` dict includes `"structure_detection"` key

- [ ] Step 2: Run tests to confirm stubs produce expected failures:

```bash
pytest tests/ingest/test_structure_detection.py -v
```

Expected: FAIL (NotImplementedError from `structure_detection_node` stub)

---

### Task A-1.5 — Tests for Text Cleaning (Node 4)

**Agent input (ONLY these):**
- FR-401 (whitespace normalisation: collapse multiple spaces, limit consecutive newlines), FR-402 (boilerplate removal from configurable regex patterns), FR-403 (repeated line detection and reduction: lines appearing > 3 times reduced to 1), FR-404 (figure description integration at `[FIGURE fig_NNN]` markers), FR-405 (table Markdown integration at `[TABLE tbl_NNN]` markers) from spec
- `DocumentProcessingState` TypedDict and `PipelineConfig` dataclass from `src/ingest/pipeline_types.py` (Phase 0)
- `text_cleaning_node` signature from `src/ingest/nodes/text_cleaning.py` (Phase 0 stub)
- Task 1.5 description and subtasks from `DOCUMENT_PROCESSING_IMPLEMENTATION.md`

**Must NOT receive:** Any text cleaning implementation code, any Part B code appendix snippets (especially B.2 sample node which includes a complete text_cleaning_node implementation).

**Files:**
- Create: `tests/ingest/test_text_cleaning.py`

- [ ] Step 1: Write tests covering:
  - Multiple consecutive spaces are collapsed to a single space (FR-401)
  - Three or more consecutive newlines are reduced to two (FR-401)
  - Single spaces and double newlines are preserved (FR-401)
  - Boilerplate lines matching configured patterns are removed (FR-402)
  - Boilerplate patterns are applied case-insensitively with multiline flag (FR-402)
  - Empty boilerplate pattern list produces no removals (FR-402)
  - Lines appearing > 3 times are reduced to a single occurrence (FR-403)
  - Lines appearing <= 3 times are all preserved (FR-403)
  - Empty lines are not treated as repeated content to remove (FR-403)
  - Figure descriptions are inserted after `[FIGURE fig_NNN]` markers (FR-404)
  - Missing figure descriptions leave the marker unchanged (FR-404)
  - Table Markdown is inserted after `[TABLE tbl_NNN]` markers (FR-405)
  - Idempotency: cleaning the same text twice produces the same result
  - Returned dict contains `cleaned_text` key
  - `timings` dict includes `"text_cleaning"` key
  - Adversarial input: mixed whitespace types (tabs, spaces, newlines)
  - Adversarial input: excessive boilerplate on every page
  - Adversarial input: text with both figure and table markers interspersed

- [ ] Step 2: Run tests to confirm stubs produce expected failures:

```bash
pytest tests/ingest/test_text_cleaning.py -v
```

Expected: FAIL (NotImplementedError from `text_cleaning_node` stub)

---

### Task A-1.11 — Tests for CLI Entry Point

**Agent input (ONLY these):**
- FR-112 (local filesystem path validation, absolute and relative) from spec
- `PipelineConfig` dataclass from `src/ingest/pipeline_types.py` (Phase 0)
- `build_document_processing_graph` signature from `src/ingest/pipeline_workflow.py` (Phase 0 stub)
- Task 1.11 description and subtasks from `DOCUMENT_PROCESSING_IMPLEMENTATION.md`

**Must NOT receive:** Any CLI implementation code, any pipeline execution logic.

**Files:**
- Create: `tests/ingest/test_cli.py`

- [ ] Step 1: Write tests covering:
  - CLI accepts `--input` path argument (single file)
  - CLI accepts `--config` path argument (config file)
  - CLI accepts `--verbose` / `-v` flag
  - CLI accepts `--dry-run` flag
  - CLI accepts `--force` flag (force re-processing)
  - CLI rejects missing `--input` argument with non-zero exit code
  - CLI rejects non-existent input path with clear error message (FR-112)
  - CLI accepts absolute paths (FR-112)
  - CLI accepts relative paths (FR-112)
  - Directory input processes all supported files within it
  - `.log` files are skipped during directory walking (FR-111)
  - `--dry-run` produces no output files
  - Structured JSON report is emitted on stdout with keys: `processed`, `skipped`, `failed`
  - Non-zero exit code on failure

- [ ] Step 2: Run tests to confirm stubs produce expected failures:

```bash
pytest tests/ingest/test_cli.py -v
```

Expected: FAIL (CLI module not yet implemented)

---

### Task A-S.1 — Tests for Clean Document Store Writer

**Agent input (ONLY these):**
- FR-581 (one `.md` and one `.meta.json` per source document), FR-582 (metadata envelope schema), FR-583 (clean_hash in metadata), FR-584 (full processed text in Markdown file), FR-585 (heading hierarchy preserved in standard heading syntax), FR-586 (atomic write: no partial writes on failure), FR-587 (configurable root directory) from spec
- `CleanDocumentMetadata` dataclass from `src/ingest/pipeline_types.py` (Phase 0)
- `CleanDocumentStore` class and `write_clean_document` function signatures from `src/ingest/clean_store.py` (Phase 0 stub)
- `compute_clean_hash` signature from `src/ingest/pipeline_shared.py` (Phase 0)
- Review tier derivation rules: >0.8 = "Fully Reviewed", 0.5-0.8 = "Partially Reviewed", <0.5 = "Self Reviewed"
- Task S.1 description and subtasks from `DOCUMENT_PROCESSING_IMPLEMENTATION.md`

**Must NOT receive:** Any `CleanDocumentStore` implementation code, any atomic write implementation, any Part B code appendix snippets.

**Files:**
- Create: `tests/ingest/test_clean_store.py`

- [ ] Step 1: Write tests covering:
  - Write creates `{source_key}.md` file in configured directory (FR-581, FR-587)
  - Write creates `{source_key}.meta.json` file in configured directory (FR-581, FR-587)
  - Markdown content matches what was written (FR-584)
  - Metadata JSON contains all required fields from `CleanDocumentMetadata` (FR-582)
  - `clean_hash` in metadata matches SHA-256 of the Markdown content (FR-583)
  - Heading hierarchy is preserved in the Markdown (standard `#` syntax) (FR-585)
  - Atomic write: simulated failure mid-Markdown-write leaves no `.md` file (FR-586)
  - Atomic write: simulated failure mid-metadata-write rolls back the `.md` file (FR-586)
  - No `.md.tmp` or `.meta.json.tmp` files remain after successful write (FR-586)
  - `exists()` returns `True` after successful write
  - `exists()` returns `False` for non-existent source_key
  - `read()` returns the content and metadata that were written
  - `read()` raises `FileNotFoundError` for non-existent source_key
  - `list_all()` returns all written source_keys sorted
  - `list_all()` returns empty list on empty store
  - Overwrite: writing same source_key twice replaces previous content
  - Review tier derivation: `extraction_confidence=0.9` -> `"Fully Reviewed"`
  - Review tier derivation: `extraction_confidence=0.7` -> `"Partially Reviewed"`
  - Review tier derivation: `extraction_confidence=0.3` -> `"Self Reviewed"`
  - Review tier derivation: missing/unavailable confidence -> `"Self Reviewed"` (default)
  - Configurable root directory: different paths produce separate stores (FR-587)

- [ ] Step 2: Run tests to confirm stubs produce expected failures:

```bash
pytest tests/ingest/test_clean_store.py -v
```

Expected: FAIL (NotImplementedError from `CleanDocumentStore` stubs)

---

### Task A-2.3 — Tests for Document Refactoring (Node 5)

**Agent input (ONLY these):**
- FR-501 (self-contained paragraph restructuring), FR-502 (configurable skip flag), FR-503 (self-correcting iteration loop with configurable max_iterations), FR-504 (fact-check validation: no numerical values altered, no entities added), FR-505 (completeness validation), FR-506 (5 safety constraints: no new info, no content removal, no meaning change, exact preservation of numerical values, abbreviation expansion only from domain vocabulary), FR-507 (fail-safe fallback to original text), FR-508 (completeness score >= 80% threshold), FR-509 (original and refactored as separate artefacts, source never mutated), FR-510 (provenance metadata: source URI), FR-511 (provenance metadata: positional span mapping) from spec
- `DocumentProcessingState` TypedDict and `PipelineConfig` dataclass from `src/ingest/pipeline_types.py` (Phase 0)
- `document_refactoring_node` signature from `src/ingest/nodes/document_refactoring.py` (Phase 0 stub)
- `RefactoringValidationError` from `src/ingest/exceptions.py` (Phase 0)
- Task 2.3 description and subtasks from `DOCUMENT_PROCESSING_IMPLEMENTATION.md`

**Must NOT receive:** Any refactoring implementation code, any LLM prompt text, any validation logic implementation, any Part B code appendix snippets.

**Files:**
- Create: `tests/ingest/test_document_refactoring.py`

- [ ] Step 1: Write tests covering (use mocked LLM for all LLM-dependent tests):
  - Happy path: refactoring produces `refactored_text` different from `cleaned_text` (FR-501)
  - Paragraph with "as mentioned above" is refactored to include explicit value (FR-501)
  - Abbreviation is expanded using domain vocabulary (FR-506)
  - `enable_refactoring=False` skips stage entirely, returns state unchanged (FR-502)
  - Iteration loop runs up to `max_refactoring_iterations` times (FR-503)
  - Fact-check failure: altered numerical value causes iteration to retry (FR-504)
  - Fact-check failure: added entity causes iteration to retry (FR-504)
  - Completeness failure: score below 80% causes iteration to retry (FR-505, FR-508)
  - All iterations fail: returns original `cleaned_text` unchanged as fallback (FR-507)
  - Fallback logs a warning (FR-507)
  - No new information is added beyond source content (FR-506)
  - No content is removed from source (FR-506)
  - Numerical values are exactly preserved (FR-506)
  - Original text is never mutated — `cleaned_text` in state is unchanged (FR-509)
  - Both original and refactored text are available in output state (FR-509)
  - Provenance metadata includes source URI (FR-510)
  - Provenance metadata includes positional span mapping (FR-511)
  - `timings` dict includes `"document_refactoring"` key
  - Returned dict contains `refactored_text` key
  - LLM timeout triggers retry, not crash
  - LLM returns unparseable output triggers fallback

- [ ] Step 2: Run tests to confirm stubs produce expected failures:

```bash
pytest tests/ingest/test_document_refactoring.py -v
```

Expected: FAIL (NotImplementedError from `document_refactoring_node` stub)

---

### Task A-3.1 — Tests for Multimodal Processing (Node 3)

**Agent input (ONLY these):**
- FR-301 (VLM-based figure description generation), FR-302 (conditional execution: fires only if figures detected), FR-303 (description content: diagram type, visible labels, numerical specifications), FR-304 (no-speculation constraint: entities in description must not exceed entities in caption + surrounding text), FR-305 (per-description confidence score 0.0–1.0), FR-306 (swappable VLM provider via config), FR-307 (per-figure failure fallback: empty description + confidence 0.0, pipeline continues) from spec
- `DocumentProcessingState` TypedDict and `PipelineConfig` dataclass from `src/ingest/pipeline_types.py` (Phase 0)
- `multimodal_processing_node` signature from `src/ingest/nodes/multimodal_processing.py` (Phase 0 stub)
- `VLMProcessingError` from `src/ingest/exceptions.py` (Phase 0)
- Task 3.1 description and subtasks from `DOCUMENT_PROCESSING_IMPLEMENTATION.md`

**Must NOT receive:** Any VLM provider implementation, any VLM prompt text, any no-speculation validation logic, any Part B code appendix snippets.

**Files:**
- Create: `tests/ingest/test_multimodal_processing.py`

- [ ] Step 1: Write tests covering (use mocked VLM for all VLM-dependent tests):
  - Happy path: figures with images produce descriptions with diagram type, labels, values (FR-301, FR-303)
  - No figures in state: node returns state unchanged, no VLM calls made (FR-302)
  - `has_figures=False`: node returns state unchanged (FR-302)
  - `enable_multimodal=False`: node returns state unchanged (FR-302)
  - Description includes diagram type identification (FR-303)
  - Description includes visible labels (FR-303)
  - Description includes numerical specifications (FR-303)
  - No-speculation: description with entity NOT in caption/surrounding text is rejected (FR-304)
  - Each description has a confidence score in [0.0, 1.0] (FR-305)
  - Different `vlm_provider` config values are accepted (FR-306)
  - VLM timeout for one figure: that figure gets empty description + confidence 0.0, other figures processed normally (FR-307)
  - VLM API error for one figure: same fallback behavior (FR-307)
  - All figures fail: all get empty descriptions, no exception raised (FR-307)
  - `figure_descriptions` list length matches `figures` list length
  - `timings` dict includes `"multimodal_processing"` key
  - Returned dict contains `figure_descriptions` key

- [ ] Step 2: Run tests to confirm stubs produce expected failures:

```bash
pytest tests/ingest/test_multimodal_processing.py -v
```

Expected: FAIL (NotImplementedError from `multimodal_processing_node` stub)

---

### Task A-3.5 — Tests for PPTX and XLSX Extractors

**Agent input (ONLY these):**
- FR-104 (PPTX: extract text frames, speaker notes, table cells preserving slide order; slide number as section context), FR-105 (XLSX: extract all sheets with sheet names as headers, detect/convert tables to Markdown, preserve named ranges) from spec
- `DocumentProcessingState` TypedDict from `src/ingest/pipeline_types.py` (Phase 0)
- `document_ingestion_node` signature from `src/ingest/nodes/document_ingestion.py` (Phase 0 stub)
- Task 3.5 description and subtasks from `DOCUMENT_PROCESSING_IMPLEMENTATION.md`

**Must NOT receive:** Any extractor implementation code, any `python-pptx` or `openpyxl` usage code, any Part B code appendix snippets.

**Files:**
- Create: `tests/ingest/test_pptx_xlsx_extractors.py`

- [ ] Step 1: Write tests covering:
  - PPTX: text frames are extracted from slides (FR-104)
  - PPTX: speaker notes are extracted (FR-104)
  - PPTX: table cells are extracted (FR-104)
  - PPTX: slide order is preserved (FR-104)
  - PPTX: slide number is included as section context (FR-104)
  - PPTX: empty slides produce no content but no error (FR-104)
  - PPTX: slides with only speaker notes still produce output (FR-104)
  - XLSX: all sheets are extracted (FR-105)
  - XLSX: sheet names appear as headers (FR-105)
  - XLSX: tables are detected and converted to Markdown (FR-105)
  - XLSX: named ranges are preserved in output text (FR-105)
  - XLSX: merged cells are handled without error (FR-105)
  - XLSX: empty sheets produce no content but no error (FR-105)
  - XLSX: large sheets do not cause memory errors (FR-105)
  - Both formats are registered in the extractor registry (FR-110)
  - `.pptx` and `.xlsx` extensions are recognized by format detection (FR-102)

- [ ] Step 2: Create minimal fixture files in `tests/fixtures/`:
  - `sample.pptx` with text frames, speaker notes, and a table
  - `sample.xlsx` with multiple sheets, tables, and a named range

- [ ] Step 3: Run tests to confirm stubs produce expected failures:

```bash
pytest tests/ingest/test_pptx_xlsx_extractors.py -v
```

Expected: FAIL (NotImplementedError from `document_ingestion_node` stub or extractor not registered)

---

## Phase B — Implementation (Against Tests)

**Agent input per task:**
1. Task description from the implementation guide (`DOCUMENT_PROCESSING_IMPLEMENTATION.md`)
2. The specific test file from Phase A (the target to pass)
3. Contract files from Phase 0 (`pipeline_types.py`, `exceptions.py`, `pipeline_shared.py`, stubs)
4. Spec requirements (FR numbers + acceptance criteria)

**Must NOT receive:** Test files for OTHER tasks (only the test file for THIS specific task). This prevents implementation from being shaped by unrelated test expectations.

---

### Task B-1.1 — Implement Pipeline Configuration System

**Agent input:**
- Task 1.1 description + subtasks from `DOCUMENT_PROCESSING_IMPLEMENTATION.md`
- `tests/ingest/test_pipeline_config.py` (from Phase A, Task A-1.1)
- `src/ingest/pipeline_types.py` (contracts from Phase 0)
- `src/ingest/exceptions.py` (contracts from Phase 0)
- FR-109, FR-208, FR-306, FR-502, FR-587 from spec

**Must NOT receive:** `tests/ingest/test_dag_skeleton.py`, `tests/ingest/test_document_ingestion.py`, or any other Phase A test file.

**Files:**
- Modify: `src/ingest/pipeline_types.py` (add defaults, validation annotations if needed)
- Create: `src/ingest/config_loader.py` (config loading, merging, validation logic)

- [ ] Step 1: Implement config loading from defaults
- [ ] Step 2: Implement environment variable override merging
- [ ] Step 3: Implement file config override merging
- [ ] Step 4: Implement validation checks:
  - `confidence_threshold` in [0.0, 1.0]
  - `max_refactoring_iterations` > 0
  - `enable_refactoring=True` requires `llm_provider` is not `None`
- [ ] Step 5: Implement domain vocabulary loading from YAML/JSON file (FR-109)
- [ ] Step 6: Run tests:

```bash
pytest tests/ingest/test_pipeline_config.py -v
```

Expected: ALL PASS

- [ ] Step 7: Commit

---

### Task B-1.2 — Implement DAG Skeleton

**Agent input:**
- Task 1.2 description + subtasks from `DOCUMENT_PROCESSING_IMPLEMENTATION.md`
- `tests/ingest/test_dag_skeleton.py` (from Phase A, Task A-1.2)
- `src/ingest/pipeline_types.py` (contracts from Phase 0)
- `src/ingest/pipeline_workflow.py` (stub from Phase 0)
- Node stub files from Phase 0 (to register as no-op nodes)
- FR-302, FR-502 from spec

**Must NOT receive:** `tests/ingest/test_document_ingestion.py`, `tests/ingest/test_structure_detection.py`, or any other Phase A test file.

**Files:**
- Modify: `src/ingest/pipeline_workflow.py` (replace stubs with full implementation)

- [ ] Step 1: Implement `_route_after_structure` routing function (FR-302)
- [ ] Step 2: Implement `_route_after_cleaning` routing function (FR-502)
- [ ] Step 3: Implement `build_document_processing_graph` with all 6 nodes, conditional edges, entry point, and END edge
- [ ] Step 4: Register no-op pass-through stubs for nodes not yet implemented (they should pass state through unchanged)
- [ ] Step 5: Expose `compile()` via public API facade in `src/ingest/pipeline/__init__.py`
- [ ] Step 6: Run tests:

```bash
pytest tests/ingest/test_dag_skeleton.py -v
```

Expected: ALL PASS

- [ ] Step 7: Commit

---

### Task B-1.3 — Implement Document Ingestion (Node 1)

**Agent input:**
- Task 1.3 description + subtasks from `DOCUMENT_PROCESSING_IMPLEMENTATION.md`
- `tests/ingest/test_document_ingestion.py` (from Phase A, Task A-1.3)
- `src/ingest/pipeline_types.py` (contracts from Phase 0)
- `src/ingest/pipeline_shared.py` (from Phase 0 — already implemented)
- `src/ingest/exceptions.py` (contracts from Phase 0)
- FR-101, FR-102, FR-103, FR-106, FR-107, FR-108, FR-109, FR-110, FR-111, FR-112, FR-113 from spec

**Must NOT receive:** `tests/ingest/test_structure_detection.py`, `tests/ingest/test_text_cleaning.py`, or any other Phase A test file.

**Files:**
- Modify: `src/ingest/nodes/document_ingestion.py` (replace stub with full implementation)

- [ ] Step 1: Implement format detection from file extension with UNKNOWN fallback (FR-102)
- [ ] Step 2: Implement `.log` file exclusion (FR-111)
- [ ] Step 3: Implement extractor registry and dispatcher pattern (FR-103, FR-110):
  - `PdfExtractor`, `DocxExtractor`, `MarkdownExtractor`, `HtmlExtractor`, `RstExtractor`, `PlainTextExtractor`
  - Open interface: adding a new format requires implementing and registering, no pipeline changes
- [ ] Step 4: Implement encoding fallback chain: UTF-8 -> Latin-1 -> CP1252 -> UTF-8 with replacement (FR-108)
- [ ] Step 5: Wire `generate_source_key` and `compute_source_hash` from `pipeline_shared.py` (FR-106, FR-107)
- [ ] Step 6: Attach domain vocabulary from config to state (FR-109)
- [ ] Step 7: Implement filesystem path validation with clear error for missing files (FR-112)
- [ ] Step 8: Run tests:

```bash
pytest tests/ingest/test_document_ingestion.py -v
```

Expected: ALL PASS

- [ ] Step 9: Commit

---

### Task B-1.4 — Implement Structure Detection (Node 2)

**Agent input:**
- Task 1.4 description + subtasks from `DOCUMENT_PROCESSING_IMPLEMENTATION.md`
- `tests/ingest/test_structure_detection.py` (from Phase A, Task A-1.4)
- `src/ingest/pipeline_types.py` (contracts from Phase 0)
- `src/ingest/exceptions.py` (contracts from Phase 0)
- FR-201, FR-202, FR-203, FR-204, FR-205, FR-206, FR-207, FR-208 from spec

**Must NOT receive:** `tests/ingest/test_text_cleaning.py`, `tests/ingest/test_document_ingestion.py`, or any other Phase A test file.

**Files:**
- Modify: `src/ingest/nodes/structure_detection.py` (replace stub with full implementation)

- [ ] Step 1: Define structure detection provider interface and make it swappable (FR-208)
- [ ] Step 2: Implement hierarchical section tree parsing preserving heading levels and parent-child relationships (FR-201)
- [ ] Step 3: Implement table extraction with header detection and Markdown conversion (FR-202)
- [ ] Step 4: Implement figure detection: bounding boxes, captions, surrounding text context (FR-203)
- [ ] Step 5: Implement figure image export to disk when `config.enable_multimodal` is set (FR-204)
- [ ] Step 6: Implement abbreviation auto-detection and merge with domain vocabulary (document-local precedence) (FR-205)
- [ ] Step 7: Implement extraction confidence score computation (FR-206)
- [ ] Step 8: Implement `requires_manual_review` flag when score < threshold (FR-207)
- [ ] Step 9: Run tests:

```bash
pytest tests/ingest/test_structure_detection.py -v
```

Expected: ALL PASS

- [ ] Step 10: Commit

---

### Task B-1.5 — Implement Text Cleaning (Node 4)

**Agent input:**
- Task 1.5 description + subtasks from `DOCUMENT_PROCESSING_IMPLEMENTATION.md`
- `tests/ingest/test_text_cleaning.py` (from Phase A, Task A-1.5)
- `src/ingest/pipeline_types.py` (contracts from Phase 0)
- FR-401, FR-402, FR-403, FR-404, FR-405 from spec

**Must NOT receive:** `tests/ingest/test_structure_detection.py`, `tests/ingest/test_clean_store.py`, or any other Phase A test file.

**Files:**
- Modify: `src/ingest/nodes/text_cleaning.py` (replace stub with full implementation)

- [ ] Step 1: Implement whitespace normalisation: collapse multiple spaces, limit consecutive newlines (FR-401)
- [ ] Step 2: Implement boilerplate removal from configurable regex pattern list (FR-402)
- [ ] Step 3: Implement repeated-line detection and reduction: lines appearing > 3 times reduced to 1 (FR-403)
- [ ] Step 4: Implement figure description integration at `[FIGURE fig_NNN]` markers (FR-404)
- [ ] Step 5: Implement table Markdown integration at `[TABLE tbl_NNN]` markers (FR-405)
- [ ] Step 6: Run tests:

```bash
pytest tests/ingest/test_text_cleaning.py -v
```

Expected: ALL PASS

- [ ] Step 7: Commit

---

### Task B-1.11 — Implement CLI Entry Point

**Agent input:**
- Task 1.11 description + subtasks from `DOCUMENT_PROCESSING_IMPLEMENTATION.md`
- `tests/ingest/test_cli.py` (from Phase A, Task A-1.11)
- `src/ingest/pipeline_types.py` (contracts from Phase 0)
- `src/ingest/pipeline_workflow.py` (implemented in Task B-1.2)
- `src/ingest/config_loader.py` (implemented in Task B-1.1)
- FR-112 from spec

**Must NOT receive:** `tests/ingest/test_document_ingestion.py`, `tests/ingest/test_clean_store.py`, or any other Phase A test file.

**Files:**
- Create: `src/ingest/ingest.py` (CLI entry point)

- [ ] Step 1: Define CLI argument schema: `--input`, `--config`, `--verbose`/`-v`, `--dry-run`, `--force`
- [ ] Step 2: Wire CLI arguments to `PipelineConfig` loader and pipeline public API facade
- [ ] Step 3: Implement directory walking with glob patterns and file-type filtering (exclude `.log` per FR-111)
- [ ] Step 4: Add progress bar for batch mode (e.g., `tqdm`)
- [ ] Step 5: Emit structured JSON report: `{"processed": [...], "skipped": [...], "failed": [...]}`
- [ ] Step 6: Run tests:

```bash
pytest tests/ingest/test_cli.py -v
```

Expected: ALL PASS

- [ ] Step 7: Commit

---

### Task B-S.1 — Implement Clean Document Store Writer

**Agent input:**
- Task S.1 description + subtasks from `DOCUMENT_PROCESSING_IMPLEMENTATION.md`
- `tests/ingest/test_clean_store.py` (from Phase A, Task A-S.1)
- `src/ingest/pipeline_types.py` (contracts from Phase 0)
- `src/ingest/clean_store.py` (stub from Phase 0)
- `src/ingest/pipeline_shared.py` (from Phase 0 — already implemented)
- FR-581, FR-582, FR-583, FR-584, FR-585, FR-586, FR-587 from spec

**Must NOT receive:** `tests/ingest/test_document_refactoring.py`, `tests/ingest/test_document_ingestion.py`, or any other Phase A test file.

**Files:**
- Modify: `src/ingest/clean_store.py` (replace stubs with full implementation)

- [ ] Step 1: Implement `CleanDocumentStore.__init__` with configurable root directory (FR-587)
- [ ] Step 2: Implement `write()` with atomic temp-file-then-rename pattern (FR-586):
  - Write `{source_key}.md.tmp` then rename to `{source_key}.md`
  - Write `{source_key}.meta.json.tmp` then rename to `{source_key}.meta.json`
- [ ] Step 3: Implement rollback: if metadata write fails after Markdown rename succeeds, delete the Markdown file (FR-582, FR-586)
- [ ] Step 4: Implement `read()`, `exists()`, `list_all()` methods
- [ ] Step 5: Compute `clean_hash` (SHA-256 of Markdown content) using `compute_clean_hash` from `pipeline_shared.py` (FR-583)
- [ ] Step 6: Implement review tier derivation in `write_clean_document()`:
  - `extraction_confidence > 0.8` -> `"Fully Reviewed"`
  - `0.5 <= extraction_confidence <= 0.8` -> `"Partially Reviewed"`
  - `extraction_confidence < 0.5` or unavailable -> `"Self Reviewed"` (default)
- [ ] Step 7: Assert heading hierarchy preservation in Markdown using standard `#` syntax (FR-585)
- [ ] Step 8: Run tests:

```bash
pytest tests/ingest/test_clean_store.py -v
```

Expected: ALL PASS

- [ ] Step 9: Commit

---

### Task B-2.3 — Implement Document Refactoring (Node 5)

**Agent input:**
- Task 2.3 description + subtasks from `DOCUMENT_PROCESSING_IMPLEMENTATION.md`
- `tests/ingest/test_document_refactoring.py` (from Phase A, Task A-2.3)
- `src/ingest/pipeline_types.py` (contracts from Phase 0)
- `src/ingest/exceptions.py` (contracts from Phase 0)
- FR-501, FR-502, FR-503, FR-504, FR-505, FR-506, FR-507, FR-508, FR-509, FR-510, FR-511 from spec

**Must NOT receive:** `tests/ingest/test_multimodal_processing.py`, `tests/ingest/test_text_cleaning.py`, or any other Phase A test file.

**Files:**
- Modify: `src/ingest/nodes/document_refactoring.py` (replace stub with full implementation)

- [ ] Step 1: Design refactoring LLM prompt with 5 safety constraints (FR-506):
  1. No new information beyond source content
  2. No content removal
  3. No meaning change
  4. Exact preservation of numerical values
  5. Abbreviation expansion only from domain vocabulary
- [ ] Step 2: Implement self-correcting iteration loop (configurable `max_iterations` from config; FR-503)
- [ ] Step 3: Implement fact-check validation: confirm no numerical values altered, no entities added (FR-504)
- [ ] Step 4: Implement completeness validation: confirm all sentences represented, reject if below 80% (FR-505, FR-508)
- [ ] Step 5: Implement fail-safe fallback: all iterations fail -> return original text unchanged + log warning (FR-507)
- [ ] Step 6: Write both original and refactored text as separate artefacts (never mutate source; FR-509)
- [ ] Step 7: Attach provenance metadata: source URI and positional span mapping (FR-510, FR-511)
- [ ] Step 8: Respect `config.enable_refactoring = False` to skip entirely (FR-502)
- [ ] Step 9: Run tests:

```bash
pytest tests/ingest/test_document_refactoring.py -v
```

Expected: ALL PASS

- [ ] Step 10: Commit

---

### Task B-3.1 — Implement Multimodal Processing (Node 3)

**Agent input:**
- Task 3.1 description + subtasks from `DOCUMENT_PROCESSING_IMPLEMENTATION.md`
- `tests/ingest/test_multimodal_processing.py` (from Phase A, Task A-3.1)
- `src/ingest/pipeline_types.py` (contracts from Phase 0)
- `src/ingest/exceptions.py` (contracts from Phase 0)
- FR-301, FR-302, FR-303, FR-304, FR-305, FR-306, FR-307 from spec

**Must NOT receive:** `tests/ingest/test_document_refactoring.py`, `tests/ingest/test_text_cleaning.py`, or any other Phase A test file.

**Files:**
- Modify: `src/ingest/nodes/multimodal_processing.py` (replace stub with full implementation)

- [ ] Step 1: Define VLM provider interface and make it swappable via config (FR-306)
- [ ] Step 2: Implement VLM call: send figure image path + caption + surrounding text; require description to include diagram type, visible labels, numerical specifications (FR-303)
- [ ] Step 3: Implement no-speculation constraint: validate entities in description do not exceed entities in caption + surrounding text (FR-304)
- [ ] Step 4: Attach confidence score (0.0–1.0) to each description (FR-305)
- [ ] Step 5: Implement per-figure failure handling: timeout/API error -> empty description + confidence 0.0, continue to next figure (FR-307)
- [ ] Step 6: Skip stage entirely when no figures detected in Node 2 (FR-302)
- [ ] Step 7: Run tests:

```bash
pytest tests/ingest/test_multimodal_processing.py -v
```

Expected: ALL PASS

- [ ] Step 8: Commit

---

### Task B-3.5 — Implement PPTX and XLSX Extractors

**Agent input:**
- Task 3.5 description + subtasks from `DOCUMENT_PROCESSING_IMPLEMENTATION.md`
- `tests/ingest/test_pptx_xlsx_extractors.py` (from Phase A, Task A-3.5)
- `src/ingest/pipeline_types.py` (contracts from Phase 0)
- `src/ingest/nodes/document_ingestion.py` (implemented in Task B-1.3 — extractor registry)
- FR-104, FR-105 from spec

**Must NOT receive:** `tests/ingest/test_document_ingestion.py`, `tests/ingest/test_structure_detection.py`, or any other Phase A test file.

**Files:**
- Modify: `src/ingest/nodes/document_ingestion.py` (add extractors to registry)
- Create: `src/ingest/extractors/pptx_extractor.py` (if extractors are separate files)
- Create: `src/ingest/extractors/xlsx_extractor.py` (if extractors are separate files)

- [ ] Step 1: Implement `PptxExtractor` using `python-pptx`: extract text frames, speaker notes, table cells per slide in slide order; include slide number as section context (FR-104)
- [ ] Step 2: Implement `XlsxExtractor` using `openpyxl`: extract all sheets with sheet names as headers; detect and convert tables to Markdown; preserve named ranges (FR-105)
- [ ] Step 3: Register both extractors in the dispatcher (extend extractor registry)
- [ ] Step 4: Run tests:

```bash
pytest tests/ingest/test_pptx_xlsx_extractors.py -v
```

Expected: ALL PASS

- [ ] Step 5: Commit

---

## Task Dependency Graph

```
Phase 0 (Contract Definitions — MUST complete first, human-reviewed before Phase A)
├── Task 0.1: State and Config Contracts (pipeline_types.py)
├── Task 0.2: Exception Types (exceptions.py)
├── Task 0.3: Node Function Signatures (all node stubs)
├── Task 0.4: Shared Utilities Signatures (pipeline_shared.py)
└── Task 0.5: Workflow Stub (pipeline_workflow.py)
    │
    ▼ [REVIEW GATE — human approval required]
    │
Phase A (Tests — isolated from implementation, all tasks can run in parallel)
├── Task A-1.1: Tests for Config System
├── Task A-1.2: Tests for DAG Skeleton
├── Task A-1.3: Tests for Document Ingestion
├── Task A-1.4: Tests for Structure Detection
├── Task A-1.5: Tests for Text Cleaning
├── Task A-1.11: Tests for CLI Entry Point
├── Task A-S.1: Tests for Clean Store Writer
├── Task A-2.3: Tests for Document Refactoring
├── Task A-3.1: Tests for Multimodal Processing
└── Task A-3.5: Tests for PPTX/XLSX Extractors
    │
    ▼ [All Phase A tests must exist before Phase B begins]
    │
Phase B (Implementation — sequential per critical path, parallel where independent)
│
├── Critical Path (MVP) — SEQUENTIAL:
│   ├── Task B-1.1: Implement Config System
│   │       Run: pytest tests/ingest/test_pipeline_config.py -v → ALL PASS
│   ├── Task B-1.2: Implement DAG Skeleton ◄── B-1.1
│   │       Run: pytest tests/ingest/test_dag_skeleton.py -v → ALL PASS
│   ├── Task B-1.3: Implement Document Ingestion ◄── B-1.2
│   │       Run: pytest tests/ingest/test_document_ingestion.py -v → ALL PASS
│   ├── Task B-1.4: Implement Structure Detection ◄── B-1.3
│   │       Run: pytest tests/ingest/test_structure_detection.py -v → ALL PASS
│   ├── Task B-1.5: Implement Text Cleaning ◄── B-1.4
│   │       Run: pytest tests/ingest/test_text_cleaning.py -v → ALL PASS
│   └── Task B-S.1: Implement Clean Store Writer ◄── B-1.5
│           Run: pytest tests/ingest/test_clean_store.py -v → ALL PASS
│
├── Parallel with Critical Path:
│   ├── Task B-1.11: Implement CLI Entry Point ◄── B-1.2, B-1.1
│   │       Run: pytest tests/ingest/test_cli.py -v → ALL PASS
│   ├── Task B-3.1: Implement Multimodal Processing ◄── B-1.4
│   │       Run: pytest tests/ingest/test_multimodal_processing.py -v → ALL PASS
│   └── Task B-3.5: Implement PPTX/XLSX Extractors ◄── B-1.3
│           Run: pytest tests/ingest/test_pptx_xlsx_extractors.py -v → ALL PASS
│
└── Enhancement (after MVP):
    └── Task B-2.3: Implement Document Refactoring ◄── B-1.5, B-1.1
            Run: pytest tests/ingest/test_document_refactoring.py -v → ALL PASS
```

---

## Task-to-Requirement Mapping

| Task | Phase A Test File | Phase B Implementation | Requirements Covered |
|------|-------------------|----------------------|---------------------|
| 1.1 Config System | `tests/ingest/test_pipeline_config.py` | `src/ingest/config_loader.py` | FR-109, FR-208, FR-306, FR-502, FR-587 |
| 1.2 DAG Skeleton | `tests/ingest/test_dag_skeleton.py` | `src/ingest/pipeline_workflow.py` | FR-302, FR-502 |
| 1.3 Document Ingestion | `tests/ingest/test_document_ingestion.py` | `src/ingest/nodes/document_ingestion.py` | FR-101, FR-102, FR-103, FR-106, FR-107, FR-108, FR-109, FR-110, FR-111, FR-112, FR-113 |
| 1.4 Structure Detection | `tests/ingest/test_structure_detection.py` | `src/ingest/nodes/structure_detection.py` | FR-201, FR-202, FR-203, FR-204, FR-205, FR-206, FR-207, FR-208 |
| 1.5 Text Cleaning | `tests/ingest/test_text_cleaning.py` | `src/ingest/nodes/text_cleaning.py` | FR-401, FR-402, FR-403, FR-404, FR-405 |
| 1.11 CLI Entry Point | `tests/ingest/test_cli.py` | `src/ingest/ingest.py` | FR-112 |
| S.1 Clean Store Writer | `tests/ingest/test_clean_store.py` | `src/ingest/clean_store.py` | FR-581, FR-582, FR-583, FR-584, FR-585, FR-586, FR-587 |
| 2.3 Document Refactoring | `tests/ingest/test_document_refactoring.py` | `src/ingest/nodes/document_refactoring.py` | FR-501, FR-502, FR-503, FR-504, FR-505, FR-506, FR-507, FR-508, FR-509, FR-510, FR-511 |
| 3.1 Multimodal Processing | `tests/ingest/test_multimodal_processing.py` | `src/ingest/nodes/multimodal_processing.py` | FR-301, FR-302, FR-303, FR-304, FR-305, FR-306, FR-307 |
| 3.5 PPTX/XLSX Extractors | `tests/ingest/test_pptx_xlsx_extractors.py` | `src/ingest/nodes/document_ingestion.py` | FR-104, FR-105 |

<!-- VERIFY: All 53 requirements from DOCUMENT_PROCESSING_SPEC.md FR-101–FR-587 appear above. -->

---

## Full Test Suite Verification (Post-Implementation)

After all Phase B tasks are complete, run the full test suite to confirm no regressions:

```bash
pytest tests/ingest/ -v --tb=short
```

Expected: ALL PASS across all 10 test files.

---

## Companion Documents

| Document | Role |
|----------|------|
| `DOCUMENT_PROCESSING_SPEC.md` | Authoritative requirements baseline (FR-101–FR-587) |
| `DOCUMENT_PROCESSING_SPEC_SUMMARY.md` | Concise requirements digest |
| `DOCUMENT_PROCESSING_IMPLEMENTATION.md` | Task descriptions, subtasks, complexity estimates |
| `EMBEDDING_PIPELINE_IMPLEMENTATION.md` | Downstream phase implementation plan |
| `INGESTION_PIPELINE_ENGINEERING_GUIDE.md` | Developer architecture guide |
