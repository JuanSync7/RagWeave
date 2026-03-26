# Ingest Pipeline — Test Docs (Phase D)

> **For write-module-tests agents:** This document is your source of truth.
> Read ONLY your assigned module section. Do not read source files, implementation code,
> or other modules' test specs.

**Engineering guide:** `docs/ingestion/INGESTION_PIPELINE_ENGINEERING_GUIDE.md`
**Phase 1 test docs:** `docs/ingestion/document_processing/DOCUMENT_PROCESSING_MODULE_TESTS.md`
**Spec (platform):** `docs/ingestion/INGESTION_PLATFORM_SPEC.md`
**Spec (embedding):** `docs/ingestion/embedding/EMBEDDING_PIPELINE_SPEC.md`
**Produced by:** write-test-docs skill

**Scope:** This document covers the Embedding Pipeline nodes (Phase 2), the two-phase
orchestrator (`ingest_file` / `ingest_directory`), shared helpers, LLM support, and CLI.
Phase 1 doc-processing node tests are in `DOCUMENT_PROCESSING_MODULE_TESTS.md`.

---

## Mock / Stub Interface Specifications

### Mock: run_document_processing

**What it replaces:** Phase 1 LangGraph pipeline invocation

**Interface to mock:**
```python
def run_document_processing(state: dict) -> dict:
    """Returns DocumentProcessingState output dict."""
    ...
```

**Happy path return:**
```python
{
    "source_hash": "abc123...",
    "raw_text": "raw document text",
    "cleaned_text": "# Clean Markdown\n\nContent here.",
    "refactored_text": None,
    "errors": [],
    "processing_log": ["document_ingestion:ok", "structure_detection:ok"],
    "structure": {"has_figures": False},
    "multimodal_notes": [],
}
```

**Error path return:**
```python
{
    "source_hash": "", "raw_text": "", "cleaned_text": "",
    "refactored_text": None, "structure": {}, "multimodal_notes": [],
    "errors": ["read_failed:doc.txt:some error"],
    "processing_log": ["document_ingestion:failed"],
}
```

**Patch target:** `src.ingest.impl.run_document_processing`
**Used by modules:** `src/ingest/impl.py`

---

### Mock: run_embedding_pipeline

**What it replaces:** Phase 2 LangGraph pipeline invocation

**Interface to mock:**
```python
def run_embedding_pipeline(state: dict) -> dict:
    """Returns EmbeddingPipelineState output dict."""
    ...
```

**Happy path return:**
```python
{
    "stored_count": 3,
    "metadata_summary": "A test document.",
    "metadata_keywords": ["test"],
    "errors": [],
    "processing_log": ["chunking:ok", "embedding_storage:ok"],
    "chunks": [],
    "kg_triples": [],
}
```

**Patch target:** `src.ingest.impl.run_embedding_pipeline`
**Used by modules:** `src/ingest/impl.py`

---

### Mock: Weaviate client

**What it replaces:** Weaviate vector store client

**Interface to mock:**
```python
client.collections.get(collection_name).data.delete_many(where=...)
client.collections.get(collection_name).data.insert(properties=..., vector=...)
```

**Setup:**
```python
from unittest.mock import MagicMock
weaviate_client = MagicMock()
```

**Used by modules:** `src/ingest/embedding/nodes/embedding_storage.py`, `src/ingest/impl.py`

---

### Mock: Embedder

**What it replaces:** Text embedding model API

**Interface to mock:**
```python
embedder.embed(text: str) -> list[float]
```

**Happy path return:** `[0.1, 0.2, ..., 0.9]`
**Error path:** `raise RuntimeError("embed timeout")`
**Used by modules:** `src/ingest/embedding/nodes/embedding_storage.py`, `src/ingest/embedding/nodes/chunking.py`

---

### Mock: MinIO / object store client

**What it replaces:** MinIO or S3-compatible object store

**Interface to mock:**
```python
minio_client.put_object(bucket_name, object_name, data, length)
# or equivalent upload method name — read source to confirm exact API
```

**Used by modules:** `src/ingest/embedding/nodes/document_storage_node.py`

---

## Module Test Specifications

---

### `src/ingest/impl.py` — Two-Phase Orchestrator

**Module purpose:** Public API for the ingestion pipeline, providing single-file two-phase orchestration (`ingest_file`) and batch directory ingestion with idempotency, manifest tracking, and update-mode removal (`ingest_directory`).

**In scope:**
- `ingest_directory` — full batch flow (discovery, manifest comparison, skip logic, per-source exception isolation, update_mode removal, manifest save)
- `_find_manifest_entry` — priority-ordered manifest lookup (source_key > source_id > source_uri > legacy source_name)
- Config validation via `verify_core_design` before any file processing (FR-1800, FR-1801)
- Skip logic when `source_hash` matches manifest AND `update_mode=False` (FR-1401)
- Update-mode removal of sources present in manifest but absent from discovered files (FR-1410)
- `IngestionRunSummary` field correctness (`total`, `processed`, `skipped`, `failed`, `removed`)
- Per-source exception isolation — one failure must not halt the batch
- `ingest_file` result field completeness (`kg_triples`, `metadata_summary`, `metadata_keywords`, `chunks`, `processing_log`)

**Out of scope:**
- `run_document_processing` internals (Phase 1 graph)
- `run_embedding_pipeline` internals (Phase 2 graph)
- `CleanDocumentStore` internals
- Weaviate collection query/insert logic
- Manifest serialization format

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| `ingest_directory` processes all new files | 3 source files, empty manifest, valid config | `IngestionRunSummary(total=3, processed=3, skipped=0, failed=0, removed=0)`; `ingest_file` called 3 times |
| `ingest_directory` skips unchanged file | 2 files; manifest has matching hash for file A; `update_mode=False` | `ingest_file` called once (file B only); `skipped=1` |
| `ingest_directory` re-ingests changed file (`update_mode=True`) | 1 file; manifest hash differs from current hash | `ingest_file` called once; `processed=1`, `skipped=0` |
| `ingest_directory` removes deleted source in update_mode | manifest has entry for stale key not in discovered files; `update_mode=True` | Weaviate delete called for stale key; manifest entry removed; `removed=1` |
| `ingest_directory` removes multiple deleted sources | manifest has 3 stale entries, 0 discovered files; `update_mode=True` | `removed=3`; Weaviate delete called 3 times; manifest saved empty |
| `ingest_file` result includes all Phase 2 fields | Phase 2 returns chunks, kg_triples, summary, keywords | `result.chunks`, `.kg_triples`, `.metadata_summary`, `.metadata_keywords` match Phase 2 output |
| `ingest_file` merges processing logs | Phase 1 log `["p1"]`, Phase 2 log `["p2"]` | `result.processing_log == ["p1", "p2"]` |
| `verify_core_design` valid config | `build_kg=True, enable_knowledge_graph_extraction=True, enable_knowledge_graph_storage=True` | `IngestionDesignCheck(ok=True, errors=[])` |
| `_find_manifest_entry` matches by source_key | manifest keyed by source_key; query matches source_key | Returns source_key-matched entry |
| `_find_manifest_entry` falls back to source_id | no source_key match; source_id matches | Returns entry matched by source_id |
| `_find_manifest_entry` falls back to source_uri | no source_key/source_id match; source_uri matches | Returns entry matched by source_uri |
| `_find_manifest_entry` falls back to legacy source_name | no other field matches | Returns entry matched by source_name |
| `_find_manifest_entry` returns None | no field matches | Returns `None` |
| `save_manifest` called once after run | any valid run | `save_manifest` called exactly once with updated dict |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| Config validation halts before processing (FR-1800) | `enable_knowledge_graph_storage=True` but `build_kg=False` | `ValueError` raised before `ingest_file` is called |
| Config validation error message actionable (FR-1801) | `enable_docling_parser=True, docling_model=""` | `ValueError` message references `docling_model` |
| Per-source exception isolated | `ingest_file` raises `RuntimeError` for file 2 of 3 | File 3 still processed; `failed=1`, `processed=2`; no re-raise |
| `verify_core_design` never raises | any invalid config | Returns `IngestionDesignCheck`; does NOT raise |
| `verify_core_design` KG storage without `build_kg` | `enable_knowledge_graph_storage=True, build_kg=False` | `ok=False`; `errors` list non-empty |
| `verify_core_design` KG storage without extraction | `enable_knowledge_graph_storage=True, enable_knowledge_graph_extraction=False` | `ok=False`; errors non-empty |
| Update-mode removal skipped in non-update mode | `update_mode=False`; stale manifest entries present | Weaviate delete NOT called; `removed=0` |

#### Boundary conditions

- Empty source directory, `update_mode=True`: 0 files discovered; all manifest entries treated as removed
- All files skipped: `ingest_file` never called; `processed=0, skipped=N`
- `allowed_extensions` filter: files with other extensions excluded from `total` count
- `IngestFileResult.errors == []` (empty list, not just falsy) when both phases succeed
- `IngestionRunSummary` counts are integers, not None

#### Integration points

- `run_document_processing` patched at `src.ingest.impl.run_document_processing`
- `run_embedding_pipeline` patched at `src.ingest.impl.run_embedding_pipeline`
- `load_manifest` / `save_manifest` patched at `src.ingest.impl.load_manifest` / `src.ingest.impl.save_manifest`
- Weaviate mock: assert `delete_many` called with `source_key` filter

#### Known test gaps

- `clean_hash` skip for Phase 2 (FR-1402): `clean_hash` field not exposed in `IngestFileResult` — deferred to Phase 2 pipeline tests
- `persist_refactor_mirror` and `export_processed` flags: behavior not described in engineering guide — untestable without source access
- Atomic replace ordering guarantee (FR-1400): delete vs. insert ordering best verified at integration test level

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code, other modules' test specs, or the engineering guide directly.

---

### `src/ingest/embedding/nodes/document_storage_node.py` — Document Storage

**Module purpose:** Persists full clean Markdown to MinIO/object store before chunking and computes a stable `document_id` from the source key regardless of upload outcome.

**In scope:**
- `document_id` = SHA-256(source_key)[:24] — always set
- Upload when `store_documents=True` and minio_client is not None
- Skip upload when `store_documents=False` — `document_id` still set
- Skip upload when minio_client is None — `document_id` still set
- Upload errors: caught and appended as `store_failed:{reason}`, pipeline continues

**Out of scope:**
- MinIO client construction
- Downstream chunking

#### Happy path scenarios

| Scenario | Input | Expected output |
|---|---|---|
| Upload enabled, client present | `store_documents=True`, valid minio_client mock | `state.document_id` is 24-char hex; upload called once |
| Upload disabled, client present | `store_documents=False`, minio_client mock | `document_id` still set; upload NOT called |
| Upload enabled, client is None | `store_documents=True`, `minio_client=None` | `document_id` still set; no error |
| Upload disabled, client is None | `store_documents=False`, `minio_client=None` | `document_id` still set; no error |
| Determinism | Same `source_key`, two independent calls | Identical `document_id` |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|---|---|---|
| Upload exception | minio_client.put raises `Exception("conn refused")` | `document_id` still set; `"store_failed:conn refused"` in `state.errors` |
| OSError upload | minio_client.put raises `OSError("disk full")` | `document_id` still set; error appended; no propagation |

#### Boundary conditions

- `source_key=""`: `document_id` is valid 24-char hex (SHA-256 of empty input)
- `source_key` with special chars: `document_id` always 24 chars
- `document_id` is always exactly 24 chars regardless of upload outcome

#### Integration points

- minio_client injected via state or runtime; mock with `MagicMock()`
- `state.errors` must be initialized as `[]` before calling node

#### Known test gaps

- Exact MinIO SDK method name (put_object vs upload) unknown without source; mock at client boundary
- Retry behavior on transient failure: not specified in guide

#### Agent isolation contract

> **Agent isolation contract:** Tests MUST NOT import or instantiate a real MinIO client. All storage I/O mocked. Tests construct state objects directly. SHA-256 determinism verified by asserting output matches `hashlib.sha256(source_key.encode()).hexdigest()[:24]`. No network or file I/O.

---

### `src/ingest/embedding/nodes/chunking.py` — Chunking

**Module purpose:** Normalizes heading format, chunks Markdown text via `chunk_markdown`, and produces `ProcessedChunk` objects with heading path, section path, and source name metadata.

**In scope:**
- Text selection: `refactored_text` preferred when non-empty, else `cleaned_text`
- `normalize_headings_to_markdown` called before chunking
- Semantic chunking path (`semantic_chunking=True`, embedder available)
- Standard chunking path (`semantic_chunking=False` or no embedder)
- `ProcessedChunk` construction with heading, section_path, source_name metadata (FR-601)
- Exception handling: error appended, empty chunks returned
- Deterministic output for same input (FR-603)

**Out of scope:**
- `chunk_markdown` internals (mocked)
- Embedding model construction
- Downstream enrichment

#### Happy path scenarios

| Scenario | Input | Expected output |
|---|---|---|
| Standard chunking | `refactored_text=""`, `cleaned_text="# H1\nText"`, mock returns 2 dicts | 2 `ProcessedChunk` items with heading, section_path, source_name metadata |
| Refactored text preferred | `refactored_text="# Refactored"`, `cleaned_text="# Old"` | `chunk_markdown` called with refactored text |
| Semantic chunking with embedder | `semantic_chunking=True`, embedder mock | `chunk_markdown` called with embedder kwarg |
| Semantic chunking, no embedder | `semantic_chunking=True`, `embedder=None` | Falls back to standard path |
| Zero chunks | `chunk_markdown` returns `[]` | `state.chunks == []`; no error |
| Determinism (FR-603) | Same input called twice | Identical chunk text order |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|---|---|---|
| `chunk_markdown` raises | `Exception("model timeout")` | `chunks=[]`; `"chunking_failed:model timeout"` in `state.errors` |
| `normalize_headings_to_markdown` raises | `ValueError` | `chunks=[]`; error appended |

#### Boundary conditions

- `refactored_text` is whitespace-only: may be treated as truthy — document observed behavior
- `chunk_markdown` returns dict missing `heading` key: assert graceful default (empty string)

#### Known test gaps

- FR-604 (atomic table chunking): cannot verify without real `chunk_markdown`; deferred to integration test

#### Agent isolation contract

> **Agent isolation contract:** Tests MUST patch `chunk_markdown` and `normalize_headings_to_markdown` at their import paths within the chunking module. Embedder is a `MagicMock`. No real NLP or network I/O runs.

---

### `src/ingest/embedding/nodes/chunk_enrichment.py` — Chunk Enrichment

**Module purpose:** Assigns stable deterministic chunk IDs, propagates all source provenance fields into chunk metadata, and maps provenance spans for refactored documents.

**In scope:**
- `build_chunk_id(source_key, ordinal, text)` → 24-char hex ID (FR-700, FR-701)
- All source fields set: `source`, `source_key`, `source_uri`, `connector` (FR-702)
- `retrieval_text_origin`: `"refactored"` when enabled, else `"original"`
- `enriched_content` set on every chunk
- Provenance fields set when `enable_document_refactoring=True` (FR-706)

**Out of scope:**
- `build_chunk_id` hash internals
- Vector store writes

#### Happy path scenarios

| Scenario | Input | Expected output |
|---|---|---|
| Single chunk, refactoring disabled | 1 chunk, `enable_document_refactoring=False` | `chunk_id` is 24-char hex; all source fields set; `retrieval_text_origin="original"` |
| Multiple chunks | 3 chunks, distinct texts | Each has unique `chunk_id`; all source fields identical across chunks |
| Refactoring enabled | `enable_document_refactoring=True`, provenance mock | Provenance fields set; `retrieval_text_origin="refactored"` |
| Determinism (FR-701) | Same source_key + ordinal + text, called twice | Identical `chunk_id` |
| Two chunks same text, different ordinal | ordinals 0 and 1 | Different `chunk_id` values |
| Two chunks same ordinal, different source_key | | Different `chunk_id` values |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|---|---|---|
| Empty chunks list | `state.chunks=[]` | No mutations; `state.chunks` remains `[]` |
| `map_chunk_provenance` raises | `enable_document_refactoring=True`, mock raises | Document behavior — mark as `xfail` pending source review |

#### Boundary conditions

- Chunk with empty text: `chunk_id` still set
- `source_uri=""`: `chunk.metadata["source_uri"]` set to empty string, not omitted
- `connector=None`: `chunk.metadata["connector"]` set to None

#### Known test gaps

- Error handling for `map_chunk_provenance` exceptions not specified in guide
- `enriched_content` composition (plain text vs heading + text) exact logic unknown without source

#### Agent isolation contract

> **Agent isolation contract:** Tests MUST patch `build_chunk_id` and `map_chunk_provenance` at their import paths. Chunk stubs are minimal objects with `text: str` and `metadata: dict`. No real hashing or I/O runs in most tests. One dedicated determinism test calls real `build_chunk_id` unpatched to verify format and stability.

---

### `src/ingest/embedding/nodes/metadata_generation.py` — Metadata Generation

**Module purpose:** Generates document-level summary and keywords via LLM with deterministic fallback, then projects both into every chunk's metadata.

**In scope:**
- LLM path: `_llm_json` called; result parsed for summary and keywords (FR-800)
- Fallback path: LLM returns `{}` → `_extract_keywords_fallback`; first sentence as summary (FR-801)
- Keyword capping at `max_keywords` (FR-803)
- `metadata_summary` and `metadata_keywords` written to state
- Projection into every chunk (FR-806)
- LLM disabled path (`enable_llm_metadata=False`): fallback used

**Out of scope:**
- LLM provider internals (mocked via `_llm_json`)

#### Happy path scenarios

| Scenario | Input | Expected output |
|---|---|---|
| LLM enabled, valid JSON | `_llm_json` returns `{"summary": "S", "keywords": ["a", "b"]}` | `state.metadata_summary="S"`, `metadata_keywords=["a","b"]`; all chunks have `doc_summary`, `doc_keywords` |
| LLM disabled | `enable_llm_metadata=False` | Fallback used; no LLM call; summary non-empty |
| Keyword capping (FR-803) | `max_keywords=3`, LLM returns 5 keywords | `state.metadata_keywords` has exactly 3 items |
| Fallback capping | `max_keywords=2`, fallback returns 10 terms | `state.metadata_keywords` has exactly 2 items |
| Projection into chunks (FR-806) | 3 chunks | Every chunk has `metadata["doc_summary"]` and `metadata["doc_keywords"]` |
| First-sentence summary | `cleaned_text="First. Second."`, LLM disabled | `state.metadata_summary == "First."` |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|---|---|---|
| LLM returns `{}` (fallback) | `_llm_json` returns `{}` | Fallback keywords and summary used; no crash |
| `cleaned_text` empty | `cleaned_text=""`, LLM disabled | No crash; `metadata_summary` is a string |

#### Boundary conditions

- `max_keywords=0`: `metadata_keywords == []`
- `max_keywords=1`: exactly one keyword retained
- LLM returns fewer keywords than `max_keywords`: all returned keywords kept

#### Known test gaps

- Whether `_llm_json` exceptions are caught: mark error scenario test as `xfail(strict=False)` pending source review
- LLM `summary=""` triggers fallback or accepted as-is: document as ambiguity with `xfail`

#### Agent isolation contract

> **Agent isolation contract:** Tests MUST patch `_llm_json` and optionally `_extract_keywords_fallback` at their import paths. No real LLM calls. Chunk stubs have `metadata: dict`. Config stub includes `enable_llm_metadata`, `max_keywords`, `llm_temperature`, `llm_timeout_seconds`.

---

### `src/ingest/embedding/nodes/quality_validation.py` — Quality Validation

**Module purpose:** Heuristic quality gating and exact-normalized deduplication that filters chunks by minimum character count, quality score threshold, and normalized exact-match.

**In scope:**
- Toggle bypass when `enable_quality_validation=False` (returns all chunks unchanged)
- Short-chunk rejection (`len(chunk.text.strip()) < min_chunk_chars`) (FR-1101)
- Quality score threshold rejection (FR-1100)
- Exact dedup after `text.lower().strip()` normalization (FR-1102)
- `chunk.metadata["quality_score"]` set on every surviving chunk (FR-1103)

**Out of scope:**
- `quality_score()` function internals (mocked)
- Downstream embedding

#### Happy path scenarios

| Scenario | Input | Expected output |
|---|---|---|
| Disabled | `enable_quality_validation=False`, any chunks | All chunks returned unchanged |
| All pass | 3 chunks, each long, high-quality, unique | All 3 returned; each has `quality_score` in metadata |
| Short chunk removed | 1 short chunk + 1 valid | Only valid returned |
| Low-quality chunk removed | quality_score=0.1 vs 0.5 | Only higher-scored returned |
| Duplicate removed (exact) | 2 identical normalized texts | 1 returned |
| Duplicate (case diff) | "Hello World" and "hello world" | 1 returned (first occurrence) |
| Duplicate (whitespace diff) | "foo bar" and "  foo bar  " | 1 returned |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|---|---|---|
| Empty chunks | `chunks=[]`, validation enabled | Returns `[]`; no error |

#### Boundary conditions

- Chunk with `len(text.strip()) == min_chunk_chars` exactly: RETAINED (`<` not `<=`)
- Chunk with `quality_score == min_quality_score` exactly: RETAINED
- All-whitespace text: stripped length = 0; rejected by short-chunk filter

#### Known test gaps

- Log message format for `quality_validation:skipped` — match loosely

#### Agent isolation contract

> **Agent isolation contract:** Mock `quality_score` at the module's import path. Chunk stubs are `SimpleNamespace` or dataclass instances with `.text` and `.metadata` attributes. No filesystem, network, or database access.

---

### `src/ingest/embedding/nodes/cross_reference_extraction.py` — Cross Reference Extraction

**Module purpose:** Pattern-based extraction of DOC-NNN, Section N.N, and RFC NNNNN reference strings from document text, returning a deduplicated list.

**In scope:**
- Toggle bypass when `enable_cross_reference_extraction=False` (FR-901)
- `DOC-\d{3,6}` pattern matching
- `[Ss]ection\s+\d+(\.\d+)*` pattern matching
- `RFC\s*\d{3,5}` pattern matching
- Text source: `refactored_text` preferred, falls back to `cleaned_text`
- Deduplication of matches (FR-900)

**Out of scope:**
- Semantic interpretation of references

#### Happy path scenarios

| Scenario | Input | Expected output |
|---|---|---|
| Disabled | `enable_cross_reference_extraction=False` | `cross_references=[]`; no regex processing |
| DOC reference | `"See DOC-1234"` | `["DOC-1234"]` |
| DOC min digits (3) | `"DOC-123"` | `["DOC-123"]` |
| Section simple | `"Section 3"` | `["Section 3"]` |
| Section multi-level | `"Section 3.1.2"` | `["Section 3.1.2"]` |
| Section lowercase | `"section 4.2"` | `["section 4.2"]` |
| RFC with space | `"RFC 2119"` | `["RFC 2119"]` |
| RFC without space | `"RFC2119"` | `["RFC2119"]` |
| Multiple types | `"DOC-100 and Section 2.3 and RFC 4567"` | All three in list |
| Deduplication | `"DOC-100 ... DOC-100"` | `["DOC-100"]` |
| Falls back to cleaned_text | `refactored_text=""`, `cleaned_text="DOC-999"` | `["DOC-999"]` |
| Prefers refactored_text | `refactored_text="DOC-111"`, `cleaned_text="DOC-999"` | `["DOC-111"]` |
| No matches | `"plain text"` | `[]` |

#### Boundary conditions

- DOC with 2 digits (`DOC-12`): must NOT match
- DOC with 7 digits (`DOC-1234567`): must NOT match
- RFC with 2 digits (`RFC 12`): must NOT match
- RFC with 6 digits (`RFC 123456`): must NOT match
- `Section` with no digits: must NOT match
- Both texts empty: `cross_references=[]`; no exception

#### Known test gaps

- Order of returned references not specified — assert membership, not order

#### Agent isolation contract

> **Agent isolation contract:** Tests for `cross_reference_extraction.py` are pure string-in / list-out. No mocking of external dependencies required. No filesystem, network, or database access.

---

### `src/ingest/embedding/nodes/knowledge_graph_extraction.py` — KG Extraction

**Module purpose:** Entity and relation extraction via `EntityExtractor` producing subject-predicate-object-confidence triples, with full error isolation.

**In scope:**
- Toggle bypass when `enable_knowledge_graph_extraction=False` (FR-1000)
- `EntityExtractor` instantiation and per-chunk invocation
- Error isolation: any exception caught → error appended, partial results returned (FR-1001)
- `kg_triples` written to state

**Out of scope:**
- `EntityExtractor` internals (mocked)
- KG storage

#### Happy path scenarios

| Scenario | Input | Expected output |
|---|---|---|
| Disabled | `enable_knowledge_graph_extraction=False` | `kg_triples=[]`; no EntityExtractor instantiation |
| Single chunk, single triple | mock returns `[("A", "rel", "B", 0.9)]` | `kg_triples=[("A", "rel", "B", 0.9)]` |
| Multiple chunks, multiple triples | mock returns triple per chunk | `kg_triples` contains all |
| Empty chunks | `chunks=[]` | `kg_triples=[]`; no errors |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|---|---|---|
| Extractor raises on one chunk | Raises `RuntimeError("bad chunk")` for chunk 2 of 3 | Error appended; chunks 1, 3 still processed; no propagation (FR-1001) |
| Extractor raises on instantiation | `__init__` raises | Error appended; `kg_triples=[]`; no propagation |

#### Known test gaps

- Partial result guarantee ("partial triples or empty list") is ambiguous in guide — test both outcomes with `xfail`
- Whether `EntityExtractor` is instantiated once or per-chunk: affects mock setup; document observed behavior

#### Agent isolation contract

> **Agent isolation contract:** Mock `EntityExtractor` at the node's import path. State supplies `chunks` and `errors`. No filesystem, network, or database access.

---

### `src/ingest/embedding/nodes/embedding_storage.py` — Embedding Storage

**Module purpose:** Embeds each surviving chunk via `embedder.embed` and persists vectors to Weaviate, with delete-before-insert in update mode and full error isolation.

**In scope:**
- Empty chunks short-circuit: `stored_count=0`, no Weaviate/embed calls (FR-1200)
- `update_mode=True`: delete_many before any inserts (FR-1205)
- Per-chunk embed + Weaviate insert
- Error isolation: caught, appended as `embed_failed:{reason}` (FR-1207)
- `stored_count` = number of successfully stored chunks

**Out of scope:**
- Weaviate client construction
- Embedder model loading

#### Happy path scenarios

| Scenario | Input | Expected output |
|---|---|---|
| Empty chunks | `chunks=[]` | `stored_count=0`; no calls to embedder or Weaviate |
| Single chunk, non-update | 1 chunk, `update_mode=False` | embed called once; insert called once; `stored_count=1`; delete NOT called |
| Multiple chunks | 3 chunks, non-update | embed 3x; insert 3x; `stored_count=3` |
| Update mode, single chunk | `update_mode=True`, `source_key="doc-abc"` | delete_many called with `source_key="doc-abc"` BEFORE first insert; `stored_count=1` |
| Update mode delete once | `update_mode=True`, 3 chunks | delete called exactly once; inserts 3x |
| Correct collection used | `target_collection="MyDocs"` | `weaviate_client.collections.get("MyDocs")` called |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|---|---|---|
| embed raises for one chunk | Raises for chunk 2 of 3 | Error appended; chunks 1 and 3 still attempted; no propagation (FR-1207) |
| Weaviate insert raises | Raises for chunk 2 | Error appended; other chunks unaffected |
| All chunks fail | Raises for every chunk | `stored_count=0`; all errors appended |

#### Boundary conditions

- `chunks=[]` with `update_mode=True`: document whether delete is skipped or called
- `chunk.metadata["enriched_content"]` missing: `KeyError` caught as error
- `stored_count` equals successfully stored count (embed AND insert both succeeded)

#### Integration points

- Assert delete called BEFORE first insert using `mock_weaviate.mock_calls` ordering
- Weaviate mock chain: `client.collections.get(name).data.delete_many(...)` and `.data.insert(...)`

#### Known test gaps

- Whether empty chunks with update_mode still triggers delete: ambiguous in guide; document observed behavior

#### Agent isolation contract

> **Agent isolation contract:** Mock `embedder` and `weaviate_client` as `MagicMock`. Configure Weaviate mock chain explicitly. Assert call ordering for delete-before-insert. No filesystem, network, or database access.

---

### `src/ingest/embedding/nodes/knowledge_graph_storage.py` — KG Storage

**Module purpose:** Feeds surviving chunks and KG triples to `kg_builder.add_chunk`, skipping entirely when storage is disabled or no builder is injected.

**In scope:**
- Skip when `enable_knowledge_graph_storage=False` (FR-1300)
- Skip when `kg_builder is None` (FR-1300)
- Log `kg_storage:skipped` in both skip cases
- Per-chunk `kg_builder.add_chunk(chunk, source_key, kg_triples)` call
- Error isolation: exceptions caught, appended as `kg_storage_failed:{reason}` (FR-1301)

**Out of scope:**
- `kg_builder` implementation
- KG triple extraction

#### Happy path scenarios

| Scenario | Input | Expected output |
|---|---|---|
| Storage disabled | `enable_knowledge_graph_storage=False` | `add_chunk` never called; log contains `kg_storage:skipped` |
| `kg_builder=None`, storage enabled | `kg_builder=None` | `add_chunk` never called; skipped log |
| Single chunk, enabled | 1 chunk, builder mock | `add_chunk(chunk, source_key, kg_triples)` called once |
| Multiple chunks | 3 chunks | `add_chunk` called 3 times with same source_key/kg_triples |
| Empty chunks | `chunks=[]`, builder present | `add_chunk` never called; no errors |
| Empty kg_triples | `kg_triples=[]`, 1 chunk | `add_chunk(chunk, source_key, [])` called |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|---|---|---|
| `add_chunk` raises for chunk 2 of 3 | Raises `RuntimeError("write failed")` | Error appended; chunks 1, 3 still attempted; no propagation (FR-1301) |

#### Boundary conditions

- `state.errors` already has prior entries: new error appended, prior preserved
- `kg_builder=False` (non-None falsy): document whether treated as None or truthy

#### Known test gaps

- Log message format `kg_storage:skipped` — match as substring
- Whether `kg_builder is None` vs truthiness check: note for implementation reader

#### Agent isolation contract

> **Agent isolation contract:** Mock `kg_builder` as `MagicMock` or set to `None`. State is plain dict or `SimpleNamespace`. Log assertions via `caplog` (substring match). No filesystem, network, or database access.

---

### `src/ingest/common/shared.py` — Shared Helpers

**Module purpose:** Cross-cutting utilities providing keyword extraction, cross-reference detection, quality scoring, processing log management, and chunk provenance mapping.

**In scope:**
- `_extract_keywords_fallback(text, max_keywords)` — frequency-ranked keyword extraction
- `cross_refs(text)` — regex pattern detection (DOC-NNN, Section N.N.N, RFC NNNN)
- `quality_score(text)` — 0.0–1.0 composite score
- `map_chunk_provenance(chunk_text, original_text, refactored_text, original_cursor, refactored_cursor)` — span matching with provenance metadata
- `append_processing_log(state, node_name, status, verbose)` — log entry appender

**Out of scope:**
- LLM calls
- Vector storage

#### Happy path scenarios

| Scenario | Input | Expected output |
|---|---|---|
| `cross_refs` DOC pattern | `"See DOC-123"` | `["DOC-123"]` |
| `cross_refs` Section pattern | `"Section 3.2.1"` | `["Section 3.2.1"]` |
| `cross_refs` RFC pattern | `"RFC 2119"` | `["RFC 2119"]` |
| `cross_refs` dedup | `"DOC-42 and DOC-42"` | `["DOC-42"]` |
| `quality_score` well-formed text | >= 20 chars, mixed content | float in (0.0, 1.0] |
| `quality_score` empty | `""` | `0.0` |
| `quality_score` short | `"Hi"` | `0.0` |
| `_extract_keywords_fallback` ranked | text with known high-frequency terms | top term is highest-frequency content word |
| `_extract_keywords_fallback` empty | `""` | `[]` |
| `map_chunk_provenance` exact match | chunk_text is literal substring | `confidence >= 0.8`, `method="exact"`, correct indices |
| `map_chunk_provenance` no match | chunk_text not in sources | `confidence == 0.0` |
| `append_processing_log` appends | state with log, `node_name="embed", status="ok"` | `state["processing_log"]` ends with `"embed:ok"` |

#### Boundary conditions

- `quality_score` with exactly 20 chars: document whether 0.0 or nonzero (inclusive/exclusive threshold)
- `_extract_keywords_fallback` with `max_keywords=0`: returns `[]`
- `_extract_keywords_fallback` with `max_keywords > unique_words`: returns all available
- `map_chunk_provenance` cursor chain: two-call sequence; new cursors from call N are valid input for call N+1
- `cross_refs` on `Section N` (single level, no dot): document match/no-match behavior

#### Known test gaps

- Fuzzy match confidence exact value: implementation-defined; assert `0.0 < confidence < 0.8`
- Stop-word list: assert presence of clearly content-bearing terms, not exact list equality
- `append_processing_log` verbose DEBUG path: logger name unknown without source; mark as gap

#### Agent isolation contract

> **Agent isolation contract:** Tests are pure unit tests. No LiteLLM calls, no file I/O. Functions called directly with plain Python arguments. State dicts constructed as `{"processing_log": []}`. Fuzzy confidence assertions use range checks.

---

### `src/ingest/support/llm.py` — LLM Helper

**Module purpose:** Provides a single JSON-only LLM chat call via LiteLLM that safely returns an empty dict when LLM support is disabled or any call-time exception occurs.

**In scope:**
- `_llm_json(prompt, config)` — fast-path disable check, LiteLLM call, fence strip, JSON parse, catch-all

**Out of scope:**
- Prompt construction (caller's responsibility)
- Auth/credential management

#### Happy path scenarios

| Scenario | Input | Expected output |
|---|---|---|
| LLM disabled | `config.enable_llm_metadata=False` | Returns `{}`; `litellm.completion` never called |
| LLM enabled, valid JSON | mock returns `'{"key": "val"}'` | Returns `{"key": "val"}` |
| JSON in markdown fences | response is ` ```json\n{"a": 1}\n``` ` | Returns `{"a": 1}` |
| JSON in plain fences | response is ` ```\n{"b": 2}\n``` ` | Returns `{"b": 2}` |
| Correct model/temperature used | `llm_model="gpt-4o"`, `llm_temperature=0.0` | `litellm.completion` called with matching kwargs |
| Correct timeout used | `llm_timeout_seconds=30` | `litellm.completion` called with `timeout=30` |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|---|---|---|
| Timeout | `TimeoutError` raised | Returns `{}`; no propagation |
| Provider error | generic `Exception` raised | Returns `{}`; no propagation |
| JSON parse failure | mock returns `"not valid json"` | Returns `{}`; no propagation |
| Empty string response | mock returns `""` | Returns `{}`; no propagation |
| Fences with no body | ` ```json\n\n``` ` | Returns `{}`; no propagation |

#### Boundary conditions

- `enable_llm_metadata=False`: `litellm.completion` call count == 0
- Nested JSON: `{"outer": {"inner": 1}}` returned as nested dict

#### Known test gaps

- Exact messages structure passed to `litellm.completion`: assert prompt appears in call arguments, not exact format

#### Agent isolation contract

> **Agent isolation contract:** `litellm.completion` must always be patched — never make real LLM calls. Config as `SimpleNamespace` with only the four enumerated fields. Patch target: `src.ingest.support.llm.litellm.completion`.

---

### `src/ingest/cli.py` — CLI Entry Point

**Module purpose:** argparse CLI for the ingest pipeline that maps command-line flags to `IngestionConfig` fields.

**In scope:**
- `_build_parser()` argument definitions and defaults
- All flag parsing beyond the existing 3 verbose_stages tests
- Type enforcement (float, int)

**Out of scope (already tested):**
- `test_verbose_stages_defaults_to_none`
- `test_verbose_stages_true_when_enabled`
- `test_verbose_stages_false_when_explicitly_disabled`

#### Happy path scenarios

| Scenario | Input argv | Expected `args` attribute |
|---|---|---|
| `--update` sets True | `["--dir", "/tmp", "--update"]` | `args.update_mode == True` |
| `--update` absent → False | `["--dir", "/tmp"]` | `args.update_mode == False` |
| `--file` sets selected_file | `["--dir", "/tmp", "--file", "doc.pdf"]` | `args.selected_file == "doc.pdf"` |
| `--file` absent → None | `["--dir", "/tmp"]` | `args.selected_file is None` |
| `--dir` sets source_dir | `["--dir", "/data/docs"]` | `args.source_dir == "/data/docs"` |
| `--no-kg` sets build_kg False | `["--dir", "/tmp", "--no-kg"]` | `args.build_kg == False` |
| `--no-semantic` sets False | `["--dir", "/tmp", "--no-semantic"]` | `args.semantic_chunking == False` |
| `--export-processed` True | `["--dir", "/tmp", "--export-processed"]` | `args.export_processed == True` |
| `--export-processed` absent → False | `["--dir", "/tmp"]` | `args.export_processed == False` |
| `--enable-docling` True | `["--dir", "/tmp", "--enable-docling"]` | `args.enable_docling_parser == True` |
| `--docling-model` value | `["--dir", "/tmp", "--docling-model", "fast"]` | `args.docling_model == "fast"` |
| `--enable-vision` True | `["--dir", "/tmp", "--enable-vision"]` | `args.enable_vision_processing == True` |
| `--vision-model` value | `["--dir", "/tmp", "--vision-model", "gpt-4o"]` | `args.vision_model == "gpt-4o"` |
| `--enable-multimodal` True | `["--dir", "/tmp", "--enable-multimodal"]` | `args.enable_multimodal_processing == True` |
| `--min-quality 0.75` float | `["--dir", "/tmp", "--min-quality", "0.75"]` | `args.min_quality_score == 0.75`; `isinstance(..., float)` |
| `--chunk-size 512` int | `["--dir", "/tmp", "--chunk-size", "512"]` | `args.chunk_size == 512`; `isinstance(..., int)` |
| `--chunk-overlap 64` int | `["--dir", "/tmp", "--chunk-overlap", "64"]` | `args.chunk_overlap == 64`; `isinstance(..., int)` |
| Combined flags | all flags together | all attributes set correctly |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|---|---|---|
| `--min-quality` non-float | `["--dir", "/tmp", "--min-quality", "high"]` | `SystemExit` raised |
| `--chunk-size` non-int | `["--dir", "/tmp", "--chunk-size", "big"]` | `SystemExit` raised |
| `--dir` absent | `[]` | `SystemExit` raised |

#### Boundary conditions

- `--min-quality 0.0`: accepted as valid float (not falsy/absent)
- `--chunk-overlap 0`: accepted as valid int

#### Known test gaps

- Default for `--docling-model` absent: assert `is None` — verify against implementation
- Whether `--dir` is `required=True` in argparse or enforced downstream: mark `SystemExit` test as verify-required

#### Agent isolation contract

> **Agent isolation contract:** Tests call `_build_parser().parse_args(argv)` ONLY. Do not call `main()` or `ingest()`. Do not import `IngestionConfig`. No filesystem access. Use `pytest.raises(SystemExit)` for error scenarios. Do NOT duplicate the three existing verbose_stages tests.

---

## Integration Test Specifications

### Integration: Happy Path End-to-End Ingest

**Scenario:** `ingest_file` successfully completes both phases, merges logs and errors, writes the cleaned document to CleanDocumentStore, and returns a correct `IngestFileResult`.

**Entry point:** `ingest_file(source_path, runtime, source_key, ...)`

**Flow:**
1. Construct `Runtime` with real `CleanDocumentStore` backed by `tmp_path`, `MagicMock` embedder, `MagicMock` weaviate client
2. Patch `src.ingest.impl.run_document_processing` to return no-error `DocumentProcessingState` with `processing_log=["phase1:cleaned"]`
3. Patch `src.ingest.impl.run_embedding_pipeline` to return `stored_count=5`, no errors, `processing_log=["phase2:embedded"]`
4. Call `ingest_file(source_path=tmp_file, runtime=runtime, source_key="doc-001")`

**What to assert:**
- `result.stored_count == 5`
- `result.errors == []`
- `result.processing_log == ["phase1:cleaned", "phase2:embedded"]`
- `result.source_hash` is non-empty string
- `CleanDocumentStore` has entry for `source_key="doc-001"` containing cleaned text
- `run_document_processing` called exactly once
- `run_embedding_pipeline` called exactly once

**Mocks required:** `run_document_processing`, `run_embedding_pipeline`, `MagicMock` embedder, `MagicMock` weaviate client

**Test function name:** `test_ingest_file_happy_path_merges_logs_and_writes_store`

---

### Integration: Update Mode Re-Ingestion

**Scenario:** `ingest_directory` with `update_mode=True` detects a changed-hash file, calls delete-before-insert for old vectors, and updates the manifest with the new hash.

**Entry point:** `ingest_directory(directory, runtime, update_mode=True, ...)`

**Flow:**
1. Create one source file in `tmp_path / "docs"`
2. Seed manifest with a stale hash for `source_key="doc_a"` (different from file's real hash)
3. Patch Phase 1 to return valid state; patch Phase 2 to return `stored_count=3`
4. Call `ingest_directory(..., update_mode=True)`

**What to assert:**
- Weaviate delete called scoped to `source_key="doc_a"` before any new insert
- Manifest after run has updated hash for `source_key="doc_a"` (new hash, not stale)
- `summary.processed == 1`, `summary.skipped == 0`

**Mocks required:** `run_document_processing`, `run_embedding_pipeline`, `MagicMock` weaviate client, `MagicMock` embedder

**Test function name:** `test_ingest_directory_update_mode_deletes_before_insert_and_updates_manifest`

---

### Integration: Partial Failure Isolation

**Scenario:** When one file raises during `ingest_file`, `ingest_directory` isolates the failure, continues processing remaining files, and reports correct counts in the summary.

**Entry point:** `ingest_directory(directory, runtime, ...)`

**Flow:**
1. Create 3 source files: `file_a.txt`, `file_b.txt`, `file_c.txt`
2. Patch `run_document_processing` with `side_effect`: success for file A, `RuntimeError` for file B, success for file C
3. Patch `run_embedding_pipeline` to return valid state with `stored_count=2`
4. Call `ingest_directory(...)`

**What to assert:**
- `summary.processed == 2` (A and C)
- `summary.failed == 1` (B)
- `summary.skipped == 0`
- `run_document_processing` called exactly 3 times (all files attempted)
- `run_embedding_pipeline` called exactly 2 times (not called for B since Phase 1 raised)
- Manifest saved with entries for A and C, not B

**Mocks required:** `run_document_processing` with `side_effect`, `run_embedding_pipeline`, `MagicMock` embedder, `MagicMock` weaviate client

**Test function name:** `test_ingest_directory_partial_failure_continues_and_reports_correct_summary`

---

## FR-to-Test Traceability Matrix

| FR | Acceptance Criteria Summary | Test Module | Test Function (or status) |
|----|----------------------------|-----------|-----------------------------|
| FR-591 | Clean Document Store: document_id always computed | `tests/ingest/embedding/test_document_storage.py` | `test_document_id_set_regardless_of_config` |
| FR-595 | CleanDocumentStore atomic write/read roundtrip | `tests/ingest/test_clean_store.py` | `test_write_and_read`, `test_write_is_atomic` |
| FR-601 | Chunking projects heading metadata to chunks | `tests/ingest/test_pipeline_schema.py` | `test_chunking_node_projects_heading_metadata` |
| FR-603 | Chunking determinism: same input → same output | `tests/ingest/embedding/test_chunking.py` | `test_chunking_deterministic_output` |
| FR-604 | Atomic table chunking | Not covered — known gap: requires integration test with real chunk_markdown |
| FR-605 | Chunk ID changes when content changes | `tests/ingest/test_idempotency_incremental.py` | `test_chunk_id_changes_with_content` |
| FR-606 | Chunk ID changes when source_key changes | `tests/ingest/test_idempotency_incremental.py` | `test_chunk_id_changes_with_source_key` |
| FR-700 | Every chunk receives chunk_id | `tests/ingest/test_pipeline_schema.py` | `test_chunk_enrichment_sets_source_fields_and_chunk_id` |
| FR-701 | chunk_id is deterministic | `tests/ingest/embedding/test_chunk_enrichment.py` | `test_chunk_id_determinism` |
| FR-702 | Source fields (source, source_key, source_uri, connector) on every chunk | `tests/ingest/test_pipeline_schema.py` | `test_chunk_enrichment_sets_source_fields_and_chunk_id` |
| FR-706 | Provenance fields set when refactoring enabled | `tests/ingest/embedding/test_chunk_enrichment.py` | `test_provenance_fields_when_refactoring_enabled` |
| FR-800 | Metadata summary always generated (LLM or fallback) | `tests/ingest/embedding/test_metadata_generation.py` | `test_summary_always_generated` |
| FR-801 | Keyword fallback when LLM unavailable | `tests/ingest/test_pipeline_schema.py` | `test_extract_keywords_fallback_returns_ranked_terms` |
| FR-803 | Keywords capped at max_keywords | `tests/ingest/embedding/test_metadata_generation.py` | `test_keywords_capped_at_max` |
| FR-806 | Summary and keywords projected into every chunk's metadata | `tests/ingest/embedding/test_metadata_generation.py` | `test_metadata_projected_into_chunks` |
| FR-900 | Cross-references extracted as deduplicated list | `tests/ingest/embedding/test_cross_reference.py` | `test_cross_refs_deduplicated` |
| FR-901 | Cross-reference extraction skippable via config | `tests/ingest/embedding/test_cross_reference.py` | `test_cross_reference_skippable` |
| FR-1000 | KG extraction skippable via config | `tests/ingest/embedding/test_kg_extraction.py` | `test_kg_extraction_skippable` |
| FR-1001 | KG extraction errors do not halt pipeline | `tests/ingest/embedding/test_kg_extraction.py` | `test_kg_extraction_errors_not_halt` |
| FR-1100 | Low-quality chunks removed | `tests/ingest/embedding/test_quality_validation.py` | `test_low_quality_chunks_removed` |
| FR-1101 | Short chunks filtered | `tests/ingest/embedding/test_quality_validation.py` | `test_short_chunks_filtered` |
| FR-1102 | Duplicate chunks deduplicated | `tests/ingest/embedding/test_quality_validation.py` | `test_duplicates_deduplicated` |
| FR-1103 | quality_score on each surviving chunk | `tests/ingest/embedding/test_quality_validation.py` | `test_quality_score_on_chunk_metadata` |
| FR-1200 | All chunks embedded and stored | `tests/ingest/embedding/test_embedding_storage.py` | `test_all_chunks_stored` |
| FR-1205 | Delete-before-insert in update mode | `tests/ingest/embedding/test_embedding_storage.py` | `test_delete_before_insert_update_mode` |
| FR-1207 | Embedding storage errors do not halt pipeline | `tests/ingest/embedding/test_embedding_storage.py` | `test_embedding_storage_errors_not_halt` |
| FR-1300 | KG storage skippable (disabled or no builder) | `tests/ingest/embedding/test_kg_storage.py` | `test_kg_storage_skippable` |
| FR-1301 | KG storage errors do not halt pipeline | `tests/ingest/embedding/test_kg_storage.py` | `test_kg_storage_errors_not_halt` |
| FR-1400 | Re-ingestion atomic replace | `tests/ingest/test_orchestrator.py` | `test_ingest_directory_update_mode_deletes_before_insert_and_updates_manifest` |
| FR-1401 | source_hash change detection → re-ingestion | `tests/ingest/test_orchestrator.py` | `test_ingest_directory_skips_unchanged_file` |
| FR-1402 | clean_hash change detection → re-embedding | Not covered — known gap: clean_hash not exposed in IngestFileResult API |
| FR-1410 | Removed sources deleted from vector store in update_mode | `tests/ingest/test_orchestrator.py` | `test_ingest_directory_removes_deleted_source_in_update_mode` |
| FR-1800 | Config validation before processing | `tests/ingest/test_pipeline_schema.py` | `test_verify_core_design_detects_invalid_kg_configuration` |
| FR-1801 | Actionable config validation error messages | `tests/ingest/test_orchestrator.py` | `test_validation_error_messages_actionable` |
