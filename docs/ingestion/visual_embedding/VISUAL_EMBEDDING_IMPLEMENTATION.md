# Visual Embedding Pipeline -- Implementation Docs

**Status:** Implementation-ready
**Date:** 2026-04-01
**Subsystem:** Ingestion / Embedding / Visual Track
**Output of:** write-implementation-docs

---

## Phase 0: Contract Definitions

All types, stubs, exception classes, and integration contracts are defined here. Every stub uses `raise NotImplementedError("Task N.N")` -- never `pass`. Implement-code agents receive the relevant Phase 0 contracts inlined in their task section; they do NOT reference this section directly.

---

### 0.1 Exception Types

```python
class VisualEmbeddingError(Exception):
    """Base exception for visual embedding pipeline errors.
    Non-fatal: per-page failures that should be caught and logged,
    allowing the pipeline to continue with remaining pages. FR-307
    """
    pass


class ColQwen2LoadError(VisualEmbeddingError):
    """Fatal: ColQwen2 model failed to load.
    When raised: visual_stored_count=0, error added to state['errors'],
    no retry attempted. FR-802
    """
    pass
```

### 0.2 Data Classes

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

### 0.3 Configuration Constants (config/settings.py)

```python
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
```

### 0.4 IngestionConfig Fields (src/ingest/common/types.py additions)

```python
# New fields to append to IngestionConfig dataclass:
    # -- Visual embedding pipeline (FR-101 through FR-109) --
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
```

### 0.5 Config Validation Stub (src/ingest/impl.py)

```python
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

### 0.6 EmbeddingPipelineState Extensions (src/ingest/embedding/state.py)

```python
from __future__ import annotations
from typing import Any, Dict, List, Optional, TypedDict
from src.ingest.common.schemas import ProcessedChunk
from src.ingest.common.types import Runtime


class EmbeddingPipelineState(TypedDict, total=False):
    """Shared state flowing through the Embedding Pipeline DAG.
    Existing fields are preserved exactly as-is (NFR-909).
    """
    # -- Existing fields (unchanged) --
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

    # -- Visual embedding extensions (FR-602) --
    visual_stored_count: int  # FR-602: number of visual page objects stored; default 0
    page_images: Optional[List[Any]]  # FR-602: PIL.Image objects; cleared after node (FR-606)
```

### 0.7 IngestFileResult Extension (src/ingest/common/types.py)

```python
from dataclasses import dataclass, field


@dataclass
class IngestFileResult:
    """Result of a single-file ingestion run. Existing fields preserved (NFR-909)."""
    # -- Existing fields (unchanged) --
    errors: list[str]
    stored_count: int
    metadata_summary: str
    metadata_keywords: list[str]
    processing_log: list[str]
    source_hash: str
    clean_hash: str
    # -- Visual embedding extension (FR-605) --
    visual_stored_count: int = 0  # FR-605: number of visual page objects stored
```

### 0.8 ColQwen2 Adapter Function Stubs (src/ingest/support/colqwen.py)

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


def load_colqwen_model(model_name: str) -> tuple[Any, Any]:
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

### 0.9 Weaviate Visual Store Function Stubs (src/vector_db/weaviate/visual_store.py)

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

### 0.10 VectorBackend Abstract Methods (src/vector_db/backend.py)

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, List, Optional


class VectorBackend(ABC):
    """Abstract contract for a vector store backend.
    Visual collection methods are added below existing methods (NFR-909).
    """
    # ... existing abstract methods unchanged ...

    # -- Visual collection operations --

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
        Returns: Number of objects inserted.
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
        Returns: Number of objects deleted.
        """
        raise NotImplementedError("Task 3.1")
```

### 0.11 visual_embedding_node Stub (src/ingest/embedding/nodes/visual_embedding.py)

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

---

### Error Taxonomy Table

| Exception | Severity | When Raised | Handler |
|-----------|----------|-------------|---------|
| `ColQwen2LoadError` | FATAL | Model files missing, CUDA error, packages not installed | `visual_embedding_node`: log error, add to `state["errors"]`, `visual_stored_count=0`, return |
| `VisualEmbeddingError` | NON-FATAL | Per-page inference failure | `visual_embedding_node`: log warning, skip page, continue |
| `Exception` (MinIO upload) | NON-FATAL | Network error, disk full, auth failure | `visual_embedding_node`: log warning, skip page+embedding, continue |
| `Exception` (Weaviate batch) | NON-FATAL | Connection error, schema mismatch | `visual_embedding_node`: log error, add to `state["errors"]`, `visual_stored_count=partial` |
| `Exception` (page extraction) | NON-FATAL | Format error, corrupted page | `visual_embedding_node`: log warning, return with `visual_stored_count=0` |

---

### Integration Contracts

```
Phase 1 -> Phase 2 (DoclingParseResult -> EmbeddingPipelineState):
  parse_with_docling(generate_page_images=True)
    -> DoclingParseResult(page_images=[PIL.Image...], page_count=N)
    -> EmbeddingPipelineState["docling_document"] (existing path)
  On failure: DoclingParseResult has page_images=[] (empty list), no error raised

EmbeddingPipelineState -> visual_embedding_node:
  Input: state["docling_document"] (DoclingDocument or None)
         state["document_id"] (str, set by document_storage_node)
         state["source_key"] (str)
         state["runtime"].config.enable_visual_embedding (bool)
  Output: state update dict with visual_stored_count, page_images=None, processing_log
  Error propagation: exceptions NEVER raised to DAG; all caught internally

visual_embedding_node -> MinIO:
  store_page_images(client, document_id, pages, quality, bucket)
    -> objects at pages/{document_id}/{page_num:04d}.jpg
  On failure: per-page warning, page skipped

visual_embedding_node -> Weaviate:
  ensure_visual_collection(client, collection) -> None (idempotent)
  add_visual_documents(client, docs, collection) -> int (inserted count)
  delete_visual_by_source_key(client, source_key, collection) -> int (deleted count)
  On failure: error added to state["errors"], visual_stored_count=0 or partial

ColQwen2 adapter lifecycle:
  ensure_colqwen_ready() -> None
    | (ColQwen2LoadError if packages missing)
  load_colqwen_model(model_name) -> (model, processor)
    | (ColQwen2LoadError if load fails -- FATAL)
  embed_page_images(model, processor, images, batch_size) -> List[ColQwen2PageEmbedding]
    | (VisualEmbeddingError per page -- non-fatal, page skipped)
  unload_colqwen_model(model) -> None
```

Directional dependency arrows:

```
config/settings.py -----> src/ingest/common/types.py (IngestionConfig reads settings)
src/ingest/support/docling.py -----> EmbeddingPipelineState (page_images populated)
EmbeddingPipelineState -----> visual_embedding_node (state input)
visual_embedding_node -----> src/ingest/support/colqwen.py (model load, embed, unload)
visual_embedding_node -----> src/db/minio/store.py (page image storage)
visual_embedding_node -----> src/vector_db/backend.py (ensure_visual_collection, add, delete)
src/vector_db/backend.py -----> src/vector_db/weaviate/backend.py (ABC implementation)
src/vector_db/weaviate/backend.py -----> src/vector_db/weaviate/visual_store.py (delegation)
src/ingest/embedding/workflow.py -----> visual_embedding_node (DAG wiring)
```

---

## Task 1.1: Config & Settings Extensions

**Description:** Add all visual embedding configuration fields to IngestionConfig in `src/ingest/common/types.py`, backed by env vars in `config/settings.py`. Extend `verify_core_design()` with validation via `_check_visual_embedding_config()`. Add `[visual]` optional extras in `pyproject.toml`.

**Spec requirements:** FR-101, FR-102, FR-103, FR-104, FR-105, FR-106, FR-107, FR-108, FR-109, NFR-905, NFR-906

**Dependencies:** none

**Source files:**
- MODIFY `config/settings.py`
- MODIFY `src/ingest/common/types.py`
- MODIFY `src/ingest/impl.py`
- MODIFY `pyproject.toml`

---

**Phase 0 contracts (inlined -- implement these stubs):**

```python
# -- config/settings.py additions --

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


# -- src/ingest/common/types.py additions to IngestionConfig --

# New fields to append to IngestionConfig dataclass:
    # -- Visual embedding pipeline (FR-101 through FR-109) --
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


# -- src/ingest/impl.py validation addition --

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

---

**Implementation steps:**

1. [FR-109] In `config/settings.py`, add all six `RAG_INGESTION_*` visual embedding constants at module level, below the existing ingestion settings section. Each reads from `os.environ.get()` with the specified default value. Boolean parsing uses `.lower() in ("true", "1", "yes")`. Integer values use `int()` wrapping.

2. [FR-101, FR-102, FR-103, FR-104, FR-105, FR-106] In `src/ingest/common/types.py`, import the six new settings constants from `config.settings`. Append the six new fields to the `IngestionConfig` dataclass, each with its default from the corresponding settings constant. Include field docstrings with FR references.

3. [FR-107] In `src/ingest/common/types.py`, add the `generate_page_images` property to `IngestionConfig` that returns `self.enable_visual_embedding`.

4. [FR-108, NFR-905] In `src/ingest/impl.py`, implement `_check_visual_embedding_config()`. It must:
   - Return early with `([], [])` if `config.enable_visual_embedding` is `False`.
   - Check that `config.enable_docling_parser` is `True` when visual embedding is enabled; if not, append a fatal error string.
   - Validate `config.colqwen_batch_size` is in range 1-32; if not, append a fatal error string.
   - Validate `config.page_image_quality` is in range 1-100; if not, append a fatal error string.
   - Validate `config.page_image_max_dimension` is in range 256-4096; if not, append a fatal error string.
   - Return `(errors, warnings)`.

5. [FR-108] In `src/ingest/impl.py`, locate the existing `verify_core_design()` function (or the function that aggregates config validation checks). Add a call to `_check_visual_embedding_config(config)` and merge its returned errors and warnings into the aggregate lists.

6. [NFR-906] In `pyproject.toml`, add a `[visual]` optional extras group under `[project.optional-dependencies]` containing `colpali-engine>=0.3.0` and `bitsandbytes>=0.43.0`. Add `rag[visual]` to the `all` extras group if one exists.

**Completion criteria:**
- [ ] All stubs implemented -- no `NotImplementedError` remaining
- [ ] Integration contracts honored (settings constants flow into IngestionConfig defaults)
- [ ] `@summary` block at top of each new file
- [ ] Module-level docstring present
- [ ] Config validation returns fatal errors for out-of-range values
- [ ] `generate_page_images` property correctly derives from `enable_visual_embedding`

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.

---

## Task 1.2: Docling Page Image Extension

**Description:** Extend `DoclingParseResult` with `page_images` and `page_count` fields. Add `generate_page_images` parameter to `parse_with_docling()`. When enabled, extract page images from `DoclingDocument`, record original dimensions, convert to RGB.

**Spec requirements:** FR-107, FR-201, FR-204, FR-205

**Dependencies:** none

**Source files:**
- MODIFY `src/ingest/support/docling.py`

---

**Phase 0 contracts (inlined -- implement these stubs):**

No function stubs for this task. Structural field additions to `DoclingParseResult` dataclass:

```python
# -- src/ingest/support/docling.py additions to DoclingParseResult --

# Add to DoclingParseResult dataclass:
    page_images: list[Any] = field(default_factory=list)
    """List of PIL.Image objects, one per extracted page. FR-201, FR-204"""
    page_count: int = 0
    """Total number of pages in the source document. FR-205"""
```

Integration contract for this task:

```
parse_with_docling(generate_page_images=True)
  -> DoclingParseResult(page_images=[PIL.Image...], page_count=N)
On failure: page_images=[] (empty list), no error raised
```

---

**Implementation steps:**

1. [FR-201] In `src/ingest/support/docling.py`, add `from typing import Any` and `from dataclasses import field` imports if not already present.

2. [FR-201, FR-204, FR-205] Add `page_images: list[Any] = field(default_factory=list)` and `page_count: int = 0` fields to the `DoclingParseResult` dataclass.

3. [FR-107] Add a `generate_page_images: bool = False` parameter to the `parse_with_docling()` function signature.

4. [FR-201] Inside `parse_with_docling()`, after the existing DoclingDocument parsing logic, add a conditional block: if `generate_page_images` is `True` and the docling document has page information, iterate over pages extracting images.

5. [FR-204] For each extracted page image, convert to RGB mode using `image.convert("RGB")` to normalize the color space. Record the original width and height before any resizing (these dimensions will be used downstream by `visual_embedding_node`).

6. [FR-205] Set `page_count` on the result to the total number of pages detected in the document (regardless of how many images were successfully extracted).

7. [FR-201] Wrap the page extraction loop in a try/except that catches any exception, logs a warning, and leaves `page_images` as an empty list. This ensures the text-track pipeline is never blocked by image extraction failures.

**Completion criteria:**
- [ ] All stubs implemented -- no `NotImplementedError` remaining
- [ ] Integration contracts honored (`page_images` populated when enabled, empty list on failure)
- [ ] `@summary` block updated at top of modified file
- [ ] Module-level docstring present
- [ ] `page_count` reflects total pages even when image extraction partially fails

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.

---

## Task 2.1: ColQwen2 Model Adapter

**Description:** Create `src/ingest/support/colqwen.py` implementing ColQwen2 model lifecycle (load with 4-bit quant, batch inference producing 128-dim patch vectors, mean pooling, GPU memory release). Follows `docling.py` structural pattern.

**Spec requirements:** FR-301, FR-302, FR-303, FR-304, FR-305, FR-306, FR-307, NFR-901, NFR-902, NFR-906, NFR-908, NFR-910

**Dependencies:** none

**Source files:**
- CREATE `src/ingest/support/colqwen.py`

---

**Phase 0 contracts (inlined -- implement these stubs):**

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


class VisualEmbeddingError(Exception):
    """Base exception for visual embedding pipeline errors.
    Non-fatal: per-page failures that should be caught and logged,
    allowing the pipeline to continue with remaining pages. FR-307
    """
    pass


class ColQwen2LoadError(VisualEmbeddingError):
    """Fatal: ColQwen2 model failed to load.
    When raised: visual_stored_count=0, error added to state['errors'],
    no retry attempted. FR-802
    """
    pass


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


def load_colqwen_model(model_name: str) -> tuple[Any, Any]:
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

---

**Implementation steps:**

1. [FR-301] Create `src/ingest/support/colqwen.py` with an `@summary` block and module-level docstring describing the ColQwen2 model adapter.

2. [FR-301] Define the `ColQwen2PageEmbedding` dataclass, `VisualEmbeddingError` exception, and `ColQwen2LoadError` exception exactly as specified in the Phase 0 contracts above.

3. [NFR-906] Implement `ensure_colqwen_ready()`: attempt to import `colpali_engine` and `bitsandbytes`. If either import fails, raise `ColQwen2LoadError` with a message including the install command: `pip install "rag[visual]"` or `pip install colpali-engine bitsandbytes`.

4. [FR-301, NFR-901, NFR-902] Implement `load_colqwen_model(model_name)`:
   - Import `torch` and `BitsAndBytesConfig` from `transformers`.
   - Import `ColQwen2` and `ColQwen2Processor` from `colpali_engine` (guard with try/except, raise `ColQwen2LoadError` on failure).
   - Create a `BitsAndBytesConfig` with `load_in_4bit=True`, `bnb_4bit_compute_dtype=torch.float16`.
   - Load the model with `ColQwen2.from_pretrained(model_name, quantization_config=bnb_config)`.
   - Load the processor with `ColQwen2Processor.from_pretrained(model_name)`.
   - Set model to eval mode.
   - Wrap the entire loading sequence in try/except, converting any exception to `ColQwen2LoadError`.
   - Return `(model, processor)`.

5. [FR-302, FR-303, FR-304, FR-306, FR-307] Implement `embed_page_images()`:
   - Default `page_numbers` to `list(range(1, len(images) + 1))` if `None`.
   - Process images in batches of `batch_size`.
   - For each batch: use `processor.process_images(batch_images)` to get model inputs, move inputs to model device, run `model(**inputs)` to get embeddings.
   - Extract per-image patch vectors from the output. Each image produces `n_patches x 128` float32 vectors.
   - Compute the mean-pooled vector as the arithmetic mean across patches (dim=0).
   - Convert tensors to Python lists for JSON serialization.
   - Create a `ColQwen2PageEmbedding` for each successfully processed page.
   - Wrap per-page processing in try/except for `VisualEmbeddingError` and generic `Exception`; log a warning and skip the page on failure (FR-307).
   - If `len(images) > 10`, log progress at 10% intervals (FR-306).

6. [NFR-908, NFR-910] Use `torch.inference_mode()` context manager (or `torch.no_grad()`) during inference to minimize memory usage and prevent gradient computation.

7. [FR-305] Implement `unload_colqwen_model(model)`:
   - Delete the model reference (`del model`).
   - Call `torch.cuda.empty_cache()`.
   - Call `gc.collect()` (import `gc`).
   - Log that GPU memory has been released.

**Completion criteria:**
- [ ] All stubs implemented -- no `NotImplementedError` remaining
- [ ] Integration contracts honored (lifecycle: ensure -> load -> embed -> unload)
- [ ] `@summary` block at top of new file
- [ ] Module-level docstring present
- [ ] `ColQwen2LoadError` is FATAL; `VisualEmbeddingError` is NON-FATAL and per-page
- [ ] Mean pooling produces exactly 128-dim float32 vectors
- [ ] Batch processing respects `batch_size` parameter
- [ ] Progress logging at 10% intervals for >10 pages

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.

---

## Task 2.2: MinIO Page Image Storage Operations

**Description:** Extend MinIO operations in `src/db/minio/store.py` to support page image storage with key pattern `pages/{document_id}/{page_number:04d}.jpg`. JPEG compression at configurable quality, pre-storage cleanup for update mode.

**Spec requirements:** FR-401, FR-402, FR-403, FR-404, FR-405

**Dependencies:** none

**Source files:**
- MODIFY `src/db/minio/store.py`

---

**Phase 0 contracts (inlined -- implement these stubs):**

No function stubs in Phase 0 for this task. New helper functions are added directly to the MinIO store module. The following function signatures define the contract:

```python
def store_page_images(
    client: Any,
    document_id: str,
    pages: list[tuple[int, Any]],  # list of (page_number, PIL.Image)
    quality: int = 85,
    bucket: str | None = None,
) -> list[str]:
    """Store page images as JPEG in MinIO.

    Key pattern: pages/{document_id}/{page_number:04d}.jpg (FR-401)
    JPEG compression at specified quality (FR-402).
    Returns list of successfully stored MinIO keys.

    Args:
        client: MinIO client handle.
        document_id: Unique document identifier.
        pages: List of (1-indexed page_number, PIL.Image) tuples.
        quality: JPEG compression quality 1-100. FR-402
        bucket: Target bucket. Uses default if None.

    Returns:
        List of MinIO object keys that were successfully stored. FR-403
    """
    pass  # Implementation target


def delete_page_images(
    client: Any,
    document_id: str,
    bucket: str | None = None,
) -> int:
    """Delete all page images for a document from MinIO.

    Deletes all objects matching prefix pages/{document_id}/ (FR-404).
    Used for pre-storage cleanup in update mode (FR-405).

    Args:
        client: MinIO client handle.
        document_id: Unique document identifier.
        bucket: Target bucket. Uses default if None.

    Returns:
        Number of objects deleted.
    """
    pass  # Implementation target
```

---

**Implementation steps:**

1. [FR-401] In `src/db/minio/store.py`, add `store_page_images()` function. Define the key pattern as `f"pages/{document_id}/{page_number:04d}.jpg"` for each page.

2. [FR-402] For each page image (PIL.Image), serialize to JPEG bytes in an `io.BytesIO` buffer using `image.save(buffer, format="JPEG", quality=quality)`. Set the content type to `"image/jpeg"`.

3. [FR-403] Upload each JPEG buffer to MinIO using the client's `put_object()` method with the computed key, buffer, buffer length, and content type. Collect successfully stored keys in a result list.

4. [FR-401] Wrap each per-page upload in try/except. On failure, log a warning with the page number and error, and skip the page (do not add its key to the result list). This ensures one bad page does not block the rest.

5. [FR-404, FR-405] Add `delete_page_images()` function. List all objects with prefix `f"pages/{document_id}/"` using the client's `list_objects()`. Delete each found object using `remove_object()`. Return the count of deleted objects.

6. [FR-405] Wrap the delete loop in try/except. On failure, log a warning and return the count of objects deleted so far.

**Completion criteria:**
- [ ] All stubs implemented -- no `NotImplementedError` remaining
- [ ] Integration contracts honored (key pattern `pages/{document_id}/{page_num:04d}.jpg`)
- [ ] `@summary` block updated at top of modified file
- [ ] Module-level docstring present
- [ ] Per-page error isolation (one failed upload does not block others)
- [ ] JPEG quality parameter is respected

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.

---

## Task 2.3: Weaviate Visual Collection Schema & CRUD

**Description:** Create `src/vector_db/weaviate/visual_store.py` implementing visual collection schema (named vector "mean_vector" 128-dim HNSW cosine, `patch_vectors` as TEXT/JSON), idempotent ensure, batch insert, and delete by `source_key`.

**Spec requirements:** FR-501, FR-502, FR-503, FR-504, FR-505, FR-506, FR-507

**Dependencies:** none

**Source files:**
- CREATE `src/vector_db/weaviate/visual_store.py`

---

**Phase 0 contracts (inlined -- implement these stubs):**

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

---

**Implementation steps:**

1. [FR-501] Create `src/vector_db/weaviate/visual_store.py` with an `@summary` block and module-level docstring describing the Weaviate visual page collection store.

2. [FR-502, FR-504] Implement `ensure_visual_collection()`:
   - Check if the collection already exists using `client.collections.exists(collection)`. If it exists, return immediately (idempotent).
   - Define the collection schema with:
     - A named vector configuration `"mean_vector"` using HNSW index with cosine distance metric and 128 dimensions.
     - Vectorizer set to `none` (pre-computed embeddings).

3. [FR-503, FR-505] Define all properties for the collection:
   - `document_id`: `DataType.TEXT`
   - `page_number`: `DataType.INT`
   - `source_key`: `DataType.TEXT`
   - `source_uri`: `DataType.TEXT`
   - `source_name`: `DataType.TEXT`
   - `tenant_id`: `DataType.TEXT`
   - `total_pages`: `DataType.INT`
   - `page_width_px`: `DataType.INT`
   - `page_height_px`: `DataType.INT`
   - `minio_key`: `DataType.TEXT`
   - `patch_vectors`: `DataType.TEXT` (JSON-serialized)

4. [FR-502] Create the collection using `client.collections.create()` with the defined schema and named vector configuration.

5. [FR-507] Implement `add_visual_documents()`:
   - Get the collection handle via `client.collections.get(collection)`.
   - Use the collection's batch insert API.
   - For each document dict, extract the `"mean_vector"` key for the named vector and pass remaining properties as object properties.
   - The `"patch_vectors"` value should already be a JSON-serialized string.
   - Return the count of successfully inserted objects.

6. [FR-506] Implement `delete_visual_by_source_key()`:
   - Get the collection handle via `client.collections.get(collection)`.
   - Use a filter on `source_key` equal to the provided value.
   - Delete matching objects using `collection.data.delete_many()` with the filter.
   - Return the count of deleted objects.

**Completion criteria:**
- [ ] All stubs implemented -- no `NotImplementedError` remaining
- [ ] Integration contracts honored (idempotent ensure, batch insert returns count, delete by source_key)
- [ ] `@summary` block at top of new file
- [ ] Module-level docstring present
- [ ] Named vector "mean_vector" is 128-dim, HNSW, cosine
- [ ] `patch_vectors` stored as TEXT (JSON-serialized)
- [ ] Collection creation is idempotent (no error if already exists)

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.

---

## Task 3.1: VectorBackend Abstract Methods + Weaviate Implementation

**Description:** Add `ensure_visual_collection()`, `add_visual_documents()`, `delete_visual_by_source_key()` abstract methods to `VectorBackend` ABC. Implement in `WeaviateBackend` by delegating to `visual_store`. Add public re-exports in `__init__.py`.

**Spec requirements:** FR-501, FR-502, FR-506, FR-507, NFR-909

**Dependencies:** Task 2.3

**Source files:**
- MODIFY `src/vector_db/backend.py`
- MODIFY `src/vector_db/weaviate/backend.py`
- MODIFY `src/vector_db/__init__.py`

---

**Phase 0 contracts (inlined -- implement these stubs):**

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, List, Optional


class VectorBackend(ABC):
    """Abstract contract for a vector store backend.
    Visual collection methods are added below existing methods (NFR-909).
    """
    # ... existing abstract methods unchanged ...

    # -- Visual collection operations --

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
        Returns: Number of objects inserted.
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
        Returns: Number of objects deleted.
        """
        raise NotImplementedError("Task 3.1")
```

---

**Implementation steps:**

1. [NFR-909] In `src/vector_db/backend.py`, add the three new abstract methods (`ensure_visual_collection`, `add_visual_documents`, `delete_visual_by_source_key`) to the `VectorBackend` ABC class. Place them after all existing abstract methods. Do NOT modify any existing methods or signatures.

2. [FR-502] In `src/vector_db/weaviate/backend.py`, import `ensure_visual_collection`, `add_visual_documents`, and `delete_visual_by_source_key` from `src.vector_db.weaviate.visual_store`.

3. [FR-502, FR-507, FR-506] In the `WeaviateBackend` class, implement the three new methods by delegating to the imported `visual_store` functions:
   - `ensure_visual_collection(self, client, collection=None)` -> calls `visual_store.ensure_visual_collection(client, collection or self.default_visual_collection)`.
   - `add_visual_documents(self, client, documents, collection=None)` -> calls `visual_store.add_visual_documents(client, documents, collection or self.default_visual_collection)`.
   - `delete_visual_by_source_key(self, client, source_key, collection=None)` -> calls `visual_store.delete_visual_by_source_key(client, source_key, collection or self.default_visual_collection)`.
   - Use `"RAGVisualPages"` as the default collection name when `collection` is `None` and no instance default exists.

4. [NFR-909] In `src/vector_db/__init__.py`, add `ensure_visual_collection`, `add_visual_documents`, and `delete_visual_by_source_key` to the public re-exports (if the module uses `__all__`, add them there; otherwise add import statements).

**Completion criteria:**
- [ ] All stubs implemented -- no `NotImplementedError` remaining
- [ ] Integration contracts honored (ABC defines contract, WeaviateBackend delegates to visual_store)
- [ ] `@summary` block updated at top of each modified file
- [ ] Module-level docstring present
- [ ] Existing methods and signatures are NOT modified (NFR-909)
- [ ] Public re-exports in `__init__.py` include the three new methods

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.

---

## Task 4.1: EmbeddingPipelineState Extension + Types Registry

**Description:** Add `visual_stored_count` (int, 0) and `page_images` (Optional[List[Any]]) to `EmbeddingPipelineState`. Add `visual_stored_count: int = 0` to `IngestFileResult`. Add `"visual_embedding"` to `PIPELINE_NODE_NAMES` between `"embedding_storage"` and `"knowledge_graph_storage"`.

**Spec requirements:** FR-602, FR-604, FR-605, NFR-909

**Dependencies:** none

**Source files:**
- MODIFY `src/ingest/embedding/state.py`
- MODIFY `src/ingest/common/types.py`

---

**Phase 0 contracts (inlined -- implement these stubs):**

```python
# -- src/ingest/embedding/state.py additions --

from __future__ import annotations
from typing import Any, Dict, List, Optional, TypedDict
from src.ingest.common.schemas import ProcessedChunk
from src.ingest.common.types import Runtime


class EmbeddingPipelineState(TypedDict, total=False):
    """Shared state flowing through the Embedding Pipeline DAG.
    Existing fields are preserved exactly as-is (NFR-909).
    """
    # -- Existing fields (unchanged) --
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

    # -- Visual embedding extensions (FR-602) --
    visual_stored_count: int  # FR-602: number of visual page objects stored; default 0
    page_images: Optional[List[Any]]  # FR-602: PIL.Image objects; cleared after node (FR-606)


# -- src/ingest/common/types.py additions to IngestFileResult --

from dataclasses import dataclass, field


@dataclass
class IngestFileResult:
    """Result of a single-file ingestion run. Existing fields preserved (NFR-909)."""
    # -- Existing fields (unchanged) --
    errors: list[str]
    stored_count: int
    metadata_summary: str
    metadata_keywords: list[str]
    processing_log: list[str]
    source_hash: str
    clean_hash: str
    # -- Visual embedding extension (FR-605) --
    visual_stored_count: int = 0  # FR-605: number of visual page objects stored
```

---

**Implementation steps:**

1. [FR-602] In `src/ingest/embedding/state.py`, add `visual_stored_count: int` and `page_images: Optional[List[Any]]` to the `EmbeddingPipelineState` TypedDict. Place them after all existing fields, under a `# -- Visual embedding extensions (FR-602) --` comment. Do NOT modify any existing fields.

2. [FR-605, NFR-909] In `src/ingest/common/types.py`, add `visual_stored_count: int = 0` to the `IngestFileResult` dataclass. Place it after all existing fields with a default of `0`. Do NOT modify any existing fields.

3. [FR-604] In `src/ingest/common/types.py` (or wherever `PIPELINE_NODE_NAMES` is defined), insert `"visual_embedding"` into the list between `"embedding_storage"` and `"knowledge_graph_storage"`. If `PIPELINE_NODE_NAMES` does not exist, locate the equivalent node ordering registry and insert there.

**Completion criteria:**
- [ ] All stubs implemented -- no `NotImplementedError` remaining
- [ ] Integration contracts honored (new state fields available for visual_embedding_node)
- [ ] `@summary` block updated at top of each modified file
- [ ] Module-level docstring present
- [ ] Existing fields and types are NOT modified (NFR-909)
- [ ] `"visual_embedding"` appears in correct position in pipeline node ordering

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.

---

## Task 4.2: visual_embedding_node Implementation

**Description:** Create `src/ingest/embedding/nodes/visual_embedding.py` implementing the complete visual embedding node. Short-circuit conditions, page image extraction and resizing, MinIO storage, ColQwen2 inference, Weaviate insertion, per-page error isolation, state cleanup.

**Spec requirements:** FR-201..205, FR-301..307, FR-401..405, FR-501..507, FR-601..606, FR-701..705, FR-801..806, NFR-901..903, NFR-907

**Dependencies:** Task 2.1, Task 2.2, Task 2.3, Task 3.1, Task 4.1

**Source files:**
- CREATE `src/ingest/embedding/nodes/visual_embedding.py`

---

**Phase 0 contracts (inlined -- implement these stubs):**

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

Dependencies from other tasks (import these -- they will be implemented):

```python
# From Task 2.1 (src/ingest/support/colqwen.py):
from src.ingest.support.colqwen import (
    ColQwen2PageEmbedding,
    ColQwen2LoadError,
    VisualEmbeddingError,
    ensure_colqwen_ready,
    load_colqwen_model,
    embed_page_images,
    unload_colqwen_model,
)

# From Task 2.2 (src/db/minio/store.py):
from src.db.minio.store import store_page_images, delete_page_images

# From Task 2.3 / 3.1 (src/vector_db/weaviate/visual_store.py via backend):
from src.vector_db.weaviate.visual_store import (
    ensure_visual_collection,
    add_visual_documents,
    delete_visual_by_source_key,
)
```

---

**Implementation steps:**

1. [FR-601] Create `src/ingest/embedding/nodes/visual_embedding.py` with an `@summary` block and module-level docstring.

2. [FR-603, NFR-903] Implement the short-circuit checks at the top of `visual_embedding_node()`:
   - Extract `config` from `state["runtime"].config`.
   - If `config.enable_visual_embedding` is `False`, return `{"visual_stored_count": 0, "page_images": None, "processing_log": [...]}` with a log entry "Visual embedding disabled by config".
   - If `state.get("docling_document")` is `None`, return similarly with log entry "No docling document available for visual embedding".

3. [FR-201, FR-204, FR-205] Extract page images from the docling document:
   - Access the docling document from state.
   - If the document has page images already available (set by the docling parsing step), use those directly.
   - Otherwise, extract pages from the `DoclingDocument` object using its page iteration API.
   - Convert each page image to RGB mode.
   - Record original dimensions (`page_width_px`, `page_height_px`) for each page before resizing.

4. [FR-202, FR-203] Resize page images:
   - For each page image, if the longer edge exceeds `config.page_image_max_dimension`, resize proportionally using `PIL.Image.LANCZOS` resampling.
   - Maintain aspect ratio.

5. [FR-603] If no extractable pages are found after extraction, return with `visual_stored_count=0` and a descriptive log entry.

6. [FR-404, FR-405] Pre-storage cleanup:
   - Get the MinIO client from `state["runtime"]`.
   - Call `delete_page_images(minio_client, document_id)` to remove any existing page images for this document.
   - Get the Weaviate client from `state["runtime"]`.
   - Call `delete_visual_by_source_key(weaviate_client, source_key, config.visual_target_collection)` to remove existing visual objects.

7. [FR-401, FR-402, FR-403] Store page images in MinIO:
   - Prepare a list of `(page_number, pil_image)` tuples.
   - Call `store_page_images(minio_client, document_id, pages, config.page_image_quality)`.
   - Collect the returned MinIO keys for use in Weaviate document construction.

8. [FR-801, FR-806] Load ColQwen2 model:
   - Call `ensure_colqwen_ready()`.
   - Call `load_colqwen_model(config.colqwen_model_name)`.
   - Wrap in try/except for `ColQwen2LoadError`: on failure, log error, add to `state["errors"]`, return with `visual_stored_count=0`.

9. [FR-301, FR-302, FR-303, FR-304, FR-306, FR-307] Run batch embedding:
   - Call `embed_page_images(model, processor, resized_images, config.colqwen_batch_size, page_numbers=page_numbers)`.
   - Receive list of `ColQwen2PageEmbedding` objects.

10. [FR-305] Unload the model immediately after embedding:
    - Call `unload_colqwen_model(model)` in a `finally` block to ensure cleanup.

11. [FR-501, FR-502, FR-503, FR-504, FR-505, FR-507] Construct and insert Weaviate visual documents:
    - Call `ensure_visual_collection(weaviate_client, config.visual_target_collection)`.
    - For each `ColQwen2PageEmbedding` that has a corresponding MinIO key, construct a document dict with:
      - `document_id`, `page_number`, `source_key`, `source_uri`, `source_name` from state
      - `tenant_id` (empty string or from config)
      - `total_pages` (total page count)
      - `page_width_px`, `page_height_px` (original dimensions recorded in step 3)
      - `minio_key` (from step 7)
      - `mean_vector` (from embedding)
      - `patch_vectors` (JSON-serialized from embedding)
    - Call `add_visual_documents(weaviate_client, documents, config.visual_target_collection)`.

12. [FR-701, FR-702, FR-703, FR-704, FR-705] Add processing log entries:
    - Log the number of pages extracted, stored in MinIO, embedded, and indexed in Weaviate.
    - Log timing information for the visual embedding step.
    - Use `append_processing_log()` for all log entries.

13. [FR-803] Verify the return dict does NOT include `stored_count`, `chunks`, `enriched_chunks`, or any text-track state fields.

14. [FR-606] Set `page_images` to `None` in the return dict to free memory.

15. [FR-801, FR-802, FR-804, FR-805] Wrap the entire node body (after short-circuit checks) in a top-level try/except that catches any unhandled exception, logs it as an error, adds it to `state["errors"]`, and returns with `visual_stored_count=0`.

**Completion criteria:**
- [ ] All stubs implemented -- no `NotImplementedError` remaining
- [ ] Integration contracts honored (all directional arrows respected)
- [ ] `@summary` block at top of new file
- [ ] Module-level docstring present
- [ ] Short-circuit conditions return immediately with descriptive logs
- [ ] Per-page error isolation (one page failure does not block others)
- [ ] ColQwen2 model is always unloaded (even on error) via `finally` block
- [ ] `page_images` set to `None` in return dict (memory cleanup)
- [ ] Text-track state fields are NEVER modified
- [ ] Processing log entries cover all major steps

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.

---

## Task 5.1: LangGraph Workflow Wiring

**Description:** Wire `visual_embedding_node` into the LangGraph DAG in `build_embedding_graph()`, positioned after `embedding_storage`, before `knowledge_graph_storage` (or `END`). Import from `nodes/visual_embedding.py`.

**Spec requirements:** FR-601, FR-604

**Dependencies:** Task 4.1, Task 4.2

**Source files:**
- MODIFY `src/ingest/embedding/workflow.py`

---

**Phase 0 contracts (inlined -- implement these stubs):**

No function stubs for this task. Modify the existing `build_embedding_graph()` function in the workflow module. The following describes the wiring contract:

```
DAG topology change:
  BEFORE: ... -> embedding_storage -> knowledge_graph_storage -> ...
  AFTER:  ... -> embedding_storage -> visual_embedding -> knowledge_graph_storage -> ...

Import:
  from src.ingest.embedding.nodes.visual_embedding import visual_embedding_node

Node registration:
  graph.add_node("visual_embedding", visual_embedding_node)

Edge wiring:
  Remove: embedding_storage -> knowledge_graph_storage (or embedding_storage -> END)
  Add:    embedding_storage -> visual_embedding
  Add:    visual_embedding -> knowledge_graph_storage (or visual_embedding -> END)

The node always runs (no conditional edge). Short-circuit logic is inside the node itself.
FR-604: "visual_embedding" must appear in PIPELINE_NODE_NAMES between
"embedding_storage" and "knowledge_graph_storage".
```

---

**Implementation steps:**

1. [FR-601] In `src/ingest/embedding/workflow.py`, add the import: `from src.ingest.embedding.nodes.visual_embedding import visual_embedding_node`.

2. [FR-601] In `build_embedding_graph()`, register the new node: `graph.add_node("visual_embedding", visual_embedding_node)`.

3. [FR-604] Modify the edge wiring:
   - Locate the existing edge from `"embedding_storage"` to the next node (either `"knowledge_graph_storage"` or `END`).
   - Replace it with: `"embedding_storage"` -> `"visual_embedding"`.
   - Add: `"visual_embedding"` -> the node that was previously after `"embedding_storage"`.

4. [FR-604] The node is unconditional (no conditional routing). The short-circuit logic lives inside `visual_embedding_node` itself and returns a no-op state update when disabled.

**Completion criteria:**
- [ ] All stubs implemented -- no `NotImplementedError` remaining
- [ ] Integration contracts honored (node positioned correctly in DAG)
- [ ] `@summary` block updated at top of modified file
- [ ] Module-level docstring present
- [ ] `visual_embedding` node runs unconditionally in the DAG
- [ ] Edge from `embedding_storage` goes to `visual_embedding`, then to next node

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.

---

## Task 5.2: Optional Dependency Declaration

**Description:** Add `[visual]` optional extras group to `pyproject.toml` declaring `colpali-engine` and `bitsandbytes`. Add `rag[visual]` to the `all` extras group.

**Spec requirements:** NFR-906

**Dependencies:** none

**Source files:**
- MODIFY `pyproject.toml`

---

**Phase 0 contracts (inlined -- implement these stubs):**

No function stubs. Configuration file edit:

```toml
# pyproject.toml additions under [project.optional-dependencies]

[project.optional-dependencies]
# ... existing extras ...
visual = [
    "colpali-engine>=0.3.0",
    "bitsandbytes>=0.43.0",
]

# Update 'all' group to include visual:
# all = [...existing..., "rag[visual]"]
```

---

**Implementation steps:**

1. [NFR-906] In `pyproject.toml`, locate the `[project.optional-dependencies]` section.

2. [NFR-906] Add a new `visual` extras group with:
   - `"colpali-engine>=0.3.0"`
   - `"bitsandbytes>=0.43.0"`

3. [NFR-906] If an `all` extras group exists, add `"rag[visual]"` (or the visual dependencies directly) to it. If no `all` group exists, skip this step.

**Completion criteria:**
- [ ] All stubs implemented -- no `NotImplementedError` remaining
- [ ] Integration contracts honored (`pip install "rag[visual]"` installs both packages)
- [ ] Existing extras groups are NOT modified
- [ ] Version constraints match the specified minimums

---

**Agent isolation contract (copy verbatim into implement-code dispatch):**

> **Agent isolation contract:** This agent receives ONLY:
> 1. This task section (description, FRs, Phase 0 contracts inlined above, implementation steps)
>
> **Must NOT receive:** Other task sections, other source files, design doc pattern entries, the full spec, the full design doc, or the complete implementation docs.

---

## Module Boundary Map

| Task | Action | File |
|------|--------|------|
| 1.1 | MODIFY | `config/settings.py` |
| 1.1 | MODIFY | `src/ingest/common/types.py` |
| 1.1 | MODIFY | `src/ingest/impl.py` |
| 1.1 | MODIFY | `pyproject.toml` |
| 1.2 | MODIFY | `src/ingest/support/docling.py` |
| 2.1 | CREATE | `src/ingest/support/colqwen.py` |
| 2.2 | MODIFY | `src/db/minio/store.py` |
| 2.3 | CREATE | `src/vector_db/weaviate/visual_store.py` |
| 3.1 | MODIFY | `src/vector_db/backend.py` |
| 3.1 | MODIFY | `src/vector_db/weaviate/backend.py` |
| 3.1 | MODIFY | `src/vector_db/__init__.py` |
| 4.1 | MODIFY | `src/ingest/embedding/state.py` |
| 4.1 | MODIFY | `src/ingest/common/types.py` |
| 4.2 | CREATE | `src/ingest/embedding/nodes/visual_embedding.py` |
| 5.1 | MODIFY | `src/ingest/embedding/workflow.py` |
| 5.2 | MODIFY | `pyproject.toml` |

**File ownership conflicts (multiple tasks touch the same file):**

| File | Tasks | Resolution |
|------|-------|------------|
| `config/settings.py` | 1.1 | No conflict (single owner) |
| `src/ingest/common/types.py` | 1.1, 4.1 | 1.1 adds config fields; 4.1 adds `IngestFileResult.visual_stored_count` and pipeline node name. Both are additive, non-overlapping sections. |
| `pyproject.toml` | 1.1, 5.2 | 1.1 may reference extras; 5.2 adds the `[visual]` group. 5.2 is the canonical owner of extras. Task 1.1 should NOT add extras (defer to 5.2). |

---

## Dependency Graph

```
Wave 1 (parallel -- no dependencies):
  Task 1.1 ─────────────┐
  Task 1.2 ─────────────┤
  Task 2.1 ─────────────┤
  Task 2.2 ─────────────┤
  Task 2.3 ─────────────┤ (all independent)
  Task 4.1 ─────────────┤
  Task 5.2 ─────────────┘

Wave 2:
  Task 3.1 ──── depends on Task 2.3

Wave 3:
  Task 4.2 ──── depends on Task 2.1, 2.2, 2.3, 3.1, 4.1  [CRITICAL PATH]

Wave 4:
  Task 5.1 ──── depends on Task 4.1, 4.2  [CRITICAL PATH]
```

**Critical path:** Task 2.3 -> Task 3.1 -> Task 4.2 -> Task 5.1

**Parallelism opportunities:**
- Wave 1: All 7 tasks can execute simultaneously.
- Wave 2: Task 3.1 runs alone (short task -- ABC additions + delegation).
- Wave 3: Task 4.2 is the largest single task (node implementation).
- Wave 4: Task 5.1 is a small wiring task.

---

## Task-to-FR Traceability Table

| FR/NFR | Task(s) | Description |
|--------|---------|-------------|
| FR-101 | 1.1 | Enable/disable visual embedding via config flag |
| FR-102 | 1.1 | Configurable visual target collection name |
| FR-103 | 1.1 | Configurable ColQwen2 model identifier |
| FR-104 | 1.1 | Configurable ColQwen2 batch size |
| FR-105 | 1.1 | Configurable page image JPEG quality |
| FR-106 | 1.1 | Configurable page image max dimension |
| FR-107 | 1.1, 1.2 | Derived generate_page_images flag + docling integration |
| FR-108 | 1.1 | Config validation (contradictory settings) |
| FR-109 | 1.1 | All config backed by environment variables |
| FR-201 | 1.2, 4.2 | Page image extraction from DoclingDocument |
| FR-202 | 4.2 | Page image resizing (max dimension constraint) |
| FR-203 | 4.2 | Aspect ratio preservation during resize |
| FR-204 | 1.2, 4.2 | RGB color space conversion |
| FR-205 | 1.2, 4.2 | Original page dimension recording |
| FR-301 | 2.1, 4.2 | ColQwen2 model loading with 4-bit quantization |
| FR-302 | 2.1, 4.2 | Per-page embedding with page number tracking |
| FR-303 | 2.1, 4.2 | 128-dim mean-pooled vector computation |
| FR-304 | 2.1, 4.2 | Raw patch vector extraction (JSON-serializable) |
| FR-305 | 2.1, 4.2 | GPU memory release after embedding |
| FR-306 | 2.1, 4.2 | Progress logging at 10% intervals for >10 pages |
| FR-307 | 2.1, 4.2 | Per-page inference failure isolation (non-fatal) |
| FR-401 | 2.2, 4.2 | MinIO page image key pattern |
| FR-402 | 2.2, 4.2 | JPEG compression at configurable quality |
| FR-403 | 2.2, 4.2 | Return list of stored MinIO keys |
| FR-404 | 2.2, 4.2 | Delete all page images by document prefix |
| FR-405 | 2.2, 4.2 | Pre-storage cleanup in update mode |
| FR-501 | 2.3, 3.1, 4.2 | Visual collection naming convention |
| FR-502 | 2.3, 3.1, 4.2 | Idempotent collection creation |
| FR-503 | 2.3, 4.2 | Visual page object property schema |
| FR-504 | 2.3, 4.2 | Named vector "mean_vector" with HNSW cosine index |
| FR-505 | 2.3, 4.2 | patch_vectors stored as TEXT/JSON |
| FR-506 | 2.3, 3.1, 4.2 | Delete visual objects by source_key |
| FR-507 | 2.3, 3.1, 4.2 | Batch insert visual page objects |
| FR-601 | 4.2, 5.1 | Node positioning in LangGraph DAG |
| FR-602 | 4.1, 4.2 | visual_stored_count state field |
| FR-603 | 4.2 | Short-circuit conditions |
| FR-604 | 4.1, 5.1 | Pipeline node ordering registry |
| FR-605 | 4.1 | IngestFileResult visual_stored_count field |
| FR-606 | 4.2 | Clear page_images from state after processing |
| FR-701 | 4.2 | Log pages extracted count |
| FR-702 | 4.2 | Log pages stored in MinIO count |
| FR-703 | 4.2 | Log pages embedded count |
| FR-704 | 4.2 | Log pages indexed in Weaviate count |
| FR-705 | 4.2 | Log timing information for visual embedding step |
| FR-801 | 4.2 | Top-level error handling in node |
| FR-802 | 4.2 | ColQwen2LoadError is fatal for visual track |
| FR-803 | 4.2 | Text-track state fields must not be modified |
| FR-804 | 4.2 | Unhandled exceptions caught and logged |
| FR-805 | 4.2 | Error added to state["errors"] on failure |
| FR-806 | 2.1, 4.2 | Clear install command in dependency error messages |
| NFR-901 | 2.1, 4.2 | Peak VRAM <= 4GB |
| NFR-902 | 2.1, 4.2 | 4-bit quantization via BitsAndBytes |
| NFR-903 | 4.2 | Short-circuit is zero-cost (no model load) |
| NFR-904 | 2.2 | MinIO storage efficiency |
| NFR-905 | 1.1 | Config validation fail-fast |
| NFR-906 | 1.1, 2.1, 5.2 | Optional dependency declaration |
| NFR-907 | 4.2 | Per-page error isolation |
| NFR-908 | 2.1 | torch.inference_mode for memory efficiency |
| NFR-909 | 3.1, 4.1 | Existing API/state contracts preserved |
| NFR-910 | 2.1 | No gradient computation during inference |

**Coverage verification:** All 48 functional requirements (FR-101 through FR-806) and all 10 non-functional requirements (NFR-901 through NFR-910) appear in the traceability table above with at least one task assignment.
