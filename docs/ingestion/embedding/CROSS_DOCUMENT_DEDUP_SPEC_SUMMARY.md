# Cross-Document Deduplication — Specification Summary

> **Document type:** Specification summary (Layer 2)
> **Upstream:** CROSS_DOCUMENT_DEDUP_SPEC.md
> **Last updated:** 2026-04-15

---

## 1) System Overview

### Purpose

When an organisation ingests hundreds of documents, substantial content overlap is common. The same paragraph may appear verbatim in a specification, an onboarding guide, and a runbook. Near-identical content — differing only in whitespace, formatting, or minor phrasing — compounds the problem. Without cross-document deduplication, these duplicates degrade the retrieval system in three ways: duplicate chunks consume retrieval slots that could surface diverse context, each duplicate is independently embedded and stored at wasted cost, and retrieval scores are artificially inflated for frequently-duplicated boilerplate rather than uniquely relevant material. Existing within-document deduplication handles duplicates inside a single document but cannot detect duplicates across documents because it has no access to previously stored content.

### Pipeline Flow

A new deduplication node is inserted into the embedding pipeline between quality validation and vector storage. For each chunk that survives quality filtering, the node computes a content hash from normalised text and queries the vector store for an exact match. If a match is found, the chunk is not stored independently — instead, the current document's identity is appended to the existing canonical chunk's back-reference array, preserving provenance across all contributing documents. If no exact match is found and optional fuzzy deduplication is enabled, a locality-sensitive hash fingerprint is computed and compared against stored fingerprints to detect near-duplicates above a configurable similarity threshold. When a fuzzy match is found, the longer chunk is kept as canonical. Chunks with no match in either tier pass through to storage as novel entries with their content hash attached for future lookups. A structured merge report records every deduplication decision for auditing and user review.

### Tunable Knobs

Operators can enable or disable the entire deduplication feature, independently enable or disable the fuzzy deduplication tier, set the similarity threshold for near-duplicate detection, configure the shingle size and hash function count for fingerprint computation, and maintain a list of source documents exempt from deduplication. All settings are independent of the quality validation toggle, allowing any combination.

### Design Rationale

Two principles govern the design. Data availability takes precedence over deduplication — if the deduplication infrastructure encounters an error, chunks pass through to storage rather than being lost. Transparency over automation means every merge decision is recorded in a structured report, users are notified of deduplication activity, and a revert mechanism exists to undo incorrect merges without re-ingesting the entire corpus.

### Boundary Semantics

The node's entry point is the filtered chunk list from quality validation. Its exit point is a deduplicated chunk list passed to the vector storage node, plus a merge report in pipeline state. The node queries the vector store for existing content hashes and updates back-reference arrays via partial updates, but it does not own chunk embedding or final storage — those remain downstream responsibilities. Re-ingestion of a changed document cleans up stale back-references before processing new chunks through deduplication.

---

## 2) Scope and Boundaries

**Entry point:** Filtered chunk list from `quality_validation` node in the Embedding Pipeline DAG.

**Exit point:** Deduplicated chunk list passed to `embedding_storage` node, plus `dedup_merge_report` and `dedup_stats` in pipeline state.

**In scope:** Tier 1 exact content-hash dedup (SHA-256), Tier 2 optional fuzzy-fingerprint dedup (MinHash), back-reference model (`source_documents` array), merge reporting, per-source override and revert mechanism, configuration surface.

**Out of scope:** Within-document deduplication (handled by quality_validation), vector-similarity deduplication (rejected as disproportionately expensive), retroactive deduplication of historical data, semantic/paraphrase deduplication, chunk merging or rewriting, KG triple deduplication.

---

## 3) Dedup Node Placement and Pipeline Integration (FR-3400–FR-3403)

The `cross_document_dedup` node is positioned after `quality_validation` and before `embedding_storage` (FR-3400), replacing the direct edge between them. This placement ensures low-quality and within-document duplicate chunks are already filtered (minimising hash lookups) and dedup occurs before embedding computation (avoiding wasted GPU/API calls). The node conforms to the standard `EmbeddingPipelineState` contract (FR-3401). When disabled via `enable_cross_document_dedup`, the node returns the unmodified chunk list immediately (FR-3402). Pipeline state is extended with `dedup_merge_report` and `dedup_stats` fields (FR-3403).

---

## 4) Tier 1: Content Hash Deduplication (FR-3410–FR-3413)

For each chunk, a SHA-256 hash is computed over normalised text — whitespace-trimmed, interior whitespace collapsed, case preserved (FR-3410). The hash is looked up in Weaviate via an indexed exact-match query (FR-3411). On transient errors, the chunk is treated as novel to prevent silent data loss through false deduplication. Novel chunks receive the hash in their metadata for future lookups (FR-3412). Tier 1 is always enabled when dedup is active — there is no separate toggle because the computational cost is near-zero (FR-3413).

Key decision: SHA-256 collision probability is negligible. Case is preserved because case differences in technical documentation may indicate meaningfully different content.

---

## 5) Tier 2: Fuzzy Fingerprint Deduplication (FR-3420–FR-3424)

Tier 2 is opt-in via `enable_fuzzy_dedup` (default false) and only runs for chunks that did not match under Tier 1 (FR-3420). MinHash signatures are computed over word-level shingles of normalised text, with configurable shingle size (default 3) and hash function count (default 128) (FR-3421). The similarity threshold defaults to 0.95 (95% estimated Jaccard similarity), balancing detection of formatting-only differences against false merges (FR-3422). The best match above threshold is selected as canonical (FR-3423). When a fuzzy match is found, the longer chunk becomes or remains canonical, preserving maximum context (FR-3424).

Key trade-off: Tier 2 has higher computational cost than Tier 1 but catches near-duplicates that differ by minor whitespace, punctuation, or a few words. The 95% default is conservative.

---

## 6) Back-Reference Model (FR-3430–FR-3433)

Every stored chunk has a `source_documents` array initialised to a single element (FR-3430). On merge, the current document's identity is appended via atomic partial update (FR-3431) — no duplicate entries, concurrent appends must not lose data. The retrieval layer uses this array for multi-document citations (FR-3432). On re-ingestion of a changed document, stale back-references are cleaned up before new chunks are processed (FR-3433) — if removal leaves the array empty, the chunk is deleted as it was contributed only by the changed document.

Key decision: the back-reference model provides unique content in retrieval results with full provenance, directly addressing the top-K crowding problem.

---

## 7) Merge Reporting (FR-3440–FR-3442)

Each merge event is recorded as a structured dictionary with canonical chunk identity, merged source identity, match tier, similarity score, whether the canonical was replaced, and timestamp (FR-3440). Reports are persisted and queryable by source_key or canonical_content_hash (FR-3441). Reports are surfaced through CLI output, ingestion API responses, and progress reporting channels (FR-3442).

---

## 8) Revert and Override Mechanism (FR-3450–FR-3452)

A per-source override (FR-3450) exempts a document from dedup, storing all its chunks independently. The override is persisted in the manifest so subsequent re-ingestion respects it automatically. A targeted revert operation (FR-3451) undoes a specific merge by removing a source from a canonical chunk's back-references and re-ingesting that chunk independently. Alternatively, full document re-ingestion with the override flag (FR-3452) reverts all merges for that document.

---

## 9) Configuration (FR-3460–FR-3461)

Six configuration keys control dedup behaviour: master toggle (`enable_cross_document_dedup`, default true), fuzzy toggle (`enable_fuzzy_dedup`, default false), similarity threshold (0.95), shingle size (3), hash count (128), and exempt source list (FR-3460). The dedup feature is independent of quality validation — both can be enabled or disabled in any combination (FR-3461).

---

## 10) Non-Functional and Security Themes

- **Performance:** Tier 1 lookup completes in under 50ms at p95 for 1M-chunk collections (NFR-3500). Tier 1 adds only O(n) memory for the current document's chunks (NFR-3501). Tier 2 MinHash computation completes in under 10ms per chunk (NFR-3502).
- **Atomicity:** Partial updates to `source_documents` are atomic with respect to concurrent appends (NFR-3503).
- **Graceful degradation:** Unrecoverable dedup errors pass all chunks through to storage (NFR-3504). Dedup is an optimisation — its failure must not prevent ingestion.
- **Security:** Merge reports contain identifiers only, not full chunk text (SC-3510). Override and revert operations are audit-logged with user identity (SC-3511).

---

## 11) Key Design Decisions

- **Two-tier architecture (hash + fingerprint):** Exact-match hash covers identical content at near-zero cost. Optional fuzzy fingerprint catches formatting-only differences without requiring embedding computation. Vector-similarity (Tier 3) was rejected as disproportionately expensive.
- **Placed after quality validation, before embedding:** Minimises lookup cost (fewer chunks) and avoids wasted embedding computation (duplicates eliminated first).
- **Longer chunk wins for fuzzy matches:** When near-duplicates differ in length, the longer version preserves more context for retrieval.
- **Back-reference array on canonical chunk:** Provides multi-document citation without storing duplicate content. Uniform schema — every chunk has the array, deduplicated or not.
- **Fail-safe on infrastructure errors:** Transient Weaviate errors cause the chunk to be treated as novel. Data availability always takes precedence over deduplication.
- **Revert without full re-ingestion:** Targeted undo of individual merges prevents one incorrect dedup decision from requiring corpus-wide re-processing.

---

## 12) Requirement Summary

The spec covers **32 requirements** across functional, non-functional, and security domains:

| ID Range | Domain | Count |
|----------|--------|-------|
| FR-3400–FR-3403 | Dedup Node Placement and Integration | 4 |
| FR-3410–FR-3413 | Tier 1: Content Hash Dedup | 4 |
| FR-3420–FR-3424 | Tier 2: Fuzzy Fingerprint Dedup | 5 |
| FR-3430–FR-3433 | Back-Reference Model | 4 |
| FR-3440–FR-3442 | Merge Reporting | 3 |
| FR-3450–FR-3452 | Revert and Override | 3 |
| FR-3460–FR-3461 | Configuration | 2 |
| NFR-3500–NFR-3504 | Non-Functional Requirements | 5 |
| SC-3510–SC-3511 | Security and Compliance | 2 |

---

## 13) Companion Documents

| Document | Purpose |
|----------|---------|
| CROSS_DOCUMENT_DEDUP_SPEC.md | Authoritative requirements specification — source of truth |
| CROSS_DOCUMENT_DEDUP_SPEC_SUMMARY.md (this document) | Stakeholder-ready digest |
| CROSS_DOCUMENT_DEDUP_DESIGN.md | Design document and task decomposition |
| EMBEDDING_PIPELINE_SPEC.md | Embedding Pipeline functional requirements (FR-591–FR-1399) |
| INGESTION_PLATFORM_SPEC.md | Cross-cutting platform requirements |

---

## 14) Sync Status

- **Spec version aligned to:** CROSS_DOCUMENT_DEDUP_SPEC.md v1.0.0
- **Last synced:** 2026-04-15
- **Sync method:** Manual review
