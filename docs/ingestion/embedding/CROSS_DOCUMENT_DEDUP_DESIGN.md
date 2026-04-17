> **Document type:** Design document (Layer 4)
> **Upstream:** CROSS_DOCUMENT_DEDUP_SPEC.md
> **Last updated:** 2026-04-15

# Cross-Document Deduplication — Design (v1.0.0)

| Field | Value |
|-------|-------|
| **Document** | Cross-Document Deduplication Design Document |
| **Version** | 1.0.0 |
| **Status** | Active |
| **Spec Reference** | `CROSS_DOCUMENT_DEDUP_SPEC.md` v1.0.0 (FR-3400–FR-3461, NFR-3500–NFR-3504) |
| **Companion Documents** | `CROSS_DOCUMENT_DEDUP_SPEC.md`, `EMBEDDING_PIPELINE_DESIGN.md`, `EMBEDDING_PIPELINE_SPEC.md`, `INGESTION_PLATFORM_SPEC.md` |
| **Created** | 2026-04-15 |
| **Last Updated** | 2026-04-15 |

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-04-15 | Initial design. Covers dedup node implementation, content hash infrastructure, MinHash engine, back-reference model, merge reporting, revert mechanism, and pipeline DAG integration. |

> **Document Intent.** This design document translates the requirements defined in
> `CROSS_DOCUMENT_DEDUP_SPEC.md` (FR-3400–FR-3461, NFR-3500–NFR-3504) into a task-oriented
> implementation plan. Each task maps to one or more specification requirements and includes
> subtasks, complexity estimates, dependencies, and testing strategies.
>
> The cross-document deduplication node is an extension to the Embedding Pipeline. It detects
> chunks whose content duplicates content already stored in Weaviate from prior ingestion runs,
> eliminates the duplicate, and maintains a back-reference array (`source_documents`) on the
> canonical chunk for multi-document provenance.

---

## 1. Overview

Cross-document deduplication addresses a retrieval quality problem: when the same paragraph appears
verbatim in multiple source documents, each copy becomes an independent vector in the store,
crowding top-K results and wasting embedding compute. The dedup node eliminates this by checking
each chunk against the vector store before embedding.

The design follows the two-tier architecture defined in the spec:

- **Tier 1 (default):** SHA-256 content hash of normalised text for exact-match detection.
  Near-zero computational cost. Enabled whenever cross-document dedup is active.
- **Tier 2 (optional):** MinHash locality-sensitive hashing for near-duplicate detection at
  configurable similarity thresholds. Opt-in via `enable_fuzzy_dedup`.

Both tiers share a common merge path: when a match is found, the incoming chunk's `source_key`
is appended to the canonical chunk's `source_documents` array in Weaviate via a partial update,
and the incoming chunk is removed from the list passed to `embedding_storage`.

---

## 2. Current State Analysis

### 2.1 Existing Within-Document Dedup

The `quality_validation_node` in `src/ingest/embedding/nodes/quality_validation.py` already
performs within-document deduplication using normalised text comparison (whitespace-collapsed,
lowercased). This handles the case where the same paragraph appears twice within a single
document's chunk set. It does NOT detect duplicates across documents because it operates only
on the current document's in-memory chunk list with no access to previously stored content.

### 2.2 Current Pipeline Topology

The embedding pipeline DAG currently routes:

```
... -> quality_validation -> embedding_storage -> ...
```

The dedup node will be inserted between these two, creating:

```
... -> quality_validation -> cross_document_dedup -> embedding_storage -> ...
```

### 2.3 Current Embedding Storage

The `embedding_storage_node` in `src/ingest/embedding/nodes/embedding_storage.py` calls
`runtime.embedder.embed_documents(texts)` to generate embeddings, then writes `DocumentRecord`
objects to Weaviate via `add_documents()`. On re-ingestion (`update_mode`), it first deletes
all existing chunks for the `source_key` via `delete_by_source_key()`.

The dedup node must coordinate with this: chunks identified as duplicates are removed from the
list before `embedding_storage` runs, saving both embedding compute and storage writes. Novel
chunks carry `content_hash` (and optionally `fuzzy_fingerprint` and `source_documents`) in their
metadata, which `embedding_storage` persists to Weaviate.

### 2.4 Weaviate Schema Gap

The current Weaviate schema does not include `content_hash`, `source_documents`, `fuzzy_fingerprint`,
or `canonical` properties. These must be added as part of implementation (see Task 3.4).

---

## 3. Task Decomposition

### 3.1 Dedup Node Implementation

**Description:** Implement the `cross_document_dedup_node` function in
`src/ingest/embedding/nodes/cross_document_dedup.py`. This is the core node that orchestrates
Tier 1 and Tier 2 dedup, merge events, and chunk list reduction.

**Requirements Covered:** FR-3400, FR-3401, FR-3402, FR-3403, FR-3413, NFR-3504

**Dependencies:** Task 3.2 (content hash), Task 3.4 (Weaviate schema), Task 3.7 (DAG wiring)

**Complexity:** L

**Subtasks:**

1. **Node function skeleton.** Implement `cross_document_dedup_node(state: EmbeddingPipelineState) -> dict[str, Any]`
   following the same pattern as `quality_validation_node` (FR-3401). Accept pipeline state,
   return partial state update with `chunks`, `dedup_merge_report`, `dedup_stats`, and
   `processing_log`.
2. **Bypass path.** When `config.enable_cross_document_dedup` is `false`, return immediately
   with unmodified chunks and `cross_document_dedup:skipped` log entry (FR-3402).
3. **Per-source override check.** Before processing, check if the current document's `source_key`
   is in `config.dedup_override_sources`. If so, skip dedup lookups but still compute and attach
   `content_hash` to chunk metadata for future reference (FR-3450).
4. **Re-ingestion back-reference cleanup.** When `runtime.config.update_mode` is true (re-ingestion),
   query Weaviate for all chunks whose `source_documents` array contains the current `source_key`.
   Remove the `source_key` from each. Delete chunks whose `source_documents` becomes empty
   (FR-3433).
5. **Tier 1 loop.** For each chunk, compute content hash (Task 3.2), query Weaviate for exact
   match (FR-3411). On match: append `source_key` to canonical chunk's `source_documents`,
   record merge event, remove chunk from output list. On no match: attach `content_hash` to
   chunk metadata (FR-3412).
6. **Tier 2 loop.** For chunks that did not match in Tier 1 and when `enable_fuzzy_dedup` is
   true: compute MinHash fingerprint (Task 3.3), query fingerprint index for best match above
   threshold (FR-3423). On match: apply canonical chunk selection logic (FR-3424 -- keep longer
   chunk), record merge event. On no match: attach `fuzzy_fingerprint` to chunk metadata.
7. **Graceful degradation.** Wrap all Weaviate operations in try/except. On unrecoverable error,
   pass all remaining chunks through unmodified, log `cross_document_dedup:degraded`, set
   `dedup_stats.degraded = true` (NFR-3504).
8. **Stats aggregation.** Populate `dedup_stats` dict with `exact_matches`, `fuzzy_matches`,
   `novel_chunks`, `total_input_chunks` (FR-3403).

**Testing Strategy:**

- Unit tests with mocked Weaviate client: verify exact-match merge, no-match passthrough,
  bypass when disabled, override bypass, graceful degradation on Weaviate error.
- Integration test against Weaviate test collection: ingest document A, then ingest document B
  with overlapping content, verify back-references and reduced chunk count.

---

### 3.2 Content Hash Infrastructure

**Description:** Implement the content hash computation utility and Weaviate lookup helpers
used by the dedup node's Tier 1 path.

**Requirements Covered:** FR-3410, FR-3411, FR-3412

**Dependencies:** None

**Complexity:** S

**Subtasks:**

1. **Normalisation function.** Implement `normalise_chunk_text(text: str) -> str` in a shared
   utility module (e.g., `src/ingest/embedding/common/dedup_utils.py`). Strip leading/trailing
   whitespace, collapse interior whitespace to single space, preserve case (FR-3410).
2. **Hash function.** Implement `compute_content_hash(text: str) -> str` that normalises the
   input, then returns `hashlib.sha256(normalised.encode("utf-8")).hexdigest()` (FR-3410).
3. **Weaviate lookup helper.** Implement `find_chunk_by_content_hash(client, content_hash: str) -> Optional[dict]`
   that queries Weaviate with an exact-match filter on the `content_hash` property. Return the
   chunk's UUID, `source_documents` array, and text length. Handle transient errors by returning
   `None` and logging a warning (FR-3411 AC-3).
4. **Weaviate partial update helper.** Implement `append_source_document(client, chunk_uuid: str, source_key: str) -> bool`
   that appends `source_key` to the chunk's `source_documents` array. Use Weaviate's PATCH
   endpoint. Deduplicate: do not append if already present (FR-3431 AC-2). Handle failures
   gracefully (FR-3431 AC-4).

**Testing Strategy:**

- Unit tests for normalisation edge cases: tabs, newlines, multiple spaces, empty string,
  Unicode whitespace.
- Unit tests for hash determinism: same normalised text always produces same hash.
- Contract test: `"  Hello   World\n"` and `"Hello World"` produce identical hashes;
  `"Hello World"` and `"hello world"` produce different hashes (FR-3410 AC-1, AC-2).

---

### 3.3 MinHash Fingerprint Engine (optional tier)

**Description:** Implement Tier 2 fuzzy fingerprint computation and lookup. This is an optional
component activated only when `enable_fuzzy_dedup` is true.

**Requirements Covered:** FR-3420, FR-3421, FR-3422, FR-3423, FR-3424, NFR-3502

**Dependencies:** Task 3.2 (normalisation function is shared)

**Complexity:** M

**Subtasks:**

1. **MinHash computation.** Implement `compute_fuzzy_fingerprint(text: str, shingle_size: int = 3, num_hashes: int = 128) -> str`
   using the `datasketch` library. Tokenise normalised text into word-level shingles (contiguous
   n-grams of `shingle_size` words). Generate a MinHash signature with `num_hashes` permutations.
   Serialise the signature to a hex string for Weaviate storage (FR-3421).
2. **Similarity estimation.** Implement `estimate_similarity(sig_a: str, sig_b: str) -> float`
   that deserialises two MinHash signatures and returns their estimated Jaccard similarity.
3. **Fingerprint lookup.** Implement `find_chunk_by_fuzzy_fingerprint(client, fingerprint: str, threshold: float) -> Optional[dict]`.
   This queries Weaviate for chunks with `fuzzy_fingerprint` populated, deserialises each, and
   returns the best match above `threshold`. For v1, this is a scan over stored fingerprints
   (resolving OQ-1 from the spec: start with Weaviate query, defer LSH forest index to v1.1
   when corpus exceeds 100K chunks).
4. **Canonical selection.** Implement the longer-chunk-wins logic (FR-3424): compare normalised
   text lengths. If the incoming chunk is longer, update the canonical chunk's text, embedding,
   `content_hash`, and `fuzzy_fingerprint` in Weaviate.

**Design Decision (OQ-1 Resolution):** For v1, Tier 2 lookup scans stored fingerprints via
Weaviate query rather than maintaining a dedicated LSH forest index. This simplifies the
implementation and avoids an additional infrastructure dependency. The scan approach is
acceptable for corpora under 100K chunks. A dedicated LSH forest (e.g., `datasketch.MinHashLSH`)
should be introduced if Tier 2 lookup latency becomes a bottleneck at scale.

**Testing Strategy:**

- Unit tests: verify shingle generation for known text; verify similarity score for identical,
  similar, and dissimilar text pairs.
- Threshold boundary test: verify that similarity at exactly the threshold triggers a match,
  and similarity below does not.
- Performance test: verify MinHash computation for a 512-token chunk completes in under 10ms
  (NFR-3502).

---

### 3.4 Back-Reference Model (Weaviate schema update)

**Description:** Extend the Weaviate chunk object schema with the properties required by the
dedup node, and update `embedding_storage_node` to persist these properties.

**Requirements Covered:** FR-3430, FR-3431, FR-3432, FR-3433

**Dependencies:** None (can be done in parallel with other tasks)

**Complexity:** S

**Subtasks:**

1. **Schema migration.** Add the following properties to the chunk object schema in Weaviate:
   - `content_hash` (`string`, indexed for exact-match filter) -- SHA-256 of normalised text.
   - `source_documents` (`string[]`) -- array of `source_key` values.
   - `fuzzy_fingerprint` (`string`, optional) -- serialised MinHash signature.
   - `canonical` (`boolean`, default `true`) -- reserved for future soft-delete flows.
2. **`ensure_collection` update.** Modify `ensure_collection()` in `src/vector_db/` to include
   the new properties when creating or validating the collection schema.
3. **`embedding_storage_node` update.** Ensure the node reads `content_hash`, `source_documents`,
   and `fuzzy_fingerprint` from chunk metadata and includes them in the `DocumentRecord` written
   to Weaviate. If `source_documents` is not set on a chunk (e.g., dedup is disabled), default
   to `[source_key]` (FR-3430).
4. **Index configuration.** Configure the `content_hash` property with an inverted index for
   fast exact-match queries (NFR-3500). The `fuzzy_fingerprint` property does not need an
   inverted index (it is compared via deserialization, not Weaviate filter).

**Testing Strategy:**

- Integration test: create a collection with the new schema, insert a chunk with all dedup
  properties, query by `content_hash`, verify `source_documents` is returned correctly.
- Migration test: verify `ensure_collection` handles both fresh creation and existing-collection
  upgrade (adding new properties to an existing schema).

---

### 3.5 Merge Report Generation

**Description:** Implement the merge event recording and report persistence mechanisms.

**Requirements Covered:** FR-3440, FR-3441, FR-3442, SC-3510

**Dependencies:** Task 3.1 (merge events are generated within the dedup node)

**Complexity:** S

**Subtasks:**

1. **Merge event dataclass.** Define a `MergeEvent` TypedDict (or dataclass) in
   `src/ingest/embedding/common/types.py` matching the schema in FR-3440:
   `canonical_content_hash`, `canonical_chunk_id`, `merged_source_key`, `merged_section`,
   `match_tier` ("exact" or "fuzzy"), `similarity_score`, `canonical_replaced`, `timestamp`.
   Ensure no full chunk text is included (SC-3510).
2. **Event creation helper.** Implement `create_merge_event(...)` that constructs a `MergeEvent`
   with the current ISO 8601 timestamp.
3. **Report persistence.** The orchestrator (Temporal activity result) SHALL persist the
   `dedup_merge_report` from pipeline state to the ingestion result record. Add
   `dedup_merge_report` and `dedup_stats` to `EmbeddingResult` in
   `src/ingest/temporal/activities.py` (FR-3441).
4. **CLI surfacing.** Update CLI ingestion output to display a dedup summary line:
   `"Dedup: {exact_matches} exact, {fuzzy_matches} fuzzy, {novel_chunks} novel"` (FR-3442).

**Testing Strategy:**

- Unit test: verify merge event schema compliance for both exact and fuzzy match types.
- Unit test: verify no chunk text appears in merge event records (SC-3510).

---

### 3.6 Revert/Override Mechanism

**Description:** Implement the per-source dedup override and targeted merge revert operations.

**Requirements Covered:** FR-3450, FR-3451, FR-3452, SC-3511

**Dependencies:** Task 3.1, Task 3.4

**Complexity:** M

**Subtasks:**

1. **Override at ingest time.** The dedup node already checks `config.dedup_override_sources`
   (Task 3.1, subtask 3). This task ensures the override is persisted in the document's manifest
   entry so that subsequent re-ingestion respects it automatically (FR-3450 AC-4).
2. **CLI/API override parameter.** Add a `--dedup-override` flag to the CLI `ingest` command
   and a `dedup_override` parameter to the `/ingest` API endpoint. When set, the source's
   `source_key` is added to `dedup_override_sources` for this run and persisted to manifest.
3. **Targeted revert operation.** Implement `revert_merge(source_key: str, canonical_content_hash: str)`
   that: (a) removes `source_key` from the canonical chunk's `source_documents` via partial
   update, (b) re-ingests the affected chunk from the source document with dedup override,
   creating an independent entry (FR-3451). Ensure idempotency: if `source_key` is not in
   `source_documents`, the operation is a no-op (FR-3451 AC-5).
4. **Revert via re-ingestion.** Document-level re-ingestion with `dedup_override=true` is
   already supported by the combination of Tasks 3.1 (override check) and 3.1 (re-ingestion
   cleanup). Verify the end-to-end flow (FR-3452).
5. **Audit logging.** Log all override and revert operations with user identity, timestamp,
   `source_key`, and `canonical_content_hash` (SC-3511).

**Testing Strategy:**

- Integration test: ingest doc A, ingest doc B (with overlap, chunks merge), revert the merge,
  verify both chunks now exist independently.
- Idempotency test: revert the same merge twice, verify second call is a no-op.
- Override test: ingest doc C with `dedup_override=true`, verify all chunks stored independently
  despite matching existing content.

---

### 3.7 Pipeline DAG Integration

**Description:** Wire the `cross_document_dedup` node into the Embedding Pipeline LangGraph DAG
and extend `EmbeddingPipelineState` with dedup fields.

**Requirements Covered:** FR-3400, FR-3403

**Dependencies:** Task 3.1

**Complexity:** S

**Subtasks:**

1. **State extension.** Add `dedup_merge_report: list[dict[str, Any]]` and
   `dedup_stats: dict[str, int]` to `EmbeddingPipelineState` in `src/ingest/embedding/state.py`
   with `total=False` semantics (FR-3403).
2. **DAG modification.** In `build_embedding_pipeline_graph()` (see `EMBEDDING_PIPELINE_DESIGN.md`
   snippet B.1), replace the edge `quality_validation -> embedding_storage` with:
   `quality_validation -> cross_document_dedup -> embedding_storage` (FR-3400).
3. **Import registration.** Import `cross_document_dedup_node` from
   `src/ingest/embedding/nodes/cross_document_dedup.py` and register it as a node in the graph.
4. **Configuration propagation.** Ensure `enable_cross_document_dedup`, `enable_fuzzy_dedup`,
   and all Tier 2 parameters are present in `IngestionConfig` and propagated to the pipeline
   runtime config.

**Testing Strategy:**

- Topology test: compile the graph and verify the edge sequence
  `quality_validation -> cross_document_dedup -> embedding_storage`.
- End-to-end test: run a document through the full pipeline with dedup enabled and verify
  `dedup_stats` is populated in the final state.

---

## 4. Data Structures

### 4.1 EmbeddingPipelineState Extensions

```python
# Additions to EmbeddingPipelineState (TypedDict) in src/ingest/embedding/state.py

class EmbeddingPipelineState(TypedDict, total=False):
    # ... existing fields ...
    dedup_merge_report: list[dict[str, Any]]  # FR-3403
    dedup_stats: dict[str, int]               # FR-3403
```

### 4.2 MergeEvent Schema

```python
# src/ingest/embedding/common/types.py

class MergeEvent(TypedDict):
    canonical_content_hash: str    # SHA-256 hex of canonical chunk
    canonical_chunk_id: str        # Weaviate UUID
    merged_source_key: str         # source_key of the merged document
    merged_section: str            # section path from chunk metadata
    match_tier: str                # "exact" or "fuzzy"
    similarity_score: float        # 1.0 for exact, Jaccard estimate for fuzzy
    canonical_replaced: bool       # true if canonical was replaced (Tier 2)
    timestamp: str                 # ISO 8601
```

### 4.3 Configuration Extensions

```python
# Additions to IngestionConfig

enable_cross_document_dedup: bool = True       # FR-3460
enable_fuzzy_dedup: bool = False               # FR-3460
fuzzy_similarity_threshold: float = 0.95       # FR-3460
fuzzy_shingle_size: int = 3                    # FR-3460
fuzzy_num_hashes: int = 128                    # FR-3460
dedup_override_sources: list[str] = []         # FR-3460
```

### 4.4 Weaviate Schema Extensions

```python
# Additional properties on the chunk object in Weaviate

content_hash: str          # SHA-256, inverted index, exact-match queryable
source_documents: list[str]  # Array of source_key values
fuzzy_fingerprint: str     # Serialised MinHash signature (optional)
canonical: bool            # Always true; reserved for soft-delete
```

---

## 5. Dependency Graph

```
Task 3.2: Content Hash Infrastructure ──────────────┐
                                                     │
Task 3.3: MinHash Fingerprint Engine ────────────────┤
                                                     │
Task 3.4: Weaviate Schema Update ───────────────────┤
                                                     ▼
Task 3.1: Dedup Node Implementation ◄──── (3.2, 3.3, 3.4)
    │
    ├──► Task 3.5: Merge Report Generation ◄─── Task 3.1
    │
    ├──► Task 3.6: Revert/Override Mechanism ◄─── Task 3.1, Task 3.4
    │
    └──► Task 3.7: Pipeline DAG Integration ◄─── Task 3.1

Parallelisable:
  - Tasks 3.2, 3.3, 3.4 can all proceed in parallel (no interdependencies).
  - Tasks 3.5, 3.6, 3.7 depend on Task 3.1 but are independent of each other.

Critical path: 3.2 → 3.1 → 3.7 (minimum viable dedup with Tier 1 only)
Full path:     3.2 + 3.3 + 3.4 → 3.1 → 3.5 + 3.6 + 3.7
```

---

## 6. Migration Path

### 6.1 Schema Migration

1. Run Weaviate schema update to add `content_hash`, `source_documents`, `fuzzy_fingerprint`,
   and `canonical` properties. Existing chunks will have `null` values for these properties.
2. Existing chunks without `source_documents` will be treated as having an implicit
   `source_documents = [source_key]`. The dedup node initialises this on first access if needed.
3. No backfill of `content_hash` for existing chunks is required for v1. Tier 1 dedup only
   catches duplicates of chunks ingested after the feature is enabled. A batch backfill utility
   MAY be provided in v1.1 (see OQ-3 from spec).

### 6.2 Pipeline Integration

1. Deploy the dedup node code alongside the DAG change. The node respects the
   `enable_cross_document_dedup` config flag, so it can be deployed disabled.
2. Enable Tier 1 by setting `enable_cross_document_dedup: true` (default).
3. Monitor merge reports and dedup stats for correctness before enabling Tier 2.
4. Enable Tier 2 by setting `enable_fuzzy_dedup: true` and tuning
   `fuzzy_similarity_threshold` for the corpus.

### 6.3 Rollback

Disabling dedup is safe: set `enable_cross_document_dedup: false`. The node becomes a
passthrough. Existing `source_documents` arrays and `content_hash` values in Weaviate remain
but are not harmful -- they are simply unused metadata. No data loss occurs.

---

## Task-to-Requirement Mapping

| Task | Requirements Covered |
|------|---------------------|
| 3.1 Dedup Node Implementation | FR-3400, FR-3401, FR-3402, FR-3403, FR-3413, NFR-3504 |
| 3.2 Content Hash Infrastructure | FR-3410, FR-3411, FR-3412 |
| 3.3 MinHash Fingerprint Engine | FR-3420, FR-3421, FR-3422, FR-3423, FR-3424, NFR-3502 |
| 3.4 Back-Reference Model (Weaviate) | FR-3430, FR-3431, FR-3432, FR-3433, NFR-3500, NFR-3503 |
| 3.5 Merge Report Generation | FR-3440, FR-3441, FR-3442, SC-3510 |
| 3.6 Revert/Override Mechanism | FR-3450, FR-3451, FR-3452, SC-3511 |
| 3.7 Pipeline DAG Integration | FR-3400, FR-3403 |
