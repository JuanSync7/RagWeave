> **Document type:** Authoritative requirements specification (Layer 3)
> **Downstream:** DOCLING_CHUNKING_SPEC_SUMMARY.md, DOCLING_CHUNKING_DESIGN.md
> **Last updated:** 2026-03-27

# Docling-Native Chunking Pipeline — Specification (v1.0.0)

**AION RAG Document Embedding Pipeline**
Version: 1.0.0 | Status: Draft | Domain: Document Processing & Chunking

## Document Information

> **Document intent:** This is a formal specification for the **Docling-Native Chunking Pipeline** redesign — a cross-phase subsystem that preserves the `DoclingDocument` object through the ingestion pipeline and replaces the current markdown-string-based chunking cascade with Docling's structure-aware, token-aware `HybridChunker`. It also consolidates VLM image processing to a post-chunking step and removes the text-cleaning and document-refactoring nodes for Docling-parsed documents.
> For the existing Document Processing Pipeline functional requirements (FR-100 through FR-589), see `DOCUMENT_PROCESSING_SPEC.md`.
> For the existing Embedding Pipeline functional requirements (FR-591 through FR-1399), see `EMBEDDING_PIPELINE_SPEC.md`.
> For cross-cutting platform requirements, see `INGESTION_PLATFORM_SPEC.md`.

| Field | Value |
|-------|-------|
| System | AION RAG Document Embedding Pipeline |
| Document Type | Subsystem Specification — Docling-Native Chunking Redesign |
| Companion Documents | DOCUMENT_PROCESSING_SPEC.md, EMBEDDING_PIPELINE_SPEC.md, INGESTION_PLATFORM_SPEC.md |
| Version | 1.0.0 |
| Status | Draft |
| Supersedes | None (new subsystem; modifies behavior specified in FR-200–FR-299, FR-400–FR-499, FR-500–FR-599, FR-600–FR-699) |

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2026-03-27 | AI Assistant | Full spec from brainstorm sketch; FR IDs assigned, traceability matrix complete, appendices finalized |

---

## 1. Scope & Definitions

### 1.1 Problem Statement

The current ingestion pipeline discards the rich `DoclingDocument` object immediately after converting it to a markdown string via `export_to_markdown()`. This wastes all structural information — paragraph boundaries, table cell structure, list hierarchies, figure metadata, and code block delineation — that Docling already extracted during parsing.

As a consequence, the downstream chunking pipeline must reconstruct structure heuristically using `MarkdownHeaderTextSplitter`, which:

1. **Misses sub-heading structural boundaries.** Paragraphs, tables, and code blocks within a section are not recognized as natural chunk boundaries. A table row may be split mid-cell, or a code block may be split mid-function.
2. **Produces poor table chunks.** Markdown tables lose their header row when split across chunks, making individual table chunks unintelligible to the embedding model and to retrieval consumers.
3. **Requires compensating pipeline nodes.** The `text_cleaning_node` and `document_refactoring_node` exist primarily to compensate for structural information loss — cleaning layout artifacts that Docling already removed, and using an LLM to rewrite paragraphs into self-contained units that structure-aware chunking would produce natively.
4. **Uses character-based size limits instead of token-based limits.** The current `chunk_size` parameter measures characters, which does not align with the embedding model's token limit. This causes either wasted embedding capacity (chunks too short in tokens) or silent truncation (chunks too long in tokens).

Docling's `HybridChunker` operates on the native `DoclingDocument` object and solves all four problems: it respects document items as natural boundaries, repeats table headers in every table chunk, uses a tokenizer-aligned `max_tokens` limit, and merges undersized items into coherent chunks.

### 1.2 Scope

This specification defines the requirements for the **Docling-Native Chunking Pipeline** redesign within the AION RAG ingestion system. The redesign spans both Phase 1 (Document Processing) and Phase 2 (Embedding) pipelines.

- **Entry point:** Source document file parsed by Docling's `DocumentConverter`, producing a `DoclingDocument` object.
- **Exit point:** A list of `ProcessedChunk` objects with structure-aware metadata, ready for embedding and storage.

For non-Docling sources (documents not parsed by Docling), the existing markdown-based pipeline remains the active path. This specification covers both the new Docling-native path and its coexistence with the fallback path.

### 1.3 Terminology

| Term | Definition |
|------|-----------|
| **DoclingDocument** | The structured document object produced by Docling's `DocumentConverter`. Contains typed document items (paragraphs, tables, lists, figures, code blocks) with hierarchical section structure. |
| **HybridChunker** | A Docling-provided chunker that operates on `DoclingDocument` objects. Produces structure-aware, token-aware chunks that respect document item boundaries. Uses `semchunk` internally for forced splits of oversized items. |
| **DoclingParseResult** | The normalized dataclass returned by `parse_with_docling()`, containing the markdown export, figure metadata, headings, and (after this redesign) the native `DoclingDocument` object. |
| **VLM** | Vision Language Model — a multimodal model that processes images and produces text descriptions. Used to replace figure placeholders in chunks with semantic descriptions. |
| **Builtin VLM** | Docling's integrated SmolVLM model, downloaded and run locally alongside the Docling parser. |
| **External VLM** | A frontier VLM accessed via LiteLLM routing (e.g., GPT-4V, Claude Vision, Gemini Pro Vision). |
| **section_path** | A hierarchical breadcrumb string (e.g., "Introduction > Background > Prior Work") derived from the document's heading structure, prepended to chunk metadata for context preservation. |
| **Fallback pipeline** | The existing markdown-based chunking path (`MarkdownHeaderTextSplitter` followed by `RecursiveCharacterTextSplitter`) used for non-Docling sources. |
| **CleanDocumentStore** | The persistent file-based store at the Phase 1/Phase 2 boundary, storing clean markdown and metadata per source document. |
| **semchunk** | The token-aware text splitter used internally by `HybridChunker` when a single document item exceeds `max_tokens`. |

### 1.4 Requirement Priority Levels

This specification uses the key words defined in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119):

| Keyword | Meaning |
|---------|---------|
| **MUST** / **SHALL** | Absolute requirement. The system is non-conformant without it. |
| **SHOULD** / **RECOMMENDED** | There may be valid reasons to omit this in particular circumstances, but the full implications must be understood and carefully weighed. |
| **MAY** / **OPTIONAL** | Truly optional. The system is conformant whether or not this is implemented. |

### 1.5 Requirement Format

Requirements in this specification use domain-prefixed IDs:

| Prefix | Meaning |
|--------|---------|
| **FR-** | Functional Requirement |
| **NFR-** | Non-Functional Requirement |

Requirements are grouped by section with the following ID ranges:

| Section | ID Range | Component |
|---------|----------|-----------|
| 3. DoclingDocument Preservation | FR-2000–FR-2099 | Document object threading |
| 4. HybridChunker Integration | FR-2100–FR-2199 | Structure-aware chunking |
| 5. VLM Image Enrichment | FR-2200–FR-2299 | Post-chunking image description |
| 6. Fallback Pipeline | FR-2300–FR-2399 | Markdown-based chunking fallback |
| 7. Configuration Surface | FR-2400–FR-2499 | New config fields and env vars |
| 8. State Contract Changes | FR-2500–FR-2599 | Pipeline state modifications |
| 9. Error Handling & Fallback | FR-2600–FR-2699 | Error taxonomy, supported formats, and fallback behavior |
| 10. Non-Functional Requirements | NFR-2900–NFR-2999 | Performance, compatibility, maintainability |

### 1.6 Assumptions & Constraints

| ID | Assumption / Constraint | Impact if Violated |
|----|------------------------|--------------------|
| A-1 | Python 3.11+ runtime | Type hint syntax and match statements fail |
| A-2 | `docling` and `docling-core` packages installed | HybridChunker and DoclingDocument serialization unavailable; system falls back to markdown pipeline |
| A-3 | Embedding model (bge-m3) has a known maximum token input length | HybridChunker `max_tokens` cannot be aligned; chunks may exceed embedding capacity |
| A-4 | LiteLLM Router available when external VLM mode is enabled | External VLM calls fail; system falls back to builtin VLM or skips VLM enrichment |
| A-5 | Sequential document processing (no concurrent ingestion of same document) | Race conditions on CleanDocumentStore writes and DoclingDocument serialization |
| A-6 | SmolVLM model artifacts downloadable when builtin VLM mode is enabled | Builtin VLM initialization fails; system skips VLM enrichment with warning |

### 1.7 Design Principles

| Principle | Description |
|-----------|-------------|
| **Structure preservation over string heuristics** | When a structured document representation is available (DoclingDocument), the pipeline SHALL use it directly rather than converting to a string and reconstructing structure from that string. |
| **Fail-safe over fail-fast** | When the Docling-native path fails (missing dependencies, serialization errors, HybridChunker exceptions), the pipeline SHALL fall back to the markdown-based pipeline rather than halting. A single document's chunking failure SHALL NOT halt a batch job. |
| **Token-alignment over character-alignment** | Chunk size limits SHALL be expressed in tokens aligned with the embedding model's tokenizer, not in characters. This ensures each chunk uses the embedding model's capacity without truncation or waste. |
| **Configuration-driven path selection** | The choice between Docling-native chunking and markdown-based chunking, and between builtin and external VLM, SHALL be controlled by configuration flags — not by code-level conditionals scattered across multiple modules. |
| **Deterministic over LLM-dependent** | Where structure-aware chunking eliminates the need for LLM-based text rewriting (document refactoring), the deterministic approach SHALL be preferred. LLM calls add latency, cost, and non-determinism. |

### 1.8 Out of Scope

**Out of scope — this spec:**

- Changes to the Docling parser configuration or model selection (covered by existing FR-200 series)
- Embedding model changes or embedding storage schema changes (covered by EMBEDDING_PIPELINE_SPEC.md)
- Weaviate collection schema modifications
- Knowledge graph extraction changes
- Quality validation node changes
- Chunk enrichment node changes (beyond receiving HybridChunker output)
- CLI or web UI changes beyond new configuration flags
- Removal of the existing markdown pipeline code (retained as fallback)
- Re-ingestion logic changes (covered by INGESTION_PLATFORM_SPEC.md)

**Out of scope — this project:**

- Replacing Docling with an alternative document parser
- Multi-document cross-reference chunking (chunks spanning multiple source documents)
- Real-time streaming chunking
- GPU-accelerated chunking

---

## 2. System Overview

### 2.1 Architecture Diagram

```
Source Document File
    │
    ▼
┌──────────────────────────────────────────────┐
│ [1] STRUCTURE DETECTION (existing)           │
│     Parse with Docling → DoclingDocument      │
│     + markdown export. Store both in state.   │
│     Regex fallback if Docling disabled/fails. │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
          ┌────────┴────────┐
          │  Docling path?  │
          └───┬─────────┬───┘
        Yes   │         │  No
              ▼         ▼
┌─────────────────┐  ┌─────────────────────────┐
│ [2a] SKIP       │  │ [2b] TEXT CLEANING       │
│   text_cleaning │  │   (existing, unchanged) │
│   node          │  │   Boilerplate strip,     │
│                 │  │   unicode, whitespace    │
├─────────────────┤  ├─────────────────────────┤
│ [3a] SKIP       │  │ [3b] DOC REFACTORING    │
│   doc_refactor  │  │   (existing, unchanged) │
│   node          │  │   LLM paragraph rewrite │
└────────┬────────┘  └────────────┬────────────┘
         │                        │
         ▼                        ▼
┌──────────────────────────────────────────────┐
│              CLEAN DOCUMENT STORE             │
│  Markdown + metadata + DoclingDocument JSON   │
│  (DoclingDocument stored only for Docling     │
│   path; absent for fallback path)             │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
          ┌────────┴────────┐
          │ DoclingDocument  │
          │ available?       │
          └───┬─────────┬───┘
        Yes   │         │  No
              ▼         ▼
┌─────────────────┐  ┌─────────────────────────┐
│ [4a] HYBRID     │  │ [4b] MARKDOWN CHUNKING   │
│   CHUNKER       │  │   (existing, unchanged)  │
│   Structure +   │  │   MarkdownHeaderSplit →   │
│   token-aware   │  │   RecursiveCharSplit      │
└────────┬────────┘  └────────────┬────────────┘
         │                        │
         └───────────┬────────────┘
                     ▼
          ┌──────────┴──────────┐
          │ Figures in chunks?  │
          │ VLM enabled?        │
          └───┬─────────────┬───┘
        Yes   │             │  No
              ▼             │
┌─────────────────────┐     │
│ [5] VLM ENRICHMENT  │     │
│   Replace image     │     │
│   placeholders with │     │
│   VLM descriptions  │     │
│   (builtin/external)│     │
└─────────┬───────────┘     │
          │                 │
          └────────┬────────┘
                   ▼
┌──────────────────────────────────────────────┐
│ [6] CHUNK OUTPUT                              │
│     ProcessedChunk list with section_path,    │
│     chunk_index, total_chunks metadata        │
└──────────────────────────────────────────────┘
```

### 2.2 Data Flow Summary

| Stage | Input | Output | Condition |
|-------|-------|--------|-----------|
| Structure Detection | Source file path | `DoclingDocument` + markdown string (Docling path) OR regex-detected headings/figures (fallback path) | Always runs |
| Text Cleaning | Raw markdown text | Cleaned markdown text | Skipped for Docling-parsed documents |
| Document Refactoring | Cleaned markdown text | LLM-rewritten self-contained paragraphs | Skipped for Docling-parsed documents |
| Clean Document Store | Markdown + metadata + optional DoclingDocument JSON | Persisted files | Always runs |
| HybridChunker | `DoclingDocument` object | Token-aware, structure-aware chunk list with `section_path` metadata | DoclingDocument available in state |
| Markdown Chunking | Markdown string | Character-based chunk list with header metadata | DoclingDocument NOT available (fallback) |
| VLM Enrichment | Chunk list with image placeholders | Chunk list with image descriptions replacing placeholders | Figures detected AND VLM enabled |
| Chunk Output | Enriched chunk list | `ProcessedChunk` list with full metadata | Always runs |

---

## 3. DoclingDocument Preservation

> **FR-2001** | Priority: MUST
>
> **Description:** The `DoclingParseResult` dataclass MUST include a field that carries the native `DoclingDocument` object produced by Docling's `DocumentConverter`. This field MUST be populated when Docling parsing succeeds and MUST be `None` when Docling parsing is disabled or fails.
>
> **Rationale:** The `DoclingDocument` object contains typed structural items (paragraphs, tables, lists, figures, code blocks) with hierarchical section relationships. Without preserving this object, the pipeline cannot use `HybridChunker` and must fall back to string-based heuristics that lose structural fidelity.
>
> **Acceptance Criteria:** After a successful `parse_with_docling()` call, the returned `DoclingParseResult` has a non-None `docling_document` field that is an instance of `docling_core.types.doc.DoclingDocument`. When Docling parsing is disabled, the field is `None`.

---

> **FR-2003** | Priority: MUST
>
> **Description:** The `structure_detection_node` MUST propagate the `DoclingDocument` object from `DoclingParseResult` into the pipeline state when Docling parsing succeeds. The state field MUST be named `docling_document`.
>
> **Rationale:** The `DoclingDocument` must travel through the pipeline state to reach the chunking node in Phase 2. Without state propagation, the object is lost at the Phase 1/Phase 2 boundary.
>
> **Acceptance Criteria:** After `structure_detection_node` completes with Docling enabled and parsing successful, the returned state update contains a `docling_document` key whose value is the `DoclingDocument` instance. When Docling parsing fails or is disabled, the key is either absent or set to `None`.

---

> **FR-2005** | Priority: MUST
>
> **Description:** The `CleanDocumentStore` MUST support storing a serialized `DoclingDocument` alongside the existing markdown and metadata files. The serialized form MUST use JSON produced by `docling-core`'s serialization API.
>
> **Rationale:** The `DoclingDocument` must survive the Phase 1/Phase 2 boundary, which is mediated by the `CleanDocumentStore`. Without persistence, Phase 2 cannot access the structured document object and must fall back to markdown-based chunking.
>
> **Acceptance Criteria:** Given a Docling-parsed document, `CleanDocumentStore.write()` persists three files: `{source_key}.md`, `{source_key}.meta.json`, and `{source_key}.docling.json`. `CleanDocumentStore.read()` returns the deserialized `DoclingDocument` object when the `.docling.json` file is present. When the file is absent (non-Docling source), `read()` returns `None` for the document object.

---

> **FR-2007** | Priority: MUST
>
> **Description:** The serialized `DoclingDocument` JSON MUST be written atomically using the same tmp-file-then-rename pattern used by existing `CleanDocumentStore` writes.
>
> **Rationale:** A partial write of the DoclingDocument JSON could leave a corrupt file that causes deserialization failures in Phase 2, potentially crashing the embedding pipeline for that document. The existing atomic write pattern prevents this.
>
> **Acceptance Criteria:** The `.docling.json` file is written to a `.docling.json.tmp` path first, then renamed into place. If the write fails mid-way, no `.docling.json` file exists (the tmp file is cleaned up).

---

> **FR-2009** | Priority: SHOULD
>
> **Description:** The system SHOULD support a configuration toggle to disable `DoclingDocument` persistence in the `CleanDocumentStore`, causing the system to re-parse the source document in Phase 2 when the `DoclingDocument` is needed.
>
> **Rationale:** For very large documents, the serialized `DoclingDocument` JSON may consume significant disk space. Operators who are storage-constrained but have fast re-parsing should be able to trade storage for compute.
>
> **Acceptance Criteria:** When `persist_docling_document` is set to `false` in configuration, the `CleanDocumentStore` does not write the `.docling.json` file. Phase 2 detects the absence and either re-parses the source file or falls back to markdown chunking.

---

> **FR-2011** | Priority: MUST
>
> **Description:** When the Docling-native path is active for a document (DoclingDocument is available), the `text_cleaning_node` MUST be skipped for that document. The pipeline MUST NOT apply boilerplate stripping, whitespace normalization, or heading normalization to Docling-parsed content.
>
> **Rationale:** Docling's parser already produces clean output: layout artifacts, headers/footers, and page numbers are stripped during parsing. Running the text cleaning pipeline on Docling output risks corrupting well-formed markdown (e.g., stripping legitimate short lines in code blocks, or re-normalizing headings that Docling already formatted correctly).
>
> **Acceptance Criteria:** Given a document parsed by Docling, the `processing_log` does not contain a `text_cleaning:ok` entry. The `cleaned_text` field in state is set directly from the Docling markdown export without modification by the text cleaning pipeline.

---

> **FR-2013** | Priority: MUST
>
> **Description:** When the Docling-native path is active for a document, the `document_refactoring_node` MUST be skipped for that document. No LLM-based paragraph rewriting MUST occur.
>
> **Rationale:** Document refactoring exists to compensate for poor chunk boundaries by rewriting paragraphs into self-contained units. With structure-aware chunking via `HybridChunker`, chunks already respect document item boundaries (paragraphs, tables, lists), making LLM rewriting unnecessary. Skipping this node eliminates LLM latency, cost, and non-determinism for Docling-parsed documents.
>
> **Acceptance Criteria:** Given a document parsed by Docling, the `processing_log` does not contain a `document_refactoring:ok` entry. The `refactored_text` field in state is `None`.

---

> **FR-2015** | Priority: MUST
>
> **Description:** Lightweight unicode normalization (NFC normalization and control character removal) MUST still be applied to each chunk's text content after `HybridChunker` produces its output, regardless of whether the Docling-native or fallback path is used.
>
> **Rationale:** While Docling produces clean markdown, it does not guarantee NFC-normalized unicode or absence of control characters. The embedding model expects normalized input, and inconsistent unicode normalization leads to duplicate embeddings for visually identical text.
>
> **Acceptance Criteria:** Given a chunk containing a non-NFC unicode sequence (e.g., combining diacritical marks), the output chunk text is NFC-normalized. Given a chunk containing a control character (e.g., `\x00`), the control character is removed from the output.

---

## 4. HybridChunker Integration

> **FR-2101** | Priority: MUST
>
> **Description:** When a `DoclingDocument` is available in pipeline state, the `chunking_node` MUST use Docling's `HybridChunker` to produce chunks instead of the markdown-based `MarkdownHeaderTextSplitter` and `RecursiveCharacterTextSplitter` cascade.
>
> **Rationale:** `HybridChunker` operates on the native document structure, respecting paragraphs, tables, lists, figures, and code blocks as natural chunk boundaries. This produces higher-quality chunks than string-based splitting, which has no awareness of document item types.
>
> **Acceptance Criteria:** Given a document with a `DoclingDocument` in state, the `chunking_node` invokes `HybridChunker` and does not invoke `MarkdownHeaderTextSplitter` or `RecursiveCharacterTextSplitter`. The resulting chunks respect document item boundaries (no table rows split mid-cell, no code blocks split mid-line).

---

> **FR-2103** | Priority: MUST
>
> **Description:** The `HybridChunker` MUST be configured with a `max_tokens` parameter aligned to the embedding model's maximum input token length. The tokenizer used by `HybridChunker` MUST match the embedding model's tokenizer.
>
> **Rationale:** Token-alignment ensures that each chunk fully utilizes the embedding model's capacity without truncation. A mismatch between the chunker's tokenizer and the embedding model's tokenizer leads to chunks that are either too long (truncated during embedding, losing information) or too short (wasting embedding capacity).
>
> **Acceptance Criteria:** The `HybridChunker` is instantiated with a `max_tokens` value derived from configuration and a tokenizer that matches the embedding model (bge-m3). No chunk produced by the chunker exceeds the configured `max_tokens` when measured by the same tokenizer.

---

> **FR-2105** | Priority: MUST
>
> **Description:** Each chunk produced by `HybridChunker` MUST include a `section_path` metadata field containing the hierarchical heading breadcrumb from the document's section structure (e.g., "Chapter 1 > Background > Prior Work").
>
> **Rationale:** `section_path` provides retrieval context that was previously supplied by the `document_refactoring_node`'s LLM paragraph rewriting. Prepending the section path is deterministic, zero-cost, and preserves the chunk's position within the document's logical structure for both the embedding model and the retrieval consumer.
>
> **Acceptance Criteria:** Given a document with headings "Introduction", "Background", and a chunk under "Background", the chunk's metadata contains `section_path: "Introduction > Background"` (or the equivalent path from the DoclingDocument's heading hierarchy). Every chunk has a non-empty `section_path` unless the chunk precedes all headings in the document.

---

> **FR-2107** | Priority: MUST
>
> **Description:** When a table document item spans multiple chunks, every chunk that contains a portion of that table MUST include the table's header row as context.
>
> **Rationale:** A table chunk without its header row is unintelligible — the embedding model cannot determine what each column represents, and retrieval consumers cannot interpret the data. `HybridChunker` provides this behavior natively for `DoclingDocument` tables.
>
> **Acceptance Criteria:** Given a table with 50 rows and a header row, chunked into 3 chunks of approximately equal token count, each of the 3 chunks begins with the table's header row followed by the data rows assigned to that chunk.

---

> **FR-2109** | Priority: MUST
>
> **Description:** When a single document item (e.g., a very long paragraph or code block) exceeds `max_tokens`, `HybridChunker` MUST split it using its internal `semchunk` text splitter. The system MUST NOT apply a separate semantic splitting pass (embedding every sentence and splitting on cosine similarity drops).
>
> **Rationale:** The current pipeline's semantic splitting step (`_semantic_split`) embeds every sentence to detect topic shifts. This adds significant latency and cost with negligible benefit for technical documents and code, which are the primary document types in this system. `semchunk` handles forced splits in a token-aware manner without requiring embedding calls.
>
> **Acceptance Criteria:** Given a single paragraph exceeding `max_tokens`, the chunker splits it into sub-chunks that each fit within `max_tokens`. No embedding model calls are made during the chunking process. The `_semantic_split` function is not invoked for Docling-path documents.

---

> **FR-2111** | Priority: MUST
>
> **Description:** Each chunk produced by the Docling-native path MUST be converted to a `ProcessedChunk` object with the same metadata schema as chunks produced by the fallback markdown path. The metadata MUST include: `source`, `source_uri`, `source_key`, `source_id`, `connector`, `source_version`, `section_path`, `heading`, `heading_level`, `chunk_index`, and `total_chunks`.
>
> **Rationale:** Downstream pipeline nodes (chunk enrichment, metadata generation, embedding storage) depend on a consistent chunk metadata contract. The chunking path (Docling-native vs. fallback) must be invisible to downstream consumers.
>
> **Acceptance Criteria:** Given chunks produced by the Docling-native path, each `ProcessedChunk` contains all metadata keys listed in the description. Downstream nodes process Docling-native chunks identically to fallback-path chunks without errors or missing fields.

---

> **FR-2113** | Priority: SHOULD
>
> **Description:** Undersized document items (items whose text is shorter than a configurable `min_chunk_tokens` threshold) SHOULD be merged with adjacent items into a single chunk, up to the `max_tokens` limit.
>
> **Rationale:** Very short chunks (e.g., a single-sentence paragraph or a short list item) waste embedding capacity and add noise to retrieval results. `HybridChunker` provides undersized-chunk merging natively; this requirement ensures the feature is enabled and configured.
>
> **Acceptance Criteria:** Given three consecutive paragraphs of 10, 15, and 20 tokens respectively (total 45 tokens, below `max_tokens`), the chunker produces a single merged chunk containing all three paragraphs. The merge does not cross section heading boundaries.

---

> **FR-2115** | Priority: SHOULD
>
> **Description:** Code blocks SHOULD be kept as single chunks when they fit within `max_tokens`. When a code block exceeds `max_tokens`, it SHOULD be split at line boundaries rather than mid-line.
>
> **Rationale:** Splitting a code block mid-line produces syntactically invalid fragments that the embedding model cannot meaningfully represent. Line-boundary splitting preserves at least partial syntactic validity. `HybridChunker` respects code block items as atomic units when they fit within the token limit.
>
> **Acceptance Criteria:** Given a code block of 200 tokens (below `max_tokens`), the chunker produces a single chunk containing the entire code block. Given a code block of 1500 tokens (above `max_tokens` of 512), the split occurs at a line boundary, not mid-line.

---

## 5. VLM Image Enrichment

> **FR-2201** | Priority: MUST
>
> **Description:** VLM image processing MUST occur after chunking, not before. The VLM enrichment step MUST operate on the chunk list produced by either the Docling-native or fallback chunking path, replacing image placeholders in chunk text with VLM-generated descriptions.
>
> **Rationale:** Pre-chunking VLM processing (the current approach) inserts descriptions into the full document text, which may then be split across chunk boundaries by the chunker. Post-chunking VLM processing ensures each image description is injected into the specific chunk that contains its placeholder, maintaining chunk coherence. It also allows VLM processing to be parallelized per-chunk.
>
> **Acceptance Criteria:** The pipeline DAG places the VLM enrichment step after the chunking step. Given a document with 2 figures producing 10 chunks where chunks 3 and 7 contain figure placeholders, only chunks 3 and 7 are modified by VLM enrichment. The other 8 chunks are unchanged.

---

> **FR-2203** | Priority: MUST
>
> **Description:** The system MUST support two VLM modes, selectable via configuration:
>
> - **builtin**: Docling's integrated SmolVLM model, running locally.
> - **external**: A frontier VLM accessed via LiteLLM routing.
>
> A third implicit mode, **disabled**, disables VLM enrichment entirely.
>
> **Rationale:** Builtin SmolVLM provides zero-infrastructure image captioning suitable for basic figure descriptions. External VLM via LiteLLM provides access to frontier models (GPT-4V, Claude Vision, Gemini Pro Vision) for deep diagram understanding — critical for complex engineering diagrams, circuit schematics, and data flow charts. Operators need to choose based on their quality requirements and infrastructure constraints.
>
> **Acceptance Criteria:** When `vlm_mode` is set to `builtin`, VLM enrichment uses Docling's SmolVLM model. When set to `external`, VLM enrichment uses the LiteLLM Router with the configured vision model. When set to `disabled`, no VLM enrichment occurs and image placeholders remain in chunk text. Invalid values cause a configuration validation error at startup.

---

> **FR-2205** | Priority: MUST
>
> **Description:** Image placeholders in chunk text MUST be detected using a consistent pattern (e.g., `![Figure N](...)` or Docling's figure reference format) and replaced with the VLM-generated description text. The replacement MUST preserve the chunk's surrounding text and not alter non-placeholder content.
>
> **Rationale:** The VLM description must be integrated into the chunk text so that the embedding model encodes the image's semantic content alongside the surrounding text. Altering non-placeholder content would corrupt the chunk.
>
> **Acceptance Criteria:** Given a chunk containing `![Figure 3](image_path.png)` and a VLM description "Block diagram showing the data flow from ingestion to retrieval", the placeholder is replaced with the description text. The text before and after the placeholder is unchanged. No other content in the chunk is modified.

---

> **FR-2207** | Priority: MUST
>
> **Description:** When VLM processing fails for a specific image (model timeout, API error, unsupported image format), the system MUST leave the original image placeholder in the chunk text and log a warning. The failure MUST NOT cause the entire document's chunking to fail.
>
> **Rationale:** Supports the fail-safe-over-fail-fast principle. A single image's VLM failure should not prevent the rest of the document's chunks from being embedded and stored. The placeholder text still provides some signal to the embedding model (e.g., "Figure 3" conveys that a figure exists).
>
> **Acceptance Criteria:** Given a chunk with an image placeholder where the VLM call returns an error, the chunk retains its original placeholder text. The `processing_log` contains a warning entry identifying the failed image. Other chunks in the same document are processed normally. No entry is added to the `errors` list (warnings only).

---

> **FR-2209** | Priority: SHOULD
>
> **Description:** When using external VLM mode, the system SHOULD respect the existing `vision_max_figures` configuration limit, processing at most N images per document.
>
> **Rationale:** Frontier VLM calls are expensive (API cost + latency). Limiting the number of images processed per document controls cost and prevents a single image-heavy document from dominating pipeline latency.
>
> **Acceptance Criteria:** Given a document with 20 figures and `vision_max_figures` set to 4, only the first 4 figure placeholders are sent to the VLM. The remaining 16 placeholders are left unchanged in their respective chunks.

---

> **FR-2211** | Priority: SHOULD
>
> **Description:** When using builtin VLM mode, SmolVLM model artifacts SHOULD be downloaded only when `vlm_mode` is set to `builtin`. The download MUST NOT occur during general Docling model warmup when VLM is disabled or set to external mode.
>
> **Rationale:** SmolVLM model artifacts add significant download time and disk usage. Downloading them unconditionally wastes resources for operators who do not use builtin VLM mode.
>
> **Acceptance Criteria:** When `vlm_mode` is `external` or `disabled`, the `warmup_docling_models` function does not download SmolVLM artifacts (`with_smolvlm=False`). When `vlm_mode` is `builtin`, SmolVLM artifacts are downloaded during warmup (`with_smolvlm=True`).

---

## 6. Fallback Pipeline

> **FR-2301** | Priority: MUST
>
> **Description:** When a document is not parsed by Docling (Docling disabled, unsupported format, or Docling parsing failed in non-strict mode), the `chunking_node` MUST use the existing markdown-based chunking path: `MarkdownHeaderTextSplitter` followed by `RecursiveCharacterTextSplitter`, with optional semantic splitting if enabled.
>
> **Rationale:** The Docling-native path cannot operate without a `DoclingDocument`. The existing markdown-based pipeline is proven and handles all document formats that produce markdown text. Preserving it as a fallback ensures no regression for documents that cannot be Docling-parsed.
>
> **Acceptance Criteria:** Given a document where `docling_document` is `None` in pipeline state, the `chunking_node` invokes `chunk_markdown()` with the existing `MarkdownHeaderTextSplitter` and `RecursiveCharacterTextSplitter` logic. The output is a list of `ProcessedChunk` objects with the same metadata schema as Docling-native chunks.

---

> **FR-2303** | Priority: MUST
>
> **Description:** When the fallback pipeline is used, the `text_cleaning_node` and `document_refactoring_node` MUST execute normally according to their existing configuration flags (`enable_multimodal_processing`, `enable_document_refactoring`).
>
> **Rationale:** The text cleaning and document refactoring nodes compensate for the lack of structural awareness in the markdown-based chunking path. Skipping them for the fallback path would degrade chunk quality for non-Docling sources.
>
> **Acceptance Criteria:** Given a non-Docling document with `enable_document_refactoring=true`, the `document_refactoring_node` runs and produces `refactored_text`. The `text_cleaning_node` runs and produces `cleaned_text`. Both entries appear in the `processing_log`.

---

> **FR-2305** | Priority: MUST
>
> **Description:** The fallback pipeline MUST remain semantically unchanged in behavior compared to its pre-redesign implementation, with one deliberate exception: per-chunk unicode normalization (FR-2015) is applied uniformly to both paths as of this redesign. No existing configuration flags, chunking parameters, or output schemas MUST be altered for the fallback path. Aside from unicode normalization, the fallback path MUST produce output identical to pre-redesign behavior.
>
> **Rationale:** The fallback pipeline is the safety net for non-Docling sources and for operators who disable the Docling-native path. Unicode normalization is a deliberate quality upgrade applied to both paths for embedding consistency, not a regression. All other behavioral changes to the fallback path are a regression risk.
>
> **Acceptance Criteria:** Given identical input and configuration, the fallback pipeline produces `ProcessedChunk` output that is byte-identical to pre-redesign output except where unicode normalization (FR-2015) alters non-NFC sequences or removes control characters. All existing tests for the markdown-based chunking path continue to pass without modification.

---

> **FR-2307** | Priority: MUST
>
> **Description:** The `chunking_node` MUST select the chunking path (Docling-native vs. fallback) based solely on the presence of a non-None `docling_document` in pipeline state. No additional configuration flag MUST be required to select the chunking path at runtime.
>
> **Rationale:** Path selection should be automatic and data-driven. If Docling parsing succeeded and the `DoclingDocument` is available, the native path is used. If not, the fallback is used. This avoids configuration conflicts where an operator enables Docling parsing but accidentally disables Docling chunking.
>
> **Acceptance Criteria:** Given `docling_document` is not None in state, the Docling-native chunking path is used regardless of other configuration flags. Given `docling_document` is None, the fallback path is used. No new "enable Docling chunking" configuration flag exists.

---

## 7. Configuration Surface

> **FR-2401** | Priority: MUST
>
> **Description:** The `IngestionConfig` dataclass MUST include a `vlm_mode` field with three valid values: `"disabled"`, `"builtin"`, and `"external"`. The default value MUST be `"disabled"`.
>
> **Rationale:** The VLM mode determines which image processing backend is used for post-chunking enrichment. A dedicated field with enumerated values prevents misconfiguration (e.g., setting both builtin and external flags simultaneously).
>
> **Acceptance Criteria:** `IngestionConfig` has a `vlm_mode: str` field. Valid values are `"disabled"`, `"builtin"`, `"external"`. Setting any other value raises a validation error during configuration checking. The default is `"disabled"`.

---

> **FR-2403** | Priority: MUST
>
> **Description:** The `IngestionConfig` dataclass MUST include a `hybrid_chunker_max_tokens` field controlling the `max_tokens` parameter passed to `HybridChunker`. The default value MUST be derived from the embedding model's maximum input token length.
>
> **Rationale:** Operators need to tune the chunk size in tokens to match their embedding model's capacity. The default should be safe for the system's standard embedding model (bge-m3), but operators using different models need to override it.
>
> **Acceptance Criteria:** `IngestionConfig` has a `hybrid_chunker_max_tokens: int` field. The default value is set to the bge-m3 embedding model's maximum input token length (512 tokens or the appropriate limit). The value is passed to `HybridChunker(max_tokens=...)` when the Docling-native path is active.

---

> **FR-2405** | Priority: MUST
>
> **Description:** The `vlm_mode` configuration field MUST be settable via the environment variable `RAG_INGESTION_VLM_MODE`. The `hybrid_chunker_max_tokens` field MUST be settable via `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS`.
>
> **Rationale:** All ingestion configuration follows the pattern of environment variable defaults with runtime overrides. New configuration fields must follow the same pattern for consistency and operational parity.
>
> **Acceptance Criteria:** Setting `RAG_INGESTION_VLM_MODE=external` in the environment causes `IngestionConfig().vlm_mode` to equal `"external"`. Setting `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS=256` causes `IngestionConfig().hybrid_chunker_max_tokens` to equal `256`.

---

> **FR-2407** | Priority: MUST
>
> **Description:** The `IngestionConfig` dataclass MUST include a `persist_docling_document` boolean field controlling whether the serialized `DoclingDocument` JSON is persisted to the `CleanDocumentStore`. The default value MUST be `true`.
>
> **Rationale:** Enables the storage-vs-compute tradeoff described in FR-2009. The default of `true` ensures the Docling-native chunking path works without re-parsing in Phase 2.
>
> **Acceptance Criteria:** `IngestionConfig` has a `persist_docling_document: bool` field defaulting to `true`. When set to `false`, the `CleanDocumentStore.write()` call does not produce a `.docling.json` file. The field is settable via `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT`.

---

> **FR-2409** | Priority: SHOULD
>
> **Description:** Configuration validation SHOULD detect contradictory settings and fail fast with a clear error message. Specifically:
>
> - `vlm_mode=builtin` when Docling is not installed SHOULD produce an error.
> - `vlm_mode=external` when LiteLLM Router is not configured SHOULD produce a warning.
> - `hybrid_chunker_max_tokens` set to a value exceeding the embedding model's known maximum SHOULD produce a warning.
>
> **Rationale:** Contradictory configuration leads to runtime failures that are difficult to diagnose. Validating at startup surfaces problems before any documents are processed.
>
> **Acceptance Criteria:** Given `vlm_mode=builtin` and Docling not installed, an `IngestionDesignCheck` error is produced with a message identifying the contradiction. Given `hybrid_chunker_max_tokens=2048` with bge-m3 (max 512), a warning is produced. The validation runs during the existing design-check phase before pipeline execution.

---

## 8. State Contract Changes

> **FR-2501** | Priority: MUST
>
> **Description:** `DocumentProcessingState` MUST include a new optional field `docling_document` of type `Optional[Any]` (typed as `Any` to avoid a hard import dependency on `docling-core` at the state definition level). The field MUST default to `None`.
>
> **Rationale:** The Phase 1 pipeline state must carry the `DoclingDocument` from the `structure_detection_node` to the `CleanDocumentStore` persistence step. Using `Optional[Any]` avoids forcing a `docling-core` import in modules that only read state but never touch the document object.
>
> **Acceptance Criteria:** `DocumentProcessingState` TypedDict includes `docling_document: Optional[Any]` with a default of `None`. Existing pipeline nodes that do not reference this field continue to function without modification.

---

> **FR-2503** | Priority: MUST
>
> **Description:** `EmbeddingPipelineState` MUST include a new optional field `docling_document` of type `Optional[Any]`. The field MUST be populated by the orchestrator when reading from `CleanDocumentStore` (if a `.docling.json` file exists for the source key) and MUST be `None` otherwise.
>
> **Rationale:** The Phase 2 pipeline state must carry the `DoclingDocument` from the store boundary to the `chunking_node`. The orchestrator populates this field during Phase 2 initialization, the same way it populates `raw_text` and `cleaned_text` from the store.
>
> **Acceptance Criteria:** `EmbeddingPipelineState` TypedDict includes `docling_document: Optional[Any]`. When the orchestrator reads a source with a `.docling.json` file, the deserialized `DoclingDocument` is set in state. When no `.docling.json` exists, the field is `None`. The `chunking_node` reads this field to select the chunking path.

---

> **FR-2505** | Priority: MUST
>
> **Description:** The `structure` dictionary in `DocumentProcessingState` MUST include a new boolean field `docling_document_available` indicating whether a `DoclingDocument` was successfully obtained and is present in state.
>
> **Rationale:** Downstream routing logic (e.g., skip text_cleaning, skip document_refactoring) needs a lightweight signal to determine the active pipeline path without inspecting the full `DoclingDocument` object. This field provides that signal as part of the existing `structure` dictionary contract.
>
> **Acceptance Criteria:** After `structure_detection_node` completes with a successful Docling parse, `state["structure"]["docling_document_available"]` is `True`. After a failed or disabled Docling parse, it is `False`.

---

## 9. Error Taxonomy & Fallback Matrix

### Error Categories

| Category | Examples | Severity | Expected Behavior |
|----------|----------|----------|-------------------|
| Transient | VLM API timeout, LiteLLM rate limit | Recoverable | Retry with backoff (external VLM); leave placeholder (after retries exhausted) |
| Permanent — Docling | `docling-core` not installed, DoclingDocument serialization schema mismatch | Non-recoverable for Docling path | Fall back to markdown pipeline; log error |
| Permanent — VLM | Unsupported image format, SmolVLM model corrupt | Non-recoverable for that image | Leave placeholder in chunk; log warning |
| Partial | DoclingDocument available but HybridChunker fails | Degraded | Fall back to markdown chunking for that document; log error |
| Configuration | `vlm_mode=builtin` but SmolVLM not downloaded | Preventable | Fail fast at startup via design check |

### Fallback Matrix

| Component | Primary Strategy | Fallback Strategy | Fallback Trigger |
|-----------|-----------------|-------------------|------------------|
| Chunking | HybridChunker (Docling-native) | MarkdownHeaderTextSplitter + RecursiveCharacterTextSplitter | `docling_document` is None in state |
| VLM Enrichment (builtin) | Docling SmolVLM | Leave placeholder unchanged | SmolVLM model unavailable or processing error |
| VLM Enrichment (external) | LiteLLM-routed frontier VLM | Leave placeholder unchanged | API error after retries exhausted |
| DoclingDocument Persistence | Serialize to `.docling.json` | Re-parse source in Phase 2 | `persist_docling_document=false` or serialization failure |
| Text Cleaning (Docling path) | Skip (not needed) | N/A (Docling output is clean) | N/A |
| Document Refactoring (Docling path) | Skip (replaced by section_path) | N/A | N/A |

> **FR-2601** | Priority: MUST
>
> **Description:** When `HybridChunker` raises an exception for a document that has a `DoclingDocument` in state, the `chunking_node` MUST fall back to the markdown-based chunking path for that document. The fallback MUST use the markdown text from state (not re-parse the source file). The `processing_log` MUST record the HybridChunker failure and the fallback activation.
>
> **Rationale:** Supports the fail-safe-over-fail-fast principle. HybridChunker may fail on edge-case documents (e.g., documents with unusual item types not yet supported by the chunker version). Falling back to the proven markdown path ensures the document is still processed.
>
> **Acceptance Criteria:** Given a `DoclingDocument` in state and a `HybridChunker` that raises a `ValueError`, the `chunking_node` produces chunks using the markdown-based path. The `processing_log` contains entries `hybrid_chunker:error` and `chunking:fallback_to_markdown`. The resulting chunks are valid `ProcessedChunk` objects.

---

> **FR-2603** | Priority: MUST
>
> **Description:** When `DoclingDocument` deserialization fails during Phase 2 state initialization (corrupt `.docling.json` file), the orchestrator MUST set `docling_document` to `None` in state and log an error. The document MUST proceed through the fallback markdown chunking path.
>
> **Rationale:** A corrupt serialized document should not prevent the document from being chunked and embedded. The markdown text is always available as a fallback input.
>
> **Acceptance Criteria:** Given a `.docling.json` file containing invalid JSON, the orchestrator sets `docling_document=None`, logs an error with the source key and exception details, and the document proceeds through the markdown chunking path. No unhandled exception propagates.

---

> **FR-2605** | Priority: MUST
>
> **Description:** The system MUST define and maintain a list of Docling-supported input formats. As of Docling 2.82.0, the supported formats are: `.md`, `.pdf`, `.docx`, `.pptx`, `.html`, `.csv`, `.xlsx`, `.asciidoc`, `.latex`, `.image`, `.audio`, `.vtt`, and select XML formats (`xml_uspto`, `xml_jats`, `xml_xbrl`, `mets_gbs`, `json_docling`). Formats NOT in this list (e.g., `.txt`, `.log`, `.json`, `.yaml`, `.ini`, `.cfg`, `.toml`) are considered unsupported by Docling and MUST be routed through the fallback markdown pipeline.
>
> **Rationale:** Docling's `DocumentConverter` rejects input files whose format it does not recognize, raising a "File format not allowed" error. Without an explicit format definition, the system cannot distinguish between a format limitation and a genuine parser failure — leading to incorrect error handling (e.g., halting ingestion for `.txt` files when `docling_strict=True`).
>
> **Acceptance Criteria:** Given a `.txt` file with `enable_docling_parser=True`, the system routes the document through the fallback markdown pipeline. Given a `.pdf` file with `enable_docling_parser=True`, the system routes the document through the Docling-native pipeline. The list of supported formats is testable via `docling.datamodel.base_models.InputFormat` enum values.

---

> **FR-2607** | Priority: MUST
>
> **Description:** When Docling's `DocumentConverter` rejects an input file due to unsupported format ("File format not allowed" or equivalent error), the `structure_detection_node` MUST fall back to the regex/markdown pipeline **regardless of the `docling_strict` setting**. `docling_strict` controls the behavior for real parser failures (corrupt files, internal errors) — it MUST NOT cause a format limitation to halt document processing.
>
> **Rationale:** `docling_strict=True` is intended to enforce parser reliability — "if Docling claims to support this format and still fails, halt so operators investigate." A format that Docling does not support at all is not a parser failure; it is an expected routing decision. Halting on unsupported formats would make the system unable to ingest common file types (`.txt`, `.log`) when `docling_strict=True`, which is the default.
>
> **Acceptance Criteria:** Given a `.txt` file with `enable_docling_parser=True` and `docling_strict=True`, the `structure_detection_node` detects the format error, falls back to regex heuristics, sets `docling_document_available=False`, and does NOT set `should_skip=True`. Given a corrupt `.pdf` file with `docling_strict=True` that causes a non-format parser error, the `structure_detection_node` sets `should_skip=True`. The two error types produce demonstrably different outcomes.

---

## 10. Non-Functional Requirements

> **NFR-2901** | Priority: SHOULD
>
> **Description:** The Docling-native chunking path SHOULD meet the following performance targets for single-document processing:
>
> | Component | Target |
> |-----------|--------|
> | HybridChunker execution (100-page document) | < 2 seconds |
> | DoclingDocument JSON serialization (100-page document) | < 1 second |
> | DoclingDocument JSON deserialization (100-page document) | < 1 second |
> | VLM enrichment per image (builtin SmolVLM) | < 10 seconds |
> | VLM enrichment per image (external via LiteLLM) | < 30 seconds |
> | Unicode normalization per chunk | < 5 milliseconds |
>
> **Rationale:** The redesign adds serialization and deserialization steps that do not exist in the current pipeline. These must not become bottlenecks. VLM latency is dominated by model inference and is acceptable given that it runs post-chunking (not blocking the chunking step).
>
> **Acceptance Criteria:** Measured at P95 on a representative 100-page engineering document. Total chunking time (HybridChunker + metadata assembly) does not exceed 3 seconds. Serialization round-trip (write + read) does not exceed 2 seconds.

---

> **NFR-2903** | Priority: MUST
>
> **Description:** The redesign MUST maintain full backward compatibility with existing ingestion configurations. All existing `IngestionConfig` fields, environment variables, and their default values MUST remain unchanged. New fields MUST have defaults that preserve pre-redesign behavior.
>
> **Rationale:** Operators with existing deployments must not be forced to update their configuration to maintain current behavior. The redesign adds new capabilities behind new configuration flags; it does not change the default behavior of the system.
>
> **Acceptance Criteria:** An `IngestionConfig` instantiated with no arguments produces identical behavior to the pre-redesign configuration. Specifically: `vlm_mode` defaults to `"disabled"` (preserving current behavior where VLM is off by default), `persist_docling_document` defaults to `true`, and `hybrid_chunker_max_tokens` defaults to the embedding model's limit. Existing environment variables are not renamed or removed.

---

> **NFR-2905** | Priority: MUST
>
> **Description:** All configurable thresholds, mode selectors, and parameters introduced by this redesign MUST be externalized to environment variables with documented defaults. Changes MUST take effect on process restart without code changes.
>
> **Rationale:** Hardcoded values require code changes and redeployment to tune. The existing system follows a strict externalized-configuration pattern; new parameters must not deviate.
>
> **Acceptance Criteria:** Every new parameter referenced in this specification (`vlm_mode`, `hybrid_chunker_max_tokens`, `persist_docling_document`) is loaded from an environment variable. Missing variables fall back to documented defaults. No new parameter is hardcoded in source code.

---

> **NFR-2907** | Priority: MUST
>
> **Description:** The Docling-native chunking path MUST produce chunks that are indistinguishable from fallback-path chunks at the `ProcessedChunk` contract level. Downstream nodes (chunk enrichment, metadata generation, cross-reference extraction, embedding storage) MUST NOT require any code changes to process Docling-native chunks.
>
> **Rationale:** The chunking path is an internal implementation detail. Downstream consumers depend on the `ProcessedChunk` contract (text + metadata dictionary). Any contract break would require coordinated changes across multiple pipeline nodes.
>
> **Acceptance Criteria:** Downstream nodes process Docling-native chunks without code changes. The `ProcessedChunk.metadata` dictionary contains all keys expected by chunk enrichment, metadata generation, and embedding storage nodes. No `KeyError` or `TypeError` exceptions occur in downstream nodes when processing Docling-native chunks.

---

> **NFR-2909** | Priority: SHOULD
>
> **Description:** The system SHOULD log sufficient information to diagnose chunking path selection and VLM enrichment decisions for each document. The `processing_log` SHOULD contain entries indicating which chunking path was used (`hybrid_chunker:ok` or `chunking:markdown_fallback`) and which VLM mode was active.
>
> **Rationale:** Operators need to understand why a particular document was chunked via one path versus another, and whether VLM enrichment was applied, to diagnose quality issues and tune configuration.
>
> **Acceptance Criteria:** After processing a Docling-parsed document, the `processing_log` contains `hybrid_chunker:ok`. After processing a non-Docling document, it contains `chunking:markdown_fallback`. When VLM enrichment runs, the log contains `vlm_enrichment:builtin:ok` or `vlm_enrichment:external:ok` (or the corresponding `:error` variant).

---

> **NFR-2911** | Priority: SHOULD
>
> **Description:** The `DoclingDocument` JSON serialization format SHOULD be versioned or include a schema identifier to support future format migrations.
>
> **Rationale:** If `docling-core` changes its serialization format in a future version, stored `.docling.json` files may become unreadable. A version marker allows the system to detect and handle format changes gracefully (e.g., re-parse the source document instead of failing).
>
> **Acceptance Criteria:** The `.docling.json` file contains a top-level `_schema_version` key (or equivalent) identifying the serialization format version. Deserialization checks this version and logs a warning if it does not match the expected version.

---

> **NFR-2913** | Priority: MAY
>
> **Description:** The system MAY support parallel VLM processing of multiple images within a single document's chunk list to reduce total VLM enrichment latency.
>
> **Rationale:** When a document contains many figures, sequential VLM processing becomes the dominant latency contributor. Parallel processing can reduce wall-clock time proportionally to the number of images.
>
> **Acceptance Criteria:** When enabled, VLM enrichment of N images within a single document completes in approximately `max(per_image_latency)` instead of `sum(per_image_latency)`. The parallelism level is bounded by a configurable concurrency limit to prevent resource exhaustion.

---

## 11. System-Level Acceptance Criteria

| Criterion | Threshold | Related Requirements |
|-----------|-----------|---------------------|
| Docling-parsed documents produce structure-aware chunks | 100% of Docling-parsed documents use HybridChunker when DoclingDocument is available | FR-2101, FR-2307 |
| Fallback path produces semantically identical output to pre-redesign | ProcessedChunk output for non-Docling documents is identical except for unicode normalization (FR-2015, deliberate upgrade) | FR-2301, FR-2305 |
| No downstream node changes required | 0 code changes in chunk enrichment, metadata generation, embedding storage nodes | NFR-2907 |
| Table chunks include headers | 100% of multi-chunk tables include header row in every chunk | FR-2107 |
| VLM failure does not block chunking | 0 document-level failures caused by VLM errors | FR-2207 |
| Configuration backward compatibility | 0 existing environment variables renamed or removed | NFR-2903 |
| All chunks fit within embedding model token limit | 0 chunks exceed `hybrid_chunker_max_tokens` (Docling path) | FR-2103 |

---

## 12. Requirements Traceability Matrix

| REQ ID | Section | Priority | Component |
|--------|---------|----------|-----------|
| FR-2001 | 3 | MUST | DoclingDocument Preservation |
| FR-2003 | 3 | MUST | DoclingDocument Preservation |
| FR-2005 | 3 | MUST | DoclingDocument Preservation |
| FR-2007 | 3 | MUST | DoclingDocument Preservation |
| FR-2009 | 3 | SHOULD | DoclingDocument Preservation |
| FR-2011 | 3 | MUST | DoclingDocument Preservation |
| FR-2013 | 3 | MUST | DoclingDocument Preservation |
| FR-2015 | 3 | MUST | DoclingDocument Preservation |
| FR-2101 | 4 | MUST | HybridChunker Integration |
| FR-2103 | 4 | MUST | HybridChunker Integration |
| FR-2105 | 4 | MUST | HybridChunker Integration |
| FR-2107 | 4 | MUST | HybridChunker Integration |
| FR-2109 | 4 | MUST | HybridChunker Integration |
| FR-2111 | 4 | MUST | HybridChunker Integration |
| FR-2113 | 4 | SHOULD | HybridChunker Integration |
| FR-2115 | 4 | SHOULD | HybridChunker Integration |
| FR-2201 | 5 | MUST | VLM Image Enrichment |
| FR-2203 | 5 | MUST | VLM Image Enrichment |
| FR-2205 | 5 | MUST | VLM Image Enrichment |
| FR-2207 | 5 | MUST | VLM Image Enrichment |
| FR-2209 | 5 | SHOULD | VLM Image Enrichment |
| FR-2211 | 5 | SHOULD | VLM Image Enrichment |
| FR-2301 | 6 | MUST | Fallback Pipeline |
| FR-2303 | 6 | MUST | Fallback Pipeline |
| FR-2305 | 6 | MUST | Fallback Pipeline |
| FR-2307 | 6 | MUST | Fallback Pipeline |
| FR-2401 | 7 | MUST | Configuration Surface |
| FR-2403 | 7 | MUST | Configuration Surface |
| FR-2405 | 7 | MUST | Configuration Surface |
| FR-2407 | 7 | MUST | Configuration Surface |
| FR-2409 | 7 | SHOULD | Configuration Surface |
| FR-2501 | 8 | MUST | State Contract Changes |
| FR-2503 | 8 | MUST | State Contract Changes |
| FR-2505 | 8 | MUST | State Contract Changes |
| FR-2601 | 9 | MUST | Error Handling |
| FR-2603 | 9 | MUST | Error Handling |
| FR-2605 | 9 | MUST | Supported Formats |
| FR-2607 | 9 | MUST | Format Error Fallback |
| NFR-2901 | 10 | SHOULD | Non-Functional |
| NFR-2903 | 10 | MUST | Non-Functional |
| NFR-2905 | 10 | MUST | Non-Functional |
| NFR-2907 | 10 | MUST | Non-Functional |
| NFR-2909 | 10 | SHOULD | Non-Functional |
| NFR-2911 | 10 | SHOULD | Non-Functional |
| NFR-2913 | 10 | MAY | Non-Functional |

**Total Requirements: 45**
- MUST: 35
- SHOULD: 9
- MAY: 1

---

## Appendix A. Glossary

| Term | Definition |
|------|-----------|
| bge-m3 | BAAI General Embedding M3 — the local embedding model used by the AION RAG system |
| Docling | IBM's open-source document parsing library that converts PDFs, DOCX, PPTX, and other formats into structured document objects |
| docling-core | The core data model library for Docling, providing the `DoclingDocument` class and serialization utilities |
| HybridChunker | A chunker class in the `docling` package that combines structural awareness (document items as boundaries) with token-aware sizing |
| LiteLLM | A unified LLM API proxy that routes calls to multiple providers (OpenAI, Anthropic, Ollama, etc.) |
| NFC | Unicode Normalization Form C — canonical decomposition followed by canonical composition |
| ProcessedChunk | The system's standard chunk dataclass containing `text` and `metadata` fields |
| semchunk | A token-aware text splitter used internally by HybridChunker for forced splits of oversized items |
| SmolVLM | A small vision-language model integrated into Docling for local image captioning |

---

## Appendix B. Document References

| Document | Purpose |
|----------|---------|
| DOCUMENT_PROCESSING_SPEC.md | Existing Phase 1 spec (FR-100 to FR-589). This redesign modifies behavior of nodes covered by FR-200, FR-400, FR-500 series. |
| EMBEDDING_PIPELINE_SPEC.md | Existing Phase 2 spec (FR-591 to FR-1399). This redesign modifies chunking behavior covered by FR-600 series. |
| INGESTION_PLATFORM_SPEC.md | Cross-cutting platform requirements (re-ingestion, config validation, error handling). |
| 2026-03-27-docling-chunking-pipeline-sketch.md | Brainstorm sketch that produced the approved approach for this specification. |

---

## Appendix C. Implementation Phasing

### Phase 1 — DoclingDocument Preservation & State Changes

**Objective:** Thread the DoclingDocument through the pipeline and persist it in CleanDocumentStore.

| Scope | Requirements |
|-------|-------------|
| DoclingParseResult extension | FR-2001 |
| State contract updates | FR-2501, FR-2503, FR-2505 |
| CleanDocumentStore serialization | FR-2005, FR-2007 |
| Config fields | FR-2403, FR-2405, FR-2407 |
| structure_detection_node propagation | FR-2003 |

**Success criteria:** DoclingDocument survives the Phase 1/Phase 2 boundary via CleanDocumentStore. Existing pipeline behavior is unchanged (DoclingDocument is stored but not yet consumed by chunking).

### Phase 2 — HybridChunker Integration & Node Skipping

**Objective:** Replace markdown-based chunking with HybridChunker for Docling-parsed documents. Skip text_cleaning and document_refactoring.

| Scope | Requirements |
|-------|-------------|
| HybridChunker in chunking_node | FR-2101, FR-2103, FR-2105, FR-2107, FR-2109, FR-2111, FR-2113, FR-2115 |
| Node skipping | FR-2011, FR-2013 |
| Path selection | FR-2307 |
| Fallback preservation | FR-2301, FR-2303, FR-2305 |
| Error handling / fallback | FR-2601, FR-2603, FR-2605, FR-2607 |
| Unicode normalization | FR-2015 |

**Success criteria:** Docling-parsed documents are chunked by HybridChunker with structure-aware, token-aware output. Fallback path produces semantically identical output to pre-redesign (unicode normalization is a deliberate upgrade applied to both paths). text_cleaning and document_refactoring are skipped for Docling documents.

### Phase 3 — VLM Post-Chunking Enrichment

**Objective:** Move VLM processing to post-chunking and support builtin/external modes.

| Scope | Requirements |
|-------|-------------|
| VLM enrichment step | FR-2201, FR-2205, FR-2207 |
| VLM mode config | FR-2203, FR-2401, FR-2405 |
| VLM behavioral controls | FR-2209, FR-2211 |
| Config validation | FR-2409 |

**Success criteria:** VLM enrichment replaces image placeholders in chunks post-chunking. Both builtin and external modes work. VLM failures do not block document processing.

---

## Appendix D. Open Questions

1. **DoclingDocument serialization size:** JSON export of `DoclingDocument` may be large for big documents (potentially exceeding the source document's file size). Implementation should measure typical sizes and consider whether compression (gzip) is warranted for the `.docling.json` file. *(Related: FR-2005, FR-2009)*

2. **Token limit alignment for bge-m3:** The exact maximum input token length for bge-m3 must be verified during implementation. The model card states 8192 tokens, but effective embedding quality may degrade beyond 512 tokens. The `hybrid_chunker_max_tokens` default should be set to the *effective* limit, not the theoretical maximum. *(Related: FR-2103, FR-2403)*

3. **SmolVLM model download trigger:** When `vlm_mode=builtin`, SmolVLM artifacts need to be downloaded. This should happen during `warmup_docling_models()` but currently `with_smolvlm=False` is hardcoded. The implementation must make this conditional on `vlm_mode`. *(Related: FR-2211)*

4. **HybridChunker tokenizer selection:** `HybridChunker` accepts a tokenizer parameter. The implementation must determine whether to pass the bge-m3 tokenizer directly or use HybridChunker's default tokenizer, and verify that token counts match. *(Related: FR-2103)*
