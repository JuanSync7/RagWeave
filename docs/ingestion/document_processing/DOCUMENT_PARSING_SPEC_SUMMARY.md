# Document Parsing Abstraction — Specification Summary

> **Document type:** Specification summary (Layer 2)
> **Upstream:** DOCUMENT_PARSING_SPEC.md
> **Last updated:** 2026-04-15

---

## 1) System Overview

### Purpose

When a document ingestion pipeline is tightly coupled to a single parsing backend, three problems emerge. There is no alternative when the parser fails or is unavailable. Internal types from the parser leak into pipeline state, storage formats, and downstream node signatures, making it impossible to swap parsers without rewriting the pipeline. And source files that are not traditional documents — source code files and plain text — receive no specialised treatment, producing low-quality chunks that pollute search results.

### Pipeline Flow

The parsing abstraction introduces a pluggable interface with three parser strategy families. A document parser handles complex binary formats that require optical character recognition, layout analysis, table detection, and structural extraction. A code parser uses abstract syntax tree traversal to produce one chunk per function or class, preserving the semantic units that make code searchable. A plain text parser handles files that are already readable text, applying heading-aware splitting with minimal overhead. All three families implement the same two-method interface — parse and chunk — and produce output through a unified contract. The parse method returns a lightweight result containing markdown text, headings, a figure detection flag, and page count. The chunk method returns a list of chunk objects with section path, heading, heading level, chunk index, and an extensible metadata dictionary. Parser-internal types never cross the boundary; they remain encapsulated inside the parser instance between parse and chunk calls.

At pipeline startup, a router selects the correct parser strategy based on file extension. A registry maps strategy names to concrete implementations, ensuring no pipeline node imports a specific parser class directly. An optional configuration override can force a specific strategy for all files. A separate chunker override allows operators to replace any parser's native chunking with a shared markdown-based chunker as an escape hatch.

### Tunable Knobs

Operators can configure parser strategy selection (automatic by extension or forced globally), chunker mode (native or markdown fallback), the vision-language model mode for figure processing, and per-parser settings passed through the ingestion configuration. All settings are validated at startup with fail-fast behaviour on invalid or conflicting values.

### Design Rationale

Four principles govern the design. Encapsulation over leakage means parser-internal types never appear in pipeline state, storage, or downstream nodes. Parser-internal chunking means each parser leverages its own structural knowledge for chunking, rather than reconstructing structure from markdown. Fail fast, not fail silent means a missing parser raises an immediate error rather than silently degrading to raw text. Strategy, not conditional means parser selection uses a registry and strategy pattern, not cascading conditional branches.

### Boundary Semantics

The abstraction's entry point is a source file path and ingestion configuration. Its exit point is a parse result and a list of chunks, both conforming to parser-agnostic contracts. The abstraction does not own embedding, storage, knowledge graph extraction, or retrieval — those are downstream concerns. It also does not own vision-language model enrichment implementation, though it enforces the validation guard that prevents conflicting enrichment configurations.

---

## 2) Scope and Boundaries

**Entry point:** Source document file path and `IngestionConfig`.

**Exit point:** `ParseResult` (markdown, headings, has_figures, page_count) and `list[Chunk]` (text, section_path, heading, heading_level, chunk_index, extra_metadata).

**In scope:** Abstract parser interface, unified ParseResult/Chunk contracts, three parser strategy families (document, code, plain text), extension-based routing, parser registry, chunker override configuration, VLM mode validation guard.

**Out of scope:** Embedding and vector storage, VLM enrichment implementation, KG extraction logic, parser performance benchmarking, tree-sitter grammar installation, LLM-based code-to-natural-language translation.

---

## 3) Parser Interface Contract (FR-3200–FR-3207)

The abstract parser interface (FR-3200) declares `parse()` and `chunk()` methods. `ParseResult` (FR-3201) carries four fields — `markdown`, `headings`, `has_figures`, `page_count` — with no parser-internal types. `Chunk` (FR-3202) carries six fields including an `extra_metadata` dict for parser-specific richness. When no parser is available for a file, the system raises a runtime error immediately (FR-3203) rather than silently falling back to raw text. Each parser validates its dependencies at startup via `ensure_ready()` (FR-3204). Parser-internal state (e.g., DoclingDocument, tree-sitter Tree) is encapsulated and never exposed via ParseResult, pipeline state, or storage (FR-3205). Parsers use a per-document instance lifecycle (FR-3206) to prevent state leakage between documents. Expensive one-time initialisation is separated into an optional `warmup()` method (FR-3207).

Key decision: the `DoclingDocument` leakage in the current system is the motivating example. Eliminating it from pipeline state and storage enables true parser swappability.

---

## 4) Document Parser Strategy (FR-3220–FR-3224)

The document parser handles PDF, DOCX, PPTX, and image formats (FR-3220). The Docling implementation (FR-3221) wraps `DocumentConverter` for parsing and `HybridChunker` for chunking, storing `DoclingDocument` internally. A DeepDoc implementation (FR-3222) is optional, validating the pluggable interface. Chunk heading metadata (FR-3223) is populated from the parser's native heading hierarchy — this is a primary advantage over markdown-based chunking. The parser honours the `vlm_mode` setting (FR-3224) to control whether figure descriptions are embedded at parse time or deferred to post-chunking enrichment.

---

## 5) Code Parser Strategy (FR-3250–FR-3256)

The code parser uses tree-sitter as a universal backend (FR-3250) supporting 19+ languages with automatic extension detection (FR-3251). AST-guided chunking (FR-3252) produces one chunk per top-level function or class — function bodies are never split across chunks. Rich metadata (FR-3253) includes language, function_name, class_name, docstring, imports, and decorators. Deterministic KG extraction (FR-3254) derives import, inheritance, and call relationships directly from the AST without LLM calls, producing exact call graphs and import trees. Code is stored as raw source (FR-3255) — natural language explanation is a generation-phase concern. Code files produce a valid ParseResult with the source formatted as a fenced markdown code block (FR-3256).

Key decision: tree-sitter provides universal language support through a single library rather than maintaining language-specific parsers. Deterministic KG extraction from AST is 100% precise and avoids wasteful LLM calls.

---

## 6) Plain Text Parser Strategy (FR-3280–FR-3282)

Handles Markdown, plain text, reStructuredText, and HTML (FR-3280). Processing is minimal (FR-3281) — read the file, convert to markdown if needed, extract headings, detect image references. No models or external services are invoked. Chunking (FR-3282) uses a heading-aware markdown splitter that respects chunk size/overlap configuration and treats table blocks as atomic units. This is the same shared chunker available as a fallback for all parser types.

---

## 7) Parser Selection and Routing (FR-3300–FR-3303)

Automatic extension-based routing (FR-3300) maps files to the three strategy families with case-insensitive matching. An optional configuration override (FR-3301) forces a specific strategy globally. Unrecognised extensions fall back to the plain text parser with a logged warning (FR-3302). A parser registry (FR-3303) maps strategy names to concrete classes — pipeline nodes obtain parsers from the registry, never by importing concrete classes directly. Adding a new parser requires only registration and extension mapping.

---

## 8) Chunker Override Configuration (FR-3320–FR-3323)

The `chunker` setting (FR-3320) supports `"native"` (default, uses parser's own chunking) and `"markdown"` (forces the shared markdown chunker). The markdown chunker (FR-3321) is extracted as a shared utility that accepts a ParseResult and produces Chunks with heading-derived section paths. Invalid values are rejected at startup (FR-3322). A warning is logged when markdown override is active (FR-3323), noting the trade-off: markdown chunking produces less heading metadata than native chunking for parsers with rich hierarchies.

---

## 9) VLM Mode Validation (FR-3340–FR-3342)

The mutual exclusion guard (FR-3340) prevents `vlm_mode="builtin"` and `enable_multimodal_processing=true` from both being active, which would cause every figure to be processed by two independent VLM pipelines. The check integrates with the existing `IngestionDesignCheck` framework (FR-3341). When `vlm_mode="external"` coexists with multimodal processing (FR-3342), an informational log clarifies that both are valid but serve different pipeline stages.

---

## 10) Requirement Summary

The spec covers **34 functional requirements** across seven sections:

| ID Range | Domain | Count |
|----------|--------|-------|
| FR-3200–FR-3207 | Parser Interface Contract | 8 |
| FR-3220–FR-3224 | Document Parser Strategy | 5 |
| FR-3250–FR-3256 | Code Parser Strategy | 7 |
| FR-3280–FR-3282 | Plain Text Parser Strategy | 3 |
| FR-3300–FR-3303 | Parser Selection and Routing | 4 |
| FR-3320–FR-3323 | Chunker Override Configuration | 4 |
| FR-3340–FR-3342 | VLM Mode Validation | 3 |

Priority breakdown: 25 MUST, 4 SHOULD, 1 MAY.

---

## 11) Key Design Decisions

- **Three-strategy model:** Document, code, and plain text parser families cover all input types with specialised handling rather than forcing everything through a document parser.
- **tree-sitter as universal code parser:** One library for 100+ languages eliminates the need for language-specific parsers.
- **AST-guided chunking for code:** Functions and classes are never split mid-body, preserving the semantic units that make code retrieval useful.
- **Deterministic KG extraction from AST:** Import, inheritance, and call relationships are derived structurally with 100% precision, no LLM required.
- **DoclingDocument encapsulation:** The parser-internal type is confined to the parser class, breaking the current coupling between Docling internals and pipeline state, storage, and downstream nodes.
- **VLM mutual exclusion guard:** Startup validation prevents the silent double-processing bug where two independent VLM pipelines describe the same figures.
- **Markdown chunker as shared escape hatch:** Available to all parser types as a fallback when native chunking produces unexpected results.

---

## 12) Companion Documents

| Document | Purpose |
|----------|---------|
| DOCUMENT_PARSING_SPEC.md | Authoritative requirements specification — source of truth |
| DOCUMENT_PARSING_SPEC_SUMMARY.md (this document) | Stakeholder-ready digest |
| DOCUMENT_PROCESSING_SPEC.md | Phase 1 pipeline requirements (structure detection, cleaning, refactoring) |
| DOCLING_CHUNKING_SPEC.md | Docling-native chunking subsystem (HybridChunker, VLM enrichment) |
| EMBEDDING_PIPELINE_SPEC.md | Phase 2 pipeline requirements (embedding, KG, storage) |
| INGESTION_PLATFORM_SPEC.md | Cross-cutting platform requirements |

---

## 13) Sync Status

- **Spec version aligned to:** DOCUMENT_PARSING_SPEC.md v1.0.0
- **Last synced:** 2026-04-15
- **Sync method:** Manual review
