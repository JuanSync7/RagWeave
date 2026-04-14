<!-- @summary
Concise specification summary for the Visual Embedding Pipeline. Covers system overview,
scope, pipeline architecture, requirement domains, NFR themes, design principles, and
acceptance criteria structure. Aligned to VISUAL_EMBEDDING_SPEC.md v1.0.
@end-summary -->

## 1) Generic System Overview

### Purpose

A document ingestion pipeline that processes only text loses the visual dimension of its source material. Diagrams, spatial layouts, table structures, chart content, and the composite meaning of page design are all discarded when content is reduced to extracted text. For corpora that are inherently visual — technical drawings, slide presentations, engineering schematics — this loss degrades retrieval quality significantly. The visual embedding track addresses this gap by running a second, parallel processing path alongside the existing text path, producing page-level visual representations that capture what cannot be expressed in words alone.

### How It Works

The system activates only when visual processing is enabled at configuration time. When active, the document parsing phase is instructed to rasterize each document page into an in-memory image alongside the usual text extraction — no second parse is needed. These images are produced once and shared.

The visual node enters the pipeline after text embedding is fully complete. It begins by extracting all page images from the parsed document object held in pipeline state. Each image is resized so that its longest dimension does not exceed a configurable limit, preserving aspect ratio. Images whose dimensions already fall within the limit pass through unchanged.

Resized images are then written to object storage under a predictable, document-scoped key pattern. This happens before any inference begins, so that images are persisted even if the inference stage later fails.

With images stored, a vision-language model is loaded using reduced-precision quantization to fit within a constrained GPU memory budget. The model processes images in configurable batches, producing a set of spatial patch vectors for each page — one vector per image region. These patch vectors are averaged together to produce a single representative vector per page, suitable for fast approximate search. Both the averaged vector and the full patch set are retained: the averaged vector is indexed for retrieval, and the full patch set is stored as a data property for exact re-scoring at query time.

After all pages are processed, the model is unloaded and GPU memory is released. Per-page visual records — containing the indexed vector, the patch set, and document metadata — are batch-inserted into a dedicated vector store collection. The node then clears page images from pipeline state to free memory.

When disabled, the node exits in under ten milliseconds with no side effects.

### Tunable Knobs

**Enable/disable toggle:** Turns the entire visual track on or off. When off, no images are generated during parsing, no object storage writes occur, and no model is loaded.

**Inference batch size:** Controls how many images are processed per model call. Smaller batches reduce peak GPU memory usage; larger batches improve throughput on hardware with more headroom.

**Image dimension cap:** Sets the maximum long-edge pixel count before inference. Lower values reduce GPU memory and patch count per page; higher values preserve finer visual detail.

**Image compression quality:** Controls the fidelity-to-size tradeoff for images written to object storage. Higher values produce larger files with fewer compression artifacts.

**Model selection:** Specifies which vision-language model checkpoint to load. Allows operators to adopt newer model versions without code changes, provided the new model is interface-compatible with the inference library.

**Storage collection name:** Sets the name of the vector store collection for visual page records. Useful for environment isolation and multi-tenant deployments.

### Design Rationale

The text track must remain unaffected in both correctness and performance regardless of whether the visual track is active. This drove the decision to place the visual node after text embedding is complete, and to enforce strict state ownership — the visual node writes only to its own state fields.

GPU memory is the binding constraint on the target hardware. The two models cannot coexist in memory simultaneously, so they are loaded and unloaded sequentially. Object storage write-before-inference ordering ensures that page images survive even if model loading subsequently fails, enabling future re-embedding without a full re-parse.

Patch vectors are kept alongside the averaged vector because averaging is lossy — it enables fast candidate retrieval but degrades exact scoring. Storing the full patch set as a data property avoids an explosion of indexed vectors while preserving the option for exact late-interaction re-ranking at query time.

The dependency on the inference library is declared as an optional extras group so that deployments that do not need visual embedding are not burdened with its large transitive dependency tree.

### Boundary Semantics

**Entry point:** The system receives a parsed document object — produced by Phase 1 with page image generation enabled — held in the embedding pipeline state. Page images are available in memory only during the pipeline run; they are not part of the serialized document representation.

**Exit point:** For each successfully processed page, the system produces: a JPEG image in object storage at a predictable key, and a visual page record in the vector store containing the indexed mean vector, the stored patch vectors, and document provenance metadata.

**State handoff:** The visual node updates two state fields: the count of successfully stored visual pages, and a transient page-images list which is cleared before the node exits. All text-track state fields are left byte-identical to their values on entry.

---

## 2) Header

| Field | Value |
|---|---|
| **Companion spec** | `VISUAL_EMBEDDING_SPEC.md` |
| **Spec version** | 1.0 (Draft) |
| **Domain** | Ingestion Pipeline — Visual Embedding Track |
| **Platform** | AION Knowledge Management Platform (RagWeave) |
| **Summary purpose** | Digest of companion spec: intent, scope, structure, key decisions |
| **See also** | Embedding pipeline state, workflow DAG, Weaviate store, VLM enrichment node (Appendix B of spec) |

---

## 3) Scope and Boundaries

**Entry point:** A DoclingDocument object with page images available in memory, produced by Phase 1 with `generate_page_images=True`.

**Exit point:** Page images stored in object storage and visual embeddings (mean-pooled ANN vector + raw patch vectors) stored in a dedicated vector store visual collection.

**In scope:**
- Configuration and validation for the visual embedding track
- Page image extraction from parsed document objects
- Image resizing and JPEG compression for object storage
- Object storage management for page images (store, delete, update)
- Vision-language model loading with 4-bit quantization, batch inference, and unloading
- Mean-pooled vector computation and patch vector retention
- Dedicated vector store collection management (create, insert, delete)
- Pipeline state contract extensions (`visual_stored_count`, `page_images`)
- DAG node registration and ordering
- Per-item and per-page error handling and fault isolation
- Format-specific handling for PDF, PPTX, DOCX, and standalone image files
- Optional dependency declaration and runtime dependency checks

**Out of scope:**
- Retrieval-side dual-track query merging and MaxSim scoring at query time
- Multimodal query handling (text query embedded via vision-language model for visual search)
- PPTX slide-boundary text chunking
- Web console UI for visual search results
- Vision-language model fine-tuning or domain adaptation
- Multi-GPU model parallelism
- Vector-store-native MaxSim scoring (application-side only)
- Page image OCR or text extraction from page images
- Benchmark or evaluation framework for visual retrieval quality
- Retrieval-side visual re-ranking or result fusion

---

## 4) Architecture / Pipeline Overview

```
Phase 1: Document parse (page image generation enabled)
    |
    v
DoclingDocument (page images in memory)
    |
    v
Phase 2: Embedding Pipeline DAG
    |
    |-- document_storage
    |-- chunking
    |-- vlm_enrichment
    |-- chunk_enrichment
    |-- metadata_generation
    |-- cross_reference_extraction  [conditional]
    |-- knowledge_graph_extraction
    |-- quality_validation
    |-- embedding_storage           ... TEXT TRACK COMPLETE
    |
    +-- visual_embedding (NEW NODE)
    |       |
    |       |  1. Short-circuit if disabled / no document / no pages
    |       |  2. Extract page images from parsed document
    |       |  3. Resize images (long-edge cap)
    |       |  4. Store JPEG images to object storage
    |       |  5. Load vision-language model (4-bit quantization)
    |       |  6. Batch-infer pages → (mean vector, patch vectors) per page
    |       |  7. Delete prior visual records (update mode)
    |       |  8. Batch-insert visual page records into vector store
    |       |  9. Unload model, release GPU memory
    |       | 10. Clear page images from state
    |
    +-- knowledge_graph_storage     [conditional]
    |
    END

Dual-track relationship:
    DoclingDocument
    /             \
TEXT TRACK         VISUAL TRACK
(existing)         (new)
Text chunking      Page image extraction
Text model         Vision-language model
1024-dim vectors   128-dim patch vectors (N per page)
Text collection    Visual collection
Chunk-level        Page-level retrieval (future)

Both tracks share document_id — cross-track linking at retrieval time.
```

---

## 5) Requirement Framework

- **Priority keywords:** RFC 2119 — MUST (non-conformant without it), SHOULD (recommended, may be omitted with justification), MAY (optional at implementor's discretion).
- **Requirement format:** Each requirement includes Description, Rationale, and Acceptance Criteria.
- **ID convention:** `FR-xxx` for functional requirements, `NFR-xxx` for non-functional requirements.
- **Total requirements:** 48 (MUST: 38, SHOULD: 10, MAY: 0).

---

## 6) Functional Requirement Domains

| Domain | ID Range | Coverage |
|---|---|---|
| **Configuration & Initialization** | FR-101 to FR-109 | Enable/disable flag, all config parameters with defaults, environment variable mapping, startup validation |
| **Page Image Extraction** | FR-201 to FR-205 | DoclingDocument image extraction, aspect-ratio-preserving resize, zero-page handling, dimension metadata recording, color mode normalization |
| **Vision-Language Model Embedding** | FR-301 to FR-307 | Model loading with quantization, batch inference, mean-pooled vector computation, patch vector retention, model unloading, progress logging, per-page failure handling |
| **Object Storage (Page Images)** | FR-401 to FR-405 | Key pattern and naming convention, JPEG compression, store-before-infer ordering, existing client reuse, delete-before-update semantics |
| **Vector Store Visual Collection** | FR-501 to FR-507 | Dedicated collection lifecycle, idempotent creation, per-page object schema, indexed mean vector, patch vectors as data property, delete-by-source-key, batch insertion |
| **Pipeline Integration** | FR-601 to FR-606 | DAG node placement and ordering, state contract extension, short-circuit logic, node name registry, ingestion result extension, page image state cleanup |
| **Format-Specific Handling** | FR-701 to FR-705 | PDF, PPTX, DOCX support, standalone image file support, format-specific failure handling |
| **Error Handling & Resilience** | FR-801 to FR-806 | Per-item error isolation, model load failure as fatal, text-track state isolation, MinIO failure non-fatal, Weaviate batch failure reporting, dependency pre-check |

---

## 7) Non-Functional and Security Themes

- **GPU memory budget:** Peak VRAM usage during inference must remain within a defined bound on the target hardware class.
- **Per-page throughput:** Average seconds-per-page must remain within an upper bound for documents up to 100 pages.
- **Zero-overhead when disabled:** Short-circuit execution time is bounded at under 10 milliseconds with no model imports, GPU allocation, or storage I/O.
- **Storage footprint:** Per-page JPEG sizes are bounded at typical values for default quality and dimension settings.
- **Full configurability:** All behavioral parameters must be adjustable via typed config and environment variables without code changes.
- **Optional dependency isolation:** Inference library dependencies are declared optional; the application runs without them when visual embedding is disabled.
- **Idempotency:** Re-ingesting the same document produces the same visual output with no duplicates.
- **Embedding determinism:** Given identical input and configuration, patch vectors are reproducible within floating-point tolerance.
- **Backward compatibility:** No breaking changes to existing text pipeline API, state contract, or behavior.
- **Code maintainability:** The model adapter follows existing patterns; the inference library is isolated behind a stable adapter interface.

---

## 8) Design Principles

1. **Zero impact when disabled.** When the visual track is off, pipeline behavior is byte-identical to the pre-visual baseline with no overhead.
2. **Track isolation.** The visual node reads shared state but writes exclusively to its own state fields and storage targets. Text track results are never modified.
3. **Follow existing patterns.** The visual node uses the same structural conventions as existing pipeline nodes: short-circuit on disable, per-item try/except, processing log entries.
4. **Fail gracefully.** Individual page failures do not halt the pipeline. Model load failure is surfaced as a fatal error, not a retry loop. Partial success is a well-defined outcome.
5. **Configuration-driven.** All behavioral knobs are typed configuration fields with environment variable overrides. No hardcoded behavior.

---

## 9) Key Decisions

- **Sequential, not parallel, track execution.** GPU memory constraints on the target hardware prevent both models from coexisting. The visual node runs after text embedding completes, not concurrently.
- **Object storage write before inference.** Page images are persisted before model loading begins, so they survive inference failures and enable future re-embedding without re-parsing.
- **Mean-pooled vector for ANN + patch vectors as data property.** Averaging produces a single indexable vector for fast candidate retrieval; the full patch set is stored as a JSON property for exact re-scoring. This avoids the indexed-vector-per-patch explosion.
- **Quantized model loading.** 4-bit quantization reduces the model memory footprint to approximately a quarter of its full-precision size, making it compatible with constrained GPU memory alongside other runtime allocations.
- **Delete-before-insert on re-ingestion.** Both object storage images and vector store records are deleted by document identifier before new records are written, preventing stale data accumulation.
- **Optional extras dependency group.** Inference library dependencies are heavy and not needed by all deployments. Declaring them optional keeps the base installation lean.

---

## 10) Acceptance and Evaluation

The spec defines 8 system-level acceptance scenarios:

| Scenario | What it validates |
|---|---|
| End-to-end PDF ingestion | Full visual track produces correct page count in object storage and vector store; text track unaffected |
| End-to-end PPTX ingestion | Slide-as-page handling and correct page numbering |
| Disabled track zero-impact | No writes, no model load, node completes in under 10ms; text results identical to baseline |
| Re-ingestion cleanup | Update mode replaces old records with new; no duplicate pages |
| Partial failure resilience | Pipeline continues after per-page failure; text track unaffected; failed page logged |
| VRAM management | Model loaded only during visual node; memory returns to pre-load levels after; peak within bound |
| Configuration validation | Contradictory configuration rejected at startup before any document processing |
| Pure image file | Single-image document produces exactly one visual page record |

No separate evaluation or feedback framework is defined in this spec.

---

## 11) External Dependencies

**Required (when visual embedding enabled):**
- Vision-language model inference library (`colpali-engine` extras group)
- Model quantization library (`bitsandbytes` extras group)
- GPU with sufficient VRAM for quantized model plus inference buffers

**Required (always — existing infrastructure):**
- Object storage service (MinIO-compatible) — page image persistence
- Vector store (Weaviate v4) — visual page record indexing and retrieval
- Document parser with page image generation capability (Docling)

**Downstream contract (not in scope for this spec):**
- Retrieval pipeline: must consume the mean vector for ANN search and the patch vector property for MaxSim re-scoring
- Vector store visual collection schema: must remain stable for retrieval queries to function

---

## 12) Companion Documents

This summary is a digest of **VISUAL_EMBEDDING_SPEC.md**. It captures intent, scope, structure, and key decisions — it is not a replacement for the normative requirements in the companion spec.

The companion spec includes a full Requirements Traceability Matrix (Section 13), a Glossary (Appendix A), source file references (Appendix B), a 7-phase implementation breakdown (Appendix C), and an Open Questions log (Appendix D). Readers needing individual requirement rationale, acceptance criteria, or phasing detail should consult the spec directly.

---

## 13) Sync Status

| Field | Value |
|---|---|
| **Aligned to spec version** | 1.0 (Draft) |
| **Summary written** | 2026-04-10 |
| **Summary author** | Claude (claude-sonnet-4-6) |
