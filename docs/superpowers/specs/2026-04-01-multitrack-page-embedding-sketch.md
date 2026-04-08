# Dual-Track Page Embedding Pipeline -- Design Sketch

| Field | Value |
|---|---|
| Date | 2026-04-01 |
| Status | APPROVED (brainstorm complete) |
| Scope | EXTENSION to existing ingestion pipeline (`src/ingest/embedding/`) |
| Produced by | Autonomous brainstorm subagent |

---

## 1. Goal Statement

Add a visual embedding track to the existing ingestion pipeline so that a single Docling parse produces two parallel outputs:

- **Track 1 (text)**: Docling -> HybridChunker -> BGE-M3 -> Weaviate text collection (existing, unchanged)
- **Track 2 (visual)**: Docling page images -> ColQwen2 (page-level multi-vector patch embeddings) -> Weaviate visual collection (new)

The visual track enables late-interaction retrieval over page-level visual content (diagrams, tables, layouts, slides) that text-only embeddings lose. Both tracks share the same Docling conversion pass -- no re-parsing.

---

## 2. Clarifying Questions and Self-Answers

### Q1: What is the primary user of visual embeddings?
**A**: The retrieval pipeline. At query time, a visual query path will use ColQwen2 to embed the query text, then retrieve page-level candidates from the visual collection via ANN on mean-pooled vectors, followed by MaxSim re-scoring on patch vectors. This retrieval-side merge is explicitly OUT of scope for this design -- it is a separate pipeline run.

### Q2: Does Docling support page image generation for non-PDF formats (PPTX, DOCX)?
**A**: Yes. Docling supports `generate_page_images=True` for PDF, PPTX, and DOCX. PPTX slides are rendered as page images directly. DOCX pages are rendered via Docling's internal layout engine. The page image extraction API is format-agnostic at the `ConversionResult.pages` level.

### Q3: What happens when `enable_docling_parser=False`?
**A**: The visual track is silently disabled. No DoclingDocument means no page images. The text track falls back to markdown chunking as today. This is by design -- visual embedding requires Docling.

### Q4: What is the VRAM budget for ColQwen2?
**A**: RTX 2060, 6GB VRAM. ColQwen2 v1.0 (Qwen2-VL-2B backbone) at 4-bit quantization via bitsandbytes requires approximately 2GB VRAM. BGE-M3 uses approximately 1.5GB. Both can coexist on the same GPU if loaded sequentially (not simultaneously). The design must load ColQwen2 on-demand and release after the visual embedding node completes.

### Q5: How many patch vectors does ColQwen2 produce per page?
**A**: ColQwen2 produces a variable number of 128-dimensional patch vectors per page image, typically 500-1200 depending on image resolution. For a 10-page document, that is 5,000-12,000 vectors. These cannot each be a separate Weaviate named vector -- that exceeds practical limits. The design uses mean-pooling for ANN retrieval plus raw patch storage for MaxSim re-scoring.

### Q6: Can the visual embedding node run in parallel with the text embedding path?
**A**: In the current LangGraph sequential DAG, nodes run sequentially. True parallelism would require a LangGraph parallel branch or a post-graph parallel dispatch. The pragmatic approach is: add visual_embedding as a new node AFTER embedding_storage (the text track's final storage node) but BEFORE knowledge_graph_storage. This keeps the DAG linear. The visual node processes page images independently of text chunks -- no data dependency between tracks except the shared `docling_document` and `document_id`.

### Q7: Where are page images stored?
**A**: JPEG-compressed page images are stored in MinIO under the existing bucket with a `pages/{document_id}/{page_number}.jpg` key prefix. This reuses the existing MinIO infrastructure (`src/db/`) without a new bucket. Page image references in the Weaviate visual collection link back via `document_id` + `page_number`.

### Q8: What is the Weaviate visual collection schema?
**A**: Each object in the visual collection represents ONE PAGE. Properties include: `document_id`, `page_number`, `source_key`, `source_uri`, `source_name`, `tenant_id`, `total_pages`, `page_width`, `page_height`. The object has one named vector (`mean_vector`, 128-dim, mean-pooled from patch vectors) for ANN search, plus a `patch_vectors` property storing the full patch vector array as a JSON blob (list of list of float) for post-retrieval MaxSim.

### Q9: Is PPTX slide-boundary text chunking in scope?
**A**: No. The prompt marks it as "related but separate concern." It is listed as out-of-scope. The visual track already handles PPTX slides natively (one slide = one page image).

### Q10: What if page image generation fails for one page?
**A**: Non-fatal. Log a warning, skip the page, continue with remaining pages. The text track is unaffected. The visual embedding node follows the same error-resilience pattern as `vlm_enrichment_node` -- per-item failures are caught, logged, and do not halt the pipeline.

---

## 3. Constraint Conflict Check

| Constraint pair | Conflict? | Resolution |
|---|---|---|
| ColQwen2 VRAM (2GB@4bit) + BGE-M3 VRAM (1.5GB) vs RTX 2060 (6GB) | No conflict if sequential | Load ColQwen2 on-demand in visual_embedding_node; BGE-M3 is already loaded in Runtime. Sequential execution means only one model needs GPU at a time. ColQwen2 is loaded, used, and unloaded within the node scope. |
| `generate_page_images=True` changes Docling behavior | Potential: existing tests may assume no page images | Gate behind `enable_visual_embedding` config flag. When disabled, `generate_page_images` stays False -- zero change to existing behavior. |
| Weaviate multi-vector (patch vectors) storage | Potential: Weaviate v4 does not natively support MaxSim scoring | Resolved by two-tier approach: ANN on mean-pooled vector (standard Weaviate), MaxSim computed application-side on shortlisted candidates. Patch vectors stored as JSON property, not as Weaviate vectors. |
| LangGraph DAG is linear -- visual node adds latency | Acceptable | ColQwen2 inference for a 10-page doc at 4-bit: approximately 5-15 seconds total. This is comparable to existing LLM-based metadata generation. For large docs, page batching mitigates. |
| MinIO page image storage adds I/O | Acceptable | JPEG at 85% quality is 50-200KB per page. A 100-page PDF adds 5-20MB to MinIO. Negligible vs existing document storage. |
| `colpali-engine` library is a new dependency | Justified | `colpali-engine` is the reference implementation for ColPali/ColQwen2 inference. Writing custom inference code is error-prone and harder to maintain. The library handles image preprocessing, model loading, and patch vector extraction. No existing dependency covers this. |

No blocking constraint conflicts found.

---

## 4. Scope Feasibility Check

| Scope item | Feasibility | Risk |
|---|---|---|
| Page image extraction from Docling | High -- `generate_page_images=True` is documented and tested | Low |
| ColQwen2 inference with 4-bit quant | High -- `colpali-engine` + bitsandbytes is well-documented | Medium (first-time model download ~4GB) |
| MinIO page image storage | High -- reuses existing MinIO client | Low |
| Weaviate visual collection creation | High -- `ensure_collection` pattern already supports named collections | Low |
| Mean-pooled vector + JSON patch vector storage | Medium -- requires new collection schema in Weaviate store | Low |
| LangGraph DAG extension with new node | High -- follows existing `vlm_enrichment_node` pattern | Low |
| Config flags and env vars | High -- follows existing `RAG_INGESTION_*` pattern | Low |

Overall: **feasible within a single implementation cycle**. The highest-risk item is ColQwen2 model loading and VRAM management, which should be validated with a standalone smoke test before integration.

---

## 5. Approaches

### Approach A: New Node in Existing Embedding Pipeline DAG (RECOMMENDED)

Add `visual_embedding_node` as a new node in the existing `build_embedding_graph()` LangGraph DAG. The node runs after `embedding_storage` (text track complete) and before `knowledge_graph_storage`. It reads `state["docling_document"]` and `state["document_id"]`, extracts page images, runs ColQwen2, stores page images to MinIO, and stores visual embeddings to the Weaviate visual collection. Short-circuits when `enable_visual_embedding=False` or when no `docling_document` is present.

**Pros:**
- Follows existing patterns exactly (one node per stage, short-circuit when disabled)
- Single pipeline run produces both tracks -- no orchestration complexity
- Shared `document_id` links text and visual collections naturally
- No changes to the Phase 1 -> Phase 2 boundary (DoclingDocument already passed through)
- State contract extension is minimal (add `visual_stored_count: int` field)

**Cons:**
- Sequential execution adds latency (ColQwen2 inference after all text processing)
- ColQwen2 model load/unload within node adds 2-5 seconds overhead per document
- If visual embedding fails, the text track has already succeeded -- partial success state

### Approach B: Separate Visual Embedding Pipeline (Post-Phase-2)

Create a separate `run_visual_embedding_pipeline()` called after `run_embedding_pipeline()` in `ingest_file()`. This is a standalone LangGraph graph with its own state contract, invoked only when `enable_visual_embedding=True`.

**Pros:**
- Complete isolation -- visual failures cannot affect text pipeline state
- Can be independently versioned, tested, and disabled
- Could run in parallel with text pipeline via Temporal activities in the future

**Cons:**
- Requires a second graph compilation, second state contract, second orchestrator
- Duplicates source identity plumbing and MinIO/Weaviate client setup
- Harder to ensure `document_id` consistency between tracks
- More code surface area for the same functionality
- Over-engineers for the current sequential execution model

### Approach C: Fan-Out Parallel Branches in LangGraph

Use LangGraph's parallel branch support to run text and visual embedding simultaneously from a common fork point after chunking.

**Pros:**
- True parallelism reduces end-to-end latency
- Elegant block-diagram representation

**Cons:**
- LangGraph parallel branches share state -- ColQwen2 and BGE-M3 simultaneous GPU usage exceeds VRAM budget on RTX 2060
- Requires significant refactoring of the existing linear DAG
- State merging after parallel branches adds complexity
- The "parallelism" is illusory given the VRAM constraint -- they would need to serialize anyway

### Recommendation: Approach A

Approach A is the clear winner. It follows every existing pattern in the codebase (node-per-file, short-circuit pattern, state extension), requires minimal structural changes, and correctly handles the VRAM constraint by sequential execution. The latency cost (5-15 seconds per document for ColQwen2) is acceptable for a batch ingestion pipeline.

### Devil's Advocate Against Approach A

**Counter-argument**: "Adding visual embedding to the existing DAG creates tight coupling. If ColQwen2 inference has a bug or the model fails to load, it could corrupt the pipeline state and affect text embedding results that already succeeded."

**Rebuttal**: The existing pipeline already handles this pattern. `vlm_enrichment_node` and `knowledge_graph_extraction_node` both run after earlier stages have completed and use internal try/except to ensure they never corrupt prior state. The visual embedding node follows the same contract: it reads `document_id` and `docling_document` (immutable at this point), writes only to `visual_stored_count` and `processing_log`, and catches all exceptions internally. The text track's `stored_count` is already finalized before the visual node runs. Partial success (text OK, visual failed) is a well-defined outcome, not a corruption risk.

---

## 6. Key Architectural Decisions

### Decision 1: Single Node in Existing DAG (not a separate pipeline)

**Rationale**: Follows the project's one-node-per-stage pattern. The visual embedding node is one more stage, not a separate system. Reuses the same Runtime, DoclingDocument, and document_id without plumbing duplication. The existing short-circuit pattern (`if not enabled: return skipped`) handles the disabled case cleanly.

### Decision 2: Mean-Pooled Vector for ANN + JSON Patch Vectors for MaxSim

**Rationale**: Weaviate v4 supports efficient ANN search on single vectors. ColQwen2's late-interaction scoring (MaxSim) requires comparing all query patch vectors against all document patch vectors -- this is not natively supported by any ANN index. The pragmatic two-tier approach uses Weaviate ANN on a mean-pooled 128-dim vector for candidate retrieval (fast, approximate), then application-side MaxSim on the raw patch vectors of the top-K candidates (exact, slow but bounded). Patch vectors are stored as a JSON array property, not as Weaviate named vectors, to avoid the named-vector-per-patch explosion.

### Decision 3: `generate_page_images=True` Gated by `enable_visual_embedding` Config

**Rationale**: Docling's `generate_page_images` flag adds memory overhead and processing time during conversion. It should only be activated when the visual track is enabled. The `parse_with_docling()` function in `src/ingest/support/docling.py` already accepts `PdfPipelineOptions` -- extending it to set `generate_page_images=True` when the visual track is active is a minimal change.

### Decision 4: ColQwen2 Loaded On-Demand, Unloaded After Node Completes

**Rationale**: On a 6GB RTX 2060, ColQwen2 at 4-bit (~2GB) cannot coexist with BGE-M3 (~1.5GB) plus Weaviate/system overhead. Since the visual embedding node runs after all BGE-M3 work is complete, we can load ColQwen2 at node entry and release it at node exit. The `colpali-engine` library supports this via standard HuggingFace model loading patterns. The 2-5 second model load overhead is amortized across all pages of the document.

### Decision 5: Page Images Stored as JPEG in MinIO with Document-Scoped Key Prefix

**Rationale**: JPEG at 85% quality provides 5-10x compression over PNG for document page images (typical: 50-200KB per page). MinIO key structure `pages/{document_id}/{page_number}.jpg` enables efficient prefix-based listing and cleanup. No new bucket needed -- reuses the existing `target_bucket`. The `document_id` already generated by `document_storage_node` provides the link between text chunks and page images.

---

## 7. Component/Module List

### New Files

| Module | Responsibility |
|---|---|
| `src/ingest/embedding/nodes/visual_embedding.py` | LangGraph node: extract page images from DoclingDocument, run ColQwen2, store page images to MinIO, store visual embeddings to Weaviate visual collection. Short-circuits when disabled. |
| `src/ingest/support/colqwen.py` | ColQwen2 model adapter: load model (4-bit quant via bitsandbytes), embed page images, return mean-pooled vector + patch vectors per page. Mirrors `src/ingest/support/docling.py` adapter pattern. |
| `src/vector_db/weaviate/visual_store.py` | Weaviate visual collection schema and CRUD: `ensure_visual_collection()`, `add_visual_documents()`, `delete_visual_by_source_key()`. Separate from text collection schema. |

### Modified Files

| Module | Change |
|---|---|
| `src/ingest/embedding/workflow.py` | Add `visual_embedding` node to DAG, between `embedding_storage` and `knowledge_graph_storage`. Conditional edge: skip if `enable_visual_embedding=False`. |
| `src/ingest/embedding/state.py` | Add fields: `visual_stored_count: int`, `page_images: Optional[List[Any]]` (transient, cleared after visual storage). |
| `src/ingest/common/types.py` | Add to `IngestionConfig`: `enable_visual_embedding: bool`, `visual_target_collection: str`, `colqwen_model_name: str`, `colqwen_batch_size: int`, `page_image_quality: int`, `page_image_max_dimension: int`. Add to `PIPELINE_NODE_NAMES`: `"visual_embedding"`. |
| `config/settings.py` | Add env vars: `RAG_INGESTION_ENABLE_VISUAL_EMBEDDING`, `RAG_INGESTION_VISUAL_TARGET_COLLECTION`, `RAG_INGESTION_COLQWEN_MODEL`, `RAG_INGESTION_COLQWEN_BATCH_SIZE`, `RAG_INGESTION_PAGE_IMAGE_QUALITY`, `RAG_INGESTION_PAGE_IMAGE_MAX_DIMENSION`. |
| `src/ingest/support/docling.py` | Extend `parse_with_docling()` to accept `generate_page_images: bool` parameter. When True, set `pipeline_options.generate_page_images = True` on `PdfPipelineOptions`. Return page image availability in `DoclingParseResult`. |
| `src/ingest/impl.py` | Extend `verify_core_design()` with visual embedding config validation. Extend `ingest_file()` result to include `visual_stored_count`. |
| `src/vector_db/__init__.py` | Re-export visual collection operations: `ensure_visual_collection`, `add_visual_documents`, `delete_visual_by_source_key`. |
| `src/vector_db/backend.py` | Add abstract methods for visual collection operations to `VectorBackend`. |
| `src/vector_db/weaviate/backend.py` | Implement visual collection operations by delegating to `visual_store.py`. |
| `pyproject.toml` | Add `colpali-engine` and `bitsandbytes` to optional dependency group `[visual]`. |

### Unchanged (Confirmed No-Touch)

| Module | Reason |
|---|---|
| `src/ingest/embedding/nodes/chunking.py` | Text chunking is unaffected by the visual track. |
| `src/ingest/embedding/nodes/vlm_enrichment.py` | VLM enrichment of figure crops is orthogonal to page-level visual embedding. |
| `src/ingest/embedding/nodes/embedding_storage.py` | Text embedding storage is complete before visual node runs. |
| `src/ingest/doc_processing/` | Phase 1 is unaffected except for the `generate_page_images` flag propagation through `parse_with_docling()`. |
| `src/retrieval/` | Retrieval-side dual-track merging is out of scope. |

---

## 8. Scope Boundaries

### In Scope

- Page image extraction from DoclingDocument (PDF, PPTX, DOCX)
- ColQwen2 model adapter with 4-bit quantization via bitsandbytes
- Page image JPEG storage in MinIO
- Weaviate visual collection schema (mean-pooled vector + JSON patch vectors)
- Visual embedding LangGraph node integrated into existing embedding pipeline
- Config flags and env vars for all behavioral knobs
- Design validation in `verify_core_design()` for visual embedding config
- `colpali-engine` dependency addition (optional group)
- `DoclingParseResult` extension with page image availability metadata

### Out of Scope

- Retrieval-side dual-track query merging / MaxSim scoring at query time
- Multimodal query handling (text query -> ColQwen2 query embedding)
- PPTX slide-boundary text chunking (separate concern, different pipeline node)
- Web console UI for visual search results
- ColQwen2 fine-tuning or domain adaptation
- Multi-GPU model parallelism
- Weaviate-native MaxSim scoring (not supported; application-side only)
- Page image OCR or text extraction from page images (Docling handles this in Phase 1)
- Benchmark or evaluation framework for visual retrieval quality

---

## 9. Open Questions

### OQ-1: ColQwen2 Model Selection
`vidore/colqwen2-v1.0` (2B, ~2GB at 4-bit) is the baseline. Should we also support `vidore/colqwen2-v1.5` or newer if available? **Recommendation**: Make `colqwen_model_name` configurable with `vidore/colqwen2-v1.0` as default. New models work automatically if API-compatible with `colpali-engine`.

### OQ-2: Page Image Resolution
ColQwen2 was trained on 448x448 pixel patches. Higher-resolution page images (e.g., 2480x3508 for A4 at 300DPI) produce more patches and more vectors. Should we resize page images before ColQwen2 inference? **Recommendation**: Yes. Add `page_image_max_dimension` config (default: 1024). Resize the longer edge to this value while preserving aspect ratio. This bounds patch count and inference time while retaining enough visual detail for retrieval.

### OQ-3: Batch Size for ColQwen2 Inference
Processing all pages of a large document (100+ pages) at once may exceed GPU memory even at 4-bit. **Recommendation**: Process pages in batches of `colqwen_batch_size` (default: 4). This bounds peak VRAM usage at the cost of slightly higher total inference time.

### OQ-4: DoclingDocument Availability for Page Images
`ConversionResult.pages` (with PIL images) may only be available on the `ConversionResult`, not on the `DoclingDocument` after serialization/deserialization via CleanDocumentStore. If the DoclingDocument is loaded from JSON (persist_docling_document=True), page images may need to be re-rendered. **Recommendation**: For visual embedding, require either (a) in-memory DoclingDocument from Phase 1 (current path -- DoclingDocument passed directly from Phase 1 to Phase 2 via `ingest_file()`), or (b) re-parse from source if DoclingDocument was loaded from JSON. The in-memory path is already the primary path. Document this constraint.

### OQ-5: Cleanup on Re-Ingestion
When a document is re-ingested (update mode), text chunks are deleted by `source_key` before re-insertion. Visual page objects need the same treatment. **Recommendation**: `visual_embedding_node` calls `delete_visual_by_source_key()` before inserting new visual objects, mirroring the text track's update-mode cleanup in `embedding_storage_node`.

---

## 10. Edge Cases

### EC-1: Document with Zero Pages
Some document types (e.g., empty files, unsupported formats) may produce a DoclingDocument with no pages. The visual embedding node returns `visual_stored_count=0` and logs `visual_embedding:no_pages`.

### EC-2: Page Image Generation Fails for Specific Pages
Docling may fail to render individual pages (corrupt content, unsupported elements). The node skips failed pages, logs warnings, and continues. Partial page coverage is acceptable.

### EC-3: ColQwen2 Model Not Downloaded
First run with `enable_visual_embedding=True` triggers model download (~4GB). The `ensure_colqwen_ready()` function (mirroring `ensure_docling_ready()`) validates model availability at pipeline start and downloads if needed. Download failure is a fatal error surfaced in `verify_core_design()`.

### EC-4: Pure Image Files (JPG, PNG)
Docling wraps standalone images as single-page documents. The visual embedding node treats this as a 1-page document. ColQwen2 embeds the single page. Text track may produce minimal or empty chunks for such files -- that is expected and correct.

### EC-5: Very Large Documents (500+ Pages)
Batch processing (4 pages per batch) bounds VRAM. MinIO storage is O(pages). Weaviate visual collection size grows linearly. No architectural issue, but ingestion time scales linearly. **Recommendation**: Log progress at 10% intervals for large documents.

### EC-6: Concurrent Ingestion of Multiple Documents
The existing pipeline processes documents sequentially within a single `ingest_directory()` run. ColQwen2 is loaded/unloaded per document. If Temporal workers enable parallel document processing in the future, ColQwen2 model loading must be mutex-protected or use a singleton pattern. For now, sequential processing avoids this issue.

### EC-7: Weaviate Visual Collection Does Not Exist
`ensure_visual_collection()` is called at the start of `visual_embedding_node`, following the same idempotent pattern as `ensure_collection()` for the text collection.

---

## 11. Data Flow Summary

```
Phase 1: parse_with_docling(generate_page_images=True)
    |
    v
DoclingDocument (with page images in memory)
    |
    +-------> Phase 2: Embedding Pipeline DAG
                |
                |-- document_storage -> chunking -> vlm_enrichment -> chunk_enrichment
                |      -> metadata_generation -> cross_reference_extraction
                |      -> knowledge_graph_extraction -> quality_validation
                |      -> embedding_storage (TEXT TRACK COMPLETE)
                |
                |-- visual_embedding (NEW NODE)
                |      1. Extract page images from state["docling_document"]
                |      2. Resize to page_image_max_dimension
                |      3. Store JPEG to MinIO: pages/{document_id}/{page_num}.jpg
                |      4. Load ColQwen2 (4-bit, colpali-engine)
                |      5. Batch-embed pages -> (mean_vector, patch_vectors) per page
                |      6. Store to Weaviate visual collection
                |      7. Unload ColQwen2
                |      8. Return visual_stored_count
                |
                |-- knowledge_graph_storage (if enabled)
                |
                v
              END
```

---

## 12. Configuration Keys

| Env Var | Type | Default | Description |
|---|---|---|---|
| `RAG_INGESTION_ENABLE_VISUAL_EMBEDDING` | bool | `false` | Master toggle for the visual embedding track |
| `RAG_INGESTION_VISUAL_TARGET_COLLECTION` | str | `RAGVisualPages` | Weaviate collection name for visual page embeddings |
| `RAG_INGESTION_COLQWEN_MODEL` | str | `vidore/colqwen2-v1.0` | HuggingFace model ID for ColQwen2 |
| `RAG_INGESTION_COLQWEN_BATCH_SIZE` | int | `4` | Pages per ColQwen2 inference batch |
| `RAG_INGESTION_PAGE_IMAGE_QUALITY` | int | `85` | JPEG quality for MinIO page image storage (1-100) |
| `RAG_INGESTION_PAGE_IMAGE_MAX_DIMENSION` | int | `1024` | Max pixel dimension (long edge) for page images before ColQwen2 |

---

## 13. Self-Critique

### Recommendation
Approach A: new `visual_embedding_node` in the existing embedding pipeline DAG, with ColQwen2 via `colpali-engine`, mean-pooled ANN + JSON patch MaxSim storage pattern.

### Strongest Counter-Argument
The mean-pooled vector loses the late-interaction property that makes ColQwen2 valuable. If the mean-pooled vector retrieves poor candidates, the MaxSim re-scoring on those candidates cannot recover relevant pages that were missed by the approximate ANN step. This is a fundamental information-theoretic limitation of the two-tier approach.

### Why the Recommendation Stands
The alternative -- storing all 500-1200 patch vectors per page as individual Weaviate objects and doing full MaxSim at query time -- would require scanning the entire visual collection for every query (no ANN shortcut), making it O(N * P) where N is total pages and P is patches per page. For even moderate collections (1000 documents * 10 pages * 800 patches = 8M vectors), this is prohibitively slow. The mean-pooled approximation is the standard approach used in production ColPali deployments (e.g., Vespa's ColPali integration uses the same two-tier pattern). Mean pooling preserves enough signal for top-100 candidate retrieval, and MaxSim on 100 candidates is fast (<50ms). The quality degradation vs full MaxSim is typically <5% on standard benchmarks (ViDoRe). This is the right engineering tradeoff for a local deployment on consumer hardware.
