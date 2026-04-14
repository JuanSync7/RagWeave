# Visual Page Retrieval Pipeline — Specification Summary

> **Companion spec:** `VISUAL_RETRIEVAL_SPEC.md` (v0.1)
> **Summary purpose:** Digest of intent, scope, structure, and key decisions. Not a replacement for the spec.
> **See also:** `VISUAL_RETRIEVAL_DESIGN.md`, `VISUAL_RETRIEVAL_IMPLEMENTATION.md`, `VISUAL_RETRIEVAL_ENGINEERING_GUIDE.md`

---

## 1) Generic System Overview

### Purpose

Documents with rich visual content — charts, diagrams, tables rendered as images, presentation slides, and layout-dependent pages — lose semantic meaning when reduced to extracted text. A visual page retrieval system solves this gap by enabling text queries to surface document pages on the basis of visual similarity rather than textual overlap. Without it, users cannot discover visually-relevant pages even when those pages have been indexed. The system is an additive enhancement to an existing text-based retrieval pipeline: when enabled, it runs as a second retrieval track alongside the text track and appends page-level results to the unified response.

### How It Works

When a query arrives with visual retrieval active, the text track runs first and to completion — query reformulation, semantic embedding, hybrid search, and reranking all execute before the visual track begins. Once text results are ready, the visual track takes the reformulated query text and encodes it into a fixed-dimensional vector using a cross-modal vision-language encoder. This encoding maps the query into the same vector space used during document ingestion, where page images were embedded as mean-pooled patch vectors and stored in a dedicated vector index.

The encoded query vector is submitted to a nearest-neighbor search on the visual index, returning the highest-scoring pages ranked by cosine similarity. A configurable score threshold filters out low-confidence matches, and a configurable result limit caps the number of pages returned. For each matched page, a time-limited access URL is generated from the object store using the page's stored object key — this URL allows callers to retrieve the page image directly without additional credentials.

The final response assembles text results and visual page results into a unified structure. Both are returned together; if the visual track fails at any stage, text results are returned intact with an empty visual results list. When visual retrieval is disabled, the visual track is entirely bypassed with zero overhead.

### Tunable Knobs

- **Enable/disable toggle:** Controls whether the visual track runs at all. Defaults to off; operators must explicitly enable it after confirming the visual index is populated and sufficient GPU memory is available.
- **Result limit:** Controls the maximum number of visual page results per query. Operators tune this to balance result coverage against response payload size.
- **Score threshold:** Sets the minimum similarity required for a page to appear in results. Raising this threshold improves precision; lowering it improves recall. The appropriate value depends on corpus characteristics.
- **URL expiry window:** Controls how long the generated access URLs remain valid. Shorter windows reduce exposure; longer windows accommodate slower clients or session patterns.
- **Stage time budget:** Caps the wall-clock time the visual track may consume. When the budget is exhausted, whatever results have been retrieved so far are returned rather than blocking the entire response.

### Design Rationale

Sequential execution between the text and visual tracks is a deliberate choice to avoid GPU memory contention on constrained hardware. The two tracks each require GPU-resident models; running them concurrently risks out-of-memory failures. By running them in sequence, the system guarantees stability at the cost of additive latency.

Lazy model loading was chosen over startup loading because the visual encoder is large and consumes significant GPU memory. Loading it at startup would penalize all deployments, even those that receive no visual queries. Lazy loading defers the allocation until the first visual query is actually issued, and the loaded model is then cached for subsequent queries.

The same model must be used for query encoding as was used for page image encoding during ingestion. Using different models would produce embeddings in incompatible vector spaces and degrade retrieval quality unpredictably. The configuration shares a single model identifier between ingestion and retrieval to eliminate this class of misconfiguration.

### Boundary Semantics

**Entry point:** A user text query arrives at the retrieval pipeline with visual retrieval enabled via configuration. The query has already passed through the text track's reformulation stage, and the reformulated query text is the input to the visual track.

**Exit point:** The pipeline response includes both text retrieval results (unchanged from the pre-visual baseline) and a list of visual page results, each carrying a similarity score, page-level metadata, and a time-limited URL for the page image.

**State maintained:** The cross-modal model is loaded lazily and cached as a pipeline-level instance after first use. It is released during pipeline shutdown.

**State discarded:** Query vectors and intermediate search results are not persisted. The visual track is stateless across queries beyond the cached model.

**Responsibility boundary:** This system ends when the unified response is returned to the API layer. Page image ingestion, visual index construction, and UI rendering of page images are outside this system's scope.

---

## 2) Header

| Field | Value |
|-------|-------|
| Companion spec | `VISUAL_RETRIEVAL_SPEC.md` |
| Spec version | 0.1 (Draft) |
| Domain | Information Retrieval |
| Summary date | 2026-04-10 |

---

## 3) Scope and Boundaries

**Entry point:** A text query arrives at the RAG pipeline with visual retrieval enabled via configuration.

**Exit point:** The pipeline response includes a list of visually-matched document pages, each with a similarity score and a time-limited presigned URL for the page image.

### In Scope

- Configuration keys for enabling and tuning the visual retrieval track
- Cross-modal text query encoding to produce a vector compatible with the visual index
- Nearest-neighbor search on the visual page index with limit and score threshold filtering
- Tenant-scoped filtering of visual search results
- Time-limited presigned URL generation for matched page images
- `VisualPageResult` typed schema for visual retrieval results
- Extension of the unified response schema to include an optional visual results list
- Integration of the visual track into the retrieval pipeline orchestrator (sequential, post-text-track)
- Lazy loading and lifecycle management of the cross-modal encoder model
- Extension of the server API response schema to surface visual results to API clients
- Stage timing observability, structured logging, and distributed tracing spans for the visual track
- Graceful degradation when any visual track component fails

### Out of Scope (already implemented — ingestion side)

- Page image extraction from PDF, PPTX, DOCX
- Visual image embedding and mean-pooling during ingestion
- MinIO page image storage and deletion
- Visual collection schema creation and document insertion/deletion
- Configuration keys for visual embedding during ingestion

### Out of Scope (not planned)

- Image-to-image queries
- Visual reranking via cross-encoder
- Patch-level MaxSim retrieval using individual patch vectors
- Multi-vector late interaction scoring
- Visual result summarization at query time
- UI rendering of visual results
- Multi-instance vector store or object store for visual workloads
- Alternative visual embedding model support
- OCR fallback for pages without text extraction

---

## 4) Architecture / Pipeline Overview

```
Text Query (from user)
    |
    v
+------------------------------------------+
|  TEXT TRACK (unchanged, runs first)       |
|  Query Processing -> Semantic Embedding   |
|  -> Hybrid Search -> Reranking            |
+------------------+-----------------------+
                   | text results ready
                   v
       +--- visual retrieval enabled? ---+
       | NO                          YES |
       v                                 v
  Return text              +-------------------------------+
  results only             | [1] QUERY ENCODING (optional) |
                           |     Text -> 128-dim vector    |
                           |     (lazy model load on first)|
                           +---------------+---------------+
                                           |
                                           v
                           +-------------------------------+
                           | [2] VISUAL INDEX SEARCH       |
                           |     Near-vector search,       |
                           |     cosine similarity,        |
                           |     limit + score threshold   |
                           +---------------+---------------+
                                           |
                                           v
                           +-------------------------------+
                           | [3] PRESIGNED URL GENERATION  |
                           |     Per matched page,         |
                           |     time-limited access URL   |
                           +---------------+---------------+
                                           |
                                           v
                           +-------------------------------+
                           | [4] RESPONSE ASSEMBLY         |
                           |     Attach visual_results to  |
                           |     unified RAGResponse       |
                           +-------------------------------+
```

| Stage | Input | Output |
|-------|-------|--------|
| Query encoding | Reformulated query text | 128-dim float vector |
| Visual index search | Query vector, limit, score threshold, tenant | Ranked page objects with metadata |
| Presigned URL generation | Object key per matched page | Time-limited access URL |
| Response assembly | Text results + visual page results | Unified response with both |

---

## 5) Requirement Framework

- **Priority keywords:** RFC 2119 — MUST (non-conformant without it), SHOULD (recommended, may be omitted with justification), MAY (optional)
- **ID convention:** `FR-xxx` for functional requirements, `NFR-xxx` for non-functional requirements
- **Each requirement includes:** Description, Rationale, Acceptance Criteria
- **Total requirements:** 37 (32 MUST, 5 SHOULD, 0 MAY)

### ID Ranges

| ID Range | Component |
|----------|-----------|
| FR-1xx | Configuration |
| FR-2xx | Cross-modal Text Query Encoding |
| FR-3xx | Visual Index Search |
| FR-4xx | Presigned URL Generation |
| FR-5xx | Retrieval Schema Extension |
| FR-6xx | Pipeline Orchestrator Integration |
| FR-7xx | Server API Schema Extension |
| NFR-9xx | Non-Functional Requirements |

---

## 6) Functional Requirement Domains

**Configuration (FR-100 to FR-199):** Defines the full set of environment-variable-backed configuration keys that control visual retrieval behavior: enable/disable toggle, result limit, score threshold, URL expiry window, model identifier reuse, and startup validation with fail-fast error reporting.

**Cross-modal Text Query Encoding (FR-200 to FR-299):** Specifies the function that encodes a text query into a 128-dimensional float vector using the same pooling strategy as ingestion. Covers determinism, empty-input handling, and typed exception propagation for model load failures versus inference failures.

**Visual Index Search (FR-300 to FR-399):** Specifies the search function over the visual index collection: nearest-neighbor search using cosine similarity on the mean-pooled named vector, parameterized limit and score threshold, tenant-scoped filtering, configurable collection name, exclusion of stored patch vectors from results, and integration into the backend abstraction layer.

**Presigned URL Generation (FR-400 to FR-499):** Specifies a new function for generating time-limited access URLs from raw object keys, distinct from the existing document URL function which applies key transformation. Covers defaulting to configured bucket and expiry.

**Retrieval Schema Extension (FR-500 to FR-599):** Defines the `VisualPageResult` typed contract (document ID, page number, source metadata, cosine score, access URL, page dimensions) and extends the unified response schema with an optional visual results field that defaults to null when the track is disabled.

**Pipeline Orchestrator Integration (FR-600 to FR-699):** Covers full lifecycle management within the retrieval orchestrator: sequential post-text-track execution, lazy model load and caching, use of the reformulated query as encoding input, presigned URL attachment per result, tenant pass-through, stage timing recording, model cleanup on shutdown, zero-overhead bypass when disabled, and stage time budget with graceful partial-result degradation.

**Server API Schema Extension (FR-700 to FR-799):** Defines the Pydantic response model for visual page results and extends the query response model with an optional visual results list for backward-compatible API serialization.

---

## 7) Non-Functional and Security Themes

**Performance:** The visual track (warm model) targets sub-2-second end-to-end latency across encoding, search, and URL generation. Cold-start latency on first query (model load) may be significantly higher and is acceptable as a one-time cost per pipeline lifecycle.

**GPU memory budget:** All GPU-resident models must coexist within a strict VRAM ceiling on constrained hardware. The cross-modal encoder's memory footprint at reduced precision is a key constraint, with open questions around encoder isolation and on-demand load/unload strategies documented in the spec.

**Graceful degradation:** Every failure mode in the visual track (model load failure, encoding failure, search failure, URL generation failure, missing collection) results in text results being returned normally with an empty visual results list. Visual track failures never propagate to text results.

**Configuration externalization:** All thresholds, limits, and behavioral parameters must be environment-variable-backed. No literal values may appear in pipeline code.

**Observability:** The visual track emits distributed tracing spans for each sub-stage (model load, encoding, search, URL generation), records stage timing in the response, and logs at INFO and DEBUG levels for operational and diagnostic visibility.

**Tenant isolation:** Visual search results are always scoped to the requesting tenant, matching the isolation guarantee of the text track.

---

## 8) Design Principles

| Principle | Description |
|-----------|-------------|
| **Additive integration** | The visual track adds alongside the text track without modifying text-track behavior. When disabled, the system is identical to the pre-visual baseline. |
| **Lazy resource allocation** | The cross-modal encoder is loaded only on the first visual query, deferring GPU memory allocation until actually needed. |
| **Sequential GPU access** | Visual retrieval stages execute after all text track stages complete to prevent GPU memory contention. |
| **Configuration-driven behavior** | All visual retrieval behavior is controlled by typed configuration keys with sensible defaults; nothing is hardcoded. |
| **Single-instance infrastructure** | The visual track reuses existing vector store and object store instances; no new infrastructure services are introduced. |

---

## 9) Key Decisions

- **Sequential, not concurrent, GPU track execution** — prevents memory contention at the cost of additive latency; required for stable operation on constrained hardware.
- **Shared model identifier between ingestion and retrieval** — a single configuration key governs both sides; separate keys would allow encoder mismatch, producing incompatible vector spaces.
- **Mean-pooling for query vectors** — matches the mean-pooling strategy used for page image vectors during ingestion; alternative pooling would create a representational distribution mismatch.
- **Score threshold filtering at search time, not client-side** — delegates filtering to the vector store query engine for efficiency; avoids fetching and discarding low-quality results over the network.
- **Null vs. empty list distinction for visual_results** — `null` signals visual retrieval is disabled; an empty list signals visual retrieval ran but found no qualifying results. This distinction is load-bearing for API clients.
- **Patch vectors excluded from search results** — stored for potential future use but excluded from retrieval responses to avoid inflating response payload with hundreds of kilobytes of vector data per page.
- **Stage time budget with partial-result fallback** — the visual track returns whatever it has retrieved when the budget is exhausted rather than blocking the full response, protecting overall pipeline latency.

---

## 10) Acceptance and Evaluation

The spec defines six system-level acceptance criteria:

| Criterion | What Is Verified |
|-----------|-----------------|
| Text track unaffected when visual disabled | Zero latency delta vs. pre-visual baseline |
| Valid presigned URLs | All page image URLs resolve to JPEG images |
| Tenant isolation | No cross-tenant visual results |
| Graceful degradation | Text results returned for every visual track failure mode |
| Configuration-driven toggle | Restart with changed enable flag activates/deactivates track without code changes |
| VRAM budget compliance | All GPU models coexist within the GPU memory ceiling |

The spec includes a requirements traceability matrix mapping all 37 requirements to sections and priority levels.

---

## 11) External Dependencies

### Required

| Dependency | Role |
|------------|------|
| Cross-modal vision-language encoder | Query text encoding into the visual vector space; must match the model used during ingestion |
| Vector store (visual collection) | Indexed visual page embeddings; must be populated by the ingestion pipeline before retrieval can return results |
| Object store | Stores page images; used for presigned URL generation |

### Assumptions

- GPU with sufficient VRAM is present; the encoder cannot load without it
- The visual collection exists in the vector store and contains indexed data from the ingestion pipeline
- Required quantization and model loading libraries are installed
- Object store is running and page images are stored at the expected key pattern

### Downstream Contract

The API server layer receives the unified response and must map `VisualPageResult` instances to the `VisualPageResultResponse` Pydantic model for JSON serialization and OpenAPI schema generation.

---

## 12) Companion Documents

| Document | Relationship |
|----------|-------------|
| `VISUAL_RETRIEVAL_SPEC.md` | This summary's companion — the authoritative requirements source |
| Visual Embedding Ingestion Spec | Companion ingestion-side spec; defines the data this retrieval spec queries |
| `VISUAL_RETRIEVAL_DESIGN.md` | Technical design document with task decomposition and code contracts |
| `VISUAL_RETRIEVAL_IMPLEMENTATION.md` | Implementation guide and source-of-truth for how requirements were realized |
| `VISUAL_RETRIEVAL_ENGINEERING_GUIDE.md` | Post-implementation reference for architecture, decisions, and troubleshooting |
| `VISUAL_RETRIEVAL_TEST_DOCS.md` | Test planning document defining what to verify for each module |
| `config/settings.py` | Canonical location for all configuration keys referenced in this spec |

The spec also notes an appendix with open questions on encoder isolation, VRAM coexistence profiling, visual result deduplication, and patch-level MaxSim scoring as a future improvement path.

---

## 13) Sync Status

| Field | Value |
|-------|-------|
| Spec version | 0.1 (Draft) |
| Summary aligned as of | 2026-04-10 |
| Coverage | All 37 requirements, all 8 sections, all appendices |
