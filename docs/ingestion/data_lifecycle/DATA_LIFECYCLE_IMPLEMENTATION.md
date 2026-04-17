> **Document type:** Implementation document (Layer 5)
> **Upstream:** DATA_LIFECYCLE_DESIGN.md
> **Downstream:** DATA_LIFECYCLE_ENGINEERING_GUIDE.md, test plans
> **Last updated:** 2026-04-15

# Data Lifecycle --- Implementation Guide (v1.0.0)

| Field | Value |
|-------|-------|
| **Document** | Data Lifecycle Implementation Guide |
| **Version** | 1.0.0 |
| **Status** | Draft |
| **Design Reference** | `DATA_LIFECYCLE_DESIGN.md` v1.0.0 (Tasks 1--6) |
| **Spec Reference** | `DATA_LIFECYCLE_SPEC.md` v1.0.0 (FR-3000--FR-3114, NFR-3180--NFR-3230) |
| **Created** | 2026-04-15 |
| **Last Updated** | 2026-04-15 |

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-04-15 | Initial implementation guide covering all six design tasks. |

> **Document Intent.** This guide provides concrete, code-level implementation
> details for each task defined in `DATA_LIFECYCLE_DESIGN.md`. It bridges the
> gap between the design (what to build) and the codebase (how to build it).
> Each section maps to one design task and includes module layout, code
> snippets, configuration examples, store schema changes, and integration
> points.

---

## 1. Implementation Overview

### Scope

Six implementation tasks, mapped to the design:

| Task | Design Task | Key Deliverable | Complexity |
|------|-------------|-----------------|------------|
| T1 | MinIO Clean Store Migration | `src/ingest/common/minio_clean_store.py` | Medium |
| T2 | Manifest Schema Extension | Extended `ManifestEntry` + `PIPELINE_SCHEMA_VERSION` | Low |
| T3 | Trace ID Infrastructure | UUID v4 per workflow, propagated to all stores | Medium |
| T4 | GC/Sync Engine | `src/ingest/lifecycle/` package | High |
| T5 | Schema Migration Runner | `src/ingest/lifecycle/migration.py` + changelog | High |
| T6 | E2E Validation Node | `src/ingest/lifecycle/validation.py` | Medium |

### Implementation Order

```
Phase A:  Task 2 (Manifest Schema)              -- zero-risk, unblocks all
Phase B:  Task 1 (MinIO Clean Store)  ||  Task 3 (Trace ID)   -- parallel
Phase C:  Task 4 (GC Engine)         ||  Task 6 (Validation)  -- parallel
Phase D:  Task 5 (Schema Migration Runner)       -- depends on all above
```

### Prerequisites

- MinIO client library (`minio`) already in the dependency set (`src/db/minio/store.py`).
- Weaviate client and vector_db facade already exist (`src/vector_db/__init__.py`).
- Neo4j is accessed through `KnowledgeGraphBuilder` (`src/core/knowledge_graph.py`).
- The `src/db/` public API (`put_document`, `get_document`, `delete_document`, `list_documents`) is the canonical MinIO interface.

---

## 2. Module Layout

### New Files

```
src/ingest/
├── common/
│   ├── minio_clean_store.py        # Task 1: MinIO-backed clean store
│   └── schemas.py                  # Task 2: ManifestEntry extension + PIPELINE_SCHEMA_VERSION
├── lifecycle/
│   ├── __init__.py                 # Task 4: Package init + public exports
│   ├── schemas.py                  # Task 4: SyncResult, GCResult, OrphanReport, StoreCleanupStatus
│   ├── sync.py                     # Task 4: Source-to-manifest diff engine
│   ├── gc.py                       # Task 4: Four-store reconciliation engine
│   ├── orphan_report.py            # Task 4: Orphan detection report
│   ├── migration.py                # Task 5: Migration runner
│   ├── changelog.py                # Task 5: Schema changelog parser
│   └── validation.py               # Task 6: E2E validation logic

config/
└── schema_changelog.yaml           # Task 5: Machine-readable schema changelog
```

### Modified Files

| File | Tasks | Summary |
|------|-------|---------|
| `src/ingest/common/schemas.py` | T2 | Add 7 fields to `ManifestEntry`, add `PIPELINE_SCHEMA_VERSION` |
| `src/ingest/common/types.py` | T1, T3, T4 | Add config fields, extend `IngestFileResult` |
| `src/ingest/common/clean_store.py` | T1 | Deprecate; remove `write_docling`/`read_docling` |
| `src/ingest/common/__init__.py` | T1 | Export `MinioCleanStore`, keep `CleanDocumentStore` alias |
| `src/ingest/impl.py` | T1, T2, T3, T4, T6 | Trace ID generation, MinIO writes, lifecycle integration |
| `src/ingest/doc_processing/state.py` | T3 | Add `trace_id` to `DocumentProcessingState` |
| `src/ingest/embedding/state.py` | T3 | Add `trace_id` to `EmbeddingPipelineState` |
| `src/ingest/embedding/nodes/embedding_storage.py` | T3, T5 | Add `trace_id`, `schema_version`, `batch_id` to chunk metadata |
| `src/vector_db/__init__.py` | T4, T6 | Add `soft_delete_by_source_key()`, `count_by_trace_id()` |
| `config/settings.py` | T4 | Add `RAG_GC_MODE`, `RAG_GC_RETENTION_DAYS`, `RAG_GC_SCHEDULE` |

---

## 3. MinIO Clean Store Implementation

**Design Task:** 1
**Spec Requirements:** FR-3030, FR-3031, FR-3032, FR-3033, FR-3034

### 3.1 Module: `src/ingest/common/minio_clean_store.py`

This module provides a purpose-built store for Phase 1 clean document output. It writes
objects under a `clean/` prefix in MinIO using the existing `src/db/` public API, keeping
the clean store logically separated from the general document store (which uses UUID-based keys).

```python
# src/ingest/common/minio_clean_store.py

"""MinIO-backed durable clean document store for Phase 1 output.

Objects are stored under the ``clean/`` prefix:
  - ``clean/{safe_key}.md``          -- UTF-8 clean markdown
  - ``clean/{safe_key}.meta.json``   -- JSON metadata envelope (FR-3033)

The ``.meta.json`` is written last as the commit marker so readers can
treat its presence as proof that both objects are consistent.
"""

from __future__ import annotations

import io
import logging
import re
import orjson
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("rag.ingest.minio_clean_store")

_UNSAFE_CHARS = re.compile(r'[/\\:*?"<>|]')
_CLEAN_PREFIX = "clean/"


def _safe_key(source_key: str) -> str:
    """Sanitize source_key for use in MinIO object keys."""
    return _UNSAFE_CHARS.sub("_", source_key).replace("..", "__")


class MinioCleanStore:
    """Durable clean document store backed by MinIO.

    Uses the ``src/db`` public API for all storage operations, keeping this
    module decoupled from raw ``minio.Minio`` calls.

    Args:
        client: A MinIO client handle (from ``src.db.create_persistent_client()``).
        bucket: Target bucket name.
    """

    def __init__(self, client: Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    # -- Object key helpers ------------------------------------------------

    @staticmethod
    def _object_key_md(source_key: str) -> str:
        return f"{_CLEAN_PREFIX}{_safe_key(source_key)}.md"

    @staticmethod
    def _object_key_meta(source_key: str) -> str:
        return f"{_CLEAN_PREFIX}{_safe_key(source_key)}.meta.json"

    # -- Write -------------------------------------------------------------

    def write(
        self,
        source_key: str,
        text: str,
        meta: dict[str, Any],
    ) -> None:
        """Write clean markdown and metadata to MinIO.

        The markdown object is written first; the ``.meta.json`` is written
        last as the commit marker (FR-3033 AC4). Content types are set to
        ``text/markdown`` and ``application/json`` respectively.

        Args:
            source_key: Stable source identity key.
            text: Clean markdown text (UTF-8).
            meta: Metadata envelope dict. Must include source identity fields,
                ``source_hash``, ``clean_hash``, ``schema_version``, ``trace_id``.
        """
        md_key = self._object_key_md(source_key)
        meta_key = self._object_key_meta(source_key)

        # Ensure created_at is present
        if "created_at" not in meta:
            meta["created_at"] = datetime.now(timezone.utc).isoformat()

        # Write markdown first
        md_bytes = text.encode("utf-8")
        self._client.put_object(
            self._bucket,
            md_key,
            io.BytesIO(md_bytes),
            length=len(md_bytes),
            content_type="text/markdown",
        )

        # Write metadata envelope last (commit marker)
        meta_bytes = orjson.dumps(meta, option=orjson.OPT_INDENT_2)
        self._client.put_object(
            self._bucket,
            meta_key,
            io.BytesIO(meta_bytes),
            length=len(meta_bytes),
            content_type="application/json",
        )

        logger.debug(
            "minio_clean_store_write source_key=%s md_key=%s meta_key=%s",
            source_key,
            md_key,
            meta_key,
        )

    # -- Read --------------------------------------------------------------

    def read(self, source_key: str) -> tuple[str, dict[str, Any]]:
        """Read clean markdown and metadata from MinIO.

        Raises:
            Exception: If objects do not exist or cannot be read.
        """
        md_key = self._object_key_md(source_key)
        meta_key = self._object_key_meta(source_key)

        md_response = self._client.get_object(self._bucket, md_key)
        text = md_response.read().decode("utf-8")
        md_response.close()
        md_response.release_conn()

        meta_response = self._client.get_object(self._bucket, meta_key)
        meta = orjson.loads(meta_response.read())
        meta_response.close()
        meta_response.release_conn()

        return text, meta

    # -- Exists ------------------------------------------------------------

    def exists(self, source_key: str) -> bool:
        """Check if a clean document exists in MinIO for this source_key.

        Checks for the ``.meta.json`` object (the commit marker).
        """
        meta_key = self._object_key_meta(source_key)
        try:
            self._client.stat_object(self._bucket, meta_key)
            return True
        except Exception:
            return False

    # -- Delete ------------------------------------------------------------

    def delete(self, source_key: str) -> None:
        """Remove both clean markdown and metadata objects from MinIO."""
        for key in (self._object_key_md(source_key), self._object_key_meta(source_key)):
            try:
                self._client.remove_object(self._bucket, key)
            except Exception as exc:
                logger.warning(
                    "minio_clean_store_delete_failed key=%s error=%s",
                    key,
                    exc,
                )

    # -- Soft delete (for GC) ----------------------------------------------

    def soft_delete(self, source_key: str) -> None:
        """Move clean objects to the deleted/ prefix for retention.

        Copies both objects to ``deleted/{safe_key}.*`` then removes the
        originals under ``clean/``.
        """
        safe = _safe_key(source_key)
        for suffix in (".md", ".meta.json"):
            src_key = f"{_CLEAN_PREFIX}{safe}{suffix}"
            dst_key = f"deleted/{safe}{suffix}"
            try:
                from minio.commonconfig import CopySource

                self._client.copy_object(
                    self._bucket,
                    dst_key,
                    CopySource(self._bucket, src_key),
                )
                self._client.remove_object(self._bucket, src_key)
            except Exception as exc:
                logger.warning(
                    "minio_clean_store_soft_delete_failed src=%s dst=%s error=%s",
                    src_key,
                    dst_key,
                    exc,
                )

    # -- List keys ---------------------------------------------------------

    def list_keys(self) -> list[str]:
        """List all source_keys with clean documents in MinIO.

        Enumerates ``.meta.json`` objects under the ``clean/`` prefix and
        strips the prefix and suffix to recover the safe key.
        """
        keys: list[str] = []
        objects = self._client.list_objects(
            self._bucket, prefix=_CLEAN_PREFIX, recursive=True
        )
        for obj in objects:
            name = obj.object_name or ""
            if name.endswith(".meta.json"):
                # Extract safe_key: strip "clean/" prefix and ".meta.json" suffix
                safe = name[len(_CLEAN_PREFIX) : -len(".meta.json")]
                keys.append(safe)
        return keys
```

### 3.2 Deprecating `CleanDocumentStore`

Modify `src/ingest/common/clean_store.py`:

1. Remove `write_docling()`, `read_docling()`, and `_docling_path()` methods.
2. Add a deprecation warning on `__init__()`.
3. Remove the `docling_document` parameter from `write()`.

```python
# src/ingest/common/clean_store.py -- changes to __init__

import warnings

class CleanDocumentStore:
    """Persistent store for clean Markdown output -- DEBUG USE ONLY.

    .. deprecated:: 1.0.0
        Use :class:`MinioCleanStore` for durable storage. This class is
        retained only for local debug exports via ``export_processed=True``.
    """

    def __init__(self, store_dir: Path) -> None:
        warnings.warn(
            "CleanDocumentStore is deprecated for production use. "
            "Use MinioCleanStore instead. This class is retained for "
            "debug exports only (export_processed=True).",
            DeprecationWarning,
            stacklevel=2,
        )
        self._dir = Path(store_dir)

    # Remove: write_docling(), read_docling(), _docling_path()
    # Remove: docling_document parameter from write()
    # Keep: write(source_key, text, meta), read(), exists(), delete(), list_keys(), clean_hash()
```

### 3.3 IngestionConfig Changes

Add to `src/ingest/common/types.py`:

```python
@dataclass
class IngestionConfig:
    # ... existing fields ...

    # -- Data Lifecycle (Task 1) --
    clean_store_bucket: str = ""
    """MinIO bucket for clean store objects. Empty string reuses target_bucket."""

    # Remove: persist_docling_document field (FR-3032)
```

The `persist_docling_document` field and its references in `ingest_file()` are removed.
Any existing code referencing `config.persist_docling_document` is updated to remove the
conditional (DoclingDocument is never persisted to any store).

### 3.4 Orchestrator Integration

Update `src/ingest/impl.py` -- `ingest_file()` to write to MinIO after Phase 1:

```python
# src/ingest/impl.py -- inside ingest_file(), after Phase 1 succeeds

from src.ingest.common.minio_clean_store import MinioCleanStore
from src.ingest.common.schemas import PIPELINE_SCHEMA_VERSION

# After Phase 1 succeeds and clean_text is determined:
clean_text: str = phase1.get("refactored_text") or phase1.get("cleaned_text", "")
clean_hash = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()

# -- MinIO durable write (FR-3031) ------------------------------------
if runtime.db_client is not None:
    minio_store = MinioCleanStore(
        client=runtime.db_client,
        bucket=config.clean_store_bucket or config.target_bucket,
    )
    minio_meta = {
        "source_key": source_key,
        "source_name": source_name,
        "source_uri": source_uri,
        "source_id": source_id,
        "connector": connector,
        "source_version": source_version,
        "source_hash": phase1.get("source_hash", ""),
        "clean_hash": clean_hash,
        "schema_version": PIPELINE_SCHEMA_VERSION,
        "trace_id": trace_id,  # from Task 3
    }
    try:
        minio_store.write(source_key, clean_text, minio_meta)
    except Exception as exc:
        logger.warning(
            "minio_clean_store_write_failed source_key=%s error=%s",
            source_key,
            exc,
        )
        # MinIO failure does not block pipeline -- in-memory handoff still works.

# -- Debug export (retained, FR-3034) ---------------------------------
if config.export_processed and config.clean_store_dir:
    _debug_store = CleanDocumentStore(Path(config.clean_store_dir))
    debug_meta = {
        "source_key": source_key,
        "source_name": source_name,
        "source_uri": source_uri,
        "source_id": source_id,
        "connector": connector,
        "source_version": source_version,
        "source_hash": phase1.get("source_hash", ""),
    }
    _debug_store.write(source_key, clean_text, debug_meta)
    # No docling_document parameter -- FR-3032
```

### 3.5 Exports Update

Update `src/ingest/common/__init__.py`:

```python
from src.ingest.common.minio_clean_store import MinioCleanStore

__all__ = [
    # ... existing exports ...
    "MinioCleanStore",
    "CleanDocumentStore",  # retained for backward compat (debug only)
]
```

---

## 4. Manifest Schema Extension

**Design Task:** 2
**Spec Requirements:** FR-3100, FR-3114, FR-3020, FR-3053, FR-3061

### 4.1 Schema Changes: `src/ingest/common/schemas.py`

```python
# src/ingest/common/schemas.py

# -- Pipeline schema version constant (FR-3100 AC4) --
PIPELINE_SCHEMA_VERSION: str = "1.0.0"
"""Single canonical source of truth for the current pipeline schema version.

Referenced by: manifest writes, Weaviate chunk metadata, MinIO metadata
envelopes, and the migration runner.
"""


class ManifestEntry(TypedDict, total=False):
    """Canonical manifest entry persisted for each source key.

    All fields are optional (total=False) per FR-3114 to maintain
    backward compatibility with existing manifests.
    """

    # --- Existing fields (unchanged) ---
    source: str
    source_uri: str
    source_id: str
    source_key: str
    connector: str
    source_version: str
    content_hash: str
    chunk_count: int
    summary: str
    keywords: list[str]
    processing_log: list[str]
    mirror_stem: str
    legacy_name: str

    # --- Data Lifecycle additions (FR-3100, FR-3020, FR-3050, FR-3053, FR-3061) ---
    schema_version: str       # Semantic version, e.g. "1.0.0" (FR-3100)
    trace_id: str             # UUID v4 trace ID for this ingestion run (FR-3050)
    batch_id: str             # Optional batch grouping ID (FR-3053)
    deleted: bool             # True if soft-deleted (FR-3020)
    deleted_at: str           # ISO 8601 timestamp of soft deletion (FR-3020)
    validation: dict          # E2E validation result dict (FR-3061)
    clean_hash: str           # SHA-256 of clean markdown output
```

### 4.2 Backward Compatibility Contract

All code reading manifest entries uses `.get()` with explicit defaults. Update
`src/ingest/impl.py` -- `_normalize_manifest_entries()`:

```python
def _normalize_manifest_entries(
    manifest: dict[str, Any],
) -> dict[str, ManifestEntry]:
    """Normalize old/new manifest formats into a source_key-indexed mapping.

    New lifecycle fields are resolved with safe defaults so pre-1.0.0
    manifests load cleanly (FR-3114).
    """
    normalized: dict[str, ManifestEntry] = {}
    for raw_key, raw_entry in manifest.items():
        if not isinstance(raw_entry, dict):
            continue
        entry = dict(raw_entry)
        source_key = str(entry.get("source_key", "")).strip()
        if not source_key:
            key_text = str(raw_key)
            if key_text.startswith(f"{_LOCAL_CONNECTOR}:"):
                source_key = key_text
            else:
                source_key = f"legacy_name:{key_text}"
                entry.setdefault("legacy_name", key_text)
        entry["source_key"] = source_key
        # Ensure lifecycle fields have safe defaults for old manifests
        entry.setdefault("schema_version", "0.0.0")
        entry.setdefault("trace_id", "")
        entry.setdefault("batch_id", "")
        entry.setdefault("deleted", False)
        entry.setdefault("deleted_at", "")
        entry.setdefault("validation", {})
        entry.setdefault("clean_hash", "")
        normalized[source_key] = entry
    return normalized
```

### 4.3 Manifest Entry Construction

Update the manifest write in `ingest_directory()` to include new fields:

```python
# src/ingest/impl.py -- manifest entry construction after successful ingest

manifest[source["source_key"]] = {
    "source": source["source_name"],
    "source_uri": source["source_uri"],
    "source_id": source["source_id"],
    "source_key": source["source_key"],
    "connector": source["connector"],
    "source_version": source["source_version"],
    "content_hash": result.source_hash,
    "clean_hash": result.clean_hash,
    "chunk_count": result.stored_count,
    "summary": result.metadata_summary,
    "keywords": result.metadata_keywords,
    "processing_log": result.processing_log[-12:],
    "mirror_stem": stem,
    # -- Data Lifecycle fields --
    "schema_version": PIPELINE_SCHEMA_VERSION,
    "trace_id": result.trace_id,
    "batch_id": batch_id,
    "deleted": False,
    "deleted_at": "",
    "validation": result.validation,
}
```

---

## 5. Trace ID Implementation

**Design Task:** 3
**Spec Requirements:** FR-3050, FR-3051, FR-3052, FR-3053, NFR-3220

### 5.1 Trace ID Generation in Orchestrator

Update `src/ingest/impl.py` -- `ingest_file()`:

```python
from uuid import uuid4

def ingest_file(
    source_path: Path,
    runtime: Runtime,
    source_name: str,
    source_uri: str,
    source_key: str,
    source_id: str,
    connector: str,
    source_version: str,
    existing_hash: str = "",
    existing_source_uri: str = "",
    batch_id: str = "",              # NEW (FR-3053)
) -> IngestFileResult:
    config = runtime.config

    # -- Trace ID generation (FR-3050) -----------------------------------
    trace_id = str(uuid4())
    logger.info(
        "ingest_file_start trace_id=%s source_key=%s batch_id=%s",
        trace_id,
        source_key,
        batch_id,
    )

    # -- Phase 1 ----------------------------------------------------------
    phase1 = run_document_processing(
        runtime=runtime,
        source_path=str(source_path),
        source_name=source_name,
        source_uri=source_uri,
        source_key=source_key,
        source_id=source_id,
        connector=connector,
        source_version=source_version,
        trace_id=trace_id,             # NEW (FR-3051)
    )
    # ... rest of function ...
```

### 5.2 Phase 1 State Extension

Update `src/ingest/doc_processing/state.py`:

```python
class DocumentProcessingState(TypedDict, total=False):
    # ... existing fields ...
    trace_id: str    # UUID v4 trace ID (FR-3051)
```

### 5.3 Phase 2 State Extension

Update `src/ingest/embedding/state.py`:

```python
class EmbeddingPipelineState(TypedDict, total=False):
    # ... existing fields ...
    trace_id: str    # UUID v4 trace ID (FR-3052)
    batch_id: str    # Optional batch grouping ID (FR-3053)
```

### 5.4 Phase 2 Function Signature

Update `run_embedding_pipeline()` to accept and propagate `trace_id`:

```python
# src/ingest/embedding/__init__.py or src/ingest/embedding/impl.py

def run_embedding_pipeline(
    runtime: Runtime,
    source_key: str,
    source_name: str,
    source_uri: str,
    source_id: str,
    connector: str,
    source_version: str,
    clean_text: str,
    clean_hash: str,
    refactored_text: str | None = None,
    docling_document: Any | None = None,
    trace_id: str = "",               # NEW (FR-3052)
    batch_id: str = "",               # NEW (FR-3053)
) -> dict:
    ...
```

### 5.5 Weaviate Chunk Metadata Injection

Update `src/ingest/embedding/nodes/embedding_storage.py` to include trace_id,
schema_version, and batch_id in every chunk's Weaviate metadata:

```python
# Inside the embedding_storage node, when constructing chunk metadata:

from src.ingest.common.schemas import PIPELINE_SCHEMA_VERSION

chunk_properties = {
    # ... existing properties (source_key, source_name, chunk_text, etc.) ...
    "trace_id": state.get("trace_id", ""),
    "schema_version": PIPELINE_SCHEMA_VERSION,
    "batch_id": state.get("batch_id", ""),
    "deleted": False,
}
```

### 5.6 Weaviate Collection Schema Extension

The Weaviate collection must include four new properties. Update the collection
schema definition (typically in `src/vector_db/__init__.py` or a schema
initialization module):

```python
# New properties to add to the Weaviate collection schema:
{
    "name": "trace_id",
    "dataType": ["text"],
    "description": "UUID v4 trace ID for the ingestion run that produced this chunk.",
},
{
    "name": "schema_version",
    "dataType": ["text"],
    "description": "Pipeline schema version at the time of storage.",
},
{
    "name": "batch_id",
    "dataType": ["text"],
    "description": "Optional batch grouping ID for the ingestion run.",
},
{
    "name": "deleted",
    "dataType": ["boolean"],
    "description": "Soft-delete flag. Excluded from retrieval when true.",
},
```

### 5.7 Structured Logging Contract

Every log call in pipeline nodes must include `trace_id` as a structured field.
Apply this pattern to all nodes in `src/ingest/doc_processing/nodes/*.py` and
`src/ingest/embedding/nodes/*.py`:

```python
# Pattern for all pipeline node log calls (NFR-3220):

logger.info(
    "text_cleaning_complete chars=%d",
    len(cleaned_text),
    extra={
        "trace_id": state.get("trace_id", ""),
        "source_key": state.get("source_key", ""),
    },
)
```

### 5.8 IngestFileResult Extension

Update `src/ingest/common/types.py`:

```python
@dataclass
class IngestFileResult:
    errors: list[str]
    stored_count: int
    metadata_summary: str
    metadata_keywords: list[str]
    processing_log: list[str]
    source_hash: str
    clean_hash: str
    visual_stored_count: int = 0
    # -- Data Lifecycle additions --
    trace_id: str = ""                # NEW: UUID v4 for manifest recording
    validation: dict = field(default_factory=dict)  # NEW: E2E validation result
```

---

## 6. GC/Sync Engine Implementation

**Design Task:** 4
**Spec Requirements:** FR-3000--FR-3022, NFR-3180, NFR-3210, NFR-3221, NFR-3230

### 6.1 Package Structure

Create `src/ingest/lifecycle/` with the following modules:

```
src/ingest/lifecycle/
├── __init__.py
├── schemas.py
├── sync.py
├── gc.py
└── orphan_report.py
```

### 6.2 Typed Contracts: `src/ingest/lifecycle/schemas.py`

```python
# src/ingest/lifecycle/schemas.py

"""Typed contracts for the data lifecycle subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SyncResult:
    """Result of a source-to-manifest diff (FR-3000)."""

    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    unchanged: int = 0


@dataclass
class StoreCleanupStatus:
    """Per-store cleanup result for a single source_key."""

    weaviate: bool = True
    minio: bool = True
    neo4j: bool = True
    manifest: bool = True
    errors: list[str] = field(default_factory=list)


@dataclass
class GCResult:
    """Aggregate result of a GC run."""

    soft_deleted: int = 0
    hard_deleted: int = 0
    retention_purged: int = 0
    per_document: dict[str, StoreCleanupStatus] = field(default_factory=dict)
    dry_run: bool = False


@dataclass
class OrphanReport:
    """Orphan detection report (FR-3002)."""

    weaviate_orphans: list[str] = field(default_factory=list)
    minio_orphans: list[str] = field(default_factory=list)
    neo4j_orphans: list[str] = field(default_factory=list)
```

### 6.3 Sync Engine: `src/ingest/lifecycle/sync.py`

```python
# src/ingest/lifecycle/sync.py

"""Source-to-manifest diff engine (FR-3000).

The diff runs in O(n) time relative to max(source_count, manifest_count)
per NFR-3180, using set operations rather than nested loops.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.ingest.common.schemas import ManifestEntry
from src.ingest.common.utils import sha256_path
from src.ingest.lifecycle.schemas import SyncResult

logger = logging.getLogger("rag.ingest.lifecycle.sync")


def diff_sources(
    source_dir: Path,
    manifest: dict[str, ManifestEntry],
    allowed_suffixes: set[str],
    source_identity_fn: Any = None,
) -> SyncResult:
    """Compare source files against manifest entries (FR-3000).

    Args:
        source_dir: Root directory to scan for source files.
        manifest: Current manifest dict keyed by source_key.
        allowed_suffixes: Set of file suffixes to include (e.g., {".pdf", ".md"}).
        source_identity_fn: Callable that returns a SourceIdentity for a file
            path. If None, uses the default local_source_identity function.

    Returns:
        SyncResult with added, modified, deleted, and unchanged counts.
    """
    # Discover all source files and build source_key -> path mapping
    # Import here to avoid circular dependency
    from src.ingest.impl import _local_source_identity

    identity_fn = source_identity_fn or (
        lambda p: _local_source_identity(p, source_dir)
    )

    source_files = sorted(
        {
            path.resolve()
            for suffix in allowed_suffixes
            for path in source_dir.rglob(f"*{suffix}")
        }
    )

    source_key_map: dict[str, Path] = {}
    for path in source_files:
        identity = identity_fn(path)
        source_key_map[identity["source_key"]] = path

    # O(n) set operations
    source_keys = set(source_key_map.keys())
    manifest_keys = {
        k for k, v in manifest.items() if not v.get("deleted", False)
    }

    added = sorted(source_keys - manifest_keys)
    deleted = sorted(manifest_keys - source_keys)
    common = source_keys & manifest_keys

    modified: list[str] = []
    unchanged = 0

    for key in sorted(common):
        path = source_key_map[key]
        current_hash = sha256_path(path)
        existing_hash = manifest[key].get("content_hash", "")
        if current_hash != existing_hash:
            modified.append(key)
        else:
            unchanged += 1

    logger.info(
        "sync_diff added=%d modified=%d deleted=%d unchanged=%d",
        len(added),
        len(modified),
        len(deleted),
        unchanged,
    )

    return SyncResult(
        added=added,
        modified=modified,
        deleted=deleted,
        unchanged=unchanged,
    )
```

### 6.4 GC Engine: `src/ingest/lifecycle/gc.py`

```python
# src/ingest/lifecycle/gc.py

"""Four-store garbage collection and reconciliation engine (FR-3001).

Supports soft delete (default) and hard delete modes. Store-level failures
are isolated per NFR-3210 -- a failure in one store does not prevent
cleanup of remaining stores.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from src.ingest.common.schemas import ManifestEntry
from src.ingest.lifecycle.schemas import GCResult, StoreCleanupStatus

logger = logging.getLogger("rag.ingest.lifecycle.gc")


def reconcile_deleted(
    deleted_keys: list[str],
    manifest: dict[str, ManifestEntry],
    weaviate_client: Any,
    minio_client: Any | None,
    minio_bucket: str,
    neo4j_client: Any | None,
    mode: str = "soft",
    retention_days: int = 30,
    dry_run: bool = False,
) -> GCResult:
    """Remove or soft-delete data for deleted source_keys across all four stores.

    Args:
        deleted_keys: Source keys identified as deleted by the sync engine.
        manifest: Current manifest dict (will be mutated for soft deletes).
        weaviate_client: Weaviate client handle.
        minio_client: MinIO client handle. None if MinIO is not configured.
        minio_bucket: Target MinIO bucket.
        neo4j_client: Neo4j client handle. None if KG is not configured.
        mode: "soft" (default) or "hard".
        retention_days: Retention period for soft deletes.
        dry_run: If True, report actions without executing.

    Returns:
        GCResult with per-document status and aggregate counts.
    """
    result = GCResult(dry_run=dry_run)

    for source_key in deleted_keys:
        status = StoreCleanupStatus()

        if dry_run:
            result.per_document[source_key] = status
            if mode == "soft":
                result.soft_deleted += 1
            else:
                result.hard_deleted += 1
            continue

        # -- Weaviate cleanup --
        try:
            if mode == "soft":
                from src.vector_db import soft_delete_by_source_key

                soft_delete_by_source_key(weaviate_client, source_key)
            else:
                from src.vector_db import delete_by_source_key

                delete_by_source_key(weaviate_client, source_key)
            status.weaviate = True
        except Exception as exc:
            status.weaviate = False
            status.errors.append(f"weaviate: {exc}")
            logger.error(
                "gc_weaviate_failed source_key=%s mode=%s error=%s",
                source_key,
                mode,
                exc,
            )

        # -- MinIO cleanup --
        if minio_client is not None:
            try:
                from src.ingest.common.minio_clean_store import MinioCleanStore

                store = MinioCleanStore(minio_client, minio_bucket)
                if mode == "soft":
                    store.soft_delete(source_key)
                else:
                    store.delete(source_key)
                status.minio = True
            except Exception as exc:
                status.minio = False
                status.errors.append(f"minio: {exc}")
                logger.error(
                    "gc_minio_failed source_key=%s mode=%s error=%s",
                    source_key,
                    mode,
                    exc,
                )

        # -- Neo4j cleanup --
        if neo4j_client is not None:
            try:
                if mode == "soft":
                    neo4j_client.soft_delete_by_source_key(source_key)
                else:
                    neo4j_client.delete_by_source_key(source_key)
                status.neo4j = True
            except Exception as exc:
                status.neo4j = False
                status.errors.append(f"neo4j: {exc}")
                logger.error(
                    "gc_neo4j_failed source_key=%s mode=%s error=%s",
                    source_key,
                    mode,
                    exc,
                )

        # -- Manifest cleanup --
        try:
            if mode == "soft":
                now = datetime.now(timezone.utc).isoformat()
                manifest[source_key]["deleted"] = True
                manifest[source_key]["deleted_at"] = now
                result.soft_deleted += 1
            else:
                manifest.pop(source_key, None)
                result.hard_deleted += 1
            status.manifest = True
        except Exception as exc:
            status.manifest = False
            status.errors.append(f"manifest: {exc}")

        result.per_document[source_key] = status

        # Audit log (NFR-3221)
        logger.info(
            "gc_operation source_key=%s mode=%s weaviate=%s minio=%s neo4j=%s manifest=%s",
            source_key,
            mode,
            status.weaviate,
            status.minio,
            status.neo4j,
            status.manifest,
        )

    return result


def purge_expired(
    manifest: dict[str, ManifestEntry],
    weaviate_client: Any,
    minio_client: Any | None,
    minio_bucket: str,
    neo4j_client: Any | None,
    retention_days: int = 30,
) -> int:
    """Hard-delete soft-deleted entries past their retention period (FR-3022).

    Scans the manifest for entries where ``deleted == True`` and
    ``deleted_at`` is older than ``retention_days``. Each qualifying entry
    is hard-deleted from all four stores.

    Returns:
        Count of purged entries.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=retention_days)
    expired_keys: list[str] = []

    for key, entry in manifest.items():
        if not entry.get("deleted", False):
            continue
        deleted_at_str = entry.get("deleted_at", "")
        if not deleted_at_str:
            continue
        try:
            deleted_at = datetime.fromisoformat(deleted_at_str)
            if deleted_at < cutoff:
                expired_keys.append(key)
        except (ValueError, TypeError):
            logger.warning(
                "gc_purge_invalid_deleted_at source_key=%s deleted_at=%s",
                key,
                deleted_at_str,
            )

    if not expired_keys:
        return 0

    result = reconcile_deleted(
        deleted_keys=expired_keys,
        manifest=manifest,
        weaviate_client=weaviate_client,
        minio_client=minio_client,
        minio_bucket=minio_bucket,
        neo4j_client=neo4j_client,
        mode="hard",
    )

    logger.info(
        "gc_purge_expired purged=%d retention_days=%d",
        result.hard_deleted,
        retention_days,
    )
    return result.hard_deleted
```

### 6.5 Orphan Report: `src/ingest/lifecycle/orphan_report.py`

```python
# src/ingest/lifecycle/orphan_report.py

"""Orphan detection report (FR-3002).

Queries each store for source_keys absent from the manifest. Report-only,
no mutations.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from src.ingest.common.schemas import ManifestEntry
from src.ingest.lifecycle.schemas import OrphanReport

logger = logging.getLogger("rag.ingest.lifecycle.orphan_report")


def detect_orphans(
    manifest: dict[str, ManifestEntry],
    weaviate_client: Any,
    minio_client: Any | None,
    minio_bucket: str,
    neo4j_client: Any | None,
) -> OrphanReport:
    """Query each store for source_keys not present in the manifest.

    Args:
        manifest: Current manifest dict.
        weaviate_client: Weaviate client handle.
        minio_client: MinIO client handle (None if unconfigured).
        minio_bucket: Target MinIO bucket.
        neo4j_client: Neo4j/KG client handle (None if unconfigured).

    Returns:
        OrphanReport with per-store orphan lists.
    """
    manifest_keys = set(manifest.keys())
    report = OrphanReport()

    # -- Weaviate orphans --
    try:
        from src.vector_db import list_source_keys

        weaviate_keys = set(list_source_keys(weaviate_client))
        report.weaviate_orphans = sorted(weaviate_keys - manifest_keys)
    except Exception as exc:
        logger.warning("orphan_detect_weaviate_failed error=%s", exc)

    # -- MinIO orphans --
    if minio_client is not None:
        try:
            from src.ingest.common.minio_clean_store import MinioCleanStore

            store = MinioCleanStore(minio_client, minio_bucket)
            minio_keys = set(store.list_keys())
            report.minio_orphans = sorted(minio_keys - manifest_keys)
        except Exception as exc:
            logger.warning("orphan_detect_minio_failed error=%s", exc)

    # -- Neo4j orphans --
    if neo4j_client is not None:
        try:
            neo4j_keys = set(neo4j_client.list_source_keys())
            report.neo4j_orphans = sorted(neo4j_keys - manifest_keys)
        except Exception as exc:
            logger.warning("orphan_detect_neo4j_failed error=%s", exc)

    logger.info(
        "orphan_report weaviate=%d minio=%d neo4j=%d",
        len(report.weaviate_orphans),
        len(report.minio_orphans),
        len(report.neo4j_orphans),
    )
    return report
```

### 6.6 New Store Interface Methods

#### Weaviate: `src/vector_db/__init__.py`

```python
def soft_delete_by_source_key(client: Any, source_key: str) -> int:
    """Mark all chunks for source_key as deleted (set deleted=true property).

    Uses Weaviate batch partial-update to set the ``deleted`` boolean property
    to ``true`` on all chunks matching the source_key filter.

    Returns:
        Count of affected chunks.
    """
    ...  # Implementation uses Weaviate batch API with filter on source_key


def count_by_trace_id(client: Any, trace_id: str, collection: str | None = None) -> int:
    """Return count of chunks with the given trace_id.

    Used for E2E validation (FR-3060).
    """
    ...  # Implementation uses Weaviate aggregate query with filter on trace_id


def list_source_keys(client: Any, collection: str | None = None) -> list[str]:
    """Return all distinct source_key values in the collection.

    Used for orphan detection (FR-3002).
    """
    ...  # Implementation uses Weaviate aggregate groupBy on source_key
```

#### Knowledge Graph: `src/core/knowledge_graph.py`

```python
class KnowledgeGraphBuilder:
    # ... existing methods ...

    def delete_by_source_key(self, source_key: str) -> int:
        """Remove all triples with source_key provenance. Returns count."""
        ...

    def soft_delete_by_source_key(self, source_key: str) -> int:
        """Mark all triples with source_key provenance as deleted. Returns count."""
        ...

    def count_triples_by_trace_id(self, trace_id: str) -> int:
        """Return count of triples with the given trace_id. For E2E validation."""
        ...

    def list_source_keys(self) -> list[str]:
        """Return all distinct source_keys in the graph. For orphan detection."""
        ...
```

### 6.7 IngestionConfig GC Fields

Add to `src/ingest/common/types.py`:

```python
@dataclass
class IngestionConfig:
    # ... existing fields ...

    # -- GC / Lifecycle (Task 4) --
    gc_mode: str = "soft"
    """Default GC delete mode: "soft" (default) or "hard"."""
    gc_retention_days: int = 30
    """Retention period in days for soft-deleted data before hard deletion."""
    gc_schedule: str = ""
    """Cron expression for scheduled GC runs. Empty string disables."""
```

### 6.8 Settings: `config/settings.py`

```python
# -- Data Lifecycle GC --
RAG_GC_MODE: str = os.environ.get("RAG_GC_MODE", "soft")
RAG_GC_RETENTION_DAYS: int = int(os.environ.get("RAG_GC_RETENTION_DAYS", "30"))
RAG_GC_SCHEDULE: str = os.environ.get("RAG_GC_SCHEDULE", "")
```

### 6.9 On-Ingest Integration

Replace the inline GC logic in `ingest_directory()` (the `removed_sources` block) with
lifecycle module calls:

```python
# src/ingest/impl.py -- replace the existing removed_sources block

from src.ingest.lifecycle.sync import diff_sources
from src.ingest.lifecycle.gc import reconcile_deleted, purge_expired

# After all additions/modifications are processed:
if update and selected_sources is None:
    sync_result = diff_sources(documents_dir, manifest, allowed_suffixes)
    if sync_result.deleted:
        gc_result = reconcile_deleted(
            deleted_keys=sync_result.deleted,
            manifest=manifest,
            weaviate_client=client,
            minio_client=_db_client,
            minio_bucket=config.target_bucket,
            neo4j_client=runtime.kg_builder,
            mode=config.gc_mode,
            retention_days=config.gc_retention_days,
        )
        # Purge any expired soft-deleted entries
        purge_expired(
            manifest=manifest,
            weaviate_client=client,
            minio_client=_db_client,
            minio_bucket=config.target_bucket,
            neo4j_client=runtime.kg_builder,
            retention_days=config.gc_retention_days,
        )
```

### 6.10 IngestionRunSummary Extension

```python
@dataclass
class IngestionRunSummary:
    processed: int
    skipped: int
    failed: int
    stored_chunks: int
    removed_sources: int
    errors: list[str]
    design_warnings: list[str] = field(default_factory=list)
    # -- Data Lifecycle additions --
    gc_soft_deleted: int = 0
    gc_hard_deleted: int = 0
    gc_retention_purged: int = 0
```

---

## 7. Schema Migration Runner

**Design Task:** 5
**Spec Requirements:** FR-3100--FR-3113, NFR-3181, NFR-3211

### 7.1 Schema Changelog: `config/schema_changelog.yaml`

```yaml
# config/schema_changelog.yaml
#
# Machine-readable changelog mapping schema version transitions to
# migration strategies (FR-3113). The migration runner reads this file
# to determine the minimum-cost re-processing path for each document.
#
# migration_strategy values:
#   none           -- No action needed. Version transition has no schema impact.
#   metadata_only  -- Weaviate batch partial-update. No re-embedding. Cheap.
#   full_phase2    -- Full Embedding Pipeline re-run. GPU-bound. Expensive.
#   kg_reextract   -- Delete old triples, re-run KG extraction nodes. LLM-bound.

schema_versions:
  - version: "0.0.0"
    date: "2026-01-01"
    description: "Pre-versioning baseline. Documents ingested before schema tracking."
    migration_strategy: "none"

  - version: "1.0.0"
    date: "2026-04-15"
    description: >
      Initial versioned schema. Adds schema_version, trace_id, batch_id,
      deleted/deleted_at, validation, clean_hash to manifest. Adds
      schema_version, trace_id, batch_id, deleted to Weaviate chunk metadata.
      Adds MinIO clean store with metadata envelope.
    migration_strategy: "metadata_only"
```

### 7.2 Changelog Parser: `src/ingest/lifecycle/changelog.py`

```python
# src/ingest/lifecycle/changelog.py

"""Schema changelog parser and migration strategy resolver (FR-3113)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger("rag.ingest.lifecycle.changelog")

_STRATEGY_ORDER = {
    "none": 0,
    "metadata_only": 1,
    "kg_reextract": 2,
    "full_phase2": 3,
}


@dataclass(frozen=True)
class SchemaChange:
    """A single entry in the schema changelog."""

    version: str
    date: str
    description: str
    migration_strategy: str  # "none" | "metadata_only" | "full_phase2" | "kg_reextract"


def load_changelog(
    path: Path = Path("config/schema_changelog.yaml"),
) -> list[SchemaChange]:
    """Load and validate the schema changelog.

    Args:
        path: Path to the YAML changelog file.

    Returns:
        List of SchemaChange entries ordered by version.

    Raises:
        FileNotFoundError: If the changelog file does not exist.
        ValueError: If the file is malformed or entries are missing required fields.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "schema_versions" not in raw:
        raise ValueError(
            f"Changelog {path} must contain a 'schema_versions' key."
        )

    entries: list[SchemaChange] = []
    for item in raw["schema_versions"]:
        for required in ("version", "date", "description", "migration_strategy"):
            if required not in item:
                raise ValueError(
                    f"Changelog entry missing required field '{required}': {item}"
                )
        strategy = item["migration_strategy"]
        if strategy not in _STRATEGY_ORDER:
            raise ValueError(
                f"Unknown migration_strategy '{strategy}' in version "
                f"{item['version']}. Valid values: {sorted(_STRATEGY_ORDER.keys())}"
            )
        entries.append(
            SchemaChange(
                version=item["version"],
                date=item["date"],
                description=item["description"],
                migration_strategy=strategy,
            )
        )

    return entries


def determine_migration_strategy(
    from_version: str,
    to_version: str,
    changelog: list[SchemaChange],
) -> str:
    """Return the most expensive migration strategy needed for a version jump.

    Examines all changelog entries between ``from_version`` (exclusive) and
    ``to_version`` (inclusive). Returns the strategy with the highest cost
    rank among the intervening versions.

    Strategy cost order: none < metadata_only < kg_reextract < full_phase2.

    Args:
        from_version: Document's current schema version (e.g., "0.0.0").
        to_version: Target schema version (e.g., "1.0.0").
        changelog: Loaded changelog entries.

    Returns:
        Migration strategy string. Returns "none" if no intermediate
        versions require migration.
    """
    if from_version == to_version:
        return "none"

    max_rank = 0
    in_range = False

    for entry in changelog:
        if entry.version == from_version:
            in_range = True
            continue  # Skip the from_version itself
        if in_range:
            rank = _STRATEGY_ORDER.get(entry.migration_strategy, 0)
            max_rank = max(max_rank, rank)
        if entry.version == to_version:
            break

    # Reverse lookup
    for strategy, rank in _STRATEGY_ORDER.items():
        if rank == max_rank:
            return strategy

    return "none"
```

### 7.3 Migration Runner: `src/ingest/lifecycle/migration.py`

```python
# src/ingest/lifecycle/migration.py

"""Schema migration runner (FR-3110, FR-3111, FR-3112).

Selectively re-processes documents based on their schema version,
applying the minimum-cost migration strategy for each version gap.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import uuid4

from src.ingest.common.schemas import ManifestEntry, PIPELINE_SCHEMA_VERSION
from src.ingest.common.utils import save_manifest
from src.ingest.lifecycle.changelog import (
    SchemaChange,
    determine_migration_strategy,
    load_changelog,
)

logger = logging.getLogger("rag.ingest.lifecycle.migration")


@dataclass
class MigrationResult:
    """Summary of a migration run."""

    total_eligible: int = 0
    processed: int = 0
    failed: int = 0
    skipped: int = 0
    strategy_counts: dict[str, int] = field(default_factory=dict)


def run_migration(
    manifest: dict[str, ManifestEntry],
    target_version: str | None = None,
    dry_run: bool = False,
    runtime: Any | None = None,
    minio_clean_store: Any | None = None,
    weaviate_client: Any | None = None,
) -> MigrationResult:
    """Execute schema migration for all documents below target version.

    Idempotent: already-migrated documents are skipped (FR-3112).
    Resumable: interrupted migrations can be re-run safely (NFR-3211).

    Migration strategies (FR-3111):
      - metadata_only: Weaviate batch partial-update. No re-embedding.
      - full_phase2: Read clean markdown from MinIO, re-run Embedding Pipeline.
      - kg_reextract: Delete old triples, re-run KG extraction nodes.
      - none: No action. Skip.

    Args:
        manifest: Current manifest dict (will be mutated on success).
        target_version: Target schema version. None uses PIPELINE_SCHEMA_VERSION.
        dry_run: If True, report what would happen without modifying stores.
        runtime: Runtime container (needed for full_phase2 and kg_reextract).
        minio_clean_store: MinioCleanStore instance (needed to read clean MD
            for re-embedding or KG re-extraction).
        weaviate_client: Weaviate client handle (needed for metadata_only updates).

    Returns:
        MigrationResult with aggregate counts and per-strategy breakdown.
    """
    target = target_version or PIPELINE_SCHEMA_VERSION
    changelog = load_changelog()
    result = MigrationResult()

    # Identify eligible documents
    eligible: list[tuple[str, ManifestEntry, str]] = []
    for key, entry in manifest.items():
        if entry.get("deleted", False):
            continue
        doc_version = entry.get("schema_version", "0.0.0")
        if doc_version == target:
            result.skipped += 1
            continue
        strategy = determine_migration_strategy(doc_version, target, changelog)
        if strategy == "none":
            result.skipped += 1
            continue
        eligible.append((key, entry, strategy))

    result.total_eligible = len(eligible)

    if dry_run:
        for key, entry, strategy in eligible:
            result.strategy_counts[strategy] = (
                result.strategy_counts.get(strategy, 0) + 1
            )
        logger.info(
            "migration_dry_run target=%s eligible=%d strategies=%s",
            target,
            result.total_eligible,
            result.strategy_counts,
        )
        return result

    for key, entry, strategy in eligible:
        result.strategy_counts[strategy] = (
            result.strategy_counts.get(strategy, 0) + 1
        )

        try:
            if strategy == "metadata_only":
                _migrate_metadata_only(key, entry, target, weaviate_client)
            elif strategy == "full_phase2":
                _migrate_full_phase2(
                    key, entry, target, runtime, minio_clean_store
                )
            elif strategy == "kg_reextract":
                _migrate_kg_reextract(
                    key, entry, target, runtime, minio_clean_store
                )
            else:
                logger.warning(
                    "migration_unknown_strategy key=%s strategy=%s", key, strategy
                )
                result.failed += 1
                continue

            # Update manifest on success (NFR-3211: resumability)
            entry["schema_version"] = target
            result.processed += 1
            logger.info(
                "migration_success key=%s strategy=%s target=%s",
                key,
                strategy,
                target,
            )

        except Exception as exc:
            result.failed += 1
            logger.error(
                "migration_failed key=%s strategy=%s error=%s",
                key,
                strategy,
                exc,
            )

    return result


def _migrate_metadata_only(
    source_key: str,
    entry: ManifestEntry,
    target_version: str,
    weaviate_client: Any,
) -> None:
    """Weaviate batch partial-update for metadata-only migration.

    Updates schema_version (and any new metadata properties) on all chunks
    matching source_key. No re-embedding occurs.

    Target throughput: >= 100 docs/sec (NFR-3181).
    """
    # Use Weaviate batch API to update schema_version on all chunks
    # with matching source_key. Implementation depends on Weaviate
    # client version (v4 uses collection.data.update).
    from src.vector_db import batch_update_metadata_by_source_key

    batch_update_metadata_by_source_key(
        weaviate_client,
        source_key,
        properties={"schema_version": target_version},
    )


def _migrate_full_phase2(
    source_key: str,
    entry: ManifestEntry,
    target_version: str,
    runtime: Any,
    minio_clean_store: Any,
) -> None:
    """Full Phase 2 re-run using clean markdown from MinIO.

    Steps:
    1. Read clean markdown from MinIO clean store.
    2. Generate a new trace_id for this migration run.
    3. Delete existing Weaviate chunks for source_key.
    4. Run full Embedding Pipeline.
    5. Update manifest entry.
    """
    if minio_clean_store is None or runtime is None:
        raise RuntimeError(
            "full_phase2 migration requires both minio_clean_store and runtime"
        )

    text, meta = minio_clean_store.read(source_key)
    trace_id = str(uuid4())

    # Delete existing chunks
    from src.vector_db import delete_by_source_key

    delete_by_source_key(runtime.weaviate_client, source_key)

    # Re-run Phase 2
    from src.ingest.embedding import run_embedding_pipeline

    run_embedding_pipeline(
        runtime=runtime,
        source_key=source_key,
        source_name=meta.get("source_name", ""),
        source_uri=meta.get("source_uri", ""),
        source_id=meta.get("source_id", ""),
        connector=meta.get("connector", ""),
        source_version=meta.get("source_version", ""),
        clean_text=text,
        clean_hash=meta.get("clean_hash", ""),
        trace_id=trace_id,
    )

    # Update trace_id on the entry
    entry["trace_id"] = trace_id


def _migrate_kg_reextract(
    source_key: str,
    entry: ManifestEntry,
    target_version: str,
    runtime: Any,
    minio_clean_store: Any,
) -> None:
    """KG re-extraction: delete old triples and re-run KG extraction.

    Steps:
    1. Read clean markdown from MinIO.
    2. Delete existing triples for source_key.
    3. Re-run KG extraction nodes.
    4. Update manifest entry.
    """
    if minio_clean_store is None or runtime is None:
        raise RuntimeError(
            "kg_reextract migration requires both minio_clean_store and runtime"
        )

    text, meta = minio_clean_store.read(source_key)

    # Delete existing triples
    if runtime.kg_builder is not None:
        runtime.kg_builder.delete_by_source_key(source_key)

    # Re-run KG extraction
    # This invokes the KG extraction nodes directly (not the full pipeline).
    # The exact invocation depends on the node API.
    if runtime.kg_builder is not None:
        runtime.kg_builder.extract_from_text(
            text=text,
            source_key=source_key,
            source_name=meta.get("source_name", ""),
            trace_id=str(uuid4()),
        )
```

### 7.4 New Vector DB Method

Add to `src/vector_db/__init__.py`:

```python
def batch_update_metadata_by_source_key(
    client: Any,
    source_key: str,
    properties: dict[str, Any],
    collection: str | None = None,
) -> int:
    """Batch partial-update metadata properties on all chunks matching source_key.

    Used by the schema migration runner for metadata_only migrations.
    Target throughput: >= 100 docs/sec (NFR-3181).

    Returns:
        Count of updated chunks.
    """
    ...
```

---

## 8. E2E Validation Node

**Design Task:** 6
**Spec Requirements:** FR-3060, FR-3061, FR-3062

### 8.1 Module: `src/ingest/lifecycle/validation.py`

```python
# src/ingest/lifecycle/validation.py

"""End-to-end per-document store consistency validation (FR-3060).

Called after Phase 2 succeeds. Queries all enabled stores to verify they
received data for the document's trace_id and source_key. Records the
result in the manifest (FR-3061).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("rag.ingest.lifecycle.validation")


@dataclass
class ValidationResult:
    """Per-document E2E consistency validation result (FR-3061)."""

    validated_at: str = ""
    weaviate_ok: bool = False
    minio_ok: bool = False
    neo4j_ok: Optional[bool] = None  # None if KG disabled (FR-3062)
    consistent: bool = False

    def to_dict(self) -> dict:
        """Serialize for manifest storage."""
        return asdict(self)


def validate_document(
    trace_id: str,
    source_key: str,
    weaviate_client: Any,
    minio_client: Any | None,
    minio_bucket: str,
    neo4j_client: Any | None,
    kg_enabled: bool,
) -> ValidationResult:
    """Query all enabled stores to verify they received data for this trace_id.

    Checks (FR-3060):
    1. Weaviate: >= 1 chunk with trace_id
    2. MinIO: clean markdown object exists for source_key
    3. Neo4j: >= 1 triple with trace_id (if KG enabled)
    4. Manifest check is implicit (caller verifies)

    Disabled stores are reported as None, not False (FR-3062).
    Failure is logged but does NOT trigger retry (FR-3060 AC6).

    Args:
        trace_id: UUID v4 trace ID for this ingestion run.
        source_key: Stable source identity key.
        weaviate_client: Weaviate client handle.
        minio_client: MinIO client handle (None if unconfigured).
        minio_bucket: Target MinIO bucket.
        neo4j_client: KG builder handle (None if unconfigured).
        kg_enabled: Whether knowledge graph storage is enabled.

    Returns:
        ValidationResult with per-store booleans and overall consistency.
    """
    result = ValidationResult(
        validated_at=datetime.now(timezone.utc).isoformat(),
    )

    # -- Weaviate check --
    try:
        from src.vector_db import count_by_trace_id

        chunk_count = count_by_trace_id(weaviate_client, trace_id)
        result.weaviate_ok = chunk_count > 0
    except Exception as exc:
        result.weaviate_ok = False
        logger.warning(
            "validation_weaviate_failed trace_id=%s error=%s", trace_id, exc
        )

    # -- MinIO check --
    if minio_client is not None:
        try:
            from src.ingest.common.minio_clean_store import MinioCleanStore

            store = MinioCleanStore(minio_client, minio_bucket)
            result.minio_ok = store.exists(source_key)
        except Exception as exc:
            result.minio_ok = False
            logger.warning(
                "validation_minio_failed source_key=%s error=%s",
                source_key,
                exc,
            )
    else:
        # MinIO not configured -- treat as None (not a failure)
        result.minio_ok = True  # No MinIO to check

    # -- Neo4j check --
    if kg_enabled and neo4j_client is not None:
        try:
            triple_count = neo4j_client.count_triples_by_trace_id(trace_id)
            result.neo4j_ok = triple_count > 0
        except Exception as exc:
            result.neo4j_ok = False
            logger.warning(
                "validation_neo4j_failed trace_id=%s error=%s", trace_id, exc
            )
    else:
        result.neo4j_ok = None  # KG disabled (FR-3062)

    # -- Overall consistency --
    enabled_checks = [result.weaviate_ok, result.minio_ok]
    if result.neo4j_ok is not None:
        enabled_checks.append(result.neo4j_ok)
    result.consistent = all(enabled_checks)

    return result
```

### 8.2 Orchestrator Integration

Update `src/ingest/impl.py` -- `ingest_file()`, after Phase 2 succeeds:

```python
# src/ingest/impl.py -- after Phase 2 returns without errors

from src.ingest.lifecycle.validation import validate_document

# After Phase 2 succeeds:
validation_result = None
if not phase2.get("errors"):
    try:
        validation_result = validate_document(
            trace_id=trace_id,
            source_key=source_key,
            weaviate_client=runtime.weaviate_client,
            minio_client=runtime.db_client,
            minio_bucket=config.clean_store_bucket or config.target_bucket,
            neo4j_client=runtime.kg_builder,
            kg_enabled=config.enable_knowledge_graph_storage,
        )
        if not validation_result.consistent:
            logger.warning(
                "e2e_validation_inconsistent trace_id=%s source_key=%s "
                "weaviate=%s minio=%s neo4j=%s",
                trace_id,
                source_key,
                validation_result.weaviate_ok,
                validation_result.minio_ok,
                validation_result.neo4j_ok,
            )
    except Exception as exc:
        logger.warning(
            "e2e_validation_error trace_id=%s source_key=%s error=%s",
            trace_id,
            source_key,
            exc,
        )

return IngestFileResult(
    errors=phase2.get("errors", []),
    stored_count=phase2.get("stored_count", 0),
    metadata_summary=phase2.get("metadata_summary", ""),
    metadata_keywords=phase2.get("metadata_keywords", []),
    processing_log=(
        phase1.get("processing_log", []) + phase2.get("processing_log", [])
    ),
    source_hash=phase1.get("source_hash", ""),
    clean_hash=clean_hash,
    trace_id=trace_id,
    validation=validation_result.to_dict() if validation_result else {},
)
```

---

## 9. Configuration Reference

### 9.1 Environment Variables

| Variable | Default | Description | Task |
|----------|---------|-------------|------|
| `RAG_GC_MODE` | `"soft"` | Default GC delete mode: `soft` or `hard` | T4 |
| `RAG_GC_RETENTION_DAYS` | `30` | Retention period (days) before soft-deleted data is purged | T4 |
| `RAG_GC_SCHEDULE` | `""` | Cron expression for scheduled GC. Empty disables. | T4 |

### 9.2 IngestionConfig Fields (New)

| Field | Type | Default | Description | Task |
|-------|------|---------|-------------|------|
| `clean_store_bucket` | `str` | `""` | MinIO bucket for clean store. Empty reuses `target_bucket`. | T1 |
| `gc_mode` | `str` | `"soft"` | Default GC mode. | T4 |
| `gc_retention_days` | `int` | `30` | Soft-delete retention period in days. | T4 |
| `gc_schedule` | `str` | `""` | Cron schedule for automatic GC. | T4 |

### 9.3 IngestionConfig Fields (Removed)

| Field | Reason | Task |
|-------|--------|------|
| `persist_docling_document` | DoclingDocument no longer persisted (FR-3032) | T1 |

### 9.4 Constants

| Constant | Location | Value | Purpose |
|----------|----------|-------|---------|
| `PIPELINE_SCHEMA_VERSION` | `src/ingest/common/schemas.py` | `"1.0.0"` | Single source of truth for schema version | T2 |

### 9.5 Example `.env` Addition

```bash
# Data Lifecycle
RAG_GC_MODE=soft
RAG_GC_RETENTION_DAYS=30
RAG_GC_SCHEDULE=""
# RAG_GC_SCHEDULE="0 3 * * *"  # Example: daily at 3 AM
```

---

## 10. CLI Integration

### 10.1 GC Command (FR-3010)

```
aion ingest gc [OPTIONS]

Options:
  --dry-run                Report what would be deleted without modifying stores.
  --mode [soft|hard]       Delete mode. Default: soft.
  --retention-days INT     Override retention period for soft deletes. Default: 30.
  --confirm / --force      Required for hard delete mode (NFR-3230).
  --source-dir PATH        Source directory to scan. Default: configured documents_dir.

Examples:
  aion ingest gc --dry-run
  aion ingest gc --mode soft --retention-days 14
  aion ingest gc --mode hard --confirm
```

Implementation sketch:

```python
# src/cli/ingest.py or equivalent CLI module

import click

@click.command("gc")
@click.option("--dry-run", is_flag=True, help="Report only, no mutations.")
@click.option("--mode", type=click.Choice(["soft", "hard"]), default="soft")
@click.option("--retention-days", type=int, default=30)
@click.option("--confirm", is_flag=True, help="Confirm hard delete.")
@click.option("--force", is_flag=True, help="Skip confirmation.")
@click.option("--source-dir", type=click.Path(exists=True), default=None)
def gc_command(dry_run, mode, retention_days, confirm, force, source_dir):
    """Run garbage collection across all stores."""
    if mode == "hard" and not (confirm or force):
        click.echo(
            "Hard delete requires --confirm or --force. "
            "This operation is irreversible.",
            err=True,
        )
        raise SystemExit(1)

    from pathlib import Path
    from config.settings import DOCUMENTS_DIR
    from src.ingest.common.utils import load_manifest, save_manifest
    from src.ingest.impl import _normalize_manifest_entries
    from src.ingest.lifecycle.sync import diff_sources
    from src.ingest.lifecycle.gc import reconcile_deleted, purge_expired

    documents_dir = Path(source_dir) if source_dir else DOCUMENTS_DIR
    manifest = _normalize_manifest_entries(load_manifest())

    # Get allowed suffixes from config
    from config.settings import RAG_INGESTION_EXPORT_EXTENSIONS

    allowed_suffixes = {
        s.strip().lower()
        for s in RAG_INGESTION_EXPORT_EXTENSIONS.split(",")
        if s.strip()
    }

    sync_result = diff_sources(documents_dir, manifest, allowed_suffixes)
    click.echo(
        f"Sync: added={len(sync_result.added)} "
        f"modified={len(sync_result.modified)} "
        f"deleted={len(sync_result.deleted)} "
        f"unchanged={sync_result.unchanged}"
    )

    if not sync_result.deleted:
        click.echo("No deleted sources found. Nothing to GC.")
        return

    # Initialize store clients
    from src.vector_db import get_client as get_weaviate_client

    with get_weaviate_client() as weaviate_client:
        minio_client = None
        try:
            from src.db import create_persistent_client

            minio_client = create_persistent_client()
        except Exception:
            click.echo("Warning: MinIO client unavailable.", err=True)

        gc_result = reconcile_deleted(
            deleted_keys=sync_result.deleted,
            manifest=manifest,
            weaviate_client=weaviate_client,
            minio_client=minio_client,
            minio_bucket="",  # Uses default
            neo4j_client=None,  # TODO: wire when available
            mode=mode,
            retention_days=retention_days,
            dry_run=dry_run,
        )

        # Purge expired
        purged = 0
        if not dry_run:
            purged = purge_expired(
                manifest=manifest,
                weaviate_client=weaviate_client,
                minio_client=minio_client,
                minio_bucket="",
                neo4j_client=None,
                retention_days=retention_days,
            )
            save_manifest(manifest)

    click.echo(
        f"GC complete: soft_deleted={gc_result.soft_deleted} "
        f"hard_deleted={gc_result.hard_deleted} "
        f"retention_purged={purged} "
        f"dry_run={gc_result.dry_run}"
    )
```

### 10.2 Migration Command (FR-3110)

```
aion ingest migrate [OPTIONS]

Options:
  --dry-run                 Report eligible documents without processing.
  --target-version TEXT     Migrate to a specific version. Default: current.

Examples:
  aion ingest migrate --dry-run
  aion ingest migrate --target-version 1.0.0
```

Implementation sketch:

```python
@click.command("migrate")
@click.option("--dry-run", is_flag=True)
@click.option("--target-version", type=str, default=None)
def migrate_command(dry_run, target_version):
    """Run schema migration for documents below target version."""
    from src.ingest.common.utils import load_manifest, save_manifest
    from src.ingest.impl import _normalize_manifest_entries
    from src.ingest.lifecycle.migration import run_migration

    manifest = _normalize_manifest_entries(load_manifest())

    result = run_migration(
        manifest=manifest,
        target_version=target_version,
        dry_run=dry_run,
        # runtime and minio_clean_store initialized when not dry_run
    )

    click.echo(
        f"Migration: eligible={result.total_eligible} "
        f"processed={result.processed} "
        f"failed={result.failed} "
        f"skipped={result.skipped} "
        f"strategies={result.strategy_counts}"
    )

    if not dry_run:
        save_manifest(manifest)
```

### 10.3 Orphan Report Command (FR-3002)

```
aion ingest orphans

Examples:
  aion ingest orphans
```

Implementation sketch:

```python
@click.command("orphans")
def orphans_command():
    """Detect orphaned data across stores."""
    from src.ingest.common.utils import load_manifest
    from src.ingest.impl import _normalize_manifest_entries
    from src.ingest.lifecycle.orphan_report import detect_orphans

    manifest = _normalize_manifest_entries(load_manifest())

    from src.vector_db import get_client as get_weaviate_client

    with get_weaviate_client() as weaviate_client:
        minio_client = None
        try:
            from src.db import create_persistent_client

            minio_client = create_persistent_client()
        except Exception:
            pass

        report = detect_orphans(
            manifest=manifest,
            weaviate_client=weaviate_client,
            minio_client=minio_client,
            minio_bucket="",
            neo4j_client=None,
        )

    click.echo(f"Weaviate orphans: {len(report.weaviate_orphans)}")
    click.echo(f"MinIO orphans: {len(report.minio_orphans)}")
    click.echo(f"Neo4j orphans: {len(report.neo4j_orphans)}")

    if report.weaviate_orphans:
        click.echo(f"  Sample: {report.weaviate_orphans[:5]}")
    if report.minio_orphans:
        click.echo(f"  Sample: {report.minio_orphans[:5]}")
    if report.neo4j_orphans:
        click.echo(f"  Sample: {report.neo4j_orphans[:5]}")
```
