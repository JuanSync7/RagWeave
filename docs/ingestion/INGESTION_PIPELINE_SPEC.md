# RAG Document Embedding Pipeline — Pipeline Specification (v2.1.0)

## Document Information

> **Document intent:** This is a formal specification for the **13-node ingestion pipeline** — the functional requirements for each processing stage from document input to vector/KG storage.
> For cross-cutting platform requirements (re-ingestion, config, error handling, data model, storage schema, NFR), see `INGESTION_PLATFORM_SPEC.md`.
> For current implementation details, use:
>
> - `INGESTION_PIPELINE_ENGINEERING_GUIDE.md`
> - `INGESTION_NEW_ENGINEER_ONBOARDING_CHECKLIST.md`
> - `src/ingest/README.md`

| Field | Value |
|-------|-------|
| System | AION RAG Document Embedding Pipeline |
| Document Type | Pipeline Specification (Functional Requirements) |
| Companion Documents | INGESTION_PLATFORM_SPEC.md (Platform/Cross-Cutting Requirements), RAG_embedding_pipeline_spec_summary.md (Summary), INGESTION_PIPELINE_IMPLEMENTATION.md (Implementation Guide) |
| Version | 2.1.0 |
| Status | Draft |

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | — | — | Initial specification |
| 2.0.0 | 2026-03-10 | — | Restructured to align with write-spec skill |
| 2.1.0 | 2026-03-17 | AI Assistant | Split from monolithic spec. This file now contains sections 1-3 (scope, pipeline overview, 13 node functional requirements FR-100 through FR-1304). Cross-cutting requirements (sections 4-16) moved to INGESTION_PLATFORM_SPEC.md. |

---

## 1. Purpose and Scope

### 1.1 Problem Statement

ASIC design organisations accumulate critical engineering knowledge across hundreds of documents: specifications, design guides, runbooks, standard operating procedures, and project reports. This knowledge is fragmented across file servers, SharePoint, and individual workstations. When engineers leave, their contextual understanding leaves with them.

Existing search tools fail for engineering documentation because:

1. The same technical term carries different meaning across domains (e.g., "clock domain" spans front-end design, DFT, verification, and physical design).
2. Knowledge exists at varying levels of maturity — from formally approved specifications to an individual engineer's utility script — with no mechanism to distinguish authoritative from informal sources.
3. Documents rely on sequential reading order; isolated paragraphs lose meaning without surrounding context (e.g., "the same voltage" is ambiguous outside its original section).

### 1.2 Scope

The system SHALL transform engineering documents into semantically searchable, context-aware vector embeddings stored in a vector database, with a complementary knowledge graph capturing relationships between documents, concepts, entities, and specifications.

The system is designed for a mission-critical engineering environment where incorrect retrieval (e.g., returning a 4nm specification when the query is about a 12nm specification) could propagate into design errors.

**Entry point:** Source document file (PDF, DOCX, PPTX, XLSX, Markdown, HTML, RST, plain text) on local filesystem.

**Exit point:** Vector embeddings + metadata stored in vector database; knowledge graph triples stored in graph store.

**In scope:**

- Document ingestion, processing, and embedding
- Vector storage with hybrid search capability (vector + keyword)
- Knowledge graph construction and storage
- Document review tier management
- Re-ingestion of updated documents
- Batch processing of document directories
- Retrieval quality evaluation framework

### 1.3 Terminology

The following terms are used throughout this specification. A complete glossary is provided in Section 17.

| Term | Definition |
|------|-----------|
| Chunk | The atomic unit of the retrieval system; a segment of document text that is individually embedded and stored |
| RAG | Retrieval-Augmented Generation — a pattern where retrieved context is provided to an LLM for answer generation |
| Knowledge Graph | A graph of entities and relationships extracted from documents |
| Triple | A subject-predicate-object relationship in the knowledge graph |
| Hybrid Search | Combined vector similarity search and BM25 keyword search |
| BM25 | Best Matching 25 — a probabilistic ranking function for keyword-based text search |
| BYOM | Bring Your Own Model — mode where embeddings are computed externally and passed as pre-computed vectors to the vector store |
| Embedding | A dense vector representation of text, used for semantic similarity search |
| Review Tier | A trust classification (Fully/Partially/Self Reviewed) controlling a document's visibility in search results |
| Re-ingestion | Processing a previously ingested document again, cleaning up old data and inserting new data |
| DAG | Directed Acyclic Graph — the processing pipeline topology |
| VLM | Vision-Language Model — a multimodal model that can process both images and text |
| Deterministic ID | An identifier derived from content via cryptographic hashing, ensuring the same input always produces the same ID |
| HNSW | Hierarchical Navigable Small World — an approximate nearest-neighbour graph index algorithm |
| Idempotent | An operation that produces the same result whether applied once or multiple times |

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
| FR-600–FR-699 | 3.6 Chunking |
| FR-700–FR-799 | 3.7 Chunk Enrichment |
| FR-800–FR-899 | 3.8 Metadata Generation |
| FR-900–FR-999 | 3.9 Cross-Reference Extraction |
| FR-1000–FR-1099 | 3.10 Knowledge Graph Extraction |
| FR-1100–FR-1199 | 3.11 Quality Validation |
| FR-1200–FR-1299 | 3.12 Embedding & Storage |
| FR-1300–FR-1399 | 3.13 Knowledge Graph Storage |
| FR-1400–FR-1499 | Re-ingestion |
| FR-1500–FR-1599 | Review Tiers |
| FR-1600–FR-1699 | Domain Vocabulary |
| FR-1700–FR-1799 | Error Handling & Fallbacks |
| FR-1800–FR-1899 | Configuration |
| FR-1900–FR-1999 | CLI / API Interface |
| FR-2000–FR-2199 | Evaluation & Feedback |
| NFR-100–NFR-699 | Non-Functional Requirements |
| SC-100–SC-199 | Security & Compliance |

### 1.6 Assumptions & Constraints

| ID | Assumption / Constraint | Impact if Violated |
|----|------------------------|--------------------|
| A-1 | Python 3.11+ runtime | Type hint syntax and match statements fail |
| A-2 | LangGraph/LangChain available | Pipeline DAG orchestration unavailable |
| A-3 | Vector database (e.g., Weaviate) accessible at configured URL | Embedding storage and retrieval fail |
| A-4 | LLM provider accessible (local or API) | LLM-dependent stages fall back to deterministic alternatives |
| A-5 | Sequential document processing (no concurrent ingestion of same document) | Race conditions on re-ingestion cleanup |
| A-6 | Documents ≤ ~100 pages | Larger documents should be pre-split; memory budget is < 2 GB peak RSS |
| A-7 | Embedding model input token limit accommodates target chunk size + boundary context | Embeddings will be truncated or fail |

### 1.7 Design Principles

The following principles SHALL guide all design and implementation decisions:

| Principle | Description |
|-----------|-------------|
| **Swappability over lock-in** | Every external dependency (LLM provider, embedding model, vector store, structure detector) SHALL be behind a configuration interface. Changing providers SHALL require configuration changes, not code changes. |
| **Fail-safe over fail-fast** | When an LLM call fails, the pipeline SHALL fall back to deterministic alternatives rather than halting. A single flawed LLM response SHALL NOT halt a batch job. |
| **Context preservation over compression** | The pipeline SHALL preserve every numerical value, specification, and procedural step. Content restructuring SHALL NOT summarise or remove information. |
| **Configuration-driven behaviour** | Pipeline behaviour (skip/enable processing stages, dry run mode) SHALL be controlled via a single configuration system with runtime overrides. |
| **Idempotency by construction** | Every processing stage SHALL produce the same output given the same input. Identifiers SHALL be derived deterministically from content. Re-ingesting a document SHALL produce an equivalent result to first-time ingestion. |
| **Controlled access over restriction** | Knowledge at all maturity levels SHALL be ingested and searchable. A tiered review system SHALL control visibility at retrieval time without restricting what enters the system. |

### 1.8 Out of Scope

**Out of scope:**

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

The system SHALL process documents through a directed acyclic graph (DAG) of processing stages, implemented using a graph-based orchestration framework (LangGraph, which is part of the LangChain ecosystem). Each document SHALL flow through the following stages in order:

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
┌──────────────────────────────────────┐
│ [6] CHUNKING                         │
│     Split into semantic chunks       │
│     with deterministic IDs           │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [7] CHUNK ENRICHMENT                 │
│     Add boundary context,            │
│     build metadata headers           │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [8] METADATA GENERATION              │
│     Generate keywords, entities,     │
│     summaries at doc & chunk level   │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [9] CROSS-REFERENCE EXTRACTION [opt] │
│     Detect inter-document refs       │
│     and standard citations           │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [10] KNOWLEDGE GRAPH EXTRACTION [opt]│
│      Extract structured triples      │
│      for relationship-aware retrieval│
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [11] QUALITY VALIDATION              │
│      Filter low-quality/duplicates,  │
│      assign quality scores           │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [12] EMBEDDING & STORAGE             │
│      Generate vectors, clean up      │
│      old data, store in vector DB    │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [13] KNOWLEDGE GRAPH STORAGE [opt]   │
│      Persist triples to graph store  │
└──────────────────────────────────────┘
               │
               ▼
Vector Database + Knowledge Graph Store
```

Stages marked with `[optional]` or `[opt]` are conditional and may be skipped based on configuration or document characteristics.

### 2.2 Stage Descriptions

| # | Stage | Purpose | Conditional |
|---|-------|---------|-------------|
| 1 | Document Ingestion | Read source file, detect format, compute content hash, detect re-ingestion | No |
| 2 | Structure Detection | Parse document into hierarchical section tree, extract figures and tables | No |
| 3 | Multimodal Processing | Convert detected figures into text descriptions using a vision-language model | Yes — only if figures detected (tentatively convert figures to text first) |
| 4 | Text Cleaning | Normalise text, remove boilerplate, integrate figure/table descriptions | No |
| 5 | Document Refactoring | Restructure content for self-containedness, resolve implicit references | Yes — skippable via config |
| 6 | Chunking | Split document into semantically coherent chunks with deterministic IDs | No |
| 7 | Chunk Enrichment | Add boundary context from adjacent chunks, build metadata headers | No |
| 8 | Metadata Generation | Generate searchable keywords and entities at document and chunk level | No |
| 9 | Cross-Reference Extraction | Detect references between documents, sections, and standards | Yes — skippable via config |
| 10 | Knowledge Graph Extraction | Extract structured triples for relationship-aware retrieval | Yes — skippable via config |
| 11 | Quality Validation | Filter low-quality and duplicate chunks, assign quality scores | No |
| 12 | Embedding & Storage | Generate vector embeddings, clean up old data on re-ingestion, store in vector database | No |
| 13 | Knowledge Graph (KG) Storage | Persist knowledge graph triples to graph store | Yes — only if KG enabled |

### 2.3 Processing Stage Independence

Each processing stage SHALL:

- Operate on a shared document state object
- Read only from fields populated by upstream stages
- Write only to its own designated output fields
- Be individually replaceable without affecting other stages
- Handle its own errors without crashing the pipeline

## 3. Functional Requirements

### 3.1 Document Ingestion (FR-100)

> **FR-101** | Priority: MUST
> **Description:** The system MUST support the following input formats: PDF, DOCX, PPTX, XLSX, Markdown, HTML, reStructuredText (RST), and plain text.
> **Rationale:** Engineering knowledge is spread across multiple document formats; without broad format coverage, significant portions of organisational knowledge remain unsearchable, directly contributing to the knowledge fragmentation problem.
> **Acceptance Criteria:** Given a test corpus containing one file of each supported format (PDF spec sheet, DOCX design guide, PPTX review deck, XLSX pin table, Markdown runbook, HTML datasheet, RST procedure, plain-text README), the system successfully ingests all eight files and produces non-empty text output for each. Given a `.wav` file, the system does not attempt format-specific extraction and classifies the format as UNKNOWN.

> **FR-102** | Priority: MUST
> **Description:** The system MUST detect document format from file extension with a fallback to UNKNOWN for unrecognised extensions.
> **Rationale:** Reliable format detection is a prerequisite for routing documents to the correct text extractor. Falling back to UNKNOWN rather than guessing prevents misinterpretation of binary data. Supports the fail-safe-over-fail-fast principle.
> **Acceptance Criteria:** Given a file named `clock_tree_spec.pdf`, the system detects format as PDF. Given a file named `notes.xyz`, the system assigns format UNKNOWN. Given a file with no extension, the system assigns format UNKNOWN.

> **FR-103** | Priority: MUST
> **Description:** The system MUST convert all input formats to text before downstream processing. Binary formats (PDF, DOCX, PPTX, XLSX) MUST go through format-specific text extractors.
> **Rationale:** A uniform text representation is the contract between ingestion and all downstream stages. Without this normalisation, every downstream stage would need format-specific logic, violating stage independence.
> **Acceptance Criteria:** Given a PDF containing a voltage specification table, the text extractor produces a text output that preserves the table content. Given a DOCX with embedded images and headings, the extractor outputs text with heading structure intact. The output for all formats is a plain text or markdown string — no binary content remains.

> **FR-104** | Priority: MUST
> **Description:** The system MUST extract text from PowerPoint files including text frames, speaker notes, and table cells, preserving slide order and structure.
> **Rationale:** Engineering review presentations often contain critical design decisions in speaker notes and specification data in table cells. Omitting these would lose knowledge that exists nowhere else. Supports the context-preservation principle.
> **Acceptance Criteria:** Given a PPTX with 5 slides where slide 3 contains a table of clock frequencies and slide 4 has speaker notes explaining a design trade-off, the extracted text includes both the table content from slide 3 and the speaker notes from slide 4 in correct slide order. Given a PPTX with an empty slide, that slide produces no text but does not cause an error.

> **FR-105** | Priority: MUST
> **Description:** The system MUST extract text from Excel files including all sheets, with table detection and markdown conversion. Named ranges and cell references MUST be preserved.
> **Rationale:** Excel files in ASIC organisations commonly contain pin tables, power budgets, and register maps across multiple sheets. Losing sheet context or cell references would make the extracted data ambiguous. Supports the context-preservation principle.
> **Acceptance Criteria:** Given an XLSX with sheets "Power_Budget" and "Pin_Table", the system extracts text from both sheets with sheet names as section headers. Given a sheet containing a table with headers `[Pin, Direction, Voltage, Description]`, the output contains a markdown table preserving all columns and rows. Given a named range "VDD_CORE_SPECS", the name appears in the extracted text.

> **FR-106** | Priority: MUST
> **Description:** The system MUST compute a SHA-256 content hash of the source file for change detection and re-ingestion purposes.
> **Rationale:** Content hashing is the foundation of the re-ingestion mechanism; without it the system cannot detect whether a document has changed, leading to either unnecessary reprocessing or stale data. Supports the idempotency-by-construction principle.
> **Acceptance Criteria:** Given the same file ingested twice, the system produces identical SHA-256 hashes both times. Given a file where a single character is changed, the system produces a different hash. The hash is a 64-character lowercase hexadecimal string.

> **FR-107** | Priority: MUST
> **Description:** The system MUST generate deterministic document identifiers derived from the source file path, ensuring the same file always produces the same document ID.
> **Rationale:** Deterministic IDs are essential for re-ingestion — the system must be able to locate previously ingested data for the same document. Supports the idempotency-by-construction principle.
> **Acceptance Criteria:** Given the file path `/data/specs/clock_tree_spec_v2.pdf` ingested twice, the system produces the same document ID both times. Given two different file paths, the system produces different document IDs.

> **FR-108** | Priority: MUST
> **Description:** The system MUST handle text encoding variations with a fallback chain (UTF-8 → Latin-1 → CP1252 → UTF-8 with replacement).
> **Rationale:** Legacy engineering documents frequently use non-UTF-8 encodings (e.g., Windows-1252 from older Word exports). Without a fallback chain, these documents would fail ingestion entirely, losing valuable knowledge. Supports the fail-safe-over-fail-fast principle.
> **Acceptance Criteria:** Given a Latin-1 encoded text file containing the character `µ` (micro sign), the system successfully decodes and preserves the character. Given a file with invalid byte sequences in all encodings, the system falls back to UTF-8 with replacement characters rather than raising an exception.

> **FR-109** | Priority: MUST
> **Description:** The system MUST load and make available a configurable domain vocabulary (abbreviation dictionary) for use by downstream stages.
> **Rationale:** ASIC/semiconductor terminology is highly domain-specific (e.g., DFT, PVT, CDC). A shared vocabulary ensures consistent abbreviation expansion across all stages and prevents misinterpretation of terms that differ across domains. Addresses the problem of term ambiguity across domains.
> **Acceptance Criteria:** Given a domain vocabulary file containing `{"DFT": "Design for Testability", "CDC": "Clock Domain Crossing"}`, the system loads the vocabulary and makes it accessible to downstream stages. Given no vocabulary file configured, the system starts with an empty vocabulary without error.

> **FR-110** | Priority: SHOULD
> **Description:** The system SHOULD support future addition of new input formats (e.g., SystemVerilog via AST-based extraction, Visio, images via OCR) without architectural changes.
> **Rationale:** Engineering toolchains evolve and new document types emerge; the ingestion layer must be extensible without requiring pipeline redesign. Supports the swappability-over-lock-in principle.
> **Acceptance Criteria:** A new format handler can be added by implementing a defined extractor interface and registering it in configuration, without modifying existing extractor code or pipeline orchestration logic. No existing unit tests break when the new handler is added.

> **FR-111** | Priority: MUST
> **Description:** Tool log files (.log) MUST be excluded from the vector embedding pipeline. Logs are better served by direct keyword search.
> **Rationale:** Log files are high-volume, low-semantic-density content that would pollute the vector space with noise, degrading retrieval quality for actual engineering documents.
> **Acceptance Criteria:** Given a directory containing `synthesis_run.log` and `clock_spec.pdf`, a batch ingestion run processes `clock_spec.pdf` and skips `synthesis_run.log`. The system logs a message indicating the `.log` file was excluded.

> **FR-112** | Priority: MUST
> **Description:** The system MUST support ingestion from local filesystem paths (absolute and relative).
> **Rationale:** Local filesystem is the primary document source for engineering teams; this is the baseline ingestion capability required before any remote integrations.
> **Acceptance Criteria:** Given an absolute path `/data/specs/clock_spec.pdf`, the system reads and ingests the file. Given a relative path `./specs/clock_spec.pdf`, the system resolves it against the working directory and ingests the file. Given a non-existent path, the system raises a clear error indicating the file was not found.

> **FR-113** | Priority: SHOULD
> **Description:** The system SHOULD support future integration with SharePoint document libraries as a document source without architectural changes. SharePoint integration is planned for Phase 3.
> **Rationale:** Many organisations store engineering documents in SharePoint; supporting it as a source expands coverage of fragmented knowledge. Supports the swappability-over-lock-in principle.
> **Acceptance Criteria:** The document source interface is abstracted such that a SharePoint adapter can be implemented without modifying the ingestion pipeline. The adapter would need to implement a defined source interface (e.g., `list_documents()`, `download_document()`) and be selectable via configuration.

### 3.2 Structure Detection (FR-200)

> **FR-201** | Priority: MUST
> **Description:** The system MUST parse documents into a hierarchical section tree preserving heading levels and parent-child relationships.
> **Rationale:** Engineering documents derive meaning from their hierarchical structure — a voltage value under "3.3V IO Domain" means something different than under "1.0V Core Domain". Losing this hierarchy causes the context-loss problem identified in the problem statement.
> **Acceptance Criteria:** Given a document with headings H1 "Power Specifications" → H2 "Core Domain" → H3 "Voltage Limits", the system produces a tree where "Voltage Limits" is a child of "Core Domain", which is a child of "Power Specifications". Given a flat document with no headings, the system produces a single root node containing all content.

> **FR-202** | Priority: MUST
> **Description:** The system MUST extract tables with headers, rows, and a text representation suitable for downstream processing.
> **Rationale:** Tables in ASIC specifications carry dense, high-value data (pin tables, timing parameters, register maps). A text representation ensures this data is searchable and preserved through the pipeline. Supports the context-preservation principle.
> **Acceptance Criteria:** Given a table with headers `[Parameter, Min, Typ, Max, Unit]` and a row `[VDD_CORE, 0.95, 1.0, 1.05, V]`, the system extracts both headers and row data and produces a markdown table representation. Given a table with merged cells, the system produces a best-effort extraction with no data loss.

> **FR-203** | Priority: MUST
> **Description:** The system MUST detect and extract figures with bounding boxes, captions, and surrounding text context.
> **Rationale:** Figures (block diagrams, timing diagrams, floorplans) convey information not present in the text. Capturing bounding boxes enables VLM processing; captions and surrounding text provide semantic anchoring for the generated description.
> **Acceptance Criteria:** Given a PDF page containing a block diagram with caption "Figure 3: Clock Distribution Network", the system extracts the figure region, associates the caption text, and captures at least the preceding and following paragraphs as surrounding context. Given a page with no figures, the figures list for that page is empty.

> **FR-204** | Priority: MUST
> **Description:** The system MUST export detected figure images to disk for multimodal processing when configured.
> **Rationale:** The VLM stage requires image files as input; exporting figures to disk decouples structure detection from multimodal processing, allowing each stage to operate independently.
> **Acceptance Criteria:** Given a document with 3 detected figures and figure export enabled in configuration, the system writes 3 image files (PNG or similar) to the configured output directory. File names include the document ID and figure index for traceability. Given figure export disabled in configuration, no image files are written.

> **FR-205** | Priority: MUST
> **Description:** The system MUST auto-detect abbreviation definitions in the document text (e.g., "Design for Testability (DFT)", abbreviation tables) and merge them with the domain vocabulary.
> **Rationale:** Documents often define their own abbreviations that may not be in the global domain vocabulary. Auto-detection ensures downstream stages (refactoring, enrichment) can resolve document-specific terms. Addresses term ambiguity across domains.
> **Acceptance Criteria:** Given text containing "Clock Domain Crossing (CDC) analysis ensures...", the system detects `CDC → Clock Domain Crossing` and adds it to the vocabulary. Given an abbreviation table with rows `DFT | Design for Testability`, the system extracts all entries. Given a conflict with the domain vocabulary (e.g., document defines "PD" as "Power Domain" but vocabulary has "PD" as "Physical Design"), the document-local definition takes precedence within that document's processing.

> **FR-206** | Priority: MUST
> **Description:** The system MUST compute an extraction confidence score (0.0–1.0) based on section tree depth, table completeness, text coherence, and character density.
> **Rationale:** Extraction quality varies significantly by document format and layout complexity. A confidence score enables downstream stages and operators to identify documents that may have lost structure during extraction.
> **Acceptance Criteria:** Given a well-structured Markdown document with clear headings and tables, the confidence score is above 0.8. Given a scanned PDF with OCR artefacts and no detectable headings, the confidence score is below 0.5. The score is a float in the range [0.0, 1.0].

> **FR-207** | Priority: MUST
> **Description:** Documents with extraction confidence below a configurable threshold MUST be flagged for manual review but MUST continue through the pipeline.
> **Rationale:** Stopping the pipeline on low-confidence documents would block batch processing. Flagging ensures operators are alerted without halting the pipeline. Supports the fail-safe-over-fail-fast principle.
> **Acceptance Criteria:** Given a confidence threshold configured at 0.6 and a document scoring 0.45, the system sets a `requires_manual_review` flag to true and continues processing. Given a document scoring 0.75 with the same threshold, the flag is false. The flagged document appears in pipeline output/logs with a review warning.

> **FR-208** | Priority: MUST
> **Description:** The structure detection provider MUST be swappable via configuration.
> **Rationale:** Different structure detection tools (e.g., Docling, Unstructured, custom parsers) have different strengths; the system must allow switching without code changes. Supports the swappability-over-lock-in principle.
> **Acceptance Criteria:** Given configuration specifying provider A, the system uses provider A for structure detection. Changing the configuration to provider B and re-running uses provider B with no code changes. Both providers implement the same interface and produce compatible output structures.

### 3.3 Multimodal Processing (FR-300)

> **FR-301** | Priority: MUST
> **Description:** The system MUST convert detected figures into text descriptions using a vision-language model (VLM), making visual content searchable via text embeddings.
> **Rationale:** Figures (block diagrams, timing diagrams, layout views) contain critical engineering information that would be entirely lost from the search index without text conversion. This directly addresses knowledge fragmentation by making visual knowledge retrievable.
> **Acceptance Criteria:** Given an extracted figure image of a clock distribution block diagram, the system sends it to the VLM and receives a text description. The description is stored associated with the figure's ID. Given a document with no figures, this stage produces no descriptions.

> **FR-302** | Priority: MUST
> **Description:** This stage MUST only execute when figures are detected in the document.
> **Rationale:** VLM calls are expensive (latency and cost). Skipping the stage entirely when no figures exist avoids unnecessary API calls and processing time.
> **Acceptance Criteria:** Given a Markdown document with no figures, the multimodal processing stage is not invoked (no VLM API calls are made). Given a PDF with 2 detected figures, the stage executes and processes both figures.

> **FR-303** | Priority: MUST
> **Description:** VLM descriptions MUST include diagram type, visible labels and values, key relationships, and numerical specifications.
> **Rationale:** Generic descriptions (e.g., "a block diagram") are useless for engineering retrieval. Descriptions must capture the specific technical content visible in the figure to enable precise search. Supports the context-preservation principle.
> **Acceptance Criteria:** Given a timing diagram showing setup time = 0.5ns and hold time = 0.2ns for a flip-flop, the VLM description includes the diagram type ("timing diagram"), the numerical values (0.5ns, 0.2ns), and the relationship (setup/hold time for flip-flop). The description does not merely say "a timing diagram".

> **FR-304** | Priority: MUST
> **Description:** VLM descriptions MUST NOT contain speculative or inferred information not visible in the figure.
> **Rationale:** In a mission-critical engineering environment, fabricated details in a figure description could propagate into design decisions. The system must never present LLM hallucinations as document content. Supports the context-preservation principle.
> **Acceptance Criteria:** Given a block diagram showing modules A, B, and C connected in series, the description does not mention module D or speculate about internal implementation of any module. A validation check can compare entities in the description against entities visible in the figure caption and surrounding text.

> **FR-305** | Priority: MUST
> **Description:** Each VLM-generated description MUST have an associated confidence score.
> **Rationale:** VLM output quality varies with figure complexity and clarity. A confidence score allows downstream stages and retrieval to weight or filter descriptions appropriately.
> **Acceptance Criteria:** Given a VLM description, the system stores a confidence score as a float in [0.0, 1.0] alongside the description. Given a clear, well-labelled schematic, the confidence score is higher than for a blurry or hand-drawn sketch.

> **FR-306** | Priority: MUST
> **Description:** The VLM provider MUST be swappable via configuration.
> **Rationale:** VLM technology is rapidly evolving; the system must allow switching providers (e.g., GPT-4V to Claude Vision) without code changes. Supports the swappability-over-lock-in principle.
> **Acceptance Criteria:** Given configuration specifying VLM provider "openai/gpt-4o", the system uses that provider. Changing the configuration to "anthropic/claude-sonnet" and re-running uses the new provider with no code changes. Both providers are accessed through the same interface.

> **FR-307** | Priority: MUST
> **Description:** If the VLM call fails, the figure MUST be recorded without a description (confidence = 0.0).
> **Rationale:** A single failed VLM call must not halt processing of the entire document. The figure is still recorded so it can be reprocessed later. Supports the fail-safe-over-fail-fast principle.
> **Acceptance Criteria:** Given a VLM API timeout or error for figure 2 of 5, the system records figure 2 with an empty description and confidence 0.0, then continues to process figures 3–5. The pipeline does not raise an exception. Pipeline logs record the failure with the figure ID and error details.

### 3.4 Text Cleaning (FR-400)

> **FR-401** | Priority: MUST
> **Description:** The system MUST normalise whitespace (collapse multiple spaces, limit consecutive newlines).
> **Rationale:** PDF and DOCX extraction frequently produces irregular whitespace that wastes token budget and degrades embedding quality. Normalisation ensures consistent input for chunking and embedding.
> **Acceptance Criteria:** Given text with 5 consecutive spaces between words, the output contains a single space. Given text with 6 consecutive newlines, the output contains no more than the configured maximum (e.g., 2). Given text with tabs mixed with spaces, the output uses consistent spacing.

> **FR-402** | Priority: MUST
> **Description:** The system MUST remove boilerplate artefacts (page headers/footers, confidentiality notices, stray page numbers) using configurable patterns.
> **Rationale:** Boilerplate text (e.g., "CONFIDENTIAL — Company Internal" repeated on every page) adds noise to embeddings and wastes token capacity without contributing searchable knowledge. Supports the configuration-driven-behaviour principle.
> **Acceptance Criteria:** Given a configurable pattern list including `"CONFIDENTIAL.*INTERNAL"` and text containing "CONFIDENTIAL — Company Internal" on 20 pages, all 20 occurrences are removed. Given a pattern `"^Page \\d+$"`, stray page numbers like "Page 42" on their own line are removed. Custom patterns can be added via configuration without code changes.

> **FR-403** | Priority: MUST
> **Description:** The system MUST detect and reduce repeated headers/footers (lines appearing more than 3 times) to a single occurrence.
> **Rationale:** Even without explicit pattern configuration, frequently repeated lines are almost certainly boilerplate. Automatic detection catches document-specific headers/footers that configurable patterns might miss.
> **Acceptance Criteria:** Given a document where the line "ASIC Design Specification Rev 2.1" appears 15 times (once per page), the output contains this line exactly once. Given a line that appears exactly 3 times in a document, it is preserved (threshold is "more than 3"). Given a line that appears 4 times, it is reduced to 1 occurrence.

> **FR-404** | Priority: MUST
> **Description:** The system MUST integrate VLM-generated figure descriptions into the text stream with figure ID markers.
> **Rationale:** Figure descriptions must be embedded in-line at the figure's original position so that chunking preserves the spatial relationship between figures and surrounding text. Supports the context-preservation principle.
> **Acceptance Criteria:** Given a figure description for figure ID `fig_003` with text "Block diagram showing clock distribution from PLL to 4 clock domains", the text stream contains a marker such as `[FIGURE fig_003]` followed by the description at the position where the figure originally appeared. Given a figure with no description (confidence = 0.0), only the marker is inserted with no description text.

> **FR-405** | Priority: MUST
> **Description:** The system MUST integrate table markdown representations into the text stream with table ID markers, preserving tabular data (e.g., voltage specifications, pin tables) in a searchable format.
> **Rationale:** Tables carry dense, high-value engineering data. Integrating them as markdown preserves structure while keeping the data in the text stream for chunking and embedding. Supports the context-preservation principle.
> **Acceptance Criteria:** Given a table with ID `tbl_002` containing voltage specifications, the text stream includes a marker such as `[TABLE tbl_002]` followed by the markdown table representation. The markdown preserves all headers, rows, and cell values from the original table. Given a pin table with 50 rows, all 50 rows appear in the markdown output.

### 3.5 Document Refactoring (FR-500)

> **FR-501** | Priority: MUST
> **Description:** The system MUST support optional restructuring of document text to make each paragraph self-contained for retrieval, resolving implicit references (e.g., "as mentioned above") to explicit references (e.g., "the 1.8V core voltage specified in Section 1.2").
> **Rationale:** Isolated paragraphs lose meaning without surrounding context — this is a core problem identified in the problem statement (e.g., "the same voltage" is ambiguous outside its original section). Refactoring resolves this at ingestion time rather than burdening retrieval. Supports the context-preservation principle.
> **Acceptance Criteria:** Given a paragraph containing "This voltage should not exceed the limit specified above", the refactored output replaces the implicit reference with the explicit value, e.g., "This voltage should not exceed the 1.05V maximum specified in Section 2.3 Core Power". Given a paragraph with no implicit references, the text is returned unchanged.

> **FR-502** | Priority: MUST
> **Description:** Refactoring MUST be skippable via configuration.
> **Rationale:** Refactoring uses LLM calls which add latency and cost. Some deployments may prefer raw text. Supports the configuration-driven-behaviour principle.
> **Acceptance Criteria:** Given configuration with `refactoring.enabled = false`, the refactoring stage is skipped entirely and the text passes through unchanged. Given `refactoring.enabled = true`, the stage executes. No LLM calls are made when the stage is disabled.

> **FR-503** | Priority: MUST
> **Description:** The refactoring process MUST use a self-correcting loop with configurable maximum iterations per section.
> **Rationale:** A single LLM pass may introduce errors or miss references. Iterative correction with a bounded loop prevents runaway processing while improving output quality.
> **Acceptance Criteria:** Given `refactoring.max_iterations = 3`, the system performs at most 3 refactoring-validation cycles per section. If iteration 2 passes validation, iteration 3 is not executed. Given `max_iterations = 1`, only one pass is performed regardless of validation outcome.

> **FR-504** | Priority: MUST
> **Description:** Each refactoring iteration MUST include a fact-check validation that no information was added, removed, or distorted.
> **Rationale:** LLMs can hallucinate or subtly alter technical facts. In a mission-critical environment, a refactored paragraph claiming "1.2V" when the source says "1.0V" could cause a design error. Supports the context-preservation principle.
> **Acceptance Criteria:** Given a source paragraph stating "VDD_CORE = 1.0V" and a refactored version that changes it to "VDD_CORE = 1.2V", the fact-check validation fails and the iteration is rejected. Given a refactored version that only adds context ("VDD_CORE = 1.0V, as specified in Section 2.1"), the fact-check passes.

> **FR-505** | Priority: MUST
> **Description:** Each refactoring iteration MUST include a completeness check that no content was lost.
> **Rationale:** Refactoring must restructure, not summarise. Dropped sentences or values represent irreversible knowledge loss. Supports the context-preservation principle.
> **Acceptance Criteria:** Given a source paragraph with 4 sentences and a refactored version with only 3 sentences (one dropped), the completeness check fails. Given a refactored version that rephrases all 4 sentences but preserves all information, the completeness check passes.

> **FR-506** | Priority: MUST
> **Description:** Refactoring MUST adhere to the following constraints: never add information not in the source, never remove content, never change meaning, preserve all numerical values exactly, and only expand abbreviations found in the document or the domain vocabulary.
> **Rationale:** These constraints are the safety boundary for LLM-based content manipulation in a mission-critical environment. Violating any one of them could propagate incorrect information into engineering decisions. Supports the context-preservation principle.
> **Acceptance Criteria:** Given source text "The PVT corners are nominal", the refactored text may expand to "The Process-Voltage-Temperature (PVT) corners are nominal" if PVT is in the vocabulary, but must not add "at 25°C" unless that temperature appears in the source. Given a numerical value "3.3V ± 5%", the refactored text preserves "3.3V ± 5%" exactly.

> **FR-507** | Priority: MUST
> **Description:** If all refactoring iterations fail validation, the system MUST return the original text unchanged (fail-safe).
> **Rationale:** A failed refactoring attempt must never result in corrupted or partially-refactored text entering the pipeline. The original text is always a safe fallback. Supports the fail-safe-over-fail-fast principle.
> **Acceptance Criteria:** Given 3 iterations where each fails fact-check or completeness validation, the system returns the exact original text byte-for-byte. The system logs a warning indicating refactoring failed for the section. No exception is raised.

> **FR-508** | Priority: MUST
> **Description:** If completeness falls below 80%, the system MUST reject the refactored text and return the original.
> **Rationale:** A completeness score below 80% indicates significant content loss, making the refactored text unreliable. The 80% threshold provides a concrete, measurable safety net.
> **Acceptance Criteria:** Given a completeness score of 0.75 (75%), the system rejects the refactored text and returns the original. Given a completeness score of 0.85 (85%), the system accepts the refactored text. The completeness score and accept/reject decision are logged.

> **FR-509** | Priority: MUST
> **Description:** Refactoring MUST NOT mutate source-of-truth documents. The pipeline MUST persist original and refactored mirror artifacts as separate representations.
> **Rationale:** Refactoring improves retrieval utility but can introduce representation drift. Keeping immutable source plus derived mirror prevents accidental overwrite of authoritative content while preserving auditability.
> **Acceptance Criteria:** Given a source document and refactoring enabled, ingestion writes a mirror pair (original representation and refactored representation) without modifying the source file. Given refactoring disabled, only original representation is required.

> **FR-510** | Priority: MUST
> **Description:** Every stored chunk produced from refactored text MUST include provenance mapping back to source-of-truth location (URI plus positional mapping or equivalent).
> **Rationale:** Retrieval from derived text must still cite original evidence. Without provenance mapping, generated answers can become ungrounded even if retrieval quality is high.
> **Acceptance Criteria:** Given a retrieved chunk from refactored text, metadata includes source URI and source span mapping fields. If exact span mapping fails, metadata records fallback method and confidence score.

> **FR-511** | Priority: MUST
> **Description:** Citation outputs MUST resolve to original source references, not only refactored chunk text.
> **Rationale:** Engineering decisions require traceability to authoritative source material. Derived text may improve retrieval but cannot replace source provenance in citations.
> **Acceptance Criteria:** Given an answer citing information from a refactored chunk, the citation payload includes original source URI and mapped source location. UI/CLI presentation can optionally show that retrieval text origin was refactored.

### 3.6 Chunking (FR-600)

> **FR-601** | Priority: MUST
> **Description:** The system MUST split document text into semantically coherent chunks that respect topic boundaries, specification blocks, and procedure sequences.
> **Rationale:** Naive fixed-size splitting breaks mid-sentence or mid-specification, producing chunks that lose meaning in isolation. Semantic chunking preserves the coherence needed for accurate retrieval. Addresses the context-loss problem from isolated paragraphs.
> **Acceptance Criteria:** Given a section containing a 3-step procedure (Step 1, Step 2, Step 3), the chunker keeps all 3 steps in the same chunk if they fit within the size limit. Given two topically distinct subsections ("Clock Distribution" and "Power Grid"), they are placed in separate chunks. Given a specification block with related parameters, the parameters are not split across chunks.

> **FR-602** | Priority: MUST
> **Description:** Chunk size MUST be configurable with target, minimum, and maximum token limits.
> **Rationale:** Optimal chunk size depends on the embedding model, retrieval strategy, and document characteristics. Configurable limits allow tuning without code changes. Supports the configuration-driven-behaviour principle.
> **Acceptance Criteria:** Given configuration `chunk_size.target = 512, chunk_size.min = 100, chunk_size.max = 1024`, chunks are produced targeting ~512 tokens, with no chunk below 100 tokens (except the final chunk of a section) and no chunk exceeding 1024 tokens. Changing these values in configuration changes the chunk sizes produced.

> **FR-603** | Priority: MUST
> **Description:** The target chunk size MUST account for downstream enrichment overhead (boundary context) to prevent exceeding the embedding model's input token limit.
> **Rationale:** Boundary context (FR-703) adds tokens to the embedding input. If the chunk itself already uses the full token budget, the enriched input will exceed the model's limit, causing truncation or errors.
> **Acceptance Criteria:** Given an embedding model with 8192 token limit and boundary context configured to add up to 200 tokens, the effective maximum chunk size is at most 8192 - 200 = 7992 tokens. No enriched chunk (chunk + boundary context) exceeds the embedding model's input token limit.

> **FR-604** | Priority: MUST
> **Description:** Tables MUST be treated as indivisible chunking units by default (configurable). Tables exceeding maximum chunk size MUST be split row-wise with the header row prepended to every fragment.
> **Rationale:** Splitting a table mid-row produces meaningless fragments. Keeping tables atomic preserves data integrity. When a table is too large, prepending headers to each fragment ensures every fragment is interpretable on its own. Supports the context-preservation principle.
> **Acceptance Criteria:** Given a 10-row pin table within the maximum chunk size, it appears as a single chunk. Given a 200-row register map exceeding the maximum chunk size, it is split into multiple chunks where each chunk starts with the original header row (`| Register | Address | Width | Description |`) followed by a subset of data rows. Given `tables.keep_atomic = false` in configuration, tables may be split at any boundary.

> **FR-605** | Priority: MUST
> **Description:** Each chunk MUST receive a deterministic identifier derived from the document ID, chunk position, and content hash. Re-ingesting the same document with identical content MUST produce identical chunk IDs.
> **Rationale:** Deterministic chunk IDs enable the re-ingestion mechanism to identify and replace specific chunks. Without determinism, every re-ingestion would appear as entirely new content. Supports the idempotency-by-construction principle.
> **Acceptance Criteria:** Given the same document ingested twice with no content changes, all chunk IDs are identical across both runs. Given a document where only section 5 changes, chunks derived from unchanged sections produce the same IDs. The chunk ID is a string that encodes document ID, position index, and a content-derived hash component.

> **FR-606** | Priority: MUST
> **Description:** Each chunk MUST carry adjacency links (previous/next chunk IDs) to enable context expansion at retrieval time.
> **Rationale:** Retrieval sometimes returns a chunk that is only partially relevant; adjacency links let the retrieval layer fetch surrounding chunks for additional context without re-processing the document. Supports the context-preservation principle.
> **Acceptance Criteria:** Given a document split into chunks C1, C2, C3, chunk C2 has `previous_chunk_id = C1.id` and `next_chunk_id = C3.id`. Chunk C1 has `previous_chunk_id = null` and chunk C3 has `next_chunk_id = null`. After quality validation removes a chunk, adjacency links are repaired (see FR-1105).

> **FR-607** | Priority: MUST
> **Description:** Each chunk MUST be tagged with its production method (e.g., LLM-driven, deterministic fallback, table-specific).
> **Rationale:** Knowing how a chunk was produced enables quality analysis and debugging. If retrieval quality degrades, operators can correlate with production method to identify whether fallback chunking is the cause.
> **Acceptance Criteria:** Given a chunk produced by the LLM chunker, it has `production_method = "llm"`. Given a chunk produced by the deterministic fallback, it has `production_method = "deterministic_fallback"`. Given a table chunk, it has `production_method = "table"`. The tag is stored as chunk metadata.

> **FR-608** | Priority: MUST
> **Description:** If the primary (LLM-driven) chunking fails, the system MUST fall back to a deterministic recursive splitter on paragraph/sentence boundaries.
> **Rationale:** LLM calls can fail due to rate limits, timeouts, or provider outages. A deterministic fallback ensures the pipeline always produces chunks rather than halting. Supports the fail-safe-over-fail-fast principle.
> **Acceptance Criteria:** Given an LLM API failure during chunking, the system switches to the deterministic splitter and produces valid chunks. The fallback chunks respect paragraph and sentence boundaries (no mid-sentence splits except when a single sentence exceeds the maximum chunk size). The pipeline logs a warning indicating the fallback was used.

> **FR-609** | Priority: MUST
> **Description:** Each chunk MUST carry a content type tag (text, table, figure, code, equation, list, heading).
> **Rationale:** Content type enables type-specific retrieval filtering (e.g., "show me only tables") and type-aware ranking at retrieval time. Different content types may also require different embedding strategies.
> **Acceptance Criteria:** Given a chunk containing a markdown table, it has `content_type = "table"`. Given a chunk containing a code block, it has `content_type = "code"`. Given a chunk containing narrative text, it has `content_type = "text"`. Given a chunk containing a figure description, it has `content_type = "figure"`.

> **FR-610** | Priority: MUST
> **Description:** Sections exceeding a configurable size limit MUST be pre-split at paragraph boundaries before chunking to keep processing windows within manageable limits.
> **Rationale:** Very large sections sent to an LLM chunker in a single call may exceed context window limits or produce poor chunking decisions. Pre-splitting reduces the problem size while preserving paragraph integrity.
> **Acceptance Criteria:** Given a section of 50,000 tokens and a pre-split limit of 10,000 tokens, the section is split into approximately 5 segments at paragraph boundaries before being sent to the chunker. Given a section of 5,000 tokens with the same limit, no pre-splitting occurs. Pre-splits never break mid-paragraph.

> **FR-611** | Priority: MUST
> **Description:** Token counting MUST use the actual tokeniser from the configured embedding model to correctly handle domain-specific terminology. A conservative approximation MUST be available as a fallback.
> **Rationale:** Different tokenisers produce different token counts for the same text, especially for domain-specific terms (e.g., "SystemVerilog" may be 1 or 3 tokens depending on the tokeniser). Using the wrong tokeniser could cause chunks to exceed the model's input limit. Supports the swappability-over-lock-in principle.
> **Acceptance Criteria:** Given an embedding model with a specific tokeniser, the system uses that tokeniser for all token counts. Given a term like "clock_domain_crossing_check", the count matches the model's actual tokenisation. If the model tokeniser is unavailable, the fallback uses a conservative ratio (e.g., 1 token per 3.5 characters) that overestimates rather than underestimates token count.

### 3.7 Chunk Enrichment (FR-700)

> **FR-701** | Priority: MUST
> **Description:** The system MUST construct metadata context headers for each chunk containing: domain, document type, title, section path, content type, review tier, and linked content references.
> **Rationale:** Context headers provide the structured metadata needed for filtering, display, and retrieval-time decisions. Without them, chunks are anonymous text fragments with no organisational context. Supports the context-preservation principle.
> **Acceptance Criteria:** Given a chunk from section "3.2 Core Power" in document "ASIC_Power_Spec_v2.pdf" classified as domain "ASIC Design" and review tier "Approved", the context header includes all of: `domain: "ASIC Design"`, `document_type: "Specification"`, `title: "ASIC_Power_Spec_v2"`, `section_path: "Power Specifications > Core Power"`, `content_type: "text"`, `review_tier: "Approved"`. No fields are omitted.

> **FR-702** | Priority: MUST
> **Description:** Context headers MUST be stored as metadata properties for filtering and display. Context headers MUST NOT be embedded into the vector by default (configurable).
> **Rationale:** Embedding metadata into the vector dilutes the semantic signal of the actual content. Storing metadata as filterable properties enables precise pre-filtering (e.g., "only Approved documents in ASIC Design domain") without compromising embedding quality. Supports the configuration-driven-behaviour principle.
> **Acceptance Criteria:** By default, the vector embedding input contains only the chunk content and boundary context — not the context header fields. The metadata fields are stored as separate filterable properties in the vector store. Given configuration `enrichment.embed_headers = true`, the context header is prepended to the embedding input. A retrieval query filtering on `domain = "ASIC Design"` uses the metadata property, not vector similarity.

> **FR-703** | Priority: MUST
> **Description:** The system MUST inject boundary context (last N sentences from the preceding chunk) into each chunk's embedding input to capture topic transitions. The number of sentences MUST be configurable.
> **Rationale:** Chunk boundaries are artificial — a topic may span two chunks. Injecting trailing sentences from the previous chunk into the embedding input captures continuity that would otherwise be lost, improving retrieval recall for queries that span chunk boundaries.
> **Acceptance Criteria:** Given `enrichment.boundary_sentences = 3` and a preceding chunk ending with sentences S1, S2, S3, the current chunk's embedding input is prepended with S1, S2, S3. Given the first chunk in a document (no predecessor), no boundary context is added. Given `boundary_sentences = 0`, no boundary context is injected for any chunk.

> **FR-704** | Priority: MUST
> **Description:** Boundary context MUST improve embedding recall without consuming excessive embedding capacity. If the enriched content exceeds the embedding model's input limit, boundary context MUST be trimmed rather than chunk content.
> **Rationale:** The chunk's own content is the primary semantic signal and must never be truncated. Boundary context is supplementary; trimming it preserves the core content integrity. Supports the context-preservation principle.
> **Acceptance Criteria:** Given a chunk of 7,800 tokens, boundary context of 500 tokens, and an embedding model limit of 8,192 tokens, the boundary context is trimmed to 392 tokens (or fewer) so the total does not exceed 8,192. The chunk's own content (7,800 tokens) is never truncated. Given a chunk of 4,000 tokens with 500 tokens of boundary context and the same model limit, no trimming occurs.

> **FR-705** | Priority: MUST
> **Description:** The raw chunk content MUST be preserved separately from the enriched embedding input for display in retrieval results.
> **Rationale:** Users viewing retrieval results should see the original chunk text, not text polluted with boundary context from adjacent chunks. Separating raw and enriched versions serves both embedding quality and user experience.
> **Acceptance Criteria:** Given a chunk with raw content "The VDD_CORE supply is 1.0V nominal" and enriched content that includes boundary context prepended, both versions are stored. The retrieval API returns the raw content for display. The enriched content is used only for generating the embedding vector. Modifying the boundary context configuration and re-ingesting does not alter the stored raw content.
>
### 3.8 Metadata Generation (FR-800)

> **FR-801** | Priority: MUST
> **Description:** The system MUST generate document-level metadata: summary (2-3 sentences), technical keywords (10-20), named entities, topic categories, domain classification, and document type classification.
> **Rationale:** Document-level metadata enables faceted filtering and retrieval-time ranking. Without structured metadata, queries cannot distinguish between documents by domain, type, or topic, worsening knowledge fragmentation across engineering teams.
> **Acceptance Criteria:** Given a design specification document for a 5nm ASIC clock distribution network, the system produces: a 2-3 sentence summary mentioning clock distribution; between 10 and 20 keywords including domain terms (e.g., "clock tree synthesis", "skew budgeting"); named entities (e.g., "TSMC N5"); a domain classification (e.g., "Physical Design"); and a document type (e.g., "Specification"). A document with fewer than 10 extractable keywords still produces at least 10 keywords or explicitly flags the shortfall.

> **FR-802** | Priority: MUST
> **Description:** The system MUST generate chunk-level metadata: keywords (5-10) and named entities for each chunk.
> **Rationale:** Chunk-level metadata supports fine-grained retrieval filtering, ensuring search results can be narrowed to chunks that specifically discuss the queried concept rather than returning entire documents. This directly addresses the term ambiguity problem where "clock domain" has different meanings in different contexts.
> **Acceptance Criteria:** Given a chunk discussing DFT scan chain insertion for a 7nm design, the system produces 5-10 keywords (e.g., "scan chain", "DFT", "ATPG", "fault coverage", "test compression") and named entities (e.g., "Synopsys DFT Compiler"). A chunk with only 3 extractable keywords produces exactly those 3 without padding with unrelated terms.

> **FR-803** | Priority: MUST
> **Description:** All LLM-generated keywords and entities MUST pass a validation gate ensuring they are grounded in the chunk content (direct presence, abbreviation bridge, or compound term overlap). Keywords inferred by association but not discussed in the chunk MUST be discarded.
> **Rationale:** Supports the context-preservation design principle. LLMs may hallucinate plausible-sounding keywords (e.g., generating "power integrity" for a chunk that only discusses signal integrity), which would cause false-positive retrievals and erode trust in search results.
> **Acceptance Criteria:** Given a chunk that discusses "CTS" (clock tree synthesis) but never mentions "OCV" (on-chip variation), an LLM-generated keyword "OCV" is discarded because it has no direct presence, abbreviation bridge, or compound term overlap in the chunk. A keyword "clock tree synthesis" is retained via abbreviation bridge to "CTS" present in the chunk text.

> **FR-804** | Priority: MUST
> **Description:** Document-level keywords MUST be stored as filterable properties but MUST NOT be keyword-indexed at the chunk level to prevent false positives.
> **Rationale:** Indexing document-level keywords at the chunk level would cause every chunk in a document to match queries for terms discussed only in other sections. This directly causes the term ambiguity problem described in the problem statement, where a search for "power grid" returns chunks about unrelated topics simply because the parent document mentions power grids elsewhere.
> **Acceptance Criteria:** Given a 50-page SoC integration guide where only Section 4 discusses "thermal management", a BM25 keyword search for "thermal management" returns only chunks from Section 4, not chunks from other sections. Document-level metadata for the guide includes "thermal management" as a filterable property for document-level queries.

> **FR-805** | Priority: MUST
> **Description:** If the LLM call fails, the system MUST fall back to a deterministic frequency-based keyword extraction (TF-IDF).
> **Rationale:** Supports the fail-safe-over-fail-fast design principle. Metadata generation must not block the pipeline; TF-IDF provides acceptable keyword extraction quality to ensure every chunk has searchable metadata even when the LLM is unavailable.
> **Acceptance Criteria:** Given an LLM timeout during metadata generation for a chunk containing "The scan chain length was optimised from 1500 to 800 flip-flops to reduce test time", the TF-IDF fallback produces keywords including "scan chain", "flip-flops", and "test time". The pipeline continues without halting, and the chunk's metadata includes a flag indicating fallback extraction was used.

> **FR-806** | Priority: MUST
> **Description:** The system MUST support domain vocabulary injection into metadata generation prompts to ensure canonical domain terminology is used.
> **Rationale:** Supports configuration-driven-behaviour. Without vocabulary injection, the LLM may generate inconsistent terminology (e.g., "DFT" vs "Design for Test" vs "Design for Testability"), fragmenting search results for the same concept across different keyword forms.
> **Acceptance Criteria:** Given a domain vocabulary entry mapping "DFT" to "Design for Testability", metadata generation for a chunk mentioning "DFT" produces the canonical keyword "Design for Testability" (or both "DFT" and "Design for Testability") rather than a non-canonical variant like "Design for Test". Removing the vocabulary entry results in the LLM choosing its own expansion.

---

### 3.9 Cross-Reference Extraction (FR-900)

> **FR-901** | Priority: MUST
> **Description:** The system MUST detect cross-references between documents, sections, and external standards.
> **Rationale:** Engineering documents form a web of dependencies; a specification may reference a design guide, which references an IEEE standard. Without cross-reference extraction, these relationships are invisible to retrieval, and the system cannot surface related documents or perform impact analysis when a referenced standard is updated.
> **Acceptance Criteria:** Given a document containing "Refer to Section 3.2 of the Clock Domain Crossing Guidelines (CDC_GUIDE_v2.1)" and "per IEEE 1149.1", the system extracts at least two cross-references: one internal reference to CDC_GUIDE_v2.1 Section 3.2, and one external standard reference to IEEE 1149.1. Each reference includes type, target identifier, and source location.

> **FR-902** | Priority: MUST
> **Description:** Cross-reference extraction MUST be skippable via configuration.
> **Rationale:** Supports configuration-driven-behaviour. Some ingestion runs (e.g., quick re-indexing of a single updated document) may not need cross-reference extraction, and skipping it reduces processing time and LLM costs.
> **Acceptance Criteria:** Given a pipeline configuration with `cross_reference_extraction.enabled: false`, the cross-reference extraction stage is skipped entirely (no LLM calls, no regex matching). The pipeline log records the stage as "skipped". Setting `cross_reference_extraction.enabled: true` enables the stage and produces cross-reference output.

> **FR-903** | Priority: MUST
> **Description:** The system MUST support both deterministic pattern matching (regex) and LLM-based extraction for implicit references.
> **Rationale:** Regex reliably captures explicit, well-formatted references (e.g., "IEEE 1149.1", "Section 3.2"), while LLM-based extraction catches implicit references (e.g., "the timing constraints discussed in the companion document") that no regex can match. Supporting both maximises recall while ensuring a deterministic baseline per the fail-safe-over-fail-fast principle.
> **Acceptance Criteria:** Given text containing both "per JEDEC JESD79-4" (explicit) and "as described in the power delivery analysis performed last quarter" (implicit), the regex path extracts the JEDEC reference, and the LLM path identifies the implicit reference to a power delivery analysis document. When the LLM is unavailable, only the regex-extracted references are returned and the implicit reference is not extracted.

> **FR-904** | Priority: MUST
> **Description:** Detected reference types MUST include: explicit (section/document citations), standard (IEEE, JEDEC, ISO), version, dependency, and implicit references.
> **Rationale:** Different reference types serve different retrieval and impact analysis needs. Version references enable traceability across document revisions; dependency references enable impact analysis when upstream documents change; standard references connect internal documents to external normative sources.
> **Acceptance Criteria:** Given a document containing "See Section 5 of SPEC-CLK-001 v2.3", "compliant with IEEE 1801-2015 (UPF)", "This design depends on the PDN model from PWR-ANALYSIS-003", and "using the approach outlined earlier", the system produces references of types: explicit (Section 5 of SPEC-CLK-001), standard (IEEE 1801-2015), version (v2.3), dependency (PWR-ANALYSIS-003), and implicit ("the approach outlined earlier"). Each reference carries a `type` field matching one of the five enumerated types.

> **FR-905** | Priority: MUST
> **Description:** Duplicate references MUST be merged, with LLM-extracted versions taking priority.
> **Rationale:** The same reference may be detected by both regex and LLM extraction. Merging avoids inflating the reference count and cluttering the knowledge graph, while prioritising the LLM version ensures richer metadata (e.g., the LLM may resolve an implicit reference target that regex cannot).
> **Acceptance Criteria:** Given that regex extracts a reference to "IEEE 1149.1" with type "standard" and the LLM also extracts a reference to "IEEE 1149.1 (JTAG boundary scan standard)" with type "standard" and additional context, the system produces a single merged reference to "IEEE 1149.1" retaining the LLM's enriched description. The final reference list contains no duplicate target identifiers.

---

### 3.10 Knowledge Graph Extraction (FR-1000)

> **FR-1001** | Priority: MUST
> **Description:** The system MUST extract structured subject-predicate-object triples from document content to build a knowledge graph enabling relationship-aware retrieval and impact analysis.
> **Rationale:** Vector similarity search alone cannot answer relational queries such as "which specifications constrain this design block?" or "what changes if we update the PDN model?". A knowledge graph captures these structural relationships, directly addressing the knowledge fragmentation problem by making inter-document dependencies explicit and queryable.
> **Acceptance Criteria:** Given a chunk stating "The clock distribution network uses a H-tree topology and must meet the skew budget defined in SPEC-CLK-001", the system extracts at least two triples: ("clock distribution network", "uses", "H-tree topology") and ("clock distribution network", "constrained_by", "SPEC-CLK-001"). Triples are stored as structured objects with subject, predicate, and object fields.

> **FR-1002** | Priority: MUST
> **Description:** Knowledge graph extraction MUST be skippable via configuration.
> **Rationale:** Supports configuration-driven-behaviour. Knowledge graph extraction involves significant LLM cost and processing time; teams that do not need relationship-aware retrieval can disable it to reduce cost and latency without affecting core vector search functionality.
> **Acceptance Criteria:** Given a pipeline configuration with `knowledge_graph.enabled: false`, the KG extraction stage is skipped (no LLM calls, no structural triple generation). The pipeline log records the stage as "skipped". Downstream stages (Quality Validation, Embedding & Storage) proceed normally without KG data.

> **FR-1003** | Priority: MUST
> **Description:** The system MUST generate structural triples deterministically (document-chunk containment, adjacency, domain membership, authorship, abbreviation mappings, cross-references).
> **Rationale:** Supports idempotency-by-construction. Structural triples derived from document hierarchy are always available regardless of LLM availability, providing a guaranteed baseline knowledge graph. Deterministic generation ensures re-ingesting the same document always produces the same structural triples.
> **Acceptance Criteria:** Given a document "SPEC-CLK-001" by author "J. Smith" in domain "Physical Design" with chunks C1 and C2 (adjacent), the system produces triples including: ("SPEC-CLK-001", "contains", "C1"), ("SPEC-CLK-001", "contains", "C2"), ("C1", "adjacent_to", "C2"), ("SPEC-CLK-001", "belongs_to_domain", "Physical Design"), ("SPEC-CLK-001", "authored_by", "J. Smith"). Re-ingesting the same document produces identical triples.

> **FR-1004** | Priority: MUST
> **Description:** The system MUST consolidate entities across chunks via exact-match deduplication, abbreviation resolution, and fuzzy matching.
> **Rationale:** The same entity often appears in different forms across chunks (e.g., "Clock Data Recovery" in one chunk, "CDR" in another, "clock data recovery circuit" in a third). Without consolidation, the knowledge graph fragments into disconnected nodes representing the same real-world entity, defeating the purpose of relationship-aware retrieval.
> **Acceptance Criteria:** Given three chunks where Chunk A mentions "Clock Data Recovery", Chunk B mentions "CDR", and Chunk C mentions "clock data recovery", all three are consolidated into a single entity node "Clock Data Recovery" with alias "CDR". The knowledge graph contains one node, not three. Fuzzy matching merges "clock data recovery circuit" with "Clock Data Recovery" but does not merge "CDR" (Clock Data Recovery) with "CDR" (Critical Design Review) when domain context disambiguates them.

> **FR-1005** | Priority: MUST
> **Description:** The system MUST optionally use LLM-based relationship extraction with a controlled predicate vocabulary.
> **Rationale:** A controlled predicate vocabulary (e.g., "uses", "constrained_by", "implements", "depends_on") ensures the knowledge graph is queryable with consistent predicates rather than free-form natural language, while LLM extraction captures semantic relationships that structural analysis cannot detect.
> **Acceptance Criteria:** Given a controlled vocabulary of 15 predicates and a chunk stating "The OCV derating factors are applied during static timing analysis", the LLM extracts a triple ("OCV derating factors", "applied_during", "static timing analysis") where "applied_during" is from the controlled vocabulary. If the LLM proposes a predicate not in the vocabulary (e.g., "are used in"), the system maps it to the nearest controlled predicate or discards the triple.

> **FR-1006** | Priority: MUST
> **Description:** All LLM-extracted triples MUST be validated: subjects and objects must appear in the chunk content or entity list. Invalid triples MUST be discarded.
> **Rationale:** Supports context-preservation. LLMs may hallucinate plausible relationships involving entities not actually discussed in the source chunk. Storing ungrounded triples would introduce false relationships into the knowledge graph, leading to incorrect impact analysis and misleading retrieval results.
> **Acceptance Criteria:** Given a chunk that discusses "scan chain insertion" and "DFT Compiler" but not "formal verification", an LLM-extracted triple ("DFT Compiler", "supports", "formal verification") is discarded because "formal verification" does not appear in the chunk content or consolidated entity list. A triple ("DFT Compiler", "performs", "scan chain insertion") is retained because both subject and object are grounded.

> **FR-1007** | Priority: MUST
> **Description:** If LLM extraction fails, the system MUST build the knowledge graph from structural triples and entity consolidation only.
> **Rationale:** Supports fail-safe-over-fail-fast. A knowledge graph built from structural triples alone (containment, adjacency, domain membership) still provides value for document navigation and basic impact analysis, ensuring the pipeline produces useful output even when the LLM is unavailable.
> **Acceptance Criteria:** Given an LLM failure during KG extraction for a 30-page document with 45 chunks, the system produces structural triples (containment, adjacency, domain, authorship, abbreviation mappings) and consolidated entities without any LLM-derived relationship triples. The pipeline log records the LLM failure and indicates fallback to structural-only mode. The resulting knowledge graph is still navigable from document to chunks.

> **FR-1008** | Priority: MUST
> **Description:** Triple identifiers MUST be deterministic, derived from document ID, subject, predicate, and object.
> **Rationale:** Supports idempotency-by-construction. Deterministic triple IDs ensure that re-ingesting the same document produces triples with the same identifiers, enabling clean upsert operations during re-ingestion and preventing duplicate triples from accumulating in the graph store.
> **Acceptance Criteria:** Given a triple ("SPEC-CLK-001", "contains", "chunk_abc123") extracted from document "SPEC-CLK-001", the triple ID is a deterministic hash of (document_id, subject, predicate, object). Re-ingesting the same document produces a triple with the identical ID. Changing the object to "chunk_def456" produces a different triple ID.

> **FR-1009** | Priority: MUST
> **Description:** The maximum number of triples per chunk MUST be configurable.
> **Rationale:** Supports configuration-driven-behaviour. Dense technical chunks can produce hundreds of triples, inflating storage costs and slowing graph queries. A configurable cap lets teams balance knowledge graph richness against storage and performance constraints.
> **Acceptance Criteria:** Given a configuration `knowledge_graph.max_triples_per_chunk: 20` and a chunk from which the LLM extracts 35 triples, only the top 20 triples (ranked by validation confidence or extraction order) are retained. Changing the configuration to `max_triples_per_chunk: 50` retains all 35 triples. Setting it to `0` disables the cap.

---

### 3.11 Quality Validation (FR-1100)

> **FR-1101** | Priority: MUST
> **Description:** The system MUST remove chunks below a configurable minimum token count.
> **Rationale:** Very short chunks (e.g., a section header with no body text) produce low-quality embeddings that pollute search results with near-meaningless matches. Removing them improves retrieval precision without losing substantive content.
> **Acceptance Criteria:** Given a configuration `quality.min_token_count: 50` and a chunk containing only "3.2 Clock Tree Results" (5 tokens), the chunk is removed from the pipeline. A chunk with 51 tokens is retained. Changing the threshold to `min_token_count: 3` retains the 5-token chunk.

> **FR-1102** | Priority: MUST
> **Description:** The system MUST detect and remove near-duplicate chunks based on content similarity exceeding a configurable threshold.
> **Rationale:** Document boilerplate (e.g., repeated disclaimers, identical headers across sections) produces near-duplicate chunks that waste storage and dilute retrieval results by returning effectively the same content multiple times.
> **Acceptance Criteria:** Given a threshold of `quality.dedup_similarity_threshold: 0.95` and two chunks with 97% content similarity (e.g., identical disclaimer paragraphs from two sections), one chunk is removed as a near-duplicate. Two chunks with 90% similarity (e.g., similar but distinct design rule descriptions for different metal layers) are both retained. The removed chunk is logged with the ID of the chunk it duplicates.

> **FR-1103** | Priority: MUST
> **Description:** The system MUST assign a quality score (0.0-1.0) to each surviving chunk based on content signals (technical term density, numerical density, structured content, chunk length, whitespace ratio, boilerplate presence, extraction confidence).
> **Rationale:** Not all chunks carry equal informational value. Quality scores enable retrieval-time weighting so that dense, information-rich chunks (e.g., a timing constraints table) rank higher than sparse, boilerplate-heavy chunks, improving answer quality without discarding low-scoring content entirely.
> **Acceptance Criteria:** Given a chunk containing a timing constraints table with 12 numerical values and 8 technical terms, the quality score is above 0.7. Given a chunk containing a generic project introduction with no numerical values and 1 technical term, the quality score is below 0.4. Scores are floating-point values in the range [0.0, 1.0] with at least two decimal places of precision.

> **FR-1104** | Priority: MUST
> **Description:** Quality scores MUST be stored with the chunk and available for retrieval-time quality weighting.
> **Rationale:** Supports controlled-access-over-restriction. Rather than discarding low-quality chunks outright, storing quality scores allows the retrieval layer to apply configurable weighting, ensuring that even low-quality chunks remain searchable when a user broadens their search.
> **Acceptance Criteria:** Given a stored chunk in the vector database, the chunk object includes a `quality_score` field of type float. A retrieval query can filter or boost results using the quality score (e.g., `quality_score >= 0.5`). The quality score is present on 100% of stored chunks.

> **FR-1105** | Priority: MUST
> **Description:** After removing low-quality and duplicate chunks, the system MUST repair adjacency links to skip over removed chunks.
> **Rationale:** Supports context-preservation. Adjacency links enable the retrieval layer to fetch surrounding chunks for context. If a removed chunk breaks the adjacency chain, the retrieval layer loses the ability to reconstruct reading order, reintroducing the context loss problem described in the problem statement.
> **Acceptance Criteria:** Given chunks [C1, C2, C3, C4] where C2 is removed as a near-duplicate and C3 is removed for being below minimum token count, the adjacency links are repaired so that C1.next = C4 and C4.previous = C1. Before repair, C1.next = C2. After repair, no adjacency link points to a removed chunk.

---

### 3.12 Embedding & Storage (FR-1200)

> **FR-1201** | Priority: MUST
> **Description:** The system MUST generate vector embeddings for all surviving chunks using the configured embedding model.
> **Rationale:** Vector embeddings are the core output of the pipeline, enabling semantic similarity search. Without embeddings, chunks cannot be retrieved by meaning, and the system fails its primary purpose of transforming documents into semantically searchable representations.
> **Acceptance Criteria:** Given 45 surviving chunks after quality validation, the system produces exactly 45 embedding vectors, one per chunk. Each vector has the dimensionality specified by the configured embedding model (e.g., 1024 for a model configured with `embedding.dimension: 1024`). No chunk is stored without an embedding.

> **FR-1202** | Priority: MUST
> **Description:** The embedding model, dimension, and provider MUST be configurable.
> **Rationale:** Supports swappability-over-lock-in. Embedding models evolve rapidly; teams must be able to switch from one provider (e.g., OpenAI) to another (e.g., Cohere, a local model) without code changes, enabling cost optimisation and adaptation to domain-specific models as they become available.
> **Acceptance Criteria:** Given a configuration change from `embedding.model: "text-embedding-3-large"` and `embedding.provider: "openai"` to `embedding.model: "embed-english-v3.0"` and `embedding.provider: "cohere"`, the system uses the Cohere model without any code changes. The embedding dimension updates accordingly. An invalid provider name produces a clear configuration error at startup, not at embedding time.

> **FR-1203** | Priority: MUST
> **Description:** The system MUST validate that the actual embedding dimension matches the configured dimension on the first batch. Mismatched dimensions MUST halt the stage.
> **Rationale:** A dimension mismatch between the embedding model and the vector store schema causes silent data corruption: vectors are stored but produce meaningless similarity scores. Halting immediately prevents an entire batch of documents from being stored with unusable embeddings.
> **Acceptance Criteria:** Given a configuration `embedding.dimension: 1024` but an embedding model that produces 768-dimensional vectors, the system detects the mismatch on the first batch of embeddings, logs an error including both expected (1024) and actual (768) dimensions, and halts the embedding stage. No chunks are written to the vector store. When dimensions match (both 1024), the stage proceeds normally.

> **FR-1204** | Priority: MUST
> **Description:** The system MUST store chunks with their embeddings, metadata (32+ properties), and pre-computed vectors in the vector database.
> **Rationale:** Rich metadata stored alongside embeddings enables hybrid retrieval (vector + metadata filtering) without requiring separate lookups, which is essential for scoping queries to specific domains, document types, review tiers, or technology nodes in a semiconductor engineering context.
> **Acceptance Criteria:** Given a chunk from a 5nm standard cell library specification, the stored vector database object includes: the embedding vector, the chunk text, and at least 32 metadata properties including document_id, chunk_id, section_hierarchy, domain, document_type, review_tier, quality_score, keywords, named_entities, source_file, and content_hash. For refactored retrieval text, metadata also includes provenance fields (source URI plus source/refactored span mapping and confidence). All filterable properties remain queryable.

> **FR-1205** | Priority: MUST
> **Description:** The system MUST use Bring Your Own Model (BYOM) mode, computing embeddings externally and passing pre-computed vectors to the vector store.
> **Rationale:** Supports swappability-over-lock-in. BYOM decouples the embedding model from the vector store, allowing the team to use any embedding model (including fine-tuned or locally hosted models) regardless of the vector store provider's native model support.
> **Acceptance Criteria:** Given a locally hosted embedding model that produces 1024-dimensional vectors, the system computes embeddings using the local model and stores the pre-computed vectors in the vector database (e.g., Weaviate) without invoking any vectoriser module built into the vector store. The vector store is configured in BYOM/none-vectoriser mode.

> **FR-1206** | Priority: MUST
> **Description:** The system MUST support asymmetric embedding prefixes (different prefixes for documents vs queries) as required by certain embedding models.
> **Rationale:** Some embedding models (e.g., E5, BGE) require different input prefixes for documents ("passage:") and queries ("query:") to produce embeddings in a shared space. Without prefix support, these models produce misaligned embeddings that degrade retrieval quality.
> **Acceptance Criteria:** Given a configuration `embedding.document_prefix: "passage: "` and `embedding.query_prefix: "query: "`, document chunks are embedded with the "passage: " prefix prepended to the text. The query prefix is stored in configuration for use by the downstream retrieval layer. When prefix configuration is empty, no prefix is prepended.

> **FR-1207** | Priority: MUST
> **Description:** The system MUST support hybrid search (vector similarity + BM25 keyword search) in the vector store.
> **Rationale:** Pure vector search struggles with exact term matching (e.g., searching for a specific specification ID like "SPEC-CLK-001"), while pure keyword search misses semantic matches. Hybrid search combines both strengths, which is critical in engineering documentation where both precise identifiers and conceptual queries are common.
> **Acceptance Criteria:** Given a vector store configured with hybrid search, a query for "SPEC-CLK-001 timing constraints" returns results ranked by a fusion of vector similarity (semantic match on "timing constraints") and BM25 keyword match (exact match on "SPEC-CLK-001"). A chunk containing the exact string "SPEC-CLK-001" ranks higher than a semantically similar chunk that does not contain the identifier.

> **FR-1208** | Priority: MUST
> **Description:** The system MUST support a dry-run mode that executes the full pipeline without writing to external stores.
> **Rationale:** Supports configuration-driven-behaviour. Dry-run mode enables pipeline validation, cost estimation, and debugging without side effects, which is essential when tuning chunking strategies or testing new embedding models before committing to production data changes.
> **Acceptance Criteria:** Given a configuration `pipeline.dry_run: true`, the pipeline processes a document through all stages (ingestion, chunking, embedding) but writes zero records to the vector store and zero triples to the graph store. The pipeline log reports the number of chunks, embeddings, and triples that would have been written. Setting `pipeline.dry_run: false` enables writes.

> **FR-1209** | Priority: MUST
> **Description:** The embedding provider and vector store MUST be swappable via configuration.
> **Rationale:** Supports swappability-over-lock-in. The organisation must be able to migrate from one vector store (e.g., Weaviate) to another (e.g., Qdrant, Pinecone) or switch embedding providers without modifying pipeline code, protecting against vendor lock-in and enabling competitive evaluation.
> **Acceptance Criteria:** Given a configuration change from `vector_store.provider: "weaviate"` to `vector_store.provider: "qdrant"`, the system stores chunks in Qdrant without code changes. Both providers support the same set of metadata filters and hybrid search. An unsupported provider name produces a clear error at startup.

---

### 3.13 Knowledge Graph Storage (FR-1300)

> **FR-1301** | Priority: MUST
> **Description:** The system MUST persist knowledge graph triples to a configurable graph store.
> **Rationale:** Extracted triples are only useful if persisted for query-time retrieval. A configurable store ensures the KG backend can evolve independently of the extraction logic, consistent with swappability-over-lock-in.
> **Acceptance Criteria:** Given 200 extracted triples for a document, all 200 triples are persisted to the configured graph store and are queryable after ingestion completes. A query for all triples with subject "SPEC-CLK-001" returns the expected containment, authorship, and relationship triples.

> **FR-1302** | Priority: MUST
> **Description:** The system MUST support at least two graph storage backends: vector store cross-references and a dedicated graph database.
> **Rationale:** Supports swappability-over-lock-in. Teams without a dedicated graph database can store cross-references as properties in the vector store (lower capability but zero additional infrastructure), while teams needing full graph traversal can use a dedicated graph database (e.g., Neo4j). This graduated approach avoids forcing infrastructure requirements on all deployments.
> **Acceptance Criteria:** Given a configuration `graph_store.backend: "vector_store_refs"`, triples are stored as cross-reference properties on vector store objects. Given `graph_store.backend: "neo4j"`, triples are stored as nodes and edges in Neo4j. Both backends support triple insertion, deletion by document ID, and lookup by subject. Switching between backends requires only a configuration change.

> **FR-1303** | Priority: MUST
> **Description:** The graph storage provider MUST be swappable via configuration.
> **Rationale:** Supports swappability-over-lock-in. As the knowledge graph matures, the team may need to migrate from a lightweight backend to a full graph database, and this migration must not require code changes.
> **Acceptance Criteria:** Given a configuration change from `graph_store.provider: "weaviate_refs"` to `graph_store.provider: "neo4j"`, the system persists triples to Neo4j without code changes. The pipeline produces identical triples regardless of the configured backend. An invalid provider name produces a clear error at startup.

> **FR-1304** | Priority: MUST
> **Description:** The system MUST support a dry-run mode for KG storage.
> **Rationale:** Supports configuration-driven-behaviour. Dry-run mode for KG storage enables teams to preview the knowledge graph that would be generated (triple count, entity count, relationship types) without committing data, which is essential for validating KG extraction configuration before production runs.
> **Acceptance Criteria:** Given a configuration `pipeline.dry_run: true`, the KG storage stage logs the number of triples and entities that would be persisted but writes zero records to the graph store. The triples are available in the pipeline's in-memory state for inspection. Setting `pipeline.dry_run: false` enables writes.

---


---

## Pipeline Requirements Traceability Matrix

| REQ ID | Section | Priority | Component/Stage |
|--------|---------|----------|-----------------|
| FR-101–FR-113 | 3.1 | MUST/SHOULD | Document Ingestion |
| FR-201–FR-208 | 3.2 | MUST | Structure Detection |
| FR-301–FR-307 | 3.3 | MUST | Multimodal Processing |
| FR-401–FR-405 | 3.4 | MUST | Text Cleaning |
| FR-501–FR-508 | 3.5 | MUST | Document Refactoring |
| FR-601–FR-611 | 3.6 | MUST | Chunking |
| FR-701–FR-705 | 3.7 | MUST | Chunk Enrichment |
| FR-801–FR-806 | 3.8 | MUST | Metadata Generation |
| FR-901–FR-905 | 3.9 | MUST | Cross-Reference Extraction |
| FR-1001–FR-1009 | 3.10 | MUST | Knowledge Graph Extraction |
| FR-1101–FR-1105 | 3.11 | MUST | Quality Validation |
| FR-1201–FR-1209 | 3.12 | MUST | Embedding & Storage |
| FR-1301–FR-1304 | 3.13 | MUST | Knowledge Graph Storage |

For cross-cutting requirements (FR-1400+, NFR, SC), see `INGESTION_PLATFORM_SPEC.md`.
