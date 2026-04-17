# Embedding Pipeline — Specification (v1.1.0)

## Document Information

> **Document intent:** This is a formal specification for the **Embedding Pipeline** — the eight-node ingestion phase responsible for transforming clean Markdown documents from the Clean Document Store into vector embeddings and knowledge graph triples stored in the vector database and graph store. This pipeline reads from the Clean Document Store produced by the Document Processing Pipeline; it does not receive in-memory output from that pipeline.
> For the Document Processing Pipeline functional requirements (FR-100 through FR-589), see `DOCUMENT_PROCESSING_SPEC.md`.
> For cross-cutting platform requirements (re-ingestion, config, error handling, data model, NFR), see `INGESTION_PLATFORM_SPEC.md`.

| Field | Value |
|-------|-------|
| System | AION RAG Document Embedding Pipeline |
| Document Type | Pipeline Specification — Embedding Phase |
| Companion Documents | DOCUMENT_PROCESSING_SPEC.md (Document Processing Phase Functional Requirements), INGESTION_PLATFORM_SPEC.md (Platform/Cross-Cutting Requirements), CROSS_DOCUMENT_DEDUP_SPEC.md (Cross-Document Deduplication), DOCUMENT_PROCESSING_SPEC_SUMMARY.md (Phase 1 Summary), EMBEDDING_PIPELINE_SPEC_SUMMARY.md (Phase 2 Summary), EMBEDDING_PIPELINE_IMPLEMENTATION.md (Phase 2 Implementation Guide) |
| Version | 1.1.0 |
| Status | Draft |
| Supersedes | INGESTION_PIPELINE_SPEC.md (sections 3.6–3.13) |

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2026-03-18 | AI Assistant | Created by splitting INGESTION_PIPELINE_SPEC.md at the Document Processing / Embedding boundary. Contains FR-600 through FR-1304 and adds the Clean Document Store input contract (FR-591–FR-595, a new section 3.0 before the chunking section). |
| 1.1.0 | 2026-04-15 | AI Assistant | Added batch embedding optimisation requirements (FR-1210–FR-1214) to section 3.7 — batch request formation, batch size configuration, partial batch handling, batch failure isolation, and batch throughput observability. |

---

## 1. Purpose and Scope

### 1.1 Problem Statement

ASIC design organisations accumulate critical engineering knowledge across hundreds of documents: specifications, design guides, runbooks, standard operating procedures, and project reports. This knowledge is fragmented across file servers, SharePoint, and individual workstations. When engineers leave, their contextual understanding leaves with them.

The Embedding Pipeline addresses the second phase of this problem: once documents have been parsed, cleaned, and normalised into structured Markdown by the Document Processing Pipeline, they must be transformed into a searchable index. Without this phase, the cleaned text exists only as files — not as a system engineers can query.

Existing search tools fail for engineering documentation because:

1. The same technical term carries different meaning across domains (e.g., "clock domain" spans front-end design, DFT, verification, and physical design).
2. Knowledge exists at varying levels of maturity — from formally approved specifications to an individual engineer's utility script — with no mechanism to distinguish authoritative from informal sources.
3. Documents rely on sequential reading order; isolated paragraphs lose meaning without surrounding context (e.g., "the same voltage" is ambiguous outside its original section).

This pipeline transforms cleaned, structured document text produced by the Document Processing Pipeline into a searchable index — semantic vector embeddings with rich metadata, hybrid keyword indexes, and a relationship knowledge graph — that directly addresses these three failure modes.

### 1.2 Scope

The Embedding Pipeline SHALL transform clean Markdown documents from the Clean Document Store into semantically searchable, context-aware vector embeddings stored in a vector database, with a complementary knowledge graph capturing relationships between documents, concepts, entities, and specifications.

**Entry point:** Clean Markdown document in the Clean Document Store (written by the Document Processing Pipeline; see `DOCUMENT_PROCESSING_SPEC.md`).

**Exit point:** Vector embeddings + metadata stored in vector database; knowledge graph triples stored in graph store.

**In scope:**

- Reading clean Markdown documents and companion metadata from the Clean Document Store
- Chunking: splitting documents into semantically coherent chunks with deterministic IDs
- Chunk enrichment: adding boundary context and metadata headers
- Metadata generation: generating keywords, entities, and summaries at document and chunk level
- Cross-reference extraction: detecting inter-document references and standard citations
- Knowledge graph extraction: extracting structured triples for relationship-aware retrieval
- Quality validation: filtering low-quality and duplicate chunks, assigning quality scores
- Embedding: generating vector embeddings for all surviving chunks
- Vector storage: storing chunks with embeddings and metadata in the vector database
- Knowledge graph storage: persisting triples to the graph store
- Re-embedding of updated documents (detected via `clean_hash` change detection)

**Out of scope:**

- Document format parsing, text extraction, text cleaning, and multimodal figure processing (see `DOCUMENT_PROCESSING_SPEC.md`)
- Query processing, reranking, and answer generation (downstream retrieval layer)
- User authentication and access control
- Document authoring or editing
- Real-time document change detection (push-based ingestion)

**Out of scope — broader platform components (see Strategic Proposal):**

- Skills repository and anti-skills validation framework
- AI-assisted documentation agents (background monitoring, draft generation)
- Code standardisation and Python migration initiative
- Web dashboard UI (planned for Phase 3 deployment)
- Reranker model deployment and tuning (downstream retrieval layer)
- Adoption strategy, change management, and gamification

### 1.3 Terminology

The following terms are used throughout this specification. A complete glossary is provided in the companion `INGESTION_PLATFORM_SPEC.md`.

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
| Deterministic ID | An identifier derived from content via cryptographic hashing, ensuring the same input always produces the same ID |
| HNSW | Hierarchical Navigable Small World — an approximate nearest-neighbour graph index algorithm |
| Idempotent | An operation that produces the same result whether applied once or multiple times |
| Clean Document Store | The persisted Markdown + metadata output of the Document Processing Pipeline, keyed by `source_key`. Each entry consists of a `{source_key}.md` file (clean Markdown) and a `{source_key}.meta.json` file (metadata envelope). This is the sole input source for the Embedding Pipeline. |
| source_key | A stable deterministic identity derived from the source file path. Used as the filename stem in the Clean Document Store (e.g., `a3f9c2.md`). Unchanged across re-ingestion runs as long as the source path does not change. |
| clean_hash | The SHA-256 hash of the clean Markdown file (`{source_key}.md`) as computed by the Document Processing Pipeline and stored in the metadata envelope. Used by the Embedding Pipeline for change detection: if `clean_hash` matches the stored hash from the previous embedding run, the document is skipped. |

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
| FR-591–FR-595 | 3.0 Clean Document Store Input Contract |
| FR-600–FR-699 | 3.1 Chunking |
| FR-700–FR-799 | 3.2 Chunk Enrichment |
| FR-800–FR-899 | 3.3 Metadata Generation |
| FR-900–FR-999 | 3.4 Cross-Reference Extraction |
| FR-1000–FR-1099 | 3.5 Knowledge Graph Extraction |
| FR-1100–FR-1199 | 3.6 Quality Validation |
| FR-1200–FR-1299 | 3.7 Embedding & Storage |
| FR-1300–FR-1399 | 3.8 Knowledge Graph Storage |

**Note on ID allocation:** FR-591 through FR-595 are new requirements defined in section 3.0 for the input contract. These IDs occupy the gap between the Document Processing Pipeline output contract (FR-581–FR-587 in DOCUMENT_PROCESSING_SPEC.md) and the Chunking section (FR-601–FR-611 in section 3.1). This range was chosen specifically to avoid collision with any existing FR IDs. All FR-6xx IDs in section 3.1 (Chunking) are preserved unchanged from the original specification.

For cross-cutting requirements (FR-1400+, NFR, SC), see `INGESTION_PLATFORM_SPEC.md`.

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
| A-8 | The Clean Document Store is populated by the Document Processing Pipeline (`DOCUMENT_PROCESSING_SPEC.md`) before this pipeline runs. If the Clean Document Store is empty or missing, this pipeline has no input to process. | Pipeline has no input; no embedding or KG output is produced |

### 1.7 Design Principles

The following principles SHALL guide all design and implementation decisions:

| Principle | Description |
|-----------|-------------|
| **Swappability over lock-in** | Every external dependency (LLM provider, embedding model, vector store, structure detector) SHALL be behind a configuration interface. Changing providers SHALL require configuration changes, not code changes. |
| **Fail-safe over fail-fast** | When an LLM call fails, the pipeline SHALL fall back to deterministic alternatives rather than halting. A single flawed LLM response SHALL NOT halt a batch job. |
| **Context preservation over compression** | The pipeline SHALL preserve every numerical value, specification, and procedural step. Content restructuring SHALL NOT summarise or remove information. |
| **Configuration-driven behaviour** | Pipeline behaviour (skip/enable processing stages, dry run mode) SHALL be controlled via a single configuration system with runtime overrides. |
| **Idempotency by construction** | Every processing stage SHALL produce the same output given the same input. Identifiers SHALL be derived deterministically from content. The same `clean_hash` always produces the same chunks, embeddings, and KG triples. Re-running this pipeline against an unchanged Clean Document Store produces an equivalent result. |
| **Controlled access over restriction** | Knowledge at all maturity levels SHALL be ingested and searchable. A tiered review system SHALL control visibility at retrieval time without restricting what enters the system. |

### 1.8 Out of Scope

**Out of scope for this pipeline (handled by Document Processing Pipeline — see `DOCUMENT_PROCESSING_SPEC.md`):**

- Document format parsing (PDF, DOCX, PPTX, XLSX, HTML, RST, plain text)
- Text extraction from source files
- Text cleaning: normalisation, boilerplate removal, whitespace normalisation
- Multimodal figure processing via VLM (Vision-Language Model)
- Document refactoring for self-containedness

**Out of scope — downstream retrieval layer:**

- Query processing, reranking, and answer generation

**Out of scope — broader platform components (see Strategic Proposal):**

- Skills repository and anti-skills validation framework
- AI-assisted documentation agents (background monitoring, draft generation)
- Code standardisation and Python migration initiative
- Web dashboard UI (planned for Phase 3 deployment)
- Reranker model deployment and tuning
- Adoption strategy, change management, and gamification

---

## 2. Processing Pipeline Overview

### 2.1 High-Level Architecture

The Embedding Pipeline processes clean Markdown documents through a directed acyclic graph (DAG) of eight processing stages, implemented using a graph-based orchestration framework (LangGraph). Each document flows through the following stages in order:

```text
    (produced by DOCUMENT_PROCESSING_SPEC.md)
┌──────────────────────────────────────┐
│     CLEAN DOCUMENT STORE             │
│  {source_key}.md + .meta.json        │
│                                      │
└──────────────────────────────────────┘
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

---

## 3. Functional Requirements

### 3.0 Clean Document Store Input Contract (FR-591)

This section defines the input contract of the Embedding Pipeline — how it reads from and validates the Clean Document Store produced by the Document Processing Pipeline. All pipeline processing begins by reading a clean Markdown document and its companion metadata envelope.

> **FR-591** | Priority: MUST
>
> **Description:** The system MUST read the clean Markdown content from `{source_key}.md` in the configured Clean Document Store directory as the input to Node 6 (Chunking). The source file MUST NOT be read directly; the Clean Document Store is the sole input source.
>
> **Rationale:** Decoupling the Embedding Pipeline from the source documents ensures it operates on fully processed, consistent input. Reading from the Clean Document Store rather than the source file ensures that all cleaning, normalisation, and refactoring has been applied before chunking begins.
>
> **Acceptance Criteria:**
> 1. Given `source_key = "a3f9c2"`, the system reads `{clean_docs_dir}/a3f9c2.md` as its document input.
> 2. If `a3f9c2.md` does not exist, the system records a structured error (missing clean document) and skips this document without halting the pipeline.
> 3. The system does not open or read the original source file during this pipeline.

> **FR-592** | Priority: MUST
>
> **Description:** The system MUST read the companion metadata envelope `{source_key}.meta.json` and validate that all required fields are present before processing.
>
> **Rationale:** The metadata envelope carries the `clean_hash` for change detection, the `review_tier` for retrieval filtering, and the `extraction_confidence` for quality scoring. Missing or malformed metadata must be caught before processing begins, not discovered mid-pipeline.
>
> **Acceptance Criteria:**
> 1. Given a valid `{source_key}.meta.json`, the system successfully parses it and makes all fields available to downstream nodes.
> 2. Given a `{source_key}.meta.json` that is missing the `clean_hash` field, the system records a structured validation error and skips this document.
> 3. Given a `{source_key}.meta.json` that is malformed JSON, the system records a parse error and skips this document.

> **FR-593** | Priority: MUST
>
> **Description:** The system MUST compare the `clean_hash` from the metadata envelope against the stored hash from the previous successful embedding run for the same `source_key`. If they match, the document has not changed and the system MUST skip re-embedding (no-op). If they differ or no previous run exists, the system MUST proceed with full processing.
>
> **Rationale:** The `clean_hash` is the Embedding Pipeline's independent change-detection key. It is separate from the `source_hash` used by the Document Processing Pipeline. This independence means the Embedding Pipeline can be forced to re-run (e.g., when the embedding model changes) without re-running document processing, and vice versa.
>
> **Acceptance Criteria:**
> 1. Given a `clean_hash` of `"abc123"` matching the stored hash from the previous run, the system skips processing and logs "skipped: clean document unchanged".
> 2. Given a `clean_hash` of `"def456"` that differs from the stored hash, the system proceeds with chunking through storage.
> 3. Given no previous run record for the `source_key`, the system treats the document as new and proceeds with full processing.

> **FR-594** | Priority: MUST
>
> **Description:** The system MUST propagate metadata fields from the envelope into chunk metadata during processing: `source_key`, `source_path`, `review_tier`, and `extraction_confidence` MUST be attached to every chunk produced from the document.
>
> **Rationale:** Chunk metadata is what allows the retrieval pipeline to apply review tier filters, cite the original source, and expose quality signals without re-reading the clean document or re-contacting the source file. These fields must be available at retrieval time.
>
> **Acceptance Criteria:**
> 1. Given a document with `review_tier: "Fully Reviewed"`, all chunks produced contain `review_tier = "Fully Reviewed"` in their stored metadata.
> 2. Given a document with `extraction_confidence: 0.72`, all chunks produced contain `extraction_confidence = 0.72` in their stored metadata.
> 3. Given a document with `source_path: "/docs/spec.pdf"`, all chunks produced contain `source_path = "/docs/spec.pdf"` in their stored metadata.

> **FR-595** | Priority: SHOULD
>
> **Description:** The system SHOULD verify that the `clean_hash` in the metadata envelope matches the actual SHA-256 of the `.md` file before processing, and log a warning if they differ.
>
> **Rationale:** Hash mismatch between the metadata envelope and the actual file indicates the clean document was modified after processing — either by a bug in the Document Processing Pipeline or by manual intervention. This is an anomalous state that should be surfaced to operators.
>
> **Acceptance Criteria:**
> 1. Given a `.md` file whose SHA-256 does not match the `clean_hash` in its companion `.meta.json`, the system logs a warning with the `source_key`, stored hash, and actual hash, but continues processing using the actual file content.
> 2. Given a `.md` file whose SHA-256 matches `clean_hash`, no warning is logged.

---

### 3.1 Chunking (FR-600)

> **FR-601** | Priority: MUST
>
> **Description:** The system MUST split document text into semantically coherent chunks that respect topic boundaries, specification blocks, and procedure sequences.
>
> **Rationale:** Naive fixed-size splitting breaks mid-sentence or mid-specification, producing chunks that lose meaning in isolation. Semantic chunking preserves the coherence needed for accurate retrieval. Addresses the context-loss problem from isolated paragraphs.
>
> **Acceptance Criteria:**
> 1. Given a section containing a 3-step procedure (Step 1, Step 2, Step 3), the chunker keeps all 3 steps in the same chunk if they fit within the size limit.
> 2. Given two topically distinct subsections ("Clock Distribution" and "Power Grid"), they are placed in separate chunks.
> 3. Given a specification block with related parameters, the parameters are not split across chunks.

> **FR-602** | Priority: MUST
>
> **Description:** Chunk size MUST be configurable with target, minimum, and maximum token limits.
>
> **Rationale:** Optimal chunk size depends on the embedding model, retrieval strategy, and document characteristics. Configurable limits allow tuning without code changes. Supports the configuration-driven-behaviour principle.
>
> **Acceptance Criteria:**
> 1. Given configuration `chunk_size.target = 512, chunk_size.min = 100, chunk_size.max = 1024`, chunks are produced targeting ~512 tokens, with no chunk below 100 tokens (except the final chunk of a section) and no chunk exceeding 1024 tokens.
> 2. Changing these values in configuration changes the chunk sizes produced.

> **FR-603** | Priority: MUST
>
> **Description:** The target chunk size MUST account for downstream enrichment overhead (boundary context) to prevent exceeding the embedding model's input token limit.
>
> **Rationale:** Boundary context (FR-703) adds tokens to the embedding input. If the chunk itself already uses the full token budget, the enriched input will exceed the model's limit, causing truncation or errors.
>
> **Acceptance Criteria:**
> 1. Given an embedding model with 8192 token limit and boundary context configured to add up to 200 tokens, the effective maximum chunk size is at most 8192 - 200 = 7992 tokens.
> 2. No enriched chunk (chunk + boundary context) exceeds the embedding model's input token limit.

> **FR-604** | Priority: MUST
>
> **Description:** Tables MUST be treated as indivisible chunking units by default (configurable). Tables exceeding maximum chunk size MUST be split row-wise with the header row prepended to every fragment.
>
> **Rationale:** Splitting a table mid-row produces meaningless fragments. Keeping tables atomic preserves data integrity. When a table is too large, prepending headers to each fragment ensures every fragment is interpretable on its own. Supports the context-preservation principle.
>
> **Acceptance Criteria:**
> 1. Given a 10-row pin table within the maximum chunk size, it appears as a single chunk.
> 2. Given a 200-row register map exceeding the maximum chunk size, it is split into multiple chunks where each chunk starts with the original header row (`| Register | Address | Width | Description |`) followed by a subset of data rows.
> 3. Given `tables.keep_atomic = false` in configuration, tables may be split at any boundary.

> **FR-605** | Priority: MUST
>
> **Description:** Each chunk MUST receive a deterministic identifier derived from the document ID, chunk position, and content hash. Re-ingesting the same document with identical content MUST produce identical chunk IDs.
>
> **Rationale:** Deterministic chunk IDs enable the re-ingestion mechanism to identify and replace specific chunks. Without determinism, every re-ingestion would appear as entirely new content. Supports the idempotency-by-construction principle.
>
> **Acceptance Criteria:**
> 1. Given the same document ingested twice with no content changes, all chunk IDs are identical across both runs.
> 2. Given a document where only section 5 changes, chunks derived from unchanged sections produce the same IDs.
> 3. The chunk ID is a string that encodes document ID, position index, and a content-derived hash component.

> **FR-606** | Priority: MUST
>
> **Description:** Each chunk MUST carry adjacency links (previous/next chunk IDs) to enable context expansion at retrieval time.
>
> **Rationale:** Retrieval sometimes returns a chunk that is only partially relevant; adjacency links let the retrieval layer fetch surrounding chunks for additional context without re-processing the document. Supports the context-preservation principle.
>
> **Acceptance Criteria:**
> 1. Given a document split into chunks C1, C2, C3, chunk C2 has `previous_chunk_id = C1.id` and `next_chunk_id = C3.id`.
> 2. Chunk C1 has `previous_chunk_id = null` and chunk C3 has `next_chunk_id = null`.
> 3. After quality validation removes a chunk, adjacency links are repaired (see FR-1105).

> **FR-607** | Priority: MUST
>
> **Description:** Each chunk MUST be tagged with its production method (e.g., LLM-driven, deterministic fallback, table-specific).
>
> **Rationale:** Knowing how a chunk was produced enables quality analysis and debugging. If retrieval quality degrades, operators can correlate with production method to identify whether fallback chunking is the cause.
>
> **Acceptance Criteria:**
> 1. Given a chunk produced by the LLM chunker, it has `production_method = "llm"`.
> 2. Given a chunk produced by the deterministic fallback, it has `production_method = "deterministic_fallback"`.
> 3. Given a table chunk, it has `production_method = "table"`.
> 4. The tag is stored as chunk metadata.

> **FR-608** | Priority: MUST
>
> **Description:** If the primary (LLM-driven) chunking fails, the system MUST fall back to a deterministic recursive splitter on paragraph/sentence boundaries.
>
> **Rationale:** LLM calls can fail due to rate limits, timeouts, or provider outages. A deterministic fallback ensures the pipeline always produces chunks rather than halting. Supports the fail-safe-over-fail-fast principle.
>
> **Acceptance Criteria:**
> 1. Given an LLM API failure during chunking, the system switches to the deterministic splitter and produces valid chunks.
> 2. The fallback chunks respect paragraph and sentence boundaries (no mid-sentence splits except when a single sentence exceeds the maximum chunk size).
> 3. The pipeline logs a warning indicating the fallback was used.

> **FR-609** | Priority: MUST
>
> **Description:** Each chunk MUST carry a content type tag (text, table, figure, code, equation, list, heading).
>
> **Rationale:** Content type enables type-specific retrieval filtering (e.g., "show me only tables") and type-aware ranking at retrieval time. Different content types may also require different embedding strategies.
>
> **Acceptance Criteria:**
> 1. Given a chunk containing a markdown table, it has `content_type = "table"`.
> 2. Given a chunk containing a code block, it has `content_type = "code"`.
> 3. Given a chunk containing narrative text, it has `content_type = "text"`.
> 4. Given a chunk containing a figure description, it has `content_type = "figure"`.

> **FR-610** | Priority: MUST
>
> **Description:** Sections exceeding a configurable size limit MUST be pre-split at paragraph boundaries before chunking to keep processing windows within manageable limits.
>
> **Rationale:** Very large sections sent to an LLM chunker in a single call may exceed context window limits or produce poor chunking decisions. Pre-splitting reduces the problem size while preserving paragraph integrity.
>
> **Acceptance Criteria:**
> 1. Given a section of 50,000 tokens and a pre-split limit of 10,000 tokens, the section is split into approximately 5 segments at paragraph boundaries before being sent to the chunker.
> 2. Given a section of 5,000 tokens with the same limit, no pre-splitting occurs.
> 3. Pre-splits never break mid-paragraph.

> **FR-611** | Priority: MUST
>
> **Description:** Token counting MUST use the actual tokeniser from the configured embedding model to correctly handle domain-specific terminology. A conservative approximation MUST be available as a fallback.
>
> **Rationale:** Different tokenisers produce different token counts for the same text, especially for domain-specific terms (e.g., "SystemVerilog" may be 1 or 3 tokens depending on the tokeniser). Using the wrong tokeniser could cause chunks to exceed the model's input limit. Supports the swappability-over-lock-in principle.
>
> **Acceptance Criteria:**
> 1. Given an embedding model with a specific tokeniser, the system uses that tokeniser for all token counts.
> 2. Given a term like "clock_domain_crossing_check", the count matches the model's actual tokenisation.
> 3. If the model tokeniser is unavailable, the fallback uses a conservative ratio (e.g., 1 token per 3.5 characters) that overestimates rather than underestimates token count.

---

### 3.2 Chunk Enrichment (FR-700)

> **FR-701** | Priority: MUST
>
> **Description:** The system MUST construct metadata context headers for each chunk containing: domain, document type, title, section path, content type, review tier, and linked content references.
>
> **Rationale:** Context headers provide the structured metadata needed for filtering, display, and retrieval-time decisions. Without them, chunks are anonymous text fragments with no organisational context. Supports the context-preservation principle.
>
> **Acceptance Criteria:**
> 1. Given a chunk from section "3.2 Core Power" in document "ASIC_Power_Spec_v2.pdf" classified as domain "ASIC Design" and review tier "Approved", the context header includes all of: `domain: "ASIC Design"`, `document_type: "Specification"`, `title: "ASIC_Power_Spec_v2"`, `section_path: "Power Specifications > Core Power"`, `content_type: "text"`, `review_tier: "Approved"`.
> 2. No fields are omitted.

> **FR-702** | Priority: MUST
>
> **Description:** Context headers MUST be stored as metadata properties for filtering and display. Context headers MUST NOT be embedded into the vector by default (configurable).
>
> **Rationale:** Embedding metadata into the vector dilutes the semantic signal of the actual content. Storing metadata as filterable properties enables precise pre-filtering (e.g., "only Approved documents in ASIC Design domain") without compromising embedding quality. Supports the configuration-driven-behaviour principle.
>
> **Acceptance Criteria:**
> 1. By default, the vector embedding input contains only the chunk content and boundary context — not the context header fields.
> 2. The metadata fields are stored as separate filterable properties in the vector store.
> 3. Given configuration `enrichment.embed_headers = true`, the context header is prepended to the embedding input.
> 4. A retrieval query filtering on `domain = "ASIC Design"` uses the metadata property, not vector similarity.

> **FR-703** | Priority: MUST
>
> **Description:** The system MUST inject boundary context (last N sentences from the preceding chunk) into each chunk's embedding input to capture topic transitions. The number of sentences MUST be configurable.
>
> **Rationale:** Chunk boundaries are artificial — a topic may span two chunks. Injecting trailing sentences from the previous chunk into the embedding input captures continuity that would otherwise be lost, improving retrieval recall for queries that span chunk boundaries.
>
> **Acceptance Criteria:**
> 1. Given `enrichment.boundary_sentences = 3` and a preceding chunk ending with sentences S1, S2, S3, the current chunk's embedding input is prepended with S1, S2, S3.
> 2. Given the first chunk in a document (no predecessor), no boundary context is added.
> 3. Given `boundary_sentences = 0`, no boundary context is injected for any chunk.

> **FR-704** | Priority: MUST
>
> **Description:** Boundary context MUST improve embedding recall without consuming excessive embedding capacity. If the enriched content exceeds the embedding model's input limit, boundary context MUST be trimmed rather than chunk content.
>
> **Rationale:** The chunk's own content is the primary semantic signal and must never be truncated. Boundary context is supplementary; trimming it preserves the core content integrity. Supports the context-preservation principle.
>
> **Acceptance Criteria:**
> 1. Given a chunk of 7,800 tokens, boundary context of 500 tokens, and an embedding model limit of 8,192 tokens, the boundary context is trimmed to 392 tokens (or fewer) so the total does not exceed 8,192.
> 2. The chunk's own content (7,800 tokens) is never truncated.
> 3. Given a chunk of 4,000 tokens with 500 tokens of boundary context and the same model limit, no trimming occurs.

> **FR-705** | Priority: MUST
>
> **Description:** The raw chunk content MUST be preserved separately from the enriched embedding input for display in retrieval results.
>
> **Rationale:** Users viewing retrieval results should see the original chunk text, not text polluted with boundary context from adjacent chunks. Separating raw and enriched versions serves both embedding quality and user experience.
>
> **Acceptance Criteria:**
> 1. Given a chunk with raw content "The VDD_CORE supply is 1.0V nominal" and enriched content that includes boundary context prepended, both versions are stored.
> 2. The retrieval API returns the raw content for display.
> 3. The enriched content is used only for generating the embedding vector.
> 4. Modifying the boundary context configuration and re-ingesting does not alter the stored raw content.

---

### 3.3 Metadata Generation (FR-800)

> **FR-801** | Priority: MUST
>
> **Description:** The system MUST generate document-level metadata: summary (2-3 sentences), technical keywords (10-20), named entities, topic categories, domain classification, and document type classification.
>
> **Rationale:** Document-level metadata enables faceted filtering and retrieval-time ranking. Without structured metadata, queries cannot distinguish between documents by domain, type, or topic, worsening knowledge fragmentation across engineering teams.
>
> **Acceptance Criteria:**
> 1. Given a design specification document for a 5nm ASIC clock distribution network, the system produces:
>    - a 2-3 sentence summary mentioning clock distribution
>    - between 10 and 20 keywords including domain terms (e.g., "clock tree synthesis", "skew budgeting")
>    - named entities (e.g., "TSMC N5")
>    - a domain classification (e.g., "Physical Design")
>    - a document type (e.g., "Specification")
> 2. A document with fewer than 10 extractable keywords still produces at least 10 keywords or explicitly flags the shortfall.

> **FR-802** | Priority: MUST
>
> **Description:** The system MUST generate chunk-level metadata: keywords (5-10) and named entities for each chunk.
>
> **Rationale:** Chunk-level metadata supports fine-grained retrieval filtering, ensuring search results can be narrowed to chunks that specifically discuss the queried concept rather than returning entire documents. This directly addresses the term ambiguity problem where "clock domain" has different meanings in different contexts.
>
> **Acceptance Criteria:**
> 1. Given a chunk discussing DFT scan chain insertion for a 7nm design, the system produces 5-10 keywords (e.g., "scan chain", "DFT", "ATPG", "fault coverage", "test compression") and named entities (e.g., "Synopsys DFT Compiler").
> 2. A chunk with only 3 extractable keywords produces exactly those 3 without padding with unrelated terms.

> **FR-803** | Priority: MUST
>
> **Description:** All LLM-generated keywords and entities MUST pass a validation gate ensuring they are grounded in the chunk content (direct presence, abbreviation bridge, or compound term overlap). Keywords inferred by association but not discussed in the chunk MUST be discarded.
>
> **Rationale:** Supports the context-preservation design principle. LLMs may hallucinate plausible-sounding keywords (e.g., generating "power integrity" for a chunk that only discusses signal integrity), which would cause false-positive retrievals and erode trust in search results.
>
> **Acceptance Criteria:**
> 1. Given a chunk that discusses "CTS" (clock tree synthesis) but never mentions "OCV" (on-chip variation), an LLM-generated keyword "OCV" is discarded because it has no direct presence, abbreviation bridge, or compound term overlap in the chunk.
> 2. A keyword "clock tree synthesis" is retained via abbreviation bridge to "CTS" present in the chunk text.

> **FR-804** | Priority: MUST
>
> **Description:** Document-level keywords MUST be stored as filterable properties but MUST NOT be keyword-indexed at the chunk level to prevent false positives.
>
> **Rationale:** Indexing document-level keywords at the chunk level would cause every chunk in a document to match queries for terms discussed only in other sections. This directly causes the term ambiguity problem described in the problem statement, where a search for "power grid" returns chunks about unrelated topics simply because the parent document mentions power grids elsewhere.
>
> **Acceptance Criteria:**
> 1. Given a 50-page SoC integration guide where only Section 4 discusses "thermal management", a BM25 keyword search for "thermal management" returns only chunks from Section 4, not chunks from other sections.
> 2. Document-level metadata for the guide includes "thermal management" as a filterable property for document-level queries.

> **FR-805** | Priority: MUST
>
> **Description:** If the LLM call fails, the system MUST fall back to a deterministic frequency-based keyword extraction (TF-IDF).
>
> **Rationale:** Supports the fail-safe-over-fail-fast design principle. Metadata generation must not block the pipeline; TF-IDF provides acceptable keyword extraction quality to ensure every chunk has searchable metadata even when the LLM is unavailable.
>
> **Acceptance Criteria:**
> 1. Given an LLM timeout during metadata generation for a chunk containing "The scan chain length was optimised from 1500 to 800 flip-flops to reduce test time", the TF-IDF fallback produces keywords including "scan chain", "flip-flops", and "test time".
> 2. The pipeline continues without halting.
> 3. The chunk's metadata includes a flag indicating fallback extraction was used.

> **FR-806** | Priority: MUST
>
> **Description:** The system MUST support domain vocabulary injection into metadata generation prompts to ensure canonical domain terminology is used.
>
> **Rationale:** Supports configuration-driven-behaviour. Without vocabulary injection, the LLM may generate inconsistent terminology (e.g., "DFT" vs "Design for Test" vs "Design for Testability"), fragmenting search results for the same concept across different keyword forms.
>
> **Acceptance Criteria:**
> 1. Given a domain vocabulary entry mapping "DFT" to "Design for Testability", metadata generation for a chunk mentioning "DFT" produces the canonical keyword "Design for Testability" (or both "DFT" and "Design for Testability") rather than a non-canonical variant like "Design for Test".
> 2. Removing the vocabulary entry results in the LLM choosing its own expansion.

---

### 3.4 Cross-Reference Extraction (FR-900)

> **FR-901** | Priority: MUST
>
> **Description:** The system MUST detect cross-references between documents, sections, and external standards.
>
> **Rationale:** Engineering documents form a web of dependencies; a specification may reference a design guide, which references an IEEE standard. Without cross-reference extraction, these relationships are invisible to retrieval, and the system cannot surface related documents or perform impact analysis when a referenced standard is updated.
>
> **Acceptance Criteria:**
> 1. Given a document containing "Refer to Section 3.2 of the Clock Domain Crossing Guidelines (CDC_GUIDE_v2.1)" and "per IEEE 1149.1", the system extracts at least two cross-references:
>    - one internal reference to CDC_GUIDE_v2.1 Section 3.2
>    - one external standard reference to IEEE 1149.1
> 2. Each reference includes type, target identifier, and source location.

> **FR-902** | Priority: MUST
>
> **Description:** Cross-reference extraction MUST be skippable via configuration.
>
> **Rationale:** Supports configuration-driven-behaviour. Some ingestion runs (e.g., quick re-indexing of a single updated document) may not need cross-reference extraction, and skipping it reduces processing time and LLM costs.
>
> **Acceptance Criteria:**
> 1. Given a pipeline configuration with `cross_reference_extraction.enabled: false`, the cross-reference extraction stage is skipped entirely (no LLM calls, no regex matching).
> 2. The pipeline log records the stage as "skipped".
> 3. Setting `cross_reference_extraction.enabled: true` enables the stage and produces cross-reference output.

> **FR-903** | Priority: MUST
>
> **Description:** The system MUST support both deterministic pattern matching (regex) and LLM-based extraction for implicit references.
>
> **Rationale:** Regex reliably captures explicit, well-formatted references (e.g., "IEEE 1149.1", "Section 3.2"), while LLM-based extraction catches implicit references (e.g., "the timing constraints discussed in the companion document") that no regex can match. Supporting both maximises recall while ensuring a deterministic baseline per the fail-safe-over-fail-fast principle.
>
> **Acceptance Criteria:**
> 1. Given text containing both "per JEDEC JESD79-4" (explicit) and "as described in the power delivery analysis performed last quarter" (implicit), the regex path extracts the JEDEC reference, and the LLM path identifies the implicit reference to a power delivery analysis document.
> 2. When the LLM is unavailable, only the regex-extracted references are returned and the implicit reference is not extracted.

> **FR-904** | Priority: MUST
>
> **Description:** Detected reference types MUST include: explicit (section/document citations), standard (IEEE, JEDEC, ISO), version, dependency, and implicit references.
>
> **Rationale:** Different reference types serve different retrieval and impact analysis needs. Version references enable traceability across document revisions; dependency references enable impact analysis when upstream documents change; standard references connect internal documents to external normative sources.
>
> **Acceptance Criteria:**
> 1. Given a document containing "See Section 5 of SPEC-CLK-001 v2.3", "compliant with IEEE 1801-2015 (UPF)", "This design depends on the PDN model from PWR-ANALYSIS-003", and "using the approach outlined earlier", the system produces references of types:
>    - explicit (Section 5 of SPEC-CLK-001)
>    - standard (IEEE 1801-2015)
>    - version (v2.3)
>    - dependency (PWR-ANALYSIS-003)
>    - implicit ("the approach outlined earlier")
> 2. Each reference carries a `type` field matching one of the five enumerated types.

> **FR-905** | Priority: MUST
>
> **Description:** Duplicate references MUST be merged, with LLM-extracted versions taking priority.
>
> **Rationale:** The same reference may be detected by both regex and LLM extraction. Merging avoids inflating the reference count and cluttering the knowledge graph, while prioritising the LLM version ensures richer metadata (e.g., the LLM may resolve an implicit reference target that regex cannot).
>
> **Acceptance Criteria:**
> 1. Given that regex extracts a reference to "IEEE 1149.1" with type "standard" and the LLM also extracts a reference to "IEEE 1149.1 (JTAG boundary scan standard)" with type "standard" and additional context, the system produces a single merged reference to "IEEE 1149.1" retaining the LLM's enriched description.
> 2. The final reference list contains no duplicate target identifiers.

---

### 3.5 Knowledge Graph Extraction (FR-1000)

> **FR-1001** | Priority: MUST
>
> **Description:** The system MUST extract structured subject-predicate-object triples from document content to build a knowledge graph enabling relationship-aware retrieval and impact analysis.
>
> **Rationale:** Vector similarity search alone cannot answer relational queries such as "which specifications constrain this design block?" or "what changes if we update the PDN model?". A knowledge graph captures these structural relationships, directly addressing the knowledge fragmentation problem by making inter-document dependencies explicit and queryable.
>
> **Acceptance Criteria:**
> 1. Given a chunk stating "The clock distribution network uses a H-tree topology and must meet the skew budget defined in SPEC-CLK-001", the system extracts at least two triples:
>    - ("clock distribution network", "uses", "H-tree topology")
>    - ("clock distribution network", "constrained_by", "SPEC-CLK-001")
> 2. Triples are stored as structured objects with subject, predicate, and object fields.

> **FR-1002** | Priority: MUST
>
> **Description:** Knowledge graph extraction MUST be skippable via configuration.
>
> **Rationale:** Supports configuration-driven-behaviour. Knowledge graph extraction involves significant LLM cost and processing time; teams that do not need relationship-aware retrieval can disable it to reduce cost and latency without affecting core vector search functionality.
>
> **Acceptance Criteria:**
> 1. Given a pipeline configuration with `knowledge_graph.enabled: false`, the KG extraction stage is skipped (no LLM calls, no structural triple generation).
> 2. The pipeline log records the stage as "skipped".
> 3. Downstream stages (Quality Validation, Embedding & Storage) proceed normally without KG data.

> **FR-1003** | Priority: MUST
>
> **Description:** The system MUST generate structural triples deterministically (document-chunk containment, adjacency, domain membership, authorship, abbreviation mappings, cross-references).
>
> **Rationale:** Supports idempotency-by-construction. Structural triples derived from document hierarchy are always available regardless of LLM availability, providing a guaranteed baseline knowledge graph. Deterministic generation ensures re-ingesting the same document always produces the same structural triples.
>
> **Acceptance Criteria:**
> 1. Given a document "SPEC-CLK-001" by author "J. Smith" in domain "Physical Design" with chunks C1 and C2 (adjacent), the system produces triples including:
>    - ("SPEC-CLK-001", "contains", "C1")
>    - ("SPEC-CLK-001", "contains", "C2")
>    - ("C1", "adjacent_to", "C2")
>    - ("SPEC-CLK-001", "belongs_to_domain", "Physical Design")
>    - ("SPEC-CLK-001", "authored_by", "J. Smith")
> 2. Re-ingesting the same document produces identical triples.

> **FR-1004** | Priority: MUST
>
> **Description:** The system MUST consolidate entities across chunks via exact-match deduplication, abbreviation resolution, and fuzzy matching.
>
> **Rationale:** The same entity often appears in different forms across chunks (e.g., "Clock Data Recovery" in one chunk, "CDR" in another, "clock data recovery circuit" in a third). Without consolidation, the knowledge graph fragments into disconnected nodes representing the same real-world entity, defeating the purpose of relationship-aware retrieval.
>
> **Acceptance Criteria:**
> 1. Given three chunks where Chunk A mentions "Clock Data Recovery", Chunk B mentions "CDR", and Chunk C mentions "clock data recovery", all three are consolidated into a single entity node "Clock Data Recovery" with alias "CDR".
> 2. The knowledge graph contains one node, not three.
> 3. Fuzzy matching merges "clock data recovery circuit" with "Clock Data Recovery" but does not merge "CDR" (Clock Data Recovery) with "CDR" (Critical Design Review) when domain context disambiguates them.

> **FR-1005** | Priority: MUST
>
> **Description:** The system MUST optionally use LLM-based relationship extraction with a controlled predicate vocabulary.
>
> **Rationale:** A controlled predicate vocabulary (e.g., "uses", "constrained_by", "implements", "depends_on") ensures the knowledge graph is queryable with consistent predicates rather than free-form natural language, while LLM extraction captures semantic relationships that structural analysis cannot detect.
>
> **Acceptance Criteria:**
> 1. Given a controlled vocabulary of 15 predicates and a chunk stating "The OCV derating factors are applied during static timing analysis", the LLM extracts a triple ("OCV derating factors", "applied_during", "static timing analysis") where "applied_during" is from the controlled vocabulary.
> 2. If the LLM proposes a predicate not in the vocabulary (e.g., "are used in"), the system maps it to the nearest controlled predicate or discards the triple.

> **FR-1006** | Priority: MUST
>
> **Description:** All LLM-extracted triples MUST be validated: subjects and objects must appear in the chunk content or entity list. Invalid triples MUST be discarded.
>
> **Rationale:** Supports context-preservation. LLMs may hallucinate plausible relationships involving entities not actually discussed in the source chunk. Storing ungrounded triples would introduce false relationships into the knowledge graph, leading to incorrect impact analysis and misleading retrieval results.
>
> **Acceptance Criteria:**
> 1. Given a chunk that discusses "scan chain insertion" and "DFT Compiler" but not "formal verification", an LLM-extracted triple ("DFT Compiler", "supports", "formal verification") is discarded because "formal verification" does not appear in the chunk content or consolidated entity list.
> 2. A triple ("DFT Compiler", "performs", "scan chain insertion") is retained because both subject and object are grounded.

> **FR-1007** | Priority: MUST
>
> **Description:** If LLM extraction fails, the system MUST build the knowledge graph from structural triples and entity consolidation only.
>
> **Rationale:** Supports fail-safe-over-fail-fast. A knowledge graph built from structural triples alone (containment, adjacency, domain membership) still provides value for document navigation and basic impact analysis, ensuring the pipeline produces useful output even when the LLM is unavailable.
>
> **Acceptance Criteria:**
> 1. Given an LLM failure during KG extraction for a 30-page document with 45 chunks, the system produces structural triples (containment, adjacency, domain, authorship, abbreviation mappings) and consolidated entities without any LLM-derived relationship triples.
> 2. The pipeline log records the LLM failure and indicates fallback to structural-only mode.
> 3. The resulting knowledge graph is still navigable from document to chunks.

> **FR-1008** | Priority: MUST
>
> **Description:** Triple identifiers MUST be deterministic, derived from document ID, subject, predicate, and object.
>
> **Rationale:** Supports idempotency-by-construction. Deterministic triple IDs ensure that re-ingesting the same document produces triples with the same identifiers, enabling clean upsert operations during re-ingestion and preventing duplicate triples from accumulating in the graph store.
>
> **Acceptance Criteria:**
> 1. Given a triple ("SPEC-CLK-001", "contains", "chunk_abc123") extracted from document "SPEC-CLK-001", the triple ID is a deterministic hash of (document_id, subject, predicate, object).
> 2. Re-ingesting the same document produces a triple with the identical ID.
> 3. Changing the object to "chunk_def456" produces a different triple ID.

> **FR-1009** | Priority: MUST
>
> **Description:** The maximum number of triples per chunk MUST be configurable.
>
> **Rationale:** Supports configuration-driven-behaviour. Dense technical chunks can produce hundreds of triples, inflating storage costs and slowing graph queries. A configurable cap lets teams balance knowledge graph richness against storage and performance constraints.
>
> **Acceptance Criteria:**
> 1. Given a configuration `knowledge_graph.max_triples_per_chunk: 20` and a chunk from which the LLM extracts 35 triples, only the top 20 triples (ranked by validation confidence or extraction order) are retained.
> 2. Changing the configuration to `max_triples_per_chunk: 50` retains all 35 triples.
> 3. Setting it to `0` disables the cap.

---

### 3.6 Quality Validation (FR-1100)

> **FR-1101** | Priority: MUST
>
> **Description:** The system MUST remove chunks below a configurable minimum token count.
>
> **Rationale:** Very short chunks (e.g., a section header with no body text) produce low-quality embeddings that pollute search results with near-meaningless matches. Removing them improves retrieval precision without losing substantive content.
>
> **Acceptance Criteria:**
> 1. Given a configuration `quality.min_token_count: 50` and a chunk containing only "3.2 Clock Tree Results" (5 tokens), the chunk is removed from the pipeline.
> 2. A chunk with 51 tokens is retained.
> 3. Changing the threshold to `min_token_count: 3` retains the 5-token chunk.

> **FR-1102** | Priority: MUST
>
> **Description:** The system MUST detect and remove near-duplicate chunks based on content similarity exceeding a configurable threshold.
>
> **Rationale:** Document boilerplate (e.g., repeated disclaimers, identical headers across sections) produces near-duplicate chunks that waste storage and dilute retrieval results by returning effectively the same content multiple times.
>
> **Acceptance Criteria:**
> 1. Given a threshold of `quality.dedup_similarity_threshold: 0.95` and two chunks with 97% content similarity (e.g., identical disclaimer paragraphs from two sections), one chunk is removed as a near-duplicate.
> 2. Two chunks with 90% similarity (e.g., similar but distinct design rule descriptions for different metal layers) are both retained.
> 3. The removed chunk is logged with the ID of the chunk it duplicates.

> **FR-1103** | Priority: MUST
>
> **Description:** The system MUST assign a quality score (0.0-1.0) to each surviving chunk based on content signals (technical term density, numerical density, structured content, chunk length, whitespace ratio, boilerplate presence, extraction confidence).
>
> **Rationale:** Not all chunks carry equal informational value. Quality scores enable retrieval-time weighting so that dense, information-rich chunks (e.g., a timing constraints table) rank higher than sparse, boilerplate-heavy chunks, improving answer quality without discarding low-scoring content entirely.
>
> **Acceptance Criteria:**
> 1. Given a chunk containing a timing constraints table with 12 numerical values and 8 technical terms, the quality score is above 0.7.
> 2. Given a chunk containing a generic project introduction with no numerical values and 1 technical term, the quality score is below 0.4.
> 3. Scores are floating-point values in the range [0.0, 1.0] with at least two decimal places of precision.

> **FR-1104** | Priority: MUST
>
> **Description:** Quality scores MUST be stored with the chunk and available for retrieval-time quality weighting.
>
> **Rationale:** Supports controlled-access-over-restriction. Rather than discarding low-quality chunks outright, storing quality scores allows the retrieval layer to apply configurable weighting, ensuring that even low-quality chunks remain searchable when a user broadens their search.
>
> **Acceptance Criteria:**
> 1. Given a stored chunk in the vector database, the chunk object includes a `quality_score` field of type float.
> 2. A retrieval query can filter or boost results using the quality score (e.g., `quality_score >= 0.5`).
> 3. The quality score is present on 100% of stored chunks.

> **FR-1105** | Priority: MUST
>
> **Description:** After removing low-quality and duplicate chunks, the system MUST repair adjacency links to skip over removed chunks.
>
> **Rationale:** Supports context-preservation. Adjacency links enable the retrieval layer to fetch surrounding chunks for context. If a removed chunk breaks the adjacency chain, the retrieval layer loses the ability to reconstruct reading order, reintroducing the context loss problem described in the problem statement.
>
> **Acceptance Criteria:**
> 1. Given chunks [C1, C2, C3, C4] where C2 is removed as a near-duplicate and C3 is removed for being below minimum token count, the adjacency links are repaired so that C1.next = C4 and C4.previous = C1.
> 2. Before repair, C1.next = C2.
> 3. After repair, no adjacency link points to a removed chunk.

---

### 3.7 Embedding & Storage (FR-1200)

> **FR-1201** | Priority: MUST
>
> **Description:** The system MUST generate vector embeddings for all surviving chunks using the configured embedding model.
>
> **Rationale:** Vector embeddings are the core output of the pipeline, enabling semantic similarity search. Without embeddings, chunks cannot be retrieved by meaning, and the system fails its primary purpose of transforming documents into semantically searchable representations.
>
> **Acceptance Criteria:**
> 1. Given 45 surviving chunks after quality validation, the system produces exactly 45 embedding vectors, one per chunk.
> 2. Each vector has the dimensionality specified by the configured embedding model (e.g., 1024 for a model configured with `embedding.dimension: 1024`).
> 3. No chunk is stored without an embedding.

> **FR-1202** | Priority: MUST
>
> **Description:** The embedding model, dimension, and provider MUST be configurable.
>
> **Rationale:** Supports swappability-over-lock-in. Embedding models evolve rapidly; teams must be able to switch from one provider (e.g., OpenAI) to another (e.g., Cohere, a local model) without code changes, enabling cost optimisation and adaptation to domain-specific models as they become available.
>
> **Acceptance Criteria:**
> 1. Given a configuration change from `embedding.model: "text-embedding-3-large"` and `embedding.provider: "openai"` to `embedding.model: "embed-english-v3.0"` and `embedding.provider: "cohere"`, the system uses the Cohere model without any code changes.
> 2. The embedding dimension updates accordingly.
> 3. An invalid provider name produces a clear configuration error at startup, not at embedding time.

> **FR-1203** | Priority: MUST
>
> **Description:** The system MUST validate that the actual embedding dimension matches the configured dimension on the first batch. Mismatched dimensions MUST halt the stage.
>
> **Rationale:** A dimension mismatch between the embedding model and the vector store schema causes silent data corruption: vectors are stored but produce meaningless similarity scores. Halting immediately prevents an entire batch of documents from being stored with unusable embeddings.
>
> **Acceptance Criteria:**
> 1. Given a configuration `embedding.dimension: 1024` but an embedding model that produces 768-dimensional vectors, the system detects the mismatch on the first batch of embeddings, logs an error including both expected (1024) and actual (768) dimensions, and halts the embedding stage.
> 2. No chunks are written to the vector store.
> 3. When dimensions match (both 1024), the stage proceeds normally.

> **FR-1204** | Priority: MUST
>
> **Description:** The system MUST store chunks with their embeddings, metadata (32+ properties), and pre-computed vectors in the vector database.
>
> **Rationale:** Rich metadata stored alongside embeddings enables hybrid retrieval (vector + metadata filtering) without requiring separate lookups, which is essential for scoping queries to specific domains, document types, review tiers, or technology nodes in a semiconductor engineering context.
>
> **Acceptance Criteria:**
> 1. Given a chunk from a 5nm standard cell library specification, the stored vector database object includes: the embedding vector, the chunk text, and at least 32 metadata properties including document_id, chunk_id, section_hierarchy, domain, document_type, review_tier, quality_score, keywords, named_entities, source_file, and content_hash.
> 2. For refactored retrieval text, metadata also includes provenance fields (source URI plus source/refactored span mapping and confidence).
> 3. All filterable properties remain queryable.

> **FR-1205** | Priority: MUST
>
> **Description:** The system MUST use Bring Your Own Model (BYOM) mode, computing embeddings externally and passing pre-computed vectors to the vector store.
>
> **Rationale:** Supports swappability-over-lock-in. BYOM decouples the embedding model from the vector store, allowing the team to use any embedding model (including fine-tuned or locally hosted models) regardless of the vector store provider's native model support.
>
> **Acceptance Criteria:**
> 1. Given a locally hosted embedding model that produces 1024-dimensional vectors, the system computes embeddings using the local model and stores the pre-computed vectors in the vector database (e.g., Weaviate) without invoking any vectoriser module built into the vector store.
> 2. The vector store is configured in BYOM/none-vectoriser mode.

> **FR-1206** | Priority: MUST
>
> **Description:** The system MUST support asymmetric embedding prefixes (different prefixes for documents vs queries) as required by certain embedding models.
>
> **Rationale:** Some embedding models (e.g., E5, BGE) require different input prefixes for documents ("passage:") and queries ("query:") to produce embeddings in a shared space. Without prefix support, these models produce misaligned embeddings that degrade retrieval quality.
>
> **Acceptance Criteria:**
> 1. Given a configuration `embedding.document_prefix: "passage: "` and `embedding.query_prefix: "query: "`, document chunks are embedded with the "passage: " prefix prepended to the text.
> 2. The query prefix is stored in configuration for use by the downstream retrieval layer.
> 3. When prefix configuration is empty, no prefix is prepended.

> **FR-1207** | Priority: MUST
>
> **Description:** The system MUST support hybrid search (vector similarity + BM25 keyword search) in the vector store.
>
> **Rationale:** Pure vector search struggles with exact term matching (e.g., searching for a specific specification ID like "SPEC-CLK-001"), while pure keyword search misses semantic matches. Hybrid search combines both strengths, which is critical in engineering documentation where both precise identifiers and conceptual queries are common.
>
> **Acceptance Criteria:**
> 1. Given a vector store configured with hybrid search, a query for "SPEC-CLK-001 timing constraints" returns results ranked by a fusion of vector similarity (semantic match on "timing constraints") and BM25 keyword match (exact match on "SPEC-CLK-001").
> 2. A chunk containing the exact string "SPEC-CLK-001" ranks higher than a semantically similar chunk that does not contain the identifier.

> **FR-1208** | Priority: MUST
>
> **Description:** The system MUST support a dry-run mode that executes the full pipeline without writing to external stores.
>
> **Rationale:** Supports configuration-driven-behaviour. Dry-run mode enables pipeline validation, cost estimation, and debugging without side effects, which is essential when tuning chunking strategies or testing new embedding models before committing to production data changes.
>
> **Acceptance Criteria:**
> 1. Given a configuration `pipeline.dry_run: true`, the pipeline processes a document through all stages (ingestion, chunking, embedding) but writes zero records to the vector store and zero triples to the graph store.
> 2. The pipeline log reports the number of chunks, embeddings, and triples that would have been written.
> 3. Setting `pipeline.dry_run: false` enables writes.

> **FR-1209** | Priority: MUST
>
> **Description:** The embedding provider and vector store MUST be swappable via configuration.
>
> **Rationale:** Supports swappability-over-lock-in. The organisation must be able to migrate from one vector store (e.g., Weaviate) to another (e.g., Qdrant, Pinecone) or switch embedding providers without modifying pipeline code, protecting against vendor lock-in and enabling competitive evaluation.
>
> **Acceptance Criteria:**
> 1. Given a configuration change from `vector_store.provider: "weaviate"` to `vector_store.provider: "qdrant"`, the system stores chunks in Qdrant without code changes.
> 2. Both providers support the same set of metadata filters and hybrid search.
> 3. An unsupported provider name produces a clear error at startup.

#### 3.7.1 Batch Embedding Optimisation (FR-1210)

> **FR-1210** | Priority: MUST
>
> **Description:** The system MUST group chunks into batches before sending them to the embedding model, rather than embedding chunks individually. The batch size SHALL be configurable via `embedding.batch_size`.
>
> **Rationale:** Embedding models — especially GPU-accelerated ones — achieve significantly higher throughput when processing batches of inputs. Individual embedding calls introduce per-request overhead (network round-trip, kernel launch, memory allocation) that dominates wall-clock time for small payloads. Batching amortises this overhead across many chunks.
>
> **Acceptance Criteria:**
> 1. Given 200 surviving chunks and `embedding.batch_size: 64`, the system issues exactly 4 embedding requests (3 batches of 64 + 1 batch of 8) rather than 200 individual requests.
> 2. The resulting embeddings are identical in order and value to those that would be produced by embedding each chunk individually.
> 3. The batch formation logic does not reorder chunks; output embeddings maintain a 1:1 positional correspondence with input chunks.

> **FR-1211** | Priority: MUST
>
> **Description:** The batch size MUST be configurable via `embedding.batch_size` with a default value of 64. The system SHALL enforce a minimum batch size of 1 and a maximum batch size of 2048. The batch size MAY also be overridden via the environment variable `RAGWEAVE_EMBEDDING_BATCH_SIZE`.
>
> **Rationale:** Optimal batch size depends on the embedding model, available GPU memory, and network constraints. A sensible default (64) works well for most API-based and mid-range GPU deployments, while the configurable range accommodates both constrained environments (small batches to avoid OOM) and high-throughput GPU clusters (large batches to saturate compute).
>
> **Acceptance Criteria:**
> 1. Given no explicit configuration, the system uses a batch size of 64.
> 2. Given `embedding.batch_size: 128`, the system uses batches of 128 chunks.
> 3. Given `embedding.batch_size: 0` or `embedding.batch_size: 4096`, the system rejects the configuration at startup with a clear error message stating the valid range [1, 2048].
> 4. Given the environment variable `RAGWEAVE_EMBEDDING_BATCH_SIZE=32` and no config file override, the system uses a batch size of 32.
> 5. If both the config file and environment variable are set, the config file value takes precedence.

> **FR-1212** | Priority: MUST
>
> **Description:** The system MUST handle a final partial batch (smaller than the configured batch size) without error. A document whose chunk count is not evenly divisible by the batch size SHALL still have all chunks embedded.
>
> **Rationale:** Real documents rarely produce chunk counts that are exact multiples of the batch size. The system must not silently drop trailing chunks or raise an error when the last batch is undersized.
>
> **Acceptance Criteria:**
> 1. Given 100 chunks and `embedding.batch_size: 64`, the system processes one batch of 64 and one batch of 36, producing exactly 100 embeddings.
> 2. Given 1 chunk and `embedding.batch_size: 64`, the system processes one batch of 1 and produces exactly 1 embedding.
> 3. Given 0 chunks (all filtered by quality validation), the system issues zero embedding requests and returns `stored_count: 0`.

> **FR-1213** | Priority: MUST
>
> **Description:** If an embedding batch fails, the system MUST retry only the failed batch, not the entire document's chunks. Successfully embedded batches SHALL NOT be re-embedded during retry. After exhausting retries for a batch, the system MUST record the failure and continue with remaining batches.
>
> **Rationale:** A transient failure (e.g., provider rate-limit, temporary OOM) affecting one batch should not force re-computation of embeddings that already succeeded. Isolating failures to the batch level minimises wasted compute and maximises the number of chunks that are successfully embedded even under degraded conditions.
>
> **Acceptance Criteria:**
> 1. Given 4 batches where batch 3 fails with a transient error, the system retries batch 3 up to the configured retry limit without re-embedding batches 1, 2, or 4.
> 2. If batch 3 succeeds on retry, all 4 batches' embeddings are stored.
> 3. If batch 3 exhausts retries, the system logs an error identifying the failed batch (batch index, chunk range), stores the embeddings from batches 1, 2, and 4, and reports the partial failure in the pipeline state (`errors` list).
> 4. The chunks from the failed batch are not written to the vector store without embeddings.

> **FR-1214** | Priority: SHOULD
>
> **Description:** The system SHOULD log batch-level observability metrics: the number of chunks per batch, embedding latency per batch (wall-clock milliseconds), and aggregate throughput (chunks per second) across all batches for a document.
>
> **Rationale:** Without batch-level metrics, operators cannot diagnose throughput bottlenecks, detect degraded embedding provider performance, or right-size the batch size configuration. Per-batch granularity reveals whether specific batches are slower (e.g., due to longer text content) and supports capacity planning.
>
> **Acceptance Criteria:**
> 1. Given a document processed in 4 batches, the system logs one entry per batch containing: batch index (1-based), chunk count in that batch, and wall-clock latency in milliseconds.
> 2. After all batches complete, the system logs a summary line containing: total chunks embedded, total batches, total wall-clock time, and throughput in chunks per second.
> 3. Log entries are structured (key-value or JSON) to support log aggregation and alerting.

---

### 3.8 Knowledge Graph Storage (FR-1300)

> **FR-1301** | Priority: MUST
>
> **Description:** The system MUST persist knowledge graph triples to a configurable graph store.
>
> **Rationale:** Extracted triples are only useful if persisted for query-time retrieval. A configurable store ensures the KG backend can evolve independently of the extraction logic, consistent with swappability-over-lock-in.
>
> **Acceptance Criteria:**
> 1. Given 200 extracted triples for a document, all 200 triples are persisted to the configured graph store and are queryable after ingestion completes.
> 2. A query for all triples with subject "SPEC-CLK-001" returns the expected containment, authorship, and relationship triples.

> **FR-1302** | Priority: MUST
>
> **Description:** The system MUST support at least two graph storage backends: vector store cross-references and a dedicated graph database.
>
> **Rationale:** Supports swappability-over-lock-in. Teams without a dedicated graph database can store cross-references as properties in the vector store (lower capability but zero additional infrastructure), while teams needing full graph traversal can use a dedicated graph database (e.g., Neo4j). This graduated approach avoids forcing infrastructure requirements on all deployments.
>
> **Acceptance Criteria:**
> 1. Given a configuration `graph_store.backend: "vector_store_refs"`, triples are stored as cross-reference properties on vector store objects.
> 2. Given `graph_store.backend: "neo4j"`, triples are stored as nodes and edges in Neo4j.
> 3. Both backends support triple insertion, deletion by document ID, and lookup by subject.
> 4. Switching between backends requires only a configuration change.

> **FR-1303** | Priority: MUST
>
> **Description:** The graph storage provider MUST be swappable via configuration.
>
> **Rationale:** Supports swappability-over-lock-in. As the knowledge graph matures, the team may need to migrate from a lightweight backend to a full graph database, and this migration must not require code changes.
>
> **Acceptance Criteria:**
> 1. Given a configuration change from `graph_store.provider: "weaviate_refs"` to `graph_store.provider: "neo4j"`, the system persists triples to Neo4j without code changes.
> 2. The pipeline produces identical triples regardless of the configured backend.
> 3. An invalid provider name produces a clear error at startup.

> **FR-1304** | Priority: MUST
>
> **Description:** The system MUST support a dry-run mode for KG storage.
>
> **Rationale:** Supports configuration-driven-behaviour. Dry-run mode for KG storage enables teams to preview the knowledge graph that would be generated (triple count, entity count, relationship types) without committing data, which is essential for validating KG extraction configuration before production runs.
>
> **Acceptance Criteria:**
> 1. Given a configuration `pipeline.dry_run: true`, the KG storage stage logs the number of triples and entities that would be persisted but writes zero records to the graph store.
> 2. The triples are available in the pipeline's in-memory state for inspection.
> 3. Setting `pipeline.dry_run: false` enables writes.

---

## Pipeline Requirements Traceability Matrix

This matrix covers all requirements defined in this specification: the new Clean Document Store Input Contract (FR-591–FR-595) and the Embedding Pipeline functional requirements (FR-601–FR-1304, plus FR-1210–FR-1214 for batch embedding optimisation).

### Requirements by Section

| REQ ID | Section | Priority | Component / Stage |
|--------|---------|----------|-------------------|
| FR-591 | 3.0 Clean Document Store Input Contract | MUST | Input Contract |
| FR-592 | 3.0 Clean Document Store Input Contract | MUST | Input Contract |
| FR-593 | 3.0 Clean Document Store Input Contract | MUST | Input Contract |
| FR-594 | 3.0 Clean Document Store Input Contract | MUST | Input Contract |
| FR-595 | 3.0 Clean Document Store Input Contract | SHOULD | Input Contract |
| FR-601–FR-611 | 3.1 Chunking | MUST | Chunking |
| FR-701–FR-705 | 3.2 Chunk Enrichment | MUST | Chunk Enrichment |
| FR-801–FR-806 | 3.3 Metadata Generation | MUST | Metadata Generation |
| FR-901–FR-905 | 3.4 Cross-Reference Extraction | MUST | Cross-Reference Extraction |
| FR-1001–FR-1009 | 3.5 Knowledge Graph Extraction | MUST | Knowledge Graph Extraction |
| FR-1101–FR-1105 | 3.6 Quality Validation | MUST | Quality Validation |
| FR-1201–FR-1209 | 3.7 Embedding & Storage | MUST | Embedding & Storage |
| FR-1210–FR-1213 | 3.7.1 Batch Embedding Optimisation | MUST | Embedding & Storage |
| FR-1214 | 3.7.1 Batch Embedding Optimisation | SHOULD | Embedding & Storage |
| FR-1301–FR-1304 | 3.8 Knowledge Graph Storage | MUST | Knowledge Graph Storage |

### Requirement Count Summary (This Specification Only)

| Priority | Count | Requirements |
|----------|-------|-------------|
| MUST | 60 | FR-591–FR-594, FR-601–FR-611, FR-701–FR-705, FR-801–FR-806, FR-901–FR-905, FR-1001–FR-1009, FR-1101–FR-1105, FR-1201–FR-1213, FR-1301–FR-1304 |
| SHOULD | 2 | FR-595, FR-1214 |
| MAY | 0 | — |
| **Total** | **62** | |

### Design Principle Coverage

| Design Principle | Requirements That Implement It |
|-----------------|-------------------------------|
| Swappability over lock-in | FR-602, FR-611, FR-702, FR-806, FR-902, FR-1002, FR-1202, FR-1205, FR-1206, FR-1209, FR-1301, FR-1302, FR-1303 |
| Fail-safe over fail-fast | FR-608, FR-704, FR-805, FR-903, FR-1007, FR-1213 |
| Context preservation over compression | FR-601, FR-604, FR-606, FR-703, FR-704, FR-705, FR-803, FR-804, FR-1006, FR-1105 |
| Configuration-driven behaviour | FR-602, FR-603, FR-604, FR-702, FR-703, FR-806, FR-902, FR-1002, FR-1009, FR-1101, FR-1102, FR-1202, FR-1208, FR-1209, FR-1211, FR-1304 |
| Idempotency by construction | FR-605, FR-593, FR-1003, FR-1008 |
| Controlled access over restriction | FR-594, FR-1104 |

### Cross-Reference to Companion Documents

| Topic | See |
|-------|-----|
| Document format parsing, text extraction, cleaning, multimodal processing | `DOCUMENT_PROCESSING_SPEC.md` (FR-100–FR-589) |
| Re-ingestion behaviour (FR-1400+) | `INGESTION_PLATFORM_SPEC.md` |
| Review tier management (FR-1500+) | `INGESTION_PLATFORM_SPEC.md` |
| Domain vocabulary (FR-1600+) | `INGESTION_PLATFORM_SPEC.md` |
| Error handling & fallbacks (FR-1700+) | `INGESTION_PLATFORM_SPEC.md` |
| Configuration (FR-1800+) | `INGESTION_PLATFORM_SPEC.md` |
| CLI / API interface (FR-1900+) | `INGESTION_PLATFORM_SPEC.md` |
| Non-functional requirements (NFR-100+) | `INGESTION_PLATFORM_SPEC.md` |
| Security & compliance (SC-100+) | `INGESTION_PLATFORM_SPEC.md` |
