> **Document type:** Authoritative requirements specification (Layer 3)
> **Downstream:** DOCUMENT_PARSING_SPEC_SUMMARY.md, DOCUMENT_PARSING_DESIGN.md
> **Last updated:** 2026-04-15

# Document Parsing Abstraction — Specification (v1.0.0)

## Document Information

> **Document intent:** This is a formal specification for the **Document Parsing Abstraction** — a pluggable parser interface that decouples the AION RAG ingestion pipeline from any single document parsing backend. It defines three parser strategy families (document, code, plain text), a unified `ParseResult`/`Chunk` contract, parser-internal chunking semantics, parser selection routing, and the VLM mode validation guard that prevents double image processing. This specification extends and supersedes parser-specific coupling in `DOCUMENT_PROCESSING_SPEC.md` and `DOCLING_CHUNKING_SPEC.md`.
> For the Document Processing Pipeline functional requirements (FR-100 through FR-589), see `DOCUMENT_PROCESSING_SPEC.md`.
> For the Embedding Pipeline functional requirements (FR-591 through FR-1399), see `EMBEDDING_PIPELINE_SPEC.md`.
> For the Docling-native chunking subsystem (HybridChunker integration, VLM enrichment), see `DOCLING_CHUNKING_SPEC.md`.
> For cross-cutting platform requirements (re-ingestion, config, error handling, data model, NFR), see `INGESTION_PLATFORM_SPEC.md`.

| Field | Value |
|-------|-------|
| System | AION RAG Document Embedding Pipeline |
| Document Type | Subsystem Specification — Document Parsing Abstraction |
| Companion Documents | DOCUMENT_PROCESSING_SPEC.md (Phase 1 Pipeline), EMBEDDING_PIPELINE_SPEC.md (Phase 2 Pipeline), DOCLING_CHUNKING_SPEC.md (Docling-Native Chunking), INGESTION_PLATFORM_SPEC.md (Platform Requirements) |
| Version | 1.0.0 |
| Status | Draft |
| Supersedes | None (new subsystem; refines parser coupling specified in FR-200–FR-299, FR-600–FR-699) |

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2026-04-15 | AI Assistant | Initial specification covering pluggable parser interface (Gap 8), three-strategy parser model (Gap 8b), and VLM mode validation guard (Gap 3). FR-3200 through FR-3399. |

---

## 1. Purpose and Scope

### 1.1 Problem Statement

The current ingestion pipeline is tightly coupled to Docling as its sole document parser. This creates three problems:

1. **No parser alternative.** If Docling fails to parse a document or is unavailable in a deployment environment, the pipeline has no recourse. There is no abstract contract separating "what a parser must produce" from "how Docling produces it."

2. **Leaked internal types.** The `DoclingDocument` object — an implementation detail of the Docling parser — has leaked into pipeline state, LangGraph node signatures, and the Clean Document Store persistence format. This couples every downstream consumer to Docling's internal representation, violating the swappability-over-lock-in design principle.

3. **No support for code or plain text sources.** The pipeline treats all inputs as documents requiring structural parsing (OCR, table detection, heading extraction). Source code files and plain text/markdown files do not need this processing and would benefit from specialised parsers: tree-sitter for AST-aware code chunking, and a lightweight heading-aware splitter for text files.

4. **Silent double VLM processing.** The `enable_multimodal_processing` flag (Phase 1 Node 3, `vision.py`) and the `vlm_mode=builtin` setting (Docling SmolVLM) can both be active simultaneously, causing figure images to be processed by two independent VLM pipelines with no user-visible warning.

### 1.2 Scope

This specification defines the requirements for a **pluggable parser abstraction** within the AION RAG ingestion system. The abstraction introduces a unified contract that all parsers implement, a routing mechanism that selects the correct parser per file, and configuration controls for chunking strategy override and VLM mode conflict prevention.

**Entry point:** Source document file path and `IngestionConfig`.

**Exit point:** A `ParseResult` containing structured metadata and markdown, plus a `list[Chunk]` produced by the parser's chunking method.

**In scope:**

- Abstract parser interface contract (`parse()` and `chunk()` methods)
- Unified `ParseResult` and `Chunk` data contracts
- Document parser strategy (Docling, RAGFlow DeepDoc)
- Code parser strategy (tree-sitter, AST-based)
- Plain text parser strategy (markdown/txt/rst)
- Parser selection routing by file extension
- Chunker override configuration ("native" vs "markdown")
- VLM mode validation guard (prevent double processing)
- Parser encapsulation rules (no internal types crossing the boundary)

### 1.3 Out of Scope

- **Embedding, storage, and retrieval.** How chunks are embedded, stored in Weaviate, or retrieved is specified in `EMBEDDING_PIPELINE_SPEC.md`.
- **VLM enrichment implementation.** Post-chunking VLM image description is specified in `DOCLING_CHUNKING_SPEC.md` (FR-2200–FR-2299). This spec only addresses the conflict guard between VLM modes.
- **Knowledge graph extraction logic.** KG entity/relationship extraction from parsed content is a downstream concern, though this spec defines the metadata contract that enables deterministic KG extraction from code ASTs.
- **RAGFlow DeepDoc implementation details.** DeepDoc is identified as a conformant parser implementation, but its internal chunking algorithm and configuration surface are not specified here.
- **Tree-sitter grammar installation and management.** Grammar availability is a deployment concern.
- **LLM-based code-to-natural-language translation.** Code chunks are stored as raw code; natural language explanation is a generation-phase concern.
- **Parser performance benchmarking and model selection heuristics.** Non-functional performance requirements are deferred to `INGESTION_PLATFORM_SPEC.md`.

### 1.4 Terminology

| Term | Definition |
|------|-----------|
| **Parser** | A component that transforms a source file into a `ParseResult` and produces `Chunk` objects from that result. Each parser encapsulates format-specific logic (OCR, AST traversal, heading detection). |
| **ParseResult** | The unified output contract of `parser.parse()`. Contains markdown text, headings, figure detection flag, and page count. Does NOT contain parser-internal types (e.g., `DoclingDocument`). |
| **Chunk** | The unified output contract of `parser.chunk()`. Contains chunk text, section path, heading, heading level, and chunk index. |
| **Parser Strategy** | One of three families: document parser, code parser, or plain text parser. Each strategy family shares input characteristics and chunking approaches. |
| **Native Chunker** | The parser's own chunking implementation, which leverages internal document structure (e.g., Docling's `HybridChunker`, tree-sitter's AST node boundaries). |
| **Markdown Chunker** | A fallback chunking implementation that operates on the markdown string from `ParseResult`, using heading-aware splitting. Available to all parsers as a chunker override. |
| **Opaque Parser State** | Internal state that a parser may retain between `parse()` and `chunk()` calls. The pipeline MUST NOT inspect, serialise, or depend on this state. |
| **AST** | Abstract Syntax Tree — the hierarchical representation of source code structure produced by tree-sitter. |
| **tree-sitter** | A universal parser generator library supporting 100+ programming languages with a consistent API and node type system. |
| **VLM Mode** | The `vlm_mode` configuration setting controlling how figure images are processed: `"disabled"`, `"builtin"` (Docling SmolVLM at parse time), or `"external"` (post-chunking via LiteLLM). |
| **Double Processing** | The erroneous state where both `enable_multimodal_processing=true` and `vlm_mode=builtin` are active, causing figures to be described by two independent VLM pipelines. |

### 1.5 Requirement Priority Levels

This specification uses the key words defined in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119):

| Keyword | Meaning |
|---------|---------|
| **MUST** / **SHALL** | Absolute requirement. The system is non-conformant without it. |
| **SHOULD** / **RECOMMENDED** | There may be valid reasons to omit this in particular circumstances, but the full implications must be understood and carefully weighed. |
| **MAY** / **OPTIONAL** | Truly optional. The system is conformant whether or not this is implemented. |

### 1.6 Requirement Format

Requirements in this specification use domain-prefixed IDs:

| Prefix | Meaning |
|--------|---------|
| **FR-** | Functional Requirement |

Requirements are grouped by section with the following ID ranges:

| Section | ID Range | Component |
|---------|----------|-----------|
| 3.1 Parser Interface Contract | FR-3200–FR-3219 | Abstract interface, ParseResult, Chunk |
| 3.2 Document Parser Strategy | FR-3220–FR-3249 | Docling, DeepDoc implementations |
| 3.3 Code Parser Strategy | FR-3250–FR-3279 | tree-sitter universal parser |
| 3.4 Plain Text Parser Strategy | FR-3280–FR-3299 | Markdown/txt/rst minimal parser |
| 3.5 Parser Selection and Routing | FR-3300–FR-3319 | Extension-based routing, config override |
| 3.6 Chunker Override Configuration | FR-3320–FR-3339 | Native vs markdown chunker selection |
| 3.7 VLM Mode Validation | FR-3340–FR-3359 | Double-processing guard |

### 1.7 Assumptions and Constraints

| ID | Assumption / Constraint | Impact if Violated |
|----|------------------------|--------------------|
| A-1 | Python 3.11+ runtime | Type hint syntax and match statements fail |
| A-2 | tree-sitter and language grammars installed for code parsing | Code parser strategy unavailable; files fall back to plain text parser |
| A-3 | Docling installed for document parsing | Document parser strategy unavailable; pipeline fails fast per FR-3200 |
| A-4 | Parser is mandatory — at least one parser implementation MUST be available | Pipeline cannot function without a parser; no silent degradation to raw text |
| A-5 | File extension reliably indicates content type | Misrouted files produce low-quality parse results but do not crash |

### 1.8 Design Principles

The following principles SHALL guide all design and implementation decisions for the parser abstraction:

| Principle | Description |
|-----------|-------------|
| **Encapsulation over leakage** | Parser-internal types (e.g., `DoclingDocument`, tree-sitter `Tree`) SHALL NOT cross the parser boundary. The pipeline operates exclusively on `ParseResult` and `Chunk`. |
| **Parser-internal chunking** | Each parser knows its own document structure best. Chunking SHALL be performed inside the parser using native structure, not reconstructed from markdown. |
| **Fail fast, not fail silent** | If a configured parser is unavailable at startup, the system SHALL raise an error immediately rather than silently degrading. |
| **Strategy, not conditional** | Parser selection SHALL use a strategy pattern, not a cascade of if/elif branches checking parser availability. |

---

## 2. Architecture Overview

### 2.1 Parser Strategy Routing

```text
Source File (path + config)
    │
    ├── Extension lookup ─────────────────────────────────┐
    │                                                     │
    ▼                                                     ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐
│  DOCUMENT       │  │  CODE           │  │  PLAIN TEXT          │
│  PARSER         │  │  PARSER         │  │  PARSER              │
│                 │  │                 │  │                      │
│  Docling /      │  │  tree-sitter    │  │  Heading-aware       │
│  DeepDoc        │  │  (universal)    │  │  markdown splitter   │
│                 │  │                 │  │                      │
│  Input:         │  │  Input:         │  │  Input:              │
│  PDF, DOCX,     │  │  .py, .rs, .go, │  │  .md, .txt, .rst    │
│  PPTX, images   │  │  .ts, .java ... │  │                      │
│                 │  │                 │  │                      │
│  Chunking:      │  │  Chunking:      │  │  Chunking:           │
│  HybridChunker  │  │  One chunk per  │  │  Markdown-based      │
│  (Docling) or   │  │  function/class │  │  heading-aware       │
│  DeepDoc native │  │  (AST-guided)   │  │  splitter            │
└────────┬────────┘  └────────┬────────┘  └──────────┬───────────┘
         │                    │                       │
         ▼                    ▼                       ▼
    ┌──────────────────────────────────────────────────────┐
    │              UNIFIED ParseResult                     │
    │  markdown: str                                       │
    │  headings: list[str]                                 │
    │  has_figures: bool                                   │
    │  page_count: int                                     │
    └──────────────────────┬───────────────────────────────┘
                           │
                           ▼
    ┌──────────────────────────────────────────────────────┐
    │              parser.chunk(parse_result)               │
    │                                                      │
    │  ┌─────────────────────────────────────────────────┐ │
    │  │  list[Chunk]                                    │ │
    │  │  text: str                                      │ │
    │  │  section_path: str                              │ │
    │  │  heading: str                                   │ │
    │  │  heading_level: int                             │ │
    │  │  chunk_index: int                               │ │
    │  │  extra_metadata: dict[str, Any]  (optional)     │ │
    │  └─────────────────────────────────────────────────┘ │
    └──────────────────────────────────────────────────────┘
                           │
                           ▼
                  Pipeline continues
            (embedding, KG extraction, storage)
```

### 2.2 Contract Summary

| Contract | Fields | Producer | Consumer |
|----------|--------|----------|----------|
| `ParseResult` | `markdown`, `headings`, `has_figures`, `page_count` | Any parser's `parse()` method | Pipeline nodes (cleaning, VLM, display, MinIO storage) |
| `Chunk` | `text`, `section_path`, `heading`, `heading_level`, `chunk_index`, `extra_metadata` | Any parser's `chunk()` method | Embedding node, KG extraction node, quality validation |

### 2.3 VLM Mode Validation Flow

```text
Config Validation (startup)
    │
    ├── vlm_mode == "builtin" AND enable_multimodal_processing == true ?
    │       │
    │       ├── YES → FAIL FAST: raise configuration error
    │       │         "vlm_mode='builtin' and enable_multimodal_processing=true
    │       │          are mutually exclusive. Disable one to prevent double
    │       │          VLM processing of figure images."
    │       │
    │       └── NO → Continue pipeline startup
    │
    ▼
Pipeline proceeds
```

---

## 3. Functional Requirements

### 3.1 Parser Interface Contract (FR-3200–FR-3219)

> **FR-3200: Abstract Parser Interface** | Priority: MUST
>
> The system MUST define an abstract parser interface that all parser implementations conform to. The interface SHALL declare exactly two public methods:
>
> 1. `parse(file_path: Path, config: IngestionConfig) -> ParseResult`
> 2. `chunk(parse_result: ParseResult) -> list[Chunk]`
>
> **Rationale:** A stable abstract interface decouples the pipeline from any single parser backend, enabling parser swappability without code changes to downstream nodes. This is the foundation of the swappability-over-lock-in design principle.
>
> **Acceptance Criteria:**
> 1. An abstract base class (or Protocol) exists with `parse()` and `chunk()` method signatures.
> 2. Calling `parse()` or `chunk()` on the abstract class directly raises `NotImplementedError` (or equivalent for Protocol).
> 3. At least two concrete implementations (Docling document parser and plain text parser) conform to the interface.
> 4. No pipeline node imports or references a concrete parser class directly — all access is through the abstract interface.

> **FR-3201: ParseResult Contract** | Priority: MUST
>
> The `parse()` method SHALL return a `ParseResult` dataclass with exactly the following fields:
>
> | Field | Type | Description |
> |-------|------|-------------|
> | `markdown` | `str` | The document content as markdown, suitable for cleaning, VLM enrichment, display, and MinIO storage. |
> | `headings` | `list[str]` | Heading text extracted from the document, in document order. |
> | `has_figures` | `bool` | Whether the parser detected any figures or images in the document. |
> | `page_count` | `int` | Total number of pages in the source document. `0` for formats without pages (code files, plain text). |
>
> The `ParseResult` SHALL NOT contain any parser-internal types (e.g., `DoclingDocument`, tree-sitter `Tree`, DeepDoc internal objects). Parser-internal state needed for chunking SHALL be retained inside the parser instance, not in `ParseResult`.
>
> **Rationale:** A minimal, parser-agnostic contract ensures that any pipeline node consuming `ParseResult` works identically regardless of which parser produced it. Excluding parser-internal types prevents type coupling and serialisation problems.
>
> **Acceptance Criteria:**
> 1. `ParseResult` is a Python dataclass with exactly the four fields listed above.
> 2. Given a Docling-parsed PDF, the `ParseResult` contains valid markdown, non-empty headings, and correct `has_figures`/`page_count` values — but no `DoclingDocument` attribute.
> 3. Given a tree-sitter-parsed Python file, the `ParseResult` contains the source code as markdown, file-level headings (module docstring or filename), `has_figures=False`, and `page_count=0`.
> 4. `ParseResult` can be serialised to JSON without custom serialisers (no opaque types in its fields).

> **FR-3202: Chunk Contract** | Priority: MUST
>
> The `chunk()` method SHALL return a `list[Chunk]` where each `Chunk` is a dataclass with the following fields:
>
> | Field | Type | Description |
> |-------|------|-------------|
> | `text` | `str` | The chunk content. |
> | `section_path` | `str` | Hierarchical breadcrumb string (e.g., `"Chapter 1 > Background > Prior Work"`). Empty string if no section hierarchy. |
> | `heading` | `str` | The nearest heading for this chunk. Empty string if none. |
> | `heading_level` | `int` | Depth of the nearest heading (1 = top-level, 0 = no heading). |
> | `chunk_index` | `int` | Zero-based index of this chunk within the document. |
> | `extra_metadata` | `dict[str, Any]` | Parser-specific metadata. MUST be JSON-serialisable. MAY be empty. |
>
> **Rationale:** A unified chunk contract ensures that embedding, KG extraction, and quality validation nodes operate identically on chunks from any parser. The `extra_metadata` field provides an extension point for parser-specific richness (e.g., code parser's `function_name`, `language`) without polluting the core contract.
>
> **Acceptance Criteria:**
> 1. `Chunk` is a Python dataclass with exactly the six fields listed above.
> 2. Given a Docling-parsed document, chunks carry `section_path` derived from Docling's heading hierarchy.
> 3. Given a tree-sitter-parsed Python file, chunks carry `extra_metadata` with `language`, `function_name`, `class_name` keys.
> 4. All values in `extra_metadata` are JSON-serialisable (no callables, no opaque objects).

> **FR-3203: Parser Mandatory — No Fallback** | Priority: MUST
>
> The system SHALL NOT provide a silent fallback when no parser is available for a given file. If the configured parser for a file's strategy cannot be loaded or initialised, the system SHALL raise a runtime error immediately and halt processing for that file.
>
> **Rationale:** Silent degradation to raw text ingestion (no structure, no heading hierarchy, no AST) produces low-quality chunks that pollute retrieval results. It is better to fail visibly and let the operator install the missing parser than to silently ingest garbage. This follows the fail-fast-not-fail-silent design principle.
>
> **Acceptance Criteria:**
> 1. Given a PDF file and Docling not installed, the system raises `RuntimeError` with a message identifying Docling as the missing dependency.
> 2. Given a `.py` file and tree-sitter not installed, the system raises `RuntimeError` with a message identifying tree-sitter as the missing dependency.
> 3. No file is ever ingested with a "raw text" fallback that bypasses all parsing.

> **FR-3204: Parser Readiness Check** | Priority: MUST
>
> Each parser implementation SHALL provide an `ensure_ready()` class method (or equivalent) that validates the parser's runtime dependencies are available before ingestion begins. This method SHALL be called during pipeline startup, not at first-file time.
>
> **Rationale:** Detecting a missing parser after processing 50 of 500 files wastes compute and creates a confusing partial-ingest state. Early validation follows the existing `ensure_docling_ready()` and `ensure_vision_ready()` patterns.
>
> **Acceptance Criteria:**
> 1. `ensure_ready()` is called during pipeline initialisation before any file is processed.
> 2. If `ensure_ready()` raises, the pipeline aborts before processing any file.
> 3. The error message from `ensure_ready()` identifies the specific missing dependency and installation instructions.

> **FR-3205: Parser Encapsulation — Opaque Internal State** | Priority: MUST
>
> A parser MAY retain internal state between its `parse()` and `chunk()` calls (e.g., the Docling parser stores `DoclingDocument` internally after `parse()` and uses it in `chunk()`). This internal state SHALL NOT be:
>
> 1. Accessible via any public attribute or method on `ParseResult`.
> 2. Stored in LangGraph pipeline state.
> 3. Persisted to the Clean Document Store or MinIO.
> 4. Referenced by any pipeline node outside the parser.
>
> The `ParseResult` MAY carry an opaque reference (e.g., a parser instance ID) that allows `chunk()` to locate the internal state, but the pipeline SHALL NOT inspect or depend on this reference.
>
> **Rationale:** Encapsulating parser-internal types prevents type leakage that couples downstream consumers to a specific parser implementation. The `DoclingDocument` leakage in the current system is the motivating example — it forced every downstream node, the state schema, and the persistence format to know about Docling internals.
>
> **Acceptance Criteria:**
> 1. `ParseResult` has no attribute named `docling_document`, `tree`, `internal_doc`, or any parser-specific type.
> 2. The `EmbeddingPipelineState` TypedDict has no key for parser-internal objects.
> 3. Replacing the Docling parser with the DeepDoc parser requires zero changes to pipeline nodes or state schema.

> **FR-3206: Parser Lifecycle — Instance Per Document** | Priority: SHOULD
>
> Parser implementations SHOULD use a per-document instance lifecycle where `parse()` populates internal state and `chunk()` consumes it. This ensures that internal state from one document does not leak into another.
>
> **Rationale:** A per-document lifecycle eliminates an entire class of state-leakage bugs. The alternative (a singleton parser with explicit state reset) is more error-prone and harder to test.
>
> **Acceptance Criteria:**
> 1. Parsing document A followed by document B does not cause B's chunks to contain headings or section paths from A.
> 2. Parser instances are safe for sequential reuse after `chunk()` completes.

> **FR-3207: Warmup Method** | Priority: SHOULD
>
> Parser implementations that require expensive one-time initialisation (model downloads, grammar compilation) SHOULD provide a `warmup()` class method that can be called during deployment or container startup, separate from `ensure_ready()`.
>
> **Rationale:** Separating warmup from readiness checking allows container images to pre-bake expensive assets (Docling model weights, tree-sitter grammars) during build time, reducing cold-start latency.
>
> **Acceptance Criteria:**
> 1. Calling `warmup()` in a clean environment downloads all required assets.
> 2. Calling `ensure_ready()` after `warmup()` completes without network access.

---

### 3.2 Document Parser Strategy (FR-3220–FR-3249)

> **FR-3220: Document Parser — Supported Formats** | Priority: MUST
>
> The document parser strategy SHALL handle the following input formats:
>
> | Format | Extension(s) |
> |--------|-------------|
> | PDF | `.pdf` |
> | Word | `.docx` |
> | PowerPoint | `.pptx` |
> | Image | `.png`, `.jpg`, `.jpeg`, `.tiff`, `.bmp` |
>
> **Rationale:** These are the binary/complex formats that require OCR, layout analysis, table detection, and structural parsing — capabilities that document parsers like Docling and DeepDoc provide. Simpler formats (markdown, plain text) are handled by the plain text parser strategy.
>
> **Acceptance Criteria:**
> 1. Given a PDF specification document, the document parser produces a `ParseResult` with structured markdown preserving headings, tables, and figure references.
> 2. Given a DOCX design guide, the document parser produces markdown with heading hierarchy intact.
> 3. Given a standalone `.png` image, the document parser produces a `ParseResult` with `has_figures=True` and any OCR-extracted text in the markdown field.

> **FR-3221: Document Parser — Docling Implementation** | Priority: MUST
>
> The system SHALL provide a Docling-based document parser implementation that conforms to the abstract parser interface (FR-3200). This implementation SHALL:
>
> 1. Use Docling's `DocumentConverter` for parsing.
> 2. Store the `DoclingDocument` object internally after `parse()`.
> 3. Use Docling's `HybridChunker` in its `chunk()` method, operating on the internal `DoclingDocument`.
> 4. Populate `ParseResult.markdown` via `DoclingDocument.export_to_markdown()`.
> 5. Populate `ParseResult.headings` from the markdown heading extraction.
> 6. Populate `ParseResult.has_figures` from `DoclingDocument.pictures`.
> 7. Populate `ParseResult.page_count` from the conversion result page count.
>
> For full Docling integration details (HybridChunker configuration, token limits, VLM enrichment), see `DOCLING_CHUNKING_SPEC.md`.
>
> **Rationale:** Docling is the existing, proven parser with rich structural extraction. Wrapping it in the abstract interface preserves all current functionality while enabling future alternatives.
>
> **Acceptance Criteria:**
> 1. The Docling parser class implements `parse()` and `chunk()` per the abstract interface.
> 2. `parse()` returns a `ParseResult` with no `DoclingDocument` attribute.
> 3. `chunk()` produces chunks with `section_path` derived from `HybridChunker`'s heading metadata.
> 4. The `DoclingDocument` is only accessible within the Docling parser class — not via `ParseResult`, state, or any other public API.

> **FR-3222: Document Parser — DeepDoc Implementation** | Priority: MAY
>
> The system MAY provide a RAGFlow DeepDoc-based document parser implementation that conforms to the abstract parser interface (FR-3200). When implemented, this parser SHALL:
>
> 1. Use DeepDoc's native parsing pipeline for document conversion.
> 2. Use DeepDoc's native chunking in its `chunk()` method.
> 3. Produce `ParseResult` and `Chunk` objects identical in structure to those from the Docling implementation.
>
> **Rationale:** DeepDoc is an alternative open-source document parser from the RAGFlow project. Supporting it validates the pluggable interface design and provides an alternative for deployments where Docling is unsuitable.
>
> **Acceptance Criteria:**
> 1. If implemented, the DeepDoc parser passes the same contract tests as the Docling parser.
> 2. Swapping from Docling to DeepDoc requires only a configuration change, not code changes.
> 3. `ParseResult` and `Chunk` objects from DeepDoc are structurally identical to those from Docling.

> **FR-3223: Document Parser — Chunk Heading Metadata** | Priority: MUST
>
> Document parser `chunk()` implementations SHALL populate the `section_path`, `heading`, and `heading_level` fields on each `Chunk` using the parser's native heading hierarchy. The Docling implementation SHALL derive these from `HybridChunker` chunk metadata (the `meta.headings` list). Other implementations SHALL derive them from their native heading structures.
>
> **Rationale:** Heading hierarchy metadata is a primary advantage of parser-internal chunking over markdown-based chunking. `HybridChunker` exists specifically because markdown chunking loses this structural information. See `DOCLING_CHUNKING_SPEC.md` for details on why this metadata matters for retrieval quality.
>
> **Acceptance Criteria:**
> 1. Given a document with nested headings (H1 > H2 > H3), chunks within the H3 section carry `section_path="H1 Title > H2 Title > H3 Title"`, `heading="H3 Title"`, `heading_level=3`.
> 2. Given a flat document with no headings, chunks carry `section_path=""`, `heading=""`, `heading_level=0`.

> **FR-3224: Document Parser — VLM Mode Passthrough** | Priority: MUST
>
> The document parser's `parse()` method SHALL respect the `vlm_mode` setting from `IngestionConfig`:
>
> - `vlm_mode="builtin"`: Configure Docling's `PdfPipelineOptions.do_picture_description=True` with SmolVLM, so figure descriptions are embedded in the `DoclingDocument` at parse time.
> - `vlm_mode="external"` or `vlm_mode="disabled"`: Do NOT enable Docling's picture description. External VLM enrichment (if any) happens post-chunking via the VLM enrichment node.
>
> **Rationale:** The VLM mode setting controls where and how figure images are described. The parser must honour this setting to prevent the double-processing scenario addressed in FR-3340.
>
> **Acceptance Criteria:**
> 1. Given `vlm_mode="builtin"`, the Docling parser produces markdown with figure descriptions already embedded.
> 2. Given `vlm_mode="disabled"`, the Docling parser produces markdown with figure placeholders (no descriptions).
> 3. The parser does not independently decide to enable or disable VLM — it follows `IngestionConfig.vlm_mode` exclusively.

---

### 3.3 Code Parser Strategy (FR-3250–FR-3279)

> **FR-3250: Code Parser — tree-sitter Universal** | Priority: MUST
>
> The system SHALL provide a code parser implementation using tree-sitter that conforms to the abstract parser interface (FR-3200). tree-sitter SHALL be the sole code parsing backend, providing universal support for 100+ programming languages through a single library with consistent node types.
>
> **Rationale:** tree-sitter parses all languages with one library and a unified node type system. Maintaining language-specific parsers (e.g., Python `ast`, Rust `syn`) for each supported language is not scalable and provides no benefit over tree-sitter's universal approach.
>
> **Acceptance Criteria:**
> 1. The code parser class implements `parse()` and `chunk()` per the abstract interface.
> 2. A Python file, a Rust file, and a Go file all produce valid `ParseResult` and `Chunk` objects through the same parser class.
> 3. No language-specific parser code exists outside of tree-sitter grammar selection.

> **FR-3251: Code Parser — Supported Languages** | Priority: MUST
>
> The code parser SHALL support at minimum the following languages, with automatic detection by file extension:
>
> | Language | Extension(s) |
> |----------|-------------|
> | Python | `.py` |
> | Rust | `.rs` |
> | Go | `.go` |
> | TypeScript | `.ts`, `.tsx` |
> | JavaScript | `.js`, `.jsx` |
> | Java | `.java` |
> | C | `.c`, `.h` |
> | C++ | `.cpp`, `.hpp`, `.cc`, `.cxx` |
> | C# | `.cs` |
> | Ruby | `.rb` |
> | Kotlin | `.kt` |
> | Swift | `.swift` |
> | Scala | `.scala` |
> | Shell | `.sh`, `.bash`, `.zsh` |
> | YAML | `.yaml`, `.yml` |
> | TOML | `.toml` |
> | JSON | `.json` |
> | Dockerfile | `Dockerfile` |
> | Makefile | `Makefile` |
>
> Additional languages MAY be supported via tree-sitter grammar installation. Unrecognised code extensions SHALL fall back to the plain text parser.
>
> **Rationale:** These languages cover the most common engineering codebases. tree-sitter grammars exist for all of them. The fallback to plain text ensures no file is rejected.
>
> **Acceptance Criteria:**
> 1. For each listed language, parsing a sample file produces a valid `ParseResult`.
> 2. For an unlisted extension (e.g., `.zig`), the system falls back to the plain text parser, not the code parser.

> **FR-3252: Code Parser — AST-Guided Chunking** | Priority: MUST
>
> The code parser's `chunk()` method SHALL produce one chunk per top-level function or class definition. A function or class body SHALL NEVER be split across multiple chunks.
>
> When a function or class body exceeds the maximum chunk size, the parser SHOULD split at logical block boundaries within the body (e.g., at method boundaries within a class, or at major control flow blocks within a function). If no logical boundary exists, the parser MAY split at line boundaries but SHALL log a warning.
>
> **Rationale:** Code is semantically coherent at the function/class level. Splitting a function mid-body destroys the semantic unit and makes retrieval results unintelligible. This is the primary advantage of AST-guided chunking over character/token-based splitting.
>
> **Acceptance Criteria:**
> 1. Given a Python file with three functions, `chunk()` produces exactly three chunks (plus optional module-level chunk for imports/constants).
> 2. Given a Python class with five methods, `chunk()` produces one chunk for the class (if it fits within size limits) or one chunk per method (if the class exceeds limits).
> 3. No chunk contains a partial function body (e.g., the first half of a function without its return statement).

> **FR-3253: Code Parser — Chunk Metadata** | Priority: MUST
>
> Each `Chunk` produced by the code parser SHALL carry the following keys in `extra_metadata`:
>
> | Key | Type | Description |
> |-----|------|-------------|
> | `language` | `str` | Programming language identifier (e.g., `"python"`, `"rust"`, `"go"`). |
> | `file_path` | `str` | Path to the source file relative to the ingestion root. |
> | `function_name` | `str` | Name of the function or method. Empty string for class-level or module-level chunks. |
> | `class_name` | `str` | Name of the enclosing class. Empty string for top-level functions or module-level chunks. |
> | `docstring` | `str` | The function/class docstring. Empty string if none. |
> | `imports` | `list[str]` | Import statements in the chunk's scope (module-level imports for top-level chunks). |
> | `decorators` | `list[str]` | Decorator names applied to the function/class (e.g., `["staticmethod", "lru_cache"]`). |
>
> **Rationale:** Rich code metadata enables precise code search (filter by language, function name, class), deterministic KG extraction (FR-3254), and generation-phase context assembly. Embedding models trained on code benefit from this structural context.
>
> **Acceptance Criteria:**
> 1. Given a Python function decorated with `@staticmethod` inside a class, the chunk's `extra_metadata` contains `function_name`, `class_name`, `decorators=["staticmethod"]`.
> 2. Given a module with `import os` and `from pathlib import Path`, all chunks carry `imports=["import os", "from pathlib import Path"]`.
> 3. All `extra_metadata` values are JSON-serialisable strings or lists of strings.

> **FR-3254: Code Parser — Deterministic KG Extraction from AST** | Priority: MUST
>
> The code parser SHALL extract knowledge graph relationships deterministically from the AST without requiring LLM calls. The following relationship types SHALL be extracted:
>
> | Relationship | Example | AST Source |
> |-------------|---------|-----------|
> | `imports` | `module_A imports module_B` | Import statements |
> | `inherits` | `class_X inherits class_Y` | Class base classes |
> | `calls` | `function_F calls function_G` | Function call expressions |
>
> These relationships SHALL be provided as structured data alongside the `Chunk` objects (via `extra_metadata` or a separate return channel) for the KG extraction node to consume without LLM processing.
>
> **Rationale:** Code relationships are structural facts derivable from the AST with 100% precision. Using an LLM to extract "module_A imports module_B" from source code is wasteful and less accurate than reading the import statement directly. Deterministic extraction produces exact call graphs, import trees, and inheritance chains.
>
> **Acceptance Criteria:**
> 1. Given a Python file that imports `os` and `pathlib`, the parser produces `imports` relationships for both.
> 2. Given a class `Dog(Animal)`, the parser produces an `inherits` relationship `Dog -> Animal`.
> 3. Given a function that calls `process_data()`, the parser produces a `calls` relationship.
> 4. No LLM call is made during code KG extraction.
> 5. Re-parsing the same file produces identical relationships (deterministic).

> **FR-3255: Code Parser — No Code-to-NL Translation at Ingest** | Priority: MUST
>
> The code parser SHALL NOT perform code-to-natural-language translation during ingestion. Code chunks SHALL be stored as raw source code. Natural language explanation of code is a generation-phase concern (after retrieval), not an ingestion-phase concern.
>
> **Rationale:** Code embedding models (e.g., CodeBERT, StarCoder embeddings) are trained on raw code and handle semantic similarity well. Adding an LLM code-to-NL step during ingestion wastes LLM calls, increases latency, and loses precision (the LLM's summary is less precise than the original code). The generation phase can explain code in context of the user's question, which is more useful than a generic summary.
>
> **Acceptance Criteria:**
> 1. Given a Python function, the chunk's `text` field contains the raw source code, not a natural language description.
> 2. No LLM call is made to summarise or describe code during the ingestion pipeline.

> **FR-3256: Code Parser — ParseResult for Code Files** | Priority: MUST
>
> The code parser's `parse()` method SHALL produce a `ParseResult` with:
>
> - `markdown`: The source code formatted as a fenced code block with language identifier (e.g., `` ```python\n...\n``` ``). This is for display and MinIO storage, not for chunking.
> - `headings`: A list containing the module-level docstring (if present) or the filename as a single heading.
> - `has_figures`: `False` (code files do not contain figures).
> - `page_count`: `0` (code files do not have pages).
>
> **Rationale:** The `ParseResult` contract must be satisfied even for code files. The markdown representation serves display and storage purposes. Chunking uses the AST (via internal state), not the markdown.
>
> **Acceptance Criteria:**
> 1. Given a Python file `utils.py` with a module docstring `"""Utility helpers."""`, the `ParseResult` has `headings=["Utility helpers."]`.
> 2. Given a Python file with no docstring, `headings=["utils.py"]`.
> 3. `has_figures` is `False` and `page_count` is `0` for all code files.

---

### 3.4 Plain Text Parser Strategy (FR-3280–FR-3299)

> **FR-3280: Plain Text Parser — Supported Formats** | Priority: MUST
>
> The plain text parser strategy SHALL handle the following input formats:
>
> | Format | Extension(s) |
> |--------|-------------|
> | Markdown | `.md` |
> | Plain text | `.txt` |
> | reStructuredText | `.rst` |
> | HTML | `.html`, `.htm` |
>
> **Rationale:** These formats are already text and require minimal processing. They do not need OCR, layout analysis, or AST parsing. The plain text parser provides heading-aware chunking without the overhead of a full document parser.
>
> **Acceptance Criteria:**
> 1. Given a markdown file with `#` headings, the parser produces a `ParseResult` with headings extracted.
> 2. Given a plain `.txt` file with no headings, the parser produces a valid `ParseResult` with `headings=[]`.
> 3. Given an `.rst` file with reStructuredText heading underlines, the parser extracts headings correctly.

> **FR-3281: Plain Text Parser — Minimal Processing** | Priority: MUST
>
> The plain text parser's `parse()` method SHALL perform minimal processing:
>
> 1. Read the file content as text.
> 2. For `.html`/`.htm` files, convert HTML to markdown (strip tags, preserve structure).
> 3. For `.rst` files, convert reStructuredText to markdown.
> 4. For `.md` and `.txt` files, use the content as-is.
> 5. Extract headings from the resulting markdown.
> 6. Set `has_figures` based on presence of markdown image references (`![...](...)`).
> 7. Set `page_count` to `0`.
>
> **Rationale:** These files are already in a readable text format. Applying OCR or structural analysis would be wasteful. The parser's value is heading extraction and format normalisation to markdown, not content transformation.
>
> **Acceptance Criteria:**
> 1. Given a 10 KB markdown file, `parse()` completes in under 100ms (no model loading, no OCR).
> 2. Given an HTML file with `<h1>`, `<h2>` tags, the parser produces markdown with `#`, `##` headings.
> 3. No external model or service is invoked during plain text parsing.

> **FR-3282: Plain Text Parser — Markdown-Based Chunking** | Priority: MUST
>
> The plain text parser's `chunk()` method SHALL use a heading-aware markdown chunker that:
>
> 1. Splits on markdown heading boundaries (`#`, `##`, `###`, etc.).
> 2. Respects `chunk_size` and `chunk_overlap` from `IngestionConfig`.
> 3. Populates `section_path`, `heading`, and `heading_level` on each `Chunk` from the heading hierarchy.
> 4. Treats markdown table blocks (`|...|` rows) as atomic units that SHALL NOT be split across chunks.
>
> **Rationale:** Heading-aware chunking is the natural strategy for text files that already use headings for structure. Table atomicity prevents splitting a table row mid-cell, which produces unintelligible chunks.
>
> **Acceptance Criteria:**
> 1. Given a markdown file with `# A`, `## B`, `## C` sections, chunks align to section boundaries.
> 2. Given a markdown table spanning 20 rows, the table is kept in a single chunk (or split at row boundaries, never mid-row).
> 3. `section_path` correctly reflects the heading hierarchy for each chunk.

---

### 3.5 Parser Selection and Routing (FR-3300–FR-3319)

> **FR-3300: Automatic Parser Selection by File Extension** | Priority: MUST
>
> The system SHALL automatically select the parser strategy based on the source file's extension according to the following priority:
>
> 1. **Document parser:** `.pdf`, `.docx`, `.pptx`, `.png`, `.jpg`, `.jpeg`, `.tiff`, `.bmp`
> 2. **Code parser:** `.py`, `.rs`, `.go`, `.ts`, `.tsx`, `.js`, `.jsx`, `.java`, `.c`, `.h`, `.cpp`, `.hpp`, `.cc`, `.cxx`, `.cs`, `.rb`, `.kt`, `.swift`, `.scala`, `.sh`, `.bash`, `.zsh`, `.yaml`, `.yml`, `.toml`, `.json`, `Dockerfile`, `Makefile`
> 3. **Plain text parser:** `.md`, `.txt`, `.rst`, `.html`, `.htm`
>
> File extensions SHALL be matched case-insensitively.
>
> **Rationale:** Automatic routing by extension eliminates manual configuration for the common case. The three strategy families have clear, non-overlapping extension sets.
>
> **Acceptance Criteria:**
> 1. Given `report.pdf`, the document parser is selected.
> 2. Given `main.py`, the code parser is selected.
> 3. Given `README.md`, the plain text parser is selected.
> 4. Given `REPORT.PDF` (uppercase), the document parser is selected (case-insensitive).

> **FR-3301: Parser Override via Configuration** | Priority: SHOULD
>
> The system SHOULD support an `IngestionConfig` field (e.g., `parser_strategy`) that overrides automatic extension-based selection. Valid values:
>
> - `"auto"` (default): Use extension-based routing per FR-3300.
> - `"document"`: Force document parser for all files.
> - `"code"`: Force code parser for all files.
> - `"text"`: Force plain text parser for all files.
>
> **Rationale:** Some edge cases benefit from override — e.g., a `.txt` file containing structured data that benefits from document parsing, or a `.json` file that should be treated as plain text rather than code.
>
> **Acceptance Criteria:**
> 1. Given `parser_strategy="document"` and a `.txt` file, the document parser is used.
> 2. Given `parser_strategy="auto"`, extension-based routing applies normally.
> 3. Given an invalid `parser_strategy` value, the system raises a configuration error at startup.

> **FR-3302: Unrecognised Extension Handling** | Priority: MUST
>
> When a file has an extension not mapped to any parser strategy, the system SHALL route it to the plain text parser as a fallback. The system SHALL log a warning identifying the unrecognised extension.
>
> **Rationale:** Unknown extensions are more likely to be text-like (config files, log files, custom formats) than binary. The plain text parser provides a reasonable best-effort parse. The warning ensures operators notice the fallback.
>
> **Acceptance Criteria:**
> 1. Given a file `config.ini`, the plain text parser is selected and a warning is logged.
> 2. Given a file `data.parquet`, the plain text parser is selected (may produce low-quality results, but does not crash).
> 3. The warning message includes the file name and the unrecognised extension.

> **FR-3303: Parser Strategy Registry** | Priority: MUST
>
> The system SHALL maintain a registry mapping parser strategy names to concrete parser classes. The registry SHALL be populated at startup based on available implementations. Pipeline nodes SHALL obtain parser instances from the registry, never by importing concrete parser classes directly.
>
> **Rationale:** A registry decouples pipeline nodes from concrete parser classes, enabling the strategy pattern. New parser implementations can be registered without modifying pipeline node code.
>
> **Acceptance Criteria:**
> 1. The registry contains entries for all installed parser strategies (at minimum: `"document"`, `"text"`).
> 2. Pipeline nodes obtain parsers via `registry.get_parser(strategy_name)`, not via `from src.ingest.support.docling import DoclingParser`.
> 3. Adding a new parser implementation requires registering it in the registry and adding extension mappings — no changes to pipeline nodes.

---

### 3.6 Chunker Override Configuration (FR-3320–FR-3339)

> **FR-3320: Chunker Override Setting** | Priority: MUST
>
> The system SHALL support an `IngestionConfig` field named `chunker` with the following values:
>
> - `"native"` (default): Use the parser's own `chunk()` implementation, which leverages internal document structure.
> - `"markdown"`: Force all parsers to use the markdown-based chunker regardless of parser type. The markdown chunker operates on `ParseResult.markdown`.
>
> **Rationale:** The native chunker is preferred because it leverages parser-internal structure (Docling's `HybridChunker` uses `DoclingDocument`, tree-sitter uses AST boundaries). However, users may want the markdown chunker as an escape hatch — for example, when a parser's native chunker produces unexpected results, or when consistent chunking behaviour across all parser types is desired.
>
> **Acceptance Criteria:**
> 1. Given `chunker="native"` and a Docling-parsed document, `HybridChunker` is used for chunking.
> 2. Given `chunker="markdown"` and a Docling-parsed document, the markdown-based heading-aware splitter is used, operating on `ParseResult.markdown`.
> 3. Given `chunker="markdown"` and a code file, the markdown-based splitter is used (the code's fenced markdown block is split by size, not by AST boundaries).
> 4. The default value is `"native"`.

> **FR-3321: Markdown Chunker Fallback Implementation** | Priority: MUST
>
> The system SHALL provide a markdown-based chunker implementation that any parser can delegate to when `chunker="markdown"` is configured. This chunker SHALL:
>
> 1. Accept a `ParseResult` (specifically its `markdown` field).
> 2. Split on markdown heading boundaries.
> 3. Respect `chunk_size` and `chunk_overlap` from `IngestionConfig`.
> 4. Produce `Chunk` objects with `section_path`, `heading`, and `heading_level` derived from markdown `#` nesting.
> 5. Treat markdown table blocks as atomic units.
>
> This is the same chunker used by the plain text parser (FR-3282), extracted as a shared utility.
>
> **Rationale:** A shared markdown chunker ensures consistent fallback behaviour across all parser types. It also serves as the native chunker for the plain text parser, avoiding duplication.
>
> **Acceptance Criteria:**
> 1. The markdown chunker is a standalone function/class, not embedded inside any specific parser.
> 2. Given `chunker="markdown"`, every parser type (document, code, text) delegates to this same implementation.
> 3. Output `Chunk` objects satisfy the FR-3202 contract.

> **FR-3322: Chunker Override Validation** | Priority: MUST
>
> The system SHALL validate the `chunker` configuration value at startup. Invalid values (anything other than `"native"` or `"markdown"`) SHALL cause a configuration error that halts pipeline startup.
>
> **Rationale:** A typo in the chunker setting (e.g., `chunker="markdwon"`) would silently fall through to unexpected behaviour without validation.
>
> **Acceptance Criteria:**
> 1. Given `chunker="native"`, validation passes.
> 2. Given `chunker="markdown"`, validation passes.
> 3. Given `chunker="hybrid"`, validation fails with a clear error message listing valid options.

> **FR-3323: Chunker Override Logging** | Priority: SHOULD
>
> When `chunker="markdown"` is configured, the system SHOULD log a warning at pipeline startup indicating that native chunking is being overridden. The warning SHALL indicate the trade-off: markdown chunking produces slightly less heading metadata than native chunking for parsers that support rich heading hierarchies (e.g., Docling `HybridChunker`).
>
> **Rationale:** The markdown override is an escape hatch, not the recommended path. A startup warning ensures operators are aware of the quality trade-off.
>
> **Acceptance Criteria:**
> 1. Given `chunker="markdown"`, a WARNING-level log message is emitted during startup.
> 2. Given `chunker="native"`, no override warning is emitted.

---

### 3.7 VLM Mode Validation (FR-3340–FR-3359)

> **FR-3340: VLM Mode Mutual Exclusion Guard** | Priority: MUST
>
> The system SHALL validate at pipeline startup that `vlm_mode="builtin"` and `enable_multimodal_processing=true` are NOT both active simultaneously. If both are active, the system SHALL raise a configuration error and halt startup.
>
> The error message SHALL clearly state:
> - Both settings are active.
> - They are mutually exclusive.
> - Which one to disable and what each controls.
>
> **Rationale:** `vlm_mode="builtin"` causes Docling's SmolVLM to describe figures at parse time (within the document parser). `enable_multimodal_processing=true` causes the Phase 1 multimodal processing node (`vision.py`) to describe figures independently using an external VLM. If both are active, every figure image is processed twice by two different VLMs, wasting compute, producing conflicting descriptions, and potentially corrupting downstream content with duplicate figure text.
>
> **Acceptance Criteria:**
> 1. Given `vlm_mode="builtin"` and `enable_multimodal_processing=true`, the pipeline raises a `ConfigurationError` (or equivalent) before processing any file.
> 2. The error message names both settings and explains they are mutually exclusive.
> 3. Given `vlm_mode="builtin"` and `enable_multimodal_processing=false`, startup proceeds normally.
> 4. Given `vlm_mode="disabled"` and `enable_multimodal_processing=true`, startup proceeds normally.
> 5. Given `vlm_mode="external"` and `enable_multimodal_processing=true`, startup proceeds normally (external VLM is post-chunking, multimodal processing is pre-chunking; they serve different purposes).

> **FR-3341: VLM Mode Validation — Integration with Design Check** | Priority: MUST
>
> The VLM mode mutual exclusion check SHALL be integrated into the existing `IngestionDesignCheck` validation framework (see `IngestionConfig` design check in `src/ingest/common/types.py`). The check SHALL:
>
> 1. Be executed as part of the standard config validation pass.
> 2. Produce an error (not a warning) that sets `IngestionDesignCheck.ok = False`.
> 3. Be testable in isolation via the design check function.
>
> **Rationale:** Integrating with the existing validation framework ensures the check is not bypassed and follows the established config validation pattern.
>
> **Acceptance Criteria:**
> 1. The design check function returns `ok=False` with a descriptive error when both settings conflict.
> 2. The design check function returns no VLM-related error when the settings are compatible.
> 3. A unit test exercises all four combinations of `vlm_mode` x `enable_multimodal_processing`.

> **FR-3342: VLM Mode Validation — External + Multimodal Coexistence** | Priority: SHOULD
>
> When `vlm_mode="external"` and `enable_multimodal_processing=true` are both active, the system SHOULD log an informational message at startup clarifying that:
>
> - `enable_multimodal_processing` processes figures in the Phase 1 multimodal node (pre-chunking).
> - `vlm_mode="external"` enables post-chunking VLM enrichment in Phase 2.
> - Both being active is valid but means figures are processed at two different pipeline stages for different purposes.
>
> **Rationale:** While this combination is valid (pre-chunking multimodal adds figure notes to the document; post-chunking VLM enriches individual chunks), it may surprise operators who expect only one VLM path to be active. An informational log prevents confusion without blocking the configuration.
>
> **Acceptance Criteria:**
> 1. Given `vlm_mode="external"` and `enable_multimodal_processing=true`, an INFO-level log message is emitted.
> 2. The message explains what each setting does and why both being active is intentional.
> 3. No error is raised — this is informational only.

---

## 4. Traceability Matrix

| FR ID | Gap | Component | Depends On | Companion Spec Reference |
|-------|-----|-----------|------------|--------------------------|
| FR-3200 | 8 | Abstract interface | — | — |
| FR-3201 | 8 | ParseResult contract | FR-3200 | — |
| FR-3202 | 8 | Chunk contract | FR-3200 | — |
| FR-3203 | 8 | Mandatory parser | FR-3200 | — |
| FR-3204 | 8 | Readiness check | FR-3200, FR-3203 | DOCUMENT_PROCESSING_SPEC.md FR-200 |
| FR-3205 | 8 | Encapsulation | FR-3200, FR-3201 | DOCLING_CHUNKING_SPEC.md FR-2000 |
| FR-3206 | 8 | Instance lifecycle | FR-3205 | — |
| FR-3207 | 8 | Warmup method | FR-3204 | DOCUMENT_PROCESSING_SPEC.md FR-210 |
| FR-3220 | 8 | Document parser formats | FR-3200 | DOCUMENT_PROCESSING_SPEC.md FR-101 |
| FR-3221 | 8 | Docling implementation | FR-3200, FR-3205 | DOCLING_CHUNKING_SPEC.md FR-2100 |
| FR-3222 | 8 | DeepDoc implementation | FR-3200 | — |
| FR-3223 | 8 | Chunk heading metadata | FR-3202 | DOCLING_CHUNKING_SPEC.md FR-2101 |
| FR-3224 | 8 | VLM mode passthrough | FR-3340 | DOCLING_CHUNKING_SPEC.md FR-2200 |
| FR-3250 | 8b | Code parser (tree-sitter) | FR-3200 | — |
| FR-3251 | 8b | Supported languages | FR-3250 | — |
| FR-3252 | 8b | AST-guided chunking | FR-3250, FR-3202 | — |
| FR-3253 | 8b | Code chunk metadata | FR-3252, FR-3202 | — |
| FR-3254 | 8b | Deterministic KG extraction | FR-3250, FR-3253 | EMBEDDING_PIPELINE_SPEC.md (KG storage) |
| FR-3255 | 8b | No code-to-NL | FR-3250 | — |
| FR-3256 | 8b | Code ParseResult | FR-3201, FR-3250 | — |
| FR-3280 | 8b | Plain text parser formats | FR-3200 | DOCUMENT_PROCESSING_SPEC.md FR-101 |
| FR-3281 | 8b | Minimal processing | FR-3280 | — |
| FR-3282 | 8b | Markdown-based chunking | FR-3280, FR-3202 | — |
| FR-3300 | 8/8b | Extension-based routing | FR-3200, FR-3220, FR-3250, FR-3280 | — |
| FR-3301 | 8/8b | Parser override config | FR-3300 | — |
| FR-3302 | 8/8b | Unrecognised extension | FR-3300, FR-3280 | — |
| FR-3303 | 8/8b | Parser registry | FR-3200, FR-3300 | — |
| FR-3320 | 8 | Chunker override setting | FR-3200, FR-3202 | — |
| FR-3321 | 8 | Markdown chunker fallback | FR-3320, FR-3282 | DOCLING_CHUNKING_SPEC.md FR-2300 |
| FR-3322 | 8 | Chunker override validation | FR-3320 | — |
| FR-3323 | 8 | Chunker override logging | FR-3320 | — |
| FR-3340 | 3 | VLM mutual exclusion guard | — | DOCLING_CHUNKING_SPEC.md FR-2200 |
| FR-3341 | 3 | Design check integration | FR-3340 | — |
| FR-3342 | 3 | External + multimodal info | FR-3340 | — |

---

## 5. Migration Notes

### 5.1 Impact on Existing Specifications

This specification introduces requirements that refine or supersede behaviour in companion specifications:

| Companion Spec | Affected FRs | Nature of Change |
|---------------|-------------|-----------------|
| DOCUMENT_PROCESSING_SPEC.md | FR-200–FR-299 (Structure Detection) | Structure detection node now delegates to the parser abstraction rather than calling Docling directly. |
| DOCLING_CHUNKING_SPEC.md | FR-2000–FR-2099 (DoclingDocument Preservation) | `DoclingDocument` no longer crosses the pipeline boundary. It is encapsulated inside the Docling parser class per FR-3205. DOCLING_CHUNKING_SPEC.md remains the authoritative reference for Docling-specific chunking behaviour (HybridChunker configuration, token limits, merge semantics). |
| DOCLING_CHUNKING_SPEC.md | FR-2300–FR-2399 (Fallback Pipeline) | The markdown fallback chunker is promoted to a shared utility (FR-3321) available to all parser types, not just as a Docling fallback. |
| EMBEDDING_PIPELINE_SPEC.md | FR-600–FR-699 (Chunking) | The chunking node receives `Chunk` objects from the parser abstraction rather than directly invoking `HybridChunker` or the markdown splitter. |

### 5.2 State Schema Changes

The following changes to `IngestState` / `EmbeddingPipelineState` are implied:

- **Remove:** `docling_document` key. Parser-internal objects no longer appear in pipeline state (FR-3205).
- **Add:** `parse_result` key of type `ParseResult` (FR-3201).
- **Add:** `chunks` key populated by parser `chunk()` output conforming to the `Chunk` contract (FR-3202).

### 5.3 Configuration Changes

The following `IngestionConfig` fields are introduced or modified:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `parser_strategy` | `str` | `"auto"` | Parser selection mode: `"auto"`, `"document"`, `"code"`, `"text"` (FR-3301). |
| `chunker` | `str` | `"native"` | Chunker selection: `"native"` or `"markdown"` (FR-3320). |

Existing fields (`enable_docling_parser`, `docling_model`, `vlm_mode`, `enable_multimodal_processing`) retain their meaning. The VLM mutual exclusion guard (FR-3340) adds a validation constraint on the combination of `vlm_mode` and `enable_multimodal_processing`.

---

## Appendix A: Extension-to-Strategy Mapping

The canonical mapping from file extension to parser strategy. Extensions are matched case-insensitively.

| Extension | Strategy | Parser |
|-----------|----------|--------|
| `.pdf` | Document | Docling / DeepDoc |
| `.docx` | Document | Docling / DeepDoc |
| `.pptx` | Document | Docling / DeepDoc |
| `.png` | Document | Docling / DeepDoc |
| `.jpg`, `.jpeg` | Document | Docling / DeepDoc |
| `.tiff` | Document | Docling / DeepDoc |
| `.bmp` | Document | Docling / DeepDoc |
| `.py` | Code | tree-sitter |
| `.rs` | Code | tree-sitter |
| `.go` | Code | tree-sitter |
| `.ts`, `.tsx` | Code | tree-sitter |
| `.js`, `.jsx` | Code | tree-sitter |
| `.java` | Code | tree-sitter |
| `.c`, `.h` | Code | tree-sitter |
| `.cpp`, `.hpp`, `.cc`, `.cxx` | Code | tree-sitter |
| `.cs` | Code | tree-sitter |
| `.rb` | Code | tree-sitter |
| `.kt` | Code | tree-sitter |
| `.swift` | Code | tree-sitter |
| `.scala` | Code | tree-sitter |
| `.sh`, `.bash`, `.zsh` | Code | tree-sitter |
| `.yaml`, `.yml` | Code | tree-sitter |
| `.toml` | Code | tree-sitter |
| `.json` | Code | tree-sitter |
| `Dockerfile` | Code | tree-sitter |
| `Makefile` | Code | tree-sitter |
| `.md` | Plain Text | Heading-aware splitter |
| `.txt` | Plain Text | Heading-aware splitter |
| `.rst` | Plain Text | Heading-aware splitter |
| `.html`, `.htm` | Plain Text | Heading-aware splitter |
| *(other)* | Plain Text (fallback) | Heading-aware splitter |

## Appendix B: Chunk Extra Metadata by Strategy

| Strategy | `extra_metadata` Keys | Description |
|----------|----------------------|-------------|
| Document | *(empty or parser-specific)* | Document parsers MAY include parser-specific metadata but are not required to. |
| Code | `language`, `file_path`, `function_name`, `class_name`, `docstring`, `imports`, `decorators` | Rich AST-derived metadata per FR-3253. |
| Code (KG) | `kg_relationships` | List of `{type, source, target}` dicts for deterministic KG extraction per FR-3254. |
| Plain Text | *(empty)* | Plain text parser does not add extra metadata beyond the core `Chunk` fields. |

## Appendix C: VLM Mode Compatibility Matrix

| `vlm_mode` | `enable_multimodal_processing` | Result |
|------------|-------------------------------|--------|
| `"disabled"` | `false` | Valid. No VLM processing. |
| `"disabled"` | `true` | Valid. Phase 1 multimodal node processes figures using external VLM via `vision.py`. |
| `"builtin"` | `false` | Valid. Docling SmolVLM describes figures at parse time. |
| `"builtin"` | `true` | **INVALID.** Configuration error per FR-3340. Double VLM processing. |
| `"external"` | `false` | Valid. Post-chunking VLM enrichment only. |
| `"external"` | `true` | Valid (with info log per FR-3342). Pre-chunking + post-chunking VLM at different stages. |
