> **Document type:** Implementation document (Layer 5)
> **Upstream:** CROSS_DOCUMENT_DEDUP_DESIGN.md
> **Last updated:** 2026-04-15

# Cross-Document Deduplication — Implementation Guide (v1.0.0)

| Field | Value |
|-------|-------|
| **Document** | Cross-Document Deduplication Implementation Guide |
| **Version** | 1.0.0 |
| **Status** | Active |
| **Design Reference** | `CROSS_DOCUMENT_DEDUP_DESIGN.md` v1.0.0 (Tasks 3.1–3.7) |
| **Spec Reference** | `CROSS_DOCUMENT_DEDUP_SPEC.md` v1.0.0 (FR-3400–FR-3461, NFR-3500–NFR-3504) |
| **Companion Documents** | `CROSS_DOCUMENT_DEDUP_SPEC.md`, `CROSS_DOCUMENT_DEDUP_DESIGN.md`, `EMBEDDING_PIPELINE_IMPLEMENTATION.md`, `EMBEDDING_PIPELINE_DESIGN.md` |
| **Created** | 2026-04-15 |
| **Last Updated** | 2026-04-15 |

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-04-15 | Initial implementation guide. Covers dedup node, content hash engine, MinHash engine, Weaviate schema changes, merge reporting, revert/override, pipeline integration, and full configuration reference. |

---

## 1. Implementation Overview

This document is the implementation source-of-truth for the cross-document deduplication subsystem. It translates the task decomposition in `CROSS_DOCUMENT_DEDUP_DESIGN.md` into concrete module layouts, function signatures, code patterns, and integration steps.

**Scope:** The dedup node is inserted into the Embedding Pipeline DAG between `quality_validation` and `embedding_storage`. It detects chunks whose content duplicates content already stored in Weaviate from prior ingestion runs, eliminates the duplicate, and maintains a back-reference array (`source_documents`) on the canonical chunk for multi-document provenance.

**Implementation approach:**

- Tier 1 (default): SHA-256 content hash of normalised text for exact-match detection. Near-zero computational cost. Always active when cross-document dedup is enabled.
- Tier 2 (opt-in): MinHash locality-sensitive hashing for near-duplicate detection at configurable similarity thresholds. Activated via `enable_fuzzy_dedup`.

**Critical path:** Content Hash Infrastructure -> Dedup Node -> Pipeline DAG Integration (minimum viable Tier 1).

**Full path:** Content Hash + MinHash + Weaviate Schema -> Dedup Node -> Merge Report + Revert + DAG Integration.

---

## 2. Module Layout

```
src/ingest/embedding/
├── common/
│   ├── types.py                        # MergeEvent TypedDict (extended)
│   └── dedup_utils.py                  # Content hash + normalisation helpers
├── nodes/
│   ├── cross_document_dedup.py         # Dedup node (core)
│   ├── embedding_storage.py            # Updated to persist dedup metadata
│   └── ...                             # Existing nodes unchanged
├── state.py                            # EmbeddingPipelineState (extended)
└── workflow.py                         # DAG wiring (edge update)

src/ingest/embedding/support/
└── minhash_engine.py                   # MinHash fingerprint engine (Tier 2)

src/vector_db/
└── ...                                 # ensure_collection updated for new schema properties

tests/ingest/embedding/
├── test_cross_document_dedup.py        # Dedup node unit tests
├── test_content_hash.py                # Hash + normalisation unit tests
├── test_minhash_engine.py              # MinHash unit + threshold tests
└── test_dedup_integration.py           # End-to-end with Weaviate test collection
```

---

## 3. Dedup Node Implementation

**File:** `src/ingest/embedding/nodes/cross_document_dedup.py`
**Design task:** 3.1
**Requirements:** FR-3400, FR-3401, FR-3402, FR-3403, FR-3413, FR-3433, FR-3450, NFR-3504

### 3.1 Node Function Skeleton

```python
"""Cross-document deduplication node for the Embedding Pipeline."""

from __future__ import annotations

import logging
from typing import Any

from src.ingest.common import append_processing_log
from src.ingest.embedding.common.dedup_utils import (
    compute_content_hash,
    find_chunk_by_content_hash,
    append_source_document,
    remove_source_document_refs,
)
from src.ingest.embedding.common.types import MergeEvent, create_merge_event
from src.ingest.embedding.state import EmbeddingPipelineState

logger = logging.getLogger("rag.ingest.embedding.dedup")


def cross_document_dedup_node(state: EmbeddingPipelineState) -> dict[str, Any]:
    """Detect and eliminate cross-document duplicate chunks.

    For each chunk surviving quality validation:
    1. Compute content hash (Tier 1).
    2. Query Weaviate for exact-match on content_hash.
    3. If match: append source_key to canonical chunk's source_documents,
       record merge event, remove chunk from output list.
    4. If no match and Tier 2 enabled: compute MinHash fingerprint,
       query for fuzzy match above threshold.
    5. If no match at all: attach content_hash (and optionally
       fuzzy_fingerprint) to chunk metadata for downstream storage.

    Args:
        state: Embedding pipeline state after quality_validation.

    Returns:
        Partial state update with deduplicated chunks, merge report,
        dedup stats, and updated processing log.
    """
    config = state["runtime"].config
    chunks = state["chunks"]

    # --- Bypass path (FR-3402) ---
    if not getattr(config, "enable_cross_document_dedup", True):
        return {
            "chunks": chunks,
            "dedup_merge_report": [],
            "dedup_stats": {},
            "processing_log": append_processing_log(
                state, "cross_document_dedup:skipped"
            ),
        }

    runtime = state["runtime"]
    client = runtime.weaviate_client
    source_key = state["source_key"]

    merge_report: list[dict[str, Any]] = []
    novel_chunks = []
    exact_matches = 0
    fuzzy_matches = 0
    degraded = False

    try:
        # --- Re-ingestion back-reference cleanup (FR-3433) ---
        if runtime.config.update_mode:
            remove_source_document_refs(client, source_key)

        # --- Per-source override check (FR-3450) ---
        override_sources = getattr(config, "dedup_override_sources", [])
        skip_lookup = source_key in override_sources

        for chunk in chunks:
            content_hash = compute_content_hash(chunk.text)
            chunk.metadata["content_hash"] = content_hash

            if skip_lookup:
                # Override: store independently but still compute hash
                chunk.metadata.setdefault("source_documents", [source_key])
                novel_chunks.append(chunk)
                continue

            # --- Tier 1: exact content-hash match (FR-3411) ---
            existing = find_chunk_by_content_hash(client, content_hash)
            if existing is not None:
                append_source_document(client, existing["uuid"], source_key)
                merge_report.append(
                    create_merge_event(
                        canonical_content_hash=content_hash,
                        canonical_chunk_id=existing["uuid"],
                        merged_source_key=source_key,
                        merged_section=chunk.metadata.get("heading_path", ""),
                        match_tier="exact",
                        similarity_score=1.0,
                        canonical_replaced=False,
                    )
                )
                exact_matches += 1
                continue

            # --- Tier 2: fuzzy fingerprint match (FR-3420–FR-3424) ---
            if getattr(config, "enable_fuzzy_dedup", False):
                fuzzy_match = _try_fuzzy_dedup(
                    client, chunk, content_hash, source_key,
                    config, merge_report,
                )
                if fuzzy_match:
                    fuzzy_matches += 1
                    continue

            # --- Novel chunk: pass through ---
            chunk.metadata.setdefault("source_documents", [source_key])
            novel_chunks.append(chunk)

    except Exception:
        logger.exception("cross_document_dedup degraded — passing remaining chunks through")
        degraded = True
        # Pass through any chunks not yet processed
        novel_chunks = chunks

    dedup_stats = {
        "total_input_chunks": len(chunks),
        "exact_matches": exact_matches,
        "fuzzy_matches": fuzzy_matches,
        "novel_chunks": len(novel_chunks),
        "degraded": degraded,
    }

    log_tag = "cross_document_dedup:degraded" if degraded else "cross_document_dedup:ok"
    return {
        "chunks": novel_chunks,
        "dedup_merge_report": merge_report,
        "dedup_stats": dedup_stats,
        "processing_log": append_processing_log(state, log_tag),
    }
```

### 3.2 Tier 2 Helper (Private)

```python
def _try_fuzzy_dedup(
    client,
    chunk,
    content_hash: str,
    source_key: str,
    config,
    merge_report: list[dict[str, Any]],
) -> bool:
    """Attempt Tier 2 fuzzy fingerprint dedup. Returns True if merged."""
    from src.ingest.embedding.support.minhash_engine import (
        compute_fuzzy_fingerprint,
        find_chunk_by_fuzzy_fingerprint,
    )

    threshold = getattr(config, "fuzzy_similarity_threshold", 0.95)
    shingle_size = getattr(config, "fuzzy_shingle_size", 3)
    num_hashes = getattr(config, "fuzzy_num_hashes", 128)

    fingerprint = compute_fuzzy_fingerprint(
        chunk.text, shingle_size=shingle_size, num_hashes=num_hashes
    )
    chunk.metadata["fuzzy_fingerprint"] = fingerprint

    match = find_chunk_by_fuzzy_fingerprint(client, fingerprint, threshold)
    if match is None:
        chunk.metadata.setdefault("source_documents", [source_key])
        return False

    # Canonical selection: longer chunk wins (FR-3424)
    canonical_replaced = False
    if len(chunk.text) > match.get("text_length", 0):
        _replace_canonical(client, match["uuid"], chunk, content_hash, fingerprint)
        canonical_replaced = True

    append_source_document(client, match["uuid"], source_key)
    merge_report.append(
        create_merge_event(
            canonical_content_hash=content_hash,
            canonical_chunk_id=match["uuid"],
            merged_source_key=source_key,
            merged_section=chunk.metadata.get("heading_path", ""),
            match_tier="fuzzy",
            similarity_score=match["similarity"],
            canonical_replaced=canonical_replaced,
        )
    )
    return True


def _replace_canonical(client, chunk_uuid: str, chunk, content_hash: str, fingerprint: str):
    """Replace a canonical chunk's content when the incoming chunk is longer."""
    from src.vector_db import update_chunk_content

    update_chunk_content(
        client,
        chunk_uuid,
        text=chunk.text,
        content_hash=content_hash,
        fuzzy_fingerprint=fingerprint,
    )
```

---

## 4. Content Hash Engine

**File:** `src/ingest/embedding/common/dedup_utils.py`
**Design task:** 3.2
**Requirements:** FR-3410, FR-3411, FR-3412

```python
"""Content hash infrastructure for cross-document deduplication (Tier 1)."""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Optional

logger = logging.getLogger("rag.ingest.embedding.dedup_utils")

_WHITESPACE_RE = re.compile(r"\s+")


def normalise_chunk_text(text: str) -> str:
    """Normalise chunk text for hash computation.

    Strips leading/trailing whitespace, collapses interior whitespace
    sequences to a single ASCII space. Case is preserved (FR-3410).

    >>> normalise_chunk_text("  Hello   World\\n")
    'Hello World'
    >>> normalise_chunk_text("Hello World")
    'Hello World'
    """
    return _WHITESPACE_RE.sub(" ", text.strip())


def compute_content_hash(text: str) -> str:
    """Compute SHA-256 content hash of normalised text.

    Returns a lowercase hex string (64 characters).

    Contract: normalise_chunk_text("  Hello   World\\n") and
    normalise_chunk_text("Hello World") produce identical hashes.
    "Hello World" and "hello world" produce different hashes (FR-3410 AC-2).
    """
    normalised = normalise_chunk_text(text)
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def find_chunk_by_content_hash(
    client, content_hash: str
) -> Optional[dict[str, Any]]:
    """Query Weaviate for a chunk with matching content_hash.

    Returns dict with 'uuid', 'source_documents', 'text_length' on match,
    or None if no match or transient error (FR-3411 AC-3).
    """
    try:
        collection = client.collections.get("Chunk")
        result = collection.query.fetch_objects(
            filters=Filter.by_property("content_hash").equal(content_hash),
            limit=1,
            return_properties=["content_hash", "source_documents", "text"],
        )
        if not result.objects:
            return None
        obj = result.objects[0]
        return {
            "uuid": str(obj.uuid),
            "source_documents": obj.properties.get("source_documents", []),
            "text_length": len(obj.properties.get("text", "")),
        }
    except Exception:
        logger.warning(
            "Weaviate lookup failed for content_hash=%s; treating as novel",
            content_hash[:16],
            exc_info=True,
        )
        return None


def append_source_document(
    client, chunk_uuid: str, source_key: str
) -> bool:
    """Append source_key to a canonical chunk's source_documents array.

    Deduplicates: does not append if already present (FR-3431 AC-2).
    Returns True on success, False on failure (FR-3431 AC-4).
    """
    try:
        collection = client.collections.get("Chunk")
        obj = collection.query.fetch_object_by_id(
            chunk_uuid, return_properties=["source_documents"]
        )
        existing = obj.properties.get("source_documents", [])
        if source_key in existing:
            return True  # already present, no-op

        existing.append(source_key)
        collection.data.update(
            uuid=chunk_uuid,
            properties={"source_documents": existing},
        )
        return True
    except Exception:
        logger.error(
            "Failed to append source_document %s to chunk %s",
            source_key, chunk_uuid, exc_info=True,
        )
        return False


def remove_source_document_refs(client, source_key: str) -> None:
    """Remove source_key from all chunks' source_documents arrays.

    Chunks whose source_documents becomes empty are deleted (FR-3433 AC-3).
    Called during re-ingestion before dedup processing.
    """
    try:
        collection = client.collections.get("Chunk")
        # Query all chunks referencing this source_key
        results = collection.query.fetch_objects(
            filters=Filter.by_property("source_documents").contains_any(
                [source_key]
            ),
            limit=10_000,
            return_properties=["source_documents"],
        )
        for obj in results.objects:
            sources = obj.properties.get("source_documents", [])
            updated = [s for s in sources if s != source_key]
            if not updated:
                collection.data.delete_by_id(obj.uuid)
            else:
                collection.data.update(
                    uuid=obj.uuid,
                    properties={"source_documents": updated},
                )
    except Exception:
        logger.error(
            "Failed to clean source_document refs for %s", source_key,
            exc_info=True,
        )
```

---

## 5. MinHash Fingerprint Engine

**File:** `src/ingest/embedding/support/minhash_engine.py`
**Design task:** 3.3
**Requirements:** FR-3420, FR-3421, FR-3422, FR-3423, FR-3424, NFR-3502

```python
"""MinHash fingerprint engine for Tier 2 fuzzy deduplication."""

from __future__ import annotations

import logging
from typing import Optional

from datasketch import MinHash

from src.ingest.embedding.common.dedup_utils import normalise_chunk_text

logger = logging.getLogger("rag.ingest.embedding.minhash")


def _word_shingles(text: str, shingle_size: int = 3) -> list[str]:
    """Generate word-level shingles (contiguous n-grams of words).

    >>> _word_shingles("the quick brown fox", 3)
    ['the quick brown', 'quick brown fox']
    """
    words = text.split()
    if len(words) < shingle_size:
        return [" ".join(words)] if words else []
    return [
        " ".join(words[i : i + shingle_size])
        for i in range(len(words) - shingle_size + 1)
    ]


def compute_fuzzy_fingerprint(
    text: str,
    shingle_size: int = 3,
    num_hashes: int = 128,
) -> str:
    """Compute a MinHash fingerprint for the given text.

    Returns a hex-encoded string of the MinHash signature (FR-3421).
    """
    normalised = normalise_chunk_text(text)
    shingles = _word_shingles(normalised, shingle_size)

    mh = MinHash(num_perm=num_hashes)
    for shingle in shingles:
        mh.update(shingle.encode("utf-8"))

    # Serialise hash values to hex string
    return mh.hashvalues.tobytes().hex()


def _deserialise_minhash(hex_str: str, num_hashes: int = 128) -> MinHash:
    """Reconstruct a MinHash object from a hex-encoded signature."""
    import numpy as np

    hash_bytes = bytes.fromhex(hex_str)
    hash_values = np.frombuffer(hash_bytes, dtype=np.uint64)
    mh = MinHash(num_perm=num_hashes)
    mh.hashvalues = hash_values
    return mh


def estimate_similarity(sig_a: str, sig_b: str, num_hashes: int = 128) -> float:
    """Estimate Jaccard similarity between two MinHash signatures.

    Returns a float in [0.0, 1.0].
    """
    mh_a = _deserialise_minhash(sig_a, num_hashes)
    mh_b = _deserialise_minhash(sig_b, num_hashes)
    return mh_a.jaccard(mh_b)


def find_chunk_by_fuzzy_fingerprint(
    client,
    fingerprint: str,
    threshold: float,
    num_hashes: int = 128,
) -> Optional[dict]:
    """Find the best fuzzy match above threshold in Weaviate.

    For v1, this scans stored fingerprints via Weaviate query rather than
    maintaining a dedicated LSH forest index. Acceptable for corpora under
    100K chunks (see design OQ-1 resolution).

    Returns dict with 'uuid', 'similarity', 'text_length' on match,
    or None if no match found or on error.
    """
    try:
        collection = client.collections.get("Chunk")
        results = collection.query.fetch_objects(
            filters=Filter.by_property("fuzzy_fingerprint").is_not_none(),
            limit=10_000,
            return_properties=["fuzzy_fingerprint", "text", "source_documents"],
        )

        best_match = None
        best_similarity = 0.0

        for obj in results.objects:
            stored_fp = obj.properties.get("fuzzy_fingerprint")
            if not stored_fp:
                continue
            sim = estimate_similarity(fingerprint, stored_fp, num_hashes)
            if sim >= threshold and sim > best_similarity:
                best_similarity = sim
                best_match = {
                    "uuid": str(obj.uuid),
                    "similarity": sim,
                    "text_length": len(obj.properties.get("text", "")),
                }

        return best_match

    except Exception:
        logger.warning(
            "Fuzzy fingerprint lookup failed; treating chunk as novel",
            exc_info=True,
        )
        return None
```

---

## 6. Weaviate Schema Changes

**Design task:** 3.4
**Requirements:** FR-3430, FR-3431, FR-3432, FR-3433, NFR-3500, NFR-3503

### 6.1 Schema Property Additions

The following properties are added to the chunk object schema in `ensure_collection()`:

```python
# In src/vector_db/ — additions to ensure_collection()

import weaviate.classes.config as wvc

# --- New properties for cross-document dedup ---
new_properties = [
    wvc.Property(
        name="content_hash",
        data_type=wvc.DataType.TEXT,
        description="SHA-256 of normalised chunk text for exact-match dedup",
        indexing=wvc.PropertyIndexing(
            filterable=True,    # Inverted index for fast exact-match queries
            searchable=False,   # Not needed for BM25/text search
        ),
    ),
    wvc.Property(
        name="source_documents",
        data_type=wvc.DataType.TEXT_ARRAY,
        description="Array of source_key values for multi-document provenance",
    ),
    wvc.Property(
        name="fuzzy_fingerprint",
        data_type=wvc.DataType.TEXT,
        description="Serialised MinHash signature (Tier 2 fuzzy dedup)",
        indexing=wvc.PropertyIndexing(
            filterable=False,   # Compared via deserialization, not filter
            searchable=False,
        ),
    ),
    wvc.Property(
        name="canonical",
        data_type=wvc.DataType.BOOL,
        description="Always true; reserved for future soft-delete flows",
    ),
]
```

### 6.2 embedding_storage_node Update

The `embedding_storage_node` must persist dedup metadata from chunk metadata:

```python
# In embedding_storage_node — when constructing DocumentRecord objects:

records = [
    DocumentRecord(
        text=text,
        embedding=vector,
        metadata={
            **chunk.metadata,
            # Ensure dedup properties are included
            "content_hash": chunk.metadata.get("content_hash"),
            "source_documents": chunk.metadata.get(
                "source_documents", [state["source_key"]]
            ),
            "fuzzy_fingerprint": chunk.metadata.get("fuzzy_fingerprint"),
            "canonical": True,
        },
    )
    for text, vector, chunk in zip(texts, vectors, state["chunks"])
]
```

### 6.3 Migration Handling

- `ensure_collection()` handles both fresh creation (new schema includes all properties) and existing-collection upgrade (adding new properties to an existing schema).
- Existing chunks without `source_documents` are treated as having an implicit `[source_key]`. The dedup node initialises this on first access if needed.
- No backfill of `content_hash` for existing chunks is required for v1. Tier 1 dedup only catches duplicates of chunks ingested after the feature is enabled.

---

## 7. Merge Report System

**Design task:** 3.5
**Requirements:** FR-3440, FR-3441, FR-3442, SC-3510

### 7.1 MergeEvent TypedDict

```python
# In src/ingest/embedding/common/types.py

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, TypedDict


class MergeEvent(TypedDict):
    """A single deduplication merge event record.

    Conforms to FR-3440 schema. No full chunk text is included (SC-3510).
    """
    canonical_content_hash: str    # SHA-256 hex of canonical chunk
    canonical_chunk_id: str        # Weaviate UUID
    merged_source_key: str         # source_key of the merged document
    merged_section: str            # section path from chunk metadata
    match_tier: str                # "exact" or "fuzzy"
    similarity_score: float        # 1.0 for exact, Jaccard estimate for fuzzy
    canonical_replaced: bool       # true if canonical was replaced (Tier 2)
    timestamp: str                 # ISO 8601


def create_merge_event(
    *,
    canonical_content_hash: str,
    canonical_chunk_id: str,
    merged_source_key: str,
    merged_section: str,
    match_tier: str,
    similarity_score: float,
    canonical_replaced: bool,
) -> MergeEvent:
    """Construct a MergeEvent with the current ISO 8601 timestamp."""
    return MergeEvent(
        canonical_content_hash=canonical_content_hash,
        canonical_chunk_id=canonical_chunk_id,
        merged_source_key=merged_source_key,
        merged_section=str(merged_section),
        match_tier=match_tier,
        similarity_score=similarity_score,
        canonical_replaced=canonical_replaced,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
```

### 7.2 Report Persistence

Add `dedup_merge_report` and `dedup_stats` to `EmbeddingResult` in `src/ingest/temporal/activities.py`:

```python
@dataclass
class EmbeddingResult:
    stored_count: int
    errors: list
    processing_log: list
    # --- Dedup extensions (FR-3441) ---
    dedup_merge_report: list = field(default_factory=list)
    dedup_stats: dict = field(default_factory=dict)
```

### 7.3 CLI Summary Line

Update CLI ingestion output to display a dedup summary (FR-3442):

```python
# In CLI output handler, after ingestion completes:
stats = result.dedup_stats
if stats:
    print(
        f"Dedup: {stats.get('exact_matches', 0)} exact, "
        f"{stats.get('fuzzy_matches', 0)} fuzzy, "
        f"{stats.get('novel_chunks', 0)} novel"
    )
```

---

## 8. Revert/Override Implementation

**Design task:** 3.6
**Requirements:** FR-3450, FR-3451, FR-3452, SC-3511

### 8.1 Override at Ingest Time

The dedup node checks `config.dedup_override_sources` (see Section 3.1, per-source override check). When a source is overridden:

- All chunks are stored independently (no dedup lookup).
- `content_hash` is still computed and attached for future reference.
- The override is persisted in the document's manifest entry for subsequent re-ingestion.

### 8.2 CLI/API Override Parameter

```python
# CLI: --dedup-override flag
@click.option("--dedup-override", is_flag=True, default=False,
              help="Exempt this source from cross-document deduplication")
def ingest(source_path: str, dedup_override: bool, ...):
    if dedup_override:
        config.dedup_override_sources.append(source_key)
    ...

# API: dedup_override parameter on /ingest endpoint
@router.post("/ingest")
async def ingest_endpoint(request: IngestRequest):
    if request.dedup_override:
        config.dedup_override_sources.append(request.source_key)
    ...
```

### 8.3 Targeted Revert Operation

```python
def revert_merge(
    client,
    source_key: str,
    canonical_content_hash: str,
) -> bool:
    """Revert a specific dedup merge by removing source_key from the
    canonical chunk's source_documents and re-ingesting the affected chunk.

    Idempotent: if source_key is not in source_documents, this is a no-op
    (FR-3451 AC-5).

    Args:
        client: Weaviate client.
        source_key: Source document to detach.
        canonical_content_hash: Content hash of the canonical chunk.

    Returns:
        True if a revert was performed, False if no-op.
    """
    chunk = find_chunk_by_content_hash(client, canonical_content_hash)
    if chunk is None:
        logger.warning(
            "revert_merge: no chunk found for hash %s",
            canonical_content_hash[:16],
        )
        return False

    sources = chunk.get("source_documents", [])
    if source_key not in sources:
        logger.info(
            "revert_merge: source_key %s not in source_documents, no-op",
            source_key,
        )
        return False

    # Remove source_key from canonical chunk
    updated = [s for s in sources if s != source_key]
    collection = client.collections.get("Chunk")

    if not updated:
        collection.data.delete_by_id(chunk["uuid"])
    else:
        collection.data.update(
            uuid=chunk["uuid"],
            properties={"source_documents": updated},
        )

    # Log audit event (SC-3511)
    logger.info(
        "revert_merge completed source_key=%s canonical_hash=%s",
        source_key, canonical_content_hash[:16],
    )
    return True
```

### 8.4 Revert via Re-Ingestion

Document-level re-ingestion with `dedup_override=true` is supported by the combination of:
1. Re-ingestion back-reference cleanup (Section 3.1, FR-3433).
2. Override check (Section 3.1, FR-3450).

When re-ingesting with override, all old back-references are cleaned and all new chunks are stored independently.

---

## 9. Pipeline Integration

**Design task:** 3.7
**Requirements:** FR-3400, FR-3403

### 9.1 State Extension

```python
# In src/ingest/embedding/state.py — additions to EmbeddingPipelineState

class EmbeddingPipelineState(TypedDict, total=False):
    # ... existing fields ...

    # --- Cross-document dedup extensions (FR-3403) ---
    dedup_merge_report: list[dict[str, Any]]
    dedup_stats: dict[str, int]
```

### 9.2 DAG Modification

```python
# In src/ingest/embedding/workflow.py — build_embedding_pipeline_graph()

from src.ingest.embedding.nodes.cross_document_dedup import cross_document_dedup_node

def build_embedding_pipeline_graph():
    graph = StateGraph(EmbeddingPipelineState)

    # ... existing node registrations ...
    graph.add_node("cross_document_dedup", cross_document_dedup_node)

    # Replace: quality_validation -> embedding_storage
    # With:    quality_validation -> cross_document_dedup -> embedding_storage
    graph.add_edge("quality_validation", "cross_document_dedup")
    graph.add_edge("cross_document_dedup", "embedding_storage")
    # Remove the old direct edge (quality_validation -> embedding_storage)

    # ... rest of graph construction ...
```

### 9.3 Configuration Propagation

Ensure all dedup config keys are present in `IngestionConfig`:

```python
# In src/ingest/common/types.py — IngestionConfig additions

@dataclass
class IngestionConfig:
    # ... existing fields ...

    # --- Cross-document dedup (FR-3460) ---
    enable_cross_document_dedup: bool = True
    enable_fuzzy_dedup: bool = False
    fuzzy_similarity_threshold: float = 0.95
    fuzzy_shingle_size: int = 3
    fuzzy_num_hashes: int = 128
    dedup_override_sources: list[str] = field(default_factory=list)
```

---

## 10. Configuration Reference

| Key | Type | Default | Env Override | FR |
|-----|------|---------|-------------|-----|
| `enable_cross_document_dedup` | `bool` | `True` | `RAGWEAVE_ENABLE_CROSS_DOC_DEDUP` | FR-3402, FR-3460 |
| `enable_fuzzy_dedup` | `bool` | `False` | `RAGWEAVE_ENABLE_FUZZY_DEDUP` | FR-3420, FR-3460 |
| `fuzzy_similarity_threshold` | `float` | `0.95` | `RAGWEAVE_FUZZY_THRESHOLD` | FR-3422, FR-3460 |
| `fuzzy_shingle_size` | `int` | `3` | `RAGWEAVE_FUZZY_SHINGLE_SIZE` | FR-3421, FR-3460 |
| `fuzzy_num_hashes` | `int` | `128` | `RAGWEAVE_FUZZY_NUM_HASHES` | FR-3421, FR-3460 |
| `dedup_override_sources` | `list[str]` | `[]` | N/A (per-run) | FR-3450 |

**Validation rules:**

- `fuzzy_similarity_threshold` must be in `[0.0, 1.0]`. Fail fast with clear error on violation.
- `fuzzy_shingle_size` must be >= 1.
- `fuzzy_num_hashes` must be >= 16.
- `enable_fuzzy_dedup=True` requires `enable_cross_document_dedup=True`; if cross-doc dedup is disabled, fuzzy dedup is silently skipped (FR-3420 AC-3).

---

## Task-to-Requirement Mapping

| Section | Design Task | Requirements Covered |
|---------|-------------|---------------------|
| 3. Dedup Node | 3.1 | FR-3400, FR-3401, FR-3402, FR-3403, FR-3413, FR-3433, FR-3450, NFR-3504 |
| 4. Content Hash Engine | 3.2 | FR-3410, FR-3411, FR-3412 |
| 5. MinHash Engine | 3.3 | FR-3420, FR-3421, FR-3422, FR-3423, FR-3424, NFR-3502 |
| 6. Weaviate Schema | 3.4 | FR-3430, FR-3431, FR-3432, FR-3433, NFR-3500, NFR-3503 |
| 7. Merge Report | 3.5 | FR-3440, FR-3441, FR-3442, SC-3510 |
| 8. Revert/Override | 3.6 | FR-3450, FR-3451, FR-3452, SC-3511 |
| 9. Pipeline Integration | 3.7 | FR-3400, FR-3403 |

---

## Companion Documents

| Document | Role |
|----------|------|
| `CROSS_DOCUMENT_DEDUP_SPEC.md` | Authoritative requirements (FR-3400–FR-3461) |
| `CROSS_DOCUMENT_DEDUP_DESIGN.md` | Task decomposition and code contracts |
| `CROSS_DOCUMENT_DEDUP_IMPLEMENTATION.md` (this document) | Implementation guide |
| `EMBEDDING_PIPELINE_SPEC.md` | Parent pipeline requirements |
| `EMBEDDING_PIPELINE_IMPLEMENTATION.md` | Parent pipeline implementation |
| `EMBEDDING_PIPELINE_DESIGN.md` | Parent pipeline design |
