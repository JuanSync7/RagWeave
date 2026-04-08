# Visual Page Retrieval Pipeline — Design Document

| Field | Value |
|-------|-------|
| **Document** | Visual Page Retrieval Pipeline Design Document |
| **Version** | 0.1 |
| **Status** | Draft |
| **Spec Reference** | `docs/ingestion/visual_retrieval/VISUAL_RETRIEVAL_SPEC.md` (FR-101 through FR-703, NFR-901 through NFR-911) |
| **Companion Documents** | `docs/ingestion/visual_retrieval/VISUAL_RETRIEVAL_SPEC.md` |
| **Output Path** | `docs/ingestion/visual_retrieval/VISUAL_RETRIEVAL_DESIGN.md` |
| **Produced by** | write-design-docs |
| **Task Decomposition Status** | [x] Approved |

> **Document Intent.** This document provides a technical design with task decomposition
> and contract-grade code appendix for the visual page retrieval pipeline specified in
> `docs/ingestion/visual_retrieval/VISUAL_RETRIEVAL_SPEC.md`.
> Every task references the requirements it satisfies. Part B contract entries are consumed
> verbatim by the companion implementation docs.

---

# Part A: Task-Oriented Overview

## Phase 1 — Configuration Foundation

### Task 1.1: Visual Retrieval Configuration Keys

**Description:** Add all retrieval-side visual configuration keys to `config/settings.py`, including the master enable toggle, result limit, score threshold, URL expiry, stage budget, and a startup validation function that fails fast on contradictory or out-of-range settings. Reuse the existing `RAG_INGESTION_COLQWEN_MODEL` key for retrieval-time model selection (single source of truth).

**Requirements Covered:** FR-101, FR-103, FR-105, FR-107, FR-109, FR-111, FR-617, NFR-907

**Dependencies:** None

**Complexity:** S

**Subtasks:**
1. Add `RAG_VISUAL_RETRIEVAL_ENABLED` boolean config key (default `false`) to `config/settings.py`
2. Add `RAG_VISUAL_RETRIEVAL_LIMIT` integer config key (default `5`, clamped to 1-50) with boundary warning
3. Add `RAG_VISUAL_RETRIEVAL_MIN_SCORE` float config key (default `0.3`, range 0.0-1.0)
4. Add `RAG_VISUAL_RETRIEVAL_URL_EXPIRY_SECONDS` integer config key (default `3600`, range 60-86400)
5. Add `RAG_STAGE_BUDGET_VISUAL_RETRIEVAL_MS` integer config key (default `10000`)
6. Implement `validate_visual_retrieval_config()` that checks: enabled + empty collection name raises error; score threshold out of range raises error; limit out of range logs warning and clamps

**Testing Strategy:** Unit test each config key with default, explicit value, and boundary conditions. Unit test validation function with contradictory/invalid settings.

---

## Phase 2 — Leaf Components

### Task 2.1: ColQwen2 Text Query Encoder

**Description:** Add an `embed_text_query()` function to the existing ColQwen2 adapter module (`src/ingest/support/colqwen.py`) that encodes a text query string into a 128-dimensional float vector using ColQwen2's text encoding pathway (`processor.process_queries()`), with mean pooling to match the image embedding format.

**Requirements Covered:** FR-201, FR-203, FR-205, FR-207

**Dependencies:** Task 1.1

**Complexity:** S

**Subtasks:**
1. Add `embed_text_query(model, processor, text) -> list[float]` function signature with full docstring
2. Implement empty/whitespace input guard that raises `ValueError` before invoking the model
3. Implement `None` model/processor guard that raises `ColQwen2LoadError`
4. Implement text encoding via `processor.process_queries([text])`, forward pass under `torch.inference_mode()`, mean pooling across token-level vectors to produce a 128-dim float32 vector
5. Wrap unexpected inference errors in `VisualEmbeddingError` with chained exception
6. Update module `@summary` to include `embed_text_query` in exports

**Testing Strategy:** Unit test with mock model/processor: verify 128-dim output, determinism, empty string raises ValueError, None model raises ColQwen2LoadError, inference failure wraps in VisualEmbeddingError.

---

### Task 2.2: Weaviate Visual Search Function

**Description:** Add a `visual_search()` function to the existing Weaviate visual store module (`src/vector_db/weaviate/visual_store.py`) that performs nearest-neighbor search on the `mean_vector` named vector of the `RAGVisualPages` collection, returning page objects ranked by cosine similarity with configurable limit, score threshold, and tenant filtering.

**Requirements Covered:** FR-301, FR-303, FR-305, FR-307, FR-309, FR-311

**Dependencies:** Task 1.1

**Complexity:** S

**Subtasks:**
1. Add `visual_search()` function with parameters: `client`, `query_vector`, `limit`, `score_threshold`, `tenant_id` (optional), `collection` (optional, defaults to `RAG_INGESTION_VISUAL_TARGET_COLLECTION`)
2. Implement near-vector query targeting the `mean_vector` named vector with cosine distance
3. Implement score threshold filtering (exclude results below threshold)
4. Implement optional tenant_id property filter
5. Return list of dicts with: `document_id`, `page_number`, `source_key`, `source_name`, `minio_key`, `tenant_id`, `total_pages`, `page_width_px`, `page_height_px`, `score` -- explicitly excluding `patch_vectors`
6. Add observability span via `get_tracer()` with result_count attribute
7. Update module `@summary` to include `visual_search` in exports

**Testing Strategy:** Unit test with mock Weaviate client: verify result structure, score filtering, tenant filtering, empty results, collection parameter propagation.

---

### Task 2.3: MinIO Page Image Presigned URL

**Description:** Add a `get_page_image_url()` function to the existing MinIO store module (`src/db/minio/store.py`) that generates a presigned GET URL for an arbitrary MinIO object key (without appending any suffix), using configurable bucket and expiry defaults.

**Requirements Covered:** FR-401, FR-403

**Dependencies:** Task 1.1

**Complexity:** S

**Subtasks:**
1. Add `get_page_image_url(client, minio_key, bucket, expires_in_seconds)` function with defaults from config
2. Implement presigned URL generation via `client.presigned_get_object()` using the raw key (no suffix appended)
3. Default `bucket` to `MINIO_BUCKET` and `expires_in_seconds` to `RAG_VISUAL_RETRIEVAL_URL_EXPIRY_SECONDS`
4. Add observability span via `get_tracer()`
5. Update module `@summary` to include `get_page_image_url` in exports

**Testing Strategy:** Unit test with mock MinIO client: verify raw key is passed without suffix, default parameters applied, explicit overrides work.

---

## Phase 3 — Abstraction and Schema Layer

### Task 3.1: Vector Backend Abstraction Extension

**Description:** Extend the `VectorBackend` abstract base class, `WeaviateBackend` implementation, and `vector_db/__init__.py` public API with a `search_visual()` method that delegates to the visual store's `visual_search()` function, maintaining the established backend abstraction pattern.

**Requirements Covered:** FR-313

**Dependencies:** Task 2.2

**Complexity:** S

**Subtasks:**
1. Add abstract `search_visual()` method to `VectorBackend` in `src/vector_db/backend.py`
2. Implement `search_visual()` in `WeaviateBackend` in `src/vector_db/weaviate/backend.py`, delegating to `visual_search()`
3. Add `search_visual()` public function to `src/vector_db/__init__.py` that routes through the backend singleton
4. Add `search_visual` to the `__all__` export list
5. Update `@summary` blocks in all three files

**Testing Strategy:** Unit test: verify abstract method exists, WeaviateBackend delegates correctly, public API routes to backend.

---

### Task 3.2: Retrieval Schema Extension

**Description:** Add a `VisualPageResult` dataclass to the retrieval schemas module and extend `RAGResponse` with an optional `visual_results` field, maintaining backward compatibility with existing text-only responses.

**Requirements Covered:** FR-501, FR-503

**Dependencies:** None

**Complexity:** S

**Subtasks:**
1. Define `VisualPageResult` dataclass in `src/retrieval/common/schemas.py` with fields: `document_id`, `page_number`, `source_key`, `source_name`, `score`, `page_image_url`, `total_pages`, `page_width_px`, `page_height_px`
2. Add `visual_results: Optional[List[VisualPageResult]]` field to `RAGResponse` dataclass with default `None`
3. Update module `@summary` to include `VisualPageResult` in exports

**Testing Strategy:** Unit test: verify VisualPageResult instantiation, RAGResponse backward compatibility (visual_results defaults to None), RAGResponse with visual_results populated.

---

## Phase 4 — Pipeline Integration

### Task 4.1: RAGChain Visual Track Integration

**Description:** Integrate the visual retrieval track into `RAGChain` as an additive post-text-reranking stage. Implement lazy ColQwen2 model loading on first visual query, sequential execution after text track completion, presigned URL generation per result, graceful degradation on any visual track failure, stage timing recording, observability spans, and model cleanup on `close()`. When visual retrieval is disabled, the system incurs zero additional overhead.

**Requirements Covered:** FR-601, FR-603, FR-605, FR-607, FR-609, FR-611, FR-613, FR-615, FR-617, NFR-901, NFR-903, NFR-905, NFR-909, NFR-911

**Dependencies:** Task 2.1, Task 2.3, Task 3.1, Task 3.2

**Complexity:** L

**Subtasks:**
1. Add lazy-loading attributes `_visual_model`, `_visual_processor` (both `None` initially) to `RAGChain.__init__()` -- no ColQwen2 imports or loading at init time when visual retrieval is enabled
2. Implement `_ensure_visual_model()` private method that loads ColQwen2 on first call and caches the model/processor pair for subsequent queries
3. In `run()`, after reranking and before generation, add a visual retrieval block guarded by `RAG_VISUAL_RETRIEVAL_ENABLED` config check
4. Within the visual block: call `embed_text_query()` with the processed query, then `search_visual()` with the query vector, limit, score threshold, and tenant_id, then `get_page_image_url()` for each result's `minio_key`
5. Assemble `VisualPageResult` list and assign to `RAGResponse.visual_results`
6. Wrap the entire visual block in try/except: on any exception, log warning, set `visual_results=[]`, continue with text results
7. Record `visual_retrieval` stage timing in `stage_timings` and check stage budget
8. Add observability spans: `visual_retrieval.model_load` (cold start only), `visual_retrieval.text_encode`, `visual_retrieval.search`, `visual_retrieval.presigned_urls`
9. Extend `close()` to call `unload_colqwen_model()` on `_visual_model` if loaded, and set references to `None`
10. When `RAG_VISUAL_RETRIEVAL_ENABLED=false`, set `visual_results=None` on response -- no visual imports, no model loading, no search

**Risks:**
- VRAM coexistence: BGE-M3 + BGE-reranker + ColQwen2 may exceed 5.5 GB on RTX 2060. Mitigation: lazy loading defers ColQwen2 to after text stages complete; if VRAM is exceeded, the graceful degradation handler catches the CUDA OOM and returns `visual_results=[]`.
- Cold-start latency: first visual query triggers model loading (up to 30 seconds). Mitigation: stage budget (`RAG_STAGE_BUDGET_VISUAL_RETRIEVAL_MS`) allows partial results on timeout; subsequent queries use cached model.

**Testing Strategy:** Unit test with mocked dependencies: verify lazy loading (model not loaded at init), sequential execution order, graceful degradation on each failure mode (model load, encoding, search, URL generation), stage timing recorded, zero-cost when disabled. Integration test: full pipeline with visual retrieval enabled returns both text and visual results.

---

## Phase 5 — API Surface

### Task 5.1: Server API Schema Extension

**Description:** Add a `VisualPageResultResponse` Pydantic model to the server schemas module and extend `QueryResponse` with an optional `visual_results` field, maintaining backward compatibility for existing API clients.

**Requirements Covered:** FR-701, FR-703

**Dependencies:** Task 3.2

**Complexity:** S

**Subtasks:**
1. Define `VisualPageResultResponse` Pydantic model in `server/schemas.py` with all `VisualPageResult` fields
2. Add `visual_results: Optional[list[VisualPageResultResponse]]` field to `QueryResponse` with default `None`
3. Add `"visual_retrieval"` to the allowed stage budget override keys in `QueryRequest` model validator
4. Update module `@summary` to include `VisualPageResultResponse` in exports

**Testing Strategy:** Unit test: verify Pydantic serialization/deserialization, backward compatibility (existing responses unaffected), OpenAPI schema inclusion.

---

## Task Dependency Graph

```
                    ┌─────────────────────────────────────────┐
                    │                                         │
                    │  1.1: Visual Retrieval Config Keys       │
                    │  [Phase 1 — Foundation]                  │
                    │                                         │
                    └──────┬──────────┬──────────┬────────────┘
                           │          │          │
                    ┌──────▼──┐  ┌────▼────┐  ┌──▼──────────┐
                    │ 2.1:    │  │ 2.2:    │  │ 2.3:        │
                    │ ColQwen │  │ Weaviate│  │ MinIO       │
                    │ Text    │  │ Visual  │  │ Presigned   │
                    │ Encoder │  │ Search  │  │ URL         │
                    └────┬────┘  └────┬────┘  └──────┬──────┘
                         │            │              │
                         │       ┌────▼────┐         │
                         │       │ 3.1:    │         │
                         │       │ Backend │         │
                         │       │ Abstract│         │
                         │       └────┬────┘         │
                         │            │              │
    ┌──────────┐         │            │              │
    │ 3.2:     │         │            │              │
    │ Retrieval│         │            │              │
    │ Schema   │─────────┼────────────┼──────────────┤
    └────┬─────┘         │            │              │
         │               │            │              │
         │          ┌────▼────────────▼──────────────▼──┐
         │          │                                    │
         ├─────────>│ 4.1: RAGChain Visual Track         │
         │          │      Integration [CRITICAL]        │
         │          │                                    │
         │          └────────────────────────────────────┘
         │
    ┌────▼─────┐
    │ 5.1:     │
    │ Server   │
    │ API      │
    │ Schema   │
    └──────────┘

Critical Path: 1.1 ──> 2.2 ──> 3.1 ──> 4.1  [CRITICAL]
```

---

## Task-to-Requirement Traceability

| REQ ID | Priority | Task(s) |
|--------|----------|---------|
| FR-101 | MUST | Task 1.1 |
| FR-103 | MUST | Task 1.1 |
| FR-105 | MUST | Task 1.1 |
| FR-107 | SHOULD | Task 1.1 |
| FR-109 | MUST | Task 1.1 |
| FR-111 | MUST | Task 1.1 |
| FR-201 | MUST | Task 2.1 |
| FR-203 | MUST | Task 2.1 |
| FR-205 | MUST | Task 2.1 |
| FR-207 | MUST | Task 2.1 |
| FR-301 | MUST | Task 2.2 |
| FR-303 | MUST | Task 2.2 |
| FR-305 | MUST | Task 2.2 |
| FR-307 | MUST | Task 2.2 |
| FR-309 | MUST | Task 2.2 |
| FR-311 | MUST | Task 2.2 |
| FR-313 | MUST | Task 3.1 |
| FR-401 | MUST | Task 2.3 |
| FR-403 | MUST | Task 2.3 |
| FR-501 | MUST | Task 3.2 |
| FR-503 | MUST | Task 3.2 |
| FR-601 | MUST | Task 4.1 |
| FR-603 | MUST | Task 4.1 |
| FR-605 | MUST | Task 4.1 |
| FR-607 | MUST | Task 4.1 |
| FR-609 | MUST | Task 4.1 |
| FR-611 | MUST | Task 4.1 |
| FR-613 | MUST | Task 4.1 |
| FR-615 | MUST | Task 4.1 |
| FR-617 | SHOULD | Task 1.1, Task 4.1 |
| FR-701 | MUST | Task 5.1 |
| FR-703 | MUST | Task 5.1 |
| NFR-901 | SHOULD | Task 4.1 |
| NFR-903 | MUST | Task 4.1 |
| NFR-905 | MUST | Task 4.1 |
| NFR-907 | MUST | Task 1.1 |
| NFR-909 | MUST | Task 4.1 |
| NFR-911 | SHOULD | Task 4.1 |

**Coverage:** 37/37 requirements covered. 0 orphan tasks.

---

# Part B: Code Appendix

## B.1: Visual Retrieval Configuration Keys — Contract

Configuration keys and validation function for the visual retrieval pipeline. Used by all tasks that read retrieval-side visual config.

**Tasks:** Task 1.1
**Requirements:** FR-101, FR-103, FR-105, FR-107, FR-109, FR-111, FR-617, NFR-907
**Type:** Contract (exact — copied to implementation docs Phase 0)

```python
import logging
import os

logger = logging.getLogger(__name__)

# --- Visual Retrieval Pipeline (retrieval-side) ---

RAG_VISUAL_RETRIEVAL_ENABLED: bool = os.environ.get(
    "RAG_VISUAL_RETRIEVAL_ENABLED", "false"
).lower() in ("true", "1", "yes")  # FR-101

_raw_visual_limit = int(os.environ.get("RAG_VISUAL_RETRIEVAL_LIMIT", "5"))
if _raw_visual_limit < 1 or _raw_visual_limit > 50:
    logger.warning(
        "RAG_VISUAL_RETRIEVAL_LIMIT=%d out of range [1, 50]; clamping.",
        _raw_visual_limit,
    )
RAG_VISUAL_RETRIEVAL_LIMIT: int = max(1, min(50, _raw_visual_limit))  # FR-103

RAG_VISUAL_RETRIEVAL_MIN_SCORE: float = float(
    os.environ.get("RAG_VISUAL_RETRIEVAL_MIN_SCORE", "0.3")
)  # FR-105

RAG_VISUAL_RETRIEVAL_URL_EXPIRY_SECONDS: int = int(
    os.environ.get("RAG_VISUAL_RETRIEVAL_URL_EXPIRY_SECONDS", "3600")
)  # FR-107

RAG_STAGE_BUDGET_VISUAL_RETRIEVAL_MS: int = int(
    os.environ.get("RAG_STAGE_BUDGET_VISUAL_RETRIEVAL_MS", "10000")
)  # FR-617

# NOTE: RAG_INGESTION_COLQWEN_MODEL is reused for retrieval-time model
# selection (FR-109). No separate retrieval model key exists.


def validate_visual_retrieval_config() -> None:
    """Validate visual retrieval configuration at startup.

    Checks for contradictory or out-of-range settings and raises
    ValueError with a descriptive message identifying the conflicting keys.

    Called during RAGChain initialization when RAG_VISUAL_RETRIEVAL_ENABLED
    is True.

    Raises:
        ValueError: If visual retrieval is enabled but the visual target
            collection is empty, or if score threshold is out of [0.0, 1.0],
            or if URL expiry is out of [60, 86400].
    """
    raise NotImplementedError("Task 1.1")
```

**Key design decisions:**
- Clamping (not rejecting) out-of-range `RAG_VISUAL_RETRIEVAL_LIMIT` matches the spec's acceptance criteria (FR-103: "clamps to the nearest boundary")
- `validate_visual_retrieval_config()` is a standalone function called lazily (not at module import time) to avoid import-time side effects; called from RAGChain init when visual retrieval is enabled
- `RAG_INGESTION_COLQWEN_MODEL` is reused per FR-109 -- no separate retrieval model key, eliminating model mismatch errors

---

## B.2: VisualPageResult Schema — Contract

Dataclass for visual page retrieval results and RAGResponse extension. Central schema consumed by RAGChain, server API, and all downstream formatting.

**Tasks:** Task 3.2
**Requirements:** FR-501, FR-503
**Type:** Contract (exact — copied to implementation docs Phase 0)

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class VisualPageResult:
    """A single visual page retrieval result with its similarity score.

    Represents a document page matched by ColQwen2 visual embedding search,
    with a presigned MinIO URL for direct image access.
    """

    document_id: str          # Document identifier (FR-501)
    page_number: int          # 1-indexed page number (FR-501)
    source_key: str           # Stable source key for traceability (FR-501)
    source_name: str          # Human-readable source name (FR-501)
    score: float              # Cosine similarity 0.0-1.0 (FR-501)
    page_image_url: str       # Presigned MinIO URL (FR-501, FR-607)
    total_pages: int          # Total pages in source document (FR-501)
    page_width_px: int        # Page image width in pixels (FR-501)
    page_height_px: int       # Page image height in pixels (FR-501)


# Extension to RAGResponse (add to existing dataclass):
# visual_results: Optional[List[VisualPageResult]] = None  # FR-503
```

**Key design decisions:**
- Dataclass (not TypedDict) matches the existing `RankedResult` pattern used in the same module
- `page_image_url` is populated at query time with a fresh presigned URL, not stored in Weaviate
- `Optional[List[VisualPageResult]]` with `None` default maintains backward compatibility: `None` means disabled, `[]` means enabled but no matches

---

## B.3: ColQwen2 Text Query Encoder — Contract

Function stub for text query encoding added to the existing ColQwen2 adapter module.

**Tasks:** Task 2.1
**Requirements:** FR-201, FR-203, FR-205, FR-207
**Type:** Contract (exact — copied to implementation docs Phase 0)

```python
from __future__ import annotations

from typing import Any


# These are defined in the existing module — included for reference:
# class VisualEmbeddingError(Exception): ...
# class ColQwen2LoadError(VisualEmbeddingError): ...


def embed_text_query(model: Any, processor: Any, text: str) -> list[float]:
    """Encode a text query into a 128-dimensional float vector using ColQwen2.

    Uses ``processor.process_queries([text])`` to tokenize the input, passes
    the tokenized input through the model under ``torch.inference_mode()``,
    and produces a single 128-dim vector by mean-pooling across token-level
    output vectors. The result dtype is float32 (Python ``float``).

    Args:
        model: Loaded ColQwen2 model (from ``load_colqwen_model()``).
        processor: Loaded ColQwen2Processor (from ``load_colqwen_model()``).
        text: Non-empty query text to encode.

    Returns:
        A list of exactly 128 float values representing the mean-pooled
        query embedding in the ColQwen2 vector space.

    Raises:
        ValueError: If ``text`` is empty or contains only whitespace.
            The model is not invoked. Message contains "empty" or "blank".
        ColQwen2LoadError: If ``model`` or ``processor`` is None or invalid.
        VisualEmbeddingError: If the model's forward pass raises an unexpected
            error (e.g., CUDA OOM). The original exception is chained as
            ``__cause__``.
    """
    raise NotImplementedError("Task 2.1")
```

**Key design decisions:**
- Function added to existing `src/ingest/support/colqwen.py` (not a new module) to keep the ColQwen2 adapter as a single source of truth for all ColQwen2 interactions
- `process_queries` (not `process_images`) is the correct ColQwen2 processor method for text encoding
- Mean pooling across token-level vectors matches the mean pooling used for image patches during ingestion, ensuring compatible embedding spaces

---

## B.4: Weaviate Visual Search — Contract

Function stub for near-vector search on the visual collection.

**Tasks:** Task 2.2
**Requirements:** FR-301, FR-303, FR-305, FR-307, FR-309, FR-311
**Type:** Contract (exact — copied to implementation docs Phase 0)

```python
from __future__ import annotations

from typing import Any, List, Optional

import weaviate


def visual_search(
    client: weaviate.WeaviateClient,
    query_vector: list[float],
    limit: int,
    score_threshold: float,
    tenant_id: Optional[str] = None,
    collection: str = "RAGVisualPages",
) -> list[dict[str, Any]]:
    """Search the visual page collection by near-vector similarity.

    Performs nearest-neighbor search on the ``mean_vector`` named vector
    of the specified collection using cosine distance. Results below
    ``score_threshold`` are excluded. The ``patch_vectors`` property is
    never included in results.

    Args:
        client: Weaviate client handle.
        query_vector: 128-dim float query vector (from ``embed_text_query``).
        limit: Maximum number of results to return (FR-303).
        score_threshold: Minimum cosine similarity; results below this
            are excluded (FR-303).
        tenant_id: When provided, only pages with matching ``tenant_id``
            are returned (FR-305). When None, no tenant filter applied.
        collection: Target collection name. Defaults to
            ``RAG_INGESTION_VISUAL_TARGET_COLLECTION`` value (FR-307).

    Returns:
        List of dicts ordered by descending cosine similarity, each
        containing: ``document_id`` (str), ``page_number`` (int),
        ``source_key`` (str), ``source_name`` (str), ``minio_key`` (str),
        ``tenant_id`` (str), ``total_pages`` (int), ``page_width_px`` (int),
        ``page_height_px`` (int), ``score`` (float). The ``patch_vectors``
        property is excluded (FR-311).

    Raises:
        weaviate.exceptions.WeaviateQueryError: On query failure.
    """
    raise NotImplementedError("Task 2.2")
```

**Key design decisions:**
- Default collection parameter uses string literal `"RAGVisualPages"` matching the existing pattern in `ensure_visual_collection()`, `add_visual_documents()`, and `delete_visual_by_source_key()`
- Returns `list[dict]` (not dataclass) matching the existing `hybrid_search()` return pattern in `store.py` -- the dataclass conversion happens at the RAGChain level
- Explicit exclusion of `patch_vectors` from the Weaviate query to prevent hundreds-of-KB payloads per result

---

## B.5: Vector Backend search_visual — Contract

Abstract method and delegation chain for visual search through the backend abstraction.

**Tasks:** Task 3.1
**Requirements:** FR-313
**Type:** Contract (exact — copied to implementation docs Phase 0)

```python
from __future__ import annotations

from abc import abstractmethod
from typing import Any, List, Optional


# Add to VectorBackend ABC (src/vector_db/backend.py):

@abstractmethod
def search_visual(
    self,
    client: Any,
    query_vector: list[float],
    limit: int,
    score_threshold: float,
    tenant_id: Optional[str] = None,
    collection: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Search the visual page collection by near-vector similarity.

    Args:
        client: Backend client handle.
        query_vector: 128-dim float query vector.
        limit: Maximum number of results.
        score_threshold: Minimum cosine similarity threshold.
        tenant_id: Optional tenant filter.
        collection: Visual collection name. None uses default.

    Returns:
        List of visual page result dicts ordered by descending score.
    """
    ...
```

**Key design decisions:**
- Method signature mirrors `visual_search()` in the store module, with `Optional[str]` collection parameter following the established backend pattern (None resolves to default)
- Return type `list[dict]` passes through from the store module; no intermediate schema conversion at the backend layer

---

## B.6: MinIO Page Image Presigned URL — Contract

Function stub for generating presigned URLs for page image objects.

**Tasks:** Task 2.3
**Requirements:** FR-401, FR-403
**Type:** Contract (exact — copied to implementation docs Phase 0)

```python
from __future__ import annotations

from minio import Minio


def get_page_image_url(
    client: Minio,
    minio_key: str,
    bucket: str = "",
    expires_in_seconds: int = 0,
) -> str:
    """Generate a presigned GET URL for a page image object.

    Unlike ``get_document_url()``, this function does NOT append any suffix
    to the key. The ``minio_key`` is used as-is (e.g.,
    ``pages/{document_id}/{page_number:04d}.jpg``).

    If the object does not exist in MinIO, a presigned URL is still
    generated (MinIO does not verify existence at signing time).

    Args:
        client: MinIO client handle.
        minio_key: Full MinIO object key for the page image (FR-401).
        bucket: Target bucket. Defaults to ``MINIO_BUCKET`` when empty
            string or not provided (FR-403).
        expires_in_seconds: URL expiry duration in seconds. Defaults to
            ``RAG_VISUAL_RETRIEVAL_URL_EXPIRY_SECONDS`` when 0 or not
            provided (FR-403).

    Returns:
        Presigned GET URL string for the page image.
    """
    raise NotImplementedError("Task 2.3")
```

**Key design decisions:**
- Sentinel defaults (empty string for bucket, 0 for expiry) avoid import-time dependency on config keys while allowing config-driven defaults at call time
- Does not append `.md` or any other suffix (unlike `get_document_url()`) since page image keys already include the full path and extension

---

## B.7: Server API Visual Schema — Contract

Pydantic model for visual page results in the API response layer.

**Tasks:** Task 5.1
**Requirements:** FR-701, FR-703
**Type:** Contract (exact — copied to implementation docs Phase 0)

```python
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class VisualPageResultResponse(BaseModel):
    """A single visual page retrieval result for API serialization.

    Maps 1:1 from the ``VisualPageResult`` dataclass in the retrieval
    schemas module. Included in the OpenAPI schema.
    """

    document_id: str            # FR-701
    page_number: int            # FR-701
    source_key: str             # FR-701
    source_name: str            # FR-701
    score: float                # FR-701 — cosine similarity 0.0-1.0
    page_image_url: str         # FR-701 — presigned MinIO URL
    total_pages: int            # FR-701
    page_width_px: int          # FR-701
    page_height_px: int         # FR-701


# Extension to QueryResponse (add to existing model):
# visual_results: Optional[list[VisualPageResultResponse]] = None  # FR-703
```

**Key design decisions:**
- Pydantic model (not raw dict) ensures API contract validation and OpenAPI schema generation
- 1:1 field mapping from `VisualPageResult` dataclass avoids translation complexity
- Optional with `None` default on `QueryResponse` maintains backward compatibility for existing API clients

---

## B.8: RAGChain Visual Track Integration — Pattern

Illustrative pattern showing the visual retrieval integration point within `RAGChain.run()`, lazy model management, and graceful degradation.

**Tasks:** Task 4.1
**Requirements:** FR-601, FR-603, FR-605, FR-607, FR-609, FR-611, FR-613, FR-615, NFR-905, NFR-909
**Type:** Pattern (illustrative — for implement-code only, never test agents)

```python
# Illustrative pattern — not the final implementation
# Shows: lazy loading, sequential placement, graceful degradation, timing

class RAGChain:
    def __init__(self, persistent_weaviate: bool = True):
        # ... existing init code ...

        # Visual retrieval: lazy-loaded attributes (FR-603, FR-615)
        self._visual_model = None
        self._visual_processor = None
        self._visual_retrieval_enabled = RAG_VISUAL_RETRIEVAL_ENABLED
        if self._visual_retrieval_enabled:
            validate_visual_retrieval_config()  # FR-111

    def _ensure_visual_model(self):
        """Lazy-load ColQwen2 on first visual query (FR-603)."""
        if self._visual_model is not None:
            return
        with self.tracer.span("visual_retrieval.model_load") as span:
            from src.ingest.support.colqwen import (
                ensure_colqwen_ready,
                load_colqwen_model,
            )
            from config.settings import RAG_INGESTION_COLQWEN_MODEL

            ensure_colqwen_ready()
            self._visual_model, self._visual_processor = load_colqwen_model(
                RAG_INGESTION_COLQWEN_MODEL
            )
            span.set_attribute("model", RAG_INGESTION_COLQWEN_MODEL)
            logger.info("ColQwen2 model loaded for visual retrieval (cold start).")

    def _run_visual_retrieval(self, processed_query, tenant_id):
        """Execute visual track: encode -> search -> presigned URLs (FR-601)."""
        from src.ingest.support.colqwen import embed_text_query
        from src.vector_db import search_visual
        from src.db.minio.store import get_page_image_url, create_client as minio_client

        # Step 1: Lazy model load (FR-603)
        self._ensure_visual_model()

        # Step 2: Text encoding (FR-605 — uses processed query)
        with self.tracer.span("visual_retrieval.text_encode") as span:
            query_vector = embed_text_query(
                self._visual_model, self._visual_processor, processed_query
            )
            span.set_attribute("vector_dim", len(query_vector))

        # Step 3: Visual search (FR-609 — passes tenant_id)
        with self.tracer.span("visual_retrieval.search") as span:
            raw_results = search_visual(
                client=self._weaviate_client,
                query_vector=query_vector,
                limit=RAG_VISUAL_RETRIEVAL_LIMIT,
                score_threshold=RAG_VISUAL_RETRIEVAL_MIN_SCORE,
                tenant_id=tenant_id,
            )
            span.set_attribute("result_count", len(raw_results))

        # Step 4: Presigned URLs (FR-607)
        visual_results = []
        mc = minio_client()
        with self.tracer.span("visual_retrieval.presigned_urls"):
            for r in raw_results:
                try:
                    url = get_page_image_url(mc, r["minio_key"])
                    visual_results.append(VisualPageResult(
                        document_id=r["document_id"],
                        page_number=r["page_number"],
                        source_key=r["source_key"],
                        source_name=r["source_name"],
                        score=r["score"],
                        page_image_url=url,
                        total_pages=r["total_pages"],
                        page_width_px=r["page_width_px"],
                        page_height_px=r["page_height_px"],
                    ))
                except Exception as exc:
                    logger.warning("Presigned URL failed for %s: %s", r["minio_key"], exc)

        return visual_results

    def run(self, query, ...):
        # ... existing text track stages 1-5 ...

        # Stage 5.5 (after reranking, before generation): Visual retrieval
        visual_results = None  # FR-615: None when disabled
        if self._visual_retrieval_enabled:
            t0 = time.perf_counter()
            try:
                visual_results = self._run_visual_retrieval(processed_query, tenant_id)
            except Exception as exc:
                # NFR-905: graceful degradation — never block text results
                logger.warning("Visual retrieval failed: %s — returning empty.", exc)
                visual_results = []  # [] means enabled-but-failed (not None)
            tp.record("visual_retrieval", "retrieval", started_at=t0)  # FR-611

        # ... existing generation stage ...

        return RAGResponse(
            # ... existing fields ...
            visual_results=visual_results,  # FR-503
        )

    def close(self):
        # ... existing cleanup ...
        # FR-613: unload ColQwen2 if loaded
        if self._visual_model is not None:
            from src.ingest.support.colqwen import unload_colqwen_model
            unload_colqwen_model(self._visual_model)
            self._visual_model = None
            self._visual_processor = None
            logger.info("ColQwen2 visual model unloaded.")
```

**Key design decisions:**
- Visual track placed after reranking and before generation (Stage 5.5) to ensure sequential GPU access: BGE models finish before ColQwen2 runs
- Lazy imports within methods (`from src.ingest.support.colqwen import ...`) ensure zero-cost when visual retrieval is disabled -- no ColQwen2 module imports at class definition time
- `visual_results=None` vs `visual_results=[]` semantic distinction: `None` means feature disabled, `[]` means feature enabled but no results or feature failed gracefully
- Entire visual block wrapped in try/except at the `run()` level, with per-page try/except for presigned URL generation, implementing the two-tier graceful degradation from NFR-905
- MinIO client created inline per visual query (stateless, safe to share per existing pattern)

---

## B.9: Weaviate Near-Vector Query — Pattern

Illustrative pattern showing the Weaviate near-vector query construction for the visual collection using the named vector and cosine distance.

**Tasks:** Task 2.2
**Requirements:** FR-309, FR-311, FR-305
**Type:** Pattern (illustrative — for implement-code only, never test agents)

```python
# Illustrative pattern — not the final implementation
# Shows: near_vector query on named vector with property filtering

import weaviate
from weaviate.classes.query import Filter, MetadataQuery

from src.platform.observability.providers import get_tracer

tracer = get_tracer()


def visual_search(client, query_vector, limit, score_threshold,
                  tenant_id=None, collection="RAGVisualPages"):
    """Near-vector search on the visual collection's mean_vector."""
    span = tracer.start_span(
        "vector_store.visual_search",
        {"limit": limit, "score_threshold": score_threshold, "collection": collection},
    )
    col = client.collections.get(collection)

    # Build tenant filter if provided (FR-305)
    filters = None
    if tenant_id is not None:
        filters = Filter.by_property("tenant_id").equal(tenant_id)

    # Near-vector query targeting the named vector (FR-309)
    # Weaviate returns cosine distance; convert to similarity = 1 - distance
    response = col.query.near_vector(
        near_vector=query_vector,
        target_vector="mean_vector",      # Named vector (FR-309)
        limit=limit,
        filters=filters,
        return_metadata=MetadataQuery(distance=True),
        # Explicitly select properties, excluding patch_vectors (FR-311)
        return_properties=[
            "document_id", "page_number", "source_key", "source_name",
            "minio_key", "tenant_id", "total_pages",
            "page_width_px", "page_height_px",
        ],
    )

    results = []
    for obj in response.objects:
        # Convert cosine distance to cosine similarity
        distance = obj.metadata.distance if obj.metadata else 1.0
        score = 1.0 - distance

        # Apply score threshold filter (FR-303)
        if score < score_threshold:
            continue

        results.append({
            "document_id": obj.properties.get("document_id", ""),
            "page_number": obj.properties.get("page_number", 0),
            "source_key": obj.properties.get("source_key", ""),
            "source_name": obj.properties.get("source_name", ""),
            "minio_key": obj.properties.get("minio_key", ""),
            "tenant_id": obj.properties.get("tenant_id", "default"),
            "total_pages": obj.properties.get("total_pages", 0),
            "page_width_px": obj.properties.get("page_width_px", 0),
            "page_height_px": obj.properties.get("page_height_px", 0),
            "score": score,
        })

    span.set_attribute("result_count", len(results))
    span.end(status="ok")
    return results
```

**Key design decisions:**
- Weaviate `near_vector` query with `target_vector="mean_vector"` targets the named vector directly (not the default vector), matching the collection schema from `ensure_visual_collection()`
- Score threshold applied client-side after distance-to-similarity conversion because Weaviate's `near_vector` `distance` parameter uses distance (not similarity), and the spec defines threshold in similarity terms
- Explicit `return_properties` list excludes `patch_vectors` (FR-311) rather than relying on a post-query filter, preventing the data from crossing the wire
