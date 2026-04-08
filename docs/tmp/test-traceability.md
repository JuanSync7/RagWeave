### FR-to-Test Traceability Matrix

## Configuration (FR-101 to FR-109)

| FR | Priority | AC Summary | Module Test | Integration Test |
|---|---|---|---|---|
| FR-101 | MUST | enable_visual_embedding flag; disabled node short-circuits with zero overhead | module_config_state — default False, module_visual_node — disabled short-circuit | integration_disabled |
| FR-102 | MUST | visual_target_collection configurable, defaults to "RAGVisualPages" | module_config_state — default value | integration_happy |
| FR-103 | MUST | colqwen_model_name configurable, defaults to "vidore/colqwen2-v1.0" | module_config_state — default model name | integration_happy |
| FR-104 | MUST | colqwen_batch_size configurable int, range 1-32, default 4 | module_config_state — range validation, module_colqwen — batch inference | integration_happy — 3 batches for 10 pages |
| FR-105 | MUST | page_image_quality configurable int, default 85, range 1-100 | module_config_state — range validation, module_minio — JPEG quality | integration_happy |
| FR-106 | MUST | page_image_max_dimension configurable int, default 1024, range 256-4096 | module_config_state — range validation, module_visual_node — resize applied | integration_happy |
| FR-107 | MUST | generate_page_images derived from enable_visual_embedding; passed to parse_with_docling | module_config_state — property derivation, module_docling — parameter gating | integration_happy — 10 images extracted |
| FR-108 | MUST | config validation at startup; visual requires Docling, range checks enforced | module_config_state — _check_visual_embedding_config all 4 rules | integration_happy |
| FR-109 | MUST | all params as RAG_INGESTION_* env vars (6 env vars) | module_config_state — all 6 env vars mapped | integration_happy |

## Page Image Extraction (FR-201 to FR-205)

| FR | Priority | AC Summary | Module Test | Integration Test |
|---|---|---|---|---|
| FR-201 | MUST | extract page images from docling_document, 1-indexed page numbers | module_docling — 10 images for 10-page PDF, module_visual_node — extract from state + fallback | integration_happy — 10 pages extracted |
| FR-202 | MUST | resize so longer edge ≤ page_image_max_dimension, preserve aspect ratio | module_visual_node — resize LANCZOS | integration_happy |
| FR-203 | MUST | zero extractable pages → short-circuit, visual_stored_count=0, log no_pages | module_visual_node — zero pages short-circuit | Not covered — known gap: requires synthetic doc with zero pages |
| FR-204 | MUST | record original dimensions (page_width_px, page_height_px) in Weaviate | module_visual_node — original dims in Weaviate dict | integration_happy |
| FR-205 | SHOULD | convert page images to RGB before processing | module_docling — RGB conversion from RGBA | Not covered — known gap: live PDF mocking with RGBA needed |

## ColQwen2 Embedding (FR-301 to FR-307)

| FR | Priority | AC Summary | Module Test | Integration Test |
|---|---|---|---|---|
| FR-301 | MUST | load ColQwen2 with 4-bit quant via bitsandbytes, after MinIO storage | module_colqwen — 4-bit load | integration_happy |
| FR-302 | MUST | batch inference at colqwen_batch_size; each page → 128-dim patches (500-1200) | module_colqwen — batch count, page numbering, patch range | integration_happy — 3 batches for 10 pages |
| FR-303 | MUST | mean-pool all patch vectors → single 128-dim float32 mean_vector | module_colqwen — mean vector arithmetic mean, 128-dim | integration_happy |
| FR-304 | MUST | retain raw patch_vectors as JSON-serializable list[list[float]] | module_colqwen — JSON serializable, size range | integration_happy |
| FR-305 | MUST | unload model + release GPU VRAM after all pages processed (always via finally) | module_colqwen — GPU release in finally block, module_visual_node — unload called in finally despite partial | integration_partial |
| FR-306 | SHOULD | log inference progress ~every 10% for docs >10 pages | module_colqwen — progress logging intervals | Not covered — known gap: interval exactness flaky in CI |
| FR-307 | MUST | per-page inference failures → warning log + skip page, continue remaining | module_colqwen — per-page skip with warning, module_visual_node — per-item error boundary | integration_partial — pages 3,7 skipped with warning |

## MinIO Page Image Storage (FR-401 to FR-405)

| FR | Priority | AC Summary | Module Test | Integration Test |
|---|---|---|---|---|
| FR-401 | MUST | key pattern pages/{document_id}/{page_number:04d}.jpg, 1-indexed, zero-padded | module_minio — key pattern 1-indexed zero-padded | integration_happy — 10 MinIO keys pattern |
| FR-402 | MUST | JPEG encoding at configured quality, using resized image | module_minio — JPEG quality, buffer correctness | Not covered — known gap: JPEG byte validity needs real PIL+MinIO integration |
| FR-403 | MUST | MinIO storage before ColQwen2 model load | module_visual_node — ordering via orchestration (caller responsibility) | integration_happy — MinIO called before model load |
| FR-404 | MUST | reuse existing MinIO client and bucket, pages/ prefix | module_minio — pages/ prefix, same bucket | integration_happy |
| FR-405 | MUST | delete existing page images before storing new ones (update mode cleanup) | module_minio — delete-before-insert delete_page_images | integration_happy — pre-cleanup called |

## Weaviate Visual Collection (FR-501 to FR-507)

| FR | Priority | AC Summary | Module Test | Integration Test |
|---|---|---|---|---|
| FR-501 | MUST | dedicated collection distinct from text collection | module_visual_store — dedicated collection | integration_happy — collection created |
| FR-502 | MUST | idempotent ensure_visual_collection (create if absent, no-op if present) | module_visual_store — idempotent create | integration_happy |
| FR-503 | MUST | 11 scalar properties per page object (document_id, page_number, source_key, source_uri, source_name, tenant_id, total_pages, page_width_px, page_height_px, minio_key, patch_vectors) | module_visual_store — all 11 properties | integration_happy — document dict properties |
| FR-504 | MUST | mean_vector named vector, 128-dim HNSW cosine, for ANN | module_visual_store — mean_vector named vector 128-dim | integration_happy |
| FR-505 | MUST | patch_vectors as JSON TEXT property, skip_vectorization=True | module_visual_store — patch_vectors TEXT skip_vectorization | Not covered — known gap: patch_vectors round-trip needs live Weaviate |
| FR-506 | MUST | delete_visual_by_source_key for update mode cleanup | module_visual_store — delete by source_key, module_visual_node — per-item error boundary | integration_happy — pre-cleanup called |
| FR-507 | MUST | batch insert add_visual_documents | module_visual_store — batch insert, count returned | integration_happy — 10 docs inserted, integration_partial — 8 docs inserted |

## Pipeline Integration (FR-601 to FR-606)

| FR | Priority | AC Summary | Module Test | Integration Test |
|---|---|---|---|---|
| FR-601 | MUST | visual_embedding node in LangGraph DAG, after embedding_storage, before knowledge_graph_storage | module_config_state — DAG edges, node count=10, module_visual_node — node wired in DAG | integration_happy — node wired correctly |
| FR-602 | MUST | EmbeddingPipelineState extended with visual_stored_count (int) and page_images (Optional[List[Any]]) | module_config_state — EmbeddingPipelineState new fields | integration_happy |
| FR-603 | MUST | short-circuit on False flag, None docling_document, zero pages; log reason; visual_stored_count=0 | module_visual_node — 3 short-circuit conditions, module_config_state — disabled path | integration_disabled — skipped:disabled log entry |
| FR-604 | MUST | "visual_embedding" in PIPELINE_NODE_NAMES, between embedding_storage and knowledge_graph_storage | module_config_state — PIPELINE_NODE_NAMES count=15, ordering | Not covered — known gap: graph introspection API stability |
| FR-605 | MUST | IngestFileResult.visual_stored_count field, default 0 | module_config_state — IngestFileResult.visual_stored_count default=0, module_visual_node — visual_stored_count always int | integration_happy — visual_stored_count=10, integration_partial — visual_stored_count=8 |
| FR-606 | MUST | page_images set to None after node completes (memory cleanup) | module_visual_node — page_images=None on return | integration_happy, integration_disabled, integration_partial |

## Format-Specific Handling (FR-701 to FR-705)

| FR | Priority | AC Summary | Module Test | Integration Test |
|---|---|---|---|---|
| FR-701 | MUST | PDF support, one image per page, correct ordering | module_docling — 10 images for 10-page PDF, module_visual_node — processing log entries | integration_happy — PDF → 10 pages |
| FR-702 | MUST | PPTX support, one image per slide, correct ordering | module_docling — slide extraction via Docling | Not covered — known gap: PPTX integration test needed |
| FR-703 | SHOULD | DOCX support via Docling layout engine | module_docling — DOCX handling | Not covered — known gap: DOCX integration test needed |
| FR-704 | MUST | pure image files (JPG/PNG) as single-page document | module_visual_node — processing log entries | Not covered — known gap: image file integration test needed |
| FR-705 | MUST | format-specific failures → log warning, visual_stored_count=0, no exception, text track unaffected | module_visual_node — format failure handling, module_config_state — backward compat | Not covered — known gap: format-specific error scenarios in integration |

## Error Handling (FR-801 to FR-806)

| FR | Priority | AC Summary | Module Test | Integration Test |
|---|---|---|---|---|
| FR-801 | MUST | per-item try/except per page; failure on one page doesn't prevent others | module_visual_node — per-item error boundary, module_colqwen — per-page skip with warning | integration_partial — pages 3,7 skipped with warning |
| FR-802 | MUST | ColQwen2 load failure → fatal for visual track, log error, visual_stored_count=0, add to errors, no retry | module_colqwen — ColQwen2LoadError fatal | Not covered — known gap: requires model load failure mock |
| FR-803 | MUST | never write to text-track state fields (stored_count, chunks, enriched_chunks, etc.) | module_visual_node — text-track isolation invariant | integration_happy — text-track fields absent from result |
| FR-804 | MUST | MinIO failure for a page → non-fatal, warn, skip that page's embedding | module_visual_node — MinIO partial skip | integration_partial — partial MinIO semantics |
| FR-805 | MUST | Weaviate batch failure → add to errors, visual_stored_count=0 or partial, no exception | module_visual_node — Weaviate batch failure, module_visual_store — batch insert count returned | Not covered — known gap: Weaviate batch failure scenario needs integration |
| FR-806 | SHOULD | pre-check colpali-engine + bitsandbytes installed; clear error with install command | module_visual_node — ensure_colqwen_ready error message | Not covered — known gap: import error handling integration test |

## Non-Functional Requirements (NFR-901 to NFR-910)

| FR | Priority | AC Summary | Module Test | Integration Test |
|---|---|---|---|---|
| NFR-901 | MUST | peak VRAM ≤4GB during ColQwen2 inference (4-page batch at 1024px) | module_colqwen — peak memory test | Not covered — known gap: requires GPU hardware measurement |
| NFR-902 | MUST | ≤5 seconds/page average on target hardware (RTX 2060) | Not covered — known gap: requires target hardware benchmark | Not covered — known gap: requires target hardware benchmark |
| NFR-903 | MUST | zero overhead when disabled; wall-clock <10ms; no GPU alloc; no I/O | module_config_state — disabled path, module_visual_node — disabled path <10ms gap | integration_disabled — no external service calls |
| NFR-904 | SHOULD | MinIO page image size 30-300KB per page at quality=85 | module_minio — JPEG quality | Not covered — known gap: byte size validation needs real PIL+MinIO |
| NFR-905 | MUST | all behavioral params configurable without code changes | module_config_state — configurable | integration_happy |
| NFR-906 | MUST | colpali-engine + bitsandbytes as optional [visual] extras in pyproject.toml | module_config_state — backward compat, integration_disabled — no import error when disabled | integration_disabled |
| NFR-907 | SHOULD | idempotent re-ingestion (same doc → same objects in Weaviate) | module_visual_store — idempotent create, module_minio — delete-before-insert | Not covered — known gap: idempotence round-trip verification needed |
| NFR-908 | SHOULD | deterministic embeddings for same page image across runs | module_colqwen — adapter isolation | Not covered — known gap: requires determinism verification across runs |
| NFR-909 | MUST | no breaking changes to existing text pipeline API/state/behavior | module_config_state — backward compat, module_visual_store — existing methods unchanged, module_visual_node — text-track isolation invariant | integration_happy — text-track fields absent from result |
| NFR-910 | SHOULD | ColQwen2 adapter follows docling.py pattern, isolates colpali-engine | module_colqwen — adapter isolation | integration_happy |
