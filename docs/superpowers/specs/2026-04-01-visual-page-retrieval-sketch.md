# Visual Page Embedding & Retrieval Pipeline — Design Sketch

| Field | Value |
|---|---|
| Date | 2026-04-01 |
| Status | APPROVED (brainstorm complete) |
| Scope | EXTENSION to existing ingestion + retrieval pipelines |
| Produced by | Autonomous brainstorm subagent (Claude) |

---

## 1. Goal Statement

Add a visual retrieval path to the RAG system so that text queries can return visually-matched document pages alongside traditional text chunk results. The ingestion side (Docling page image extraction, ColQwen2 embedding, MinIO page image storage, Weaviate visual collection indexing) is already implemented. This design focuses on the **retrieval side** -- adding a visual search path to `RAGChain` that embeds text queries via ColQwen2's text encoder, searches the `RAGVisualPages` collection, and returns visual page results with presigned MinIO image URLs. Secondary goals include handling standalone image files and PPTX slides as first-class page sources, and ensuring the visual track is fully config-driven and does not impact text-track performance when disabled.

---

## 2. Chosen Approach: Visual Retrieval as an Additive Track in RAGChain

**Approach selected:** Add a `visual_search` capability to the existing `RAGChain` class that queries the `RAGVisualPages` Weaviate collection using ColQwen2's text encoder. Visual results are returned alongside text results in `RAGResponse`. The visual track is opt-in via configuration and loads ColQwen2's text encoder lazily on first visual query.

**Why this approach over alternatives:**

- **Over separate service (Approach 2):** A separate visual search service adds operational complexity (another process, another GPU allocation, another health check) without proportional benefit. The stakeholder prefers single shared infrastructure. The existing `RAGChain` already loads multiple GPU models (BGE-M3, BGE-reranker) and manages their lifecycle -- adding another is incremental, not architectural.

- **Over metadata-only lookup (Approach 3):** Metadata-only lookup cannot find visually-relevant pages when the text representation is poor (charts, diagrams, PPTX with minimal text). ColQwen2 was chosen specifically because it captures visual semantics that text embeddings miss. Reducing visual retrieval to a text-match side-effect would negate the value of the entire visual embedding pipeline.

**Key insight for VRAM management:** At query time, only the ColQwen2 **text encoder** is needed (not the vision encoder). The text encoder at 4-bit quantization is significantly smaller (~1-1.5 GB) than the full model (~3-4 GB). This fits within RTX 2060 headroom alongside BGE-M3 and the reranker.

---

## 3. Key Decisions

### 3.1 Model Choice: ColQwen2 (Retain, No Change)

ColQwen2 (`vidore/colqwen2-v1.0`) is already implemented in `src/ingest/support/colqwen.py` with 4-bit BitsAndBytes quantization. The ingestion pipeline uses the full model (vision + text encoders) to embed page images. The retrieval pipeline will use **only the text encoder** to embed text queries into the same 128-dim space.

- **No model switch to ColSmol.** ColSmol has lower embedding quality and would require re-embedding all existing pages. ColQwen2 is already deployed and produces 128-dim vectors that match the existing Weaviate schema.
- **Config key:** `RAG_INGESTION_COLQWEN_MODEL` (existing, reused at retrieval time).

### 3.2 Storage Architecture: No Changes

MinIO page image storage is already implemented:
- Bucket: `rag-documents` (default `MINIO_BUCKET`)
- Key pattern: `pages/{document_id}/{page_number:04d}.jpg`
- JPEG at configurable quality (`RAG_INGESTION_PAGE_IMAGE_QUALITY`, default 85)
- Max dimension: `RAG_INGESTION_PAGE_IMAGE_MAX_DIMENSION` (default 1024px)
- Functions: `store_page_images()`, `delete_page_images()` in `src/db/minio/store.py`

No new storage subsystem needed.

### 3.3 Weaviate Visual Collection: No Schema Changes

The `RAGVisualPages` collection is already defined in `src/vector_db/weaviate/visual_store.py`:
- Named vector `mean_vector`: 128-dim, HNSW index, cosine distance
- Properties: `document_id`, `page_number`, `source_key`, `source_uri`, `source_name`, `tenant_id`, `total_pages`, `page_width_px`, `page_height_px`, `minio_key`, `patch_vectors`
- Functions: `ensure_visual_collection()`, `add_visual_documents()`, `delete_visual_by_source_key()`

**New requirement:** Add a `visual_search()` function to `visual_store.py` that performs nearest-neighbor search on the `mean_vector` named vector. This is the primary new storage-layer addition.

### 3.4 Pipeline Integration: RAGChain Extension

The visual retrieval path integrates into `RAGChain` (in `src/retrieval/pipeline/rag_chain.py`) as follows:

1. **Initialization:** If `RAG_VISUAL_RETRIEVAL_ENABLED=true`, the RAGChain constructor notes this but does NOT load ColQwen2 immediately (lazy loading).
2. **First visual query:** On the first query that requests visual results, load ColQwen2's text encoder with 4-bit quantization. Cache the model for subsequent queries.
3. **Query flow:** After the standard text retrieval + reranking stages complete, if visual retrieval is enabled:
   a. Embed the processed query text via ColQwen2 text encoder -> 128-dim vector
   b. Search `RAGVisualPages` collection using the mean_vector named vector
   c. For each visual result, generate a presigned MinIO URL for the page image
   d. Attach visual results to `RAGResponse`
4. **Unload:** On `RAGChain.close()`, unload the ColQwen2 text encoder.

This runs **after** text retrieval, not in parallel, to avoid VRAM contention during the text embedding/reranking GPU operations.

### 3.5 Page Definition Rules

| Source Format | Page Definition | Handler |
|---|---|---|
| PDF | Each PDF page = 1 page image | Docling `ConversionResult.pages` |
| PPTX | Each slide = 1 page image | Docling `ConversionResult.pages` |
| DOCX | Each rendered page = 1 page image | Docling `ConversionResult.pages` |
| Standalone image (PNG/JPEG/TIFF) | The image itself = 1 page | Direct PIL load (bypass Docling) |
| Multi-page TIFF | Each frame = 1 page | PIL frame iteration |

**Standalone image handling:** Docling may not produce page images for standalone image files. The `visual_embedding_node` should detect when the source file is an image format and use the file itself as the single page image, bypassing Docling's page extraction. This requires a small extension to `_extract_page_images()`.

### 3.6 Document-Page Linkage Metadata

Already fully implemented. The linkage chain is:

```
Source Document (source_key)
  -> MinIO document (document_id, built from source_key)
    -> MinIO page images (pages/{document_id}/{page_num:04d}.jpg)
  -> Weaviate text chunks (RAGDocuments, source_key property)
  -> Weaviate visual pages (RAGVisualPages, source_key + document_id + page_number)
```

At retrieval time, a visual result carries `document_id`, `page_number`, `source_key`, and `minio_key` -- sufficient to link back to the source document and generate a presigned URL.

### 3.7 Single Instance Decision: Retain Single Instance

- **Weaviate:** Single embedded instance with multiple collections (`RAGDocuments`, `RAGVisualPages`). Access control via `tenant_id` property filtering. No change.
- **MinIO:** Single instance with a single bucket (`rag-documents`). Page images stored under a `pages/` key prefix, documents under root. No change.

This aligns with the stakeholder preference: "Prefer single-instance shared infrastructure over per-feature instances unless access control demands otherwise."

### 3.8 Visual Retrieval Response Schema

Extend `RAGResponse` with an optional `visual_results` field:

```python
@dataclass
class VisualPageResult:
    """A visually-matched document page returned from visual retrieval."""
    document_id: str
    page_number: int
    source_key: str
    source_name: str
    score: float           # cosine similarity
    page_image_url: str    # presigned MinIO URL
    total_pages: int
    page_width_px: int
    page_height_px: int

@dataclass
class RAGResponse:
    # ... existing fields ...
    visual_results: Optional[List[VisualPageResult]] = None
```

---

## 4. Component/Module List

### Existing (no changes needed)
- `src/ingest/support/docling.py` -- page image extraction (complete)
- `src/ingest/support/colqwen.py` -- ColQwen2 model adapter (complete)
- `src/ingest/embedding/nodes/visual_embedding.py` -- ingestion node (complete)
- `src/ingest/embedding/workflow.py` -- graph with visual_embedding node (complete)
- `src/ingest/embedding/state.py` -- state with visual fields (complete)
- `src/db/minio/store.py` -- page image storage (complete)
- `src/vector_db/weaviate/visual_store.py` -- visual collection CRUD (needs search addition)
- `src/vector_db/weaviate/backend.py` -- backend with visual methods (complete)
- `src/vector_db/__init__.py` -- public API with visual exports (complete)

### New or Modified

| Module | Change Type | Description |
|---|---|---|
| `src/vector_db/weaviate/visual_store.py` | **MODIFY** | Add `visual_search()` function: nearest-neighbor search on `mean_vector` named vector |
| `src/vector_db/weaviate/backend.py` | **MODIFY** | Add `search_visual()` backend method delegating to `visual_search()` |
| `src/vector_db/backend.py` | **MODIFY** | Add `search_visual()` to the `VectorBackend` abstract contract |
| `src/vector_db/__init__.py` | **MODIFY** | Export `visual_search()` through the public API |
| `src/retrieval/common/schemas.py` | **MODIFY** | Add `VisualPageResult` dataclass and `visual_results` field to `RAGResponse` |
| `src/retrieval/pipeline/rag_chain.py` | **MODIFY** | Add visual retrieval path: lazy ColQwen2 text encoder load, visual search, presigned URL generation |
| `src/ingest/support/colqwen.py` | **MODIFY** | Add `embed_text_query()` function that uses ColQwen2's text encoder only (for query-time use) |
| `config/settings.py` | **MODIFY** | Add `RAG_VISUAL_RETRIEVAL_ENABLED`, `RAG_VISUAL_RETRIEVAL_LIMIT`, `RAG_VISUAL_RETRIEVAL_MIN_SCORE` config keys |
| `server/schemas.py` | **MODIFY** | Add `VisualPageResult` to API response schema |
| `src/ingest/embedding/nodes/visual_embedding.py` | **MODIFY** | Extend `_extract_page_images()` to handle standalone image files |

---

## 5. Scope Boundary

### In Scope
- Visual search function in Weaviate visual store (nearest-neighbor on `mean_vector`)
- ColQwen2 text encoder loading and text query embedding at retrieval time
- Visual retrieval integration in `RAGChain` (lazy load, search, presigned URLs)
- `VisualPageResult` schema in retrieval response
- Config keys for visual retrieval toggle, result limit, and minimum score threshold
- Standalone image file handling in the visual embedding ingestion node
- API response schema extension for visual results

### Out of Scope
- Image-to-image queries (user uploads an image to find similar pages)
- Visual reranking (reranking visual results using a cross-encoder)
- Patch-level retrieval (using individual patch vectors instead of mean_vector for finer-grained matching)
- Multi-vector MaxSim scoring (ColBERT-style late interaction using all patch vectors)
- Visual result summarization (generating text descriptions of retrieved page images at query time)
- UI rendering of visual results (frontend concern, not pipeline concern)
- Multi-instance Weaviate or MinIO deployment
- ColSmol or alternative model support
- OCR fallback for standalone images without Docling support

---

## 6. Open Questions

1. **ColQwen2 text encoder isolation:** Can `colpali_engine.models.ColQwen2` load only the text encoder (without the vision encoder) to save VRAM? If not, the full model must be loaded at query time, which is ~3-4 GB at 4-bit. This needs a code experiment during implementation. Fallback: load full model, accept the VRAM cost, and unload after visual queries complete.

2. **Patch-level MaxSim scoring (future consideration):** The `patch_vectors` are stored as JSON text in Weaviate but are not used for retrieval. ColQwen2's native scoring uses MaxSim (max of cosine similarities between query token vectors and page patch vectors). Mean-pooling loses fine-grained information. Should a future iteration add MaxSim reranking of top-k visual results? This is explicitly out of scope but should be documented as a known quality improvement path.

3. **Concurrent GPU model loading:** At query time, BGE-M3 and BGE-reranker are already loaded. Adding ColQwen2 means 3 GPU models resident simultaneously. On RTX 2060 (6GB), this may require sequential loading (embed text -> unload BGE -> load ColQwen2 -> visual search -> unload ColQwen2 -> reload BGE for next query). Implementation should profile actual VRAM usage and decide between persistent and on-demand ColQwen2 loading.

4. **Visual result deduplication:** If the same document has many similar-looking pages, visual search may return several pages from the same document. Should results be deduplicated per-document (best page per document) or returned raw?

---

## 7. Deliverable Sizing

The actual new work is narrower than the 7-deliverable list in the goal statement suggests:

| Deliverable | Status | Effort |
|---|---|---|
| Page image extraction (Docling) | COMPLETE | - |
| MinIO page image storage | COMPLETE | - |
| Visual embedding pipeline (ingestion) | COMPLETE | - |
| Weaviate visual collection management | COMPLETE (needs search) | Small |
| ColQwen2 text query embedding | NEW | Medium |
| Visual retrieval in RAGChain | NEW | Medium |
| Response schema extension | NEW | Small |
| Config keys | NEW | Small |
| API schema extension | NEW | Small |
| Standalone image handling (ingestion) | NEW | Small |

Total estimated effort: **1 pipeline run** (not split). The new work is concentrated in 2-3 modules and follows established patterns.
