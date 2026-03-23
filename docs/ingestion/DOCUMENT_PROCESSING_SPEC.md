# Document Processing Pipeline — Specification (v1.0.0)

## Document Information

> **Document intent:** This is a formal specification for the **Document Processing Pipeline** — the five-node ingestion phase responsible for transforming raw source documents into clean, structured Markdown documents persisted to the Clean Document Store. The Embedding Pipeline reads from the Clean Document Store; it does not receive in-memory output from this pipeline.
> For the Embedding Pipeline functional requirements (FR-600 through FR-1304), see `EMBEDDING_PIPELINE_SPEC.md`.
> For cross-cutting platform requirements (re-ingestion, config, error handling, data model, NFR), see `INGESTION_PLATFORM_SPEC.md`.

| Field | Value |
|-------|-------|
| System | AION RAG Document Embedding Pipeline |
| Document Type | Pipeline Specification — Document Processing Phase |
| Companion Documents | EMBEDDING_PIPELINE_SPEC.md (Embedding Phase Functional Requirements), INGESTION_PLATFORM_SPEC.md (Platform/Cross-Cutting Requirements), DOCUMENT_PROCESSING_SPEC_SUMMARY.md (Phase 1 Summary), EMBEDDING_PIPELINE_SPEC_SUMMARY.md (Phase 2 Summary), DOCUMENT_PROCESSING_IMPLEMENTATION.md (Phase 1 Implementation Guide) |
| Version | 1.0.0 |
| Status | Draft |
| Supersedes | INGESTION_PIPELINE_SPEC.md (sections 3.1–3.5) |

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2026-03-18 | AI Assistant | Created by splitting INGESTION_PIPELINE_SPEC.md at the Document Processing / Embedding boundary. Contains FR-100 through FR-599 and adds the Clean Document Store output contract (FR-580–FR-589). |

---

## 1. Purpose and Scope

### 1.1 Problem Statement

ASIC design organisations accumulate critical engineering knowledge across hundreds of documents: specifications, design guides, runbooks, standard operating procedures, and project reports. This knowledge is fragmented across file servers, SharePoint, and individual workstations. When engineers leave, their contextual understanding leaves with them.

Existing search tools fail for engineering documentation because:

1. The same technical term carries different meaning across domains (e.g., "clock domain" spans front-end design, DFT, verification, and physical design).
2. Knowledge exists at varying levels of maturity — from formally approved specifications to an individual engineer's utility script — with no mechanism to distinguish authoritative from informal sources.
3. Documents rely on sequential reading order; isolated paragraphs lose meaning without surrounding context (e.g., "the same voltage" is ambiguous outside its original section).

### 1.2 Scope

The Document Processing Pipeline SHALL transform engineering documents into clean, structured Markdown documents persisted to the Clean Document Store. Each persisted document is the sole input to the Embedding Pipeline.

The system is designed for a mission-critical engineering environment where incorrect retrieval (e.g., returning a 4nm specification when the query is about a 12nm specification) could propagate into design errors.

**Entry point:** Source document file (PDF, DOCX, PPTX, XLSX, Markdown, HTML, RST, plain text) on local filesystem.

**Exit point:** Clean Markdown document persisted to the Clean Document Store (one `.md` file and one `.meta.json` file per source document).

**In scope:**

- Document ingestion and processing
- Document structure detection and cleaning
- Multimodal processing (figure-to-text conversion)
- Text cleaning and normalisation
- Document refactoring for self-contained paragraphs
- Document review tier management
- Re-ingestion of updated documents
- Batch processing of document directories

### 1.3 Terminology

The following terms are used throughout this specification. A complete glossary is provided in the companion platform specification.

| Term | Definition |
|------|-----------|
| RAG | Retrieval-Augmented Generation — a pattern where retrieved context is provided to an LLM for answer generation |
| Knowledge Graph | A graph of entities and relationships extracted from documents |
| Hybrid Search | Combined vector similarity search and BM25 keyword search |
| BM25 | Best Matching 25 — a probabilistic ranking function for keyword-based text search |
| Review Tier | A trust classification (Fully/Partially/Self Reviewed) controlling a document's visibility in search results |
| Re-ingestion | Processing a previously ingested document again, cleaning up old data and inserting new data |
| DAG | Directed Acyclic Graph — the processing pipeline topology |
| VLM | Vision-Language Model — a multimodal model that can process both images and text |
| Deterministic ID | An identifier derived from content via cryptographic hashing, ensuring the same input always produces the same ID |
| Idempotent | An operation that produces the same result whether applied once or multiple times |
| Clean Document Store | The persistent storage boundary between the Document Processing Pipeline and the Embedding Pipeline; contains one `.md` and one `.meta.json` per source document |
| source_key | A stable, deterministic identifier derived from the source file path, used to name artefacts in the Clean Document Store |

### 1.4 Requirement Priority Levels

This specification uses the key words defined in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) to indicate requirement levels:

| Keyword | Meaning |
|---------|---------|
| **MUST** / **SHALL** | Absolute requirement. The system cannot be considered conformant without implementing this. |
| **SHOULD** / **RECOMMENDED** | There may be valid reasons to omit this in particular circumstances, but the full implications must be understood and carefully weighed. |
| **MAY** / **OPTIONAL** | Truly optional. The system is conformant whether or not this is implemented. |

### 1.5 Requirement Format

Requirements in this specification follow a structured ID convention:

| Prefix | Meaning |
|--------|---------|
| **FR-** | Functional Requirement |
| **NFR-** | Non-Functional Requirement |
| **SC-** | Security / Compliance Requirement |

Requirement ID ranges are allocated to sections as follows:

| ID Range | Section |
|----------|---------|
| FR-100–FR-199 | 3.1 Document Ingestion |
| FR-200–FR-299 | 3.2 Structure Detection |
| FR-300–FR-399 | 3.3 Multimodal Processing |
| FR-400–FR-499 | 3.4 Text Cleaning |
| FR-500–FR-599 | 3.5 Document Refactoring |
| FR-580–FR-589 | 3.6 Clean Document Store Output Contract |

### 1.6 Assumptions & Constraints

| ID | Assumption / Constraint | Impact if Violated |
|----|------------------------|--------------------|
| A-1 | Python 3.11+ runtime | Type hint syntax and match statements fail |
| A-2 | LangGraph/LangChain available | Pipeline DAG orchestration unavailable |
| A-4 | LLM provider accessible (local or API) | LLM-dependent stages fall back to deterministic alternatives |
| A-5 | Sequential document processing (no concurrent ingestion of same document) | Race conditions on re-ingestion cleanup |
| A-6 | Documents ≤ ~100 pages | Larger documents should be pre-split; memory budget is < 2 GB peak RSS |

### 1.7 Design Principles

The following principles SHALL guide all design and implementation decisions:

| Principle | Description |
|-----------|-------------|
| **Swappability over lock-in** | Every external dependency (LLM provider, embedding model, vector store, structure detector) SHALL be behind a configuration interface. Changing providers SHALL require configuration changes, not code changes. |
| **Fail-safe over fail-fast** | When an LLM call fails, the pipeline SHALL fall back to deterministic alternatives rather than halting. A single flawed LLM response SHALL NOT halt a batch job. |
| **Context preservation over compression** | The pipeline SHALL preserve every numerical value, specification, and procedural step. Content restructuring SHALL NOT summarise or remove information. |
| **Configuration-driven behaviour** | Pipeline behaviour (skip/enable processing stages, dry run mode) SHALL be controlled via a single configuration system with runtime overrides. |

### 1.8 Out of Scope

**Out of scope:**

- Chunking, embedding, vector storage, knowledge graph extraction and storage (see EMBEDDING_PIPELINE_SPEC.md)
- Query processing, reranking, and answer generation (downstream retrieval layer)
- User authentication and access control
- Document authoring or editing
- Real-time document change detection (push-based ingestion)

**Out of scope — broader platform components (see Strategic Proposal):**

The RAG Document Embedding Pipeline is one component of a larger AI-Enabled Knowledge Management Platform. The following platform components are covered by the Strategic Proposal document and are NOT part of this specification:

- Skills repository and anti-skills validation framework
- AI-assisted documentation agents (background monitoring, draft generation)
- Code standardisation and Python migration initiative
- Web dashboard UI (planned for Phase 3 deployment)
- Reranker model deployment and tuning (downstream retrieval layer)
- Adoption strategy, change management, and gamification

---

## 2. Processing Pipeline Overview

### 2.1 High-Level Architecture

The Document Processing Pipeline SHALL process documents through a directed acyclic graph (DAG) of five processing stages, implemented using a graph-based orchestration framework (LangGraph, which is part of the LangChain ecosystem). Each document SHALL flow through the following stages in order, producing a persisted clean document in the Clean Document Store:

```text
Source Document (filesystem path)
    │
    ▼
┌──────────────────────────────────────┐
│ [1] DOCUMENT INGESTION               │
│     Read file, detect format,        │
│     compute hash, detect re-ingest   │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [2] STRUCTURE DETECTION              │
│     Parse hierarchical section tree, │
│     extract figures and tables       │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [3] MULTIMODAL PROCESSING [optional] │
│     Convert figures to text via VLM  │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [4] TEXT CLEANING                    │
│     Normalise text, remove           │
│     boilerplate, integrate figures   │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [5] DOCUMENT REFACTORING [optional]  │
│     Restructure for self-contained   │
│     paragraphs, resolve references   │
└──────────────┬───────────────────────┘
               │
               ▼
    ┌─────────────────────────────────┐
    │     CLEAN DOCUMENT STORE        │
    │  {source_key}.md + .meta.json   │
    │  persisted to disk per document │
    └─────────────────────────────────┘
         (read by EMBEDDING_PIPELINE_SPEC.md)
```

Stages marked with `[optional]` are conditional and may be skipped based on configuration or document characteristics.

### 2.2 Stage Descriptions

| # | Stage | Purpose | Conditional |
|---|-------|---------|-------------|
| 1 | Document Ingestion | Read source file, detect format, compute content hash, detect re-ingestion | No |
| 2 | Structure Detection | Parse document into hierarchical section tree, extract figures and tables | No |
| 3 | Multimodal Processing | Convert detected figures into text descriptions using a vision-language model | Yes — only if figures detected (tentatively convert figures to text first) |
| 4 | Text Cleaning | Normalise text, remove boilerplate, integrate figure/table descriptions | No |
| 5 | Document Refactoring | Restructure content for self-containedness, resolve implicit references | Yes — skippable via config |

### 2.3 Processing Stage Independence

Each processing stage SHALL:

- Operate on a shared document state object
- Read only from fields populated by upstream stages
- Write only to its own designated output fields
- Be individually replaceable without affecting other stages
- Handle its own errors without crashing the pipeline

---

## 3. Functional Requirements

### 3.1 Document Ingestion (FR-100)

> **FR-101** | Priority: MUST
> **Description:** The system MUST support the following input formats:
>
> | Format | Extension(s) |
> |--------|-------------|
> | PDF | `.pdf` |
> | Word | `.docx` |
> | PowerPoint | `.pptx` |
> | Excel | `.xlsx` |
> | Markdown | `.md` |
> | HTML | `.html`, `.htm` |
> | reStructuredText | `.rst` |
> | Plain text | `.txt` |
>
> **Rationale:** Engineering knowledge is spread across multiple document formats; without broad format coverage, significant portions of organisational knowledge remain unsearchable, directly contributing to the knowledge fragmentation problem.
>
> **Acceptance Criteria:**
> 1. Given one file of each supported format (PDF spec sheet, DOCX design guide, PPTX review deck, XLSX pin table, Markdown runbook, HTML datasheet, RST procedure, plain-text README), all eight ingest successfully and produce non-empty text output.
> 2. Given a `.wav` file, the system does not attempt format-specific extraction and classifies the format as UNKNOWN.

> **FR-102** | Priority: MUST
>
> **Description:** The system MUST detect document format from file extension with a fallback to UNKNOWN for unrecognised extensions.
>
> **Rationale:** Reliable format detection is a prerequisite for routing documents to the correct text extractor. Falling back to UNKNOWN rather than guessing prevents misinterpretation of binary data. Supports the fail-safe-over-fail-fast principle.
>
> **Acceptance Criteria:**
> 1. Given a file named `clock_tree_spec.pdf`, the system detects format as PDF.
> 2. Given a file named `notes.xyz`, the system assigns format UNKNOWN.
> 3. Given a file with no extension, the system assigns format UNKNOWN.

> **FR-103** | Priority: MUST
>
> **Description:** The system MUST convert all input formats to text before downstream processing. Binary formats (PDF, DOCX, PPTX, XLSX) MUST go through format-specific text extractors.
>
> **Rationale:** A uniform text representation is the contract between ingestion and all downstream stages. Without this normalisation, every downstream stage would need format-specific logic, violating stage independence.
>
> **Acceptance Criteria:**
> 1. Given a PDF containing a voltage specification table, the text extractor produces a text output that preserves the table content.
> 2. Given a DOCX with embedded images and headings, the extractor outputs text with heading structure intact.
> 3. For all supported formats, the output is a plain text or markdown string — no binary content remains.

> **FR-104** | Priority: MUST
>
> **Description:** The system MUST extract text from PowerPoint files including text frames, speaker notes, and table cells, preserving slide order and structure.
>
> **Rationale:** Engineering review presentations often contain critical design decisions in speaker notes and specification data in table cells. Omitting these would lose knowledge that exists nowhere else. Supports the context-preservation principle.
>
> **Acceptance Criteria:**
> 1. Given a PPTX with 5 slides where slide 3 contains a table of clock frequencies and slide 4 has speaker notes explaining a design trade-off, the extracted text includes both the table content from slide 3 and the speaker notes from slide 4 in correct slide order.
> 2. Given a PPTX with an empty slide, that slide produces no text but does not cause an error.

> **FR-105** | Priority: MUST
>
> **Description:** The system MUST extract text from Excel files including all sheets, with table detection and markdown conversion. Named ranges and cell references MUST be preserved.
>
> **Rationale:** Excel files in ASIC organisations commonly contain pin tables, power budgets, and register maps across multiple sheets. Losing sheet context or cell references would make the extracted data ambiguous. Supports the context-preservation principle.
>
> **Acceptance Criteria:**
> 1. Given an XLSX with sheets "Power_Budget" and "Pin_Table", the system extracts text from both sheets with sheet names as section headers.
> 2. Given a sheet containing a table with headers `[Pin, Direction, Voltage, Description]`, the output contains a markdown table preserving all columns and rows.
> 3. Given a named range "VDD_CORE_SPECS", the name appears in the extracted text.

> **FR-106** | Priority: MUST
>
> **Description:** The system MUST compute a SHA-256 content hash of the source file for change detection and re-ingestion purposes.
>
> **Rationale:** Content hashing is the foundation of the re-ingestion mechanism; without it the system cannot detect whether a document has changed, leading to either unnecessary reprocessing or stale data. Supports the idempotency-by-construction principle.
>
> **Acceptance Criteria:**
> 1. Given the same file ingested twice, the system produces identical SHA-256 hashes both times.
> 2. Given a file where a single character is changed, the system produces a different hash.
> 3. The hash is a 64-character lowercase hexadecimal string.

> **FR-107** | Priority: MUST
>
> **Description:** The system MUST generate deterministic document identifiers derived from the source file path, ensuring the same file always produces the same document ID.
>
> **Rationale:** Deterministic IDs are essential for re-ingestion — the system must be able to locate previously ingested data for the same document. Supports the idempotency-by-construction principle.
>
> **Acceptance Criteria:**
> 1. Given the file path `/data/specs/clock_tree_spec_v2.pdf` ingested twice, the system produces the same document ID both times.
> 2. Given two different file paths, the system produces different document IDs.

> **FR-108** | Priority: MUST
>
> **Description:** The system MUST handle text encoding variations with a fallback chain (UTF-8 → Latin-1 → CP1252 → UTF-8 with replacement).
>
> **Rationale:** Legacy engineering documents frequently use non-UTF-8 encodings (e.g., Windows-1252 from older Word exports). Without a fallback chain, these documents would fail ingestion entirely, losing valuable knowledge. Supports the fail-safe-over-fail-fast principle.
>
> **Acceptance Criteria:**
> 1. Given a Latin-1 encoded text file containing the character `µ` (micro sign), the system successfully decodes and preserves the character.
> 2. Given a file with invalid byte sequences in all encodings, the system falls back to UTF-8 with replacement characters rather than raising an exception.

> **FR-109** | Priority: MUST
>
> **Description:** The system MUST load and make available a configurable domain vocabulary (abbreviation dictionary) for use by downstream stages.
>
> **Rationale:** ASIC/semiconductor terminology is highly domain-specific (e.g., DFT, PVT, CDC). A shared vocabulary ensures consistent abbreviation expansion across all stages and prevents misinterpretation of terms that differ across domains. Addresses the problem of term ambiguity across domains.
>
> **Acceptance Criteria:**
> 1. Given a domain vocabulary file containing `{"DFT": "Design for Testability", "CDC": "Clock Domain Crossing"}`, the system loads the vocabulary and makes it accessible to downstream stages.
> 2. Given no vocabulary file configured, the system starts with an empty vocabulary without error.

> **FR-110** | Priority: SHOULD
>
> **Description:** The system SHOULD support future addition of new input formats (e.g., SystemVerilog via AST-based extraction, Visio, images via OCR) without architectural changes.
>
> **Rationale:** Engineering toolchains evolve and new document types emerge; the ingestion layer must be extensible without requiring pipeline redesign. Supports the swappability-over-lock-in principle.
>
> **Acceptance Criteria:**
> 1. A new format handler can be added by implementing a defined extractor interface and registering it in configuration, without modifying existing extractor code or pipeline orchestration logic.
> 2. No existing unit tests break when the new handler is added.

> **FR-111** | Priority: MUST
>
> **Description:** Tool log files (.log) MUST be excluded from the vector embedding pipeline. Logs are better served by direct keyword search.
>
> **Rationale:** Log files are high-volume, low-semantic-density content that would pollute the vector space with noise, degrading retrieval quality for actual engineering documents.
>
> **Acceptance Criteria:**
> 1. Given a directory containing `synthesis_run.log` and `clock_spec.pdf`, a batch ingestion run processes `clock_spec.pdf` and skips `synthesis_run.log`.
> 2. The system logs a message indicating the `.log` file was excluded.

> **FR-112** | Priority: MUST
>
> **Description:** The system MUST support ingestion from local filesystem paths (absolute and relative).
>
> **Rationale:** Local filesystem is the primary document source for engineering teams; this is the baseline ingestion capability required before any remote integrations.
>
> **Acceptance Criteria:**
> 1. Given an absolute path `/data/specs/clock_spec.pdf`, the system reads and ingests the file.
> 2. Given a relative path `./specs/clock_spec.pdf`, the system resolves it against the working directory and ingests the file.
> 3. Given a non-existent path, the system raises a clear error indicating the file was not found.

> **FR-113** | Priority: SHOULD
>
> **Description:** The system SHOULD support future integration with SharePoint document libraries as a document source without architectural changes. SharePoint integration is planned for Phase 3.
>
> **Rationale:** Many organisations store engineering documents in SharePoint; supporting it as a source expands coverage of fragmented knowledge. Supports the swappability-over-lock-in principle.
>
> **Acceptance Criteria:**
> 1. The document source interface is abstracted such that a SharePoint adapter can be implemented without modifying the ingestion pipeline.
> 2. The adapter would need to implement a defined source interface (e.g., `list_documents()`, `download_document()`) and be selectable via configuration.

### 3.2 Structure Detection (FR-200)

> **FR-201** | Priority: MUST
>
> **Description:** The system MUST parse documents into a hierarchical section tree preserving heading levels and parent-child relationships.
>
> **Rationale:** Engineering documents derive meaning from their hierarchical structure — a voltage value under "3.3V IO Domain" means something different than under "1.0V Core Domain". Losing this hierarchy causes the context-loss problem identified in the problem statement.
>
> **Acceptance Criteria:**
> 1. Given a document with headings H1 "Power Specifications" → H2 "Core Domain" → H3 "Voltage Limits", the system produces a tree where "Voltage Limits" is a child of "Core Domain", which is a child of "Power Specifications".
> 2. Given a flat document with no headings, the system produces a single root node containing all content.

> **FR-202** | Priority: MUST
>
> **Description:** The system MUST extract tables with headers, rows, and a text representation suitable for downstream processing.
>
> **Rationale:** Tables in ASIC specifications carry dense, high-value data (pin tables, timing parameters, register maps). A text representation ensures this data is searchable and preserved through the pipeline. Supports the context-preservation principle.
>
> **Acceptance Criteria:**
> 1. Given a table with headers `[Parameter, Min, Typ, Max, Unit]` and a row `[VDD_CORE, 0.95, 1.0, 1.05, V]`, the system extracts both headers and row data and produces a markdown table representation.
> 2. Given a table with merged cells, the system produces a best-effort extraction with no data loss.

> **FR-203** | Priority: MUST
>
> **Description:** The system MUST detect and extract figures with bounding boxes, captions, and surrounding text context.
>
> **Rationale:** Figures (block diagrams, timing diagrams, floorplans) convey information not present in the text. Capturing bounding boxes enables VLM processing; captions and surrounding text provide semantic anchoring for the generated description.
>
> **Acceptance Criteria:**
> 1. Given a PDF page containing a block diagram with caption "Figure 3: Clock Distribution Network", the system extracts the figure region, associates the caption text, and captures at least the preceding and following paragraphs as surrounding context.
> 2. Given a page with no figures, the figures list for that page is empty.

> **FR-204** | Priority: MUST
>
> **Description:** The system MUST export detected figure images to disk for multimodal processing when configured.
>
> **Rationale:** The VLM stage requires image files as input; exporting figures to disk decouples structure detection from multimodal processing, allowing each stage to operate independently.
>
> **Acceptance Criteria:**
> 1. Given a document with 3 detected figures and figure export enabled in configuration, the system writes 3 image files (PNG or similar) to the configured output directory.
> 2. File names include the document ID and figure index for traceability.
> 3. Given figure export disabled in configuration, no image files are written.

> **FR-205** | Priority: MUST
>
> **Description:** The system MUST auto-detect abbreviation definitions in the document text (e.g., "Design for Testability (DFT)", abbreviation tables) and merge them with the domain vocabulary.
>
> **Rationale:** Documents often define their own abbreviations that may not be in the global domain vocabulary. Auto-detection ensures downstream stages (refactoring, enrichment) can resolve document-specific terms. Addresses term ambiguity across domains.
>
> **Acceptance Criteria:**
> 1. Given text containing "Clock Domain Crossing (CDC) analysis ensures...", the system detects `CDC → Clock Domain Crossing` and adds it to the vocabulary.
> 2. Given an abbreviation table with rows `DFT | Design for Testability`, the system extracts all entries.
> 3. Given a conflict with the domain vocabulary (e.g., document defines "PD" as "Power Domain" but vocabulary has "PD" as "Physical Design"), the document-local definition takes precedence within that document's processing.

> **FR-206** | Priority: MUST
>
> **Description:** The system MUST compute an extraction confidence score (0.0–1.0) based on section tree depth, table completeness, text coherence, and character density.
>
> **Rationale:** Extraction quality varies significantly by document format and layout complexity. A confidence score enables downstream stages and operators to identify documents that may have lost structure during extraction.
>
> **Acceptance Criteria:**
> 1. Given a well-structured Markdown document with clear headings and tables, the confidence score is above 0.8.
> 2. Given a scanned PDF with OCR artefacts and no detectable headings, the confidence score is below 0.5.
> 3. The score is a float in the range [0.0, 1.0].

> **FR-207** | Priority: MUST
>
> **Description:** Documents with extraction confidence below a configurable threshold MUST be flagged for manual review but MUST continue through the pipeline.
>
> **Rationale:** Stopping the pipeline on low-confidence documents would block batch processing. Flagging ensures operators are alerted without halting the pipeline. Supports the fail-safe-over-fail-fast principle.
>
> **Acceptance Criteria:**
> 1. Given a confidence threshold configured at 0.6 and a document scoring 0.45, the system sets a `requires_manual_review` flag to true and continues processing.
> 2. Given a document scoring 0.75 with the same threshold, the flag is false.
> 3. The flagged document appears in pipeline output/logs with a review warning.

> **FR-208** | Priority: MUST
>
> **Description:** The structure detection provider MUST be swappable via configuration.
>
> **Rationale:** Different structure detection tools (e.g., Docling, Unstructured, custom parsers) have different strengths; the system must allow switching without code changes. Supports the swappability-over-lock-in principle.
>
> **Acceptance Criteria:**
> 1. Given configuration specifying provider A, the system uses provider A for structure detection.
> 2. Changing the configuration to provider B and re-running uses provider B with no code changes.
> 3. Both providers implement the same interface and produce compatible output structures.

### 3.3 Multimodal Processing (FR-300)

> **FR-301** | Priority: MUST
>
> **Description:** The system MUST convert detected figures into text descriptions using a vision-language model (VLM), making visual content searchable via text embeddings.
>
> **Rationale:** Figures (block diagrams, timing diagrams, layout views) contain critical engineering information that would be entirely lost from the search index without text conversion. This directly addresses knowledge fragmentation by making visual knowledge retrievable.
>
> **Acceptance Criteria:**
> 1. Given an extracted figure image of a clock distribution block diagram, the system sends it to the VLM and receives a text description.
> 2. The description is stored associated with the figure's ID.
> 3. Given a document with no figures, this stage produces no descriptions.

> **FR-302** | Priority: MUST
>
> **Description:** This stage MUST only execute when figures are detected in the document.
>
> **Rationale:** VLM calls are expensive (latency and cost). Skipping the stage entirely when no figures exist avoids unnecessary API calls and processing time.
>
> **Acceptance Criteria:**
> 1. Given a Markdown document with no figures, the multimodal processing stage is not invoked (no VLM API calls are made).
> 2. Given a PDF with 2 detected figures, the stage executes and processes both figures.

> **FR-303** | Priority: MUST
>
> **Description:** VLM descriptions MUST include diagram type, visible labels and values, key relationships, and numerical specifications.
>
> **Rationale:** Generic descriptions (e.g., "a block diagram") are useless for engineering retrieval. Descriptions must capture the specific technical content visible in the figure to enable precise search. Supports the context-preservation principle.
>
> **Acceptance Criteria:**
> 1. Given a timing diagram showing setup time = 0.5ns and hold time = 0.2ns for a flip-flop, the VLM description includes the diagram type ("timing diagram"), the numerical values (0.5ns, 0.2ns), and the relationship (setup/hold time for flip-flop).
> 2. The description does not merely say "a timing diagram".

> **FR-304** | Priority: MUST
>
> **Description:** VLM descriptions MUST NOT contain speculative or inferred information not visible in the figure.
>
> **Rationale:** In a mission-critical engineering environment, fabricated details in a figure description could propagate into design decisions. The system must never present LLM hallucinations as document content. Supports the context-preservation principle.
>
> **Acceptance Criteria:**
> 1. Given a block diagram showing modules A, B, and C connected in series, the description does not mention module D or speculate about internal implementation of any module.
> 2. A validation check can compare entities in the description against entities visible in the figure caption and surrounding text.

> **FR-305** | Priority: MUST
>
> **Description:** Each VLM-generated description MUST have an associated confidence score.
>
> **Rationale:** VLM output quality varies with figure complexity and clarity. A confidence score allows downstream stages and retrieval to weight or filter descriptions appropriately.
>
> **Acceptance Criteria:**
> 1. Given a VLM description, the system stores a confidence score as a float in [0.0, 1.0] alongside the description.
> 2. Given a clear, well-labelled schematic, the confidence score is higher than for a blurry or hand-drawn sketch.

> **FR-306** | Priority: MUST
>
> **Description:** The VLM provider MUST be swappable via configuration.
>
> **Rationale:** VLM technology is rapidly evolving; the system must allow switching providers (e.g., GPT-4V to Claude Vision) without code changes. Supports the swappability-over-lock-in principle.
>
> **Acceptance Criteria:**
> 1. Given configuration specifying VLM provider "openai/gpt-4o", the system uses that provider.
> 2. Changing the configuration to "anthropic/claude-sonnet" and re-running uses the new provider with no code changes.
> 3. Both providers are accessed through the same interface.

> **FR-307** | Priority: MUST
>
> **Description:** If the VLM call fails, the figure MUST be recorded without a description (confidence = 0.0).
>
> **Rationale:** A single failed VLM call must not halt processing of the entire document. The figure is still recorded so it can be reprocessed later. Supports the fail-safe-over-fail-fast principle.
>
> **Acceptance Criteria:**
> 1. Given a VLM API timeout or error for figure 2 of 5, the system records figure 2 with an empty description and confidence 0.0, then continues to process figures 3–5.
> 2. The pipeline does not raise an exception.
> 3. Pipeline logs record the failure with the figure ID and error details.

### 3.4 Text Cleaning (FR-400)

> **FR-401** | Priority: MUST
>
> **Description:** The system MUST normalise whitespace (collapse multiple spaces, limit consecutive newlines).
>
> **Rationale:** PDF and DOCX extraction frequently produces irregular whitespace that wastes token budget and degrades embedding quality. Normalisation ensures consistent input for chunking and embedding.
>
> **Acceptance Criteria:**
> 1. Given text with 5 consecutive spaces between words, the output contains a single space.
> 2. Given text with 6 consecutive newlines, the output contains no more than the configured maximum (e.g., 2).
> 3. Given text with tabs mixed with spaces, the output uses consistent spacing.

> **FR-402** | Priority: MUST
>
> **Description:** The system MUST remove boilerplate artefacts (page headers/footers, confidentiality notices, stray page numbers) using configurable patterns.
>
> **Rationale:** Boilerplate text (e.g., "CONFIDENTIAL — Company Internal" repeated on every page) adds noise to embeddings and wastes token capacity without contributing searchable knowledge. Supports the configuration-driven-behaviour principle.
>
> **Acceptance Criteria:**
> 1. Given a configurable pattern list including `"CONFIDENTIAL.*INTERNAL"` and text containing "CONFIDENTIAL — Company Internal" on 20 pages, all 20 occurrences are removed.
> 2. Given a pattern `"^Page \\d+$"`, stray page numbers like "Page 42" on their own line are removed.
> 3. Custom patterns can be added via configuration without code changes.

> **FR-403** | Priority: MUST
>
> **Description:** The system MUST detect and reduce repeated headers/footers (lines appearing more than 3 times) to a single occurrence.
>
> **Rationale:** Even without explicit pattern configuration, frequently repeated lines are almost certainly boilerplate. Automatic detection catches document-specific headers/footers that configurable patterns might miss.
>
> **Acceptance Criteria:**
> 1. Given a document where the line "ASIC Design Specification Rev 2.1" appears 15 times (once per page), the output contains this line exactly once.
> 2. Given a line that appears exactly 3 times in a document, it is preserved (threshold is "more than 3").
> 3. Given a line that appears 4 times, it is reduced to 1 occurrence.

> **FR-404** | Priority: MUST
>
> **Description:** The system MUST integrate VLM-generated figure descriptions into the text stream with figure ID markers.
>
> **Rationale:** Figure descriptions must be embedded in-line at the figure's original position so that chunking preserves the spatial relationship between figures and surrounding text. Supports the context-preservation principle.
>
> **Acceptance Criteria:**
> 1. Given a figure description for figure ID `fig_003` with text "Block diagram showing clock distribution from PLL to 4 clock domains", the text stream contains a marker such as `[FIGURE fig_003]` followed by the description at the position where the figure originally appeared.
> 2. Given a figure with no description (confidence = 0.0), only the marker is inserted with no description text.

> **FR-405** | Priority: MUST
>
> **Description:** The system MUST integrate table markdown representations into the text stream with table ID markers, preserving tabular data (e.g., voltage specifications, pin tables) in a searchable format.
>
> **Rationale:** Tables carry dense, high-value engineering data. Integrating them as markdown preserves structure while keeping the data in the text stream for chunking and embedding. Supports the context-preservation principle.
>
> **Acceptance Criteria:**
> 1. Given a table with ID `tbl_002` containing voltage specifications, the text stream includes a marker such as `[TABLE tbl_002]` followed by the markdown table representation.
> 2. The markdown preserves all headers, rows, and cell values from the original table.
> 3. Given a pin table with 50 rows, all 50 rows appear in the markdown output.

### 3.5 Document Refactoring (FR-500)

> **FR-501** | Priority: MUST
>
> **Description:** The system MUST support optional restructuring of document text to make each paragraph self-contained for retrieval, resolving implicit references (e.g., "as mentioned above") to explicit references (e.g., "the 1.8V core voltage specified in Section 1.2").
>
> **Rationale:** Isolated paragraphs lose meaning without surrounding context — this is a core problem identified in the problem statement (e.g., "the same voltage" is ambiguous outside its original section). Refactoring resolves this at ingestion time rather than burdening retrieval. Supports the context-preservation principle.
>
> **Acceptance Criteria:**
> 1. Given a paragraph containing "This voltage should not exceed the limit specified above", the refactored output replaces the implicit reference with the explicit value, e.g., "This voltage should not exceed the 1.05V maximum specified in Section 2.3 Core Power".
> 2. Given a paragraph with no implicit references, the text is returned unchanged.

> **FR-502** | Priority: MUST
>
> **Description:** Refactoring MUST be skippable via configuration.
>
> **Rationale:** Refactoring uses LLM calls which add latency and cost. Some deployments may prefer raw text. Supports the configuration-driven-behaviour principle.
>
> **Acceptance Criteria:**
> 1. Given configuration with `refactoring.enabled = false`, the refactoring stage is skipped entirely and the text passes through unchanged.
> 2. Given `refactoring.enabled = true`, the stage executes.
> 3. No LLM calls are made when the stage is disabled.

> **FR-503** | Priority: MUST
>
> **Description:** The refactoring process MUST use a self-correcting loop with configurable maximum iterations per section.
>
> **Rationale:** A single LLM pass may introduce errors or miss references. Iterative correction with a bounded loop prevents runaway processing while improving output quality.
>
> **Acceptance Criteria:**
> 1. Given `refactoring.max_iterations = 3`, the system performs at most 3 refactoring-validation cycles per section.
> 2. If iteration 2 passes validation, iteration 3 is not executed.
> 3. Given `max_iterations = 1`, only one pass is performed regardless of validation outcome.

> **FR-504** | Priority: MUST
>
> **Description:** Each refactoring iteration MUST include a fact-check validation that no information was added, removed, or distorted.
>
> **Rationale:** LLMs can hallucinate or subtly alter technical facts. In a mission-critical environment, a refactored paragraph claiming "1.2V" when the source says "1.0V" could cause a design error. Supports the context-preservation principle.
>
> **Acceptance Criteria:**
> 1. Given a source paragraph stating "VDD_CORE = 1.0V" and a refactored version that changes it to "VDD_CORE = 1.2V", the fact-check validation fails and the iteration is rejected.
> 2. Given a refactored version that only adds context ("VDD_CORE = 1.0V, as specified in Section 2.1"), the fact-check passes.

> **FR-505** | Priority: MUST
>
> **Description:** Each refactoring iteration MUST include a completeness check that no content was lost.
>
> **Rationale:** Refactoring must restructure, not summarise. Dropped sentences or values represent irreversible knowledge loss. Supports the context-preservation principle.
>
> **Acceptance Criteria:**
> 1. Given a source paragraph with 4 sentences and a refactored version with only 3 sentences (one dropped), the completeness check fails.
> 2. Given a refactored version that rephrases all 4 sentences but preserves all information, the completeness check passes.

> **FR-506** | Priority: MUST
>
> **Description:** Refactoring MUST adhere to the following constraints: never add information not in the source, never remove content, never change meaning, preserve all numerical values exactly, and only expand abbreviations found in the document or the domain vocabulary.
>
> **Rationale:** These constraints are the safety boundary for LLM-based content manipulation in a mission-critical environment. Violating any one of them could propagate incorrect information into engineering decisions. Supports the context-preservation principle.
>
> **Acceptance Criteria:**
> 1. Given source text "The PVT corners are nominal", the refactored text may expand to "The Process-Voltage-Temperature (PVT) corners are nominal" if PVT is in the vocabulary, but must not add "at 25°C" unless that temperature appears in the source.
> 2. Given a numerical value "3.3V ± 5%", the refactored text preserves "3.3V ± 5%" exactly.

> **FR-507** | Priority: MUST
>
> **Description:** If all refactoring iterations fail validation, the system MUST return the original text unchanged (fail-safe).
>
> **Rationale:** A failed refactoring attempt must never result in corrupted or partially-refactored text entering the pipeline. The original text is always a safe fallback. Supports the fail-safe-over-fail-fast principle.
>
> **Acceptance Criteria:**
> 1. Given 3 iterations where each fails fact-check or completeness validation, the system returns the exact original text byte-for-byte.
> 2. The system logs a warning indicating refactoring failed for the section.
> 3. No exception is raised.

> **FR-508** | Priority: MUST
>
> **Description:** If completeness falls below 80%, the system MUST reject the refactored text and return the original.
>
> **Rationale:** A completeness score below 80% indicates significant content loss, making the refactored text unreliable. The 80% threshold provides a concrete, measurable safety net.
>
> **Acceptance Criteria:**
> 1. Given a completeness score of 0.75 (75%), the system rejects the refactored text and returns the original.
> 2. Given a completeness score of 0.85 (85%), the system accepts the refactored text.
> 3. The completeness score and accept/reject decision are logged.

> **FR-509** | Priority: MUST
>
> **Description:** Refactoring MUST NOT mutate source-of-truth documents. The pipeline MUST persist original and refactored mirror artifacts as separate representations.
>
> **Rationale:** Refactoring improves retrieval utility but can introduce representation drift. Keeping immutable source plus derived mirror prevents accidental overwrite of authoritative content while preserving auditability.
>
> **Acceptance Criteria:**
> 1. Given a source document and refactoring enabled, ingestion writes a mirror pair (original representation and refactored representation) without modifying the source file.
> 2. Given refactoring disabled, only original representation is required.

> **FR-510** | Priority: MUST
>
> **Description:** Every stored chunk produced from refactored text MUST include provenance mapping back to source-of-truth location (URI plus positional mapping or equivalent).
>
> **Rationale:** Retrieval from derived text must still cite original evidence. Without provenance mapping, generated answers can become ungrounded even if retrieval quality is high.
>
> **Acceptance Criteria:**
> 1. Given a retrieved chunk from refactored text, metadata includes source URI and source span mapping fields.
> 2. If exact span mapping fails, metadata records fallback method and confidence score.

> **FR-511** | Priority: MUST
>
> **Description:** Citation outputs MUST resolve to original source references, not only refactored chunk text.
>
> **Rationale:** Engineering decisions require traceability to authoritative source material. Derived text may improve retrieval but cannot replace source provenance in citations.
>
> **Acceptance Criteria:**
> 1. Given an answer citing information from a refactored chunk, the citation payload includes original source URI and mapped source location.
> 2. UI/CLI presentation can optionally show that retrieval text origin was refactored.

### 3.6 Clean Document Store Output Contract (FR-580)

This section defines the output contract of the Document Processing Pipeline — the schema of the Clean Document Store that the Embedding Pipeline reads as its sole input. Every source document that completes processing MUST produce exactly two artefacts in the Clean Document Store: a Markdown content file and a companion metadata envelope.

> **FR-581** | Priority: MUST
>
> **Description:** The system MUST persist each processed document to the Clean Document Store as a Markdown file named `{source_key}.md`, where `source_key` is derived deterministically from the source file path.
>
> **Rationale:** A persistent, named clean document is the storage boundary between the Document Processing Pipeline and the Embedding Pipeline. Without persistence, the two pipelines cannot operate independently — re-embedding the corpus would require re-running document processing.
>
> **Acceptance Criteria:**
> 1. Given source file `/docs/spec.pdf` with `source_key = "a3f9c2"`, the system writes `{clean_docs_dir}/a3f9c2.md` containing the full clean Markdown text.
> 2. Given the same source file re-processed without changes, the output file is overwritten with identical content.
> 3. The `source_key` is a deterministic function of the source path — the same path always produces the same key.

> **FR-582** | Priority: MUST
>
> **Description:** The system MUST persist a companion metadata envelope as `{source_key}.meta.json` alongside each clean Markdown file, containing the fields defined in the Clean Document Store schema.
>
> **Rationale:** The metadata envelope carries the information the Embedding Pipeline needs to perform its own change detection, apply review tier filtering, and populate chunk metadata — without having to re-parse the Markdown content or re-contact the source document.
>
> **Acceptance Criteria:**
> 1. Given a successfully processed document, the system writes `{source_key}.meta.json` in the same directory as `{source_key}.md`.
> 2. The file is valid JSON and contains all required fields (see FR-583).
> 3. If the Markdown write succeeds but the metadata write fails, the system records the failure and does not leave a Markdown file without a companion metadata file (partial state must not occur).

> **FR-583** | Priority: MUST
>
> **Description:** The metadata envelope MUST contain the following fields:
>
> | Field | Type | Description |
> |-------|------|-------------|
> | `source_key` | string | Stable deterministic identity derived from source path |
> | `source_path` | string | Original absolute filesystem path of the source document |
> | `source_hash` | string | SHA-256 of the source file — used by Section 6 change detection |
> | `clean_hash` | string | SHA-256 of the clean Markdown content — used by Section 7 change detection |
> | `processing_timestamp` | string | ISO 8601 timestamp of when processing completed |
> | `extraction_confidence` | float | Extraction confidence score (0.0–1.0) from Node 2 |
> | `review_tier` | string | One of: `Fully Reviewed`, `Partially Reviewed`, `Self Reviewed` |
> | `section_tree_depth` | integer | Maximum heading depth detected in the document |
> | `table_count` | integer | Number of tables extracted |
> | `has_figures` | boolean | Whether any figures were detected |
> | `figure_count` | integer | Number of figures detected |
> | `processing_flags` | object | `{"multimodal_enabled": bool, "refactoring_enabled": bool}` |
>
> **Rationale:** The `source_hash` and `clean_hash` are the two independent change-detection keys: the Document Processing Pipeline compares `source_hash` to decide if it needs to re-run; the Embedding Pipeline compares `clean_hash` to decide if it needs to re-embed. Separating the two hashes makes each pipeline's skip logic independent. The remaining fields are consumed by the Embedding Pipeline to populate chunk metadata and apply retrieval filters without re-parsing the document.
>
> **Acceptance Criteria:**
> 1. Given a processed document, all fields in the table above are present in the metadata JSON.
> 2. `source_hash` matches the SHA-256 computed in Node 1 (FR-106).
> 3. `clean_hash` is the SHA-256 of the content written to `{source_key}.md`.
> 4. `extraction_confidence` matches the score computed in Node 2 (FR-206).
> 5. `review_tier` is one of the three valid enum values.

> **FR-584** | Priority: MUST
>
> **Description:** The clean Markdown file MUST contain the full document text after all processing stages have been applied: whitespace normalised, boilerplate removed, figure descriptions integrated at their original positions, and (if enabled) paragraphs refactored for self-containedness.
>
> **Rationale:** The Markdown file is the canonical representation of the document that the Embedding Pipeline will chunk and embed. Any content missing from this file will be absent from the search index. Supports the context-preservation-over-compression principle.
>
> **Acceptance Criteria:**
> 1. Given a document with 3 figures and refactoring enabled, the Markdown file contains: the cleaned body text, all three VLM-generated figure descriptions at their original positions, and refactored paragraph content.
> 2. Given the same document with refactoring disabled, the Markdown file contains the cleaned body text and figure descriptions but unmodified paragraph structure.
> 3. The file is valid UTF-8 Markdown — no binary content, no extraction artefacts.

> **FR-585** | Priority: MUST
>
> **Description:** The clean Markdown file MUST preserve the document's heading hierarchy using standard Markdown heading syntax (`#`, `##`, `###`, etc.) matching the section tree depth detected in Node 2.
>
> **Rationale:** The Embedding Pipeline's structure-aware chunking (Node 6) relies on Markdown heading syntax to respect section boundaries. If heading hierarchy is lost, the chunker cannot split at meaningful document boundaries.
>
> **Acceptance Criteria:**
> 1. Given a document with H1 "Overview" → H2 "Subsystem A" → H3 "Detail", the Markdown file contains `# Overview`, `## Subsystem A`, `### Detail` at the correct positions.
> 2. Given a flat document with no detected headings, the Markdown file contains no heading markers.

> **FR-586** | Priority: MUST
>
> **Description:** If document processing fails for any reason, the system MUST NOT write a partial clean Markdown file or metadata envelope to the Clean Document Store. Any previously existing clean document for the same `source_key` MUST be preserved.
>
> **Rationale:** Supports fail-safe-over-fail-fast. A partial or corrupt clean document would cause the Embedding Pipeline to produce incorrect chunks. Preserving the previous clean document ensures the Embedding Pipeline can still use the last successfully processed version.
>
> **Acceptance Criteria:**
> 1. Given a processing run that fails during Node 5 (refactoring), the system does not overwrite the existing `{source_key}.md` with partial output.
> 2. The existing `{source_key}.meta.json` is unchanged.
> 3. The pipeline log records the failure with the node, error type, and source key.

> **FR-587** | Priority: SHOULD
>
> **Description:** The Clean Document Store SHOULD support a configurable root directory, allowing deployments to place the store on a separate filesystem or network share from the source documents.
>
> **Rationale:** In production deployments, the source document filesystem may be read-only or on a different storage tier. Allowing the store root to be configured independently enables flexible deployment without code changes.
>
> **Acceptance Criteria:**
> 1. Given `clean_docs_dir: "/mnt/processed"` in configuration, all `.md` and `.meta.json` files are written to `/mnt/processed/`.
> 2. Changing the configured path and re-running writes to the new location.
> 3. The default path (if not configured) is a subdirectory of the working directory.

---

## Pipeline Requirements Traceability Matrix

This matrix covers FR-101 through FR-589 — the full scope of this specification.

| REQ ID | Section | Priority | Component/Stage |
|--------|---------|----------|-----------------|
| FR-101 | 3.1 | MUST | Document Ingestion — supported input formats |
| FR-102 | 3.1 | MUST | Document Ingestion — format detection |
| FR-103 | 3.1 | MUST | Document Ingestion — format-to-text conversion |
| FR-104 | 3.1 | MUST | Document Ingestion — PowerPoint extraction |
| FR-105 | 3.1 | MUST | Document Ingestion — Excel extraction |
| FR-106 | 3.1 | MUST | Document Ingestion — SHA-256 content hash |
| FR-107 | 3.1 | MUST | Document Ingestion — deterministic document ID |
| FR-108 | 3.1 | MUST | Document Ingestion — encoding fallback chain |
| FR-109 | 3.1 | MUST | Document Ingestion — domain vocabulary loading |
| FR-110 | 3.1 | SHOULD | Document Ingestion — extensible format support |
| FR-111 | 3.1 | MUST | Document Ingestion — log file exclusion |
| FR-112 | 3.1 | MUST | Document Ingestion — local filesystem ingestion |
| FR-113 | 3.1 | SHOULD | Document Ingestion — future SharePoint integration |
| FR-201 | 3.2 | MUST | Structure Detection — hierarchical section tree |
| FR-202 | 3.2 | MUST | Structure Detection — table extraction |
| FR-203 | 3.2 | MUST | Structure Detection — figure detection and extraction |
| FR-204 | 3.2 | MUST | Structure Detection — figure image export |
| FR-205 | 3.2 | MUST | Structure Detection — abbreviation auto-detection |
| FR-206 | 3.2 | MUST | Structure Detection — extraction confidence score |
| FR-207 | 3.2 | MUST | Structure Detection — low-confidence flagging |
| FR-208 | 3.2 | MUST | Structure Detection — swappable provider |
| FR-301 | 3.3 | MUST | Multimodal Processing — VLM figure description |
| FR-302 | 3.3 | MUST | Multimodal Processing — conditional execution |
| FR-303 | 3.3 | MUST | Multimodal Processing — description content requirements |
| FR-304 | 3.3 | MUST | Multimodal Processing — no speculative content |
| FR-305 | 3.3 | MUST | Multimodal Processing — VLM confidence score |
| FR-306 | 3.3 | MUST | Multimodal Processing — swappable VLM provider |
| FR-307 | 3.3 | MUST | Multimodal Processing — VLM failure fallback |
| FR-401 | 3.4 | MUST | Text Cleaning — whitespace normalisation |
| FR-402 | 3.4 | MUST | Text Cleaning — boilerplate removal via patterns |
| FR-403 | 3.4 | MUST | Text Cleaning — repeated header/footer reduction |
| FR-404 | 3.4 | MUST | Text Cleaning — VLM figure description integration |
| FR-405 | 3.4 | MUST | Text Cleaning — table markdown integration |
| FR-501 | 3.5 | MUST | Document Refactoring — self-contained paragraph restructuring |
| FR-502 | 3.5 | MUST | Document Refactoring — configurable skip |
| FR-503 | 3.5 | MUST | Document Refactoring — self-correcting iteration loop |
| FR-504 | 3.5 | MUST | Document Refactoring — fact-check validation |
| FR-505 | 3.5 | MUST | Document Refactoring — completeness check |
| FR-506 | 3.5 | MUST | Document Refactoring — content safety constraints |
| FR-507 | 3.5 | MUST | Document Refactoring — fail-safe original text fallback |
| FR-508 | 3.5 | MUST | Document Refactoring — 80% completeness threshold |
| FR-509 | 3.5 | MUST | Document Refactoring — immutable source, mirror artefacts |
| FR-510 | 3.5 | MUST | Document Refactoring — provenance mapping |
| FR-511 | 3.5 | MUST | Document Refactoring — citation resolution to source |
| FR-581 | 3.6 | MUST | Clean Document Store — Markdown file persistence |
| FR-582 | 3.6 | MUST | Clean Document Store — metadata envelope persistence |
| FR-583 | 3.6 | MUST | Clean Document Store — metadata envelope schema |
| FR-584 | 3.6 | MUST | Clean Document Store — full processed content in Markdown |
| FR-585 | 3.6 | MUST | Clean Document Store — heading hierarchy preservation |
| FR-586 | 3.6 | MUST | Clean Document Store — no partial writes on failure |
| FR-587 | 3.6 | SHOULD | Clean Document Store — configurable root directory |

### Requirement Priority Summary

| Priority | Count | Requirement IDs |
|----------|-------|-----------------|
| MUST | 50 | FR-101–109, FR-111–112, FR-201–208, FR-301–307, FR-401–405, FR-501–511, FR-581–586 |
| SHOULD | 3 | FR-110, FR-113, FR-587 |
| MAY | 0 | — |
| **Total** | **53** | **FR-101 through FR-587** |
