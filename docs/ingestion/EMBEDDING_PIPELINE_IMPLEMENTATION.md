# Embedding Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the full Embedding Pipeline (FR-591–FR-1304) using a three-phase contract-first workflow that prevents test bias by isolating agent contexts.

**Architecture:** The Embedding Pipeline is a LangGraph `StateGraph` DAG with 8 nodes processing clean Markdown documents from the Clean Document Store into vector embeddings (Weaviate) and optional knowledge graph triples. Nodes are plain functions (`def node_name(state: EmbeddingPipelineState) -> dict`), not classes. State flows through a single `EmbeddingPipelineState` TypedDict. Three nodes are conditional (cross-reference extraction, KG extraction, KG storage); the remaining five are mandatory. The pipeline is decoupled from the Document Processing Pipeline at the Clean Document Store boundary, enabling independent re-runs.

**Tech Stack:** Python 3.11+, LangGraph StateGraph, Weaviate (vector DB + v1 KG via cross-references), BAAI/bge-large-en-v1.5 (default embedding model, 1024 dimensions), LiteLLM Router (LLM calls), orjson (JSON), pytest (testing), Langfuse (observability).

---

## File Structure

All files that will be created or modified, organized by directory.

### Contracts (Phase 0)

```
src/ingest/
├── pipeline_types.py              # MODIFY — add EmbeddingPipelineState TypedDict, PipelineConfig extensions
├── schemas.py                     # CREATE — ChunkRecord, EnrichedChunk, KGTriple, QualityScore, EmbeddingReport
├── exceptions.py                  # MODIFY — add embedding-specific exception types
└── clean_store.py                 # CREATE — CleanDocumentStore reader + change detection
```

### Nodes (Phase B implementation)

```
src/ingest/nodes/
├── chunking.py                    # MODIFY — new Embedding Pipeline chunking node
├── chunk_enrichment.py            # MODIFY — new Embedding Pipeline enrichment node
├── metadata_generation.py         # MODIFY — LLM keyword/entity extraction + TF-IDF fallback
├── cross_reference_extraction.py  # MODIFY — inter-document reference detection
├── knowledge_graph_extraction.py  # MODIFY — triple extraction + entity normalization
├── quality_validation.py          # MODIFY — quality scoring + dedup filtering
├── embedding_storage.py           # MODIFY — embedding generation + Weaviate upsert
└── knowledge_graph_storage.py     # MODIFY — graph store writer
```

### Pipeline orchestration (Phase B)

```
src/ingest/
├── pipeline/
│   ├── workflow.py                # MODIFY — build_embedding_pipeline_graph() factory
│   └── impl.py                    # MODIFY — EmbeddingPipelineRuntime orchestrator
└── support/
    ├── vocabulary.py              # CREATE — domain vocabulary loader
    └── entity.py                  # CREATE — entity consolidation support
```

### Tests (Phase A)

```
tests/ingest/
├── test_clean_store_reader.py     # CREATE
├── test_embedding_report.py       # CREATE
├── test_reingestion.py            # CREATE
└── nodes/
    ├── __init__.py                # CREATE
    ├── test_chunking.py           # CREATE
    ├── test_chunk_enrichment.py   # CREATE
    ├── test_metadata_generation.py # CREATE
    ├── test_cross_reference.py    # CREATE
    ├── test_kg_extraction.py      # CREATE
    ├── test_entity_consolidation.py # CREATE
    ├── test_quality_validation.py # CREATE
    ├── test_embedding_storage.py  # CREATE
    ├── test_kg_storage.py         # CREATE
    ├── test_review_tiers.py       # CREATE
    └── test_pipeline_dag.py       # CREATE
```

### Supporting files

```
tests/ingest/
├── test_domain_vocabulary.py      # CREATE
├── test_evaluation_framework.py   # CREATE
├── test_langfuse_integration.py   # CREATE
├── test_batch_processing.py       # CREATE
└── test_schema_migration.py       # CREATE
```

---

## Phase 0 — Contract Definitions

**Purpose:** Define all TypedDicts, dataclasses, function signatures, and exception types BEFORE any tests or implementation. This is the shared contract that both the test agent (Phase A) and the implementation agent (Phase B) work against. Phase 0 output contains NO business logic — only type shapes, field names, and stub signatures.

**Review gate:** Phase 0 output must be human-reviewed and approved before Phase A begins. Any schema change after approval requires re-review.

---

### Task 0.1 — State Contract (`EmbeddingPipelineState`)

**Files:**
- Modify: `src/ingest/pipeline_types.py` (add `EmbeddingPipelineState`)

**Depends on:** Nothing

- [ ] Step 1: Define `EmbeddingPipelineState` TypedDict with ALL fields:

```python
from __future__ import annotations

from typing import Any, TypedDict


class EmbeddingPipelineState(TypedDict, total=False):
    """LangGraph state schema for the Embedding Pipeline.

    Each node reads from upstream-populated fields and writes only to its
    own designated output fields. Fields use ``total=False`` so that the
    initial state can be constructed with only the entry-point fields.
    """

    # ── Entry-point fields (populated before graph invocation) ───────
    config: PipelineConfig
    source_key: str
    md_content: str
    metadata: CleanDocumentMetadata

    # ── Chunking output (Node 6) ─────────────────────────────────────
    chunks: list[ChunkRecord]

    # ── Chunk Enrichment output (Node 7) ─────────────────────────────
    enriched_chunks: list[EnrichedChunk]

    # ── Metadata Generation output (Node 8) ──────────────────────────
    chunk_metadata: list[dict[str, Any]]

    # ── Cross-Reference Extraction output (Node 9, optional) ─────────
    cross_references: list[dict[str, Any]]

    # ── KG Extraction output (Node 10, optional) ─────────────────────
    kg_triples: list[KGTriple]

    # ── Quality Validation output (Node 11) ──────────────────────────
    quality_scores: list[float]

    # ── Embedding & Storage output (Node 12) ─────────────────────────
    embeddings: list[list[float]]

    # ── Cross-cutting ────────────────────────────────────────────────
    errors: list[dict[str, Any]]
    timings: dict[str, float]
```

- [ ] Step 2: Add forward references for `PipelineConfig`, `CleanDocumentMetadata`, `ChunkRecord`, `EnrichedChunk`, `KGTriple` (these are defined in Tasks 0.2 and 0.5).

---

### Task 0.2 — Chunk and Triple Schemas

**Files:**
- Create: `src/ingest/schemas.py`

**Depends on:** Nothing

- [ ] Step 1: Define `ChunkRecord` TypedDict:

```python
from __future__ import annotations

from typing import Any, TypedDict


class ChunkRecord(TypedDict):
    """A single chunk produced by the Chunking node (Node 6).

    Chunk ID formula:
        content_hash = SHA-256(chunk_text)[:16]
        chunk_id     = SHA-256(source_key + ":" + str(ordinal) + ":" + content_hash)[:24]

    The content_hash component ensures that if a chunk's content changes during
    re-chunking (while keeping the same ordinal position), the chunk_id changes
    accordingly, enabling accurate change detection.
    """

    chunk_id: str           # Deterministic: SHA-256(source_key + ":" + str(ordinal) + ":" + content_hash)[:24]
    source_key: str         # Stable document identifier from Clean Document Store
    ordinal: int            # 0-based position within the document's chunk sequence
    text: str               # Raw chunk text before enrichment
    content_hash: str       # SHA-256(chunk_text)[:16]
    char_start: int         # Character offset of chunk start in source markdown
    char_end: int           # Character offset of chunk end in source markdown
    heading_path: list[str] # Section hierarchy, e.g. ["# Title", "## Section", "### Subsection"]
    content_type: str       # One of: text, table, figure, code, equation, list, heading
    previous_chunk_id: str | None  # Adjacency link to preceding chunk (null for first chunk)
    next_chunk_id: str | None      # Adjacency link to following chunk (null for last chunk)
```

- [ ] Step 2: Define `EnrichedChunk` TypedDict:

```python
class EnrichedChunk(TypedDict):
    """An enriched chunk produced by the Chunk Enrichment node (Node 7)
    and progressively populated by Metadata Generation (Node 8).

    Key invariant:
        enriched_content = chunk_text + boundary_context
        context_header is stored but NOT embedded.
    """

    chunk_id: str               # Carried forward from ChunkRecord
    chunk_text: str             # Original chunk text (from ChunkRecord.text)
    boundary_context: str       # Text from adjacent chunks (previous tail + next head)
    context_header: str         # Metadata header (title, section path, tier) — stored, NOT embedded
    enriched_content: str       # = chunk_text + boundary_context — THIS is what gets embedded
    keywords: list[str]         # LLM-extracted or TF-IDF fallback keywords
    entities: list[dict[str, str]]  # Named entities: [{"name": ..., "type": ...}, ...]
    summary: str                # Chunk-level summary
    quality_score: float        # Quality score from Node 11 (0.0–1.0)
    review_tier: str            # Propagated from CleanDocumentMetadata: FULLY_REVIEWED | PARTIALLY_REVIEWED | SELF_REVIEWED
```

- [ ] Step 3: Define `KGTriple` TypedDict:

```python
class KGTriple(TypedDict):
    """A knowledge graph triple extracted by Node 10.

    Represents a subject-predicate-object relationship with provenance
    tracking back to the source chunk.
    """

    subject: str                # Normalized entity (canonical form)
    predicate: str              # Relationship type from controlled vocabulary
    object: str                 # Normalized entity (canonical form)
    source_chunk_id: str        # chunk_id of the chunk this triple was extracted from
    confidence: float           # Extraction confidence (0.0–1.0)
    provenance: dict[str, Any]  # Extraction metadata: model, prompt version, method (llm/structural)
```

- [ ] Step 4: Define `QualityScore` TypedDict:

```python
class QualityScore(TypedDict):
    """Quality assessment for a single chunk, produced by Node 11."""

    chunk_id: str
    score: float                # Overall quality score (0.0–1.0)
    completeness: float         # Content completeness sub-score
    coherence: float            # Coherence sub-score
    keyword_density: float      # Keyword density sub-score
    is_duplicate: bool          # True if flagged as near-duplicate
    duplicate_of: str | None    # chunk_id of the original if duplicate
    passed: bool                # True if score >= min_quality_score and not duplicate
```

- [ ] Step 5: Define `EmbeddingReport` dataclass:

```python
from dataclasses import dataclass, field


@dataclass
class EmbeddingReport:
    """Structured report for a single document embedding run."""

    source_key: str
    chunks_produced: int = 0
    chunks_enriched: int = 0
    chunks_passed_quality: int = 0
    chunks_filtered: int = 0
    chunks_deduplicated: int = 0
    chunks_embedded: int = 0
    chunks_stored: int = 0
    triples_extracted: int = 0
    triples_stored: int = 0
    cross_references_found: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    skipped: bool = False
    dry_run: bool = False
```

---

### Task 0.3 — Exception Types

**Files:**
- Create or Modify: `src/ingest/exceptions.py` (add embedding-specific exceptions)

**Depends on:** Nothing

- [ ] Step 1: Define embedding-specific exception hierarchy:

```python
class EmbeddingPipelineError(Exception):
    """Base exception for all Embedding Pipeline errors."""


class MissingCleanDocumentError(EmbeddingPipelineError):
    """Raised when the .md file for a source_key is absent from the Clean Document Store."""

    def __init__(self, source_key: str, expected_path: str):
        self.source_key = source_key
        self.expected_path = expected_path
        super().__init__(f"Clean document not found: {expected_path} (source_key={source_key})")


class InvalidMetadataError(EmbeddingPipelineError):
    """Raised when .meta.json is missing, malformed, or fails schema validation."""

    def __init__(self, source_key: str, reason: str):
        self.source_key = source_key
        self.reason = reason
        super().__init__(f"Invalid metadata for {source_key}: {reason}")


class EmbeddingDimensionMismatchError(EmbeddingPipelineError):
    """Raised when embedding vector dimension does not match model configuration."""

    def __init__(self, expected: int, actual: int, model: str):
        self.expected = expected
        self.actual = actual
        self.model = model
        super().__init__(
            f"Embedding dimension mismatch: model {model} expected {expected}, got {actual}"
        )


class ChunkSizeViolationError(EmbeddingPipelineError):
    """Raised when a chunk violates min/max token constraints and cannot be corrected."""

    def __init__(self, chunk_id: str, token_count: int, min_tokens: int, max_tokens: int):
        self.chunk_id = chunk_id
        self.token_count = token_count
        super().__init__(
            f"Chunk {chunk_id} has {token_count} tokens "
            f"(allowed: {min_tokens}–{max_tokens})"
        )


class VectorStoreWriteError(EmbeddingPipelineError):
    """Raised when a vector store write fails after exhausting retries."""

    def __init__(self, source_key: str, reason: str):
        self.source_key = source_key
        self.reason = reason
        super().__init__(f"Vector store write failed for {source_key}: {reason}")


class GraphStoreWriteError(EmbeddingPipelineError):
    """Raised when a graph store write fails after exhausting retries."""

    def __init__(self, source_key: str, reason: str):
        self.source_key = source_key
        self.reason = reason
        super().__init__(f"Graph store write failed for {source_key}: {reason}")
```

---

### Task 0.4 — Node Function Signatures (Stubs)

**Files:**
- Modify: All 8 node files under `src/ingest/nodes/` (add Embedding Pipeline stub functions)
- Create: `src/ingest/clean_store.py` (stub)
- Create: `src/ingest/report.py` (stub)

**Depends on:** Task 0.1, Task 0.2, Task 0.3

- [ ] Step 1: Create `src/ingest/clean_store.py` with reader stub:

```python
def read(source_key: str) -> tuple[str, CleanDocumentMetadata]:
    """Read clean document and metadata from the Clean Document Store.

    Returns (md_content, metadata). Raises MissingCleanDocumentError if absent,
    InvalidMetadataError if metadata is malformed.
    """
    raise NotImplementedError

def validate_metadata(meta: dict) -> CleanDocumentMetadata:
    """Validate raw metadata dict against the CleanDocumentMetadata schema."""
    raise NotImplementedError

def check_clean_hash_changed(source_key: str, current_hash: str) -> bool:
    """Compare current clean_hash against the embedding run manifest.

    Returns True if re-embedding is needed.
    """
    raise NotImplementedError

def propagate_metadata_to_chunk(chunk: dict, metadata: CleanDocumentMetadata) -> dict:
    """Attach source_key, source_path, review_tier, extraction_confidence to chunk."""
    raise NotImplementedError
```

- [ ] Step 2: Create Embedding Pipeline node stubs (one per node). Each stub follows:

```python
def embedding_chunking_node(state: EmbeddingPipelineState) -> dict:
    """Node 6: Structure-aware chunking with deterministic IDs."""
    raise NotImplementedError

def embedding_chunk_enrichment_node(state: EmbeddingPipelineState) -> dict:
    """Node 7: Boundary context + metadata header construction."""
    raise NotImplementedError

def embedding_metadata_generation_node(state: EmbeddingPipelineState) -> dict:
    """Node 8: LLM keyword/entity extraction with TF-IDF fallback."""
    raise NotImplementedError

def embedding_cross_reference_node(state: EmbeddingPipelineState) -> dict:
    """Node 9: Inter-document reference detection (optional)."""
    raise NotImplementedError

def embedding_kg_extraction_node(state: EmbeddingPipelineState) -> dict:
    """Node 10: Triple extraction with entity normalization (optional)."""
    raise NotImplementedError

def embedding_quality_validation_node(state: EmbeddingPipelineState) -> dict:
    """Node 11: Quality scoring + deduplication filtering."""
    raise NotImplementedError

def embedding_storage_node(state: EmbeddingPipelineState) -> dict:
    """Node 12: Embedding generation + Weaviate upsert."""
    raise NotImplementedError

def embedding_kg_storage_node(state: EmbeddingPipelineState) -> dict:
    """Node 13: Graph store writer (optional)."""
    raise NotImplementedError
```

- [ ] Step 3: Create `src/ingest/report.py` with report stub:

```python
def build_embedding_report(state: EmbeddingPipelineState) -> EmbeddingReport:
    """Collect per-document statistics from final pipeline state."""
    raise NotImplementedError
```

---

### Task 0.5 — Embedding-Specific Config Extensions

**Files:**
- Modify: `src/ingest/pipeline_types.py` (extend `PipelineConfig` frozen dataclass or `IngestionConfig`)

**Depends on:** Nothing

- [ ] Step 1: Add embedding-specific config fields. These extend the existing `IngestionConfig` dataclass:

```python
# ── Chunking configuration ───────────────────────────────────────
chunk_size: int              # Target chunk size in tokens (default: 450)
chunk_overlap: int           # Overlap tokens between adjacent chunks (default: 50)
min_chunk_tokens: int        # Minimum acceptable chunk size (default: 30)
max_chunk_tokens: int        # Maximum acceptable chunk size (default: 512)
splitting_strategy: str      # "recursive" | "document_aware" | "semantic" (default: "document_aware")
boundary_context_tokens: int # Tokens from adjacent chunks for boundary context (default: 60)

# ── Enrichment configuration ─────────────────────────────────────
embed_context_header: bool   # Include context_header in embedding input (default: False)

# ── Embedding model configuration ────────────────────────────────
embedding_model: str         # Model identifier (default: "BAAI/bge-large-en-v1.5")
embedding_dimension: int     # Expected vector dimension (default: 1024)
byom_mode: bool              # Bring Your Own Model — accept pre-computed vectors (default: False)
document_prefix: str         # Asymmetric prefix for documents (default: "passage: ")
query_prefix: str            # Asymmetric prefix for queries (default: "query: ")

# ── Optional stage toggles ───────────────────────────────────────
enable_cross_references: bool     # Enable Node 9 (default: False)
enable_knowledge_graph: bool      # Enable Nodes 10 + 13 (default: False)
graph_store_backend: str          # "weaviate" | "neo4j" (default: "weaviate")

# ── Quality validation ───────────────────────────────────────────
min_quality_score: float     # Discard threshold (default: 0.45)
dedup_threshold: float       # Near-duplicate cosine similarity threshold (default: 0.95)

# ── Hybrid search ────────────────────────────────────────────────
enable_bm25: bool            # Enable BM25 keyword indexing alongside vectors (default: True)

# ── Clean Document Store ─────────────────────────────────────────
clean_docs_dir: str          # Path to Clean Document Store directory
weaviate_collection: str     # Weaviate collection name for chunk storage
```

- [ ] Step 2: Define `CleanDocumentMetadata` dataclass:

```python
@dataclass(frozen=True)
class CleanDocumentMetadata:
    """Metadata envelope read from {source_key}.meta.json in the Clean Document Store."""

    source_key: str
    source_path: str
    clean_hash: str               # SHA-256 of the clean Markdown content
    review_tier: str              # FULLY_REVIEWED | PARTIALLY_REVIEWED | SELF_REVIEWED
    extraction_confidence: float  # From document processing pipeline
    title: str
    page_count: int
    processing_timestamp: str
```

- [ ] Step 3: Add config validation: contradictory settings should fail fast (e.g., `byom_mode=True` with `embedding_model` set, `enable_knowledge_graph=True` with `graph_store_backend` unset).

---

## Phase A — Tests (Isolated from Implementation)

**Agent isolation contract:** The test agent receives ONLY the following for each task:
1. The spec requirements (FR numbers + exact acceptance criteria text)
2. The contract files from Phase 0 (TypedDicts, function signatures, exception types)
3. The task description from this plan

**Must NOT receive:**
- Any implementation code from `src/ingest/nodes/`
- Any Part B code appendix snippets from `EMBEDDING_PIPELINE_DESIGN.md`
- Any implementation code from other Phase B tasks
- Any existing node implementations from the Document Processing Pipeline

This isolation prevents the test agent from reverse-engineering implementation details into the tests, ensuring tests validate behavior against the specification, not against a particular implementation strategy.

---

### Task A-S.2 — Tests for Clean Document Store Reader

**Agent input (ONLY these):**
- FR-591: The pipeline MUST read clean Markdown from `{source_key}.md` in the Clean Document Store
- FR-592: The pipeline MUST validate the `.meta.json` metadata envelope; raise `InvalidMetadataError` on schema violation
- FR-593: The pipeline MUST compare `clean_hash` against the embedding run manifest; skip if unchanged
- FR-594: The pipeline MUST propagate `source_key`, `source_path`, `review_tier`, and `extraction_confidence` from metadata to every chunk
- FR-595: The pipeline SHOULD verify actual SHA-256 of `.md` matches `clean_hash`; log warning on mismatch without halting
- `CleanDocumentMetadata` dataclass from Phase 0 (Task 0.5)
- `MissingCleanDocumentError`, `InvalidMetadataError` from Phase 0 (Task 0.3)
- Function signatures: `read()`, `validate_metadata()`, `check_clean_hash_changed()`, `propagate_metadata_to_chunk()` from Phase 0 (Task 0.4)

**Must NOT receive:** Any implementation code from `src/ingest/clean_store.py`, any Part B snippets.

**Files:**
- Create: `tests/ingest/test_clean_store_reader.py`

- [ ] Step 1: Write tests covering:
  - Read existing clean document returns `(md_content, CleanDocumentMetadata)` (FR-591)
  - Read missing `.md` file raises `MissingCleanDocumentError` (FR-591)
  - Read missing `.meta.json` raises `InvalidMetadataError` (FR-592)
  - Malformed JSON in `.meta.json` raises `InvalidMetadataError` (FR-592)
  - Missing required fields in metadata raises `InvalidMetadataError` (FR-592)
  - `clean_hash` unchanged returns skip signal (FR-593)
  - `clean_hash` changed returns reprocess signal (FR-593)
  - `propagate_metadata_to_chunk` attaches `source_key`, `source_path`, `review_tier`, `extraction_confidence` (FR-594)
  - SHA-256 mismatch between `.md` content and `clean_hash` logs warning but does not raise (FR-595)

- [ ] Step 2: Run tests to confirm stubs raise `NotImplementedError`:

```bash
pytest tests/ingest/test_clean_store_reader.py -v
```

Expected: ALL FAIL with `NotImplementedError`

---

### Task A-1.2 — Tests for Embedding Pipeline DAG Skeleton

**Agent input (ONLY these):**
- FR-591: Pipeline reads from Clean Document Store
- FR-901: Cross-reference extraction is conditional on `enable_cross_references` config
- FR-1001: KG extraction is conditional on `enable_knowledge_graph` config
- FR-1301: KG storage fires only when KG triples exist AND `enable_knowledge_graph` is true
- `EmbeddingPipelineState` TypedDict from Phase 0 (Task 0.1)
- `PipelineConfig` config fields from Phase 0 (Task 0.5)
- Node stub function signatures from Phase 0 (Task 0.4)

**Must NOT receive:** Any `build_embedding_pipeline_graph()` implementation, any Part B DAG snippet.

**Files:**
- Create: `tests/ingest/nodes/test_pipeline_dag.py`

- [ ] Step 1: Write tests covering:
  - Graph compiles without error
  - All 8 nodes are registered in the graph
  - Entry point is `chunking`
  - Mandatory path: chunking -> chunk_enrichment -> metadata_generation -> quality_validation -> embedding_storage
  - When `enable_cross_references=False` and `enable_knowledge_graph=False`, cross-ref and KG nodes are skipped
  - When `enable_cross_references=True`, cross-reference node executes after metadata_generation
  - When `enable_knowledge_graph=True`, KG extraction executes; KG storage executes after embedding_storage
  - When `enable_knowledge_graph=True` but no triples produced, KG storage is skipped
  - State keys are preserved end-to-end through a synthetic document run

- [ ] Step 2: Run tests:

```bash
pytest tests/ingest/nodes/test_pipeline_dag.py -v
```

Expected: FAIL (stubs raise `NotImplementedError`)

---

### Task A-1.6 — Tests for Chunking Node

**Agent input (ONLY these):**
- FR-601: Structure-aware splitting respects Markdown heading boundaries (`#`, `##`, `###`)
- FR-602: Recursive character splitter as fallback when a section exceeds `max_chunk_tokens`
- FR-603: Deterministic chunk IDs: `SHA-256(source_key + ":" + str(ordinal) + ":" + content_hash)[:24]` where `content_hash = SHA-256(chunk_text)[:16]`
- FR-604: Tables are indivisible chunks; oversized tables split by row groups with header row prepended
- FR-605: Chunk ID changes when content changes (content_hash component ensures this)
- FR-606: Adjacency links: `previous_chunk_id` / `next_chunk_id` on every chunk; first chunk has `previous_chunk_id = None`; last has `next_chunk_id = None`
- `EmbeddingPipelineState` TypedDict from Phase 0 (Task 0.1)
- `ChunkRecord` TypedDict from Phase 0 (Task 0.2)
- Function signature: `def embedding_chunking_node(state: EmbeddingPipelineState) -> dict`
- Chunk ID formula: `SHA-256(source_key + ":" + str(ordinal) + ":" + content_hash)[:24]` where `content_hash = SHA-256(chunk_text)[:16]`

**Must NOT receive:** Any implementation from `src/ingest/nodes/chunking.py`, `src/ingest/support/markdown.py`, or Part B snippets.

**Files:**
- Create: `tests/ingest/nodes/test_chunking.py`

- [ ] Step 1: Write tests covering:
  - Heading-aware splitting: input with `# A` and `## B` sections produces chunks at heading boundaries (FR-601)
  - Recursive fallback: section exceeding `max_chunk_tokens` is split into multiple chunks (FR-602)
  - Deterministic chunk IDs: same input produces identical chunk IDs across runs (FR-603)
  - Content-hash component: changing chunk text changes the chunk_id even at the same ordinal (FR-605)
  - Chunk ID formula verification: manually compute `SHA-256(source_key + ":" + str(ordinal) + ":" + SHA-256(chunk_text)[:16])[:24]` and assert match (FR-603)
  - Table atomic chunking: Markdown table preserved as a single chunk (FR-604)
  - Oversized table: table exceeding `max_chunk_tokens` split by rows with header prepended to each sub-chunk (FR-604)
  - Adjacency links: first chunk has `previous_chunk_id = None` (FR-606)
  - Adjacency links: last chunk has `next_chunk_id = None` (FR-606)
  - Adjacency links: middle chunks link to both neighbors (FR-606)
  - Chunk size validation: all chunks within `min_chunk_tokens`–`max_chunk_tokens` range
  - `char_start` and `char_end` offsets are correct for each chunk
  - `heading_path` reflects the section hierarchy
  - `content_type` is assigned correctly (text, table, code, etc.)
  - Single-section document produces chunks without unnecessary heading splits

- [ ] Step 2: Run tests:

```bash
pytest tests/ingest/nodes/test_chunking.py -v
```

Expected: FAIL (stubs raise `NotImplementedError`)

---

### Task A-2.2a — Tests for Chunk Enrichment Node

**Agent input (ONLY these):**
- FR-701: Attach boundary context from adjacent chunks (configurable window of `boundary_context_tokens`)
- FR-702: Build `context_header` from document title, section path, review tier — stored but NOT embedded by default
- FR-703: `enriched_content = chunk_text + boundary_context` — this is what gets embedded
- FR-704: `context_header` is stored separately in chunk metadata for retrieval display
- FR-705: Cross-chunk overlap: last N tokens from previous chunk + first N tokens from next chunk as boundary context
- `EmbeddingPipelineState` TypedDict, `ChunkRecord`, `EnrichedChunk` from Phase 0
- Function signature: `def embedding_chunk_enrichment_node(state: EmbeddingPipelineState) -> dict`
- Config fields: `boundary_context_tokens`, `embed_context_header`

**Must NOT receive:** Any implementation from `src/ingest/nodes/chunk_enrichment.py`.

**Files:**
- Create: `tests/ingest/nodes/test_chunk_enrichment.py`

- [ ] Step 1: Write tests covering:
  - `enriched_content` equals `chunk_text + boundary_context` (FR-703)
  - `context_header` is NOT included in `enriched_content` by default (FR-702)
  - When `embed_context_header=True`, `context_header` IS included in `enriched_content` (FR-702 override)
  - `context_header` includes document title, section path, review tier (FR-702, FR-704)
  - `context_header` is stored as a separate field in `EnrichedChunk` (FR-704)
  - Boundary context: first chunk gets only next-chunk context (no previous) (FR-705)
  - Boundary context: last chunk gets only previous-chunk context (no next) (FR-705)
  - Boundary context: middle chunks get both previous and next context (FR-705)
  - Boundary context respects `boundary_context_tokens` configuration (FR-701)
  - Single-chunk document: boundary context is empty (FR-705)
  - Enrichment failure falls back to unenriched chunk (FR-705)
  - `chunk_id` is carried forward from `ChunkRecord` to `EnrichedChunk`

- [ ] Step 2: Run tests:

```bash
pytest tests/ingest/nodes/test_chunk_enrichment.py -v
```

Expected: FAIL (stubs raise `NotImplementedError`)

---

### Task A-2.2b — Tests for Metadata Generation Node

**Agent input (ONLY these):**
- FR-801: LLM extracts keywords at document and chunk level
- FR-802: LLM extracts named entities per chunk
- FR-803: Keywords validated against domain vocabulary before use
- FR-804: Domain vocabulary terms appearing in chunk text but not extracted by LLM are injected
- FR-805: TF-IDF fallback when LLM call fails or times out
- FR-806: Document-level summary generated by aggregating chunk summaries
- `EmbeddingPipelineState` TypedDict, `EnrichedChunk` from Phase 0
- Function signature: `def embedding_metadata_generation_node(state: EmbeddingPipelineState) -> dict`
- Config fields: `max_keywords`, `enable_llm_metadata`

**Must NOT receive:** Any implementation from `src/ingest/nodes/metadata_generation.py` or `src/ingest/common/shared.py`.

**Files:**
- Create: `tests/ingest/nodes/test_metadata_generation.py`

- [ ] Step 1: Write tests covering:
  - LLM produces keywords list per chunk (FR-801)
  - LLM produces entities list per chunk (FR-802)
  - Keywords validated against domain vocabulary — non-vocabulary keywords are retained but flagged (FR-803)
  - Domain vocabulary injection: terms in chunk text not extracted by LLM are added (FR-804)
  - TF-IDF fallback activates when LLM call raises exception (FR-805)
  - TF-IDF fallback activates when LLM call times out (FR-805)
  - TF-IDF fallback produces keyword list (non-empty for non-trivial text) (FR-805)
  - Document-level summary is generated (FR-806)
  - Configurable `max_keywords` limits keyword count
  - Empty chunk text produces empty keywords list
  - LLM failure on one chunk does not fail the entire node

- [ ] Step 2: Run tests:

```bash
pytest tests/ingest/nodes/test_metadata_generation.py -v
```

Expected: FAIL (stubs raise `NotImplementedError`)

---

### Task A-1.7 — Tests for Embedding Generation

**Agent input (ONLY these):**
- FR-1201: Embedding model is configurable; default BAAI/bge-large-en-v1.5, 1024 dimensions
- FR-1202: Batched embedding calls with configurable batch size
- FR-1203: Dimensionality validation: output vector dimension must match `embedding_dimension` config; halt on mismatch
- FR-1204: BYOM mode: when `byom_mode=True`, accept pre-computed vectors instead of calling embedding API
- `EmbeddingPipelineState` TypedDict, `EnrichedChunk` from Phase 0
- `EmbeddingDimensionMismatchError` from Phase 0 (Task 0.3)
- Function signature: `def embedding_storage_node(state: EmbeddingPipelineState) -> dict`
- Config fields: `embedding_model`, `embedding_dimension`, `byom_mode`, `document_prefix`

**Must NOT receive:** Any implementation from `src/ingest/nodes/embedding_storage.py`.

**Files:**
- Create: `tests/ingest/nodes/test_embedding_storage.py`

- [ ] Step 1: Write tests for embedding generation covering:
  - Embeddings are generated for all enriched chunks (FR-1201)
  - Embedding dimension matches `embedding_dimension` config (FR-1203)
  - Dimension mismatch raises `EmbeddingDimensionMismatchError` (FR-1203)
  - BYOM mode skips embedding API call entirely (FR-1204)
  - BYOM mode uses pre-computed vectors from chunk state (FR-1204)
  - Batched calls respect configured batch size (FR-1202)
  - Document prefix is prepended to `enriched_content` before embedding (FR-1206)
  - Token count exceeding model context window is rejected before API call
  - Transient API errors trigger retry with backoff

- [ ] Step 2: Run tests:

```bash
pytest tests/ingest/nodes/test_embedding_storage.py -v
```

Expected: FAIL (stubs raise `NotImplementedError`)

---

### Task A-1.8 — Tests for Vector Store Upsert

**Agent input (ONLY these):**
- FR-1205: Delete-and-reinsert on re-ingestion: delete all chunks by `source_key` before inserting
- FR-1206: Asymmetric embedding prefixes (`document_prefix` for documents, `query_prefix` for queries)
- FR-1207: BM25 keyword indexing alongside vector indexing; enabled via `enable_bm25` (default: true)
- FR-1208: Atomic storage: no partial writes on failure (rollback or no-commit)
- FR-1209: Vector dimensionality validation against model output
- `EmbeddingPipelineState` TypedDict from Phase 0
- `VectorStoreWriteError` from Phase 0 (Task 0.3)
- Config fields: `weaviate_collection`, `enable_bm25`, `document_prefix`, `query_prefix`

**Must NOT receive:** Any implementation from `src/ingest/nodes/embedding_storage.py` or Part B re-ingestion snippet.

**Files:**
- Modify: `tests/ingest/nodes/test_embedding_storage.py` (add upsert tests to same file)

- [ ] Step 1: Write tests for vector store upsert covering:
  - Chunks are stored with full metadata envelope in Weaviate (FR-1205)
  - Re-ingestion: existing chunks for source_key are deleted before insert (FR-1205)
  - Idempotency: re-upserting same chunks does not increase point count (FR-1205)
  - Asymmetric prefix: document_prefix is applied at ingestion time (FR-1206)
  - BM25 index: when `enable_bm25=True`, `enriched_content` text is indexed for keyword search (FR-1207)
  - Atomic write: partial failure rolls back all writes for the document (FR-1208)
  - Transient Weaviate errors trigger retry (FR-1208)
  - `VectorStoreWriteError` raised after exhausting retries (FR-1208)
  - Stale chunks are gone after re-ingestion of a changed document (FR-1205)

- [ ] Step 2: Run tests:

```bash
pytest tests/ingest/nodes/test_embedding_storage.py -v
```

Expected: FAIL (stubs raise `NotImplementedError`)

---

### Task A-1.9 — Tests for Result Reporting

**Agent input (ONLY these):**
- FR-1201: Storage completeness reporting
- `EmbeddingPipelineState` TypedDict from Phase 0
- `EmbeddingReport` dataclass from Phase 0 (Task 0.2)
- Function signature: `def build_embedding_report(state: EmbeddingPipelineState) -> EmbeddingReport`

**Must NOT receive:** Any implementation from `src/ingest/report.py`.

**Files:**
- Create: `tests/ingest/test_embedding_report.py`

- [ ] Step 1: Write tests covering:
  - Report contains correct `chunks_produced` count
  - Report contains correct `chunks_embedded` count
  - Report contains correct `chunks_stored` count
  - Report contains correct `chunks_filtered` count (quality-rejected)
  - Report contains correct `chunks_deduplicated` count
  - Report contains `triples_extracted` and `triples_stored` when KG is enabled
  - Report contains timing data for each stage
  - Report contains errors list for any failed operations
  - Report `skipped=True` when document hash unchanged
  - Report `dry_run=True` when dry-run mode is active
  - Report serializes to valid JSON

- [ ] Step 2: Run tests:

```bash
pytest tests/ingest/test_embedding_report.py -v
```

Expected: FAIL (stubs raise `NotImplementedError`)

---

### Task A-1.10 — Tests for Re-Ingestion Flow

**Agent input (ONLY these):**
- FR-593: `clean_hash` comparison determines re-embedding; skip if unchanged
- FR-1205: Delete-and-reinsert strategy for changed documents
- FR-1208: Atomic re-ingestion (delete old + insert new as a unit)
- `EmbeddingPipelineState` TypedDict, `CleanDocumentMetadata` from Phase 0
- `EmbeddingPipelineRuntime` class signature from Phase 0
- Config fields: `force` flag, `dry_run` flag

**Must NOT receive:** Any implementation from `src/ingest/pipeline/impl.py` or Part B re-ingestion snippet.

**Files:**
- Create: `tests/ingest/test_reingestion.py`

- [ ] Step 1: Write tests covering:
  - Unchanged `clean_hash` skips entire pipeline (FR-593)
  - Changed `clean_hash` triggers full re-embedding (FR-593)
  - `force=True` bypasses hash comparison and always re-embeds (FR-593)
  - Delete-and-reinsert: old chunks removed before new chunks inserted (FR-1205)
  - Dry-run mode reports what would be deleted without executing (FR-1205)
  - Dry-run mode does not modify vector store (FR-1205)
  - After re-ingestion, old chunk IDs are gone and new chunk IDs are present (FR-1205)
  - Manifest is updated with new `clean_hash` after successful embedding (FR-593)

- [ ] Step 2: Run tests:

```bash
pytest tests/ingest/test_reingestion.py -v
```

Expected: FAIL (stubs raise `NotImplementedError`)

---

### Task A-2.1 — Tests for LLM-Assisted Chunking

**Agent input (ONLY these):**
- FR-606: Adjacency links (already tested in A-1.6, but verify under LLM mode too)
- FR-607: LLM-assisted semantic boundary detection when `splitting_strategy="semantic"`
- FR-608: Fallback to rule-based chunking on LLM failure or timeout
- FR-609: Content type tagging: `text`, `table`, `figure`, `code`, `equation`, `list`, `heading`
- FR-610: Domain vocabulary compound-term boundary respect
- FR-611: Maximum chunk count limit per document
- `EmbeddingPipelineState` TypedDict, `ChunkRecord` from Phase 0
- Config fields: `splitting_strategy`, `max_chunk_tokens`

**Must NOT receive:** Any implementation from `src/ingest/nodes/chunking.py`, any LLM prompt text.

**Files:**
- Modify: `tests/ingest/nodes/test_chunking.py` (add LLM-specific test class)

- [ ] Step 1: Write tests covering:
  - Semantic splitting produces coherent topic-based chunks (FR-607)
  - LLM failure degrades to rule-based chunking transparently (FR-608)
  - LLM timeout degrades to rule-based chunking transparently (FR-608)
  - Content type tagging: code fences tagged as `code` (FR-609)
  - Content type tagging: Markdown table tagged as `table` (FR-609)
  - Content type tagging: heading-only chunk tagged as `heading` (FR-609)
  - Domain vocabulary terms not split across chunk boundaries (FR-610)
  - Maximum chunk count limit enforced (FR-611)
  - Adjacency links correct under LLM mode (FR-606)

- [ ] Step 2: Run tests:

```bash
pytest tests/ingest/nodes/test_chunking.py -v
```

Expected: FAIL (stubs raise `NotImplementedError`)

---

### Task A-2.4 — Tests for Domain Vocabulary System

**Agent input (ONLY these):**
- FR-803: Keywords validated against domain vocabulary
- FR-804: Domain vocabulary terms appearing in chunk text injected into keywords
- Vocabulary schema: term, synonyms, category, weight
- Function signatures: `load_vocabulary()`, `validate_keywords()`, `inject_vocabulary_terms()`

**Must NOT receive:** Any implementation from `src/ingest/support/vocabulary.py`.

**Files:**
- Create: `tests/ingest/test_domain_vocabulary.py`

- [ ] Step 1: Write tests covering:
  - Load vocabulary from YAML file
  - Validate keywords against loaded vocabulary
  - Inject vocabulary terms found in text but not in keyword list
  - Synonym resolution (e.g., "ML" matches "Machine Learning")
  - Hot-reload on file change
  - Invalid YAML raises descriptive error
  - Empty vocabulary file returns empty set

- [ ] Step 2: Run tests:

```bash
pytest tests/ingest/test_domain_vocabulary.py -v
```

Expected: FAIL (stubs raise `NotImplementedError`)

---

### Task A-3.2 — Tests for Cross-Reference Extraction Node

**Agent input (ONLY these):**
- FR-901: Detect inter-document references and standard citations
- FR-902: Resolve references to existing `source_key` values
- FR-903: Store cross-references as `{target_source_key, reference_type}` in chunk metadata
- FR-904: Dangling references logged as warnings, not failures
- FR-905: Regex fallback when LLM detection fails
- `EmbeddingPipelineState` TypedDict from Phase 0
- Config fields: `enable_cross_references`

**Must NOT receive:** Any implementation from `src/ingest/nodes/cross_reference_extraction.py` or `src/ingest/common/shared.py` `_cross_refs()`.

**Files:**
- Create: `tests/ingest/nodes/test_cross_reference.py`

- [ ] Step 1: Write tests covering:
  - Detect explicit document references (e.g., "see DOC-123") (FR-901)
  - Detect standard references (e.g., "RFC 2119", "Section 3.2") (FR-901)
  - Resolve detected reference to known `source_key` (FR-902)
  - Store as `{target_source_key, reference_type}` (FR-903)
  - Dangling reference (unknown target) logged but not raised (FR-904)
  - Regex fallback activates on LLM failure (FR-905)
  - Regex fallback extracts basic patterns (document IDs, section refs) (FR-905)
  - Node is no-op when `enable_cross_references=False`
  - Empty document produces empty cross-reference list

- [ ] Step 2: Run tests:

```bash
pytest tests/ingest/nodes/test_cross_reference.py -v
```

Expected: FAIL (stubs raise `NotImplementedError`)

---

### Task A-3.3a — Tests for Triple Extraction Node

**Agent input (ONLY these):**
- FR-1001: Extract subject-predicate-object triples from enriched chunks
- FR-1002: Structured JSON output with provenance chunk ID
- FR-1003: Entity normalization (casing, abbreviation expansion)
- FR-1004: Alias resolution to canonical entity identifiers
- FR-1005: Relation typing into controlled vocabulary
- FR-1006: Configurable ontology of relationship types
- FR-1007: Structural triple fallback on LLM failure (headings as entities, list items as relations)
- FR-1008: Each triple includes `source_chunk_id` provenance
- FR-1009: Conditional activation via `enable_knowledge_graph` config flag
- `EmbeddingPipelineState` TypedDict, `KGTriple` TypedDict from Phase 0
- Config fields: `enable_knowledge_graph`

**Must NOT receive:** Any implementation from `src/ingest/nodes/knowledge_graph_extraction.py`.

**Files:**
- Create: `tests/ingest/nodes/test_kg_extraction.py`

- [ ] Step 1: Write tests covering:
  - LLM extracts triples from enriched chunk text (FR-1001)
  - Triple output matches `KGTriple` schema (FR-1002)
  - Each triple has `source_chunk_id` matching the source chunk (FR-1008)
  - Entity normalization: "machine learning" and "Machine Learning" resolve to same form (FR-1003)
  - Alias resolution: "ML" resolves to "Machine Learning" (FR-1004)
  - Relation typing: extracted predicates mapped to controlled vocabulary (FR-1005)
  - Configurable ontology: custom predicate set is respected (FR-1006)
  - Structural fallback: headings become entities when LLM fails (FR-1007)
  - Structural fallback: list items become relations when LLM fails (FR-1007)
  - Node is no-op when `enable_knowledge_graph=False` (FR-1009)
  - Confidence score is assigned to each triple (0.0–1.0)
  - LLM failure on one chunk does not fail the entire node

- [ ] Step 2: Run tests:

```bash
pytest tests/ingest/nodes/test_kg_extraction.py -v
```

Expected: FAIL (stubs raise `NotImplementedError`)

---

### Task A-3.3b — Tests for Entity Consolidation

**Agent input (ONLY these):**
- FR-1003: Entity deduplication across chunks
- FR-1004: Alias resolution mapping variant forms to canonical identifiers
- FR-1005: Confidence scoring for entity merges
- `KGTriple` TypedDict from Phase 0
- Function signatures: `deduplicate_entities()`, `resolve_aliases()`, `score_merge_confidence()`

**Must NOT receive:** Any implementation from `src/ingest/support/entity.py`.

**Files:**
- Create: `tests/ingest/nodes/test_entity_consolidation.py`

- [ ] Step 1: Write tests covering:
  - Exact duplicate entities are merged (FR-1003)
  - Near-duplicate entities (fuzzy string match) are merged above threshold (FR-1003)
  - Alias table maps variant forms to canonical ID (FR-1004)
  - Merge confidence score reflects string similarity and context overlap (FR-1005)
  - Below-threshold entity pairs are NOT merged (FR-1005)
  - Consolidation across multiple chunks produces consistent canonical forms
  - Empty triple list returns empty consolidation result

- [ ] Step 2: Run tests:

```bash
pytest tests/ingest/nodes/test_entity_consolidation.py -v
```

Expected: FAIL (stubs raise `NotImplementedError`)

---

### Task A-3.3c — Tests for Graph Store Writer Node

**Agent input (ONLY these):**
- FR-1301: Persist triples to graph store (Weaviate cross-references in v1)
- FR-1302: Neo4j planned as v2 upgrade path
- FR-1303: Backend swapping via `graph_store_backend` config key without code changes
- FR-1304: Delete-and-reinsert on re-ingestion: delete existing triples for document before inserting
- `EmbeddingPipelineState` TypedDict, `KGTriple` TypedDict from Phase 0
- `GraphStoreWriteError` from Phase 0 (Task 0.3)
- Config fields: `enable_knowledge_graph`, `graph_store_backend`

**Must NOT receive:** Any implementation from `src/ingest/nodes/knowledge_graph_storage.py`.

**Files:**
- Create: `tests/ingest/nodes/test_kg_storage.py`

- [ ] Step 1: Write tests covering:
  - Triples are persisted to Weaviate as cross-references (FR-1301)
  - Re-ingestion deletes existing triples for document before inserting (FR-1304)
  - Node is no-op when `enable_knowledge_graph=False` or no triples in state
  - Backend config set to "weaviate" uses Weaviate writer (FR-1303)
  - Backend config set to "neo4j" uses Neo4j writer (FR-1303)
  - `GraphStoreWriteError` raised after exhausting retries
  - Successful write returns triple count in state

- [ ] Step 2: Run tests:

```bash
pytest tests/ingest/nodes/test_kg_storage.py -v
```

Expected: FAIL (stubs raise `NotImplementedError`)

---

### Task A-3.4 — Tests for Review Tier System

**Agent input (ONLY these):**
- FR-594: `review_tier` propagated from `CleanDocumentMetadata` to every chunk
- FR-803: `review_tier` stored as Weaviate filterable field
- Review tiers: `FULLY_REVIEWED`, `PARTIALLY_REVIEWED`, `SELF_REVIEWED`
- Default tier for new documents: `SELF_REVIEWED`
- `CleanDocumentMetadata` dataclass from Phase 0 (Task 0.5)

**Must NOT receive:** Any implementation from `src/ingest/clean_store.py` or node files.

**Files:**
- Create: `tests/ingest/nodes/test_review_tiers.py`

- [ ] Step 1: Write tests covering:
  - `review_tier` from metadata is attached to every chunk (FR-594)
  - `FULLY_REVIEWED` tier propagates correctly
  - `PARTIALLY_REVIEWED` tier propagates correctly
  - `SELF_REVIEWED` tier propagates correctly
  - Missing `review_tier` defaults to `SELF_REVIEWED`
  - `review_tier` is stored as a filterable field in Weaviate payload (FR-803)
  - Review tier is preserved through quality validation (not stripped)
  - Review tier update does not require re-embedding

- [ ] Step 2: Run tests:

```bash
pytest tests/ingest/nodes/test_review_tiers.py -v
```

Expected: FAIL (stubs raise `NotImplementedError`)

---

### Task A-4.0 — Tests for Quality Validation Node

**Agent input (ONLY these):**
- FR-1101: Quality score assignment based on content completeness and coherence (0.0–1.0)
- FR-1102: Configurable discard threshold (`min_quality_score`); chunks below are filtered
- FR-1103: Near-duplicate detection against stored chunks using hash and cosine similarity
- FR-1104: Configurable deduplication threshold (`dedup_threshold`)
- FR-1105: `review_tier` metadata passes through regardless of quality score
- `EmbeddingPipelineState` TypedDict, `QualityScore` TypedDict from Phase 0
- Function signature: `def embedding_quality_validation_node(state: EmbeddingPipelineState) -> dict`
- Config fields: `min_quality_score`, `dedup_threshold`

**Must NOT receive:** Any implementation from `src/ingest/nodes/quality_validation.py` or `src/ingest/common/shared.py` `_quality_score()`.

**Files:**
- Create: `tests/ingest/nodes/test_quality_validation.py`

- [ ] Step 1: Write tests covering:
  - Quality score assigned to each chunk in range [0.0, 1.0] (FR-1101)
  - Chunk below `min_quality_score` is filtered out (FR-1102)
  - Chunk at exactly `min_quality_score` passes (FR-1102, boundary test)
  - Chunk above `min_quality_score` passes (FR-1102)
  - Near-duplicate detected by content hash match (FR-1103)
  - Near-duplicate detected by cosine similarity above `dedup_threshold` (FR-1103)
  - Non-duplicate chunks with similar but distinct content pass (FR-1104)
  - `review_tier` is preserved on all chunks regardless of quality score (FR-1105)
  - Filtered chunks are logged but not embedded
  - Empty chunk list returns empty output
  - All-low-quality chunks: node returns empty list, no error

- [ ] Step 2: Run tests:

```bash
pytest tests/ingest/nodes/test_quality_validation.py -v
```

Expected: FAIL (stubs raise `NotImplementedError`)

---

### Task A-4.1 — Tests for Evaluation Framework

**Agent input (ONLY these):**
- No dedicated FR (cross-cutting)
- Evaluation metrics: chunk coherence score, metadata precision/recall, retrieval MRR
- Evaluation dataset: minimum 50 documents with annotations
- Function signatures: `evaluate_chunking()`, `evaluate_metadata()`, `evaluate_retrieval()`

**Must NOT receive:** Any implementation code.

**Files:**
- Create: `tests/ingest/test_evaluation_framework.py`

- [ ] Step 1: Write tests covering:
  - Evaluation harness loads annotated dataset
  - Chunk coherence metric returns score in [0.0, 1.0]
  - Metadata precision metric returns score in [0.0, 1.0]
  - Retrieval MRR metric returns score in [0.0, 1.0]
  - Regression detection: alert when metric drops below threshold
  - Empty dataset raises descriptive error

- [ ] Step 2: Run tests:

```bash
pytest tests/ingest/test_evaluation_framework.py -v
```

Expected: FAIL (stubs raise `NotImplementedError`)

---

### Task A-4.2 — Tests for Langfuse Observability Integration

**Agent input (ONLY these):**
- No dedicated FR (cross-cutting)
- Each pipeline run creates a Langfuse trace
- Each node creates a span with metadata (node name, input size, output size)
- LLM calls captured with token counts, latency, cost

**Must NOT receive:** Any implementation code.

**Files:**
- Create: `tests/ingest/test_langfuse_integration.py`

- [ ] Step 1: Write tests covering:
  - Pipeline run creates a Langfuse trace (mocked client)
  - Each node invocation creates a span
  - Span metadata includes node name, input size, output size
  - LLM calls are captured with token counts
  - Errors are tagged and searchable in trace
  - Langfuse SDK unavailable degrades gracefully (no crash)

- [ ] Step 2: Run tests:

```bash
pytest tests/ingest/test_langfuse_integration.py -v
```

Expected: FAIL (stubs raise `NotImplementedError`)

---

### Task A-4.3 — Tests for Batch Processing Hardening

**Agent input (ONLY these):**
- No dedicated FR (cross-cutting)
- Configurable concurrency via async semaphore
- Progress checkpointing: persist completed source_keys for crash recovery
- Partial failure isolation: single document failure does not abort batch
- Per-document memory limits

**Must NOT receive:** Any implementation code.

**Files:**
- Create: `tests/ingest/test_batch_processing.py`

- [ ] Step 1: Write tests covering:
  - Batch processes multiple documents
  - Concurrency limit respected (no more than N parallel)
  - Checkpoint persisted after each document completes
  - Resume from checkpoint after simulated crash
  - Single document failure does not abort remaining documents
  - Batch-level report aggregates per-document statistics
  - Memory limit prevents OOM on oversized document

- [ ] Step 2: Run tests:

```bash
pytest tests/ingest/test_batch_processing.py -v
```

Expected: FAIL (stubs raise `NotImplementedError`)

---

### Task A-4.4 — Tests for Schema Migration

**Agent input (ONLY these):**
- No dedicated FR (cross-cutting)
- `metadata_schema_version` field in all chunk payloads
- Migration registry: `{version -> migration_function}`
- Dry-run and rollback support

**Must NOT receive:** Any implementation code.

**Files:**
- Create: `tests/ingest/test_schema_migration.py`

- [ ] Step 1: Write tests covering:
  - All chunk payloads contain `metadata_schema_version` field
  - Migration from v1 to v2 transforms payload correctly
  - Dry-run mode reports changes without modifying data
  - Rollback on failed migration restores original state
  - Unknown version raises descriptive error
  - Sequential migration (v1 -> v2 -> v3) applies both migrations in order

- [ ] Step 2: Run tests:

```bash
pytest tests/ingest/test_schema_migration.py -v
```

Expected: FAIL (stubs raise `NotImplementedError`)

---

## Phase B — Implementation (Against Tests)

**Agent input per task:**
1. The task description from `EMBEDDING_PIPELINE_DESIGN.md` (Part A section for that task)
2. The test file from Phase A (the target to pass)
3. The contract files from Phase 0 (TypedDicts, signatures, exceptions)
4. The spec requirements (FR numbers + acceptance criteria)

**Must NOT receive:** Test files for OTHER tasks. Each implementation task receives only its own test file.

---

### Task B-S.2 — Implement Clean Document Store Reader

**Agent input:**
- Task S.2 description from `EMBEDDING_PIPELINE_DESIGN.md` (lines 50–77)
- `tests/ingest/test_clean_store_reader.py` (from Phase A-S.2)
- Contract files: `CleanDocumentMetadata`, `MissingCleanDocumentError`, `InvalidMetadataError`
- FR-591, FR-592, FR-593, FR-594, FR-595

**Files:**
- Modify: `src/ingest/clean_store.py` (replace stubs with implementation)

- [ ] Step 1: Implement `read(source_key)` — locate and read `{source_key}.md` + `{source_key}.meta.json`
- [ ] Step 2: Implement `validate_metadata(meta)` — schema validation against `CleanDocumentMetadata`
- [ ] Step 3: Implement `check_clean_hash_changed(source_key, current_hash)` — manifest comparison
- [ ] Step 4: Implement `propagate_metadata_to_chunk(chunk, metadata)` — field attachment
- [ ] Step 5: Implement optional SHA-256 integrity check (FR-595)
- [ ] Step 6: Run tests:

```bash
pytest tests/ingest/test_clean_store_reader.py -v
```

Expected: ALL PASS

- [ ] Step 7: Commit

---

### Task B-1.2 — Implement Embedding Pipeline DAG Skeleton

**Agent input:**
- Task 1.2 description from `EMBEDDING_PIPELINE_DESIGN.md` (lines 89–117)
- `tests/ingest/nodes/test_pipeline_dag.py` (from Phase A-1.2)
- Contract files: `EmbeddingPipelineState`, `PipelineConfig`, node stubs
- FR-591, FR-901, FR-1001, FR-1301

**Files:**
- Modify: `src/ingest/pipeline/workflow.py` (add `build_embedding_pipeline_graph()`)
- Modify: `src/ingest/pipeline/__init__.py` (expose public API)

- [ ] Step 1: Implement `build_embedding_pipeline_graph(config)` with all 8 nodes
- [ ] Step 2: Implement conditional routing functions for Nodes 9, 10, 13
- [ ] Step 3: Wire no-op stubs for Phase 2/3 nodes
- [ ] Step 4: Expose `compile()` via public API facade
- [ ] Step 5: Run tests:

```bash
pytest tests/ingest/nodes/test_pipeline_dag.py -v
```

Expected: ALL PASS

- [ ] Step 6: Commit

---

### Task B-1.6 — Implement Chunking Node (Rule-Based MVP)

**Agent input:**
- Task 1.6 description from `EMBEDDING_PIPELINE_DESIGN.md` (lines 121–156)
- `tests/ingest/nodes/test_chunking.py` (from Phase A-1.6, rule-based tests only)
- Contract files: `EmbeddingPipelineState`, `ChunkRecord`
- FR-601, FR-602, FR-603, FR-604, FR-605, FR-606

**Files:**
- Modify: `src/ingest/nodes/chunking.py` (add Embedding Pipeline chunking function)

- [ ] Step 1: Implement heading-aware structural splitting
- [ ] Step 2: Implement recursive character splitter fallback
- [ ] Step 3: Implement deterministic chunk ID generation: `SHA-256(source_key + ":" + str(ordinal) + ":" + content_hash)[:24]` where `content_hash = SHA-256(chunk_text)[:16]`
- [ ] Step 4: Implement table atomic chunking with header-row prepending for oversized tables
- [ ] Step 5: Implement adjacency links (`previous_chunk_id`, `next_chunk_id`)
- [ ] Step 6: Implement chunk metadata: ordinal, source_key, char_start, char_end, heading_path, content_type
- [ ] Step 7: Run tests:

```bash
pytest tests/ingest/nodes/test_chunking.py -v -k "not LLM"
```

Expected: ALL PASS (rule-based tests only)

- [ ] Step 8: Commit

---

### Task B-2.2a — Implement Chunk Enrichment Node

**Agent input:**
- Task 2.2a description from `EMBEDDING_PIPELINE_DESIGN.md` (lines 325–356)
- `tests/ingest/nodes/test_chunk_enrichment.py` (from Phase A-2.2a)
- Contract files: `EmbeddingPipelineState`, `ChunkRecord`, `EnrichedChunk`
- FR-701, FR-702, FR-703, FR-704, FR-705

**Files:**
- Modify: `src/ingest/nodes/chunk_enrichment.py` (add Embedding Pipeline enrichment function)

- [ ] Step 1: Implement boundary context attachment (previous tail + next head)
- [ ] Step 2: Implement `enriched_content = chunk_text + boundary_context`
- [ ] Step 3: Implement `context_header` assembly (title, section path, review tier)
- [ ] Step 4: Implement `embed_context_header` config flag (default: false)
- [ ] Step 5: Run tests:

```bash
pytest tests/ingest/nodes/test_chunk_enrichment.py -v
```

Expected: ALL PASS

- [ ] Step 6: Commit

---

### Task B-2.2b — Implement Metadata Generation Node

**Agent input:**
- Task 2.2b description from `EMBEDDING_PIPELINE_DESIGN.md` (lines 359–387)
- `tests/ingest/nodes/test_metadata_generation.py` (from Phase A-2.2b)
- Contract files: `EmbeddingPipelineState`, `EnrichedChunk`
- FR-801, FR-802, FR-803, FR-804, FR-805, FR-806

**Files:**
- Modify: `src/ingest/nodes/metadata_generation.py` (add Embedding Pipeline metadata function)

- [ ] Step 1: Implement LLM keyword extraction per chunk
- [ ] Step 2: Implement LLM entity extraction per chunk
- [ ] Step 3: Implement TF-IDF fallback on LLM failure
- [ ] Step 4: Implement domain vocabulary validation and injection
- [ ] Step 5: Implement document-level summary aggregation
- [ ] Step 6: Run tests:

```bash
pytest tests/ingest/nodes/test_metadata_generation.py -v
```

Expected: ALL PASS

- [ ] Step 7: Commit

---

### Task B-1.7 — Implement Embedding Generation

**Agent input:**
- Task 1.7 description from `EMBEDDING_PIPELINE_DESIGN.md` (lines 159–187)
- `tests/ingest/nodes/test_embedding_storage.py` (from Phase A-1.7, embedding generation tests only)
- Contract files: `EmbeddingPipelineState`, `EnrichedChunk`, `EmbeddingDimensionMismatchError`
- FR-1201, FR-1202, FR-1203, FR-1204

**Files:**
- Modify: `src/ingest/nodes/embedding_storage.py` (add embedding generation)

- [ ] Step 1: Implement batched embedding calls
- [ ] Step 2: Implement exponential backoff retry with jitter
- [ ] Step 3: Implement token-count pre-validation
- [ ] Step 4: Implement BYOM mode
- [ ] Step 5: Implement dimensionality validation
- [ ] Step 6: Implement document prefix application
- [ ] Step 7: Run tests:

```bash
pytest tests/ingest/nodes/test_embedding_storage.py -v -k "embedding_generation"
```

Expected: ALL PASS (embedding generation tests only)

- [ ] Step 8: Commit

---

### Task B-1.8 — Implement Vector Store Upsert

**Agent input:**
- Task 1.8 description from `EMBEDDING_PIPELINE_DESIGN.md` (lines 191–226)
- `tests/ingest/nodes/test_embedding_storage.py` (from Phase A-1.8, upsert tests only)
- Contract files: `EmbeddingPipelineState`, `VectorStoreWriteError`
- FR-1205, FR-1206, FR-1207, FR-1208, FR-1209

**Files:**
- Modify: `src/ingest/nodes/embedding_storage.py` (add upsert logic)

- [ ] Step 1: Implement Weaviate upsert with full metadata envelope
- [ ] Step 2: Implement batched upsert
- [ ] Step 3: Implement delete-and-reinsert for re-ingestion
- [ ] Step 4: Implement retry logic for transient errors
- [ ] Step 5: Implement asymmetric prefix handling
- [ ] Step 6: Implement BM25 keyword indexing
- [ ] Step 7: Run tests:

```bash
pytest tests/ingest/nodes/test_embedding_storage.py -v -k "vector_store"
```

Expected: ALL PASS (upsert tests only)

- [ ] Step 8: Commit

---

### Task B-1.9 — Implement Result Reporting

**Agent input:**
- Task 1.9 description from `EMBEDDING_PIPELINE_DESIGN.md` (lines 228–248)
- `tests/ingest/test_embedding_report.py` (from Phase A-1.9)
- Contract files: `EmbeddingPipelineState`, `EmbeddingReport`
- FR-1201

**Files:**
- Modify: `src/ingest/report.py` (replace stub with implementation)

- [ ] Step 1: Implement `build_embedding_report()` statistics aggregation
- [ ] Step 2: Implement JSON serialization
- [ ] Step 3: Implement human-readable summary logging
- [ ] Step 4: Run tests:

```bash
pytest tests/ingest/test_embedding_report.py -v
```

Expected: ALL PASS

- [ ] Step 5: Commit

---

### Task B-1.10 — Implement Re-Ingestion Flow

**Agent input:**
- Task 1.10 description from `EMBEDDING_PIPELINE_DESIGN.md` (lines 251–276)
- `tests/ingest/test_reingestion.py` (from Phase A-1.10)
- Contract files: `EmbeddingPipelineState`, `CleanDocumentMetadata`
- FR-593, FR-1205, FR-1208

**Files:**
- Modify: `src/ingest/pipeline/impl.py` (add `EmbeddingPipelineRuntime`)

- [ ] Step 1: Implement `_delete_existing_chunks()` by source_key filter
- [ ] Step 2: Wire `clean_hash` comparison into runtime
- [ ] Step 3: Implement `force` flag bypass
- [ ] Step 4: Implement dry-run mode
- [ ] Step 5: Run tests:

```bash
pytest tests/ingest/test_reingestion.py -v
```

Expected: ALL PASS

- [ ] Step 6: Commit

---

### Task B-2.1 — Implement LLM-Assisted Chunking

**Agent input:**
- Task 2.1 description from `EMBEDDING_PIPELINE_DESIGN.md` (lines 291–321)
- `tests/ingest/nodes/test_chunking.py` (from Phase A-2.1, LLM-specific tests only)
- Contract files: `EmbeddingPipelineState`, `ChunkRecord`
- FR-606, FR-607, FR-608, FR-609, FR-610, FR-611

**Files:**
- Modify: `src/ingest/nodes/chunking.py` (add LLM chunking strategy)

- [ ] Step 1: Implement LLM boundary detection prompt
- [ ] Step 2: Implement LLM chunking behind strategy interface
- [ ] Step 3: Implement fallback to rule-based on LLM failure
- [ ] Step 4: Implement content type tagging
- [ ] Step 5: Implement domain vocabulary boundary respect
- [ ] Step 6: Implement chunk count limit
- [ ] Step 7: Run tests:

```bash
pytest tests/ingest/nodes/test_chunking.py -v
```

Expected: ALL PASS (both rule-based and LLM tests)

- [ ] Step 8: Commit

---

### Task B-2.4 — Implement Domain Vocabulary System

**Agent input:**
- Task 2.4 description from `EMBEDDING_PIPELINE_DESIGN.md` (lines 390–409)
- `tests/ingest/test_domain_vocabulary.py` (from Phase A-2.4)
- FR-803, FR-804

**Files:**
- Create: `src/ingest/support/vocabulary.py`

- [ ] Step 1: Define vocabulary schema (term, synonyms, category, weight)
- [ ] Step 2: Implement vocabulary loader from YAML
- [ ] Step 3: Implement hot-reload on file change
- [ ] Step 4: Implement keyword validation against vocabulary
- [ ] Step 5: Implement vocabulary injection for text terms
- [ ] Step 6: Run tests:

```bash
pytest tests/ingest/test_domain_vocabulary.py -v
```

Expected: ALL PASS

- [ ] Step 7: Commit

---

### Task B-3.2 — Implement Cross-Reference Extraction Node

**Agent input:**
- Task 3.2 description from `EMBEDDING_PIPELINE_DESIGN.md` (lines 420–442)
- `tests/ingest/nodes/test_cross_reference.py` (from Phase A-3.2)
- Contract files: `EmbeddingPipelineState`
- FR-901, FR-902, FR-903, FR-904, FR-905

**Files:**
- Modify: `src/ingest/nodes/cross_reference_extraction.py`

- [ ] Step 1: Implement regex + LLM hybrid reference detection
- [ ] Step 2: Implement reference resolution to existing source_keys
- [ ] Step 3: Implement cross-reference edge storage in chunk metadata
- [ ] Step 4: Implement dangling reference handling (warn, don't fail)
- [ ] Step 5: Run tests:

```bash
pytest tests/ingest/nodes/test_cross_reference.py -v
```

Expected: ALL PASS

- [ ] Step 6: Commit

---

### Task B-3.3a — Implement Triple Extraction Node

**Agent input:**
- Task 3.3a description from `EMBEDDING_PIPELINE_DESIGN.md` (lines 446–477)
- `tests/ingest/nodes/test_kg_extraction.py` (from Phase A-3.3a)
- Contract files: `EmbeddingPipelineState`, `KGTriple`
- FR-1001, FR-1002, FR-1003, FR-1004, FR-1005, FR-1006, FR-1007, FR-1008, FR-1009

**Files:**
- Modify: `src/ingest/nodes/knowledge_graph_extraction.py`

- [ ] Step 1: Implement LLM triple extraction prompt
- [ ] Step 2: Implement entity normalization
- [ ] Step 3: Implement relation typing
- [ ] Step 4: Implement provenance tracking (source_chunk_id)
- [ ] Step 5: Implement structural triple fallback
- [ ] Step 6: Implement conditional activation via config
- [ ] Step 7: Run tests:

```bash
pytest tests/ingest/nodes/test_kg_extraction.py -v
```

Expected: ALL PASS

- [ ] Step 8: Commit

---

### Task B-3.3b — Implement Entity Consolidation

**Agent input:**
- Task 3.3b description from `EMBEDDING_PIPELINE_DESIGN.md` (lines 481–503)
- `tests/ingest/nodes/test_entity_consolidation.py` (from Phase A-3.3b)
- Contract files: `KGTriple`
- FR-1003, FR-1004, FR-1005

**Files:**
- Create: `src/ingest/support/entity.py`

- [ ] Step 1: Implement entity deduplication (string similarity + embedding match)
- [ ] Step 2: Implement alias resolution table
- [ ] Step 3: Implement confidence scoring for merges
- [ ] Step 4: Run tests:

```bash
pytest tests/ingest/nodes/test_entity_consolidation.py -v
```

Expected: ALL PASS

- [ ] Step 5: Commit

---

### Task B-3.3c — Implement Graph Store Writer Node

**Agent input:**
- Task 3.3c description from `EMBEDDING_PIPELINE_DESIGN.md` (lines 507–533)
- `tests/ingest/nodes/test_kg_storage.py` (from Phase A-3.3c)
- Contract files: `EmbeddingPipelineState`, `KGTriple`, `GraphStoreWriteError`
- FR-1301, FR-1302, FR-1303, FR-1304

**Files:**
- Modify: `src/ingest/nodes/knowledge_graph_storage.py`

- [ ] Step 1: Implement Weaviate cross-reference writing (v1 backend)
- [ ] Step 2: Implement Neo4j backend interface (v2 planned)
- [ ] Step 3: Implement backend swapping via config
- [ ] Step 4: Implement re-ingestion cleanup (delete before insert)
- [ ] Step 5: Run tests:

```bash
pytest tests/ingest/nodes/test_kg_storage.py -v
```

Expected: ALL PASS

- [ ] Step 6: Commit

---

### Task B-3.4 — Implement Review Tier System

**Agent input:**
- Task 3.4 description from `EMBEDDING_PIPELINE_DESIGN.md` (lines 537–559)
- `tests/ingest/nodes/test_review_tiers.py` (from Phase A-3.4)
- Contract files: `CleanDocumentMetadata`
- FR-594, FR-803

**Files:**
- Modify: `src/ingest/clean_store.py` (review tier propagation)
- Modify: `src/ingest/nodes/embedding_storage.py` (Weaviate filterable field)

- [ ] Step 1: Implement review tier propagation via `propagate_metadata_to_chunk`
- [ ] Step 2: Implement Weaviate filterable field storage
- [ ] Step 3: Implement default tier assignment (`SELF_REVIEWED`)
- [ ] Step 4: Run tests:

```bash
pytest tests/ingest/nodes/test_review_tiers.py -v
```

Expected: ALL PASS

- [ ] Step 5: Commit

---

### Task B-4.0 — Implement Quality Validation Node

**Agent input:**
- Task 4.0 description from `EMBEDDING_PIPELINE_DESIGN.md` (lines 570–593)
- `tests/ingest/nodes/test_quality_validation.py` (from Phase A-4.0)
- Contract files: `EmbeddingPipelineState`, `QualityScore`
- FR-1101, FR-1102, FR-1103, FR-1104, FR-1105

**Files:**
- Modify: `src/ingest/nodes/quality_validation.py`

- [ ] Step 1: Implement quality scoring (completeness, coherence, keyword density)
- [ ] Step 2: Implement threshold filtering
- [ ] Step 3: Implement near-duplicate detection (hash + cosine similarity)
- [ ] Step 4: Attach quality_score to surviving chunks
- [ ] Step 5: Ensure review_tier passes through regardless
- [ ] Step 6: Run tests:

```bash
pytest tests/ingest/nodes/test_quality_validation.py -v
```

Expected: ALL PASS

- [ ] Step 7: Commit

---

### Task B-4.1 — Implement Evaluation Framework

**Agent input:**
- Task 4.1 description from `EMBEDDING_PIPELINE_DESIGN.md` (lines 596–616)
- `tests/ingest/test_evaluation_framework.py` (from Phase A-4.1)
- No dedicated FR

**Files:**
- Create: `src/ingest/evaluation/` directory with evaluation harness

- [ ] Step 1: Define evaluation metrics
- [ ] Step 2: Implement chunk coherence scoring
- [ ] Step 3: Implement metadata precision/recall
- [ ] Step 4: Implement retrieval MRR
- [ ] Step 5: Implement regression detection
- [ ] Step 6: Run tests:

```bash
pytest tests/ingest/test_evaluation_framework.py -v
```

Expected: ALL PASS

- [ ] Step 7: Commit

---

### Task B-4.2 — Implement Langfuse Observability Integration

**Agent input:**
- Task 4.2 description from `EMBEDDING_PIPELINE_DESIGN.md` (lines 620–642)
- `tests/ingest/test_langfuse_integration.py` (from Phase A-4.2)
- No dedicated FR

**Files:**
- Modify: `src/ingest/pipeline/impl.py` (trace creation)
- Modify: Node files (span creation)

- [ ] Step 1: Add Langfuse SDK dependency
- [ ] Step 2: Instrument pipeline runtime with trace creation per document
- [ ] Step 3: Instrument each node with span creation
- [ ] Step 4: Capture LLM calls with token counts
- [ ] Step 5: Add error tagging
- [ ] Step 6: Run tests:

```bash
pytest tests/ingest/test_langfuse_integration.py -v
```

Expected: ALL PASS

- [ ] Step 7: Commit

---

### Task B-4.3 — Implement Batch Processing Hardening

**Agent input:**
- Task 4.3 description from `EMBEDDING_PIPELINE_DESIGN.md` (lines 646–672)
- `tests/ingest/test_batch_processing.py` (from Phase A-4.3)
- No dedicated FR

**Files:**
- Modify: `src/ingest/pipeline/impl.py` (batch processing, concurrency, checkpointing)

- [ ] Step 1: Implement configurable concurrency (async semaphore)
- [ ] Step 2: Implement progress checkpointing
- [ ] Step 3: Implement partial failure isolation
- [ ] Step 4: Implement per-document memory limits
- [ ] Step 5: Implement batch-level reporting
- [ ] Step 6: Run tests:

```bash
pytest tests/ingest/test_batch_processing.py -v
```

Expected: ALL PASS

- [ ] Step 7: Commit

---

### Task B-4.4 — Implement Schema Migration

**Agent input:**
- Task 4.4 description from `EMBEDDING_PIPELINE_DESIGN.md` (lines 676–697)
- `tests/ingest/test_schema_migration.py` (from Phase A-4.4)
- No dedicated FR

**Files:**
- Create: `src/ingest/migration.py`

- [ ] Step 1: Define `metadata_schema_version` field convention
- [ ] Step 2: Implement migration registry
- [ ] Step 3: Implement dry-run mode
- [ ] Step 4: Implement rollback support
- [ ] Step 5: Run tests:

```bash
pytest tests/ingest/test_schema_migration.py -v
```

Expected: ALL PASS

- [ ] Step 6: Commit

---

## Task Dependency Graph

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         PHASE 0 — CONTRACTS                             │
│                                                                         │
│  Task 0.1 (State) ─┐                                                   │
│  Task 0.2 (Schemas) ├──→ Task 0.4 (Stubs) ──→ [HUMAN REVIEW GATE]     │
│  Task 0.3 (Exceptions)┘           ↑                                    │
│  Task 0.5 (Config) ──────────────┘                                     │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                    ┌────────────┴────────────┐
                    ▼                         ▼
┌───────────────────────────┐  ┌──────────────────────────────────────────┐
│    PHASE A — TESTS        │  │  (Phase A completes before Phase B)      │
│                           │  │                                          │
│  A-S.2 (Clean Store)     │  │                                          │
│  A-1.2 (DAG Skeleton)    │  │                                          │
│  A-1.6 (Chunking)        │  │                                          │
│  A-2.2a (Enrichment)     │  │                                          │
│  A-2.2b (Metadata Gen)   │  │                                          │
│  A-1.7 (Embedding Gen)   │  │                                          │
│  A-1.8 (Vector Upsert)   │  │                                          │
│  A-1.9 (Reporting)       │  │                                          │
│  A-1.10 (Re-Ingestion)   │  │                                          │
│  A-2.1 (LLM Chunking)    │  │                                          │
│  A-2.4 (Vocabulary)      │  │                                          │
│  A-3.2 (Cross-Refs)      │  │                                          │
│  A-3.3a (Triple Extract)  │  │                                          │
│  A-3.3b (Entity Consol)  │  │                                          │
│  A-3.3c (Graph Writer)   │  │                                          │
│  A-3.4 (Review Tiers)    │  │                                          │
│  A-4.0 (Quality Valid)   │  │                                          │
│  A-4.1 (Eval Framework)  │  │                                          │
│  A-4.2 (Langfuse)        │  │                                          │
│  A-4.3 (Batch Hardening) │  │                                          │
│  A-4.4 (Schema Migration)│  │                                          │
└───────────────────────────┘  └──────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    PHASE B — IMPLEMENTATION                             │
│                                                                         │
│  Part A0 (Clean Document Store — Boundary)                              │
│  └── B-S.2: Clean Store Reader ────────────────────────────────────┐    │
│                                                                    │    │
│  Phase 1 (Core Embedding — MVP)                                    │    │
│  ├── B-1.2: DAG Skeleton ◄─── B-S.2 ──────────────────────────────┤    │
│  ├── B-1.6: Chunking ◄─── B-S.2, B-1.2                  [CRITICAL]│    │
│  ├── B-1.7: Embedding Generation ◄─── B-1.6             [CRITICAL]│    │
│  ├── B-1.8: Vector Store Upsert ◄─── B-1.7              [CRITICAL]│    │
│  ├── B-1.9: Result Reporting ◄─── B-1.8                           │    │
│  └── B-1.10: Re-Ingestion Flow ◄─── B-S.2, B-1.8                 │    │
│                                                                    │    │
│  Phase 2 (LLM Enhancement)                                        │    │
│  ├── B-2.1: LLM-Assisted Chunking ◄─── B-1.6                     │    │
│  ├── B-2.2a: Chunk Enrichment ◄─── B-1.6                [CRITICAL]│    │
│  ├── B-2.2b: Metadata Generation ◄─── B-2.2a            [CRITICAL]│    │
│  └── B-2.4: Domain Vocabulary ◄─── None (parallel)                │    │
│                                                                    │    │
│  Phase 3 (Extended Features)                                       │    │
│  ├── B-3.2: Cross-Reference Extraction ◄─── B-2.2b                │    │
│  ├── B-3.3a: Triple Extraction ◄─── B-2.2a                        │    │
│  ├── B-3.3b: Entity Consolidation ◄─── B-3.3a                     │    │
│  ├── B-3.3c: Graph Store Writer ◄─── B-3.3a, B-3.3b               │    │
│  └── B-3.4: Review Tier System ◄─── B-S.2, B-2.2b                 │    │
│                                                                    │    │
│  Phase 4 (Quality & Operations)                                    │    │
│  ├── B-4.0: Quality Validation ◄─── B-2.2b              [CRITICAL]│    │
│  ├── B-4.1: Evaluation Framework ◄─── Phase 1 complete             │    │
│  ├── B-4.2: Langfuse Observability ◄─── B-1.2                     │    │
│  ├── B-4.3: Batch Processing ◄─── B-1.10                          │    │
│  └── B-4.4: Schema Migration ◄─── B-1.8                           │    │
│                                                                         │
│  Critical path (MVP): B-S.2 → B-1.2 → B-1.6 → B-1.7 → B-1.8         │
│  Critical path (full): + B-2.2a → B-2.2b → B-4.0                      │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Task-to-Requirement Mapping

| Task | Phase 0 | Phase A Test File | Phase B Requirements |
|------|---------|-------------------|---------------------|
| S.2 Clean Document Store Reader | 0.1, 0.3, 0.4, 0.5 | `tests/ingest/test_clean_store_reader.py` | FR-591, FR-592, FR-593, FR-594, FR-595 |
| 1.2 Embedding Pipeline DAG Skeleton | 0.1, 0.4 | `tests/ingest/nodes/test_pipeline_dag.py` | FR-591, FR-901, FR-1001, FR-1301 |
| 1.6 Node 6: Chunking (Rule-Based) | 0.1, 0.2 | `tests/ingest/nodes/test_chunking.py` | FR-601, FR-602, FR-603, FR-604, FR-605, FR-606 |
| 2.2a Node 7: Chunk Enrichment | 0.1, 0.2 | `tests/ingest/nodes/test_chunk_enrichment.py` | FR-701, FR-702, FR-703, FR-704, FR-705 |
| 2.2b Node 8: Metadata Generation | 0.1, 0.2 | `tests/ingest/nodes/test_metadata_generation.py` | FR-801, FR-802, FR-803, FR-804, FR-805, FR-806 |
| 1.7 Node 12: Embedding Generation | 0.1, 0.2, 0.3 | `tests/ingest/nodes/test_embedding_storage.py` | FR-1201, FR-1202, FR-1203, FR-1204 |
| 1.8 Vector Store Upsert | 0.1, 0.3 | `tests/ingest/nodes/test_embedding_storage.py` | FR-1205, FR-1206, FR-1207, FR-1208, FR-1209 |
| 1.9 Result Reporting | 0.2 | `tests/ingest/test_embedding_report.py` | FR-1201 |
| 1.10 Re-Ingestion Flow | 0.1, 0.5 | `tests/ingest/test_reingestion.py` | FR-593, FR-1205, FR-1208 |
| 2.1 LLM-Assisted Chunking | 0.1, 0.2 | `tests/ingest/nodes/test_chunking.py` | FR-606, FR-607, FR-608, FR-609, FR-610, FR-611 |
| 2.4 Domain Vocabulary System | — | `tests/ingest/test_domain_vocabulary.py` | FR-803, FR-804 |
| 3.2 Node 9: Cross-Reference Extraction | 0.1 | `tests/ingest/nodes/test_cross_reference.py` | FR-901, FR-902, FR-903, FR-904, FR-905 |
| 3.3a Node 10: Triple Extraction | 0.1, 0.2 | `tests/ingest/nodes/test_kg_extraction.py` | FR-1001–FR-1009 |
| 3.3b Entity Consolidation | 0.2 | `tests/ingest/nodes/test_entity_consolidation.py` | FR-1003, FR-1004, FR-1005 |
| 3.3c Node 13: Graph Store Writer | 0.1, 0.2, 0.3 | `tests/ingest/nodes/test_kg_storage.py` | FR-1301, FR-1302, FR-1303, FR-1304 |
| 3.4 Review Tier System | 0.5 | `tests/ingest/nodes/test_review_tiers.py` | FR-594, FR-803 |
| 4.0 Node 11: Quality Validation | 0.1, 0.2 | `tests/ingest/nodes/test_quality_validation.py` | FR-1101, FR-1102, FR-1103, FR-1104, FR-1105 |
| 4.1 Evaluation Framework | — | `tests/ingest/test_evaluation_framework.py` | — (cross-cutting) |
| 4.2 Langfuse Observability | — | `tests/ingest/test_langfuse_integration.py` | — (cross-cutting) |
| 4.3 Batch Processing Hardening | — | `tests/ingest/test_batch_processing.py` | — (cross-cutting) |
| 4.4 Schema Migration | — | `tests/ingest/test_schema_migration.py` | — (cross-cutting) |

---

## Requirement Coverage Verification

All 57 requirements (FR-591 through FR-1304) are covered:

| Requirement Range | Count | Tasks |
|-------------------|-------|-------|
| FR-591–FR-595 (Clean Store Input) | 5 | S.2 |
| FR-601–FR-611 (Chunking) | 11 | 1.6, 2.1 |
| FR-701–FR-705 (Chunk Enrichment) | 5 | 2.2a |
| FR-801–FR-806 (Metadata Generation) | 6 | 2.2b |
| FR-901–FR-905 (Cross-Reference) | 5 | 3.2 |
| FR-1001–FR-1009 (KG Extraction) | 9 | 3.3a, 3.3b |
| FR-1101–FR-1105 (Quality Validation) | 5 | 4.0 |
| FR-1201–FR-1209 (Embedding & Storage) | 9 | 1.7, 1.8 |
| FR-1301–FR-1304 (KG Storage) | 4 | 3.3c |
| **Total** | **57** | |

---

## Companion Documents

| Document | Role |
|----------|------|
| `EMBEDDING_PIPELINE_SPEC.md` | Authoritative requirements baseline (FR-591–FR-1304) |
| `EMBEDDING_PIPELINE_SPEC_SUMMARY.md` | Concise requirements digest |
| `EMBEDDING_PIPELINE_DESIGN.md` | Task descriptions, subtasks, code appendix |
| `EMBEDDING_PIPELINE_IMPLEMENTATION.md` (this document) | Three-phase implementation plan with test isolation |
| `DOCUMENT_PROCESSING_DESIGN.md` | Phase 1 implementation (shared patterns) |
| `INGESTION_PIPELINE_ENGINEERING_GUIDE.md` | Developer guide — architecture, extension steps |
| `INGESTION_NEW_ENGINEER_ONBOARDING_CHECKLIST.md` | Quick-start checklist |
