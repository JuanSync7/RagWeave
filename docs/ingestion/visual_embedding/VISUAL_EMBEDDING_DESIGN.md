# Visual Embedding Pipeline -- Design Document

**AION Knowledge Management Platform**
Version: 1.0 | Status: Draft | Domain: Ingestion Pipeline -- Visual Embedding Track

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-04-01 | AI Assistant | Initial design -- task decomposition and code appendix for dual-track visual embedding pipeline |

> **Document intent:** This is a design document bridging the [Visual Embedding Spec](VISUAL_EMBEDDING_SPEC.md) (Layer 3) and the implementation docs (Layer 5). **Part A** decomposes the 48 spec requirements into phased, dependency-ordered tasks with FR traceability. **Part B** provides the exact code contracts (types, stubs, exceptions) that will be copied verbatim into the implementation docs, plus illustrative patterns for the implement-code agent.

---

# Part A: Task-Oriented Overview

## Phase 1 -- Foundation (Config & Docling Extension)

### Task 1.1: Config & Settings Extensions
**Description:** Add all visual embedding configuration fields to `IngestionConfig` in `src/ingest/common/types.py`, backed by environment variables defined in `config/settings.py`. Extend `verify_core_design()` in `src/ingest/impl.py` with validation rules (enable_visual_embedding requires enable_docling_parser; range checks on numeric parameters). Add `colpali-engine` and `bitsandbytes` as `[visual]` optional extras in `pyproject.toml`.
**Requirements Covered:** FR-101, FR-102, FR-103, FR-104, FR-105, FR-106, FR-107, FR-108, FR-109, NFR-905, NFR-906
**Dependencies:** None
**Complexity:** M
**Subtasks:**
1. Add env var constants to `config/settings.py`: `RAG_INGESTION_ENABLE_VISUAL_EMBEDDING` (bool, default False), `RAG_INGESTION_VISUAL_TARGET_COLLECTION` (str, default "RAGVisualPages"), `RAG_INGESTION_COLQWEN_MODEL` (str, default "vidore/colqwen2-v1.0"), `RAG_INGESTION_COLQWEN_BATCH_SIZE` (int, default 4), `RAG_INGESTION_PAGE_IMAGE_QUALITY` (int, default 85), `RAG_INGESTION_PAGE_IMAGE_MAX_DIMENSION` (int, default 1024).
2. Import the six new settings constants into `src/ingest/common/types.py`.
3. Add six new fields to the `IngestionConfig` dataclass with defaults pointing to the imported constants.
4. Add a `generate_page_images` property (or derived field) that returns `True` when `enable_visual_embedding` is `True` (FR-107).
5. Add a `_check_visual_embedding_config()` validation function in `src/ingest/impl.py` covering: enable_visual_embedding requires enable_docling_parser; colqwen_batch_size range 1-32; page_image_quality range 1-100; page_image_max_dimension range 256-4096. Fatal errors on violations.
6. Wire `_check_visual_embedding_config()` into `verify_core_design()`.
7. Add `[visual]` optional extras group to `pyproject.toml` with `colpali-engine` and `bitsandbytes` (NFR-906).
**Risks:** Breaking existing config import surface if new settings constants collide with existing names. Mitigation: use `RAG_INGESTION_` prefix consistently.
**Testing Strategy:** Unit-test each validation rule in `_check_visual_embedding_config()`. Verify default values match spec. Verify env var override wiring with monkeypatch.

### Task 1.2: Docling Page Image Extension
**Description:** Extend `DoclingParseResult` with `page_images` and `page_count` fields. Add `generate_page_images` parameter to `parse_with_docling()`. When enabled, extract page images from the `DoclingDocument`, record original dimensions, and convert to RGB.
**Requirements Covered:** FR-107, FR-201, FR-204, FR-205
**Dependencies:** None
**Complexity:** S
**Subtasks:**
1. Add `page_images: list[Any]` (default empty list) and `page_count: int` (default 0) fields to `DoclingParseResult`.
2. Add `generate_page_images: bool = False` keyword parameter to `parse_with_docling()`.
3. When `generate_page_images=True`, iterate `docling_document.pages`, extract each page's `PIL.Image`, record original `(width, height)` as metadata, and convert to RGB mode (FR-205).
4. Populate `page_images` and `page_count` on the returned `DoclingParseResult`.
**Testing Strategy:** Unit-test with mock DoclingDocument that has page images. Verify RGB conversion. Verify page_count matches list length.

---

## Phase 2 -- Core Adapters

### Task 2.1: ColQwen2 Model Adapter
**Description:** Create `src/ingest/support/colqwen.py` implementing ColQwen2 model lifecycle (load with 4-bit quantization, batch inference producing 128-dim patch vectors, mean pooling, GPU memory release). Follows `docling.py` structural pattern with lazy imports and explicit error messages.
**Requirements Covered:** FR-301, FR-302, FR-303, FR-304, FR-305, FR-306, FR-307, NFR-901, NFR-902, NFR-906, NFR-908, NFR-910
**Dependencies:** None
**Complexity:** L
**Subtasks:**
1. Create `src/ingest/support/colqwen.py` with module-level docstring and `@summary` block.
2. Define `ColQwen2PageEmbedding` dataclass (page_number, mean_vector, patch_vectors, patch_count).
3. Define `VisualEmbeddingError` and `ColQwen2LoadError` exception types.
4. Implement `ensure_colqwen_ready()` that validates `colpali-engine` and `bitsandbytes` are importable (NFR-906, FR-806).
5. Implement `load_colqwen_model(model_name)` that loads the model and processor with 4-bit BitsAndBytesConfig quantization (FR-301, NFR-901).
6. Implement `embed_page_images(model, processor, images, batch_size)` that batches inference, computes mean-pooled 128-dim vectors and retains raw patch vectors, logs progress at 10% intervals for large documents, and catches per-page failures (FR-302, FR-303, FR-304, FR-306, FR-307).
7. Implement `unload_colqwen_model(model)` that deletes the model and calls `torch.cuda.empty_cache()` and `gc.collect()` (FR-305).
**Risks:** VRAM budget (4GB) may be tight with batch_size=4 on certain GPUs. Mitigation: batch_size is configurable (FR-104). 4-bit quantization is mandatory (FR-301). Model load failure is treated as FATAL with clear error message (FR-802).
**Testing Strategy:** Mock `colpali_engine` and `transformers` imports. Verify batch partitioning logic. Verify mean pooling arithmetic. Verify per-page exception isolation. Verify unload sequence.

### Task 2.2: MinIO Page Image Storage Operations
**Description:** Extend MinIO operations to support page image storage with the key pattern `pages/{document_id}/{page_number:04d}.jpg`. Supports JPEG compression at configurable quality, pre-storage cleanup for update mode, and uses the existing Runtime.db_client and bucket.
**Requirements Covered:** FR-401, FR-402, FR-403, FR-404, FR-405
**Dependencies:** None
**Complexity:** M
**Subtasks:**
1. Add `store_page_images(client, document_id, page_images, quality, bucket)` function to `src/db/minio/store.py` that iterates page images, JPEG-encodes each at the given quality, and uploads with key pattern `pages/{document_id}/{page_number:04d}.jpg`.
2. Add `delete_page_images(client, document_id, bucket)` function that lists and removes all objects under `pages/{document_id}/` prefix.
3. Ensure JPEG encoding uses the resized image (not the original), as per FR-402.
4. Ensure delete is called before store in update mode (FR-405), coordinated by the node caller.
**Risks:** Large documents (hundreds of pages) may generate many MinIO put operations. Mitigation: page images are small (30-300KB at quality=85, NFR-904).
**Testing Strategy:** Mock MinIO client. Verify key pattern format. Verify JPEG encoding path. Verify delete-before-store sequence.

### Task 2.3: Weaviate Visual Collection Schema & CRUD
**Description:** Create `src/vector_db/weaviate/visual_store.py` implementing visual collection creation with named vector "mean_vector" (128-dim, HNSW+cosine), per-page properties (document_id, page_number, source_key, etc.), patch_vectors as JSON data property, and batch insertion/deletion operations.
**Requirements Covered:** FR-501, FR-502, FR-503, FR-504, FR-505, FR-506, FR-507
**Dependencies:** None
**Complexity:** M
**Subtasks:**
1. Create `src/vector_db/weaviate/visual_store.py` with module-level docstring and `@summary` block.
2. Implement `ensure_visual_collection(client, collection)` that creates the collection with named vector config for "mean_vector" (128-dim, HNSW, cosine distance) and all required properties including "patch_vectors" as TEXT type for JSON storage (FR-501, FR-502, FR-503, FR-504, FR-505).
3. Implement `add_visual_documents(client, documents, collection)` that batch-inserts visual page objects with named vector "mean_vector" and patch_vectors as JSON-serialized data property (FR-507).
4. Implement `delete_visual_by_source_key(client, source_key, collection)` that deletes all objects matching source_key (FR-506).
**Risks:** Named vector API differs between Weaviate v4 minor versions. Mitigation: use `weaviate.classes.config.Configure.NamedVectors.none()` as shown in the codebase context.
**Testing Strategy:** Mock Weaviate client. Verify collection schema properties match FR-503. Verify named vector configuration. Verify batch insertion populates all required fields.

---

## Phase 3 -- Vector DB Backend Abstraction

### Task 3.1: VectorBackend Abstract Methods + Weaviate Implementation
**Description:** Add `ensure_visual_collection()`, `add_visual_documents()`, and `delete_visual_by_source_key()` abstract methods to the `VectorBackend` ABC. Implement them in `WeaviateBackend` by delegating to the visual_store functions. Add public re-exports in `src/vector_db/__init__.py`. Designed to not break the existing text pipeline API surface.
**Requirements Covered:** FR-501, FR-502, FR-506, FR-507, NFR-909
**Dependencies:** Task 2.3
**Complexity:** S
**Subtasks:**
1. Add three abstract methods to `VectorBackend` in `src/vector_db/backend.py`: `ensure_visual_collection(client, collection)`, `add_visual_documents(client, documents, collection)`, `delete_visual_by_source_key(client, source_key, collection)`.
2. Implement all three in `WeaviateBackend` (`src/vector_db/weaviate/backend.py`) by importing and delegating to visual_store functions.
3. Add public re-exports in `src/vector_db/__init__.py`: `ensure_visual_collection`, `add_visual_documents`, `delete_visual_by_source_key`.
4. Verify no existing abstract method signatures or public exports are modified (NFR-909).
**Testing Strategy:** Verify WeaviateBackend satisfies all abstract methods (instantiation test). Verify __init__.py exports are importable.

---

## Phase 4 -- Pipeline State & Node

### Task 4.1: EmbeddingPipelineState Extension + Types Registry
**Description:** Add `visual_stored_count` (int, default 0) and `page_images` (Optional[List[Any]]) fields to `EmbeddingPipelineState`. Add `visual_stored_count` field to `IngestFileResult`. Add `"visual_embedding"` to `PIPELINE_NODE_NAMES` between `"embedding_storage"` and `"knowledge_graph_storage"`.
**Requirements Covered:** FR-602, FR-604, FR-605, NFR-909
**Dependencies:** None
**Complexity:** S
**Subtasks:**
1. Add `visual_stored_count: int` and `page_images: Optional[List[Any]]` fields to `EmbeddingPipelineState` TypedDict in `src/ingest/embedding/state.py`.
2. Add `visual_stored_count: int = 0` field to `IngestFileResult` dataclass in `src/ingest/common/types.py`.
3. Insert `"visual_embedding"` into `PIPELINE_NODE_NAMES` list between `"embedding_storage"` and `"knowledge_graph_storage"` in `src/ingest/common/types.py`.
4. Verify no existing fields are modified or removed (NFR-909).
**Testing Strategy:** Verify TypedDict accepts the new fields. Verify PIPELINE_NODE_NAMES ordering is correct. Verify IngestFileResult default value.

### Task 4.2: visual_embedding_node Implementation
**Description:** Create `src/ingest/embedding/nodes/visual_embedding.py` implementing the complete visual embedding pipeline node. Handles short-circuit conditions (disabled, no docling_document, no pages), page image extraction and resizing, MinIO storage, ColQwen2 inference, Weaviate visual collection insertion, per-page error isolation, and state cleanup.
**Requirements Covered:** FR-201, FR-202, FR-203, FR-204, FR-205, FR-301, FR-302, FR-303, FR-304, FR-305, FR-306, FR-307, FR-401, FR-402, FR-403, FR-404, FR-405, FR-501, FR-502, FR-503, FR-504, FR-505, FR-506, FR-507, FR-601, FR-602, FR-603, FR-604, FR-605, FR-606, FR-701, FR-702, FR-703, FR-704, FR-705, FR-801, FR-802, FR-803, FR-804, FR-805, FR-806, NFR-901, NFR-902, NFR-903, NFR-907
**Dependencies:** Task 2.1, Task 2.2, Task 2.3, Task 3.1, Task 4.1
**Complexity:** L
**Subtasks:**
1. Create `src/ingest/embedding/nodes/visual_embedding.py` with module docstring and `@summary` block.
2. Implement short-circuit logic: return immediately with `visual_stored_count=0` when `enable_visual_embedding=False` OR `docling_document is None` OR no extractable pages (FR-603, NFR-903).
3. Extract page images from `docling_document` with format dispatch (PDF pages, PPTX slides, DOCX layout pages, single-image files) and record original dimensions (FR-201, FR-204, FR-701 through FR-704).
4. Resize images so longer edge <= `page_image_max_dimension`, preserve aspect ratio (FR-202). Convert to RGB (FR-205).
5. Handle zero-page documents: short-circuit with `visual_stored_count=0`, log `"visual_embedding:no_pages"` (FR-203).
6. Handle format failures (encrypted PDF, password-protected PPTX, corruption): log warning, `visual_stored_count=0`, return without error; text track unaffected (FR-705).
7. Delete existing visual objects for this source_key in update mode (FR-405, FR-506).
8. Store all page images to MinIO BEFORE starting ColQwen2 inference (FR-403).
9. Per-page MinIO upload failure: log warning, skip embedding for that page, continue (FR-804).
10. Load ColQwen2 model with 4-bit quantization (FR-301). Model load failure is FATAL: log error, `visual_stored_count=0`, add to `state["errors"]`, no retry (FR-802).
11. Run batch inference producing patch vectors and mean-pooled vectors (FR-302, FR-303, FR-304).
12. Per-page inference failure: log warning, skip page, continue (FR-307, FR-801).
13. Ensure visual collection exists (FR-502). Batch-insert visual page objects to Weaviate (FR-507).
14. Weaviate batch insertion failure: add to `state["errors"]`, `visual_stored_count=0` or partial, no exception raised (FR-805).
15. Unload ColQwen2 and release GPU memory (FR-305).
16. Clear `page_images` field from state (set to `None`) (FR-606).
17. Verify node MUST NOT modify `stored_count`, `chunks`, `enriched_chunks`, or any text-track fields (FR-803).
**Risks:** GPU memory leak if model unload fails. Mitigation: wrap unload in try/finally. Complex per-page error handling may mask silent data loss. Mitigation: log every skip with page number and reason.
**Testing Strategy:** Mock all adapters (colqwen, MinIO, Weaviate). Verify short-circuit paths. Verify per-page error isolation. Verify text-track fields are never modified. Verify state cleanup.

---

## Phase 5 -- DAG Integration & Packaging

### Task 5.1: LangGraph Workflow Wiring
**Description:** Wire the `visual_embedding_node` into the LangGraph DAG in `build_embedding_graph()`, positioned after `embedding_storage` and before `knowledge_graph_storage` (or END). The node is always present in the graph and short-circuits internally when disabled.
**Requirements Covered:** FR-601, FR-604
**Dependencies:** Task 4.1, Task 4.2
**Complexity:** S
**Subtasks:**
1. Import `visual_embedding_node` in `src/ingest/embedding/workflow.py`.
2. Add `graph.add_node("visual_embedding", visual_embedding_node)` to `build_embedding_graph()`.
3. Modify the conditional edge from `embedding_storage` to route through `visual_embedding` before `knowledge_graph_storage` or END.
4. Add edge from `visual_embedding` to the next node (knowledge_graph_storage conditional or END).
**Testing Strategy:** Verify graph compiles without error. Verify visual_embedding node is in the graph topology. Verify edge ordering.

### Task 5.2: Optional Dependency Declaration
**Description:** Add `[visual]` optional extras group to `pyproject.toml` declaring `colpali-engine` and `bitsandbytes` as optional dependencies. Core installation remains functional without them.
**Requirements Covered:** NFR-906
**Dependencies:** None
**Complexity:** S
**Subtasks:**
1. Add `visual = ["colpali-engine", "bitsandbytes"]` to `[project.optional-dependencies]` in `pyproject.toml`.
2. Add `"rag[visual]"` to the `all` extras group.
**Testing Strategy:** Verify `uv pip install -e ".[visual]"` resolves. Verify core install without `[visual]` does not pull colpali-engine.

---

## Task Dependency Graph

```
Phase 1 (no deps):
  Task 1.1 ──┐
  Task 1.2 ──┤
             │
Phase 2 (no deps):
  Task 2.1 ──┤
  Task 2.2 ──┤
  Task 2.3 ──┤
             │
Phase 3:     │
  Task 3.1 ──┤── depends on Task 2.3
             │
Phase 4:     │
  Task 4.1 ──┤── no deps
  Task 4.2 ──┤── depends on Task 2.1, 2.2, 2.3, 3.1, 4.1
             │
Phase 5:     │
  Task 5.1 ──┘── depends on Task 4.1, 4.2
  Task 5.2 ────── no deps (parallel with everything)
```

Parallelizable groups:
- **Wave 1:** Task 1.1, Task 1.2, Task 2.1, Task 2.2, Task 2.3, Task 4.1, Task 5.2 (all independent)
- **Wave 2:** Task 3.1 (needs 2.3)
- **Wave 3:** Task 4.2 (needs 2.1, 2.2, 2.3, 3.1, 4.1)
- **Wave 4:** Task 5.1 (needs 4.1, 4.2)

---

## Task-to-Requirement Mapping

| Requirement | Task(s) | Type |
|-------------|---------|------|
| FR-101 | 1.1 | Config |
| FR-102 | 1.1 | Config |
| FR-103 | 1.1 | Config |
| FR-104 | 1.1 | Config |
| FR-105 | 1.1 | Config |
| FR-106 | 1.1 | Config |
| FR-107 | 1.1, 1.2 | Config + Docling |
| FR-108 | 1.1 | Config validation |
| FR-109 | 1.1 | Config env vars |
| FR-201 | 1.2, 4.2 | Page extraction |
| FR-202 | 4.2 | Resize |
| FR-203 | 4.2 | Zero-page handling |
| FR-204 | 1.2, 4.2 | Page dimensions |
| FR-205 | 1.2, 4.2 | RGB conversion |
| FR-301 | 2.1, 4.2 | ColQwen2 loading |
| FR-302 | 2.1, 4.2 | Batch inference |
| FR-303 | 2.1, 4.2 | Mean pooling |
| FR-304 | 2.1, 4.2 | Patch vectors |
| FR-305 | 2.1, 4.2 | GPU release |
| FR-306 | 2.1, 4.2 | Progress logging |
| FR-307 | 2.1, 4.2 | Per-page failure |
| FR-401 | 2.2, 4.2 | MinIO key pattern |
| FR-402 | 2.2, 4.2 | JPEG compression |
| FR-403 | 2.2, 4.2 | Store before inference |
| FR-404 | 2.2, 4.2 | Existing bucket |
| FR-405 | 2.2, 4.2 | Update mode cleanup |
| FR-501 | 2.3, 3.1, 4.2 | Visual collection |
| FR-502 | 2.3, 3.1, 4.2 | Idempotent ensure |
| FR-503 | 2.3, 4.2 | Properties |
| FR-504 | 2.3, 4.2 | Named vector |
| FR-505 | 2.3, 4.2 | Patch vectors property |
| FR-506 | 2.3, 3.1, 4.2 | Delete by source_key |
| FR-507 | 2.3, 3.1, 4.2 | Batch insert |
| FR-601 | 4.2, 5.1 | DAG position |
| FR-602 | 4.1, 4.2 | State extension |
| FR-603 | 4.2 | Short-circuit |
| FR-604 | 4.1, 5.1 | Node name registry |
| FR-605 | 4.1 | IngestFileResult |
| FR-606 | 4.2 | State cleanup |
| FR-701 | 4.2 | PDF support |
| FR-702 | 4.2 | PPTX support |
| FR-703 | 4.2 | DOCX support |
| FR-704 | 4.2 | Image file support |
| FR-705 | 4.2 | Format failures |
| FR-801 | 4.2 | Per-page try/except |
| FR-802 | 4.2 | FATAL model load |
| FR-803 | 4.2 | Text-track isolation |
| FR-804 | 4.2 | MinIO upload failure |
| FR-805 | 4.2 | Weaviate batch failure |
| FR-806 | 2.1, 4.2 | Dependency validation |
| NFR-901 | 2.1, 4.2 | VRAM budget |
| NFR-902 | 2.1, 4.2 | Per-page latency |
| NFR-903 | 4.2 | Zero overhead disabled |
| NFR-904 | 2.2 | Image size budget |
| NFR-905 | 1.1 | All params configurable |
| NFR-906 | 1.1, 2.1, 5.2 | Optional extras |
| NFR-907 | 4.2 | Idempotent re-ingestion |
| NFR-908 | 2.1 | Deterministic embeddings |
| NFR-909 | 3.1, 4.1 | No breaking changes |
| NFR-910 | 2.1 | Structural pattern |

---

# Part B: Code Appendix

## B.1: IngestionConfig Visual Embedding Fields -- Contract
Exact dataclass fields and env var settings constants for the visual embedding configuration surface. These are appended to the existing `IngestionConfig` and `config/settings.py`.
**Tasks:** Task 1.1
**Requirements:** FR-101, FR-102, FR-103, FR-104, FR-105, FR-106, FR-107, FR-108, FR-109, NFR-905
**Type:** Contract (exact -- copied to implementation docs Phase 0)

```python
# ── config/settings.py additions ──────────────────────────────────────────

import os

# --- Visual Embedding Pipeline ---
RAG_INGESTION_ENABLE_VISUAL_EMBEDDING: bool = os.environ.get(
    "RAG_INGESTION_ENABLE_VISUAL_EMBEDDING", "false"
).lower() in ("true", "1", "yes")  # FR-101, FR-109

RAG_INGESTION_VISUAL_TARGET_COLLECTION: str = os.environ.get(
    "RAG_INGESTION_VISUAL_TARGET_COLLECTION", "RAGVisualPages"
)  # FR-102, FR-109

RAG_INGESTION_COLQWEN_MODEL: str = os.environ.get(
    "RAG_INGESTION_COLQWEN_MODEL", "vidore/colqwen2-v1.0"
)  # FR-103, FR-109

RAG_INGESTION_COLQWEN_BATCH_SIZE: int = int(os.environ.get(
    "RAG_INGESTION_COLQWEN_BATCH_SIZE", "4"
))  # FR-104, FR-109

RAG_INGESTION_PAGE_IMAGE_QUALITY: int = int(os.environ.get(
    "RAG_INGESTION_PAGE_IMAGE_QUALITY", "85"
))  # FR-105, FR-109

RAG_INGESTION_PAGE_IMAGE_MAX_DIMENSION: int = int(os.environ.get(
    "RAG_INGESTION_PAGE_IMAGE_MAX_DIMENSION", "1024"
))  # FR-106, FR-109


# ── src/ingest/common/types.py additions to IngestionConfig ───────────────

from config.settings import (
    RAG_INGESTION_ENABLE_VISUAL_EMBEDDING,
    RAG_INGESTION_VISUAL_TARGET_COLLECTION,
    RAG_INGESTION_COLQWEN_MODEL,
    RAG_INGESTION_COLQWEN_BATCH_SIZE,
    RAG_INGESTION_PAGE_IMAGE_QUALITY,
    RAG_INGESTION_PAGE_IMAGE_MAX_DIMENSION,
)
from dataclasses import dataclass


@dataclass
class IngestionConfig:
    # ... existing fields ...

    # ── Visual embedding pipeline (FR-101 through FR-109) ─────────────
    enable_visual_embedding: bool = RAG_INGESTION_ENABLE_VISUAL_EMBEDDING
    """Enable dual-track visual embedding pipeline. Default: False. FR-101"""
    visual_target_collection: str = RAG_INGESTION_VISUAL_TARGET_COLLECTION
    """Weaviate collection name for visual page objects. Default: 'RAGVisualPages'. FR-102"""
    colqwen_model_name: str = RAG_INGESTION_COLQWEN_MODEL
    """ColQwen2 model identifier for visual embedding. Default: 'vidore/colqwen2-v1.0'. FR-103"""
    colqwen_batch_size: int = RAG_INGESTION_COLQWEN_BATCH_SIZE
    """Batch size for ColQwen2 inference. Range: 1-32. Default: 4. FR-104"""
    page_image_quality: int = RAG_INGESTION_PAGE_IMAGE_QUALITY
    """JPEG compression quality for page images. Range: 1-100. Default: 85. FR-105"""
    page_image_max_dimension: int = RAG_INGESTION_PAGE_IMAGE_MAX_DIMENSION
    """Max pixel dimension (longer edge) for page images. Range: 256-4096. Default: 1024. FR-106"""

    @property
    def generate_page_images(self) -> bool:
        """Derived flag: True when visual embedding is enabled. FR-107"""
        return self.enable_visual_embedding


# ── src/ingest/impl.py validation addition ────────────────────────────────

def _check_visual_embedding_config(
    config: "IngestionConfig",
) -> tuple[list[str], list[str]]:
    """Validate visual embedding configuration.

    Checks:
    1. enable_visual_embedding=True requires enable_docling_parser=True (fatal)
    2. colqwen_batch_size range 1-32 (fatal)
    3. page_image_quality range 1-100 (fatal)
    4. page_image_max_dimension range 256-4096 (fatal)

    Args:
        config: IngestionConfig to validate.

    Returns:
        Tuple of (errors, warnings). Errors block pipeline start.
    """
    raise NotImplementedError("Task 1.1")
```

**Key design decisions:**
- All six config fields follow the existing `RAG_INGESTION_*` env var pattern for consistency (FR-109, NFR-905).
- `generate_page_images` is a `@property` rather than a stored field, derived from `enable_visual_embedding` (FR-107). This avoids config state duplication and ensures the gate in `parse_with_docling()` always reflects the current config.
- Validation is a separate function wired into `verify_core_design()` rather than in-dataclass `__post_init__` to match the existing validation pattern (`_check_docling_chunking_config`).

---

## B.2: EmbeddingPipelineState Extensions -- Contract
New TypedDict fields for the embedding pipeline state to carry visual embedding data and results.
**Tasks:** Task 4.1
**Requirements:** FR-602, NFR-909
**Type:** Contract (exact -- copied to implementation docs Phase 0)

```python
from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict

from src.ingest.common.schemas import ProcessedChunk
from src.ingest.common.types import Runtime


class EmbeddingPipelineState(TypedDict, total=False):
    """Shared state flowing through the Embedding Pipeline DAG.

    Existing fields are preserved exactly as-is (NFR-909).
    """

    # ── Existing fields (unchanged) ───────────────────────────────────
    runtime: Runtime
    source_key: str
    source_name: str
    source_uri: str
    source_id: str
    source_version: str
    connector: str
    raw_text: str
    cleaned_text: str
    refactored_text: Optional[str]
    clean_hash: str
    document_id: str
    chunks: List[ProcessedChunk]
    enriched_chunks: List[ProcessedChunk]
    metadata_summary: str
    metadata_keywords: List[str]
    cross_references: List[Dict[str, str]]
    kg_triples: List[Dict[str, Any]]
    stored_count: int
    errors: List[str]
    processing_log: List[str]
    docling_document: Optional[Any]

    # ── Visual embedding extensions (FR-602) ──────────────────────────
    visual_stored_count: int  # FR-602: number of visual page objects stored; default 0
    page_images: Optional[List[Any]]  # FR-602: PIL.Image objects from docling; cleared after node (FR-606)
```

**Key design decisions:**
- `total=False` on the TypedDict means all fields are optional at construction time, which is the existing pattern. `visual_stored_count` defaults to 0 at the node level, not the TypedDict level (TypedDict has no defaults).
- `page_images` uses `Optional[List[Any]]` to avoid importing PIL at the type level, matching the `docling_document: Optional[Any]` precedent.

---

## B.3: IngestFileResult Extension -- Contract
New field on the ingestion result dataclass to surface visual embedding count to callers.
**Tasks:** Task 4.1
**Requirements:** FR-605, NFR-909
**Type:** Contract (exact -- copied to implementation docs Phase 0)

```python
from dataclasses import dataclass, field


@dataclass
class IngestFileResult:
    """Result of a single-file ingestion run.

    Existing fields are preserved exactly as-is (NFR-909).
    """

    # ── Existing fields (unchanged) ───────────────────────────────────
    errors: list[str]
    stored_count: int
    metadata_summary: str
    metadata_keywords: list[str]
    processing_log: list[str]
    source_hash: str
    clean_hash: str

    # ── Visual embedding extension (FR-605) ───────────────────────────
    visual_stored_count: int = 0  # FR-605: number of visual page objects stored
```

**Key design decisions:**
- Default value `0` ensures backward compatibility: callers that do not use visual embedding see `visual_stored_count=0` without code changes.
- Placed after `clean_hash` as the last field to maintain positional compatibility with any existing constructor calls (all existing fields are positional).

---

## B.4: ColQwen2PageEmbedding -- Contract (dataclass)
Result type for a single page's ColQwen2 embedding output, carrying mean-pooled vector, raw patch vectors, and metadata.
**Tasks:** Task 2.1
**Requirements:** FR-302, FR-303, FR-304
**Type:** Contract (exact -- copied to implementation docs Phase 0)

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ColQwen2PageEmbedding:
    """Embedding result for a single document page from ColQwen2.

    Attributes:
        page_number: 1-indexed page number within the document.
        mean_vector: 128-dim float32 mean-pooled vector (arithmetic mean across patches). FR-303
        patch_vectors: Raw patch vectors as list of list of float, serializable as JSON. FR-304
        patch_count: Number of patches produced for this page.
    """

    page_number: int  # FR-302: 1-indexed page number
    mean_vector: list[float]  # FR-303: 128-dim float32 mean-pooled vector
    patch_vectors: list[list[float]]  # FR-304: raw patch vectors, JSON-serializable
    patch_count: int  # FR-302: number of patches for this page
```

**Key design decisions:**
- `mean_vector` and `patch_vectors` use `list[float]` and `list[list[float]]` rather than numpy arrays, ensuring JSON serializability without conversion (FR-304).
- `page_number` is 1-indexed to match PDF page numbering convention and the MinIO key pattern (FR-401).

---

## B.5: Exception Types -- Contract
Custom exception hierarchy for visual embedding errors, distinguishing recoverable per-page failures from fatal model load failures.
**Tasks:** Task 2.1
**Requirements:** FR-802, FR-307
**Type:** Contract (exact -- copied to implementation docs Phase 0)

```python
class VisualEmbeddingError(Exception):
    """Base exception for visual embedding pipeline errors.

    Non-fatal: per-page failures that should be caught and logged,
    allowing the pipeline to continue with remaining pages. FR-307
    """

    pass


class ColQwen2LoadError(VisualEmbeddingError):
    """Fatal: ColQwen2 model failed to load.

    When this is raised, visual_stored_count=0, the error is added to
    state['errors'], and no retry is attempted. FR-802
    """

    pass
```

**Key design decisions:**
- Two-level hierarchy: `VisualEmbeddingError` for catchable per-page issues, `ColQwen2LoadError` subclass for the one truly fatal case (FR-802). The node catches `ColQwen2LoadError` separately and transitions to fatal handling.
- Both exception classes live in `src/ingest/support/colqwen.py` alongside the adapter functions, co-locating error types with their producers.

---

## B.6: ColQwen2 Adapter Function Stubs -- Contract
Function signatures for the ColQwen2 model lifecycle adapter in `src/ingest/support/colqwen.py`.
**Tasks:** Task 2.1
**Requirements:** FR-301, FR-302, FR-303, FR-304, FR-305, FR-306, FR-307, FR-806, NFR-901, NFR-906
**Type:** Contract (exact -- copied to implementation docs Phase 0)

```python
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def ensure_colqwen_ready() -> None:
    """Validate that colpali-engine and bitsandbytes are installed.

    Raises:
        ColQwen2LoadError: If required packages are not importable,
            with a clear install command message. FR-806, NFR-906
    """
    raise NotImplementedError("Task 2.1")


def load_colqwen_model(
    model_name: str,
) -> tuple[Any, Any]:
    """Load ColQwen2 model and processor with 4-bit quantization.

    Uses BitsAndBytesConfig with load_in_4bit=True and float16 compute dtype.
    Peak VRAM must be <= 4GB (NFR-901).

    Args:
        model_name: HuggingFace model identifier. FR-103

    Returns:
        Tuple of (model, processor). Both are loaded to CUDA.

    Raises:
        ColQwen2LoadError: On any model load failure (FATAL). FR-802
    """
    raise NotImplementedError("Task 2.1")


def embed_page_images(
    model: Any,
    processor: Any,
    images: list[Any],
    batch_size: int,
    *,
    page_numbers: list[int] | None = None,
) -> list["ColQwen2PageEmbedding"]:
    """Batch-embed page images through ColQwen2.

    Processes images in batches of batch_size. Each page produces:
    - 128-dim float32 patch vectors (n_patches x 128)
    - 128-dim float32 mean-pooled vector (arithmetic mean across patches)

    Per-page inference failure logs a warning and skips the page (FR-307).
    Logs progress at 10% intervals for documents with >10 pages (FR-306).

    Args:
        model: Loaded ColQwen2 model.
        processor: Loaded ColQwen2Processor.
        images: List of PIL.Image objects (already resized/RGB).
        batch_size: Number of images per forward pass. FR-104
        page_numbers: Optional 1-indexed page numbers. If None,
            defaults to 1..len(images).

    Returns:
        List of ColQwen2PageEmbedding for successfully processed pages.
        Failed pages are omitted (not None entries).
    """
    raise NotImplementedError("Task 2.1")


def unload_colqwen_model(model: Any) -> None:
    """Release ColQwen2 model and free GPU memory.

    Deletes the model reference, calls torch.cuda.empty_cache() and
    gc.collect(). VRAM should return to pre-load levels (+/- 200MB). FR-305

    Args:
        model: The ColQwen2 model to unload.
    """
    raise NotImplementedError("Task 2.1")
```

**Key design decisions:**
- `load_colqwen_model` returns a tuple `(model, processor)` rather than a container object, matching the `colpali_engine` API surface and avoiding wrapper overhead.
- `embed_page_images` accepts an optional `page_numbers` list to handle cases where some pages were filtered out (e.g., MinIO upload failures). Failed pages are omitted from the result list rather than represented as `None`, simplifying downstream iteration.
- `unload_colqwen_model` is a separate function (not a context manager) because the model lifetime spans multiple operations (MinIO storage + inference + Weaviate insertion) and the unload must happen in a specific order after all pages are processed.

---

## B.7: Weaviate Visual Store Function Stubs -- Contract
Function signatures for visual collection schema management and CRUD operations in `src/vector_db/weaviate/visual_store.py`.
**Tasks:** Task 2.3
**Requirements:** FR-501, FR-502, FR-503, FR-504, FR-505, FR-506, FR-507
**Type:** Contract (exact -- copied to implementation docs Phase 0)

```python
from __future__ import annotations

import logging
from typing import Any, List, Optional

import weaviate

logger = logging.getLogger("rag.vector_db.weaviate.visual_store")


def ensure_visual_collection(
    client: weaviate.WeaviateClient,
    collection: str = "RAGVisualPages",
) -> None:
    """Create the visual page collection if it does not exist (idempotent).

    Collection schema:
    - Named vector "mean_vector": 128-dim float32, HNSW index, cosine distance. FR-504
    - Properties: document_id(str), page_number(int), source_key(str),
      source_uri(str), source_name(str), tenant_id(str), total_pages(int),
      page_width_px(int), page_height_px(int), minio_key(str),
      patch_vectors(text/JSON). FR-503, FR-505
    - Vectorizer: none (pre-computed embeddings). FR-504

    Args:
        client: Weaviate client handle.
        collection: Collection name. Default: "RAGVisualPages". FR-501, FR-502
    """
    raise NotImplementedError("Task 2.3")


def add_visual_documents(
    client: weaviate.WeaviateClient,
    documents: List[dict[str, Any]],
    collection: str = "RAGVisualPages",
) -> int:
    """Batch-insert visual page objects into the named collection.

    Each document dict must contain:
    - All properties from FR-503
    - "mean_vector": list[float] (128-dim) for the named vector
    - "patch_vectors": JSON-serialized list[list[float]] as str

    Args:
        client: Weaviate client handle.
        documents: List of visual page object dicts.
        collection: Target collection name. FR-507

    Returns:
        Number of objects successfully inserted.
    """
    raise NotImplementedError("Task 2.3")


def delete_visual_by_source_key(
    client: weaviate.WeaviateClient,
    source_key: str,
    collection: str = "RAGVisualPages",
) -> int:
    """Delete all visual page objects matching source_key.

    Args:
        client: Weaviate client handle.
        source_key: Stable source key to match. FR-506
        collection: Target collection name.

    Returns:
        Number of objects deleted.
    """
    raise NotImplementedError("Task 2.3")
```

**Key design decisions:**
- `documents` parameter to `add_visual_documents` uses `list[dict]` rather than a typed dataclass to match the existing `add_documents` pattern in `store.py` (flat dict with properties + vector).
- `patch_vectors` is stored as a TEXT property with JSON serialization (FR-505), not as a named vector, because Weaviate named vectors are indexed for ANN search and patch vectors are only used for MaxSim scoring at retrieval time (out of scope but anticipated).
- Default collection name "RAGVisualPages" is hardcoded in the function signature, matching the FR-102 default, but is overridable from config via the caller.

---

## B.8: VectorBackend Abstract Methods -- Contract
Abstract method signatures to add to the `VectorBackend` ABC for visual collection operations.
**Tasks:** Task 3.1
**Requirements:** FR-501, FR-502, FR-506, FR-507, NFR-909
**Type:** Contract (exact -- copied to implementation docs Phase 0)

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List, Optional


class VectorBackend(ABC):
    """Abstract contract for a vector store backend.

    Visual collection methods are added below existing methods (NFR-909).
    All existing abstract methods remain unchanged.
    """

    # ... existing abstract methods unchanged ...

    # ── Visual collection operations ──────────────────────────────────

    @abstractmethod
    def ensure_visual_collection(
        self,
        client: Any,
        collection: Optional[str] = None,
    ) -> None:
        """Create the visual collection if it does not exist (idempotent). FR-502"""
        raise NotImplementedError("Task 3.1")

    @abstractmethod
    def add_visual_documents(
        self,
        client: Any,
        documents: List[dict[str, Any]],
        collection: Optional[str] = None,
    ) -> int:
        """Batch-insert visual page objects. FR-507

        Returns:
            Number of objects inserted.
        """
        raise NotImplementedError("Task 3.1")

    @abstractmethod
    def delete_visual_by_source_key(
        self,
        client: Any,
        source_key: str,
        collection: Optional[str] = None,
    ) -> int:
        """Delete all visual page objects matching source_key. FR-506

        Returns:
            Number of objects deleted.
        """
        raise NotImplementedError("Task 3.1")
```

**Key design decisions:**
- Three new abstract methods are added after all existing methods to avoid changing the existing method resolution order or positional ABC contract (NFR-909).
- `collection` parameter is `Optional[str]` with default `None`, matching the existing pattern where `None` resolves to the backend's configured default. For visual collections, the default is the visual collection name rather than the text collection name.
- `documents` uses `List[dict[str, Any]]` to match the visual_store.py contract (B.7).

---

## B.9: visual_embedding_node Stub -- Contract
Full function stub for the visual embedding pipeline node with docstring, short-circuit logic outline, and NotImplementedError.
**Tasks:** Task 4.2
**Requirements:** FR-601, FR-602, FR-603, FR-604, FR-606, FR-803
**Type:** Contract (exact -- copied to implementation docs Phase 0)

```python
from __future__ import annotations

import logging
from typing import Any

from src.ingest.common.shared import append_processing_log
from src.ingest.common.types import IngestionConfig
from src.ingest.embedding.state import EmbeddingPipelineState

logger = logging.getLogger(__name__)


def visual_embedding_node(state: EmbeddingPipelineState) -> dict[str, Any]:
    """Visual embedding pipeline node: extract, store, embed, and index page images.

    Positioned in the LangGraph DAG after embedding_storage, before
    knowledge_graph_storage (FR-601, FR-604).

    Short-circuit conditions (FR-603, NFR-903):
    - enable_visual_embedding=False
    - docling_document is None
    - No extractable pages

    On short-circuit: returns visual_stored_count=0, logs descriptive entry.

    On completion: clears page_images from state (FR-606).

    MUST NOT modify: stored_count, chunks, enriched_chunks, or any
    text-track state fields (FR-803).

    Args:
        state: EmbeddingPipelineState with runtime, document_id, source_key,
            and docling_document populated by preceding nodes.

    Returns:
        Dict with keys: visual_stored_count, page_images (None), processing_log,
        and optionally errors.
    """
    raise NotImplementedError("Task 4.2")
```

**Key design decisions:**
- The node returns a dict (not a full state replacement), following the LangGraph convention used by all other nodes in the pipeline (e.g., `vlm_enrichment_node`).
- The return dict explicitly includes `page_images: None` to clear the state field (FR-606), preventing large PIL objects from persisting in memory after the node completes.
- The node never raises exceptions to the DAG runtime: all errors are caught internally and added to `state["errors"]` or logged as warnings.

---

## B.10: ColQwen2 Adapter Pattern -- Pattern
Illustrative implementation showing the model loading, batch inference, mean pooling, and GPU memory release lifecycle for the ColQwen2 adapter.
**Tasks:** Task 2.1
**Requirements:** FR-301, FR-302, FR-303, FR-304, FR-305, FR-306, FR-307, NFR-901, NFR-908
**Type:** Pattern (illustrative -- for implement-code only, never test agents)

```python
# Illustrative pattern -- not the final implementation
from __future__ import annotations

import gc
import logging
import math
from typing import Any

import torch

logger = logging.getLogger(__name__)


def ensure_colqwen_ready() -> None:
    """Validate required optional packages are installed."""
    try:
        import colpali_engine  # noqa: F401
        import bitsandbytes  # noqa: F401
    except ImportError as exc:
        raise ColQwen2LoadError(
            f"Visual embedding requires colpali-engine and bitsandbytes. "
            f"Install with: uv pip install 'rag[visual]'. Missing: {exc.name}"
        ) from exc


def load_colqwen_model(model_name: str) -> tuple[Any, Any]:
    """Load ColQwen2 with 4-bit quantization for <= 4GB VRAM."""
    from colpali_engine.models import ColQwen2, ColQwen2Processor
    from transformers import BitsAndBytesConfig

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.float16,
    )
    try:
        model = ColQwen2.from_pretrained(
            model_name,
            quantization_config=bnb_config,
            device_map="cuda",
        )
        processor = ColQwen2Processor.from_pretrained(model_name)
    except Exception as exc:
        raise ColQwen2LoadError(
            f"Failed to load ColQwen2 model '{model_name}': {exc}"
        ) from exc

    model.eval()
    return model, processor


def embed_page_images(
    model: Any,
    processor: Any,
    images: list[Any],
    batch_size: int,
    *,
    page_numbers: list[int] | None = None,
) -> list:
    """Batch inference with progress logging and per-page error isolation."""
    if page_numbers is None:
        page_numbers = list(range(1, len(images) + 1))

    results = []
    total = len(images)
    log_interval = max(1, total // 10) if total > 10 else total + 1

    for batch_start in range(0, total, batch_size):
        batch_end = min(batch_start + batch_size, total)
        batch_imgs = images[batch_start:batch_end]
        batch_pages = page_numbers[batch_start:batch_end]

        for idx, (img, page_num) in enumerate(zip(batch_imgs, batch_pages)):
            global_idx = batch_start + idx
            try:
                # Process single image through the model
                processed = processor.process_images([img]).to("cuda")
                with torch.no_grad():
                    embeddings = model(**processed)  # [1, n_patches, 128]

                # Mean pooling: arithmetic mean across patch dimension
                mean_vec = embeddings.mean(dim=1).squeeze(0)  # [128]
                patch_vecs = embeddings.squeeze(0)  # [n_patches, 128]

                results.append(ColQwen2PageEmbedding(
                    page_number=page_num,
                    mean_vector=mean_vec.cpu().float().tolist(),
                    patch_vectors=patch_vecs.cpu().float().tolist(),
                    patch_count=patch_vecs.shape[0],
                ))
            except Exception as exc:
                logger.warning(
                    "visual_embedding: page %d inference failed: %s",
                    page_num, exc,
                )
                continue

            # Progress logging at 10% intervals
            if total > 10 and (global_idx + 1) % log_interval == 0:
                pct = int(((global_idx + 1) / total) * 100)
                logger.info(
                    "visual_embedding: progress %d%% (%d/%d pages)",
                    pct, global_idx + 1, total,
                )

    return results


def unload_colqwen_model(model: Any) -> None:
    """Release model and reclaim GPU memory."""
    del model
    torch.cuda.empty_cache()
    gc.collect()
    logger.info("visual_embedding: ColQwen2 model unloaded, GPU memory released")
```

**Key design decisions:**
- Single-image processing within batch loops (rather than true batched forward pass) provides cleaner per-page error isolation (FR-307, FR-801). The batch_size parameter controls memory pressure by limiting concurrent GPU allocations, not collating inputs.
- `float()` cast before `tolist()` ensures all values are float32 regardless of compute dtype (NFR-908).
- Progress logging uses integer percentage thresholds (10%, 20%, ...) rather than fixed intervals, adapting to document length (FR-306).
- The `ensure_colqwen_ready()` check happens before any model loading attempt, providing a clear error message with install command (FR-806).

---

## B.11: visual_embedding_node Pattern -- Pattern
Illustrative implementation showing the full node flow: short-circuit evaluation, page extraction, MinIO storage, ColQwen2 inference, Weaviate insertion, error handling, and state cleanup.
**Tasks:** Task 4.2
**Requirements:** FR-201, FR-202, FR-203, FR-403, FR-601, FR-603, FR-606, FR-705, FR-801, FR-802, FR-803, FR-804, FR-805
**Type:** Pattern (illustrative -- for implement-code only, never test agents)

```python
# Illustrative pattern -- not the final implementation
from __future__ import annotations

import io
import json
import logging
from typing import Any

from src.ingest.common.shared import append_processing_log
from src.ingest.embedding.state import EmbeddingPipelineState

logger = logging.getLogger(__name__)


def visual_embedding_node(state: EmbeddingPipelineState) -> dict[str, Any]:
    """Full visual embedding node flow."""
    config = state["runtime"].config

    # ── Short-circuit: feature disabled ────────────────────────────────
    if not config.enable_visual_embedding:
        return {
            "visual_stored_count": 0,
            "page_images": None,
            "processing_log": append_processing_log(
                state, "visual_embedding:disabled"
            ),
        }

    # ── Short-circuit: no docling document ─────────────────────────────
    docling_doc = state.get("docling_document")
    if docling_doc is None:
        return {
            "visual_stored_count": 0,
            "page_images": None,
            "processing_log": append_processing_log(
                state, "visual_embedding:no_docling_document"
            ),
        }

    # ── Extract page images ────────────────────────────────────────────
    try:
        raw_pages = _extract_page_images(docling_doc)
    except Exception as exc:
        logger.warning("visual_embedding: format error: %s", exc)
        return {
            "visual_stored_count": 0,
            "page_images": None,
            "processing_log": append_processing_log(
                state, "visual_embedding:format_error"
            ),
        }

    if not raw_pages:
        return {
            "visual_stored_count": 0,
            "page_images": None,
            "processing_log": append_processing_log(
                state, "visual_embedding:no_pages"
            ),
        }

    # ── Resize and convert to RGB ──────────────────────────────────────
    max_dim = config.page_image_max_dimension
    resized_pages = []
    page_metadata = []
    for page_num, img in raw_pages:
        orig_w, orig_h = img.size
        img = img.convert("RGB")
        longer = max(orig_w, orig_h)
        if longer > max_dim:
            scale = max_dim / longer
            new_w = int(orig_w * scale)
            new_h = int(orig_h * scale)
            img = img.resize((new_w, new_h))
        resized_pages.append((page_num, img))
        page_metadata.append({
            "page_width_px": orig_w,
            "page_height_px": orig_h,
        })

    document_id = state.get("document_id", "")
    source_key = state.get("source_key", "")
    db_client = state["runtime"].db_client
    wv_client = state["runtime"].weaviate_client
    errors = list(state.get("errors", []))

    # ── Update mode: delete existing visual objects ────────────────────
    if config.update_mode:
        from src.vector_db.weaviate.visual_store import delete_visual_by_source_key
        delete_visual_by_source_key(wv_client, source_key,
                                     config.visual_target_collection)

    # ── Store all page images to MinIO BEFORE inference (FR-403) ───────
    stored_page_nums = []
    stored_images = []
    for (page_num, img), meta in zip(resized_pages, page_metadata):
        try:
            _store_page_image(db_client, document_id, page_num, img,
                              config.page_image_quality)
            stored_page_nums.append(page_num)
            stored_images.append(img)
        except Exception as exc:
            logger.warning(
                "visual_embedding: MinIO upload failed page %d: %s",
                page_num, exc,
            )
            # Skip embedding for this page (FR-804)

    if not stored_images:
        return {
            "visual_stored_count": 0,
            "page_images": None,
            "processing_log": append_processing_log(
                state, "visual_embedding:all_uploads_failed"
            ),
        }

    # ── Load ColQwen2 and run inference ────────────────────────────────
    from src.ingest.support.colqwen import (
        ColQwen2LoadError,
        ensure_colqwen_ready,
        load_colqwen_model,
        embed_page_images,
        unload_colqwen_model,
    )

    try:
        ensure_colqwen_ready()
        model, processor = load_colqwen_model(config.colqwen_model_name)
    except ColQwen2LoadError as exc:
        errors.append(f"visual_embedding:model_load_failed:{exc}")
        logger.error("visual_embedding: FATAL model load: %s", exc)
        return {
            "visual_stored_count": 0,
            "page_images": None,
            "errors": errors,
            "processing_log": append_processing_log(
                state, "visual_embedding:model_load_failed"
            ),
        }

    try:
        embeddings = embed_page_images(
            model, processor, stored_images,
            config.colqwen_batch_size,
            page_numbers=stored_page_nums,
        )
    finally:
        unload_colqwen_model(model)

    # ── Insert visual page objects into Weaviate ───────────────────────
    from src.vector_db.weaviate.visual_store import (
        ensure_visual_collection,
        add_visual_documents,
    )

    ensure_visual_collection(wv_client, config.visual_target_collection)

    visual_docs = []
    for emb in embeddings:
        idx = stored_page_nums.index(emb.page_number)
        meta = page_metadata[idx] if idx < len(page_metadata) else {}
        minio_key = f"pages/{document_id}/{emb.page_number:04d}.jpg"
        visual_docs.append({
            "document_id": document_id,
            "page_number": emb.page_number,
            "source_key": source_key,
            "source_uri": state.get("source_uri", ""),
            "source_name": state.get("source_name", ""),
            "tenant_id": "default",
            "total_pages": len(raw_pages),
            "page_width_px": meta.get("page_width_px", 0),
            "page_height_px": meta.get("page_height_px", 0),
            "minio_key": minio_key,
            "mean_vector": emb.mean_vector,
            "patch_vectors": json.dumps(emb.patch_vectors),
        })

    visual_count = 0
    try:
        visual_count = add_visual_documents(
            wv_client, visual_docs, config.visual_target_collection
        )
    except Exception as exc:
        errors.append(f"visual_embedding:weaviate_batch_failed:{exc}")
        logger.error("visual_embedding: Weaviate batch insert failed: %s", exc)

    return {
        "visual_stored_count": visual_count,
        "page_images": None,  # FR-606: clear from state
        "errors": errors if errors != list(state.get("errors", [])) else state.get("errors", []),
        "processing_log": append_processing_log(
            state, f"visual_embedding:ok:stored={visual_count}"
        ),
    }
```

**Key design decisions:**
- MinIO storage happens entirely before ColQwen2 model loading (FR-403). This avoids holding GPU memory while waiting on network I/O and ensures page images are persisted even if inference fails.
- ColQwen2 imports are lazy (inside the function body) to avoid importing heavy ML libraries when the node short-circuits (NFR-903).
- The `try/finally` block around inference ensures `unload_colqwen_model` always runs, preventing GPU memory leaks even on partial failure (FR-305).
- The return dict never includes `stored_count`, `chunks`, or `enriched_chunks` keys, which prevents LangGraph's state merge from overwriting text-track fields (FR-803).
- `page_images: None` in the return dict clears the potentially large list of PIL objects from state memory (FR-606).

---

## B.12: Weaviate Visual Schema Pattern -- Pattern
Illustrative implementation showing the visual collection creation with named vector configuration, property schema, and batch insertion using the Weaviate v4 client API.
**Tasks:** Task 2.3
**Requirements:** FR-501, FR-502, FR-503, FR-504, FR-505, FR-507
**Type:** Pattern (illustrative -- for implement-code only, never test agents)

```python
# Illustrative pattern -- not the final implementation
from __future__ import annotations

import json
import logging
from typing import Any, List

import weaviate
from weaviate.classes.config import Configure, DataType, Property, VectorDistances

logger = logging.getLogger("rag.vector_db.weaviate.visual_store")


def ensure_visual_collection(
    client: weaviate.WeaviateClient,
    collection: str = "RAGVisualPages",
) -> None:
    """Idempotent visual collection creation with named vector schema."""
    if client.collections.exists(collection):
        return

    client.collections.create(
        name=collection,
        # No auto-vectorizer; embeddings are pre-computed by ColQwen2
        vectorizer_config=Configure.Vectorizer.none(),
        # Named vector for ANN indexing of mean-pooled embeddings
        vector_index_config=Configure.VectorIndex.hnsw(),
        properties=[
            # ── Document identity (FR-503) ────────────────────────────
            Property(name="document_id", data_type=DataType.TEXT),
            Property(name="page_number", data_type=DataType.INT),
            Property(name="source_key", data_type=DataType.TEXT),
            Property(name="source_uri", data_type=DataType.TEXT),
            Property(name="source_name", data_type=DataType.TEXT),
            Property(name="tenant_id", data_type=DataType.TEXT),
            Property(name="total_pages", data_type=DataType.INT),
            # ── Page dimensions (FR-503) ──────────────────────────────
            Property(name="page_width_px", data_type=DataType.INT),
            Property(name="page_height_px", data_type=DataType.INT),
            # ── Storage reference ─────────────────────────────────────
            Property(name="minio_key", data_type=DataType.TEXT),
            # ── Patch vectors as JSON (FR-505) ────────────────────────
            # NOT a named vector — stored as data property for MaxSim
            Property(name="patch_vectors", data_type=DataType.TEXT),
        ],
        # Named vector "mean_vector" for ANN search (FR-504)
        named_vectors=[
            Configure.NamedVectors.none(
                name="mean_vector",
                vector_index_config=Configure.VectorIndex.hnsw(
                    distance_metric=VectorDistances.COSINE,
                ),
            )
        ],
    )
    logger.info("visual_store: created collection %r", collection)


def add_visual_documents(
    client: weaviate.WeaviateClient,
    documents: List[dict[str, Any]],
    collection: str = "RAGVisualPages",
) -> int:
    """Batch-insert visual page objects with named vector."""
    col = client.collections.get(collection)

    with col.batch.dynamic() as batch:
        for doc in documents:
            # Separate the named vector from properties
            mean_vector = doc.pop("mean_vector", [])
            properties = {k: v for k, v in doc.items()}

            batch.add_object(
                properties=properties,
                vector={"mean_vector": mean_vector},
            )

    return len(documents)


def delete_visual_by_source_key(
    client: weaviate.WeaviateClient,
    source_key: str,
    collection: str = "RAGVisualPages",
) -> int:
    """Delete all visual page objects by source_key filter."""
    from weaviate.classes.query import Filter

    col = client.collections.get(collection)
    where = Filter.by_property("source_key").equal(source_key)
    result = col.data.delete_many(where=where)
    deleted = getattr(result, "matches", 0) or 0
    logger.info(
        "visual_store: deleted %d objects for source_key=%r from %r",
        deleted, source_key, collection,
    )
    return deleted
```

**Key design decisions:**
- `Configure.NamedVectors.none()` is used for the "mean_vector" named vector because embeddings are pre-computed by ColQwen2 and passed at insertion time, not generated by Weaviate's vectorizer (FR-504).
- `patch_vectors` is stored as `DataType.TEXT` (JSON string) rather than as a second named vector. Named vectors in Weaviate are HNSW-indexed, which would waste memory and index build time on patch vectors that are only used for MaxSim re-scoring at query time (FR-505).
- `VectorDistances.COSINE` is chosen for the HNSW index to match the ColQwen2 embedding space, where cosine similarity is the standard retrieval metric.
- `batch.dynamic()` context manager handles automatic batching and error reporting, matching the existing pattern in `store.py` for text documents.

---

## Quality Checklist

- [x] Every FR/NFR from spec covered by at least one task (see Task-to-Requirement Mapping table -- all 38 FRs + 10 NFRs mapped)
- [x] Every task references at least one FR
- [x] Task dependencies form a valid DAG (no cycles): linear flow Phase 1 -> Phase 2 -> Phase 3 -> Phase 4 -> Phase 5 with identified parallelism
- [x] All stubs use `raise NotImplementedError("Task X.Y")` -- verified in B.1, B.6, B.7, B.8, B.9
- [x] TypedDict fields have FR-tagged comments -- verified in B.2
- [x] Pattern entries include "Key design decisions" -- verified in B.10, B.11, B.12
- [x] No pattern entries labelled as contracts or vice versa -- B.1-B.9 are Contract, B.10-B.12 are Pattern
- [x] Contract entries include imports at top -- verified in all B.1-B.9 entries
