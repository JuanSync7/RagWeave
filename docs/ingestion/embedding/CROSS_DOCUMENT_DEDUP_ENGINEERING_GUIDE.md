> **Document type:** Engineering guide (Layer 5 — post-implementation)
> **Upstream:** CROSS_DOCUMENT_DEDUP_IMPLEMENTATION.md
> **Last updated:** 2026-04-17
> **Status:** Authoritative

# Cross-Document Deduplication Engineering Guide

| Field | Value |
|-------|-------|
| **Document** | Cross-Document Deduplication Engineering Guide |
| **Version** | 1.0.0 |
| **Status** | Active |
| **Implementation Reference** | `CROSS_DOCUMENT_DEDUP_IMPLEMENTATION.md` v1.0.0 |
| **Spec Reference** | `CROSS_DOCUMENT_DEDUP_SPEC.md` v1.0.0 (FR-3400–FR-3461, NFR-3500–NFR-3504) |
| **Created** | 2026-04-15 |
| **Last Updated** | 2026-04-17 |

---

## 1. Overview

Cross-document deduplication detects and eliminates chunk-level duplicates across multiple
ingested documents. When two documents share identical or near-identical content in the same
chunk, the subsystem stores only one canonical copy and records provenance for every source
document that contains that content.

The subsystem covers two tiers of matching:

- **Tier 1 — Exact hash (FR-3411):** SHA-256 of normalised chunk text. Near-zero compute cost.
  Always active when `enable_cross_document_dedup=True`.
- **Tier 2 — MinHash fuzzy (FR-3420–FR-3424):** MinHash locality-sensitive hashing over
  word shingles. Catches near-duplicates (minor whitespace, punctuation, or phrasing
  differences). Opt-in via `enable_fuzzy_dedup=True`. Requires the `datasketch` library.

Both tiers share the same merge-and-back-reference pattern: a duplicate chunk is dropped from
the output list and the matching canonical chunk's `source_documents` array is updated to
include the incoming source key.

---

## 2. Module Layout

```
src/ingest/embedding/
├── common/
│   ├── types.py                   # MergeEvent TypedDict, create_merge_event()
│   └── dedup_utils.py             # Tier 1 engine: normalise, hash, Weaviate ops, revert_merge
├── nodes/
│   └── cross_document_dedup.py    # Node function (orchestrates Tier 1 + optional Tier 2)
├── support/
│   └── minhash_engine.py          # Tier 2 engine: MinHash fingerprint, similarity, lookup
├── state.py                       # EmbeddingPipelineState — dedup_merge_report, dedup_stats
└── workflow.py                    # DAG wiring (conditional edge from quality_validation)

src/vector_db/
└── __init__.py                    # update_chunk_content() — canonical replacement (FR-3432)

tests/ingest/
├── test_dedup_workflow_integration.py  # Node integration: bypass, override, merge events
└── test_dedup_revert.py                # revert_merge() unit tests
```

**Exports per module:**

| Module | Exports |
|--------|---------|
| `src/ingest/embedding/common/types.py` | `MergeEvent`, `create_merge_event` |
| `src/ingest/embedding/common/dedup_utils.py` | `normalise_chunk_text`, `compute_content_hash`, `find_chunk_by_content_hash`, `append_source_document`, `remove_source_document_refs`, `revert_merge`, `build_fuzzy_fingerprint` |
| `src/ingest/embedding/support/minhash_engine.py` | `MinHashEngine`, `compute_fuzzy_fingerprint`, `estimate_similarity`, `find_chunk_by_fuzzy_fingerprint` |
| `src/ingest/embedding/nodes/cross_document_dedup.py` | `cross_document_dedup_node` |

---

## 3. Key Abstractions

### 3.1 MergeEvent

```python
class MergeEvent(TypedDict):
    canonical_content_hash: str   # SHA-256 hex of the canonical chunk's text
    canonical_chunk_id:     str   # Weaviate UUID of canonical (empty for overrides)
    merged_source_key:      str   # source_key of the incoming document
    merged_section:         str   # heading_path from chunk metadata (may be empty)
    match_tier:             str   # "exact" | "fuzzy" | "override"
    similarity_score:       float # 1.0 exact, Jaccard score fuzzy, 0.0 override
    canonical_replaced:     bool  # True only when incoming chunk replaced canonical text
    action:                 str   # "merged" | "replaced" | "skipped" | "override_skipped"
    timestamp:              str   # ISO 8601 UTC
```

`create_merge_event()` is the only factory and auto-fills `timestamp`:

```python
def create_merge_event(
    *,
    canonical_content_hash: str,
    canonical_chunk_id: str,
    merged_source_key: str,
    merged_section: str,
    match_tier: str,
    similarity_score: float,
    canonical_replaced: bool,
    action: str = "merged",
) -> MergeEvent:
```

### 3.2 Content hash

```python
def normalise_chunk_text(text: str) -> str:
    """Strip leading/trailing whitespace; collapse interior whitespace to one space.
    Case is preserved (FR-3410 AC-2)."""

def compute_content_hash(text: str) -> str:
    """Return lowercase SHA-256 hex (64 chars) of normalised text."""
```

### 3.3 MinHashEngine

```python
class MinHashEngine:
    def __init__(self, shingle_size: int = 3, num_hashes: int = 128) -> None:
        """Eagerly verify datasketch availability.
        Raises ValueError if shingle_size < 1 or num_hashes < 16.
        Raises ImportError if datasketch is not installed."""

    def fingerprint(self, text: str) -> str:
        """Return hex-encoded MinHash signature for text."""

    def jaccard(self, sig_a: str, sig_b: str) -> float:
        """Estimate Jaccard similarity between two hex-encoded signatures."""
```

### 3.4 Dedup node function

```python
def cross_document_dedup_node(state: EmbeddingPipelineState) -> dict[str, Any]:
    """Detect and eliminate cross-document duplicate chunks.

    Returns partial state update:
        chunks           — deduplicated output list (novel chunks only)
        dedup_merge_report — list[MergeEvent dict] for every merge/override this run
        dedup_stats      — {total_input_chunks, exact_matches, fuzzy_matches,
                            novel_chunks, degraded}
        processing_log   — updated log with "cross_document_dedup:ok" |
                           "cross_document_dedup:skipped" |
                           "cross_document_dedup:degraded"
    """
```

### 3.5 Revert merge

```python
def revert_merge(
    client: Any,
    event: MergeEvent,
    *,
    collection: Optional[str] = None,
) -> bool:
    """Detach merged_source_key from the canonical chunk's source_documents.
    Deletes the canonical chunk when source_documents becomes empty.
    Returns True on success, False on no-op or error. Idempotent."""
```

---

## 4. Dedup Flow

The node executes the following steps for every call. Steps are abbreviated when the feature
is disabled or the source is overridden.

### Step 1 — Bypass check (FR-3402)

```
config.enable_cross_document_dedup == False
    → return chunks unchanged, dedup_merge_report=[], dedup_stats={},
      log "cross_document_dedup:skipped"
```

### Step 2 — Re-ingestion cleanup (FR-3433)

```
config.update_mode == True
    → remove_source_document_refs(client, source_key)
      For every chunk whose source_documents contains source_key:
        remove source_key from the array
        if array is now empty: delete the chunk from Weaviate
```

This runs before the per-chunk loop so that re-ingested chunks compete fresh against the
current state of the store.

### Step 3 — Per-source override check (FR-3450)

```
source_key in config.dedup_override_sources
    → skip_lookup = True
      All chunks for this source pass through as novel.
      Each emits an "override_skipped" MergeEvent (match_tier="override",
      similarity_score=0.0, canonical_chunk_id="").
```

### Step 4 — Per-chunk loop

For each chunk (when `skip_lookup` is False):

**4a. Normalise and hash**

```python
content_hash = compute_content_hash(chunk.text)
chunk.metadata["content_hash"] = content_hash
```

**4b. Tier 1 — exact lookup (FR-3411)**

```python
existing = find_chunk_by_content_hash(client, content_hash)
```

Queries Weaviate `Chunk` collection with `Filter.by_property("content_hash").equal(content_hash)`.
Returns `{"uuid", "source_documents", "text_length"}` on match, `None` on miss or error.

On match:
- `append_source_document(client, existing["uuid"], source_key)` — deduplicates before
  appending; no-op if already present.
- Append `MergeEvent(match_tier="exact", action="merged", similarity_score=1.0)` to report.
- Remove chunk from output (`continue`).

**4c. Tier 2 — MinHash fuzzy (FR-3420–FR-3424)** — only when `config.enable_fuzzy_dedup=True`

```python
fingerprint = compute_fuzzy_fingerprint(
    chunk.text, shingle_size=config.fuzzy_shingle_size, num_hashes=config.fuzzy_num_hashes
)
chunk.metadata["fuzzy_fingerprint"] = fingerprint
match = find_chunk_by_fuzzy_fingerprint(client, fingerprint, threshold, num_hashes)
```

`find_chunk_by_fuzzy_fingerprint` scans all chunks with a stored `fuzzy_fingerprint`
(up to 10,000), deserialises each, and returns the best Jaccard match above `threshold`.
Returns `{"uuid", "similarity", "text_length"}` or `None`.

On match above threshold:
- **Canonical selection — longer chunk wins (FR-3424):** If `len(chunk.text) > match["text_length"]`,
  call `update_chunk_content(client, match["uuid"], text=..., content_hash=..., fuzzy_fingerprint=...)`.
  Set `canonical_replaced=True`.
- `append_source_document(client, match["uuid"], source_key)`.
- Append `MergeEvent(match_tier="fuzzy", action="replaced"|"merged", similarity_score=match["similarity"])`.
- Remove chunk from output.

**4d. Novel chunk — pass through**

```python
chunk.metadata.setdefault("source_documents", [source_key])
novel_chunks.append(chunk)
```

### Step 5 — Graceful degradation (NFR-3504)

Any unhandled exception in the loop sets `degraded=True` and falls back to passing all
remaining chunks through unchanged. The processing log records `cross_document_dedup:degraded`.
Storing a duplicate is preferable to failing the ingestion run.

---

## 5. Weaviate Schema Extensions

The subsystem adds four properties to the `Chunk` collection:

| Property | Type | Index | Purpose |
|----------|------|-------|---------|
| `content_hash` | `TEXT` | `filterable: true`, `searchable: false` | SHA-256 for Tier 1 exact lookup |
| `source_documents` | `TEXT[]` | default | Provenance array — all source keys that contain this chunk's content |
| `fuzzy_fingerprint` | `TEXT` | `filterable: false`, `searchable: false` | Serialised MinHash signature for Tier 2 lookup |
| `canonical` | `BOOL` | default | Reserved for future canonical-selection queries; not yet used by the node |

**How they flow:**

- Novel chunks: `content_hash` and `source_documents` are set in `chunk.metadata` by the
  dedup node before `embedding_storage` persists them.
- Novel chunks (Tier 2 active): `fuzzy_fingerprint` is also added to `chunk.metadata`.
- Merged chunks: never reach `embedding_storage`. Their metadata is discarded.
- Canonical replacement: `update_chunk_content()` in `src/vector_db/__init__.py` patches the
  existing object's `text`, `content_hash`, and `fuzzy_fingerprint` in place.

**`update_chunk_content` signature:**

```python
def update_chunk_content(
    client: Any,
    chunk_uuid: str,
    *,
    text: str,
    content_hash: str,
    fuzzy_fingerprint: Optional[str] = None,
    collection: Optional[str] = None,
) -> bool:
    """Replace a canonical chunk's text + dedup metadata in place (FR-3432).
    Returns True on success, False on error (non-fatal to the pipeline)."""
```

---

## 6. DAG Integration

The dedup node is inserted between `quality_validation` and `embedding_storage` in the
Phase 3.3 Embedding Pipeline DAG.

**Full node order:**

```
document_storage → chunking → vlm_enrichment → chunk_enrichment
  → metadata_generation → [cross_reference_extraction →]
  knowledge_graph_extraction → quality_validation
  → [cross_document_dedup →] embedding_storage
  → visual_embedding → [knowledge_graph_storage]
```

**Conditional activation (FR-3402):**

The edge from `quality_validation` is a `conditional_edge` in LangGraph:

```python
graph.add_conditional_edges(
    "quality_validation",
    lambda state: (
        "cross_document_dedup"
        if getattr(state["runtime"].config, "enable_cross_document_dedup", True)
        else "embedding_storage"
    ),
    {
        "cross_document_dedup": "cross_document_dedup",
        "embedding_storage": "embedding_storage",
    },
)
graph.add_edge("cross_document_dedup", "embedding_storage")
```

When `enable_cross_document_dedup=False`, the graph routes directly to `embedding_storage`
and the node is never invoked — preserving pre-Phase 3.3 behaviour exactly.

Note: the node also has an internal bypass path (checks the same flag) so that if the node
is entered through a misconfigured route it still degrades gracefully.

**State fields added by Phase 3.3:**

```python
# in EmbeddingPipelineState (state.py)
dedup_merge_report: list[dict[str, Any]]
# List of MergeEvent dicts emitted by cross_document_dedup_node.

dedup_stats: dict[str, Any]
# {total_input_chunks, exact_matches, fuzzy_matches, novel_chunks, degraded}
```

---

## 7. Override / Revert Path

### Per-source override (FR-3450)

Add a source key to `config.dedup_override_sources` to store all its chunks independently
regardless of content matches:

```python
# IngestionConfig
dedup_override_sources: list[str] = []
```

When a source is in this list:
- `content_hash` is still computed and attached to chunk metadata.
- No Weaviate lookups are performed (hash or fingerprint queries skipped).
- All chunks pass through as novel with `source_documents=[source_key]`.
- Each chunk emits an `"override_skipped"` merge event so the report remains queryable.

### Reverting a merge (FR-3451)

`revert_merge()` in `src/ingest/embedding/common/dedup_utils.py` undoes a specific merge
event by detaching a source key from a canonical chunk's `source_documents` array.

```python
from src.ingest.embedding.common.dedup_utils import revert_merge

reverted = revert_merge(
    client=weaviate_client,
    event=merge_event_dict,        # a MergeEvent from dedup_merge_report
    collection="Chunk",            # optional; defaults to "Chunk"
)
# True  → source_key was detached (or canonical deleted if array became empty)
# False → source_key was not present (no-op) or an error occurred
```

Behaviour:
- Looks up the canonical chunk by `event["canonical_content_hash"]`.
- Removes `event["merged_source_key"]` from `source_documents`.
- If `source_documents` becomes empty: deletes the canonical chunk from Weaviate.
- **Idempotent:** if `merged_source_key` is not present, returns `False` without error.

After reverting, re-ingest the affected document with the source key added to
`dedup_override_sources` if independent storage is required.

### Re-ingestion cleanup (FR-3433)

When `config.update_mode=True`, the node automatically calls
`remove_source_document_refs(client, source_key)` before the per-chunk loop.
This removes the source key from every chunk's `source_documents` and deletes any chunk
that has no remaining provenance. The fresh ingestion run then deduplicates against the
updated store state.

---

## 8. Configuration

All fields are read via `getattr(config, field, default)` so they are backward-compatible
with configs that predate Phase 3.3.

| Config field | Type | Default | Description |
|---|---|---|---|
| `enable_cross_document_dedup` | `bool` | `True` | Master toggle. When `False`, routes the DAG edge directly to `embedding_storage`. |
| `enable_fuzzy_dedup` | `bool` | `False` | Activate Tier 2 MinHash matching. Requires `datasketch`. |
| `fuzzy_similarity_threshold` | `float` | `0.95` | Minimum Jaccard similarity to consider a fuzzy match. |
| `fuzzy_shingle_size` | `int` | `3` | Word-level n-gram width for MinHash shingle generation. |
| `fuzzy_num_hashes` | `int` | `128` | Number of MinHash permutations. Must be >= 16. |
| `dedup_override_sources` | `list[str]` | `[]` | Source keys exempt from cross-document dedup lookups. |
| `update_mode` | `bool` | `False` | When `True`, triggers back-reference cleanup before dedup. |

**Similarity threshold guidance:**

| Threshold | Effect |
|-----------|--------|
| `0.99` | Merges chunks differing by one or two words only |
| `0.95` (default) | Merges minor phrasing, punctuation, and whitespace differences |
| `0.90` | Merges moderate differences (a few rewritten sentences) |
| below `0.90` | High false-positive risk; not recommended without manual review |

---

## 9. Troubleshooting

### 9.1 False positive merges

**Symptom:** Two chunks from different documents are merged even though they should be kept
separate.

**Diagnosis:**
- Inspect `dedup_merge_report` from the ingestion run. Check `match_tier` and `similarity_score`.
- `match_tier="exact"` means the chunks are textually identical after normalisation. If the
  merge is semantically incorrect, use the override path.
- `match_tier="fuzzy"` with a score close to `fuzzy_similarity_threshold` — raise the threshold
  slightly to prevent future merges at that similarity level.

**Resolution:**
- Add the source key to `dedup_override_sources` for permanent exemption.
- Call `revert_merge(client, event)` to undo a specific past merge, then re-ingest.

### 9.2 Missing back-references

**Symptom:** A chunk's `source_documents` array is missing a source key that should be listed.

**Diagnosis:**
1. Was the document ingested before the dedup feature was deployed? Pre-Phase 3.3 chunks have
   no `content_hash`. They cannot be matched by Tier 1. No backfill is available in v1.
2. Did the node degrade? Check `dedup_stats["degraded"]` or `processing_log` for
   `cross_document_dedup:degraded`. If degraded, all chunks were stored without dedup.
3. Is the source in `dedup_override_sources`? Override sources bypass the lookup.
4. Unicode edge case: compare normalised text of both chunks.
   `U+00A0` (non-breaking space) is not collapsed by `_WHITESPACE_RE` — it produces a
   different hash than `U+0020`.

**Resolution:**
- Re-ingest the source document (without override) to trigger a fresh dedup run.

### 9.3 Tier 2 performance degradation

**Symptom:** Ingestion slows noticeably after enabling `enable_fuzzy_dedup=True`.

**Cause:** `find_chunk_by_fuzzy_fingerprint` loads up to 10,000 stored fingerprints from
Weaviate and compares each in Python. This is O(n) over stored fingerprints per chunk.

**Mitigation:**
- Check the count of chunks with `fuzzy_fingerprint` populated. If it exceeds 50K, consider
  disabling Tier 2 until an LSH forest index is implemented (planned v1.1).
- Reduce `fuzzy_num_hashes` (e.g., to 64) to speed up per-comparison cost at the cost of
  estimation accuracy.
- The node degrades gracefully if Weaviate is unresponsive — all chunks pass through with
  `degraded=True` in stats.

### 9.4 Missing Weaviate schema properties

**Symptom:** The dedup node raises errors about missing properties (`content_hash`, etc.),
or `ensure_collection()` fails.

**Cause:** The `Chunk` collection was created before Phase 3.3 schema properties were added.

**Diagnosis:** Verify properties directly:

```bash
curl -s http://localhost:8080/v1/schema/Chunk | \
  jq '.properties[] | select(.name == "content_hash")'
```

**Resolution:** Re-run `ensure_collection()` — it handles adding new properties to an
existing collection idempotently. If properties exist with the wrong type, you must recreate
the collection (Weaviate does not support in-place property type changes).

### 9.5 `datasketch` import error

**Symptom:** Enabling `enable_fuzzy_dedup=True` raises `ImportError: datasketch is required
for Tier 2 fuzzy deduplication`.

**Resolution:**

```bash
pip install datasketch
```

Tier 1 is unaffected — `minhash_engine.py` is importable without `datasketch`, and the error
surfaces only at call time.

---

## 10. Extension Guide

### Adding a new dedup tier

1. Create the engine in `src/ingest/embedding/support/`. Expose:
   - A `compute_*` function returning a hex fingerprint from text.
   - A `find_chunk_by_*` function querying Weaviate.

2. Add a `_try_<tier>_dedup` private helper in `cross_document_dedup.py` following the
   pattern of `_try_fuzzy_dedup`.

3. Wire it into the per-chunk loop after the Tier 2 block with a new `getattr(config, ...)` guard.

4. Add the new toggle and parameters to `IngestionConfig`.

5. Add a `<tier>_matches` counter to `dedup_stats`.

6. Update tests and this guide.

### Customising normalisation

`normalise_chunk_text` in `dedup_utils.py` strips and collapses whitespace; case is preserved
(FR-3410 AC-2). Changing this function invalidates all existing `content_hash` values and
MinHash fingerprints in Weaviate. Any change requires a batch re-hash migration plan.

---

## Companion Documents

| Document | Role |
|----------|------|
| `CROSS_DOCUMENT_DEDUP_SPEC.md` | Authoritative requirements (FR-3400–FR-3461, NFR-3500–NFR-3504) |
| `CROSS_DOCUMENT_DEDUP_DESIGN.md` | Task decomposition and code contracts |
| `CROSS_DOCUMENT_DEDUP_IMPLEMENTATION.md` | Implementation source-of-truth |
| `CROSS_DOCUMENT_DEDUP_TEST_DOCS.md` | Test strategy, file map, coverage |
| `EMBEDDING_PIPELINE_SPEC.md` | Parent pipeline requirements |
