# Document Processing Pipeline — Specification Summary

> **Document type:** Specification summary (Layer 2)
> **Companion spec:** `DOCUMENT_PROCESSING_SPEC.md`
> **Upstream:** DOCUMENT_PROCESSING_SPEC.md
> **Downstream:** DOCUMENT_PROCESSING_DESIGN.md
> **Last updated:** 2026-03-31

---

## 1) System Overview

### Purpose

Engineering organisations accumulate critical knowledge across hundreds of documents in diverse formats, authored over years by different teams. When this knowledge is fragmented and unsearchable, engineers cannot find what they need, and departing staff take contextual understanding with them. The document processing pipeline solves this problem: it transforms raw source documents — regardless of format, structure quality, or authoring style — into clean, structured, human-readable documents suitable for downstream indexing and retrieval. Without it, source documents remain opaque to any search system.

### How It Works

A source document enters the pipeline from the filesystem and passes through up to five sequential stages. First, the document is ingested: its format is detected, its content is extracted into a normalised text representation, and a content fingerprint is computed for change detection. Second, the extracted text is parsed into a hierarchical section tree, with tables, figures, and abbreviation definitions identified and extracted. **The default structure detection provider is Docling**, which converts binary formats (PDF, DOCX, HTML, PPTX, XLSX) into a structured `DoclingDocument` object preserving paragraph boundaries, table structure, and heading hierarchy. Third, if figures were detected, an optional multimodal stage converts each figure image into a text description so that visual content becomes searchable (Docling supports builtin SmolVLM at parse time or external VLM post-chunking). **When Docling successfully parses a document, the fourth and fifth stages are skipped** — the `DoclingDocument` already contains clean, structured content that does not require text cleaning or LLM-based refactoring. For non-Docling paths (Docling disabled or parsing failed with fallback enabled), the fourth stage cleans the text and the fifth optionally restructures paragraphs for self-containedness. The final output is a clean document, its metadata envelope, and (for Docling-parsed documents) a serialized `DoclingDocument` JSON file, all persisted to a dedicated store that serves as the sole input to the downstream embedding phase. The two phases are decoupled at this storage boundary, not connected by an in-memory handoff.

### Tunable Knobs

The pipeline is fully configuration-driven. Operators can control which processing stages are active, toggle the refactoring pass for high-value documents only, select which extraction and detection providers are used, adjust the confidence threshold that flags documents for manual review, define custom boilerplate removal patterns per deployment, manage a shared domain vocabulary for abbreviation handling, and exclude low-value file types from processing. Defaults favour safety: optional stages are off, thresholds are conservative, and unknown formats are rejected rather than guessed.

### Design Rationale

Four principles govern the design. Provider swappability ensures no single external dependency is hardwired — every model, parser, and detection library sits behind a configuration interface. Fail-safe behaviour means a single problematic document or failed model call never halts a batch run; every stage has a deterministic fallback. Context preservation prohibits summarisation or information loss during restructuring; every fact in the source must survive. Configuration-driven behaviour ensures that all stage toggles, thresholds, and provider selections are controlled from one place with runtime overrides, not scattered across code.

### Boundary Semantics

The pipeline's entry point is a source document file path on the local filesystem. Its exit point is a pair of persisted artefacts per document — a clean content file and a metadata envelope — written atomically to the clean document store. The content fingerprint computed at entry propagates downstream for change detection. The pipeline maintains no cross-document state; each document is processed independently. Responsibility ends at persistence — chunking, embedding, indexing, and retrieval belong to the downstream phase.

---

## 2) Scope and Boundaries

**Entry point:** Source document file (PDF, DOCX, PPTX, XLSX, Markdown, HTML, RST, plain text) on local filesystem.

**Exit point:** Clean Markdown document persisted to the Clean Document Store (one `.md` file and one `.meta.json` file per source document).

**In scope:** Document ingestion and processing, structure detection and cleaning, multimodal processing (figure-to-text), text cleaning and normalisation, document refactoring, review tier management, re-ingestion of updated documents, batch processing.

**Out of scope:** Chunking, embedding, vector storage, knowledge graph extraction (Embedding Pipeline), query processing, reranking, answer generation (retrieval layer), user authentication, document authoring, real-time change detection.

---

## 3) Architecture — Pipeline Overview

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
│     Default: Docling DocumentConverter           │
│     Hierarchical section tree · figure/table     │
│     extraction · DoclingDocument production      │
└────────────────────────┬─────────────────────────┘
                         │
                    ┌────┴────┐
                    │ Docling │
                    │success? │
                    └─┬────┬──┘
                 NO   │    │ YES (fast path)
                      ▼    │
┌─────────────────────────────────┐    │
│ [3] MULTIMODAL    [optional]    │    │
│     VLM figure-to-text          │    │
└────────────────┬────────────────┘    │
                 │                     │
                 ▼                     │
┌─────────────────────────────────┐    │
│ [4] TEXT CLEANING [conditional] │    │
│     (skipped if Docling path)   │    │
└────────────────┬────────────────┘    │
                 │                     │
                 ▼                     │
┌─────────────────────────────────┐    │
│ [5] REFACTORING   [optional]    │    │
│     (skipped if Docling path)   │    │
└────────────────┬────────────────┘    │
                 │                     │
                 ▼                     ▼
        ┌────────────────────────────────────────┐
        │        CLEAN DOCUMENT STORE            │
        │  {source_key}.md                       │
        │  {source_key}.meta.json                │
        │  {source_key}.docling.json [if Docling]│
        │  (sole input to Embedding Pipeline)    │
        └────────────────────────────────────────┘
```

Stages marked `[optional]` or `[conditional]` may be skipped. When Docling parsing succeeds, Nodes 4–5 are bypassed — the `DoclingDocument` carries the authoritative structure. See `DOCLING_CHUNKING_SPEC.md` for the full Docling-native subsystem specification. Cross-cutting platform requirements are defined in `INGESTION_PLATFORM_SPEC.md`.

---

## 4) Requirement Framework

**Priority keywords:** MUST / SHALL (absolute requirement), SHOULD / RECOMMENDED (strong default, omit only with justification), MAY / OPTIONAL (truly optional) — per RFC 2119.

**ID conventions:**

| Prefix | Meaning |
|--------|---------|
| **FR-** | Functional Requirement |
| **NFR-** | Non-Functional Requirement |
| **SC-** | Security / Compliance Requirement |

The spec covers **56 functional requirements** across five stages plus the output contract: 53 MUST, 3 SHOULD, 0 MAY.

---

## 5) Functional Requirement Domains

| ID Range | Domain | Coverage |
|----------|--------|----------|
| FR-100–FR-199 | Document Ingestion (13 reqs) | Eight supported input formats, format detection, format-specific extraction rules (slide-order PPTX, sheet-by-sheet XLSX), SHA-256 content hashing, deterministic document IDs, encoding fallback chain, domain vocabulary loading, log file exclusion, local filesystem ingestion, future SharePoint integration |
| FR-200–FR-299 | Structure Detection (10 reqs) | Hierarchical section tree, table extraction with markdown conversion, figure detection with bounding boxes/captions, figure image export, abbreviation auto-detection and vocabulary merge, extraction confidence scoring, low-confidence flagging, swappable detection provider (default: Docling), Docling fast path (skip Nodes 4–5), Docling model/artifact configuration |
| FR-300–FR-399 | Multimodal Processing (7 reqs) | VLM-based figure description, conditional execution, description content requirements (labels, values, relationships), prohibition on speculative content, per-description confidence, swappable VLM provider, failure fallback |
| FR-400–FR-499 | Text Cleaning (5 reqs) | Whitespace normalisation, configurable boilerplate removal, repeated header/footer reduction, figure description integration at original positions, table markdown integration |
| FR-500–FR-599 | Document Refactoring (11 reqs) | Self-contained paragraph restructuring, configurable skip, self-correcting iteration loop, fact-check validation, completeness threshold, content safety constraints (no fact addition/removal), fail-safe fallback, source immutability, mirror artefact model, provenance mapping, citation resolution |
| FR-580–FR-589 | Clean Document Store Contract (8 reqs) | One `.md` and one `.meta.json` per source, metadata envelope schema (with `docling_document_available` flag), full content in Markdown, heading hierarchy preservation, atomic writes, configurable root directory, DoclingDocument persistence (`.docling.json`) |

---

## 6) Non-Functional and Security Themes

- **Performance:** Memory budget constraints, processing time targets per document, batch throughput expectations
- **Reliability:** Stage isolation (single-stage failure does not halt pipeline), LLM/VLM fallback to deterministic alternatives, defensive output parsing, atomic writes preventing partial artefacts
- **Observability:** Structured processing log per document (started/completed/skipped/failed per stage), stage-specific metrics (figure count, confidence score), post-hoc diagnosis without re-runs
- **Configurability:** Startup config validation catching contradictory settings before processing, single configuration system with runtime overrides
- **Security:** Content hash integrity for change detection, no modification of source documents (immutable source principle), provenance metadata linking derived artefacts to originals

---

## 7) Design Principles

- **Swappability over lock-in** — every external dependency sits behind a configuration interface; changing providers requires config changes, not code changes
- **Fail-safe over fail-fast** — failed model calls trigger deterministic fallbacks; a single problematic document never halts a batch run
- **Context preservation over compression** — every value, specification, and procedural step is preserved; restructuring never summarises or removes information
- **Configuration-driven behaviour** — stage enablement, provider selection, thresholds, and patterns are controlled by a single configuration system with runtime overrides

---

## 8) Key Design Decisions

- **DAG orchestration:** The pipeline is a directed acyclic graph enabling conditional routing (skip refactoring, skip VLM) and future parallel branch execution without restructuring the orchestration layer.
- **SHA-256 content hashing:** Source files are hashed before processing. The hash propagates downstream as the primary signal for re-ingestion detection.
- **Deterministic document IDs from file path:** The same file always maps to the same ID across runs, enabling reliable re-ingestion cleanup.
- **Encoding fallback chain:** Four-step fallback (UTF-8 → Latin-1 → CP1252 → replacement) handles legacy engineering document encodings without failing on unknown byte sequences.
- **Domain vocabulary as a shared contract:** A single external vocabulary file spans both pipeline phases — abbreviations auto-detected in structure detection are merged into it, and terms are injected into all downstream prompts.
- **Refactoring as an immutable mirror:** The original source document is never modified. Refactored text is a derived artefact with provenance metadata mapping every span back to its source location.
- **Self-correcting refactoring loop:** Multi-pass iteration with fact-check and completeness check before accepting output, rather than single-pass rewrite.
- **Docling as default structure detection:** Docling produces a rich `DoclingDocument` that preserves paragraph boundaries, table structure, and heading hierarchy. When available, this object is threaded through both pipeline phases — enabling the Embedding Pipeline's `HybridChunker` to perform structure-aware, token-aware chunking instead of heuristic markdown splitting. Documents parsed by Docling skip text cleaning and refactoring (redundant with Docling's output quality), reducing latency and LLM costs.
- **Startup config validation:** Contradictory or incomplete configuration produces a startup error before any documents are processed.

---

## 9) External Dependencies

| Dependency | Role | Swappable |
|------------|------|-----------|
| Graph orchestration framework | DAG execution, conditional routing | Via configuration interface |
| Structure detection library (default: Docling ≥2.82.0) | Document parsing, section tree, figure/table extraction, DoclingDocument production | Yes — provider selectable via config; Docling is the default and recommended provider |
| Vision-language model (VLM) | Figure-to-text descriptions | Yes — provider and model selectable via config |
| Language model (LLM) | Document refactoring | Yes — independent of generation-layer LLM |
| Domain vocabulary file | Abbreviation expansions, compound terms, domain contexts | External YAML — loadable per deployment |

---

## 10) Companion Documents

| Document | Purpose | Relationship |
|----------|---------|-------------|
| DOCUMENT_PROCESSING_SPEC.md | Authoritative requirements specification | Source of truth — this summary distils it |
| DOCLING_CHUNKING_SPEC.md | Docling-native chunking subsystem specification | Specifies DoclingDocument threading, HybridChunker, VLM modes, fallback behavior |
| **DOCUMENT_PROCESSING_SPEC_SUMMARY.md** (this document) | Executive summary | Stakeholder-ready digest |
| DOCUMENT_PROCESSING_DESIGN.md | Task decomposition and code appendix | Next step in the chain |
| DOCUMENT_PROCESSING_IMPLEMENTATION.md | Six-phase implementation plan | Operationalises the design |
| DOCUMENT_PROCESSING_ENGINEERING_GUIDE.md | Post-implementation reference | Documents what was built |
| DOCUMENT_PROCESSING_MODULE_TESTS.md | Phase D white-box test plan | Test specifications |

**Flow:** Spec → **Spec Summary** → Design → Implementation → Engineering Guide → Module Tests

---

## 11) Glossary of Key Abstractions

| Term | Definition |
|------|-----------|
| Clean Document Store | The persistent storage boundary between the Document Processing Pipeline and the Embedding Pipeline. Contains one `.md` and one `.meta.json` per source document, plus an optional `.docling.json` for Docling-parsed documents. |
| Docling | The default structure detection provider. Converts binary formats into structured `DoclingDocument` objects. When Docling parsing succeeds, Nodes 4–5 are skipped (fast path). |
| DoclingDocument | The structured document object produced by Docling, threaded through the pipeline and persisted to the Clean Document Store for the Embedding Pipeline's `HybridChunker`. |
| source_key | A stable, deterministic identifier derived from the source file path, used to name artefacts in the Clean Document Store. |
| Review Tier | A trust classification (Fully/Partially/Self Reviewed) assigned to each document, controlling its visibility weight in retrieval results. |
| Re-ingestion | Processing a previously ingested document again after detecting a content change, including cleanup of old artefacts before writing new ones. |
| VLM | Vision-Language Model — a multimodal model that receives image input and produces text descriptions used to make figures searchable. |
| Deterministic ID | An identifier derived from content or path via cryptographic hashing. The same input always produces the same ID, enabling idempotent re-ingestion. |

---

## 12) Sync Status

- **Spec version aligned to:** Current version of DOCUMENT_PROCESSING_SPEC.md
- **Last synced:** 2026-03-24
- **Sync method:** Manual review
