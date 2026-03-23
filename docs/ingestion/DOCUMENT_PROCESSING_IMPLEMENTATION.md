# Document Processing Pipeline — Implementation Guide

| Field | Value |
|-------|-------|
| **Document** | Document Processing Pipeline Implementation Guide |
| **Version** | 1.0.0 |
| **Status** | Active |
| **Spec Reference** | `DOCUMENT_PROCESSING_SPEC.md` v1.0.0 (FR-101–FR-587) |
| **Companion Documents** | `DOCUMENT_PROCESSING_SPEC.md`, `DOCUMENT_PROCESSING_SPEC_SUMMARY.md`, `EMBEDDING_PIPELINE_IMPLEMENTATION.md`, `INGESTION_PIPELINE_ENGINEERING_GUIDE.md`, `INGESTION_NEW_ENGINEER_ONBOARDING_CHECKLIST.md`, `INGESTION_PLATFORM_SPEC.md` |
| **Created** | 2026-03-20 |
| **Last Updated** | 2026-03-20 |

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-03-20 | Split from `INGESTION_PIPELINE_IMPLEMENTATION.md` v1.1.0 — Document Processing phase tasks only. |

> **Document Intent.** This guide translates the requirements defined in `DOCUMENT_PROCESSING_SPEC.md`
> (FR-101–FR-587) into a phased, task-oriented implementation plan. Each task maps to one or more
> specification requirements and includes subtasks, complexity estimates, dependencies, and testing
> strategies.
>
> The Document Processing Pipeline transforms source documents (PDF, DOCX, PPTX, XLSX, Markdown,
> HTML, RST, plain text) into clean Markdown documents persisted to the **Clean Document Store**
> — the storage boundary between this phase and the Embedding Pipeline.
>
> See `EMBEDDING_PIPELINE_IMPLEMENTATION.md` for the downstream phase that reads from the Clean
> Document Store.

---

# Part A: Task-Oriented Overview

## Phase 1 — Core Document Processing (MVP)

The goal of Phase 1 is a working end-to-end Document Processing Pipeline: source documents are
read, parsed for structure, cleaned, and written to the Clean Document Store. Re-ingestion
detection (skipping unchanged documents) must work from day one.

---

### Task 1.1 — Pipeline Configuration System

**Description:** Implement the hierarchical configuration loader that merges defaults, environment
variables, and per-run overrides into a frozen `PipelineConfig` dataclass. Validate all values
at startup and fail fast on invalid combinations.

**Requirements Covered:** FR-109, FR-208, FR-306, FR-502, FR-587

**Dependencies:** None

**Complexity:** S

**Subtasks:**
1. Define `PipelineConfig` dataclass in `src/ingest/pipeline_types.py` with fields for all
   configurable pipeline behaviours (multimodal toggle, refactoring toggle, clean store root,
   structure detection provider, VLM provider, domain vocabulary path, boilerplate patterns).
2. Implement config loading and merging logic (environment variables override file values; file
   values override built-in defaults).
3. Add validation checks for contradictory settings (e.g., refactoring enabled but no LLM
   provider configured) and fail fast with clear error messages.
4. Load the domain vocabulary file (YAML/JSON) at startup and attach to config; accept empty
   vocabulary without error (FR-109).
5. Write unit tests covering merge precedence, invalid-value rejection, and missing-vocabulary
   fallback.

**Testing Strategy:** Unit tests only; no external services required.

---

### Task 1.2 — Document Processing DAG Skeleton

**Description:** Build the LangGraph `StateGraph` in `src/ingest/pipeline_workflow.py` with all
five Document Processing nodes. Phase 1 wires only the MVP nodes (document ingestion, structure
detection, text cleaning, clean store write); optional nodes (multimodal, refactoring) are
no-op pass-throughs until their tasks are complete. Conditional edges route based on figure
detection and config flags.

**Requirements Covered:** FR-302, FR-502

**Dependencies:** Task 1.1

**Complexity:** M

**Subtasks:**
1. Define `DocumentProcessingState` TypedDict in `pipeline_types.py` with all required state
   keys (source path, hash, format, section tree, figures, cleaned text, errors, timings).
2. Create the `build_document_processing_graph()` factory in `pipeline_workflow.py`.
3. Implement conditional routing: post-structure-detection route (multimodal if figures +
   enabled, else text cleaning; FR-302); post-cleaning route (refactoring if enabled, else
   write clean store; FR-502).
4. Register no-op stubs for Phase 2/3 nodes (multimodal, refactoring) so the graph compiles
   without their full implementations.
5. Expose `compile()` → `CompiledGraph` via the public API facade in
   `src/ingest/pipeline/__init__.py`.

**Testing Strategy:** Verify graph topology with LangGraph introspection; run a synthetic
document through the stub graph and assert all state keys are preserved end-to-end.

**Risks:** LangGraph API surface evolves; pin the dependency version.

---

### Task 1.3 — Node 1: Document Ingestion

**Description:** Implement the document ingestion node in
`src/ingest/nodes/document_ingestion.py`. Accepts a file path, detects document format from
extension, converts the file to raw text using format-specific extractors, computes a SHA-256
content hash for change detection, generates a deterministic `source_key`, and applies the
encoding fallback chain for text files.

**Requirements Covered:** FR-101, FR-102, FR-103, FR-106, FR-107, FR-108, FR-109, FR-110, FR-111, FR-112, FR-113

**Dependencies:** Task 1.2

**Complexity:** M

**Subtasks:**
1. Implement format detection from file extension with UNKNOWN fallback (FR-102); exclude
   `.log` files early (FR-111).
2. Build the extractor registry and dispatcher: `PdfExtractor`, `DocxExtractor`,
   `MarkdownExtractor`, `HtmlExtractor`, `RstExtractor`, `PlainTextExtractor` (FR-103). Design
   the extractor interface to be open to future addition without pipeline changes (FR-110).
3. Implement the encoding fallback chain: UTF-8 → Latin-1 → CP1252 → UTF-8 with replacement
   (FR-108).
4. Compute SHA-256 file hash (FR-106) and derive `source_key` from the source path (FR-107).
5. Attach loaded domain vocabulary to state (FR-109).
6. Validate local filesystem paths (absolute and relative); raise a clear error for missing
   files (FR-112). Document the SharePoint adapter interface for future implementation (FR-113).

**Testing Strategy:** Unit tests with fixture files of each supported MIME type; adversarial
tests with non-UTF-8 encodings; test that `.log` files are excluded.

---

### Task 1.4 — Node 2: Structure Detection

**Description:** Implement the structure detection node in
`src/ingest/nodes/structure_detection.py`. Parses the raw text into a hierarchical section
tree, extracts tables and figures with metadata, computes an extraction confidence score, and
auto-detects abbreviation definitions for merging with the domain vocabulary.

**Requirements Covered:** FR-201, FR-202, FR-203, FR-204, FR-205, FR-206, FR-207, FR-208

**Dependencies:** Task 1.3

**Complexity:** M

**Subtasks:**
1. Define the structure detection provider interface (section tree, figures, tables, confidence)
   and make the provider swappable via `PipelineConfig.structure_detection_provider` (FR-208).
2. Implement hierarchical section tree parsing preserving heading levels and parent-child
   relationships (FR-201).
3. Implement table extraction with header detection and Markdown conversion (FR-202).
4. Implement figure detection: bounding boxes, captions, surrounding text context (FR-203);
   export figure images to disk when `config.enable_multimodal` is set (FR-204).
5. Implement abbreviation auto-detection from inline definitions and abbreviation tables; merge
   with domain vocabulary, document-local definitions taking precedence (FR-205).
6. Compute extraction confidence score (FR-206); set `requires_manual_review` flag and
   continue pipeline when score is below configured threshold (FR-207).

**Testing Strategy:** Unit tests with documents of varying structure (well-structured Markdown,
scanned PDF artefacts, flat plain text); assert section tree depth, table count, figure count,
and confidence score range.

**Risks:** Extraction quality varies by format and layout; the confidence score and manual
review flag (FR-207) are the mitigation.

---

### Task 1.5 — Node 4: Text Cleaning

**Description:** Implement the text cleaning node in `src/ingest/nodes/text_cleaning.py`.
Normalises whitespace, removes boilerplate using configurable patterns, reduces repeated
headers/footers, and integrates VLM-generated figure descriptions and table Markdown
representations into the text stream at their original positions.

**Requirements Covered:** FR-401, FR-402, FR-403, FR-404, FR-405

**Dependencies:** Task 1.4

**Complexity:** S

**Subtasks:**
1. Implement whitespace normalisation: collapse multiple spaces, limit consecutive newlines to
   the configured maximum (FR-401).
2. Implement boilerplate removal from configurable regex pattern list (FR-402).
3. Implement automatic repeated-line detection and reduction: lines appearing more than 3 times
   are reduced to a single occurrence (FR-403).
4. Integrate VLM figure descriptions into the text stream at their original positions using
   `[FIGURE fig_NNN]` markers (FR-404).
5. Integrate table Markdown representations at their original positions using `[TABLE tbl_NNN]`
   markers (FR-405).

**Testing Strategy:** Unit tests with adversarial inputs (mixed encodings, excessive whitespace,
boilerplate every page, tables, figure markers). Assert idempotency: cleaning the same text
twice produces the same result.

---

### Task 1.11 — CLI Entry Point

**Description:** Implement the CLI in `ingest.py` using `argparse` or `click`. Supports
single-file and directory-glob modes, config file path, verbosity, dry-run, and force
re-processing. The CLI is the primary operational entry point for the full ingestion system —
it also triggers the downstream Embedding Pipeline after Document Processing completes.

> **Integration note:** Embedding Pipeline triggering is a platform-level integration concern defined in `INGESTION_PLATFORM_SPEC.md`. This task implements the CLI hook point; the actual orchestration logic lives in the platform layer.

**Requirements Covered:** FR-112

**Dependencies:** Task 1.2, Task 1.1

**Complexity:** S

**Subtasks:**
1. Define CLI argument schema: input path, config file, verbosity, dry-run, force-reprocess.
2. Wire CLI arguments to the `PipelineConfig` loader and the pipeline public API facade.
3. Implement directory walking with glob patterns and file-type filtering (respecting the
   exclusion rules from FR-111, FR-102).
4. Add progress bar for batch mode (e.g., `tqdm`).
5. Emit a structured JSON report summarising processed, skipped, and failed documents.

**Testing Strategy:** CLI smoke tests via subprocess; verify exit codes and report structure.

---

## Part A0: Clean Document Store (Writer)

The Clean Document Store is the persistent storage boundary between the Document Processing
Pipeline and the Embedding Pipeline. It is not a pipeline node — it is an infrastructure
component that this phase writes and the Embedding Pipeline reads.

See `EMBEDDING_PIPELINE_IMPLEMENTATION.md` → Task S.2 for the reader implementation.

---

### Task S.1 — Clean Document Store Writer

**Description:** Implement the Clean Document Store writer in
`src/ingest/clean_store.py`. Writes `{source_key}.md` (clean Markdown content) and
`{source_key}.meta.json` (metadata envelope) atomically. Atomic write ensures no partial state:
write to a temp file, then rename. On failure mid-write, the existing clean document for the
same `source_key` is preserved.

**Requirements Covered:** FR-581, FR-582, FR-583, FR-584, FR-585, FR-586, FR-587

**Dependencies:** Task 1.5

**Complexity:** S

**Subtasks:**
1. Define `CleanDocumentStore` class with `write(source_key, md_content, metadata)`,
   `read(source_key)`, `exists(source_key)`, and `list_all()` methods. Make the root directory
   configurable via `PipelineConfig.clean_docs_dir` (FR-587).
2. Implement atomic write: write to `{source_key}.md.tmp` then rename; same for
   `.meta.json.tmp` (FR-586).
3. Implement rollback: if metadata write fails after Markdown write succeeds, delete the
   Markdown file to prevent partial state (FR-582, FR-586).
4. Implement `CleanDocumentMetadata` dataclass with all required fields from FR-583:
   `source_key`, `source_path`, `source_hash`, `clean_hash`, `processing_timestamp`,
   `extraction_confidence`, `review_tier`, `section_tree_depth`, `table_count`, `has_figures`,
   `figure_count`, `processing_flags`.
5. Compute `clean_hash` (SHA-256 of Markdown content) during write (FR-583); assert heading
   hierarchy is preserved in the Markdown using standard heading syntax (FR-585).
6. Ensure the full processed text (cleaned body + figure descriptions + tables + optional
   refactored content) is written to the `.md` file (FR-584).
7. Derive `review_tier` for the metadata envelope based on extraction confidence from Node 2:
   - If `extraction_confidence` > 0.8: `"Fully Reviewed"`
   - If `extraction_confidence` between 0.5–0.8: `"Partially Reviewed"`
   - If `extraction_confidence` < 0.5 or unavailable: `"Self Reviewed"` (default)
   - The default tier (`"Self Reviewed"`) is configurable via platform config per FR-1514.

> **Cross-reference:** See `INGESTION_PLATFORM_SPEC.md` Section 4 for the full review tier lifecycle, including how review tiers propagate to the Embedding Pipeline and affect retrieval visibility weighting.

**Testing Strategy:** Unit tests asserting atomic write (simulate failure mid-write, verify no
partial files), hash correctness, and metadata schema completeness. Test that a failed metadata
write leaves no orphan `.md` file.

---

## Phase 2 — Document Enhancement

Phase 2 adds LLM-powered document refactoring to improve the quality of the clean Markdown
output by resolving implicit cross-references and making paragraphs self-contained for
downstream retrieval.

---

### Task 2.3 — Node 5: Document Refactoring

**Description:** Implement the document refactoring node in
`src/ingest/nodes/document_refactoring.py`. Uses an LLM to restructure document paragraphs
into self-contained units by resolving implicit references (e.g., "as mentioned above") to
explicit values. Uses a self-correcting bounded iteration loop with fact-check and completeness
validation. Falls back to the original text if all iterations fail validation.

**Requirements Covered:** FR-501, FR-502, FR-503, FR-504, FR-505, FR-506, FR-507, FR-508, FR-509, FR-510, FR-511

**Dependencies:** Task 1.5, Task 1.1

**Complexity:** L

**Subtasks:**
1. Design the refactoring LLM prompt with the five safety constraints: no new information, no
   content removal, no meaning change, exact preservation of numerical values, abbreviation
   expansion only from domain vocabulary (FR-506).
2. Implement the self-correcting iteration loop (configurable `max_iterations`; FR-503): each
   iteration attempts refactoring, then runs fact-check validation (FR-504) and completeness
   validation (FR-505, FR-508).
3. Implement fact-check validation: confirm no numerical values were altered, no entities added.
4. Implement completeness validation: confirm all sentences from source are represented; reject
   if completeness score falls below 80% (FR-508).
5. Implement fail-safe fallback: if all iterations fail, return original text unchanged and log
   a warning (FR-507).
6. Write both original and refactored text as separate artefacts (never mutate source; FR-509).
7. Attach provenance metadata to every refactored section: source URI and positional span
   mapping (FR-510, FR-511).

> **Scope note:** FR-510 and FR-511 are partially covered here — this task generates and attaches provenance metadata (source URI, positional span mapping) to refactored output. Chunk-level provenance propagation and citation resolution are downstream responsibilities covered in `EMBEDDING_PIPELINE_IMPLEMENTATION.md`.

8. Respect `config.enable_refactoring = false` to skip the stage entirely (FR-502).

**Testing Strategy:** Unit tests with mocked LLM covering: fact-check failure, completeness
failure, max-iterations exhaustion, and happy path. Integration test verifying that a paragraph
with "the voltage mentioned above" is refactored to include the explicit value.

**Risks:**
- LLM hallucination can subtly alter technical values; fact-check and completeness loops are
  the primary defence — ensure both pass before accepting a refactored section.
- LLM latency adds significant wall-clock time for large documents; mitigate with
  section-level parallelism and response caching keyed by content hash.

---

## Phase 3 — Extended Format Support

Phase 3 adds multimodal figure processing and extended format extractors, expanding both the
range of document types and the depth of knowledge captured from visual content.

---

### Task 3.1 — Node 3: Multimodal Processing

**Description:** Implement the multimodal processing node in
`src/ingest/nodes/multimodal_processing.py`. Uses a Vision-Language Model to generate text
descriptions of figures detected in Node 2. Only executes when figures were detected (conditional
edge from Node 2). VLM provider is swappable via configuration. Failures for individual figures
are non-fatal — the figure is recorded without a description.

**Requirements Covered:** FR-301, FR-302, FR-303, FR-304, FR-305, FR-306, FR-307

**Dependencies:** Task 1.4

**Complexity:** L

**Subtasks:**
1. Define the VLM provider interface and make it swappable via
   `PipelineConfig.vlm_provider` (FR-306).
2. Implement the VLM call: send figure image path + caption + surrounding text as context;
   require the description to include diagram type, visible labels, and numerical specifications
   (FR-303).
3. Implement the no-speculation constraint: validate that entities in the description do not
   exceed entities present in the figure's caption and surrounding text context (FR-304).
4. Attach a confidence score (0.0–1.0) to each description (FR-305).
5. Implement per-figure failure handling: on timeout or API error, record the figure with an
   empty description and confidence 0.0; continue to the next figure (FR-307).
6. Skip the stage entirely (no VLM calls) when no figures were detected in Node 2 (FR-302).

**Testing Strategy:** Integration tests with image-heavy documents; unit tests with mocked VLM
covering: successful description, timeout, and empty-description fallback.

**Risks:**
- VLM costs can be significant for image-heavy documents; mitigate with configurable per-document
  image limits and cost tracking.
- VLM output may include speculative content; the no-speculation validation (FR-304) must be
  enforced before accepting a description.

---

### Task 3.5 — PPTX and XLSX Extractors

**Description:** Add extractors for PowerPoint (PPTX) and Excel (XLSX) formats to the Node 1
extractor registry. PPTX extracts text frames, speaker notes, and table cells preserving slide
order; XLSX extracts all sheets with table detection and Markdown conversion, preserving named
ranges and cell references.

**Requirements Covered:** FR-104, FR-105

**Dependencies:** Task 1.3

**Complexity:** M

**Subtasks:**
1. Implement `PptxExtractor` using `python-pptx`: extract text frames and speaker notes per
   slide in slide order; extract table cells; include slide number as section context (FR-104).
2. Implement `XlsxExtractor` using `openpyxl`: extract all sheets with sheet names as headers;
   detect and convert tables to Markdown; preserve named ranges in output text (FR-105).
3. Register both extractors in the dispatcher (extend extractor registry, no pipeline changes).
4. Add fixture files and unit tests for both formats; test edge cases (empty slides, merged
   cells, large sheets).

**Testing Strategy:** Unit tests with representative PPTX and XLSX fixtures including speaker
notes, tables, and named ranges.

---

## Task Dependency Graph

```
Phase 1 (Core Document Processing — MVP)
├── Task 1.1: Config System ─────────────────────────────────────────┐
├── Task 1.2: DAG Skeleton ◄─── Task 1.1                            │ [CRITICAL]
├── Task 1.3: Node 1 Ingestion ◄─── Task 1.2                       │ [CRITICAL]
├── Task 1.4: Node 2 Structure Detection ◄─── Task 1.3             │ [CRITICAL]
├── Task 1.5: Node 4 Text Cleaning ◄─── Task 1.4                   │ [CRITICAL]
└── Task 1.11: CLI Entry Point ◄─── Task 1.2, Task 1.1             │

Part A0 (Clean Document Store — Boundary)
└── Task S.1: Clean Store Writer ◄─── Task 1.5 ─────────────────────┘ [CRITICAL]

Phase 2 (Enhancement)
└── Task 2.3: Node 5 Refactoring ◄─── Task 1.5, Task 1.1           [CRITICAL if enabled]

Phase 3 (Extended Format Support)
├── Task 3.1: Node 3 Multimodal ◄─── Task 1.4                      (parallel with 1.5)
└── Task 3.5: PPTX / XLSX Extractors ◄─── Task 1.3

Critical path (MVP): Task 1.1 → Task 1.2 → Task 1.3 → Task 1.4 → Task 1.5 → Task S.1
Critical path (full): + Task 2.3
```

---

## Task-to-Requirement Mapping

| Task | Requirements Covered |
|------|---------------------|
| 1.1 Pipeline Configuration System | FR-109, FR-208, FR-306, FR-502, FR-587 |
| 1.2 Document Processing DAG Skeleton | FR-302, FR-502 |
| 1.3 Node 1: Document Ingestion | FR-101, FR-102, FR-103, FR-106, FR-107, FR-108, FR-109, FR-110, FR-111, FR-112, FR-113 |
| 1.4 Node 2: Structure Detection | FR-201, FR-202, FR-203, FR-204, FR-205, FR-206, FR-207, FR-208 |
| 1.5 Node 4: Text Cleaning | FR-401, FR-402, FR-403, FR-404, FR-405 |
| 1.11 CLI Entry Point | FR-112 |
| S.1 Clean Document Store Writer | FR-581, FR-582, FR-583, FR-584, FR-585, FR-586, FR-587 |
| 2.3 Node 5: Document Refactoring | FR-501, FR-502, FR-503, FR-504, FR-505, FR-506, FR-507, FR-508, FR-509, FR-510, FR-511 |
| 3.1 Node 3: Multimodal Processing | FR-301, FR-302, FR-303, FR-304, FR-305, FR-306, FR-307 |
| 3.5 PPTX and XLSX Extractors | FR-104, FR-105 |

<!-- VERIFY: All 53 requirements from DOCUMENT_PROCESSING_SPEC.md FR-101–FR-587 appear above. -->

---

# Part B: Code Appendix

The following snippets illustrate the key design patterns used in the Document Processing
Pipeline. They are representative, not exhaustive — consult the source code for the full
implementation.

---

## B.1 — Document Processing DAG (LangGraph StateGraph)

Constructs the 5-stage Document Processing graph with two conditional routing points: post-structure
(multimodal optional) and post-cleaning (refactoring optional). Supports Tasks 1.2, 1.3, 1.4,
1.5, 2.3, 3.1, and S.1.

**Tasks:** Task 1.2, Task 3.1, Task 2.3
**Requirements:** FR-302, FR-502

```python
# src/ingest/pipeline_workflow.py

from langgraph.graph import StateGraph, END
from src.ingest.pipeline_types import DocumentProcessingState, PipelineConfig
from src.ingest.nodes.document_ingestion import document_ingestion_node
from src.ingest.nodes.structure_detection import structure_detection_node
from src.ingest.nodes.multimodal_processing import multimodal_processing_node
from src.ingest.nodes.text_cleaning import text_cleaning_node
from src.ingest.nodes.document_refactoring import document_refactoring_node
from src.ingest.clean_store import write_clean_document


def _route_after_structure(state: DocumentProcessingState) -> str:
    """Route to VLM node only if figures were detected and multimodal is enabled (FR-302)."""
    if state.get("has_figures") and state["config"].enable_multimodal:
        return "multimodal_processing"
    return "text_cleaning"


def _route_after_cleaning(state: DocumentProcessingState) -> str:
    """Route to refactoring stage only if enabled in config (FR-502)."""
    if state["config"].enable_refactoring:
        return "document_refactoring"
    return "write_clean_store"


def build_document_processing_graph(config: PipelineConfig) -> StateGraph:
    """Construct the Document Processing DAG.

    Flow:
        document_ingestion
            → structure_detection
            → [multimodal_processing]  (conditional: figures detected + enabled)
            → text_cleaning
            → [document_refactoring]   (conditional: enabled in config)
            → write_clean_store        → END
    """
    graph = StateGraph(DocumentProcessingState)

    graph.add_node("document_ingestion", document_ingestion_node)
    graph.add_node("structure_detection", structure_detection_node)
    graph.add_node("multimodal_processing", multimodal_processing_node)
    graph.add_node("text_cleaning", text_cleaning_node)
    graph.add_node("document_refactoring", document_refactoring_node)
    graph.add_node("write_clean_store", write_clean_document)

    graph.set_entry_point("document_ingestion")
    graph.add_edge("document_ingestion", "structure_detection")
    graph.add_conditional_edges(
        "structure_detection",
        _route_after_structure,
        {
            "multimodal_processing": "multimodal_processing",
            "text_cleaning": "text_cleaning",
        },
    )
    graph.add_edge("multimodal_processing", "text_cleaning")
    graph.add_conditional_edges(
        "text_cleaning",
        _route_after_cleaning,
        {
            "document_refactoring": "document_refactoring",
            "write_clean_store": "write_clean_store",
        },
    )
    graph.add_edge("document_refactoring", "write_clean_store")
    graph.add_edge("write_clean_store", END)

    return graph
```

**Key design decisions:**

- **Conditional edges over node removal** — disabled stages (multimodal, refactoring) are never
  reached rather than removed from the graph. The topology stays static and debuggable regardless
  of config.
- **Single entry point and exit** (`document_ingestion` → `write_clean_store`) simplify
  observability: every trace has the same shape.
- **Node functions are plain functions** accepting and returning `DocumentProcessingState`. No
  class instantiation per node — shared resources (LLM clients, VLM clients) are injected via
  the config object.

---

## B.2 — Shared State Schema and Node Base Pattern

Defines the typed state flowing through the Document Processing DAG and illustrates the node
function pattern. Supports all Phase 1 tasks.

**Tasks:** Task 1.1, Task 1.3, Task 1.4, Task 1.5, Task S.1
**Requirements:** FR-101–FR-113, FR-201–FR-208, FR-401–FR-405, FR-581–FR-587

```python
# src/ingest/pipeline_types.py  (excerpt)

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict


class DocumentProcessingState(TypedDict, total=False):
    """Shared state flowing through every node in the Document Processing DAG."""

    # Populated by Task 1.1 (config loader) and passed on the initial call
    config: "PipelineConfig"

    # Populated by Node 1 — Document Ingestion
    source_path: str
    source_key: str           # Deterministic identity derived from source path (FR-107)
    source_hash: str          # SHA-256 of source file bytes (FR-106)
    format: str               # Detected document format, e.g. "pdf", "docx" (FR-102)
    raw_text: str             # Format-converted plain text (FR-103)
    domain_vocabulary: dict[str, str]  # Abbreviation dictionary loaded at startup (FR-109)

    # Populated by Node 2 — Structure Detection
    section_tree: dict[str, Any]       # Hierarchical section structure (FR-201)
    tables: list[dict[str, Any]]       # Extracted tables with markdown (FR-202)
    figures: list[dict[str, Any]]      # Figures with bounding boxes + captions (FR-203)
    has_figures: bool
    extraction_confidence: float       # 0.0–1.0 quality score (FR-206)
    requires_manual_review: bool       # Set when confidence < threshold (FR-207)

    # Populated by Node 3 — Multimodal Processing (optional)
    figure_descriptions: list[dict[str, Any]]  # VLM descriptions per figure (FR-301)

    # Populated by Node 4 — Text Cleaning
    cleaned_text: str          # Whitespace-normalised, boilerplate-free, figures integrated

    # Populated by Node 5 — Document Refactoring (optional)
    refactored_text: str       # Self-contained paragraph version (FR-501)

    # Cross-cutting
    errors: list[dict[str, Any]]
    timings: dict[str, float]


@dataclass(frozen=True)
class CleanDocumentMetadata:
    """Metadata envelope written to the Clean Document Store (FR-583)."""

    source_key: str
    source_path: str
    source_hash: str           # SHA-256 of source file — Document Processing change key
    clean_hash: str            # SHA-256 of clean Markdown — Embedding Pipeline change key
    processing_timestamp: str  # ISO 8601
    extraction_confidence: float
    review_tier: str           # "Fully Reviewed" | "Partially Reviewed" | "Self Reviewed"
    section_tree_depth: int
    table_count: int
    has_figures: bool
    figure_count: int
    processing_flags: dict[str, bool]  # {"multimodal_enabled": bool, "refactoring_enabled": bool}


# --- Sample Node ---
# src/ingest/nodes/text_cleaning.py

import re
from collections import Counter

from src.ingest.pipeline_types import DocumentProcessingState


def text_cleaning_node(state: DocumentProcessingState) -> DocumentProcessingState:
    """Node 4: Normalise whitespace, remove boilerplate, integrate figure/table content."""
    start = time.perf_counter()
    config = state["config"]
    text = state["raw_text"]

    # FR-401: Whitespace normalisation
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # FR-402: Remove configurable boilerplate patterns
    for pattern in config.boilerplate_patterns:
        text = re.sub(pattern, "", text, flags=re.MULTILINE)

    # FR-403: Detect and reduce repeated lines (>3 occurrences → 1)
    lines = text.splitlines()
    line_counts = Counter(lines)
    seen: set[str] = set()
    deduped: list[str] = []
    for line in lines:
        if line_counts[line] > 3:
            if line not in seen:
                deduped.append(line)
                seen.add(line)
        else:
            deduped.append(line)
    text = "\n".join(deduped)

    # FR-404: Integrate figure descriptions at their original positions
    for fig in state.get("figure_descriptions", []):
        marker = f"[FIGURE {fig['figure_id']}]"
        description = fig.get("description", "")
        text = text.replace(marker, f"{marker}\n{description}" if description else marker)

    # FR-405: Integrate table Markdown at their original positions
    for tbl in state.get("tables", []):
        marker = f"[TABLE {tbl['table_id']}]"
        text = text.replace(marker, f"{marker}\n{tbl['markdown']}")

    elapsed = time.perf_counter() - start
    return {
        **state,
        "cleaned_text": text,
        "timings": {**state.get("timings", {}), "text_cleaning": elapsed},
    }
```

**Key design decisions:**

- **Nodes are pure functions** that accept and return `DocumentProcessingState`. No side effects
  inside the node function itself — I/O (VLM calls, disk writes) goes through injected clients
  in the config object.
- **Immutable return pattern** — nodes spread the incoming state and override only the keys they
  own. Upstream keys are never mutated.
- **Timing instrumentation** is built into every node from the start. The `timings` dict
  accumulates per-node wall-clock durations for reporting and Langfuse spans.

---

## B.3 — Deterministic ID Generation

Implements `source_key` derivation and the two-hash change-detection scheme used by both
the Document Processing and Embedding Pipelines. Supports Task 1.3 and Task S.1.

**Tasks:** Task 1.3, Task S.1
**Requirements:** FR-106, FR-107, FR-583

```python
# src/ingest/pipeline_shared.py  (excerpt)

import hashlib


def generate_source_key(source_path: str) -> str:
    """Derive a deterministic source key from the source file path (FR-107).

    The source_key is stable across re-ingestion of the same file at the same
    path — it is used as the filename stem in the Clean Document Store
    ({source_key}.md and {source_key}.meta.json).

    Moving the file to a different path produces a new source_key, which is
    the desired behaviour: the pipeline treats the file as a new document.
    """
    return hashlib.sha256(source_path.encode("utf-8")).hexdigest()[:24]


def compute_source_hash(file_path: str) -> str:
    """Compute SHA-256 hash of source file content (FR-106).

    Used by the Document Processing Pipeline for change detection:
    if source_hash in the stored .meta.json matches this value, the source
    document has not changed and processing can be skipped.
    """
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for block in iter(lambda: f.read(8192), b""):
            hasher.update(block)
    return hasher.hexdigest()


def compute_clean_hash(clean_markdown: str) -> str:
    """Compute SHA-256 hash of the clean Markdown content (FR-583).

    Used by the Embedding Pipeline for its own independent change detection:
    if clean_hash in the stored .meta.json matches this value, the clean
    Markdown has not changed and re-embedding can be skipped, even if the
    pipeline configuration changed.

    See EMBEDDING_PIPELINE_IMPLEMENTATION.md → Task S.2 for the downstream
    usage of this hash.
    """
    return hashlib.sha256(clean_markdown.encode("utf-8")).hexdigest()
```

**Key design decisions:**

- **Two independent change-detection hashes** — `source_hash` is the Document Processing
  Pipeline's skip key; `clean_hash` is the Embedding Pipeline's skip key. This decoupling
  means the two pipelines can independently decide whether to re-run without coordinating.
- **24-character truncation for `source_key`** — 96 bits of entropy is sufficient to avoid
  collisions at the expected corpus scale. Shorter keys make Clean Document Store filenames
  human-readable in logs and file browsers.
- **Path-derived `source_key` not content-derived** — the key is stable even if the file
  content changes (re-ingestion of a modified document produces the same key, overwriting the
  previous clean document). Content changes are tracked by `source_hash`, not by the key.
