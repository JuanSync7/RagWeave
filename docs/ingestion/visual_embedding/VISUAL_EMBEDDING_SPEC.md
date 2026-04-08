# Visual Embedding Pipeline -- Formal Requirements Specification

**AION Knowledge Management Platform**
Version: 1.0 | Status: Draft | Domain: Ingestion Pipeline -- Visual Embedding Track

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-04-01 | AI Assistant | Initial draft -- 48 requirements for dual-track visual embedding pipeline |

> **Document intent:** This is a normative requirements/specification document for the **visual embedding track** of the ingestion pipeline. The visual track adds page-level ColQwen2 multi-vector embeddings alongside the existing text embedding track. For the text embedding pipeline, see the existing embedding pipeline documentation. For retrieval-side dual-track query merging and MaxSim scoring, see a future retrieval specification (out of scope for this document).

---

## 1. Scope & Definitions

### 1.1 Problem Statement

The existing RAG ingestion pipeline produces text-only embeddings (BGE-M3, 1024-dim dense vectors per chunk). This representation loses visual information present in document pages: diagrams, tables, figures, slide layouts, charts, and spatial arrangements. Documents rich in visual content (engineering specifications, slide decks, technical drawings) are poorly served by text-only retrieval.

The visual embedding track adds a second parallel output to the ingestion pipeline: page-level visual embeddings produced by ColQwen2, a vision-language model that generates multi-vector patch representations of each page image. These enable late-interaction retrieval over visual document content without modifying the existing text track.

### 1.2 Boundary

- **Entry point:** A DoclingDocument object with page images available in memory, produced by Phase 1 (document processing pipeline) with `generate_page_images=True`.
- **Exit point:** Page images stored in MinIO and visual embeddings (mean-pooled ANN vector + raw patch vectors) stored in a dedicated Weaviate visual collection.

The visual embedding track is a new node within the existing Phase 2 Embedding Pipeline LangGraph DAG. It runs after the text track completes (after `embedding_storage`) and before `knowledge_graph_storage`.

### 1.3 Terminology

| Term | Definition |
|------|-----------|
| **Visual Embedding Track** | The new pipeline path that processes page images through ColQwen2 to produce visual embeddings, running alongside the existing text embedding track |
| **Text Embedding Track** | The existing pipeline path that chunks text and embeds via BGE-M3 into the text Weaviate collection |
| **ColQwen2** | A vision-language model (Qwen2-VL-2B backbone) that produces multi-vector patch embeddings for document page images, enabling late-interaction retrieval |
| **Patch Vector** | A 128-dimensional float32 vector representing a spatial patch of a page image; ColQwen2 produces 500-1200 patch vectors per page |
| **Mean-Pooled Vector** | A single 128-dimensional float32 vector computed by averaging all patch vectors for a page; used for approximate nearest neighbor (ANN) search |
| **Late-Interaction Scoring (MaxSim)** | A retrieval scoring method that computes the maximum similarity between each query patch vector and all document patch vectors, then sums across query patches |
| **Page Image** | A rasterized image of a single document page, produced by Docling during Phase 1 conversion |
| **4-bit Quantization** | A model compression technique (via bitsandbytes) that reduces model weights from 16-bit to 4-bit, reducing VRAM from ~8GB to ~2GB |
| **Visual Collection** | The dedicated Weaviate collection storing per-page visual embedding objects (distinct from the text chunk collection) |
| **colpali-engine** | The reference Python library for ColPali/ColQwen2 inference, handling image preprocessing, model loading, and patch vector extraction |
| **DoclingDocument** | The native Docling document object produced by Phase 1 parsing, containing structured text, metadata, and optionally page images |
| **ANN** | Approximate Nearest Neighbor search -- fast vector similarity lookup used by Weaviate for candidate retrieval |

### 1.4 Priority Levels

This document uses RFC 2119 language:

- **MUST** -- Absolute requirement. The system is non-conformant without it.
- **SHOULD** -- Recommended. May be omitted only with documented justification.
- **MAY** -- Optional. Included at the implementor's discretion.

### 1.5 Requirement Format

Each requirement follows this structure:

> **FR-xxx** | Priority: MUST/SHOULD/MAY
>
> **Description:** What the system shall do.
>
> **Rationale:** Why this requirement exists.
>
> **Acceptance Criteria:** How to verify conformance.

FR-xxx for functional requirements, NFR-xxx for non-functional requirements.

### 1.6 Assumptions & Constraints

| Assumption/Constraint | Description |
|---|---|
| Hardware | RTX 2060 with 6GB VRAM is the target deployment GPU |
| VRAM budget | BGE-M3 (~1.5GB) and ColQwen2 at 4-bit (~2GB) cannot coexist simultaneously; sequential loading is required |
| Docling availability | Page images are only available when `enable_docling_parser=True` and `generate_page_images=True` in Phase 1 |
| In-memory page images | Page images from `ConversionResult.pages` are available in memory only during the pipeline run; they are not persisted in DoclingDocument JSON serialization |
| Sequential DAG | The LangGraph embedding pipeline DAG executes nodes sequentially; true parallelism between text and visual tracks is not supported due to VRAM constraints |
| Single GPU | The system operates on a single GPU; multi-GPU model parallelism is not supported |
| Weaviate v4 | The target Weaviate version supports named vectors but does not natively support MaxSim scoring |
| colpali-engine | The ColQwen2 inference library (`colpali-engine`) is the reference implementation and handles image preprocessing and patch vector extraction |

### 1.7 Design Principles

1. **Zero impact when disabled.** When `enable_visual_embedding=False`, the pipeline behaves identically to the current system with no performance overhead and no behavioral changes.
2. **Track isolation.** The visual track reads shared state (document_id, docling_document) but writes only to its own state fields (visual_stored_count) and its own storage targets (visual Weaviate collection, MinIO pages prefix). Text track results are never modified by the visual track.
3. **Follow existing patterns.** The visual embedding node follows the same structural patterns as existing nodes (short-circuit when disabled, per-item try/except, processing_log entries).
4. **Fail gracefully.** Individual page failures do not halt the pipeline. Model load failure is fatal and surfaced at validation time. Partial success (some pages embedded, others skipped) is a well-defined outcome.
5. **Configuration-driven.** All behavioral knobs (model name, batch size, image quality, collection name) are exposed as typed configuration fields with environment variable overrides.

### 1.8 Out of Scope

The following are explicitly out of scope for this specification:

- Retrieval-side dual-track query merging and MaxSim scoring at query time
- Multimodal query handling (text query embedded via ColQwen2 for visual search)
- PPTX slide-boundary text chunking (separate pipeline concern)
- Web console UI for visual search results
- ColQwen2 fine-tuning or domain adaptation
- Multi-GPU model parallelism
- Weaviate-native MaxSim scoring (application-side only)
- Page image OCR or text extraction from page images (Docling handles this in Phase 1)
- Benchmark or evaluation framework for visual retrieval quality
- Retrieval-side visual re-ranking or result fusion

---

## 2. System Overview

### 2.1 Architecture Diagram

```text
Phase 1: parse_with_docling(generate_page_images=True)
    |
    v
DoclingDocument (with page images in memory)
    |
    +-------> Phase 2: Embedding Pipeline DAG
                |
                |-- document_storage
                |      |
                |      v
                |-- chunking
                |      |
                |      v
                |-- vlm_enrichment
                |      |
                |      v
                |-- chunk_enrichment
                |      |
                |      v
                |-- metadata_generation
                |      |
                |      v
                |-- cross_reference_extraction (conditional)
                |      |
                |      v
                |-- knowledge_graph_extraction
                |      |
                |      v
                |-- quality_validation
                |      |
                |      v
                |-- embedding_storage ........... TEXT TRACK COMPLETE
                |      |
                |      v
                |-- visual_embedding (NEW NODE)
                |      |
                |      | 1. Short-circuit if disabled or no docling_document
                |      | 2. Extract page images from docling_document
                |      | 3. Resize pages to page_image_max_dimension
                |      | 4. Store JPEG pages to MinIO: pages/{doc_id}/{page}.jpg
                |      | 5. Load ColQwen2 (4-bit quantization)
                |      | 6. Batch-embed pages -> (mean_vector, patch_vectors)
                |      | 7. Delete prior visual objects (update mode)
                |      | 8. Store visual embeddings to Weaviate visual collection
                |      | 9. Unload ColQwen2, release VRAM
                |      |
                |      v
                |-- knowledge_graph_storage (conditional)
                |      |
                |      v
                +-- END
```

### 2.2 Data Flow Summary

| Stage | Input | Output | Storage Target |
|-------|-------|--------|----------------|
| Page Image Extraction | DoclingDocument with page images | List of resized PIL.Image objects with page metadata | (in-memory) |
| MinIO Page Storage | Resized PIL.Image objects, document_id | JPEG files at `pages/{document_id}/{page_number}.jpg` | MinIO |
| ColQwen2 Embedding | Resized PIL.Image objects (batched) | Per-page: mean_vector (128-dim float32) + patch_vectors (list of 128-dim float32) | (in-memory) |
| Weaviate Visual Storage | Per-page embedding data + document metadata | Visual page objects in Weaviate visual collection | Weaviate |

### 2.3 Dual-Track Relationship

```text
                      DoclingDocument
                      /             \
                     /               \
          TEXT TRACK                   VISUAL TRACK
          (existing)                  (new)
              |                           |
    HybridChunker/MD split         Page image extraction
              |                           |
    BGE-M3 embedding               ColQwen2 patch embedding
    (1024-dim per chunk)           (128-dim x N patches per page)
              |                           |
    Weaviate text collection       Weaviate visual collection
    (target_collection)            (visual_target_collection)
              |                           |
    Chunk-level retrieval          Page-level retrieval (future)
```

Both tracks share the same `document_id`, enabling cross-track linking at retrieval time. Both tracks are produced from a single Docling parse pass -- no re-parsing.

---

## 3. Configuration & Initialization

> **FR-101** | Priority: MUST
>
> **Description:** The system MUST provide an `enable_visual_embedding` boolean configuration flag that controls whether the visual embedding track is active. When set to `False`, the visual embedding node MUST short-circuit immediately with zero processing overhead.
>
> **Rationale:** The visual track adds significant compute cost (ColQwen2 inference, MinIO storage) and introduces a new dependency (colpali-engine). Operators who do not need visual retrieval must be able to disable it completely without side effects on the existing text pipeline.
>
> **Acceptance Criteria:** With `enable_visual_embedding=False`: the visual_embedding node returns immediately, no ColQwen2 model is loaded, no MinIO page images are stored, no Weaviate visual objects are created, and `visual_stored_count` is set to 0. The text track produces identical results regardless of this flag's value.

> **FR-102** | Priority: MUST
>
> **Description:** The system MUST expose `visual_target_collection` as a configurable string specifying the Weaviate collection name for visual page embeddings. The default value MUST be `"RAGVisualPages"`.
>
> **Rationale:** Operators may need to use different visual collection names for multi-tenant deployments or testing environments. Hardcoding the collection name would prevent environment isolation.
>
> **Acceptance Criteria:** Setting `RAG_INGESTION_VISUAL_TARGET_COLLECTION=TestVisual` causes visual embeddings to be stored in the `TestVisual` collection instead of `RAGVisualPages`. The text collection name is unaffected.

> **FR-103** | Priority: MUST
>
> **Description:** The system MUST expose `colqwen_model_name` as a configurable string specifying the HuggingFace model identifier for the ColQwen2 model. The default value MUST be `"vidore/colqwen2-v1.0"`.
>
> **Rationale:** Newer ColQwen2 model versions may be released with improved quality. Operators must be able to switch models without code changes, provided the new model is API-compatible with colpali-engine.
>
> **Acceptance Criteria:** Setting `RAG_INGESTION_COLQWEN_MODEL=vidore/colqwen2-v1.5` causes the pipeline to load and use the v1.5 model. Model loading fails with a clear error message if the specified model is not available locally or downloadable.

> **FR-104** | Priority: MUST
>
> **Description:** The system MUST expose `colqwen_batch_size` as a configurable integer specifying the number of page images processed per ColQwen2 inference batch. The default value MUST be `4`. The value MUST be constrained to the range 1-32.
>
> **Rationale:** Processing all pages of a large document at once may exceed GPU memory. Batch size controls peak VRAM usage during inference. A value of 4 keeps inference within the 2GB VRAM budget on RTX 2060 at 4-bit quantization.
>
> **Acceptance Criteria:** A 20-page document with `colqwen_batch_size=4` is processed in 5 inference batches. Setting `colqwen_batch_size=0` or `colqwen_batch_size=33` is rejected during configuration validation with a descriptive error message.

> **FR-105** | Priority: MUST
>
> **Description:** The system MUST expose `page_image_quality` as a configurable integer specifying the JPEG compression quality for page images stored in MinIO. The default value MUST be `85`. The value MUST be constrained to the range 1-100.
>
> **Rationale:** JPEG quality controls the tradeoff between file size and image fidelity. Quality 85 provides approximately 5-10x compression over PNG for typical document pages (50-200KB per page) while preserving sufficient visual detail for both retrieval and human inspection.
>
> **Acceptance Criteria:** Page images stored in MinIO use the configured JPEG quality. Setting `page_image_quality=0` or `page_image_quality=101` is rejected during configuration validation.

> **FR-106** | Priority: MUST
>
> **Description:** The system MUST expose `page_image_max_dimension` as a configurable integer specifying the maximum pixel dimension (long edge) for page images before ColQwen2 inference and MinIO storage. The default value MUST be `1024`. The value MUST be constrained to the range 256-4096.
>
> **Rationale:** Higher-resolution page images produce more patch vectors per page (increasing VRAM usage and storage size) without proportional retrieval quality gains. Resizing to 1024px long edge bounds patch count to approximately 500-1200 while preserving enough visual detail for retrieval. The minimum of 256 ensures sufficient resolution for text and diagram readability.
>
> **Acceptance Criteria:** A page image with original dimensions 2480x3508 (A4 at 300 DPI) is resized so that the long edge is 1024px (resulting in approximately 723x1024), preserving aspect ratio. Setting `page_image_max_dimension=200` is rejected during configuration validation.

> **FR-107** | Priority: MUST
>
> **Description:** The system MUST derive a `generate_page_images` flag from the `enable_visual_embedding` configuration. When `enable_visual_embedding=True`, the `generate_page_images` parameter MUST be set to `True` in the Phase 1 `parse_with_docling()` call. When `enable_visual_embedding=False`, `generate_page_images` MUST remain `False`.
>
> **Rationale:** Docling's page image generation adds memory overhead and processing time during Phase 1 conversion. This overhead is only justified when the visual track is enabled. Gating `generate_page_images` behind `enable_visual_embedding` ensures zero overhead when the visual track is disabled.
>
> **Acceptance Criteria:** With `enable_visual_embedding=True`, the DoclingDocument produced by Phase 1 contains page images accessible via the conversion result's pages object. With `enable_visual_embedding=False`, no page images are generated and the Phase 1 behavior is identical to the current baseline.

> **FR-108** | Priority: MUST
>
> **Description:** The system MUST validate visual embedding configuration at pipeline startup (within the `verify_core_design()` function). Validation MUST check: (a) if `enable_visual_embedding=True`, then `enable_docling_parser` MUST also be `True`; (b) `colqwen_batch_size` is within range 1-32; (c) `page_image_quality` is within range 1-100; (d) `page_image_max_dimension` is within range 256-4096. Validation failures MUST be surfaced as fatal errors that prevent pipeline execution.
>
> **Rationale:** Visual embedding requires Docling for page image generation. Contradictory configurations (visual embedding enabled but Docling disabled) would cause silent failures at runtime. Fail-fast validation at startup catches these issues before any documents are processed.
>
> **Acceptance Criteria:** Setting `enable_visual_embedding=True` with `enable_docling_parser=False` produces a fatal validation error with a message indicating that Docling is required for visual embedding. All range violations produce descriptive error messages identifying the invalid parameter and its valid range.

> **FR-109** | Priority: MUST
>
> **Description:** The system MUST expose all visual embedding configuration parameters as environment variables following the existing `RAG_INGESTION_*` naming convention. The mapping MUST be: `RAG_INGESTION_ENABLE_VISUAL_EMBEDDING`, `RAG_INGESTION_VISUAL_TARGET_COLLECTION`, `RAG_INGESTION_COLQWEN_MODEL`, `RAG_INGESTION_COLQWEN_BATCH_SIZE`, `RAG_INGESTION_PAGE_IMAGE_QUALITY`, `RAG_INGESTION_PAGE_IMAGE_MAX_DIMENSION`.
>
> **Rationale:** All existing ingestion configuration is controlled via environment variables. Visual embedding configuration must follow the same pattern for consistency and to support container-based deployments where environment variables are the primary configuration mechanism.
>
> **Acceptance Criteria:** Each listed environment variable, when set, overrides the corresponding default value in the ingestion configuration. Unsetting all visual environment variables results in the default values being used. Environment variables are read at application startup, not at per-document processing time.

---

## 4. Page Image Extraction

> **FR-201** | Priority: MUST
>
> **Description:** The visual embedding node MUST extract page images from the `docling_document` field in the pipeline state. Each page image MUST be a PIL.Image object associated with a page number (1-indexed).
>
> **Rationale:** Page images are the input to ColQwen2 embedding. The DoclingDocument produced by Phase 1 contains page images in memory when `generate_page_images=True` was set during conversion. Extracting these images is the first step of the visual track.
>
> **Acceptance Criteria:** For a 10-page PDF document parsed with `generate_page_images=True`, the visual embedding node extracts exactly 10 PIL.Image objects, each associated with the correct page number (1 through 10).

> **FR-202** | Priority: MUST
>
> **Description:** The system MUST resize each extracted page image so that the longer edge does not exceed `page_image_max_dimension` pixels. Resizing MUST preserve the original aspect ratio. Images whose longer edge is already within the limit MUST NOT be resized.
>
> **Rationale:** Resizing bounds the number of patch vectors produced by ColQwen2 per page, controlling VRAM usage and storage size. Aspect ratio preservation prevents distortion that would degrade visual embedding quality.
>
> **Acceptance Criteria:** A page image with dimensions 2480x3508 and `page_image_max_dimension=1024` is resized to approximately 723x1024. A page image with dimensions 800x600 and `page_image_max_dimension=1024` is not resized. The aspect ratio of the resized image matches the original within a 1-pixel rounding tolerance.

> **FR-203** | Priority: MUST
>
> **Description:** The system MUST handle documents with zero extractable page images by short-circuiting the visual embedding node. The node MUST set `visual_stored_count=0`, log a `visual_embedding:no_pages` entry to `processing_log`, and return without error.
>
> **Rationale:** Some document types (empty files, unsupported formats, conversion failures) may produce a DoclingDocument with no page images. This is a valid outcome, not an error condition. The text track may still have produced valid chunks from the document's text content.
>
> **Acceptance Criteria:** An empty document (0 pages) produces `visual_stored_count=0` and a `visual_embedding:no_pages` log entry. No ColQwen2 model is loaded. No MinIO or Weaviate operations are performed. The pipeline continues to subsequent nodes without error.

> **FR-204** | Priority: MUST
>
> **Description:** The system MUST record each extracted page image's original dimensions (width and height in pixels) as metadata. This metadata MUST be stored alongside the visual embedding in the Weaviate visual collection.
>
> **Rationale:** Page dimensions are needed for coordinate-based retrieval features (future scope) and for diagnostics when debugging visual embedding quality. Recording dimensions at extraction time avoids the need to re-read page images from MinIO.
>
> **Acceptance Criteria:** Each visual page object in Weaviate contains `page_width_px` and `page_height_px` integer fields reflecting the original page dimensions before resizing.

> **FR-205** | Priority: SHOULD
>
> **Description:** The system SHOULD convert page images to RGB color mode before processing. Page images in RGBA, grayscale, or other color modes SHOULD be converted to RGB to ensure compatibility with ColQwen2's expected input format.
>
> **Rationale:** ColQwen2 expects RGB images as input. Docling may produce page images in RGBA mode (for PDFs with transparency) or other color modes. Failing to convert could cause inference errors or incorrect embeddings.
>
> **Acceptance Criteria:** A page image in RGBA mode is converted to RGB before being passed to ColQwen2. The conversion does not raise exceptions. The resulting image has exactly 3 color channels.

---

## 5. ColQwen2 Embedding

> **FR-301** | Priority: MUST
>
> **Description:** The system MUST load the ColQwen2 model specified by `colqwen_model_name` using the colpali-engine library with 4-bit quantization via bitsandbytes. Model loading MUST occur at the start of the visual embedding node, after page images have been extracted and stored in MinIO.
>
> **Rationale:** 4-bit quantization reduces ColQwen2's VRAM footprint from approximately 8GB (16-bit) to approximately 2GB, which is within the RTX 2060's 6GB budget. Loading at node entry (not at pipeline startup) ensures VRAM is available for BGE-M3 during the text track.
>
> **Acceptance Criteria:** The ColQwen2 model is loaded with 4-bit quantization. GPU memory usage after loading is approximately 2GB (within 500MB tolerance). The model is ready for inference after loading completes.

> **FR-302** | Priority: MUST
>
> **Description:** The system MUST process page images through ColQwen2 in batches of `colqwen_batch_size` pages. Each batch inference call MUST produce, for each page in the batch, a set of 128-dimensional float32 patch vectors.
>
> **Rationale:** Batch processing bounds peak VRAM usage during inference. Processing all pages of a large document at once could exceed GPU memory even at 4-bit quantization. The batch size parameter allows operators to tune the tradeoff between throughput and memory usage.
>
> **Acceptance Criteria:** A 20-page document with `colqwen_batch_size=4` produces 5 batch inference calls. Each call processes exactly 4 pages (except the last batch which may contain fewer). Each page produces between 500 and 1200 patch vectors of dimension 128.

> **FR-303** | Priority: MUST
>
> **Description:** The system MUST compute a mean-pooled vector for each page by averaging all patch vectors produced by ColQwen2 for that page. The mean-pooled vector MUST be a single 128-dimensional float32 vector.
>
> **Rationale:** Weaviate's ANN index operates on single vectors, not multi-vector sets. Mean pooling produces a single representative vector per page that can be used for fast approximate retrieval. This is the standard approach used in production ColPali deployments.
>
> **Acceptance Criteria:** Given a page with 800 patch vectors of dimension 128, the mean-pooled vector is a single 128-dimensional vector where each dimension is the arithmetic mean of the corresponding dimension across all 800 patch vectors. The mean-pooled vector has dtype float32.

> **FR-304** | Priority: MUST
>
> **Description:** The system MUST retain the full set of raw patch vectors for each page alongside the mean-pooled vector. The patch vectors MUST be serializable as a JSON array (list of lists of floats) for storage in a Weaviate property field.
>
> **Rationale:** Mean pooling is a lossy approximation. The raw patch vectors are needed for post-retrieval MaxSim re-scoring, which provides exact late-interaction scoring on shortlisted candidates. Storing patch vectors as JSON in a Weaviate property field (not as named vectors) avoids per-patch vector explosion in the ANN index.
>
> **Acceptance Criteria:** For each page, the full patch vector array is retained in memory after mean pooling. The patch vectors can be serialized to JSON (list of lists of float) without loss of precision beyond float32 representation. The serialized size for a page with 1000 patches of dimension 128 is approximately 500KB-1MB.

> **FR-305** | Priority: MUST
>
> **Description:** The system MUST unload the ColQwen2 model and release GPU memory after all pages have been processed. The VRAM freed MUST be sufficient for subsequent pipeline nodes or future model loads.
>
> **Rationale:** On a 6GB RTX 2060, ColQwen2 at 4-bit occupies approximately 2GB of VRAM. If the model is not unloaded, subsequent GPU operations (including future document processing) may fail due to insufficient VRAM. The visual embedding node is the only consumer of ColQwen2.
>
> **Acceptance Criteria:** After the visual embedding node completes, GPU memory usage returns to pre-ColQwen2-load levels (within 200MB tolerance, accounting for CUDA cache). The ColQwen2 model object is no longer referenced and is eligible for garbage collection.

> **FR-306** | Priority: SHOULD
>
> **Description:** The system SHOULD log inference progress at regular intervals during ColQwen2 batch processing. For documents with more than 10 pages, progress SHOULD be logged at approximately 10% completion intervals.
>
> **Rationale:** ColQwen2 inference on large documents (50-500+ pages) can take minutes. Without progress logging, operators have no visibility into processing status and cannot distinguish a slow-but-working pipeline from a hung one.
>
> **Acceptance Criteria:** A 100-page document produces progress log entries at approximately every 10 pages (10%, 20%, ..., 100%). A 5-page document does not produce intermediate progress logs (only start and completion).

> **FR-307** | Priority: MUST
>
> **Description:** The system MUST handle per-page inference failures gracefully. If ColQwen2 fails to embed a specific page (due to image corruption, unexpected dimensions, or inference errors), the system MUST log a warning identifying the failed page, skip that page, and continue processing remaining pages.
>
> **Rationale:** A single corrupted or unusual page should not prevent the remaining pages from being embedded. Partial coverage (N-1 out of N pages embedded) is strictly better than zero coverage.
>
> **Acceptance Criteria:** A document where page 5 of 10 causes a ColQwen2 inference error produces: visual embeddings for pages 1-4 and 6-10, a warning log entry identifying page 5 as failed, and `visual_stored_count=9`. The pipeline does not raise an exception.

---

## 6. MinIO Page Image Storage

> **FR-401** | Priority: MUST
>
> **Description:** The system MUST store each resized page image as a JPEG file in MinIO under the key pattern `pages/{document_id}/{page_number}.jpg`. The `document_id` MUST be the same identifier used by the text track's document storage node. Page numbers MUST be 1-indexed and zero-padded to 4 digits (e.g., `0001.jpg`, `0042.jpg`).
>
> **Rationale:** The key pattern enables efficient prefix-based listing (`pages/{document_id}/`) and cleanup. Using the same `document_id` as the text track enables cross-track linking. Zero-padding ensures correct lexicographic ordering.
>
> **Acceptance Criteria:** A 10-page document with `document_id=abc-123` produces MinIO objects at keys `pages/abc-123/0001.jpg` through `pages/abc-123/0010.jpg`. Each object is a valid JPEG file.

> **FR-402** | Priority: MUST
>
> **Description:** The system MUST compress page images using JPEG encoding at the quality level specified by `page_image_quality`. The JPEG encoding MUST use the resized image (after FR-202 resizing), not the original full-resolution image.
>
> **Rationale:** JPEG compression controls storage size. At quality 85, typical document page images are 50-200KB. Storing uncompressed or PNG images would be 5-10x larger with negligible benefit for retrieval or visual inspection.
>
> **Acceptance Criteria:** Each stored page image is a valid JPEG file. File sizes for typical document pages at quality 85 are between 30KB and 300KB. The JPEG quality matches the configured `page_image_quality` value.

> **FR-403** | Priority: MUST
>
> **Description:** The system MUST store page images in MinIO before starting ColQwen2 inference. Page image storage and ColQwen2 embedding are sequential operations within the visual embedding node.
>
> **Rationale:** Storing page images first ensures they are persisted even if ColQwen2 inference fails partway through. This supports future re-embedding scenarios where page images can be read from MinIO without re-parsing the source document.
>
> **Acceptance Criteria:** If ColQwen2 model loading fails after page image extraction, all page images are already stored in MinIO. The MinIO storage operation completes before ColQwen2 model loading begins.

> **FR-404** | Priority: MUST
>
> **Description:** The system MUST use the existing MinIO client available via `Runtime.db_client`. The system MUST NOT create a new MinIO connection or bucket for page image storage. Page images MUST be stored in the same bucket used for document content storage, differentiated by the `pages/` key prefix.
>
> **Rationale:** Reusing the existing MinIO infrastructure avoids connection management complexity and bucket proliferation. The key prefix pattern provides logical separation within a single bucket.
>
> **Acceptance Criteria:** Page images are stored using the same MinIO client instance and bucket as document content (`documents/{document_id}/content.md`). No new bucket is created. The `pages/` prefix is distinct from the `documents/` prefix.

> **FR-405** | Priority: MUST
>
> **Description:** The system MUST delete all existing page images for a document before storing new page images during re-ingestion (update mode). Deletion MUST use prefix-based listing and delete all objects under `pages/{document_id}/`.
>
> **Rationale:** When a document is re-ingested, page counts may change (pages added or removed). Deleting all existing page images before storing new ones prevents stale page images from persisting. This mirrors the text track's delete-before-insert pattern for Weaviate chunks.
>
> **Acceptance Criteria:** Re-ingesting a document that previously had 10 pages but now has 8 pages results in exactly 8 page images in MinIO. No remnant images from the previous ingestion remain.

---

## 7. Weaviate Visual Collection

> **FR-501** | Priority: MUST
>
> **Description:** The system MUST create and manage a dedicated Weaviate collection for visual page embeddings, distinct from the text chunk collection. The collection name MUST be specified by the `visual_target_collection` configuration parameter.
>
> **Rationale:** Visual embeddings have a fundamentally different schema from text chunk embeddings (page-level granularity, 128-dim vectors, patch vector storage). A dedicated collection provides clean separation and enables independent indexing, querying, and lifecycle management.
>
> **Acceptance Criteria:** The visual collection exists in Weaviate with the configured name. It is a separate collection from `target_collection` (text chunks). Both collections can be queried independently.

> **FR-502** | Priority: MUST
>
> **Description:** The system MUST call an idempotent `ensure_visual_collection()` function at the start of the visual embedding node to create the visual collection if it does not exist. If the collection already exists, the function MUST return without error.
>
> **Rationale:** The visual collection may not exist on first run or after a Weaviate reset. Idempotent creation follows the same pattern as `ensure_collection()` for the text collection, ensuring the pipeline is self-bootstrapping.
>
> **Acceptance Criteria:** The first document ingested with `enable_visual_embedding=True` creates the visual collection. Subsequent documents reuse the existing collection without errors. The function succeeds whether the collection exists or not.

> **FR-503** | Priority: MUST
>
> **Description:** Each object in the visual collection MUST represent a single document page and MUST include the following properties: `document_id` (string), `page_number` (integer, 1-indexed), `source_key` (string), `source_uri` (string), `source_name` (string), `tenant_id` (string), `total_pages` (integer), `page_width_px` (integer), `page_height_px` (integer), `minio_key` (string).
>
> **Rationale:** These properties enable filtering (by document, tenant, source), cross-referencing (with text collection via document_id), and linking to stored page images (via minio_key). The property set mirrors the metadata available on text chunk objects for consistency.
>
> **Acceptance Criteria:** A visual page object in Weaviate contains all listed properties with correct types. The `document_id` value matches the corresponding text chunk objects for the same document. The `minio_key` value matches the actual MinIO storage key for the page image.

> **FR-504** | Priority: MUST
>
> **Description:** Each visual page object MUST have a named vector called `mean_vector` containing the 128-dimensional float32 mean-pooled vector for that page. This named vector MUST be configured for ANN indexing in Weaviate.
>
> **Rationale:** The mean-pooled vector is used for fast approximate nearest neighbor search at query time. Weaviate's ANN index on this vector enables efficient candidate retrieval across the visual collection.
>
> **Acceptance Criteria:** The `mean_vector` named vector is present on every visual page object. It has exactly 128 dimensions. Weaviate can perform ANN search on this vector and return results ranked by similarity.

> **FR-505** | Priority: MUST
>
> **Description:** Each visual page object MUST have a `patch_vectors` property containing the full set of raw patch vectors as a JSON-serialized array (list of lists of floats). This property MUST NOT be indexed as a Weaviate vector (it is a data property, not a named vector).
>
> **Rationale:** The raw patch vectors are needed for post-retrieval MaxSim re-scoring. Storing them as a JSON property rather than as individual Weaviate named vectors avoids the named-vector-per-patch explosion (500-1200 named vectors per page would exceed practical limits). The property is read-only after insertion; it is not used for ANN search.
>
> **Acceptance Criteria:** The `patch_vectors` property is present on every visual page object. It can be deserialized from JSON to a Python list of lists of floats. The number of inner lists matches the patch count reported during ColQwen2 inference. Each inner list has exactly 128 elements.

> **FR-506** | Priority: MUST
>
> **Description:** The system MUST provide a `delete_visual_by_source_key()` function that deletes all visual page objects matching a given `source_key` from the visual collection. This function MUST be called before inserting new visual objects during re-ingestion (update mode).
>
> **Rationale:** When a document is re-ingested, the number of pages and their visual embeddings may have changed. Deleting prior visual objects by source_key before inserting new ones prevents stale data. This mirrors the text track's delete-before-insert pattern.
>
> **Acceptance Criteria:** After calling `delete_visual_by_source_key("doc_abc")`, no visual page objects with `source_key="doc_abc"` exist in the visual collection. Objects with different source_keys are unaffected. Calling the function when no matching objects exist does not raise an error.

> **FR-507** | Priority: MUST
>
> **Description:** The system MUST provide an `add_visual_documents()` function that batch-inserts visual page objects into the visual collection. The function MUST accept a list of visual page data (properties, mean_vector, patch_vectors) and insert them in a single batch operation.
>
> **Rationale:** Batch insertion is more efficient than per-page insertion, especially for large documents. A single batch operation reduces Weaviate round trips from O(pages) to O(1).
>
> **Acceptance Criteria:** A 50-page document's visual embeddings are inserted in a single batch call. All 50 objects are present in the collection after insertion. Each object has the correct properties, mean_vector, and patch_vectors.

---

## 8. Pipeline Integration

> **FR-601** | Priority: MUST
>
> **Description:** The visual embedding node MUST be added to the Phase 2 Embedding Pipeline LangGraph DAG as a node named `"visual_embedding"`. It MUST be placed after the `embedding_storage` node and before the `knowledge_graph_storage` node (or before `END` if knowledge graph storage is disabled).
>
> **Rationale:** Placing the visual node after `embedding_storage` ensures the text track is fully complete before visual processing begins. This guarantees that text track results are never affected by visual track failures and that VRAM is available for ColQwen2 (BGE-M3 inference is complete).
>
> **Acceptance Criteria:** The compiled LangGraph DAG includes a `visual_embedding` node. The DAG edge ordering is: `embedding_storage` -> `visual_embedding` -> `knowledge_graph_storage` (or `END`). The visual node receives the complete pipeline state including `stored_count` from the text track.

> **FR-602** | Priority: MUST
>
> **Description:** The pipeline state contract (`EmbeddingPipelineState`) MUST be extended with two new fields: `visual_stored_count` (integer, default 0) representing the number of visual page objects successfully stored in Weaviate, and `page_images` (optional list) representing the transient in-memory page images extracted from the DoclingDocument.
>
> **Rationale:** `visual_stored_count` provides the visual track's equivalent of `stored_count` for reporting and verification. `page_images` provides a typed state field for passing extracted page images between extraction and embedding steps within the visual node.
>
> **Acceptance Criteria:** The `EmbeddingPipelineState` TypedDict includes `visual_stored_count: int` and `page_images: Optional[List[Any]]`. Existing fields are unchanged. The pipeline compiles and runs with the extended state.

> **FR-603** | Priority: MUST
>
> **Description:** The visual embedding node MUST short-circuit and return immediately when any of the following conditions are met: (a) `enable_visual_embedding` is `False`, (b) the `docling_document` field in state is `None`, or (c) no page images can be extracted from the DoclingDocument. In all short-circuit cases, the node MUST log a descriptive entry to `processing_log` and set `visual_stored_count=0`.
>
> **Rationale:** Short-circuiting avoids unnecessary processing, model loading, and storage operations when the visual track is not applicable. Logging the reason for short-circuiting provides operational visibility.
>
> **Acceptance Criteria:** With `enable_visual_embedding=False`, the node returns in under 10 milliseconds. With `docling_document=None`, the node logs `visual_embedding:no_docling_document` and returns. With a DoclingDocument that has no page images, the node logs `visual_embedding:no_pages` and returns. In all cases, `visual_stored_count=0` and no model is loaded.

> **FR-604** | Priority: MUST
>
> **Description:** The `"visual_embedding"` node name MUST be added to the `PIPELINE_NODE_NAMES` registry in the ingestion common types module. It MUST be placed after `"embedding_storage"` and before `"knowledge_graph_storage"`.
>
> **Rationale:** The `PIPELINE_NODE_NAMES` registry is used for pipeline progress tracking, stage ordering validation, and log correlation. The visual embedding node must be registered to maintain these capabilities.
>
> **Acceptance Criteria:** `"visual_embedding"` appears in `PIPELINE_NODE_NAMES` at the position between `"embedding_storage"` and `"knowledge_graph_storage"`. The total number of registered node names increases by one.

> **FR-605** | Priority: MUST
>
> **Description:** The `IngestFileResult` dataclass MUST be extended to include a `visual_stored_count` integer field reporting the number of visual page objects stored during ingestion. The default value MUST be `0`.
>
> **Rationale:** Operators and monitoring systems need visibility into visual track results alongside text track results. Including `visual_stored_count` in the ingestion result enables reporting on dual-track ingestion outcomes.
>
> **Acceptance Criteria:** After ingesting a 10-page document with visual embedding enabled, the `IngestFileResult` includes `visual_stored_count=10` (or fewer if some pages failed). With visual embedding disabled, `visual_stored_count=0`.

> **FR-606** | Priority: MUST
>
> **Description:** The visual embedding node MUST clear the `page_images` field from the pipeline state after processing is complete (whether successful or partially failed). Page images MUST NOT remain in state after the visual embedding node returns.
>
> **Rationale:** Page images are large in-memory objects (PIL.Image instances). Retaining them in state after the visual node completes wastes memory for the remainder of the pipeline. Clearing them immediately enables garbage collection.
>
> **Acceptance Criteria:** After the visual embedding node completes, the `page_images` field in the pipeline state is set to `None` or an empty list. Memory profiling confirms that PIL.Image objects from page extraction are eligible for garbage collection after the node returns.

---

## 9. Format-Specific Handling

> **FR-701** | Priority: MUST
>
> **Description:** The system MUST support page image extraction and visual embedding for PDF documents. Each PDF page MUST produce exactly one page image. Page ordering MUST match the PDF page order.
>
> **Rationale:** PDF is the primary document format for technical documentation, engineering specifications, and research papers. PDF support is the baseline for the visual embedding track.
>
> **Acceptance Criteria:** A 10-page PDF produces 10 page images and 10 visual page objects in Weaviate. Page 1 in the PDF corresponds to page_number=1 in Weaviate. Visual embedding quality is consistent across text-heavy, diagram-heavy, and mixed pages.

> **FR-702** | Priority: MUST
>
> **Description:** The system MUST support page image extraction and visual embedding for PPTX (PowerPoint) documents. Each slide MUST produce exactly one page image. Slide ordering MUST match the presentation order.
>
> **Rationale:** Slide decks contain highly visual content (diagrams, charts, layouts) that text-only embedding poorly represents. PPTX is a primary use case for visual embedding because slides are inherently visual documents.
>
> **Acceptance Criteria:** A 20-slide PPTX produces 20 page images and 20 visual page objects in Weaviate. Slide 1 corresponds to page_number=1. Slide content (text, shapes, images) is rendered in the page image.

> **FR-703** | Priority: SHOULD
>
> **Description:** The system SHOULD support page image extraction and visual embedding for DOCX (Word) documents. Page boundaries SHOULD be determined by Docling's layout engine. The number of page images SHOULD match the rendered page count of the document.
>
> **Rationale:** DOCX documents do not have inherent page boundaries (they are flow-layout documents). Docling's layout engine renders them to pages, but page boundaries may not match the user's expected pagination (which depends on printer settings, font availability, etc.). DOCX support is therefore SHOULD rather than MUST.
>
> **Acceptance Criteria:** A DOCX document renders to page images via Docling. The number of page images is reasonable for the document length (e.g., a 5000-word document produces approximately 5-10 page images). Visual embeddings are stored for each rendered page.

> **FR-704** | Priority: MUST
>
> **Description:** The system MUST support visual embedding for pure image files (JPG, PNG) that Docling wraps as single-page documents. A pure image file MUST produce exactly one page image (the image itself) and one visual page object.
>
> **Rationale:** Users may ingest standalone images (diagrams, flowcharts, whiteboard photos). Docling wraps these as single-page documents. The visual track should process them identically to a 1-page PDF.
>
> **Acceptance Criteria:** Ingesting a single JPG file produces one visual page object in Weaviate with `page_number=1` and `total_pages=1`. The page image stored in MinIO matches the input image (resized per FR-202 if necessary).

> **FR-705** | Priority: MUST
>
> **Description:** The system MUST handle format-specific page image extraction failures gracefully. If Docling fails to render page images for a specific format (e.g., an encrypted PDF, a password-protected PPTX, or a corrupted file), the visual embedding node MUST log a warning, set `visual_stored_count=0`, and return without error. The text track MUST NOT be affected.
>
> **Rationale:** Format-specific failures (encryption, corruption, unsupported features) should not crash the pipeline. The text track may still have successfully processed the document's text content.
>
> **Acceptance Criteria:** An encrypted PDF that produces text chunks via Docling but fails page image rendering results in: text track `stored_count > 0`, visual track `visual_stored_count=0`, a warning log entry, and no pipeline exception.

---

## 10. Error Handling & Resilience

> **FR-801** | Priority: MUST
>
> **Description:** The visual embedding node MUST follow the per-item try/except error handling pattern used by existing pipeline nodes (e.g., `vlm_enrichment_node`). Each page MUST be processed within its own error boundary. A failure on one page MUST NOT prevent other pages from being processed.
>
> **Rationale:** The existing pipeline uses consistent per-item error isolation. Following this pattern ensures that partial failures produce partial results rather than complete failures. Operators expect consistent error handling behavior across all pipeline nodes.
>
> **Acceptance Criteria:** A 10-page document where page 3 and page 7 cause exceptions produces visual embeddings for pages 1, 2, 4, 5, 6, 8, 9, 10. Each exception is logged as a warning. The pipeline continues to subsequent nodes. `visual_stored_count=8`.

> **FR-802** | Priority: MUST
>
> **Description:** ColQwen2 model load failure MUST be treated as a fatal error for the visual embedding node. When the model fails to load (missing model files, incompatible GPU, CUDA errors), the node MUST log an error, set `visual_stored_count=0`, and add the error to the `errors` list in pipeline state. The node MUST NOT retry model loading.
>
> **Rationale:** Model load failure indicates a systemic issue (missing dependency, GPU incompatibility, insufficient VRAM) that will not be resolved by retrying. Logging the error and continuing allows the text track results to be preserved.
>
> **Acceptance Criteria:** When ColQwen2 fails to load (simulated by an invalid model name), the node logs an error with the exception details, sets `visual_stored_count=0`, adds the error message to `state["errors"]`, and returns. The text track's `stored_count` is unaffected. No retry is attempted.

> **FR-803** | Priority: MUST
>
> **Description:** The visual embedding node MUST NOT corrupt or modify any pipeline state fields owned by the text track. The node MUST write only to: `visual_stored_count`, `page_images` (transient), `processing_log`, and `errors`. The fields `stored_count`, `chunks`, `enriched_chunks`, and all other text-track fields MUST remain unchanged.
>
> **Rationale:** Track isolation is a core design principle. The text track has already completed by the time the visual node runs. Any modification to text track state fields would introduce coupling between independent tracks and could corrupt already-finalized results.
>
> **Acceptance Criteria:** Before and after the visual embedding node runs, the values of `stored_count`, `chunks`, `enriched_chunks`, `metadata_summary`, and `metadata_keywords` in the pipeline state are byte-identical. The visual node does not call any functions that modify text track state.

> **FR-804** | Priority: MUST
>
> **Description:** MinIO storage failures for individual page images MUST be handled as non-fatal errors. If a page image fails to upload to MinIO, the system MUST log a warning, skip the ColQwen2 embedding for that page (since the minio_key reference would be invalid), and continue with remaining pages.
>
> **Rationale:** A MinIO upload failure for one page (network blip, temporary disk full) should not prevent other pages from being processed. Skipping the embedding for a failed upload is correct because the Weaviate object would reference a non-existent MinIO key.
>
> **Acceptance Criteria:** A MinIO upload failure for page 5 of 10 results in: 9 page images in MinIO, 9 visual page objects in Weaviate (pages 1-4, 6-10), a warning log entry for the failed page, and `visual_stored_count=9`.

> **FR-805** | Priority: MUST
>
> **Description:** Weaviate batch insertion failures MUST be handled by reporting the failure in the pipeline state. If `add_visual_documents()` fails, the system MUST add the error to `state["errors"]`, set `visual_stored_count` to the number of successfully stored objects (which may be 0), and return without raising an exception.
>
> **Rationale:** Weaviate batch insertion may fail due to connection issues, schema mismatches, or resource exhaustion. The pipeline must not crash; it must report the failure and preserve text track results.
>
> **Acceptance Criteria:** A Weaviate batch insertion failure produces: an error message in `state["errors"]`, `visual_stored_count=0` (or the partial count if partial batch success is detectable), and the pipeline continues without exception.

> **FR-806** | Priority: SHOULD
>
> **Description:** The system SHOULD validate that the `colpali-engine` and `bitsandbytes` packages are installed before attempting to load ColQwen2. If either package is missing, the visual embedding node SHOULD log a clear error message identifying the missing package and short-circuit.
>
> **Rationale:** These packages are optional dependencies (in the `[visual]` extra group). Attempting to import them at runtime without validation produces cryptic ImportError messages. A clear pre-check message helps operators install the correct package.
>
> **Acceptance Criteria:** When `colpali-engine` is not installed and `enable_visual_embedding=True`, the node logs an error message containing the text "colpali-engine" and the installation command. The node short-circuits with `visual_stored_count=0`. No ImportError traceback is shown to the operator.

---

## 11. Non-Functional Requirements

> **NFR-901** | Priority: MUST
>
> **Description:** The visual embedding track MUST operate within a peak GPU VRAM budget of 4GB during ColQwen2 inference (model + inference buffers). The combined VRAM usage of the visual embedding node at peak MUST NOT exceed 4GB on a 6GB GPU.
>
> **Rationale:** The target deployment GPU is an RTX 2060 with 6GB VRAM. Approximately 1.5-2GB is reserved for CUDA runtime, operating system, and display. ColQwen2 at 4-bit quantization uses approximately 2GB for model weights plus up to 1.5GB for inference buffers, totaling approximately 3.5GB.
>
> **Acceptance Criteria:** During ColQwen2 inference on a 4-page batch at 1024px max dimension, peak GPU memory allocation does not exceed 4GB as measured by `torch.cuda.max_memory_allocated()`.

> **NFR-902** | Priority: MUST
>
> **Description:** The visual embedding node MUST complete processing within 5 seconds per page on average for documents up to 100 pages, measured on the target hardware (RTX 2060, 6GB VRAM).
>
> **Rationale:** The existing text embedding pipeline processes a 100-page document in approximately 30-60 seconds. Adding more than 500 seconds (5 seconds/page x 100 pages) of visual processing would more than double the total ingestion time, which is the acceptable upper bound for a batch pipeline.
>
> **Acceptance Criteria:** A 10-page PDF document completes visual embedding (extraction, MinIO storage, ColQwen2 inference, Weaviate storage) in under 50 seconds. A 100-page PDF completes in under 500 seconds.

> **NFR-903** | Priority: MUST
>
> **Description:** The visual embedding node MUST add zero latency and zero resource consumption to the pipeline when `enable_visual_embedding=False`. The short-circuit path MUST execute in under 10 milliseconds.
>
> **Rationale:** The visual track is optional. When disabled, operators should observe identical performance characteristics to the pre-visual-embedding baseline. Any overhead (even trivial) contradicts the zero-impact design principle.
>
> **Acceptance Criteria:** With `enable_visual_embedding=False`, the visual embedding node's wall-clock execution time is under 10 milliseconds. No GPU memory is allocated. No MinIO or Weaviate calls are made. No model imports occur.

> **NFR-904** | Priority: SHOULD
>
> **Description:** The MinIO page image storage footprint SHOULD be bounded at approximately 50-200KB per page for typical document pages at the default quality setting (85) and maximum dimension (1024px).
>
> **Rationale:** Storage cost scales linearly with page count. At 100KB average per page, a 1000-document corpus with 10 pages each adds approximately 1GB to MinIO. This is acceptable for local deployments but should not grow unboundedly.
>
> **Acceptance Criteria:** The average JPEG file size for document pages at quality=85 and max_dimension=1024 is between 30KB and 300KB across a sample of 100 pages from mixed document types (text-heavy, diagram-heavy, slides).

> **NFR-905** | Priority: MUST
>
> **Description:** All behavioral parameters of the visual embedding track MUST be configurable without code changes, using typed configuration fields with environment variable overrides.
>
> **Rationale:** This is a core design principle of the ingestion pipeline. Operators must be able to tune the visual track's behavior (model selection, batch size, image quality, collection name) for their specific hardware and use case without modifying source code.
>
> **Acceptance Criteria:** Every parameter listed in FR-101 through FR-109 is configurable via both a Python configuration field and an environment variable. Changing any parameter does not require code modification, recompilation, or redeployment of the application image.

> **NFR-906** | Priority: MUST
>
> **Description:** The `colpali-engine` and `bitsandbytes` packages MUST be declared as optional dependencies in a `[visual]` extras group in `pyproject.toml`. The core application MUST be installable and runnable without these packages when `enable_visual_embedding=False`.
>
> **Rationale:** ColQwen2 inference dependencies are heavy (torch, transformers, bitsandbytes). Systems that do not use visual embedding should not be forced to install these packages, which increase image size and potential dependency conflicts.
>
> **Acceptance Criteria:** Running `pip install .` (without extras) succeeds and the application starts with `enable_visual_embedding=False`. Running `pip install ".[visual]"` installs `colpali-engine` and `bitsandbytes`. Attempting to enable visual embedding without the `[visual]` extras produces the error described in FR-806.

> **NFR-907** | Priority: SHOULD
>
> **Description:** The visual embedding node SHOULD be idempotent. Re-running the visual embedding node on the same document with the same configuration SHOULD produce identical results (same page images in MinIO, same visual embeddings in Weaviate).
>
> **Rationale:** Idempotency simplifies re-processing and recovery from partial failures. If an operator re-ingests a document, the visual track should produce the same output without accumulating duplicate objects.
>
> **Acceptance Criteria:** Ingesting the same document twice with `update_mode=True` produces exactly the same set of visual page objects in Weaviate (same count, same properties, same vectors within floating-point tolerance). No duplicate page images exist in MinIO after re-ingestion.

> **NFR-908** | Priority: SHOULD
>
> **Description:** The visual embedding node SHOULD produce deterministic embeddings for the same page image across runs. Given the same page image, ColQwen2 model, and quantization settings, the produced patch vectors and mean-pooled vector SHOULD be identical within floating-point tolerance (1e-5 per dimension).
>
> **Rationale:** Deterministic embeddings enable reproducible retrieval results and simplify testing. Non-determinism in embeddings would make it difficult to verify correctness and could cause inconsistent retrieval behavior across re-ingestion cycles.
>
> **Acceptance Criteria:** The mean-pooled vector for a given page image differs by less than 1e-5 per dimension across two independent pipeline runs with identical configuration and model.

> **NFR-909** | Priority: MUST
>
> **Description:** The visual embedding track MUST NOT introduce any breaking changes to the existing text embedding pipeline's public API, state contract, or behavior. All existing imports, function signatures, and configuration parameters MUST remain backward-compatible.
>
> **Rationale:** The visual track is an additive feature. Existing integrations (CLI, API, Temporal workers) that use the ingestion pipeline must continue to work without modification when the visual track is disabled.
>
> **Acceptance Criteria:** All existing tests for the text embedding pipeline pass without modification after the visual track is integrated. The `EmbeddingPipelineState` remains backward-compatible (new fields are optional with defaults). Existing callers of `ingest_file()` receive valid results without code changes.

> **NFR-910** | Priority: SHOULD
>
> **Description:** The ColQwen2 model adapter module SHOULD follow the same structural pattern as the existing `docling.py` support module. It SHOULD provide a clean adapter interface that isolates the colpali-engine library details from the pipeline node.
>
> **Rationale:** Following existing patterns reduces cognitive load for developers maintaining the codebase. Adapter isolation means that if colpali-engine's API changes, only the adapter module needs updating.
>
> **Acceptance Criteria:** The ColQwen2 adapter module is located at `src/ingest/support/colqwen.py`. It exposes functions for model loading, batch inference, and model unloading. The pipeline node (`visual_embedding.py`) does not import directly from `colpali-engine` -- it uses the adapter's interface.

---

## 12. System-Level Acceptance Criteria

The following end-to-end acceptance criteria validate the complete visual embedding track:

1. **End-to-end PDF ingestion:** Ingest a 10-page PDF with `enable_visual_embedding=True`. Verify: 10 page images in MinIO, 10 visual page objects in Weaviate with correct properties and vectors, text track `stored_count > 0`, `visual_stored_count=10`.

2. **End-to-end PPTX ingestion:** Ingest a 20-slide PPTX with `enable_visual_embedding=True`. Verify: 20 page images in MinIO, 20 visual page objects with `page_number` 1-20, text track unaffected.

3. **Disabled track zero-impact:** Ingest the same PDF with `enable_visual_embedding=False`. Verify: no page images in MinIO, no visual collection objects, text track results identical to a baseline run without the visual track code present, node execution time under 10ms.

4. **Re-ingestion cleanup:** Ingest a PDF, then re-ingest with `update_mode=True`. Verify: old visual objects are replaced by new ones, page image count matches the current document, no duplicates.

5. **Partial failure resilience:** Ingest a document where one page has a corrupted image. Verify: other pages are successfully embedded, failed page is logged, pipeline does not crash, text track is unaffected.

6. **VRAM management:** Ingest a document and monitor GPU memory. Verify: ColQwen2 is loaded only during visual embedding, VRAM returns to pre-load levels after the node completes, peak VRAM does not exceed 4GB.

7. **Configuration validation:** Start the pipeline with `enable_visual_embedding=True` and `enable_docling_parser=False`. Verify: `verify_core_design()` returns a fatal error before any documents are processed.

8. **Pure image file:** Ingest a standalone JPG file. Verify: 1 page image in MinIO, 1 visual page object with `page_number=1` and `total_pages=1`.

---

## 13. Requirements Traceability Matrix

| REQ ID | Section | Priority | Component |
|--------|---------|----------|-----------|
| FR-101 | 3 | MUST | Configuration |
| FR-102 | 3 | MUST | Configuration |
| FR-103 | 3 | MUST | Configuration |
| FR-104 | 3 | MUST | Configuration |
| FR-105 | 3 | MUST | Configuration |
| FR-106 | 3 | MUST | Configuration |
| FR-107 | 3 | MUST | Configuration |
| FR-108 | 3 | MUST | Configuration |
| FR-109 | 3 | MUST | Configuration |
| FR-201 | 4 | MUST | Page Image Extraction |
| FR-202 | 4 | MUST | Page Image Extraction |
| FR-203 | 4 | MUST | Page Image Extraction |
| FR-204 | 4 | MUST | Page Image Extraction |
| FR-205 | 4 | SHOULD | Page Image Extraction |
| FR-301 | 5 | MUST | ColQwen2 Embedding |
| FR-302 | 5 | MUST | ColQwen2 Embedding |
| FR-303 | 5 | MUST | ColQwen2 Embedding |
| FR-304 | 5 | MUST | ColQwen2 Embedding |
| FR-305 | 5 | MUST | ColQwen2 Embedding |
| FR-306 | 5 | SHOULD | ColQwen2 Embedding |
| FR-307 | 5 | MUST | ColQwen2 Embedding |
| FR-401 | 6 | MUST | MinIO Page Image Storage |
| FR-402 | 6 | MUST | MinIO Page Image Storage |
| FR-403 | 6 | MUST | MinIO Page Image Storage |
| FR-404 | 6 | MUST | MinIO Page Image Storage |
| FR-405 | 6 | MUST | MinIO Page Image Storage |
| FR-501 | 7 | MUST | Weaviate Visual Collection |
| FR-502 | 7 | MUST | Weaviate Visual Collection |
| FR-503 | 7 | MUST | Weaviate Visual Collection |
| FR-504 | 7 | MUST | Weaviate Visual Collection |
| FR-505 | 7 | MUST | Weaviate Visual Collection |
| FR-506 | 7 | MUST | Weaviate Visual Collection |
| FR-507 | 7 | MUST | Weaviate Visual Collection |
| FR-601 | 8 | MUST | Pipeline Integration |
| FR-602 | 8 | MUST | Pipeline Integration |
| FR-603 | 8 | MUST | Pipeline Integration |
| FR-604 | 8 | MUST | Pipeline Integration |
| FR-605 | 8 | MUST | Pipeline Integration |
| FR-606 | 8 | MUST | Pipeline Integration |
| FR-701 | 9 | MUST | Format-Specific Handling |
| FR-702 | 9 | MUST | Format-Specific Handling |
| FR-703 | 9 | SHOULD | Format-Specific Handling |
| FR-704 | 9 | MUST | Format-Specific Handling |
| FR-705 | 9 | MUST | Format-Specific Handling |
| FR-801 | 10 | MUST | Error Handling |
| FR-802 | 10 | MUST | Error Handling |
| FR-803 | 10 | MUST | Error Handling |
| FR-804 | 10 | MUST | Error Handling |
| FR-805 | 10 | MUST | Error Handling |
| FR-806 | 10 | SHOULD | Error Handling |
| NFR-901 | 11 | MUST | Performance |
| NFR-902 | 11 | MUST | Performance |
| NFR-903 | 11 | MUST | Performance |
| NFR-904 | 11 | SHOULD | Storage |
| NFR-905 | 11 | MUST | Configurability |
| NFR-906 | 11 | MUST | Dependency Management |
| NFR-907 | 11 | SHOULD | Reliability |
| NFR-908 | 11 | SHOULD | Reliability |
| NFR-909 | 11 | MUST | Backward Compatibility |
| NFR-910 | 11 | SHOULD | Maintainability |

**Total Requirements: 48** (MUST: 38, SHOULD: 10, MAY: 0)

---

## Appendix A: Glossary

| Term | Definition |
|------|-----------|
| ANN | Approximate Nearest Neighbor -- fast vector similarity search algorithm |
| BGE-M3 | BAAI General Embedding Model, Multi-granularity Multi-lingual Multi-function -- 1024-dim text embedding model used by the text track |
| bitsandbytes | Python library for 4-bit and 8-bit model quantization on NVIDIA GPUs |
| ColPali | A vision-language model family for document understanding via multi-vector patch embeddings |
| ColQwen2 | ColPali variant using Qwen2-VL-2B as the vision-language backbone |
| colpali-engine | Reference Python library for ColPali/ColQwen2 inference |
| CUDA | NVIDIA's parallel computing platform for GPU programming |
| DAG | Directed Acyclic Graph -- the pipeline execution topology |
| Docling | IBM's document conversion library that parses PDF, PPTX, DOCX into structured representations |
| DoclingDocument | The native Docling document object containing parsed structure, text, and optionally page images |
| HuggingFace | Platform hosting machine learning models; ColQwen2 is distributed via HuggingFace Model Hub |
| LangGraph | Graph-based state machine framework used for pipeline orchestration |
| Late interaction | A retrieval paradigm where query and document representations interact at scoring time (not pre-computed), enabling fine-grained matching |
| MaxSim | Maximum Similarity -- the late-interaction scoring function used by ColPali models |
| MinIO | S3-compatible object storage used for document and page image persistence |
| PIL | Python Imaging Library (Pillow) -- used for page image manipulation |
| VRAM | Video Random Access Memory -- GPU memory used for model weights and inference buffers |
| Weaviate | Vector database used for text and visual embedding storage and retrieval |

## Appendix B: Document References

| Document | Path | Relevance |
|----------|------|-----------|
| Design sketch (input) | `docs/superpowers/specs/2026-04-01-multitrack-page-embedding-sketch.md` | Source design decisions and approach selection |
| Embedding pipeline state | `src/ingest/embedding/state.py` | Current state contract to be extended |
| Embedding pipeline workflow | `src/ingest/embedding/workflow.py` | Current DAG topology to be extended |
| Ingestion types | `src/ingest/common/types.py` | Configuration and runtime types to be extended |
| Docling support | `src/ingest/support/docling.py` | Existing Docling adapter to be extended with `generate_page_images` |
| VLM enrichment node | `src/ingest/embedding/nodes/vlm_enrichment.py` | Reference pattern for per-item error handling and short-circuit |
| Weaviate text store | `src/vector_db/weaviate/store.py` | Reference pattern for collection management and batch insertion |
| Vector DB backend | `src/vector_db/backend.py` | Abstract interface to be extended with visual collection operations |

## Appendix C: Implementation Phasing

| Phase | Description | Requirements Covered |
|-------|-------------|---------------------|
| Phase 1: Configuration & State | Add config fields, env vars, state contract extensions, validation | FR-101 through FR-109, FR-602, FR-604, FR-605 |
| Phase 2: Page Image Pipeline | Page image extraction from DoclingDocument, resize, MinIO storage, Docling `generate_page_images` integration | FR-107, FR-201 through FR-205, FR-401 through FR-405 |
| Phase 3: ColQwen2 Adapter | ColQwen2 model adapter module (load, infer, unload), batch processing, mean pooling | FR-301 through FR-307, NFR-906, NFR-910 |
| Phase 4: Weaviate Visual Collection | Visual collection schema, ensure/add/delete operations, backend abstraction | FR-501 through FR-507 |
| Phase 5: Pipeline Integration | DAG wiring, visual embedding node, short-circuit logic, update mode cleanup, format handling | FR-601, FR-603, FR-606, FR-701 through FR-705 |
| Phase 6: Error Handling & Validation | Per-item fault tolerance, model load failure handling, state isolation, dependency checks | FR-801 through FR-806, FR-803 |
| Phase 7: Non-Functional Validation | VRAM profiling, latency benchmarks, idempotency tests, backward compatibility verification | NFR-901 through NFR-909 |

## Appendix D: Open Questions

| ID | Question | Recommendation | Status |
|----|----------|----------------|--------|
| OQ-1 | Should the system support ColQwen2 model variants beyond v1.0? | Make `colqwen_model_name` configurable (FR-103). New models work automatically if API-compatible with colpali-engine. | Resolved (covered by FR-103) |
| OQ-2 | Should page images be resized before ColQwen2 inference? | Yes. Use `page_image_max_dimension` config (FR-106). Default 1024px bounds patch count while preserving visual detail. | Resolved (covered by FR-106, FR-202) |
| OQ-3 | How should batch size interact with GPU memory on different hardware? | Expose `colqwen_batch_size` config (FR-104). Default 4 is tuned for RTX 2060. Operators with more VRAM can increase. | Resolved (covered by FR-104) |
| OQ-4 | What happens when DoclingDocument was loaded from JSON (serialized) and page images are not available? | Short-circuit with `visual_embedding:no_pages` log (FR-203, FR-603). In-memory path from Phase 1 is the primary path. Re-rendering from source is future scope. | Resolved (covered by FR-603) |
| OQ-5 | How does cleanup work on re-ingestion? | Delete visual objects by source_key and page images by document_id prefix before re-insertion (FR-405, FR-506). | Resolved (covered by FR-405, FR-506) |
| OQ-6 | Should ColQwen2 be kept loaded across multiple documents in a batch ingestion run? | Out of scope for this spec. Current design loads/unloads per document. A singleton or cached model loader could be a future optimization. | Open |
| OQ-7 | What is the maximum document size (page count) the system should support? | No hard limit specified. Batch processing (FR-302) handles arbitrarily large documents. Progress logging (FR-306) provides visibility for large documents. Performance is linear in page count. | Resolved (covered by FR-302, FR-306) |
