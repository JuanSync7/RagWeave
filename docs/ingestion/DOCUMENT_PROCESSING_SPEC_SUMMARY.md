# Document Processing Pipeline — Specification Summary

**Companion document to:** `DOCUMENT_PROCESSING_SPEC.md` (v1.0.0)
**Purpose:** Concise digest combining the conceptual pipeline overview and project requirements summary for stakeholders, reviewers, and implementers.
**See also:** `EMBEDDING_PIPELINE_SPEC_SUMMARY.md`, `INGESTION_PLATFORM_SPEC.md`, `DOCUMENT_PROCESSING_IMPLEMENTATION.md`

---

## 1. Document Processing Pipeline — Conceptual Overview

> **Scope:** This section describes what the Document Processing Pipeline is and how it works in generic, platform-level terms. It contains no requirement IDs and no project-specific technology choices. It is the authoritative source for this pipeline's conceptual description and is designed to be aggregated with equivalent sections from other components into a top-down platform overview.

This phase is the first of two ingestion phases. Its responsibility is to transform raw source documents — regardless of format, structure quality, or authoring style — into clean, structured, self-contained Markdown documents and persist them to a dedicated **Clean Document Store**. The Clean Document Store is a format-normalised mirror of the source document corpus: every source file has a corresponding clean Markdown representation that preserves the full content of the original without its formatting artefacts, extraction noise, or context-dependent references. This store is the sole input to the Embedding Pipeline — the two phases are decoupled at this storage boundary, not connected by an in-memory handoff.

The decoupling at the Clean Document Store has two practical consequences. First, the Embedding Pipeline can be re-run independently — for example, when switching to a different embedding model and re-indexing the entire corpus — without re-running document processing, because the clean Markdown documents are already available. Second, the clean documents are human-readable and inspectable: operators can audit what the pipeline extracted and cleaned from any source document before it enters the vector index.

The pipeline processes one document at a time through a sequence of five stages, implemented as nodes in a directed acyclic graph (DAG). Two of the five nodes are conditional: multimodal processing fires only when figures are detected, and document refactoring is skippable via configuration. The mandatory baseline — ingestion, structure detection, and text cleaning — is sufficient for plain-text and well-structured documents. The optional stages activate progressively as document complexity and infrastructure allow.

Four design principles govern this phase:

- **Swappability over lock-in:** Every external dependency — document parser, structure detection library, vision-language model — is behind a configuration interface. Changing providers requires configuration changes, not code changes.
- **Fail-safe over fail-fast:** When an LLM or VLM call fails, the pipeline records the failure and continues rather than halting. A single problematic document or figure never stops a batch run.
- **Context preservation over compression:** The pipeline preserves every value, specification, and procedural step in the source document. No information is summarised or removed during restructuring.
- **Configuration-driven behaviour:** Which stages are enabled, which detection library is used, which boilerplate patterns are stripped — all controlled by a single configuration system with runtime overrides.

The five stages of this phase are:

```
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
    │  Markdown mirror of source      │
    │  corpus — persisted to disk,    │
    │  human-readable, auditable      │
    └─────────────────────────────────┘
    (read by Embedding Pipeline)
```

### 1.1 Document Ingestion and Parsing (Stages 1–2)

These two stages form the entry point of the pipeline. **Stage 1 (Document Ingestion)** reads the source file from the local filesystem, detects its format from the file extension, converts it to a normalised text representation using a format-specific extractor, and computes a cryptographic content hash of the source file. Supported formats are PDF, Word (.docx), PowerPoint (.pptx), Excel (.xlsx), Markdown, HTML, reStructuredText, and plain text. PowerPoint files are extracted with slide order preserved, including text frames, table cells, and speaker notes — a critical source of knowledge that is lost if only the slide body is extracted. Excel files are extracted sheet by sheet, with headers, table structure, and named ranges preserved as markdown. The content hash is passed to the Embedding Pipeline where it is used by the re-ingestion mechanism to detect whether a document has changed since it was last processed.

**Stage 2 (Structure Detection)** parses the extracted text into a hierarchical section tree that mirrors the document's heading structure. Figures and tables are identified and extracted: tables are converted to markdown representations preserving all headers and rows; figures are detected with their bounding boxes, captions, and surrounding paragraph context. The stage also auto-detects abbreviation definitions in the document body — for example, "Natural Language Processing (NLP)" or any inline definition of the form "Term (ABBREV)" — and merges them with the global domain vocabulary so that downstream stages can resolve domain-specific terms. An extraction confidence score is computed for each document based on section tree depth, table completeness, and text coherence. Documents below a configurable confidence threshold are flagged for manual review but continue through the pipeline.

Several aspects of these stages are configurable to optimise coverage and quality:

- **Format-specific extractor:** Each input format has its own extraction handler. Adding a new format requires implementing a defined extractor interface and registering it in configuration, without modifying any existing code.
- **Structure detection provider:** The library used to detect document structure is swappable via configuration. Different providers have different strengths across document types — switching requires no code changes.
- **Confidence threshold:** The threshold below which a document is flagged for review is configurable. Raising it catches more borderline documents; lowering it reduces review queue volume.
- **Domain vocabulary file:** A configurable external dictionary maps abbreviations to their expansions, domain contexts, related terms, and compound multi-word terms specific to the organisation's knowledge domain. The vocabulary serves two roles across the full ingestion system: document-local abbreviation definitions discovered in Stage 2 are merged into it, and its terms are injected into every LLM prompt across both pipeline phases to ensure consistent abbreviation handling from document refactoring through to knowledge graph extraction. Domain-aware disambiguation is supported — the same abbreviation can expand differently depending on the surrounding document's domain classification. Compound terms in the vocabulary additionally inform the chunking stage in the Embedding Pipeline, preventing multi-word domain terms from being split across chunk boundaries.
- **File type exclusion:** High-volume, low-semantic-density file types — such as build logs, binary assets, or generated output files — can be configured for exclusion. Excluding these prevents noise from polluting the vector space.

### 1.2 Content Processing and Refactoring (Stages 3–5)

These three stages clean the extracted content and optionally restructure it for better downstream retrieval. **Stage 3 (Multimodal Processing)** is conditional and executes only when figures were detected in Stage 2. It passes each figure image to a vision-language model (VLM) and receives a text description capturing the diagram type, visible labels and numerical values, and key relationships shown in the figure. This makes visual content — block diagrams, flowcharts, process diagrams, architectural views — fully searchable through text embeddings, which would otherwise be invisible to the retrieval system. The VLM is instructed to describe only what is visible and never to speculate or infer content not present in the figure, because in a knowledge-critical environment, fabricated details in a figure description could propagate into incorrect conclusions or decisions. If a VLM call fails, the figure is recorded without a description rather than halting the pipeline.

**Stage 4 (Text Cleaning)** normalises whitespace, removes boilerplate artefacts — page headers, footers, confidentiality notices, stray page numbers — using configurable patterns, and integrates the VLM-generated figure descriptions into the text body at the positions where each figure appeared. The result is a single, clean text document where visual content has been translated to text and positioned in its original document context.

**Stage 5 (Document Refactoring)** is optional and skippable via configuration. When enabled, it uses a language model to restructure paragraphs for self-containedness — resolving implicit references (e.g., "the threshold established above" → the specific value), expanding abbreviations that were ambiguous without surrounding context, and reorganising content so that each paragraph can be understood in isolation without its surrounding section. This addresses a fundamental problem with naive chunking: isolated paragraphs lose meaning when they rely on context from elsewhere in the document (e.g., a pronoun or relative reference without a referent, or an abbreviation defined several pages earlier). Refactoring is expensive and increases processing time significantly, so it is designed as a configurable stage that can be applied selectively to high-value documents.

Configurable aspects of these stages include:

- **VLM provider and model selection:** The VLM used for figure description is swappable via configuration. Each provider is accessed through the same interface, so switching requires only a configuration change.
- **VLM confidence threshold:** Descriptions below a configurable confidence threshold can be discarded or flagged, preventing low-quality VLM outputs from entering the search index.
- **Boilerplate patterns:** The list of patterns used to detect and remove boilerplate is configurable. Custom patterns can be added per deployment without code changes.
- **Refactoring enablement:** Stage 5 is enabled or disabled via a configuration flag. It can also be applied only to specific document types or review tiers.
- **LLM provider for refactoring:** The language model used for document refactoring is swappable via configuration and independent of the LLM used for generation in the retrieval layer.

### 1.3 Error Handling and Observability

The Document Processing Pipeline is designed to fail safely — a single problematic document or failed LLM call never halts a batch run. Four mechanisms enforce this:

**Stage isolation:** Every stage in the DAG is independently error-contained. If a stage throws an exception — for example, a corrupted table during text cleaning — the error is captured and logged, and the document proceeds to the next stage with whatever state it had before the failure. A document can complete the pipeline with partial results: a document that fails refactoring is still cleaned and persisted to the Clean Document Store with its original (unrefactored) text.

**LLM fallbacks:** Every stage that calls an LLM or VLM has a deterministic fallback that produces a lower-quality but usable result when the primary call fails, times out, or returns unparseable output:

| Stage | Primary | Fallback |
|-------|---------|----------|
| Multimodal Processing | VLM image-to-text description | Figure recorded without description |
| Document Refactoring | Multi-pass LLM restructuring | Original text persisted unchanged |

**Defensive output parsing:** LLM calls that return structured output are parsed through a defensive parser that strips common LLM formatting artefacts before attempting to parse. On parse failure, the stage activates its deterministic fallback rather than crashing or producing corrupt state.

**Structured processing log:** The pipeline records a timestamped log entry for every stage — started, completed, skipped, or failed — including stage name, status, and stage-specific metrics such as figure count or extraction confidence score. This log enables post-hoc diagnosis of why a particular document produced low-quality output without requiring a full re-run.

Before any document is processed, the pipeline validates its configuration at startup. Contradictory settings — for example, refactoring enabled but no LLM provider configured — produce a startup error that halts the run before wasting compute.

---

## 2. System Architecture

The pipeline is orchestrated as a LangGraph `StateGraph` (DAG). All five nodes share a single `DocumentProcessingState` TypedDict; each node reads from upstream-populated fields and writes only to its own designated output fields.

```
Source Document (filesystem path)
    │
    ▼
┌──────────────────────────────────────────────────┐
│ [1] DOCUMENT INGESTION                           │
│     Format detection · extraction · SHA-256 hash │
│     Deterministic source_key ID generation       │
└────────────────────────┬─────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────┐
│ [2] STRUCTURE DETECTION                          │
│     Hierarchical section tree · figure/table     │
│     extraction · abbreviation merge · confidence │
└────────────────────────┬─────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────┐
│ [3] MULTIMODAL PROCESSING            [optional]  │
│     VLM figure-to-text (fires if figures > 0)    │
└────────────────────────┬─────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────┐
│ [4] TEXT CLEANING                                │
│     Whitespace norm · boilerplate removal        │
│     Figure/table description integration         │
└────────────────────────┬─────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────┐
│ [5] DOCUMENT REFACTORING             [optional]  │
│     Self-contained paragraph restructuring       │
│     Self-correcting iteration · fact-check       │
└────────────────────────┬─────────────────────────┘
                         │
                         ▼
        ┌────────────────────────────────────┐
        │        CLEAN DOCUMENT STORE        │
        │  {source_key}.md                   │
        │  {source_key}.meta.json            │
        │  (sole input to Embedding Pipeline)│
        └────────────────────────────────────┘
```

Stages marked `[optional]` are conditional: multimodal processing fires only when figures are detected; refactoring is skippable via `enable_refactoring` config flag. Cross-cutting platform requirements (re-ingestion detection, review tier management, batch processing, configuration schema, error handling framework, NFRs) are defined in `INGESTION_PLATFORM_SPEC.md`.

---

## 3. Requirements Digest

The spec covers **53 requirements** across five stages plus the Clean Document Store output contract: 50 MUST, 3 SHOULD, 0 MAY.

### Document Ingestion (`FR-100` to `FR-199` — 13 requirements)

Covers the eight supported input formats (PDF, DOCX, PPTX, XLSX, Markdown, HTML, RST, plain text), format detection and normalisation, format-specific extraction rules (slide-order PPTX, sheet-by-sheet XLSX), SHA-256 content hashing for re-ingestion detection, deterministic document ID generation, encoding fallback chain (UTF-8 → Latin-1 → CP1252 → replacement), domain vocabulary loading, log file exclusion, local filesystem ingestion, and future SharePoint integration (SHOULD).

### Structure Detection (`FR-200` to `FR-299` — 8 requirements)

Covers hierarchical section tree parsing, table extraction with markdown conversion, figure detection with bounding boxes and captions, figure image export for VLM processing, abbreviation auto-detection and vocabulary merge, extraction confidence scoring, low-confidence document flagging, and swappable detection provider.

### Multimodal Processing (`FR-300` to `FR-399` — 7 requirements)

Covers VLM-based figure description generation, conditional execution (fires only if figures detected), description content requirements (labels, values, relationships), prohibition on speculative content, per-description confidence score, swappable VLM provider, and VLM failure fallback to empty description.

### Text Cleaning (`FR-400` to `FR-499` — 5 requirements)

Covers whitespace normalisation, configurable boilerplate removal via patterns, repeated header/footer reduction, VLM figure description integration at original figure positions, and table markdown integration.

### Document Refactoring (`FR-500` to `FR-599` — 11 requirements)

Covers self-contained paragraph restructuring, configurable skip flag, self-correcting iteration loop, fact-check validation, completeness check with 80% threshold, content safety constraints (no addition or removal of facts), fail-safe fallback to original text, immutability of source document, mirror artefact model, provenance mapping to original source spans, and citation resolution to original source URI.

### Clean Document Store Output Contract (`FR-580` to `FR-589` — 7 requirements)

Covers one `.md` file and one `.meta.json` per source document, metadata envelope schema (source path, hash, version, timestamp, stage results), full processed content in the Markdown file, heading hierarchy preservation, atomic write behaviour (no partial writes on failure), and configurable root directory.

---

## 4. Key Design Decisions

- **DAG orchestration via graph framework:** The pipeline is a LangGraph `StateGraph`, enabling conditional routing (skip refactoring, skip VLM) and future parallel branch execution without restructuring the orchestration layer.
- **SHA-256 content hashing:** Source files are hashed before processing. The hash propagates to the Embedding Pipeline as the primary signal for re-ingestion detection — identical hashes mean skip, different hash means reprocess.
- **Deterministic document IDs from file path:** Document identifiers are derived from the source file path, not generated randomly. This ensures the same file always maps to the same ID across runs, enabling reliable re-ingestion cleanup.
- **Encoding fallback chain:** Text extraction uses a four-step fallback (UTF-8 → Latin-1 → CP1252 → UTF-8 with replacement) to handle the full range of legacy engineering document encodings without failing on unknown byte sequences.
- **Domain vocabulary as a shared YAML contract:** A single external vocabulary file spans both pipeline phases. Abbreviations auto-detected in Stage 2 are merged into it; its terms are injected into all downstream LLM prompts through to knowledge graph extraction in the Embedding Pipeline.
- **Refactoring as an immutable mirror:** The original source document is never modified. Refactored text is a derived retrieval representation stored as a separate artefact. Provenance metadata maps every refactored span back to its source location, so citations always resolve to the original.
- **Self-correcting refactoring loop:** Document refactoring uses a multi-pass iteration with integrated fact-check (no facts added or removed) and completeness check (≥ 80% content preserved) before accepting the refactored output, rather than a single-pass rewrite.
- **Startup config validation before processing:** Contradictory or incomplete configuration produces a startup error before any documents are processed, preventing wasted compute and partial-batch failures.

---

## 5. Glossary of Key Abstractions

| Term | Definition |
|------|-----------|
| `Clean Document Store` | The persistent storage boundary between the Document Processing Pipeline and the Embedding Pipeline. Contains one `.md` and one `.meta.json` per source document. |
| `source_key` | A stable, deterministic identifier derived from the source file path, used to name artefacts in the Clean Document Store. |
| `DocumentProcessingState` | The TypedDict that flows through all pipeline stages. Each stage reads from upstream-populated fields and writes to its own designated fields. |
| `PipelineConfig` | The master configuration object. Controls stage enablement, provider selection, thresholds, and runtime overrides for a pipeline run. |
| Node function | Pipeline stages are implemented as plain functions (e.g., `def text_cleaning_node(state: DocumentProcessingState) -> dict`), not as subclasses of an abstract base class. Each function enforces the stage contract: shared state input, stage-scoped output, independent error handling. |
| `Review Tier` | A trust classification (`FULLY_REVIEWED`, `PARTIALLY_REVIEWED`, `SELF_REVIEWED`) assigned to each document, controlling its visibility weight in retrieval results. |
| `Re-ingestion` | Processing a previously ingested document again after detecting a content change, including cleanup of the old Clean Document Store artefacts before writing the new ones. |
| `VLM` | Vision-Language Model — a multimodal model that receives image input and produces text descriptions used to make figures searchable. |
| `Deterministic ID` | An identifier derived from content or path via cryptographic hashing. The same input always produces the same ID, enabling idempotent re-ingestion. |
| `domain_vocabulary.yaml` | The external vocabulary file providing abbreviation expansions, domain contexts, related terms, and compound multi-word terms specific to the organisation's knowledge domain. |

---

## 6. Companion Documents

| Document | Role |
|----------|------|
| `DOCUMENT_PROCESSING_SPEC.md` | Authoritative requirements baseline — FR-101 through FR-587 |
| `EMBEDDING_PIPELINE_SPEC.md` | Phase 2 functional requirements — chunking, enrichment, embedding, storage |
| `INGESTION_PLATFORM_SPEC.md` | Cross-cutting platform requirements — re-ingestion, config schema, error handling, NFRs |
| `DOCUMENT_PROCESSING_IMPLEMENTATION.md` | Phased implementation plan for Document Processing phase (FR-101–FR-587) |
| `EMBEDDING_PIPELINE_IMPLEMENTATION.md` | Phased implementation plan for Embedding Pipeline phase (FR-591–FR-1304) |
| `INGESTION_PIPELINE_ENGINEERING_GUIDE.md` | Practical developer guide — architecture, extension steps, troubleshooting |
| `INGESTION_NEW_ENGINEER_ONBOARDING_CHECKLIST.md` | Quick-start checklist for new engineers |
| `DOCUMENT_PROCESSING_SPEC_SUMMARY.md` (this document) | Concise requirements digest combining conceptual overview and project-specific summary |

---

## 7. Sync Status

Aligned to `DOCUMENT_PROCESSING_SPEC.md` v1.0.0 as of 2026-03-20.

Supersedes: `RAG_embedding_pipeline_spec_summary.md` (Document Processing sections only).
