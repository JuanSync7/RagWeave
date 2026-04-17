> **Document type:** Authoritative requirements specification (Layer 3)
> **Downstream:** CROSS_DOCUMENT_DEDUP_SPEC_SUMMARY.md, CROSS_DOCUMENT_DEDUP_DESIGN.md
> **Last updated:** 2026-04-15

# Cross-Document Deduplication — Specification (v1.0.0)

## Document Information

> **Document intent:** This is a formal specification for **Cross-Document Deduplication** — an additional pipeline node that eliminates duplicate and near-duplicate chunks originating from different source documents before they are embedded and stored. This specification extends the AION RAG Document Embedding Pipeline defined in `EMBEDDING_PIPELINE_SPEC.md`. It covers content-hash exact deduplication (Tier 1), optional fuzzy-fingerprint deduplication (Tier 2), the back-reference model that preserves multi-document provenance, merge reporting, and user-initiated revert. For existing Embedding Pipeline functional requirements (FR-591 through FR-1399), see `EMBEDDING_PIPELINE_SPEC.md`. For cross-cutting platform requirements, see `INGESTION_PLATFORM_SPEC.md`.

| Field | Value |
|-------|-------|
| System | AION RAG Document Embedding Pipeline |
| Document Type | Pipeline Specification — Cross-Document Deduplication Extension |
| Companion Documents | EMBEDDING_PIPELINE_SPEC.md (Embedding Pipeline Functional Requirements), DOCUMENT_PROCESSING_SPEC.md (Document Processing Phase), INGESTION_PLATFORM_SPEC.md (Platform/Cross-Cutting Requirements), EMBEDDING_PIPELINE_SPEC_SUMMARY.md (Phase 2 Summary), CROSS_DOCUMENT_DEDUP_SPEC_SUMMARY.md (This Spec Summary), CROSS_DOCUMENT_DEDUP_DESIGN.md (Design Document) |
| Version | 1.0.0 |
| Status | Draft |
| Extends | EMBEDDING_PIPELINE_SPEC.md (section 3.6 Quality Validation, section 3.7 Embedding & Storage) |

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2026-04-15 | AI Assistant | Initial specification. Defines cross-document deduplication node (FR-3400 through FR-3549), covering Tier 1 content-hash dedup, Tier 2 fuzzy fingerprint dedup, back-reference model, merge reporting, and revert mechanism. |

---

## 1. Purpose and Scope

### 1.1 Problem Statement

When an organisation ingests hundreds of documents, substantial content overlap is common. The same paragraph may appear verbatim in a specification, an onboarding guide, and a runbook. Near-identical content — differing only in whitespace, formatting, or minor phrasing — compounds the problem further.

Without cross-document deduplication, these duplicate chunks degrade the retrieval system in three ways:

1. **Top-K crowding.** Duplicate chunks consume retrieval slots that could otherwise surface diverse, complementary context. A query returning five near-identical paragraphs from five documents wastes four slots.
2. **Storage waste.** Each duplicate is independently embedded and stored, multiplying vector storage and embedding compute costs with zero information gain.
3. **Relevance skew.** Retrieval scores are artificially inflated for content that happens to be repeated across many documents, biasing results toward frequently-duplicated boilerplate rather than uniquely relevant material.

The existing within-document deduplication in `quality_validation_node` (see `EMBEDDING_PIPELINE_SPEC.md`, FR-1100 range) addresses duplicates within a single document's chunk set. It does not detect duplicates across documents because it operates only on the current document's chunks with no access to previously stored content.

### 1.2 Scope

This specification defines a new **cross-document deduplication node** inserted into the Embedding Pipeline DAG between the `quality_validation` node and the `embedding_storage` node. The node SHALL detect chunks whose content duplicates or near-duplicates content already stored in the vector database from prior ingestion runs.

**In scope:**

- Tier 1: Exact content-hash deduplication via SHA-256 of normalised text
- Tier 2: Optional fuzzy-fingerprint deduplication via MinHash for near-duplicate detection
- Back-reference model: maintaining a `source_documents` array on each canonical chunk in Weaviate
- Merge reporting: structured reporting of every deduplication merge event
- Revert mechanism: per-source override to undo incorrect merges
- Configuration surface for enabling/disabling tiers, setting thresholds, and controlling behaviour
- Pipeline state extensions to carry dedup results through the DAG

**Out of scope:**

- **Within-document deduplication.** Already handled by `quality_validation_node` (FR-1100 range in `EMBEDDING_PIPELINE_SPEC.md`). This spec addresses only cross-document (inter-document) deduplication.
- **Vector-similarity deduplication (Tier 3).** Rejected during design as disproportionately expensive relative to benefit. Content hash and fuzzy fingerprint cover the practical duplicate spectrum without requiring embedding computation.
- **Retroactive deduplication of already-stored content.** This spec covers deduplication at ingest time. A batch migration utility to deduplicate historical data MAY be specified separately.
- **Semantic deduplication.** Detecting paraphrased content that conveys the same meaning but uses different words is not addressed. This would require embedding-time comparison and is deferred.
- **Chunk merging or rewriting.** When a near-duplicate is found, the system selects a canonical chunk; it does not synthesise a new chunk by merging text from both sources.
- **Cross-document deduplication for knowledge graph triples.** KG triple deduplication is a separate concern handled by the knowledge graph subsystem.

### 1.3 Terminology

| Term | Definition |
|------|-----------|
| Cross-document deduplication | Detection and elimination of chunks whose content duplicates content from a different source document already stored in the vector database. |
| Canonical chunk | The single stored instance of a chunk when duplicates are detected. All back-references point to this chunk. |
| Back-reference | An entry in the canonical chunk's `source_documents` array identifying an additional source document that contained the same or near-identical content. |
| Content hash | A SHA-256 digest computed over normalised chunk text, used for exact-match deduplication (Tier 1). |
| Normalised text | Chunk text with leading/trailing whitespace trimmed and interior whitespace sequences collapsed to a single space. Case is preserved. |
| Fuzzy fingerprint | A MinHash or SimHash locality-sensitive hash of normalised chunk text, used for near-duplicate detection (Tier 2). |
| MinHash | A locality-sensitive hashing technique that estimates Jaccard similarity between sets. Used here on word-level shingles of chunk text. |
| Similarity threshold | The minimum estimated similarity (0.0 to 1.0) at which two chunks are considered near-duplicates under Tier 2. Default: 0.95. |
| Merge event | A single deduplication action where a new chunk is identified as a duplicate of an existing canonical chunk, and the new chunk's source is appended to the canonical chunk's back-reference list instead of being stored separately. |
| Merge report | A structured log of all merge events produced during a single ingestion run. |
| Dedup override | A per-source flag that exempts a specific source document from cross-document deduplication, causing all its chunks to be stored independently. |

### 1.4 Requirement Priority Levels

This specification uses the key words defined in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) to indicate requirement levels:

| Keyword | Meaning |
|---------|---------|
| **MUST** / **SHALL** | Absolute requirement. The system cannot be considered conformant without implementing this. |
| **SHOULD** / **RECOMMENDED** | There may be valid reasons to omit this in particular circumstances, but the full implications must be understood and carefully weighed. |
| **MAY** / **OPTIONAL** | Truly optional. The system is conformant whether or not this is implemented. |

---

## 2. Architecture Overview

### 2.1 Pipeline Placement

The cross-document deduplication node is inserted into the Embedding Pipeline DAG at a single point:

```
... → quality_validation → cross_document_dedup → embedding_storage → ...
```

This placement is deliberate:

- **After quality_validation:** Low-quality and within-document duplicate chunks have already been filtered. The dedup node operates on the smallest possible set of surviving chunks, minimising hash lookups against the vector store.
- **Before embedding_storage:** Duplicate chunks are eliminated before embedding computation occurs, avoiding wasted embedding API/GPU calls. When a match is found, the node performs a Weaviate partial update (appending to `source_documents`) and removes the chunk from the list passed to `embedding_storage`.

### 2.2 Data Flow

```
                          ┌──────────────────────┐
                          │  quality_validation   │
                          │  (within-doc dedup,   │
                          │   quality filtering)  │
                          └──────────┬───────────┘
                                     │
                              chunks (filtered)
                                     │
                                     ▼
                     ┌───────────────────────────────┐
                     │    cross_document_dedup        │
                     │                                │
                     │  For each chunk:               │
                     │  1. Compute content hash       │
                     │  2. Query Weaviate for match   │
                     │  3a. Match found:              │
                     │      - Append source to        │
                     │        canonical chunk's        │
                     │        source_documents         │
                     │      - Record merge event       │
                     │      - Remove from chunk list   │
                     │  3b. No exact match + Tier 2:  │
                     │      - Compute fuzzy fingerprint│
                     │      - Query fingerprint index  │
                     │      - If similar: merge        │
                     │  3c. No match: pass through     │
                     │      - Attach content_hash to   │
                     │        chunk metadata           │
                     └──────────────┬────────────────┘
                                    │
                         chunks (deduplicated)
                           + dedup_merge_report
                                    │
                                    ▼
                     ┌───────────────────────────────┐
                     │      embedding_storage         │
                     │  (embed + store only novel     │
                     │   chunks; skips merged ones)   │
                     └───────────────────────────────┘
```

### 2.3 Weaviate Schema Extension

The dedup node requires the following additions to the chunk object schema in Weaviate:

| Property | Type | Purpose |
|----------|------|---------|
| `content_hash` | `string` | SHA-256 of normalised chunk text. Indexed for exact-match lookup. |
| `source_documents` | `string[]` | Array of source document identifiers (source_key values) that contain this chunk's content. |
| `fuzzy_fingerprint` | `string` (optional) | Serialised MinHash signature. Present only when Tier 2 is enabled. |
| `canonical` | `boolean` | Always `true` for stored chunks. Reserved for future use in soft-delete/revert flows. |

---

## 3. Functional Requirements

### 3.1 Dedup Node Placement and Pipeline Integration

> **FR-3400: Dedup Node Position in DAG**
> The Embedding Pipeline DAG SHALL include a `cross_document_dedup` node positioned immediately after the `quality_validation` node and immediately before the `embedding_storage` node.
> **Rationale:** Deduplication after quality filtering avoids wasted hash lookups on chunks that would be discarded anyway. Deduplication before embedding avoids wasted embedding computation on chunks that already exist in the store.
> **Acceptance Criteria:**
> 1. The `build_embedding_graph()` function in `workflow.py` SHALL include a `cross_document_dedup` node with edges `quality_validation → cross_document_dedup → embedding_storage`.
> 2. No other node SHALL exist between `quality_validation` and `cross_document_dedup`, or between `cross_document_dedup` and `embedding_storage`.
> 3. The existing edge `quality_validation → embedding_storage` SHALL be replaced by the two-hop path through `cross_document_dedup`.

> **FR-3401: Dedup Node State Contract**
> The `cross_document_dedup` node SHALL accept `EmbeddingPipelineState` and return a partial state update containing at minimum: `chunks` (the deduplicated chunk list), `dedup_merge_report` (list of merge event records), and `processing_log` (updated log).
> **Rationale:** Consistent state contract ensures downstream nodes receive the correct reduced chunk list and merge metadata is available for reporting.
> **Acceptance Criteria:**
> 1. The node function signature SHALL be `cross_document_dedup_node(state: EmbeddingPipelineState) -> dict[str, Any]`.
> 2. The returned `chunks` list SHALL contain only chunks that were NOT identified as duplicates of existing stored content.
> 3. The returned `dedup_merge_report` SHALL contain one entry per merge event (see FR-3440).
> 4. The returned `processing_log` SHALL include an entry indicating the node's outcome (e.g., `cross_document_dedup:ok`, `cross_document_dedup:skipped`).

> **FR-3402: Dedup Node Bypass**
> When `config.enable_cross_document_dedup` is `false`, the node SHALL return immediately with the unmodified `chunks` list and a `processing_log` entry of `cross_document_dedup:skipped`.
> **Rationale:** Cross-document dedup is an optional enhancement. Operators MUST be able to disable it without altering the pipeline topology.
> **Acceptance Criteria:**
> 1. When disabled, the node SHALL NOT query Weaviate or compute any hashes.
> 2. When disabled, the returned `chunks` list SHALL be identical to the input `chunks` list.
> 3. When disabled, the returned `dedup_merge_report` SHALL be an empty list.

> **FR-3403: State Extension for Dedup Results**
> `EmbeddingPipelineState` SHALL be extended with the following fields: `dedup_merge_report: list[dict[str, Any]]` (default empty list) and `dedup_stats: dict[str, int]` (default empty dict).
> **Rationale:** Downstream nodes and the orchestrator need access to dedup results for reporting and auditing.
> **Acceptance Criteria:**
> 1. `dedup_merge_report` SHALL be a list of merge event dictionaries conforming to the schema defined in FR-3440.
> 2. `dedup_stats` SHALL contain at minimum the keys `exact_matches`, `fuzzy_matches`, `novel_chunks`, and `total_input_chunks`.
> 3. Both fields SHALL have `total=False` semantics (optional in TypedDict).

### 3.2 Tier 1: Content Hash Deduplication

> **FR-3410: Content Hash Computation**
> For each chunk surviving quality validation, the dedup node SHALL compute a SHA-256 hash of the chunk's normalised text. Normalisation SHALL consist of: (a) stripping leading and trailing whitespace, (b) collapsing all interior whitespace sequences (spaces, tabs, newlines) to a single ASCII space character (U+0020), and (c) preserving original case (no lowercasing).
> **Rationale:** Normalisation ensures that formatting-only differences (extra newlines, trailing spaces, tab-vs-space) do not prevent detection of otherwise identical content. Case is preserved because case differences in technical documentation (e.g., `VHDL` vs `vhdl`) may indicate meaningfully different content.
> **Acceptance Criteria:**
> 1. The string `"  Hello   World\n"` and `"Hello World"` SHALL produce the same content hash.
> 2. The strings `"Hello World"` and `"hello world"` SHALL produce different content hashes.
> 3. The hash SHALL be computed using Python's `hashlib.sha256` on the UTF-8 encoding of the normalised text.
> 4. The resulting hash SHALL be represented as a lowercase hexadecimal string (64 characters).

> **FR-3411: Content Hash Lookup**
> The dedup node SHALL query Weaviate for an existing chunk whose `content_hash` property matches the computed hash.
> **Rationale:** A single indexed property lookup is the lowest-cost deduplication check available. SHA-256 collision probability is negligible for this use case.
> **Acceptance Criteria:**
> 1. The query SHALL use an exact-match filter on the `content_hash` property.
> 2. The query SHALL return at most one result (the canonical chunk).
> 3. If the Weaviate query fails due to a transient error, the node SHALL log a warning and treat the chunk as novel (no match). The chunk SHALL proceed to embedding. Silent data loss through false deduplication MUST NOT occur due to infrastructure errors.
> 4. The query SHALL execute within the configured Weaviate timeout (see `INGESTION_PLATFORM_SPEC.md` NFR requirements).

> **FR-3412: Content Hash Storage on Novel Chunks**
> When a chunk has no content-hash match in Weaviate (novel chunk), the dedup node SHALL attach the computed `content_hash` to the chunk's metadata dictionary before passing it to `embedding_storage`.
> **Rationale:** The `embedding_storage` node stores chunk metadata in Weaviate. Including `content_hash` in metadata ensures it is persisted and available for future dedup lookups.
> **Acceptance Criteria:**
> 1. The chunk's `metadata["content_hash"]` SHALL be set to the computed SHA-256 hex string.
> 2. The `embedding_storage` node SHALL persist this value as the `content_hash` Weaviate property.

> **FR-3413: Tier 1 Enabled by Default**
> Content-hash deduplication (Tier 1) SHALL be enabled whenever `config.enable_cross_document_dedup` is `true`. There SHALL be no separate toggle for Tier 1 independent of the overall dedup feature flag.
> **Rationale:** Tier 1 has near-zero computational cost (one SHA-256 per chunk, one indexed lookup per chunk). There is no practical reason to enable dedup but disable exact-match detection.
> **Acceptance Criteria:**
> 1. When `enable_cross_document_dedup` is `true`, Tier 1 content-hash dedup SHALL execute for every chunk.
> 2. No configuration key SHALL exist to disable Tier 1 while keeping Tier 2 enabled.

### 3.3 Tier 2: Fuzzy Fingerprint Deduplication (MinHash)

> **FR-3420: Tier 2 Enable Flag**
> Fuzzy-fingerprint deduplication SHALL be controlled by a dedicated configuration flag `enable_fuzzy_dedup`. This flag SHALL default to `false`. When `enable_cross_document_dedup` is `false`, Tier 2 SHALL NOT execute regardless of the `enable_fuzzy_dedup` value.
> **Rationale:** Tier 2 has higher computational cost than Tier 1 (shingle computation, MinHash signature generation, similarity estimation) and involves a similarity threshold that operators may need to tune. It SHOULD be opt-in.
> **Acceptance Criteria:**
> 1. When `enable_fuzzy_dedup` is `false` (default), Tier 2 SHALL NOT execute.
> 2. When `enable_fuzzy_dedup` is `true` and `enable_cross_document_dedup` is `true`, Tier 2 SHALL execute for chunks that did not match under Tier 1.
> 3. When `enable_cross_document_dedup` is `false`, Tier 2 SHALL NOT execute even if `enable_fuzzy_dedup` is `true`.

> **FR-3421: MinHash Fingerprint Computation**
> When Tier 2 is enabled, the dedup node SHALL compute a MinHash signature for each chunk that did not match under Tier 1. The MinHash SHALL be computed over word-level shingles (contiguous word n-grams) of the normalised text.
> **Rationale:** MinHash over word shingles provides a computationally efficient estimate of Jaccard similarity without requiring embedding computation. Word-level shingles (as opposed to character-level) provide better semantic granularity for natural-language text.
> **Acceptance Criteria:**
> 1. The shingle size (n-gram length) SHALL be configurable via `fuzzy_shingle_size`, defaulting to 3 (trigrams).
> 2. The number of hash functions in the MinHash signature SHALL be configurable via `fuzzy_num_hashes`, defaulting to 128.
> 3. The MinHash signature SHALL be computed on the same normalised text used for Tier 1 content-hash computation.
> 4. The implementation SHOULD use the `datasketch` library's `MinHash` class or an equivalent implementation producing compatible signatures.

> **FR-3422: Fuzzy Similarity Threshold**
> The similarity threshold for Tier 2 near-duplicate detection SHALL be configurable via `fuzzy_similarity_threshold`, defaulting to `0.95` (95% estimated Jaccard similarity).
> **Rationale:** A 95% default is conservative — it catches chunks that differ by minor whitespace, punctuation, or a few words while avoiding false merges of genuinely distinct content. Operators processing highly templated documents may lower the threshold; operators prioritising precision may raise it.
> **Acceptance Criteria:**
> 1. The threshold SHALL be a float in the range `[0.0, 1.0]`.
> 2. Configuration validation SHALL reject values outside this range with a clear error message.
> 3. Two chunks with estimated Jaccard similarity >= the threshold SHALL be considered near-duplicates.
> 4. Two chunks with estimated Jaccard similarity < the threshold SHALL NOT be considered near-duplicates.

> **FR-3423: Fuzzy Fingerprint Lookup**
> When Tier 2 is enabled, the dedup node SHALL compare the current chunk's MinHash signature against stored fingerprints of existing chunks in Weaviate. The comparison SHALL estimate Jaccard similarity and identify the best match above the configured threshold.
> **Rationale:** The fingerprint index enables sub-linear lookup for near-duplicates without scanning all stored chunks.
> **Acceptance Criteria:**
> 1. The lookup SHALL return the single best match (highest similarity) above the threshold, if any.
> 2. If multiple stored chunks exceed the threshold, the one with the highest similarity SHALL be selected as the canonical chunk.
> 3. If no stored chunk exceeds the threshold, the chunk SHALL be treated as novel.
> 4. The `fuzzy_fingerprint` property SHALL be stored on novel chunks to enable future Tier 2 lookups.
> 5. If the lookup fails due to a transient error, the node SHALL log a warning and treat the chunk as novel. The same fail-safe principle from FR-3411 applies: no silent data loss through false deduplication.

> **FR-3424: Canonical Chunk Selection for Fuzzy Matches**
> When a Tier 2 fuzzy match is found, the system SHALL keep the longer chunk as the canonical chunk. If the existing stored chunk is shorter than the incoming chunk, the stored chunk SHALL be replaced by the incoming chunk (content, content_hash, and fuzzy_fingerprint updated), and the existing chunk's source document SHALL be retained in the `source_documents` array.
> **Rationale:** The longer chunk preserves more context. When a chunk is trimmed slightly in one document but appears in full in another, the full version is more useful for retrieval.
> **Acceptance Criteria:**
> 1. When the incoming chunk is longer (by character count of normalised text) than the existing canonical chunk, the canonical chunk's text, embedding, content_hash, and fuzzy_fingerprint SHALL be updated to reflect the incoming chunk.
> 2. When the incoming chunk is shorter than or equal in length to the existing canonical chunk, the existing chunk SHALL remain unchanged except for `source_documents` being appended.
> 3. When the canonical chunk is replaced, the old content_hash SHALL be removed from the index and the new content_hash SHALL be indexed.

### 3.4 Back-Reference Model (source_documents Array)

> **FR-3430: source_documents Array Initialisation**
> Every chunk stored in Weaviate SHALL have a `source_documents` property containing an array of source document identifiers. When a chunk is first stored (novel chunk, no dedup match), `source_documents` SHALL be initialised to a single-element array containing the chunk's `source_key`.
> **Rationale:** Uniform schema — every chunk has a `source_documents` array, whether it has been deduplicated or not. This simplifies retrieval logic, which can always iterate the array for citations.
> **Acceptance Criteria:**
> 1. A novel chunk's `source_documents` SHALL equal `[source_key]` where `source_key` is the current document's stable identity.
> 2. The `source_documents` property SHALL be of type `string[]` in the Weaviate schema.
> 3. The `embedding_storage` node SHALL persist `source_documents` from chunk metadata.

> **FR-3431: source_documents Append on Merge**
> When a chunk is identified as a duplicate (Tier 1 or Tier 2) of an existing canonical chunk, the dedup node SHALL append the current document's `source_key` to the canonical chunk's `source_documents` array in Weaviate via a partial update.
> **Rationale:** The back-reference array is the mechanism by which retrieval can trace a single canonical chunk back to all documents that contained it. This is the core value proposition: unique content in retrieval results with full provenance.
> **Acceptance Criteria:**
> 1. The partial update SHALL append the new `source_key` without removing existing entries.
> 2. If the `source_key` is already present in `source_documents` (e.g., re-ingestion of the same document), the node SHALL NOT create a duplicate entry. The array SHALL remain a set of unique values.
> 3. The partial update SHALL be atomic — concurrent appends to the same chunk MUST NOT lose entries.
> 4. If the partial update fails, the node SHALL log an error, treat the chunk as novel, and allow it to proceed to `embedding_storage` for independent storage. Data availability takes precedence over deduplication.

> **FR-3432: source_documents in Retrieval**
> The retrieval layer SHALL use the `source_documents` array to provide multi-document citations when returning a deduplicated chunk.
> **Rationale:** Users need to know that a piece of information appears in multiple documents. The back-reference array directly supports citation of all origin documents.
> **Acceptance Criteria:**
> 1. When a chunk with `source_documents` containing more than one entry is returned in search results, all source documents SHALL be listed in the citation metadata.
> 2. The retrieval API response SHALL include a `source_documents` field (or equivalent) for each returned chunk.

> **FR-3433: source_documents Consistency on Re-Ingestion**
> When a document is re-ingested (detected via `clean_hash` change), the system SHALL remove the document's `source_key` from the `source_documents` arrays of all canonical chunks that previously referenced it, before processing the new version's chunks through dedup.
> **Rationale:** Re-ingestion means the document's content has changed. Old back-references are stale and MUST be cleaned up to avoid pointing to content the document no longer contains.
> **Acceptance Criteria:**
> 1. Before dedup processing begins for a re-ingested document, the node SHALL query Weaviate for all chunks whose `source_documents` array contains the current `source_key`.
> 2. For each such chunk, the node SHALL remove the current `source_key` from `source_documents`.
> 3. If removing the `source_key` leaves `source_documents` empty, the chunk SHALL be deleted from Weaviate (it was only contributed by this document and is now stale).
> 4. After cleanup, the re-ingested document's chunks SHALL proceed through normal dedup processing.

### 3.5 Merge Reporting

> **FR-3440: Merge Event Schema**
> Each merge event SHALL be recorded as a structured dictionary containing the following fields:
>
> | Field | Type | Description |
> |-------|------|-------------|
> | `canonical_content_hash` | `string` | Content hash of the canonical chunk |
> | `canonical_chunk_id` | `string` | Weaviate ID of the canonical chunk |
> | `merged_source_key` | `string` | `source_key` of the document whose chunk was merged |
> | `merged_section` | `string` | Section path or heading of the merged chunk (from chunk metadata) |
> | `match_tier` | `string` | `"exact"` for Tier 1, `"fuzzy"` for Tier 2 |
> | `similarity_score` | `float` | `1.0` for exact matches; estimated Jaccard similarity for fuzzy matches |
> | `canonical_replaced` | `boolean` | `true` if the canonical chunk was replaced by a longer incoming chunk (Tier 2 only) |
> | `timestamp` | `string` | ISO 8601 timestamp of the merge event |
>
> **Rationale:** Structured merge events enable auditing, debugging, and user-facing reporting. Every merge decision is traceable.
> **Acceptance Criteria:**
> 1. Every merge event (Tier 1 or Tier 2) SHALL produce exactly one merge event record conforming to this schema.
> 2. The `dedup_merge_report` list in pipeline state SHALL contain all merge events for the current document.
> 3. No merge event SHALL be silently discarded.

> **FR-3441: Merge Report Persistence**
> The merge report for each ingestion run SHALL be persisted and made available through the ingestion result API.
> **Rationale:** Users MUST be able to review what was merged to exercise the revert mechanism (FR-3450). Merge reports that exist only in ephemeral pipeline state are insufficient.
> **Acceptance Criteria:**
> 1. The orchestrator SHALL persist the `dedup_merge_report` from pipeline state to the ingestion result record.
> 2. The merge report SHALL be queryable by `source_key` (show all merges for a given document).
> 3. The merge report SHALL be queryable by `canonical_content_hash` (show all documents merged into a given canonical chunk).
> 4. Merge reports SHALL be retained for at least as long as the corresponding chunks exist in Weaviate.

> **FR-3442: Merge Report Surfacing**
> The system SHALL surface merge reports to users through the ingestion result API, CLI output, and progress reporting channels.
> **Rationale:** Transparency is a core design principle. Users should never be surprised to learn that their content was deduplicated.
> **Acceptance Criteria:**
> 1. CLI ingestion commands SHALL display a summary of dedup activity: number of exact matches, number of fuzzy matches, number of novel chunks.
> 2. The ingestion result API SHALL include the full `dedup_merge_report` in its response payload.
> 3. Progress reporting (if enabled; see `INGESTION_PLATFORM_SPEC.md`) SHALL emit dedup statistics at node completion.

### 3.6 Revert and Override Mechanism

> **FR-3450: Per-Source Dedup Override**
> The system SHALL support a per-source override that exempts a specific source document from cross-document deduplication. When a document is ingested with `dedup_override=true`, all of its chunks SHALL be stored independently, even if they match existing canonical chunks.
> **Rationale:** Users may determine that a merge was incorrect — e.g., two chunks have identical text but carry different semantic weight in their respective documents. The override mechanism prevents the system from silently merging content that the user has explicitly flagged as distinct.
> **Acceptance Criteria:**
> 1. The override SHALL be specifiable per `source_key` via the ingestion API and CLI.
> 2. When `dedup_override=true` for a source, the `cross_document_dedup` node SHALL skip all dedup processing for that document's chunks and pass them through unmodified to `embedding_storage`.
> 3. When `dedup_override=true`, the node SHALL still compute and attach `content_hash` to chunk metadata (for future reference) but SHALL NOT query Weaviate for matches.
> 4. The override setting SHALL be persisted in the document's manifest entry so that subsequent re-ingestion of the same document respects the override without requiring the user to re-specify it.

> **FR-3451: Revert Merge Operation**
> The system SHALL provide a revert operation that undoes a specific merge: given a `source_key` and a `canonical_content_hash`, the system SHALL remove the `source_key` from the canonical chunk's `source_documents` array and re-ingest that source document's chunk as an independent entry.
> **Rationale:** Deduplication is a lossy operation (one copy is discarded). Users MUST have a path to recover from incorrect merges without re-ingesting the entire corpus.
> **Acceptance Criteria:**
> 1. The revert operation SHALL accept `source_key` and `canonical_content_hash` as inputs.
> 2. The revert operation SHALL remove the specified `source_key` from the canonical chunk's `source_documents` array.
> 3. The revert operation SHALL re-ingest the affected chunk from the specified source document with `dedup_override=true` for that chunk, creating an independent stored entry.
> 4. If the canonical chunk's `source_documents` array becomes empty after removal, the canonical chunk SHALL NOT be deleted (it may still be the original source's content).
> 5. The revert operation SHALL be idempotent — reverting an already-reverted merge SHALL be a no-op.
> 6. The revert operation SHALL generate a log entry recording the action for audit purposes.

> **FR-3452: Revert via Re-Ingestion**
> As an alternative to the targeted revert operation (FR-3451), a user SHALL be able to re-ingest a document with `dedup_override=true` to create independent copies of all its chunks, effectively reverting all merges for that document.
> **Rationale:** For cases where multiple merges from a single document are incorrect, document-level re-ingestion with the override flag is simpler than reverting individual merges.
> **Acceptance Criteria:**
> 1. Re-ingestion with `dedup_override=true` SHALL first clean up existing back-references (per FR-3433) and then store all chunks independently.
> 2. The resulting chunks SHALL have `source_documents` arrays containing only the re-ingested document's `source_key`.
> 3. Other canonical chunks that previously referenced this document SHALL have the document's `source_key` removed from their `source_documents` arrays (per FR-3433).

### 3.7 Configuration

> **FR-3460: Configuration Keys**
> The following configuration keys SHALL be supported for cross-document deduplication:
>
> | Key | Type | Default | Description |
> |-----|------|---------|-------------|
> | `enable_cross_document_dedup` | `bool` | `true` | Master toggle for the cross-document dedup node. |
> | `enable_fuzzy_dedup` | `bool` | `false` | Enable Tier 2 fuzzy fingerprint dedup (requires `enable_cross_document_dedup`). |
> | `fuzzy_similarity_threshold` | `float` | `0.95` | Minimum Jaccard similarity for Tier 2 matches. Range: [0.0, 1.0]. |
> | `fuzzy_shingle_size` | `int` | `3` | Word n-gram size for MinHash shingle computation. |
> | `fuzzy_num_hashes` | `int` | `128` | Number of hash functions in MinHash signature. |
> | `dedup_override_sources` | `list[str]` | `[]` | List of `source_key` values exempt from dedup. |
>
> **Rationale:** All dedup behaviour MUST be configurable. Operators managing different corpora (e.g., highly repetitive compliance docs vs. unique research papers) need different settings.
> **Acceptance Criteria:**
> 1. All keys SHALL be loadable from the pipeline configuration file and overridable via environment variables following existing config precedence rules (see `INGESTION_PLATFORM_SPEC.md`).
> 2. Configuration validation SHALL fail fast with a clear error if `fuzzy_similarity_threshold` is outside [0.0, 1.0].
> 3. Configuration validation SHALL fail fast with a clear error if `fuzzy_shingle_size` < 1 or `fuzzy_num_hashes` < 1.
> 4. Configuration validation SHALL emit a warning if `enable_fuzzy_dedup` is `true` but `enable_cross_document_dedup` is `false` (Tier 2 has no effect without the master toggle).

> **FR-3461: Configuration Interaction with Existing Settings**
> The `enable_cross_document_dedup` flag SHALL be independent of `enable_quality_validation`. Both nodes SHALL operate independently: quality validation handles within-document filtering and scoring; cross-document dedup handles inter-document deduplication.
> **Rationale:** An operator may wish to disable quality validation (accepting all chunks regardless of quality score) while still deduplicating across documents, or vice versa.
> **Acceptance Criteria:**
> 1. Disabling `enable_quality_validation` SHALL NOT disable cross-document dedup.
> 2. Disabling `enable_cross_document_dedup` SHALL NOT disable quality validation.
> 3. Both nodes MAY be independently enabled or disabled in any combination.

---

## 4. Non-Functional Requirements

> **NFR-3500: Dedup Lookup Latency**
> Tier 1 content-hash lookup against Weaviate SHALL complete in under 50ms per chunk at p95 for collections containing up to 1 million chunks.
> **Rationale:** The dedup node processes every chunk in sequence. High per-chunk latency would make the node a pipeline bottleneck.
> **Acceptance Criteria:**
> 1. The `content_hash` property SHALL be indexed in Weaviate (inverted index, not vector index).
> 2. Benchmark testing SHALL confirm p95 latency < 50ms for single-property exact-match queries on a 1M-chunk collection.

> **NFR-3501: Tier 1 Memory Overhead**
> Tier 1 dedup SHALL add no more than O(n) memory overhead where n is the number of chunks in the current document. The node SHALL NOT load all stored content hashes into memory.
> **Rationale:** The dedup node queries Weaviate per-chunk. It MUST NOT degrade to an in-memory set comparison that scales with total corpus size.
> **Acceptance Criteria:**
> 1. The node SHALL query Weaviate for each chunk's hash individually (or in bounded batches) rather than loading a full hash set.
> 2. Peak memory increase attributable to the dedup node SHALL not exceed 10MB for a 500-chunk document.

> **NFR-3502: Tier 2 Computational Budget**
> When Tier 2 is enabled, the additional per-chunk computation (shingle generation + MinHash signature) SHALL complete in under 10ms per chunk on a single CPU core.
> **Rationale:** Tier 2 adds computation but SHOULD NOT dominate pipeline runtime. MinHash is designed to be fast; this budget ensures the implementation does not use an inefficient algorithm.
> **Acceptance Criteria:**
> 1. Benchmark testing SHALL confirm that MinHash signature computation for a 512-token chunk completes in under 10ms on commodity hardware (4-core, 3GHz+).

> **NFR-3503: Partial Update Atomicity**
> The Weaviate partial update to append a `source_key` to `source_documents` SHALL be atomic with respect to concurrent appends to the same chunk.
> **Rationale:** While sequential document processing (Assumption A-5 in `EMBEDDING_PIPELINE_SPEC.md`) reduces concurrency risk, future parallelisation MUST NOT introduce lost-update bugs.
> **Acceptance Criteria:**
> 1. The implementation SHALL use Weaviate's PATCH endpoint or equivalent atomic array-append operation.
> 2. If Weaviate does not support atomic array append natively, the implementation SHALL use optimistic concurrency control (read-modify-write with version check) and retry on conflict.

> **NFR-3504: Graceful Degradation**
> If the dedup node encounters an unrecoverable error (e.g., Weaviate unavailable for all lookups), it SHALL pass all chunks through to `embedding_storage` unmodified and log the failure. The pipeline SHALL NOT fail due to dedup infrastructure errors.
> **Rationale:** Dedup is an optimisation. Its failure MUST NOT prevent document ingestion. Storing a duplicate is preferable to losing a document.
> **Acceptance Criteria:**
> 1. Unrecoverable dedup errors SHALL result in a `processing_log` entry of `cross_document_dedup:degraded`.
> 2. All input chunks SHALL be passed through with `content_hash` still attached (computed locally, no Weaviate dependency).
> 3. The `dedup_stats` SHALL reflect the degraded state (e.g., `degraded: true`).

---

## 5. Security and Compliance

> **SC-3510: No Content Leakage via Merge Reports**
> Merge reports SHALL include chunk identifiers and source document identifiers but SHALL NOT include the full text of matched chunks. Users with access to the merge report MUST also have access to the referenced documents to view content.
> **Rationale:** Merge reports may be exposed through APIs or logs. Including full chunk text in reports creates a secondary content store outside access control boundaries.
> **Acceptance Criteria:**
> 1. Merge event records (FR-3440) SHALL NOT contain a field with the full chunk text.
> 2. The `canonical_content_hash` and `canonical_chunk_id` fields provide lookup keys; the actual content is retrieved through normal access-controlled retrieval paths.

> **SC-3511: Dedup Override Audit Trail**
> All dedup override and revert operations SHALL be logged with the requesting user identity, timestamp, affected `source_key`, and reason (if provided).
> **Rationale:** Overrides alter the dedup behaviour for specific documents. An audit trail ensures accountability for these decisions.
> **Acceptance Criteria:**
> 1. Override and revert events SHALL be recorded in the system audit log.
> 2. Each log entry SHALL include: user identity, operation type (`override` or `revert`), `source_key`, `canonical_content_hash` (for revert), and ISO 8601 timestamp.

---

## 6. Assumptions and Constraints

| ID | Assumption / Constraint | Impact if Violated |
|----|------------------------|--------------------|
| A-CD-1 | Sequential document processing (inherited from A-5 in `EMBEDDING_PIPELINE_SPEC.md`) | Concurrent ingestion of different documents may produce race conditions on `source_documents` partial updates. Mitigated by NFR-3503 atomicity requirement. |
| A-CD-2 | Weaviate supports indexed string property queries with sub-100ms latency on collections up to 1M objects | Dedup lookup becomes a bottleneck if index performance degrades. |
| A-CD-3 | `datasketch` library (or equivalent) available in runtime environment for Tier 2 | Tier 2 cannot function without a MinHash implementation. Tier 1 has no external dependency beyond `hashlib`. |
| A-CD-4 | Chunk text is UTF-8 encoded | SHA-256 hash computation assumes UTF-8 byte representation. Non-UTF-8 text would produce incorrect hashes. |
| A-CD-5 | The `embedding_storage` node stores all metadata keys present in `chunk.metadata` to Weaviate | The dedup node attaches `content_hash`, `source_documents`, and optionally `fuzzy_fingerprint` to chunk metadata. These MUST be persisted by the storage node. |

---

## 7. Traceability Matrix

| Requirement | Design Decision | Implementation Component |
|-------------|----------------|--------------------------|
| FR-3400–FR-3403 | Dedup node between quality_validation and embedding_storage | `workflow.py`, `state.py`, `nodes/cross_document_dedup.py` |
| FR-3410–FR-3413 | Tier 1: SHA-256 content hash, near-zero cost | `nodes/cross_document_dedup.py` (hash computation + Weaviate lookup) |
| FR-3420–FR-3424 | Tier 2: MinHash fuzzy fingerprint, optional, 95% threshold default | `nodes/cross_document_dedup.py` (MinHash computation + fingerprint index) |
| FR-3430–FR-3433 | Back-reference model: `source_documents` array on canonical chunk | Weaviate schema extension, `nodes/cross_document_dedup.py`, `nodes/embedding_storage.py` |
| FR-3440–FR-3442 | Merge reporting: structured events, persisted, user-surfaced | `nodes/cross_document_dedup.py`, orchestrator, ingestion API |
| FR-3450–FR-3452 | Revert: per-source override, targeted revert, re-ingest with override | Configuration, ingestion API, `nodes/cross_document_dedup.py` |
| FR-3460–FR-3461 | Configuration: six keys, independent of quality_validation | `config/settings.py`, configuration validation |
| NFR-3500–NFR-3504 | Performance, atomicity, graceful degradation | Implementation-level concerns; validated by benchmarks and integration tests |
| SC-3510–SC-3511 | No content leakage, audit trail for overrides | Merge report schema, audit logging |

---

## 8. Open Questions

| ID | Question | Impact | Resolution Target |
|----|----------|--------|-------------------|
| OQ-1 | Should Tier 2 fingerprint comparison use a dedicated index (e.g., LSH forest) or scan stored fingerprints via Weaviate query? | Affects Tier 2 lookup performance at scale (>100K chunks). LSH forest is faster but adds infrastructure. | CROSS_DOCUMENT_DEDUP_DESIGN.md |
| OQ-2 | What is the maximum practical size of the `source_documents` array before Weaviate property update performance degrades? | Affects corpora with extremely high duplication (e.g., legal boilerplate appearing in thousands of documents). | Benchmarking during implementation |
| OQ-3 | Should the batch migration utility for retroactive dedup of historical data be specified as a separate document or an addendum to this spec? | Scoping decision for v1.1. | Product decision |

---

## Appendix A: FR ID Allocation

| ID Range | Section | Count |
|----------|---------|-------|
| FR-3400–FR-3403 | 3.1 Dedup Node Placement and Pipeline Integration | 4 |
| FR-3410–FR-3413 | 3.2 Tier 1: Content Hash Deduplication | 4 |
| FR-3420–FR-3424 | 3.3 Tier 2: Fuzzy Fingerprint Deduplication (MinHash) | 5 |
| FR-3430–FR-3433 | 3.4 Back-Reference Model | 4 |
| FR-3440–FR-3442 | 3.5 Merge Reporting | 3 |
| FR-3450–FR-3452 | 3.6 Revert and Override Mechanism | 3 |
| FR-3460–FR-3461 | 3.7 Configuration | 2 |
| NFR-3500–NFR-3504 | 4. Non-Functional Requirements | 5 |
| SC-3510–SC-3511 | 5. Security and Compliance | 2 |
| **Total** | | **32** |

Reserved for future use: FR-3462–FR-3499, FR-3453–FR-3459, FR-3434–FR-3439, FR-3443–FR-3449, FR-3414–FR-3419, FR-3425–FR-3429, FR-3500–FR-3549 (NFR/SC range).
