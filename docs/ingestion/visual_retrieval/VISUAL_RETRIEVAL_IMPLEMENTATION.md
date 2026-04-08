# Visual Page Retrieval Pipeline — Implementation Docs

> **For implement-code agents:** This document is your source of truth.
> Read ONLY your assigned task section. Your section contains your FR context,
> Phase 0 contracts inlined, implementation steps, and isolation contract verbatim.
> Do not read the full document, the spec, the design doc, or other task sections.

**Goal:** Add a visual retrieval track to the RAG pipeline that encodes text queries through ColQwen2, searches the visual page collection in Weaviate, generates presigned MinIO URLs for matched page images, and returns visual results alongside existing text results.
**Spec:** `docs/ingestion/visual_retrieval/VISUAL_RETRIEVAL_SPEC.md`
**Design doc:** `docs/ingestion/visual_retrieval/VISUAL_RETRIEVAL_DESIGN.md`
**Output path:** `docs/ingestion/visual_retrieval/VISUAL_RETRIEVAL_IMPLEMENTATION.md`
**Produced by:** write-implementation-docs
**Phase 0 status:** [ ] Awaiting human review

---

## Phase 0: Contract Definitions

This section defines the shared type surface for the entire implementation. Every task agent works against these definitions. All stubs use `raise NotImplementedError("Task N.M")` and contain no implementation logic.

### 0.1 Configuration Keys and Validation

Configuration keys and validation function for the visual retrieval pipeline. Added to `config/settings.py`.

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

### 0.2 VisualPageResult Schema

Dataclass for visual page retrieval results. Added to `src/retrieval/common/schemas.py`.

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

### 0.3 ColQwen2 Text Query Encoder

Function stub added to `src/ingest/support/colqwen.py`.

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

### 0.4 Weaviate Visual Search

Function stub added to `src/vector_db/weaviate/visual_store.py`.

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

### 0.5 Vector Backend `search_visual` Abstract Method

Abstract method added to `src/vector_db/backend.py`.

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

### 0.6 MinIO Page Image Presigned URL

Function stub added to `src/db/minio/store.py`.

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

### 0.7 Server API Visual Schema

Pydantic model added to `server/schemas.py`.

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

### 0.8 Error Taxonomy

| Error Type | Trigger Condition | Expected Message Format | Retryable | Raising Module |
|---|---|---|---|---|
| `ValueError` | Empty/whitespace query text passed to `embed_text_query` | `"Query text is empty or blank"` | No | `src/ingest/support/colqwen.py` |
| `ValueError` | Visual retrieval enabled with empty collection name, score out of range, or URL expiry out of range | `"RAG_VISUAL_RETRIEVAL_ENABLED=true but RAG_INGESTION_VISUAL_TARGET_COLLECTION is empty"` / `"RAG_VISUAL_RETRIEVAL_MIN_SCORE={value} out of range [0.0, 1.0]"` / `"RAG_VISUAL_RETRIEVAL_URL_EXPIRY_SECONDS={value} out of range [60, 86400]"` | No | `config/settings.py` |
| `ColQwen2LoadError` | Model or processor is None/invalid when `embed_text_query` is called | `"ColQwen2 model or processor is None — call load_colqwen_model() first"` | No | `src/ingest/support/colqwen.py` |
| `ColQwen2LoadError` | ColQwen2 model fails to load (missing packages, CUDA unavailable, model not found) | `"ColQwen2 model load failed for '{model_name}': {detail}"` | No | `src/ingest/support/colqwen.py` |
| `VisualEmbeddingError` | Forward pass raises unexpected error (CUDA OOM, tensor shape mismatch) | `"ColQwen2 text encoding failed: {detail}"` | Yes (transient CUDA errors) | `src/ingest/support/colqwen.py` |
| `weaviate.exceptions.WeaviateQueryError` | Weaviate query failure (connection lost, collection missing, schema mismatch) | Weaviate-native message | Yes (connection errors) | `src/vector_db/weaviate/visual_store.py` |
| `S3Error` | MinIO presigned URL generation failure (bucket missing, auth failure) | MinIO-native message | Yes (connection errors) | `src/db/minio/store.py` |

### 0.9 Integration Contracts

```
config/settings.py → RAGChain.__init__() reads RAG_VISUAL_RETRIEVAL_ENABLED
  Called when: RAGChain initializes
  On ValueError from validate_visual_retrieval_config(): RAGChain surfaces to caller unchanged (fatal config error)

RAGChain._ensure_visual_model() → colqwen.ensure_colqwen_ready()
  Called when: first visual query triggers lazy model load
  On ColQwen2LoadError: RAGChain catches in _run_visual_retrieval, sets visual_results=[]

RAGChain._ensure_visual_model() → colqwen.load_colqwen_model(model_name) → tuple[model, processor]
  Called when: first visual query, after ensure_colqwen_ready succeeds
  On ColQwen2LoadError: RAGChain catches in _run_visual_retrieval, sets visual_results=[]

RAGChain._run_visual_retrieval() → colqwen.embed_text_query(model, processor, text) → list[float]
  Called when: processing each visual retrieval request with the processed query
  On ValueError: RAGChain catches in run(), sets visual_results=[]
  On ColQwen2LoadError: RAGChain catches in run(), sets visual_results=[]
  On VisualEmbeddingError: RAGChain catches in run(), sets visual_results=[]

RAGChain._run_visual_retrieval() → vector_db.search_visual(client, query_vector, ...) → list[dict]
  Called when: after text encoding succeeds
  On WeaviateQueryError: RAGChain catches in run(), sets visual_results=[]

RAGChain._run_visual_retrieval() → minio_store.get_page_image_url(client, minio_key) → str
  Called when: for each visual search result, generating presigned URL
  On S3Error: per-page catch — that page omitted from visual_results, remaining pages continue

vector_db.__init__.search_visual() → WeaviateBackend.search_visual() → visual_store.visual_search()
  Called when: RAGChain invokes the public API
  On WeaviateQueryError: surfaces to caller unchanged

RAGChain.close() → colqwen.unload_colqwen_model(model)
  Called when: RAGChain lifecycle cleanup
  On any exception: logged as warning, cleanup continues

RAGResponse.visual_results → QueryResponse.visual_results (server route conversion)
  Called when: API route converts RAGResponse to Pydantic QueryResponse
  Mapping: VisualPageResult → VisualPageResultResponse (1:1 field mapping)
```

---

## Task 1.1: Visual Retrieval Configuration Keys

**Description:** Add all retrieval-side visual configuration keys to `config/settings.py`, including the master enable toggle, result limit, score threshold, URL expiry, stage budget, and a startup validation function that fails fast on contradictory or out-of-range settings. Reuses the existing `RAG_INGESTION_COLQWEN_MODEL` key for retrieval-time model selection (single source of truth).

**Spec requirements:** FR-101, FR-103, FR-105, FR-107, FR-109, FR-111, FR-617, NFR-907

**Dependencies:** none

**Source files:**
- MODIFY `config/settings.py`

---

**Phase 0 contracts (inlined -- implement these stubs):**

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

---

**Implementation steps:**

1. [FR-101] Add `RAG_VISUAL_RETRIEVAL_ENABLED` boolean config key to `config/settings.py` after the existing visual ingestion keys block (after `RAG_INGESTION_PAGE_IMAGE_MAX_DIMENSION`). Default `false`, parsed from environment variable with `("true", "1", "yes")` matching.
2. [FR-103] Add `RAG_VISUAL_RETRIEVAL_LIMIT` integer config key with clamping logic. Parse from env, log warning if out of [1, 50] range, clamp with `max(1, min(50, value))`.
3. [FR-105] Add `RAG_VISUAL_RETRIEVAL_MIN_SCORE` float config key. Default `0.3`, parsed from environment variable.
4. [FR-107] Add `RAG_VISUAL_RETRIEVAL_URL_EXPIRY_SECONDS` integer config key. Default `3600`, parsed from environment variable.
5. [FR-617] Add `RAG_STAGE_BUDGET_VISUAL_RETRIEVAL_MS` integer config key. Default `10000`, parsed from environment variable.
6. [FR-111, NFR-907] Implement `validate_visual_retrieval_config()` body: check that `RAG_INGESTION_VISUAL_TARGET_COLLECTION` (already defined in this file) is not empty when visual retrieval is enabled; check `RAG_VISUAL_RETRIEVAL_MIN_SCORE` is in [0.0, 1.0]; check `RAG_VISUAL_RETRIEVAL_URL_EXPIRY_SECONDS` is in [60, 86400]. Raise `ValueError` with a message identifying both the key name and the conflicting value for each violation.
7. [FR-109] Add a comment documenting that `RAG_INGESTION_COLQWEN_MODEL` is reused for retrieval-time model selection. No new key is created.
8. Update `@summary` exports list at the top of `config/settings.py` to include all new config keys and `validate_visual_retrieval_config`.

**Completion criteria:**
- [ ] All five config keys are defined and loaded from environment variables with documented defaults
- [ ] `validate_visual_retrieval_config()` implemented -- no `NotImplementedError` remaining
- [ ] `@summary` block updated with new exports

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 2.1: ColQwen2 Text Query Encoder

**Description:** Add an `embed_text_query()` function to the existing ColQwen2 adapter module that encodes a text query string into a 128-dimensional float vector using ColQwen2's text encoding pathway (`processor.process_queries()`), with mean pooling to match the image embedding format.

**Spec requirements:** FR-201, FR-203, FR-205, FR-207

**Dependencies:** Task 1.1

**Source files:**
- MODIFY `src/ingest/support/colqwen.py`

---

**Phase 0 contracts (inlined -- implement these stubs):**

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

---

**Implementation steps:**

1. [FR-205] Add input validation guard at the top of `embed_text_query`: if `text` is empty or whitespace-only (`not text or not text.strip()`), raise `ValueError` with a message containing "empty" or "blank". Do not invoke the model.
2. [FR-207] Add None/invalid model/processor guard: if `model is None` or `processor is None`, raise `ColQwen2LoadError` with a message indicating the model or processor is None and suggesting `load_colqwen_model()` must be called first.
3. [FR-203] Implement text encoding: call `processor.process_queries([text])` to tokenize the input, move batch inputs to the model device (`{k: v.to(model.device) for k, v in batch_inputs.items()}`), run forward pass under `torch.inference_mode()`, extract output tensor, compute mean across token-level vectors (`output_tensor[0].float().mean(dim=0)`), convert to Python list of float (`mean_tensor.cpu().tolist()`).
4. [FR-201] Verify the returned list has exactly 128 elements (matching the ColQwen2 embedding dimension).
5. [FR-207] Wrap the entire encoding block (steps 3-4) in a try/except that catches any non-`ColQwen2LoadError` exception and re-raises it as `VisualEmbeddingError` with the original exception chained as `__cause__`.
6. Update module `@summary` to include `embed_text_query` in exports.

**Completion criteria:**
- [ ] `embed_text_query` implemented -- no `NotImplementedError` remaining
- [ ] Integration contracts honored: returns `list[float]` of length 128, raises the three documented exception types
- [ ] `@summary` block updated with new export

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 2.2: Weaviate Visual Search Function

**Description:** Add a `visual_search()` function to the existing Weaviate visual store module that performs nearest-neighbor search on the `mean_vector` named vector of the `RAGVisualPages` collection, returning page objects ranked by cosine similarity with configurable limit, score threshold, and tenant filtering.

**Spec requirements:** FR-301, FR-303, FR-305, FR-307, FR-309, FR-311

**Dependencies:** Task 1.1

**Source files:**
- MODIFY `src/vector_db/weaviate/visual_store.py`

---

**Phase 0 contracts (inlined -- implement these stubs):**

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

---

**Implementation steps:**

1. [FR-309] Get the collection handle via `client.collections.get(collection)`. Construct a `near_vector` query targeting `target_vector="mean_vector"` with the provided `query_vector` and `limit`.
2. [FR-305] Build an optional tenant filter: if `tenant_id is not None`, create `Filter.by_property("tenant_id").equal(tenant_id)` from `weaviate.classes.query`. Pass as the `filters` parameter to the query.
3. [FR-311] Set `return_properties` to the explicit list: `["document_id", "page_number", "source_key", "source_name", "minio_key", "tenant_id", "total_pages", "page_width_px", "page_height_px"]`. This excludes `patch_vectors` from the wire. Set `return_metadata=MetadataQuery(distance=True)` to get cosine distance values.
4. [FR-303] Iterate over response objects. Convert cosine distance to cosine similarity (`score = 1.0 - distance`). Skip results where `score < score_threshold`.
5. [FR-301] Build result dicts with all specified fields from `obj.properties` plus the computed `score`. Return the list (already ordered by descending similarity from Weaviate).
6. [NFR-909] Add observability span via `get_tracer().start_span("vector_store.visual_search", {...})` at the start, with `result_count` attribute, and `span.end(status="ok")` at the end.
7. Update module `@summary` to include `visual_search` in exports.

**Completion criteria:**
- [ ] `visual_search` implemented -- no `NotImplementedError` remaining
- [ ] Integration contracts honored: returns `list[dict]` with the 10 specified keys, ordered by descending score
- [ ] `@summary` block updated with new export

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 2.3: MinIO Page Image Presigned URL

**Description:** Add a `get_page_image_url()` function to the existing MinIO store module that generates a presigned GET URL for an arbitrary MinIO object key (without appending any suffix), using configurable bucket and expiry defaults.

**Spec requirements:** FR-401, FR-403

**Dependencies:** Task 1.1

**Source files:**
- MODIFY `src/db/minio/store.py`

---

**Phase 0 contracts (inlined -- implement these stubs):**

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

---

**Implementation steps:**

1. [FR-403] Implement sentinel default resolution: if `bucket` is empty string, import and use `MINIO_BUCKET` from `config.settings`. If `expires_in_seconds` is 0, import and use `RAG_VISUAL_RETRIEVAL_URL_EXPIRY_SECONDS` from `config.settings`.
2. [FR-401] Call `client.presigned_get_object(bucket, minio_key, expires=timedelta(seconds=expires_in_seconds))` using the resolved bucket and expiry. Pass `minio_key` as-is -- do NOT append any suffix (unlike `get_document_url()` which appends `_CONTENT_SUFFIX`).
3. [FR-401] Add observability span via `get_tracer().start_span("document_store.get_page_image_url", {"minio_key": minio_key, "bucket": bucket})` at the start, and `span.end(status="ok")` at the end.
4. Update module `@summary` to include `get_page_image_url` in exports.

**Completion criteria:**
- [ ] `get_page_image_url` implemented -- no `NotImplementedError` remaining
- [ ] Integration contracts honored: returns `str` (presigned URL), uses raw key without suffix
- [ ] `@summary` block updated with new export

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 3.1: Vector Backend Abstraction Extension

**Description:** Extend the `VectorBackend` abstract base class, `WeaviateBackend` implementation, and `vector_db/__init__.py` public API with a `search_visual()` method that delegates to the visual store's `visual_search()` function, maintaining the established backend abstraction pattern.

**Spec requirements:** FR-313

**Dependencies:** Task 2.2

**Source files:**
- MODIFY `src/vector_db/backend.py`
- MODIFY `src/vector_db/weaviate/backend.py`
- MODIFY `src/vector_db/__init__.py`

---

**Phase 0 contracts (inlined -- implement these stubs):**

Abstract method to add to `VectorBackend` in `src/vector_db/backend.py`:

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

---

**Implementation steps:**

1. [FR-313] Add the abstract `search_visual()` method to `VectorBackend` in `src/vector_db/backend.py`, placed after the existing visual collection operations section (after `delete_visual_by_source_key`). Use the exact signature from the Phase 0 contract above.
2. [FR-313] Implement `search_visual()` in `WeaviateBackend` in `src/vector_db/weaviate/backend.py`. Import `visual_search` from `src.vector_db.weaviate.visual_store` (following the existing alias pattern: `from src.vector_db.weaviate.visual_store import visual_search as _vs_visual_search`). Delegate: `return _vs_visual_search(client, query_vector, limit, score_threshold, tenant_id, collection or "RAGVisualPages")`.
3. [FR-313] Add a public `search_visual()` function to `src/vector_db/__init__.py` that routes through `_get_vector_backend().search_visual(...)`, following the existing pattern used by `ensure_visual_collection`, `add_visual_documents`, etc. Add `"search_visual"` to the `__all__` list.
4. Update `@summary` blocks in all three files to include the new `search_visual` export.

**Completion criteria:**
- [ ] Abstract method exists in `VectorBackend`
- [ ] `WeaviateBackend` delegates to `visual_search()` from the visual store module
- [ ] Public `search_visual()` exported from `src/vector_db/__init__.py`
- [ ] `@summary` blocks updated in all three files

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 3.2: Retrieval Schema Extension

**Description:** Add a `VisualPageResult` dataclass to the retrieval schemas module and extend `RAGResponse` with an optional `visual_results` field, maintaining backward compatibility with existing text-only responses.

**Spec requirements:** FR-501, FR-503

**Dependencies:** none

**Source files:**
- MODIFY `src/retrieval/common/schemas.py`

---

**Phase 0 contracts (inlined -- implement these stubs):**

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

---

**Implementation steps:**

1. [FR-501] Add the `VisualPageResult` dataclass to `src/retrieval/common/schemas.py`, placed after the existing `RankedResult` dataclass. Include all nine fields with the exact types shown in the Phase 0 contract.
2. [FR-503] Add `visual_results: Optional[List[VisualPageResult]] = None` field to the existing `RAGResponse` dataclass. Place it after the existing `re_retrieval_params` field. The default `None` maintains backward compatibility -- existing code constructing `RAGResponse` without `visual_results` will work unchanged.
3. Update module `@summary` to include `VisualPageResult` in exports.

**Completion criteria:**
- [ ] `VisualPageResult` dataclass importable from `src.retrieval.common.schemas`
- [ ] `RAGResponse` has `visual_results` field with `None` default
- [ ] `@summary` block updated with new export

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 4.1: RAGChain Visual Track Integration

**Description:** Integrate the visual retrieval track into `RAGChain` as an additive post-text-reranking stage. Implement lazy ColQwen2 model loading on first visual query, sequential execution after text track completion, presigned URL generation per result, graceful degradation on any visual track failure, stage timing recording, observability spans, and model cleanup on `close()`. When visual retrieval is disabled, the system incurs zero additional overhead.

**Spec requirements:** FR-601, FR-603, FR-605, FR-607, FR-609, FR-611, FR-613, FR-615, FR-617, NFR-901, NFR-903, NFR-905, NFR-909, NFR-911

**Dependencies:** Task 2.1, Task 2.3, Task 3.1, Task 3.2

**Source files:**
- MODIFY `src/retrieval/pipeline/rag_chain.py`

---

**Phase 0 contracts (inlined -- implement against these types):**

`VisualPageResult` dataclass (from `src/retrieval/common/schemas.py`):

```python
@dataclass
class VisualPageResult:
    """A single visual page retrieval result with its similarity score."""
    document_id: str
    page_number: int
    source_key: str
    source_name: str
    score: float
    page_image_url: str
    total_pages: int
    page_width_px: int
    page_height_px: int
```

`embed_text_query` (from `src/ingest/support/colqwen.py`):
- Signature: `embed_text_query(model: Any, processor: Any, text: str) -> list[float]`
- Raises: `ValueError` (empty text), `ColQwen2LoadError` (None model/processor), `VisualEmbeddingError` (inference failure)

`search_visual` (from `src/vector_db/__init__.py`):
- Signature: `search_visual(client, query_vector, limit, score_threshold, tenant_id=None, collection=None) -> list[dict]`
- Each dict contains: `document_id`, `page_number`, `source_key`, `source_name`, `minio_key`, `tenant_id`, `total_pages`, `page_width_px`, `page_height_px`, `score`

`get_page_image_url` (from `src/db/minio/store.py`):
- Signature: `get_page_image_url(client: Minio, minio_key: str, bucket: str = "", expires_in_seconds: int = 0) -> str`

Config keys (from `config/settings.py`):
- `RAG_VISUAL_RETRIEVAL_ENABLED: bool` (default `false`)
- `RAG_VISUAL_RETRIEVAL_LIMIT: int` (default `5`)
- `RAG_VISUAL_RETRIEVAL_MIN_SCORE: float` (default `0.3`)
- `RAG_STAGE_BUDGET_VISUAL_RETRIEVAL_MS: int` (default `10000`)
- `RAG_INGESTION_COLQWEN_MODEL: str` (existing key, reused for retrieval)
- `validate_visual_retrieval_config() -> None` (raises `ValueError` on bad config)

Lifecycle functions (from `src/ingest/support/colqwen.py`):
- `ensure_colqwen_ready() -> None` (raises `ColQwen2LoadError`)
- `load_colqwen_model(model_name: str) -> tuple[Any, Any]` (raises `ColQwen2LoadError`)
- `unload_colqwen_model(model: Any) -> None`

---

**Implementation steps:**

1. [FR-603, FR-615] In `RAGChain.__init__()`, after existing initialization code, add lazy-loading attributes: `self._visual_model = None`, `self._visual_processor = None`, `self._visual_retrieval_enabled = RAG_VISUAL_RETRIEVAL_ENABLED`. Import `RAG_VISUAL_RETRIEVAL_ENABLED` and `validate_visual_retrieval_config` from `config.settings`. If `self._visual_retrieval_enabled`, call `validate_visual_retrieval_config()` (FR-111). Add `"visual_retrieval"` to the `stage_budgets` dict in `run()` using `RAG_STAGE_BUDGET_VISUAL_RETRIEVAL_MS`.
2. [FR-603] Implement `_ensure_visual_model(self)` private method: if `self._visual_model is not None`, return immediately (warm path). Otherwise, import `ensure_colqwen_ready`, `load_colqwen_model` from `src.ingest.support.colqwen` and `RAG_INGESTION_COLQWEN_MODEL` from `config.settings` (lazy imports for zero-cost when disabled). Call `ensure_colqwen_ready()`, then `load_colqwen_model(RAG_INGESTION_COLQWEN_MODEL)` and cache as `self._visual_model, self._visual_processor`. Add `visual_retrieval.model_load` observability span wrapping the load.
3. [FR-601, FR-605, FR-607, FR-609, NFR-909] Implement `_run_visual_retrieval(self, processed_query: str, tenant_id: Optional[str]) -> list[VisualPageResult]` private method: (a) call `self._ensure_visual_model()`, (b) import and call `embed_text_query` with the processed query under a `visual_retrieval.text_encode` span (FR-605 -- uses processed query, not raw), (c) import and call `search_visual` from `src.vector_db` with the query vector, limit, score threshold, and tenant_id under a `visual_retrieval.search` span (FR-609), (d) for each result, import and call `get_page_image_url` from `src.db.minio.store` with `create_client()` and the result's `minio_key` under a `visual_retrieval.presigned_urls` span; wrap each per-page URL generation in a try/except that logs warning and skips that page on failure (NFR-905 per-page isolation), (e) assemble and return `list[VisualPageResult]`.
4. [FR-601, FR-615, NFR-905, FR-611] In `RAGChain.run()`, after the reranking stage and before generation, add the visual retrieval block: set `visual_results = None` (disabled semantics). If `self._visual_retrieval_enabled`, record start time, wrap `self._run_visual_retrieval(processed_query, tenant_id)` in a try/except that catches `Exception`, logs warning, and sets `visual_results = []` (enabled-but-failed semantics -- not `None`). Record `visual_retrieval` stage timing via `tp.record(...)`.
5. [FR-503] Pass `visual_results=visual_results` to the `RAGResponse` constructor in all return paths within `run()`. For early-return paths (ask_user, budget_exhausted), set `visual_results=None`.
6. [FR-613] Extend `RAGChain.close()`: after existing Weaviate cleanup, if `self._visual_model is not None`, import `unload_colqwen_model` from `src.ingest.support.colqwen`, call `unload_colqwen_model(self._visual_model)`, set `self._visual_model = None` and `self._visual_processor = None`. Log at INFO level.
7. [NFR-911] Add INFO-level logging: number of visual results returned, cold start vs warm model, visual stage duration. Add DEBUG-level logging: query vector dimensions, score range of results.

**Completion criteria:**
- [ ] Lazy model loading: ColQwen2 not loaded at `__init__()` time, loaded on first visual query, cached for subsequent queries
- [ ] Sequential execution: visual track runs after reranking, before generation
- [ ] Graceful degradation: any visual track failure returns `visual_results=[]`, text results intact
- [ ] Stage timing recorded with name `"visual_retrieval"`
- [ ] Observability spans: `visual_retrieval.model_load`, `visual_retrieval.text_encode`, `visual_retrieval.search`, `visual_retrieval.presigned_urls`
- [ ] `close()` unloads ColQwen2 model if loaded
- [ ] Zero overhead when `RAG_VISUAL_RETRIEVAL_ENABLED=false`

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Task 5.1: Server API Schema Extension

**Description:** Add a `VisualPageResultResponse` Pydantic model to the server schemas module and extend `QueryResponse` with an optional `visual_results` field, maintaining backward compatibility for existing API clients.

**Spec requirements:** FR-701, FR-703

**Dependencies:** Task 3.2

**Source files:**
- MODIFY `server/schemas.py`

---

**Phase 0 contracts (inlined -- implement these stubs):**

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

---

**Implementation steps:**

1. [FR-701] Add the `VisualPageResultResponse` Pydantic model to `server/schemas.py`, placed after the existing `ChunkResult` model. Include all nine fields with the exact types shown in the Phase 0 contract.
2. [FR-703] Add `visual_results: Optional[list[VisualPageResultResponse]] = None` field to the existing `QueryResponse` model. Place it after the existing `budget_exhausted_stage` field. The default `None` maintains backward compatibility -- existing API responses serialize correctly.
3. [FR-703] Add `"visual_retrieval"` to the `allowed` set in the `_validate_stage_budget_overrides` model validator of `QueryRequest`, so clients can override the visual retrieval stage budget.
4. Update module `@summary` to include `VisualPageResultResponse` in exports.

**Completion criteria:**
- [ ] `VisualPageResultResponse` Pydantic model present in `server/schemas.py`
- [ ] `QueryResponse` has `visual_results` field with `None` default
- [ ] `"visual_retrieval"` is an allowed stage budget override key
- [ ] `@summary` block updated with new export

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries,
> the full spec, the full design doc, or the complete implementation docs.

---

## Module Boundary Map

| Task | Source File | Action |
|------|-----------|--------|
| Task 1.1 | `config/settings.py` | MODIFY |
| Task 2.1 | `src/ingest/support/colqwen.py` | MODIFY |
| Task 2.2 | `src/vector_db/weaviate/visual_store.py` | MODIFY |
| Task 2.3 | `src/db/minio/store.py` | MODIFY |
| Task 3.1 | `src/vector_db/backend.py` | MODIFY |
| Task 3.1 | `src/vector_db/weaviate/backend.py` | MODIFY |
| Task 3.1 | `src/vector_db/__init__.py` | MODIFY |
| Task 3.2 | `src/retrieval/common/schemas.py` | MODIFY |
| Task 4.1 | `src/retrieval/pipeline/rag_chain.py` | MODIFY |
| Task 5.1 | `server/schemas.py` | MODIFY |

**Note:** No new files are created. All changes modify existing modules, following the additive integration principle.

---

## Dependency Graph

```
                    ┌─────────────────────────────────────┐
                    │ Task 1.1: Config Keys               │
                    │ [Phase 1 — no dependencies]         │
                    └──────┬──────────┬──────────┬────────┘
                           │          │          │
                    ┌──────▼──┐  ┌────▼────┐  ┌──▼──────┐
                    │ Task 2.1│  │ Task 2.2│  │ Task 2.3│
                    │ ColQwen │  │ Weaviate│  │ MinIO   │
                    │ Text    │  │ Visual  │  │ Presign │
                    │ Encoder │  │ Search  │  │ URL     │
                    └────┬────┘  └────┬────┘  └────┬────┘
                         │            │            │
                         │       ┌────▼────┐       │
                         │       │ Task 3.1│       │
                         │       │ Backend │       │
                         │       │ Abstract│       │
                         │       └────┬────┘       │
                         │            │            │
    ┌──────────┐         │            │            │
    │ Task 3.2 │         │            │            │
    │ Retrieval│─────────┼────────────┼────────────┤
    │ Schema   │         │            │            │
    └──┬───┬───┘         │            │            │
       │   │        ┌────▼────────────▼────────────▼──┐
       │   │        │                                  │
       │   ├───────>│ Task 4.1: RAGChain Visual Track  │
       │   │        │          Integration [CRITICAL]  │
       │   │        │                                  │
       │   │        └──────────────────────────────────┘
       │   │
    ┌──▼───▼──┐
    │ Task 5.1│
    │ Server  │
    │ API     │
    │ Schema  │
    └─────────┘

Parallel wave 1: Task 1.1, Task 3.2
Parallel wave 2: Task 2.1, Task 2.2, Task 2.3, Task 5.1
Parallel wave 3: Task 3.1
Parallel wave 4: Task 4.1

Critical path: 1.1 → 2.2 → 3.1 → 4.1
```

---

## Task-to-FR Traceability Table

| REQ ID | Priority | Task(s) | Source File(s) |
|--------|----------|---------|----------------|
| FR-101 | MUST | Task 1.1 | `config/settings.py` |
| FR-103 | MUST | Task 1.1 | `config/settings.py` |
| FR-105 | MUST | Task 1.1 | `config/settings.py` |
| FR-107 | SHOULD | Task 1.1 | `config/settings.py` |
| FR-109 | MUST | Task 1.1 | `config/settings.py` |
| FR-111 | MUST | Task 1.1 | `config/settings.py` |
| FR-201 | MUST | Task 2.1 | `src/ingest/support/colqwen.py` |
| FR-203 | MUST | Task 2.1 | `src/ingest/support/colqwen.py` |
| FR-205 | MUST | Task 2.1 | `src/ingest/support/colqwen.py` |
| FR-207 | MUST | Task 2.1 | `src/ingest/support/colqwen.py` |
| FR-301 | MUST | Task 2.2 | `src/vector_db/weaviate/visual_store.py` |
| FR-303 | MUST | Task 2.2 | `src/vector_db/weaviate/visual_store.py` |
| FR-305 | MUST | Task 2.2 | `src/vector_db/weaviate/visual_store.py` |
| FR-307 | MUST | Task 2.2 | `src/vector_db/weaviate/visual_store.py` |
| FR-309 | MUST | Task 2.2 | `src/vector_db/weaviate/visual_store.py` |
| FR-311 | MUST | Task 2.2 | `src/vector_db/weaviate/visual_store.py` |
| FR-313 | MUST | Task 3.1 | `src/vector_db/backend.py`, `src/vector_db/weaviate/backend.py`, `src/vector_db/__init__.py` |
| FR-401 | MUST | Task 2.3 | `src/db/minio/store.py` |
| FR-403 | MUST | Task 2.3 | `src/db/minio/store.py` |
| FR-501 | MUST | Task 3.2 | `src/retrieval/common/schemas.py` |
| FR-503 | MUST | Task 3.2 | `src/retrieval/common/schemas.py` |
| FR-601 | MUST | Task 4.1 | `src/retrieval/pipeline/rag_chain.py` |
| FR-603 | MUST | Task 4.1 | `src/retrieval/pipeline/rag_chain.py` |
| FR-605 | MUST | Task 4.1 | `src/retrieval/pipeline/rag_chain.py` |
| FR-607 | MUST | Task 4.1 | `src/retrieval/pipeline/rag_chain.py` |
| FR-609 | MUST | Task 4.1 | `src/retrieval/pipeline/rag_chain.py` |
| FR-611 | MUST | Task 4.1 | `src/retrieval/pipeline/rag_chain.py` |
| FR-613 | MUST | Task 4.1 | `src/retrieval/pipeline/rag_chain.py` |
| FR-615 | MUST | Task 4.1 | `src/retrieval/pipeline/rag_chain.py` |
| FR-617 | SHOULD | Task 1.1, Task 4.1 | `config/settings.py`, `src/retrieval/pipeline/rag_chain.py` |
| FR-701 | MUST | Task 5.1 | `server/schemas.py` |
| FR-703 | MUST | Task 5.1 | `server/schemas.py` |
| NFR-901 | SHOULD | Task 4.1 | `src/retrieval/pipeline/rag_chain.py` |
| NFR-903 | MUST | Task 4.1 | `src/retrieval/pipeline/rag_chain.py` |
| NFR-905 | MUST | Task 4.1 | `src/retrieval/pipeline/rag_chain.py` |
| NFR-907 | MUST | Task 1.1 | `config/settings.py` |
| NFR-909 | MUST | Task 4.1 | `src/retrieval/pipeline/rag_chain.py` |
| NFR-911 | SHOULD | Task 4.1 | `src/retrieval/pipeline/rag_chain.py` |

**Coverage:** 37/37 requirements covered. 0 orphan tasks (every task traces to at least one FR/NFR).
