> **⚠ DRAFT — PRE-IMPLEMENTATION DESIGN RATIONALE**
>
> This document was authored **before** source code existed and has not been validated against a running implementation. File paths, CLI syntax, error messages, and troubleshooting sections are **speculative**. Sections that claim post-implementation knowledge (Operations, Troubleshooting, exact module paths, performance numbers) are provisional until the code lands.
>
> To be **fully rewritten post-implementation** using `/write-engineering-guide` (which now enforces a non-skippable existence check). For authoritative content prior to rewrite, consult the companion `CROSS_DOCUMENT_DEDUP_SPEC.md`, `CROSS_DOCUMENT_DEDUP_DESIGN.md`, and `CROSS_DOCUMENT_DEDUP_IMPLEMENTATION.md`.
>
> **Salvage audit:** Architecture Overview (§1), Data Flow (§2), and Extension Guide (§4) survive rewrite. Operations (§3) and Troubleshooting (§5) — which reference APIs like `get_ingestion_result()` that may not exist as specified — will be fully regenerated.

---

> **Document type:** Engineering guide (Layer 5)
> **Upstream:** CROSS_DOCUMENT_DEDUP_IMPLEMENTATION.md
> **Last updated:** 2026-04-15
> **Status:** DRAFT (pre-implementation)

# Cross-Document Deduplication — Engineering Guide (v1.0.0-draft)

| Field | Value |
|-------|-------|
| **Document** | Cross-Document Deduplication Engineering Guide |
| **Version** | 1.0.0 |
| **Status** | Active |
| **Implementation Reference** | `CROSS_DOCUMENT_DEDUP_IMPLEMENTATION.md` v1.0.0 |
| **Spec Reference** | `CROSS_DOCUMENT_DEDUP_SPEC.md` v1.0.0 (FR-3400–FR-3461, NFR-3500–NFR-3504) |
| **Created** | 2026-04-15 |
| **Last Updated** | 2026-04-15 |

---

## 1. Architecture Overview

### 1.1 Where Dedup Sits in the Pipeline

The cross-document dedup node occupies a single position in the Embedding Pipeline DAG:

```
... -> quality_validation -> cross_document_dedup -> embedding_storage -> ...
```

This placement is load-bearing. The node must run:

- **After `quality_validation`** because within-document duplicates and low-quality chunks are
  already removed. The dedup node operates on the smallest surviving set, which minimises
  Weaviate lookups per document.
- **Before `embedding_storage`** because duplicate chunks are eliminated before embedding API
  calls. Every chunk removed by dedup saves one embedding computation and one Weaviate write.

Both phases belong to the Embedding Pipeline (Phase 2 of the two-phase ingestion architecture).
The dedup node has no interaction with Phase 1 (Document Processing). Its only external
dependency is the Weaviate client provided via `runtime.weaviate_client`.

### 1.2 Key Architecture Decisions

| Decision | Rationale | Trade-off |
|----------|-----------|-----------|
| Two-tier architecture (exact hash + optional fuzzy) | Tier 1 is near-zero cost. Tier 2 adds compute but catches whitespace/punctuation-only differences. Separating them lets operators adopt incrementally. | Tier 2 scan is O(n) over stored fingerprints in v1. Acceptable under 100K chunks; LSH forest deferred to v1.1. |
| Weaviate as the dedup index (no separate store) | Avoids a second infrastructure dependency. `content_hash` is indexed for fast exact-match queries. | Tier 2 cannot use Weaviate's native vector search for fingerprint comparison — it deserialises and compares in Python. |
| Graceful degradation on Weaviate errors | Dedup is an optimisation. Storing a duplicate is preferable to failing a document ingestion. | A degraded run produces duplicates. The `degraded` flag in `dedup_stats` signals this for later cleanup. |
| Longer-chunk-wins for fuzzy canonical selection | The longer chunk preserves more retrieval context. | Requires a Weaviate content update (text + embedding + hashes) when the incoming chunk wins, which is more expensive than a simple back-reference append. |
| `source_documents` array on every chunk | Uniform schema simplifies retrieval — always iterate the array for citations, whether the chunk was deduplicated or not. | Small storage overhead per chunk (single-element array for non-deduplicated chunks). |

### 1.3 Component Map

```
src/ingest/embedding/
├── common/
│   ├── types.py                        # MergeEvent TypedDict, create_merge_event()
│   └── dedup_utils.py                  # Tier 1 engine: normalise, hash, Weaviate lookup/update
├── nodes/
│   ├── cross_document_dedup.py         # Node function (orchestrates Tier 1 + Tier 2)
│   ├── quality_validation.py           # Upstream node (within-document dedup + quality filter)
│   └── embedding_storage.py            # Downstream node (persists dedup metadata to Weaviate)
├── support/
│   └── minhash_engine.py               # Tier 2 engine: fingerprint, similarity, lookup
├── state.py                            # EmbeddingPipelineState (dedup_merge_report, dedup_stats)
└── workflow.py                         # DAG wiring (edge insertion)

src/vector_db/
└── ...                                 # ensure_collection() — schema with content_hash, etc.

tests/ingest/embedding/
├── test_cross_document_dedup.py        # Node unit tests (mocked Weaviate)
├── test_content_hash.py                # Normalisation + hash contract tests
├── test_minhash_engine.py              # Fingerprint + threshold boundary tests
└── test_dedup_integration.py           # End-to-end with Weaviate test collection
```

---

## 2. Data Flow

### 2.1 Tier 1: Content Hash Flow

Tier 1 runs for every chunk when `enable_cross_document_dedup` is `true`. It has near-zero
computational cost: one `hashlib.sha256` call and one indexed Weaviate query per chunk.

**Step-by-step example:**

Suppose Document B is being ingested and contains a chunk with the text
`"ASIC design requires careful clock domain crossing analysis."`. Document A was ingested
previously and stored a chunk with identical text.

```
1. quality_validation passes the chunk through (it survived quality + within-doc dedup).

2. cross_document_dedup_node receives the chunk.

3. Normalise text:
   Input:  "  ASIC design requires careful clock domain crossing analysis.  \n"
   Output: "ASIC design requires careful clock domain crossing analysis."

4. Compute SHA-256:
   hashlib.sha256(b"ASIC design requires careful clock domain crossing analysis.").hexdigest()
   -> "a3f7c1...d902e4"

5. Query Weaviate:
   Filter: content_hash == "a3f7c1...d902e4"
   Result: existing chunk found (UUID: "abc-123", source_documents: ["doc_a"])

6. Match found -> merge:
   a. Append "doc_b" to canonical chunk's source_documents:
      Weaviate PATCH: source_documents = ["doc_a", "doc_b"]
   b. Record MergeEvent:
      {
        canonical_content_hash: "a3f7c1...d902e4",
        canonical_chunk_id: "abc-123",
        merged_source_key: "doc_b",
        merged_section: "3.1 Clock Domain Crossing",
        match_tier: "exact",
        similarity_score: 1.0,
        canonical_replaced: false,
        timestamp: "2026-04-15T14:32:00Z"
      }
   c. Remove chunk from output list (it will NOT be passed to embedding_storage).

7. Stats: exact_matches += 1
```

When no match is found, the chunk flows through with `content_hash` attached to its metadata:

```
chunk.metadata["content_hash"] = "a3f7c1...d902e4"
chunk.metadata["source_documents"] = ["doc_b"]
-> passed to embedding_storage, which persists both values to Weaviate.
```

### 2.2 Tier 2: MinHash Flow

Tier 2 runs only when `enable_fuzzy_dedup` is `true` and only for chunks that did NOT match
under Tier 1. It uses MinHash locality-sensitive hashing to estimate Jaccard similarity.

**Step-by-step example:**

Document C contains a chunk `"ASIC design requires careful clock-domain crossing analysis and verification."` — similar to the canonical chunk from Document A but not identical (hyphenated "clock-domain", added "and verification").

```
1. Tier 1 hash: different from canonical (text differs) -> no exact match.

2. Tier 2 activates (enable_fuzzy_dedup = true):

3. Normalise text (same normalisation as Tier 1):
   "ASIC design requires careful clock-domain crossing analysis and verification."

4. Generate word shingles (shingle_size=3):
   ["ASIC design requires", "design requires careful",
    "requires careful clock-domain", "careful clock-domain crossing",
    "clock-domain crossing analysis", "crossing analysis and",
    "analysis and verification."]

5. Compute MinHash signature (num_hashes=128):
   mh = MinHash(num_perm=128)
   for shingle in shingles: mh.update(shingle.encode("utf-8"))
   fingerprint = mh.hashvalues.tobytes().hex()  -> "0a4b9f..."

6. Scan Weaviate for stored fingerprints:
   Query: all chunks where fuzzy_fingerprint is not null (limit 10,000)
   For each: deserialise stored fingerprint, estimate Jaccard similarity.
   Best match: canonical chunk "abc-123" with similarity 0.97

7. 0.97 >= threshold (0.95) -> fuzzy match found.

8. Canonical selection — longer chunk wins:
   Incoming chunk (72 chars) > stored chunk (60 chars)
   -> Replace canonical: update text, embedding, content_hash, fuzzy_fingerprint in Weaviate.
   -> canonical_replaced = true

9. Append "doc_c" to source_documents: ["doc_a", "doc_b", "doc_c"]

10. Record MergeEvent with match_tier="fuzzy", similarity_score=0.97, canonical_replaced=true.

11. Stats: fuzzy_matches += 1
```

**Performance note:** The Tier 2 scan loads up to 10,000 fingerprints from Weaviate and
compares each in Python. This is acceptable for corpora under 100K chunks. If you are
approaching that limit, the design anticipates a `datasketch.MinHashLSH` index in v1.1.

### 2.3 Merge and Back-Reference Flow

Every merge event — whether Tier 1 or Tier 2 — follows the same back-reference update pattern:

```
                  ┌─────────────────────────────────┐
                  │  Canonical chunk in Weaviate     │
                  │  UUID: "abc-123"                 │
                  │  source_documents: ["doc_a"]     │
                  └──────────────┬──────────────────┘
                                 │
            Ingest doc_b with matching chunk
                                 │
                                 ▼
                  ┌─────────────────────────────────┐
                  │  Weaviate PATCH:                 │
                  │  source_documents: ["doc_a",     │
                  │                     "doc_b"]     │
                  └──────────────┬──────────────────┘
                                 │
            Ingest doc_c with matching chunk
                                 │
                                 ▼
                  ┌─────────────────────────────────┐
                  │  Weaviate PATCH:                 │
                  │  source_documents: ["doc_a",     │
                  │                     "doc_b",     │
                  │                     "doc_c"]     │
                  └─────────────────────────────────┘
```

**Deduplication guarantee:** `append_source_document()` checks whether `source_key` is already
present before appending. Re-ingesting the same document does not create duplicate entries in the
array.

**Re-ingestion cleanup:** When a document is re-ingested (content changed), the node first calls
`remove_source_document_refs(client, source_key)` which:

1. Finds all chunks whose `source_documents` contains this `source_key`.
2. Removes the `source_key` from each array.
3. Deletes any chunk whose `source_documents` becomes empty (that chunk existed only because of
   this document).

This cleanup runs before the dedup loop, so the re-ingested document's chunks compete fresh
against the current state of the store.

### 2.4 Merge Report Generation

Each merge event is recorded as a `MergeEvent` TypedDict (defined in
`src/ingest/embedding/common/types.py`). The full list of merge events for the current document
is returned as `dedup_merge_report` in the node's partial state update.

The report is surfaced at three levels:

1. **Pipeline state:** `dedup_merge_report` and `dedup_stats` are available to downstream nodes
   and the orchestrator.
2. **Orchestrator persistence:** `EmbeddingResult` includes `dedup_merge_report` and
   `dedup_stats`, persisted to the ingestion result record via Temporal activity results.
3. **CLI output:** A summary line is printed after ingestion:
   ```
   Dedup: 12 exact, 3 fuzzy, 85 novel
   ```

**Security constraint (SC-3510):** Merge events contain chunk identifiers and source keys but
never full chunk text. Content is accessible only through normal access-controlled retrieval.

---

## 3. Operations Guide

### 3.1 Viewing Merge Reports

After ingestion, merge reports are available through the ingestion result API. To inspect merges
for a specific document:

```python
# Via the ingestion result record
result = get_ingestion_result(source_key="doc_b")
for event in result.dedup_merge_report:
    print(f"  {event['match_tier']} match -> canonical {event['canonical_chunk_id'][:8]}... "
          f"(sim={event['similarity_score']:.2f})")
```

To find all documents merged into a specific canonical chunk:

```python
# Query merge reports by canonical_content_hash
events = query_merge_events(canonical_content_hash="a3f7c1...d902e4")
for event in events:
    print(f"  Source: {event['merged_source_key']} ({event['match_tier']})")
```

The CLI also outputs a summary line immediately after ingestion completes. Check the
`dedup_stats` for overall numbers:

```python
stats = result.dedup_stats
# {
#   "total_input_chunks": 100,
#   "exact_matches": 12,
#   "fuzzy_matches": 3,
#   "novel_chunks": 85,
#   "degraded": False
# }
```

### 3.2 Reverting a Merge

If a merge was incorrect (two chunks have identical text but different semantic weight in their
documents), you have two options:

**Option 1: Targeted revert** (undo one specific merge)

```python
from src.ingest.embedding.common.dedup_utils import find_chunk_by_content_hash
# Provide source_key and the canonical_content_hash from the merge report.
reverted = revert_merge(
    client=weaviate_client,
    source_key="doc_b",
    canonical_content_hash="a3f7c1...d902e4",
)
# reverted=True: source_key removed from canonical's source_documents.
# Then re-ingest doc_b with --dedup-override to create independent chunks.
```

The `revert_merge` function is idempotent. Calling it twice for the same source_key and hash
is a safe no-op.

**Option 2: Document-level override** (undo all merges for a document)

```bash
# CLI: re-ingest with override flag
ragweave ingest --source doc_b.md --dedup-override
```

This first cleans all existing back-references for `doc_b` (via `remove_source_document_refs`),
then stores all chunks independently with `source_documents = ["doc_b"]`.

### 3.3 Re-ingesting with Dedup Override

The `--dedup-override` flag (CLI) or `dedup_override=true` parameter (API) exempts a source
from cross-document dedup during ingestion:

```bash
# CLI
ragweave ingest --source compliance_boilerplate.md --dedup-override

# API
POST /ingest
{
  "source_path": "compliance_boilerplate.md",
  "dedup_override": true
}
```

When overridden:

- `content_hash` is still computed and attached to chunk metadata (for future reference).
- No Weaviate lookups are performed (no hash or fingerprint queries).
- All chunks are stored independently.
- The override is persisted in the document's manifest entry, so future re-ingestion of the
  same document respects it automatically.

To add a persistent override without re-ingesting, add the source_key to
`dedup_override_sources` in the configuration file.

### 3.4 Monitoring Dedup Metrics

The `dedup_stats` dictionary provides the key operational metrics:

| Metric | Meaning | Action if unexpected |
|--------|---------|---------------------|
| `exact_matches` | Chunks eliminated by Tier 1 (identical content) | High count on unrelated documents may indicate a normalisation bug. |
| `fuzzy_matches` | Chunks eliminated by Tier 2 (near-identical) | High count may mean the threshold is too low. |
| `novel_chunks` | Chunks passed through (no match found) | Should be the majority for unique content. |
| `total_input_chunks` | Chunks received from quality_validation | Sanity check: `exact + fuzzy + novel = total`. |
| `degraded` | `true` if the node fell back to passthrough due to Weaviate errors | Investigate Weaviate connectivity. All chunks were stored without dedup. |

The processing log entry for the node is one of:

- `cross_document_dedup:ok` — normal operation.
- `cross_document_dedup:skipped` — feature disabled via config.
- `cross_document_dedup:degraded` — Weaviate error, chunks passed through.

---

## 4. Extension Guide

### 4.1 Adding a New Dedup Tier

The two-tier design is explicitly extensible. To add a Tier 3 (for example, embedding-based
semantic dedup):

1. **Create the engine module.** Place it in `src/ingest/embedding/support/`, following the
   pattern of `minhash_engine.py`. The module must expose:
   - A `compute_*` function that produces a fingerprint/signature from chunk text.
   - A `find_chunk_by_*` function that queries Weaviate for matches.

2. **Add a private helper in the dedup node.** Follow the `_try_fuzzy_dedup` pattern in
   `cross_document_dedup.py`:

   ```python
   def _try_tier3_dedup(client, chunk, content_hash, source_key, config, merge_report) -> bool:
       """Attempt Tier 3 dedup. Returns True if merged."""
       from src.ingest.embedding.support.semantic_engine import (
           compute_semantic_fingerprint,
           find_chunk_by_semantic_similarity,
       )
       # ... compute, query, merge if match, return True/False
   ```

3. **Wire it into the main loop.** In `cross_document_dedup_node`, after the Tier 2 block:

   ```python
   # --- Tier 3: semantic similarity (FR-XXXX) ---
   if getattr(config, "enable_semantic_dedup", False):
       tier3_match = _try_tier3_dedup(...)
       if tier3_match:
           tier3_matches += 1
           continue
   ```

4. **Extend configuration.** Add the new toggle and parameters to `IngestionConfig` in
   `src/ingest/common/types.py`. Add validation rules.

5. **Extend stats.** Add a `tier3_matches` counter to `dedup_stats`.

6. **Add tests.** Follow the pattern in `test_minhash_engine.py` for unit tests and
   `test_dedup_integration.py` for end-to-end.

### 4.2 Customizing Normalization

The normalisation function lives in `src/ingest/embedding/common/dedup_utils.py`:

```python
_WHITESPACE_RE = re.compile(r"\s+")

def normalise_chunk_text(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text.strip())
```

This normalisation is shared by both Tier 1 (hash) and Tier 2 (MinHash shingles). If you need
to change it, be aware of these consequences:

- **Hash invalidation:** Changing normalisation changes the SHA-256 output. Existing
  `content_hash` values in Weaviate will no longer match newly computed hashes for the same
  text. You must either accept that historical chunks will not be dedup-matched, or run a
  batch re-hash migration.
- **Tier 2 fingerprint invalidation:** MinHash fingerprints are computed on normalised text.
  Changing normalisation invalidates stored fingerprints.

Common customisation scenarios:

| Need | Change | Risk |
|------|--------|------|
| Case-insensitive dedup | Add `.lower()` after `text.strip()` | "VHDL" and "vhdl" will merge. Spec explicitly preserves case (FR-3410 AC-2). |
| Strip punctuation | Add `re.sub(r"[^\w\s]", "", ...)` | "U.S.A." and "USA" will merge. May cause false positives on code snippets. |
| Unicode normalisation | Add `unicodedata.normalize("NFC", ...)` | Minimal risk. Handles composed vs. decomposed Unicode. |

If you change normalisation, update the contract tests in `test_content_hash.py` to reflect the
new expected behaviour.

### 4.3 Adjusting Similarity Thresholds

The fuzzy similarity threshold controls how aggressively Tier 2 merges near-duplicates:

| Threshold | Behaviour | When to use |
|-----------|-----------|-------------|
| 0.99 | Only merges chunks that differ by one or two words | High-precision environments where false merges are costly |
| 0.95 (default) | Merges chunks with minor phrasing, punctuation, or whitespace differences | General-purpose. Good balance for technical documentation. |
| 0.90 | Merges chunks with moderate differences (a few sentences rewritten) | Highly templated corpora (legal boilerplate, compliance docs) |
| 0.80 | Aggressive merging, high risk of false positives | Not recommended for production without manual review |

To change the threshold:

```yaml
# config/settings.yaml
ingestion:
  fuzzy_similarity_threshold: 0.92
```

Or via environment variable:

```bash
export RAGWEAVE_FUZZY_THRESHOLD=0.92
```

**Tuning workflow:**

1. Run ingestion with `enable_fuzzy_dedup: true` at the default threshold.
2. Review the merge report. Check `similarity_score` on fuzzy merge events.
3. If false positives appear (distinct chunks merged), raise the threshold.
4. If obvious near-duplicates are missed, lower the threshold.
5. Use `--dedup-override` to fix individual false merges while tuning.

The `fuzzy_shingle_size` and `fuzzy_num_hashes` parameters also affect similarity estimation:

- **Shingle size (`fuzzy_shingle_size`):** Larger shingles (4-5) make the estimate more
  sensitive to word-order differences. Smaller shingles (2) are more forgiving. Default 3 is
  a good balance.
- **Number of hashes (`fuzzy_num_hashes`):** More hashes (256) give a more accurate Jaccard
  estimate but increase fingerprint storage size and comparison time. Default 128 is sufficient
  for most corpora.

---

## 5. Troubleshooting

### 5.1 False Positive Merges

**Symptom:** Two chunks from different documents are merged even though they carry different
semantic weight or context.

**Diagnosis:**

1. Check the merge report for the affected document:
   ```python
   result = get_ingestion_result(source_key="doc_b")
   for e in result.dedup_merge_report:
       if e["canonical_chunk_id"] == "<suspect_uuid>":
           print(e)
   ```
2. If `match_tier` is `"exact"`, the chunks have identical normalised text. This is a correct
   merge by the system's rules — the chunks really are the same text. The problem is that the
   user considers them semantically distinct despite textual identity.
3. If `match_tier` is `"fuzzy"`, check `similarity_score`. If it is close to the threshold
   (e.g., 0.951 with threshold 0.95), raising the threshold slightly will prevent this merge.

**Resolution:**

- For exact matches of text you want stored independently: use `--dedup-override` for the
  affected source.
- For fuzzy matches: raise `fuzzy_similarity_threshold` or use `--dedup-override`.
- For persistent exemption: add the source_key to `dedup_override_sources` in config.

### 5.2 Missing Back-References

**Symptom:** A chunk's `source_documents` array does not include a source that you know
contains the same content.

**Diagnosis:**

1. Was the document ingested after the dedup feature was enabled? Chunks ingested before the
   feature was deployed do not have `content_hash` values. Tier 1 cannot match them. This is
   by design (no backfill in v1).
2. Did the dedup node degrade? Check the processing log for `cross_document_dedup:degraded`.
   If the node degraded, the chunk was stored independently without checking for matches.
3. Was the source in `dedup_override_sources`? Overridden sources skip dedup lookups.
4. Did normalisation produce different results? Compare the normalised text of both chunks.
   Subtle Unicode differences (e.g., non-breaking space U+00A0 vs. regular space U+0020) can
   cause different hashes.

**Resolution:**

- Re-ingest the affected document (without override) to trigger fresh dedup lookups.
- If you need to backfill `content_hash` on historical chunks, a batch utility is planned for
  v1.1 (see spec OQ-3).

### 5.3 Performance Issues

**Symptom:** Ingestion slows down significantly after enabling dedup.

**Tier 1 performance:**

- Tier 1 should add less than 50ms per chunk (NFR-3500). If Tier 1 is slow, the
  `content_hash` property index may be degraded.
- Check: query Weaviate directly with a known content_hash and measure latency.
- Fix: verify the inverted index on `content_hash` is configured with `filterable: true`.

**Tier 2 performance:**

- Tier 2 scans up to 10,000 stored fingerprints per chunk. For a document with 100 chunks,
  this means up to 1 million fingerprint comparisons.
- If Tier 2 is slow, check the number of chunks with `fuzzy_fingerprint` populated:
  ```python
  collection = client.collections.get("Chunk")
  count = collection.aggregate.over_all(
      filters=Filter.by_property("fuzzy_fingerprint").is_not_none()
  ).total_count
  ```
- If count exceeds 50K, consider disabling Tier 2 until the LSH forest index is implemented
  (v1.1), or reduce `fuzzy_num_hashes` to speed up comparison (at the cost of estimation
  accuracy).

**General mitigation:**

- The node has graceful degradation. If Weaviate becomes unresponsive, chunks pass through
  with `degraded: true`. This prevents ingestion from stalling but produces duplicates.

### 5.4 Weaviate Schema Conflicts

**Symptom:** `ensure_collection()` fails or the dedup node raises errors about missing
properties.

**Diagnosis:**

The dedup subsystem requires four properties on the chunk object schema:

| Property | Type | Indexed |
|----------|------|---------|
| `content_hash` | `TEXT` | `filterable: true`, `searchable: false` |
| `source_documents` | `TEXT_ARRAY` | default |
| `fuzzy_fingerprint` | `TEXT` | `filterable: false`, `searchable: false` |
| `canonical` | `BOOL` | default |

**Common causes:**

1. **Fresh deployment without schema update:** `ensure_collection()` was not run after deploying
   the dedup code. Run it manually or restart the service (it runs on startup).
2. **Property name collision:** Another subsystem added a property with the same name but
   different type. Check the Weaviate collection schema directly:
   ```bash
   curl -s http://localhost:8080/v1/schema/Chunk | jq '.properties[] | select(.name == "content_hash")'
   ```
3. **Existing collection, missing properties:** `ensure_collection()` handles adding new
   properties to an existing collection. If it fails, check Weaviate logs for schema
   validation errors.

**Resolution:**

- For missing properties: re-run `ensure_collection()` or add properties manually via the
  Weaviate REST API.
- For type mismatches: you cannot change a property's type in Weaviate without recreating the
  collection. Coordinate with the team before making schema changes.

---

## 6. Testing Guide

### 6.1 Critical Test Scenarios

These are the scenarios that must pass before any dedup change ships. They are ordered by
priority.

| # | Scenario | Type | File | What it validates |
|---|----------|------|------|-------------------|
| 1 | **Exact-match merge** — ingest doc A, then doc B with identical chunk text. Verify B's chunk is not stored independently and A's canonical chunk has `source_documents: ["doc_a", "doc_b"]`. | Integration | `test_dedup_integration.py` | Core Tier 1 merge path (FR-3411, FR-3431) |
| 2 | **Bypass when disabled** — set `enable_cross_document_dedup: false`, ingest two documents with overlapping content. Verify both chunks stored independently, no Weaviate queries made. | Unit | `test_cross_document_dedup.py` | Config bypass (FR-3402) |
| 3 | **Novel chunk passthrough** — ingest a document with unique content. Verify all chunks pass through with `content_hash` and `source_documents` attached. | Unit | `test_cross_document_dedup.py` | No-match path (FR-3412, FR-3430) |
| 4 | **Hash contract** — `"  Hello   World\n"` and `"Hello World"` produce identical hashes; `"Hello World"` and `"hello world"` produce different hashes. | Unit | `test_content_hash.py` | Normalisation contract (FR-3410) |
| 5 | **Fuzzy match above threshold** — two chunks with 0.97 Jaccard similarity and threshold 0.95. Verify merge occurs. | Unit | `test_minhash_engine.py` | Tier 2 match path (FR-3423) |
| 6 | **Fuzzy match below threshold** — two chunks with 0.93 Jaccard similarity and threshold 0.95. Verify no merge. | Unit | `test_minhash_engine.py` | Tier 2 threshold boundary (FR-3422) |
| 7 | **Re-ingestion cleanup** — ingest doc A (creates back-refs on canonical chunks), re-ingest doc A. Verify old back-refs are removed before new dedup runs. | Integration | `test_dedup_integration.py` | Back-reference consistency (FR-3433) |
| 8 | **Graceful degradation** — mock Weaviate client to raise exceptions. Verify all chunks pass through, `degraded: true` in stats. | Unit | `test_cross_document_dedup.py` | Weaviate failure handling (NFR-3504) |
| 9 | **Override bypass** — ingest doc B with `dedup_override=true`. Verify all chunks stored independently, `content_hash` still attached. | Unit | `test_cross_document_dedup.py` | Override path (FR-3450) |
| 10 | **Longer-chunk-wins** — Tier 2 match where incoming chunk is longer. Verify canonical chunk's text, hash, and fingerprint are updated. | Unit | `test_cross_document_dedup.py` | Canonical replacement (FR-3424) |
| 11 | **source_documents deduplication** — re-ingest the same document. Verify `source_key` is not appended twice to `source_documents`. | Unit | `test_content_hash.py` | Array uniqueness (FR-3431 AC-2) |
| 12 | **Merge report schema** — verify merge events contain no chunk text. Verify all required fields are present. | Unit | `test_cross_document_dedup.py` | Report integrity (FR-3440, SC-3510) |

### 6.2 Test Fixtures

The test suite uses a small set of reusable fixtures:

```python
# Chunk fixtures for dedup testing

CHUNK_ASIC_ORIGINAL = "ASIC design requires careful clock domain crossing analysis."
CHUNK_ASIC_DUPLICATE = "ASIC design requires careful clock domain crossing analysis."
CHUNK_ASIC_NEAR_DUP = "ASIC design requires careful clock-domain crossing analysis and verification."
CHUNK_ASIC_UNRELATED = "FPGA prototyping enables rapid hardware validation."
CHUNK_WHITESPACE_VARIANT = "  ASIC  design requires   careful clock domain crossing analysis.  \n"

# Expected hash for CHUNK_ASIC_ORIGINAL (after normalisation)
EXPECTED_HASH = hashlib.sha256(
    b"ASIC design requires careful clock domain crossing analysis."
).hexdigest()

# CHUNK_WHITESPACE_VARIANT should produce the same hash as CHUNK_ASIC_ORIGINAL
assert compute_content_hash(CHUNK_WHITESPACE_VARIANT) == EXPECTED_HASH

# Mock Weaviate client factory
def make_mock_client(stored_chunks: list[dict]) -> MagicMock:
    """Create a mock Weaviate client pre-loaded with stored chunks."""
    client = MagicMock()
    collection = MagicMock()
    client.collections.get.return_value = collection
    # Configure query.fetch_objects to return stored chunks matching filters
    # ...
    return client
```

For integration tests, use Weaviate's test collection:

```python
@pytest.fixture
def weaviate_test_collection(weaviate_client):
    """Create a fresh test collection with dedup schema properties."""
    collection_name = f"TestChunk_{uuid4().hex[:8]}"
    # Create collection with content_hash, source_documents, etc.
    yield collection_name
    # Teardown: delete collection
    weaviate_client.collections.delete(collection_name)
```

### 6.3 Integration Test Setup

Integration tests require a running Weaviate instance. The test harness assumes:

- Weaviate is available at `localhost:8080` (override with `WEAVIATE_TEST_URL`).
- Tests create and destroy their own collections (no shared state).
- Each test run uses a unique collection name to avoid conflicts with parallel test execution.

**Running the tests:**

```bash
# Unit tests only (no Weaviate required)
pytest tests/ingest/embedding/test_content_hash.py
pytest tests/ingest/embedding/test_minhash_engine.py
pytest tests/ingest/embedding/test_cross_document_dedup.py

# Integration tests (requires Weaviate)
pytest tests/ingest/embedding/test_dedup_integration.py

# All dedup tests
pytest tests/ingest/embedding/ -k dedup
```

**End-to-end integration test pattern:**

```python
def test_cross_document_dedup_end_to_end(weaviate_test_collection, weaviate_client):
    """Ingest doc A, then doc B with overlap. Verify merges and back-refs."""

    # 1. Ingest document A (3 chunks, all novel)
    result_a = run_embedding_pipeline(
        source_key="doc_a",
        chunks=[chunk_1, chunk_2, chunk_3],
        config=IngestionConfig(enable_cross_document_dedup=True),
    )
    assert result_a.dedup_stats["novel_chunks"] == 3
    assert result_a.dedup_stats["exact_matches"] == 0

    # 2. Ingest document B (3 chunks: 1 duplicate of A, 2 novel)
    result_b = run_embedding_pipeline(
        source_key="doc_b",
        chunks=[chunk_1_dup, chunk_4, chunk_5],  # chunk_1_dup == chunk_1
        config=IngestionConfig(enable_cross_document_dedup=True),
    )
    assert result_b.dedup_stats["exact_matches"] == 1
    assert result_b.dedup_stats["novel_chunks"] == 2

    # 3. Verify back-reference on canonical chunk
    canonical = find_chunk_by_content_hash(weaviate_client, compute_content_hash(chunk_1.text))
    assert set(canonical["source_documents"]) == {"doc_a", "doc_b"}

    # 4. Verify merge report
    assert len(result_b.dedup_merge_report) == 1
    event = result_b.dedup_merge_report[0]
    assert event["match_tier"] == "exact"
    assert event["merged_source_key"] == "doc_b"
    assert event["similarity_score"] == 1.0
```

---

## Companion Documents

| Document | Role |
|----------|------|
| `CROSS_DOCUMENT_DEDUP_SPEC.md` | Authoritative requirements (FR-3400–FR-3461, NFR-3500–NFR-3504) |
| `CROSS_DOCUMENT_DEDUP_DESIGN.md` | Task decomposition and code contracts |
| `CROSS_DOCUMENT_DEDUP_IMPLEMENTATION.md` | Implementation source-of-truth (function signatures, module layout) |
| `CROSS_DOCUMENT_DEDUP_ENGINEERING_GUIDE.md` (this document) | Operational guide, extension patterns, troubleshooting |
| `EMBEDDING_PIPELINE_SPEC.md` | Parent pipeline requirements |
| `INGESTION_PIPELINE_ENGINEERING_GUIDE.md` | Parent pipeline engineering guide |
