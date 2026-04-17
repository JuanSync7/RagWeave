> **Document type:** Design document (Layer 4)
> **Upstream:** DATA_LIFECYCLE_SPEC.md
> **Downstream:** DATA_LIFECYCLE_IMPLEMENTATION.md
> **Last updated:** 2026-04-15

# Data Lifecycle — Design (v1.0.0)

| Field | Value |
|-------|-------|
| **Document** | Data Lifecycle Design Document |
| **Version** | 1.0.0 |
| **Status** | Draft |
| **Spec Reference** | `DATA_LIFECYCLE_SPEC.md` v1.0.0 (FR-3000–FR-3114, NFR-3180–NFR-3230) |
| **Companion Documents** | `DATA_LIFECYCLE_SPEC.md`, `DATA_LIFECYCLE_SPEC_SUMMARY.md`, `DOCUMENT_PROCESSING_DESIGN.md`, `EMBEDDING_PIPELINE_DESIGN.md`, `INGESTION_PIPELINE_ENGINEERING_GUIDE.md` |
| **Created** | 2026-04-15 |
| **Last Updated** | 2026-04-15 |

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-04-15 | Initial design. Six tasks covering MinIO clean store migration, manifest schema extension, trace ID infrastructure, GC/sync engine, schema migration runner, and E2E validation node. |

> **Document Intent.** This design translates the requirements defined in `DATA_LIFECYCLE_SPEC.md`
> (FR-3000–FR-3114) into a phased, task-oriented implementation plan. Each task maps to one or more
> specification requirements and includes file-level changes, interface contracts, dependencies,
> and acceptance criteria.
>
> The Data Lifecycle subsystem is cross-cutting: it touches both the Document Processing Pipeline
> and the Embedding Pipeline, and governs how data flows, persists, ages, and evolves across all
> four storage backends (Weaviate, MinIO, Neo4j, and the ingestion manifest).

---

# Part A: Current State Analysis

## What Exists Today

### CleanDocumentStore (local filesystem boundary)

**File:** `src/ingest/common/clean_store.py`

The current `CleanDocumentStore` class writes Phase 1 output to the local filesystem as three
files per document: `{source_key}.md`, `{source_key}.meta.json`, and optionally
`{source_key}.docling.json`. Phase 2 is invoked by the orchestrator (`src/ingest/impl.py`)
which passes `clean_text` and `docling_document` in-memory — the CleanDocumentStore is already
used only as a debug export, not as the inter-phase handoff. However, the class still exists,
the `.docling.json` path is still present, and no MinIO-based durable clean store exists.

### Manifest (JSON ledger)

**File:** `src/ingest/common/utils.py` (load/save), `src/ingest/common/schemas.py` (ManifestEntry)

The manifest is a flat JSON file keyed by `source_key`. Entries contain source identity fields,
`content_hash`, `chunk_count`, `summary`, `keywords`, `processing_log`, and `mirror_stem`.
Missing from the current schema: `schema_version`, `trace_id`, `batch_id`, `deleted`,
`deleted_at`, `validation`, `clean_hash`.

### GC / Orphan Handling

**File:** `src/ingest/impl.py` (`ingest_directory`)

The current `ingest_directory` function performs a limited sync during `update=True` runs:
it diffs discovered source keys against the manifest and calls `delete_by_source_key` on
Weaviate for removed sources, plus deletes the local CleanDocumentStore entry. It does NOT
clean MinIO blobs or Neo4j triples — these become orphaned.

### Trace ID / Validation

No trace ID exists. Documents flow through both phases correlated only by `source_key` in
log messages. No end-to-end validation occurs after Phase 2.

### Schema Versioning

No `schema_version` field exists on manifest entries or Weaviate chunk metadata. There is no
migration mechanism — the only option for schema changes is full re-ingestion.

## What Changes

| Area | Current | Target |
|------|---------|--------|
| Inter-phase boundary | In-memory (already) + local FS debug export | In-memory + MinIO durable store; local FS debug-only |
| CleanDocumentStore | Full class with .docling.json support | Removed or reduced to debug-only facade; no .docling.json |
| GC scope | Weaviate + manifest only | All four stores (Weaviate, MinIO, Neo4j, manifest) |
| GC trigger | Implicit during update runs | Manual CLI, scheduled, on-ingest diff |
| Delete mode | Hard delete only | Soft delete (default) with configurable retention + hard delete override |
| Trace ID | None | UUID v4 per workflow, propagated to all stores and logs |
| Validation | None | Per-document E2E consistency check across all enabled stores |
| Schema version | None | Version stamp on manifest + Weaviate + MinIO; migration job |
| Manifest fields | 12 fields | 19 fields (+schema_version, trace_id, batch_id, deleted, deleted_at, validation, clean_hash) |

---

# Part B: Task Decomposition

## Task 1: MinIO Clean Store Migration (Gap 4)

**Spec requirements:** FR-3030, FR-3031, FR-3032, FR-3033, FR-3034

**Dependencies:** None (foundational; other tasks depend on this)

**Complexity:** Medium

### Description

Replace the local filesystem `CleanDocumentStore` with MinIO as the single durable store for
Phase 1 output. The in-memory handoff between phases is already in place in `ingest_file()` —
this task adds the MinIO persistence path and removes the `.docling.json` storage path entirely.

### Files to Create

| File | Purpose |
|------|---------|
| `src/ingest/common/minio_clean_store.py` | MinIO-backed clean store: `write()`, `read()`, `exists()`, `delete()`, `list_keys()` |

### Files to Modify

| File | Change |
|------|--------|
| `src/ingest/common/clean_store.py` | Deprecate class. Remove `write_docling()`, `read_docling()`, `_docling_path()`. Retain as debug-only facade or delete entirely with alias in `__init__.py`. |
| `src/ingest/impl.py` | Replace `_debug_store = CleanDocumentStore(...)` with `MinioCleanStore` write in the main path (not debug-only). Remove `docling_document` param from write calls. Add MinIO clean store write after Phase 1 success. |
| `src/ingest/common/__init__.py` | Export `MinioCleanStore`. Remove or alias `CleanDocumentStore`. |
| `src/ingest/common/types.py` | Add `clean_store_bucket: str` field to `IngestionConfig` (default: reuse `target_bucket`). Remove `persist_docling_document` flag. |

### Interface Contract

```python
# src/ingest/common/minio_clean_store.py

class MinioCleanStore:
    """Durable clean document store backed by MinIO.

    Objects are stored under the `clean/` prefix:
      - clean/{safe_key}.md          — UTF-8 clean markdown
      - clean/{safe_key}.meta.json   — JSON metadata envelope
    """

    def __init__(self, client: Any, bucket: str) -> None: ...

    def write(
        self,
        source_key: str,
        text: str,
        meta: dict[str, Any],
    ) -> None:
        """Write clean markdown and metadata to MinIO.

        Objects are written with deterministic keys under clean/ prefix.
        The .meta.json is written last as the commit marker (FR-3033 AC4).
        Content types: text/markdown and application/json.
        """
        ...

    def read(self, source_key: str) -> tuple[str, dict[str, Any]]:
        """Read clean markdown and metadata from MinIO."""
        ...

    def exists(self, source_key: str) -> bool:
        """Check if a clean document exists in MinIO for this source_key."""
        ...

    def delete(self, source_key: str) -> None:
        """Remove both clean markdown and metadata objects."""
        ...

    def list_keys(self) -> list[str]:
        """List all source_keys with clean documents in MinIO."""
        ...

    @staticmethod
    def _object_key_md(source_key: str) -> str:
        """Return MinIO object key for the markdown file."""
        return f"clean/{_safe_key(source_key)}.md"

    @staticmethod
    def _object_key_meta(source_key: str) -> str:
        """Return MinIO object key for the metadata envelope."""
        return f"clean/{_safe_key(source_key)}.meta.json"
```

### Acceptance Criteria (from spec)

- FR-3030: Phase 1 returns clean_text and metadata in-memory; no local FS read/write for inter-phase handoff. **Already true** — validate and document.
- FR-3031: Clean markdown written to MinIO under `clean/{source_key}.md`; metadata under `clean/{source_key}.meta.json`. Atomic write order (meta last).
- FR-3032: No `.docling.json` written anywhere. `write_docling()`/`read_docling()` removed.
- FR-3033: Meta envelope includes all required fields (source_key, source_name, source_uri, source_id, connector, source_version, source_hash, clean_hash, schema_version, trace_id, created_at). Content types set correctly.
- FR-3034: Debug export retained via `export_processed` flag, writes to local FS **in addition to** MinIO. No `.docling.json` in debug export.

### Testing Strategy

- Unit tests: `MinioCleanStore` write/read/delete/list with mocked MinIO client.
- Integration test: Round-trip write then read; verify content types and object keys.
- Regression test: Confirm `CleanDocumentStore` debug export still works when `export_processed=True`.

---

## Task 2: Manifest Schema Extension (Gap 11 + Gap 7 + Gap 2)

**Spec requirements:** FR-3100, FR-3114, FR-3020, FR-3053, FR-3061

**Dependencies:** None (schema-only change; code that writes new fields depends on Tasks 3, 4, 5)

**Complexity:** Low

### Description

Extend the `ManifestEntry` TypedDict with seven new optional fields required by the Data
Lifecycle spec. All fields are `total=False` (optional) per FR-3114 to maintain backward
compatibility with existing manifests.

### Files to Modify

| File | Change |
|------|--------|
| `src/ingest/common/schemas.py` | Add 7 new fields to `ManifestEntry`: `schema_version`, `trace_id`, `batch_id`, `deleted`, `deleted_at`, `validation`, `clean_hash`. |
| `src/ingest/impl.py` | Update manifest entry construction in `ingest_directory()` to include new fields with defaults. Update `_normalize_manifest_entries()` to handle missing new fields gracefully (`.get()` with defaults). |
| `src/ingest/common/utils.py` | No structural change — `load_manifest`/`save_manifest` are schema-agnostic (they serialize/deserialize dicts). |

### Data Structure

```python
# src/ingest/common/schemas.py — additions to ManifestEntry

class ManifestEntry(TypedDict, total=False):
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

    # --- Added by DATA_LIFECYCLE_SPEC ---
    schema_version: str       # Semantic version string, e.g. "1.0.0" (FR-3100)
    trace_id: str             # UUID v4 trace ID for this ingestion run (FR-3050)
    batch_id: str             # Optional batch grouping ID (FR-3053)
    deleted: bool             # True if soft-deleted (FR-3020)
    deleted_at: str           # ISO 8601 timestamp of soft deletion (FR-3020)
    validation: dict          # E2E validation result (FR-3061)
    clean_hash: str           # SHA-256 of clean markdown output
```

### Schema Version Constant

```python
# src/ingest/common/schemas.py or config/settings.py

PIPELINE_SCHEMA_VERSION: str = "1.0.0"
```

Single canonical location per FR-3100 AC4. Referenced by manifest writes, Weaviate chunk
metadata injection, MinIO metadata envelope construction, and the migration runner.

### Backward Compatibility Contract (FR-3114)

All code that reads manifest entries MUST use `.get()` with explicit defaults for new fields:

```python
schema_version = entry.get("schema_version", "0.0.0")
trace_id = entry.get("trace_id", "")
deleted = entry.get("deleted", False)
deleted_at = entry.get("deleted_at", "")
validation = entry.get("validation", {})
clean_hash = entry.get("clean_hash", "")
batch_id = entry.get("batch_id", "")
```

Existing manifests written by older pipeline versions load without error or data loss.

### Acceptance Criteria (from spec)

- FR-3100: `ManifestEntry` includes `schema_version: str`. Every new/updated entry written with current version. Missing field treated as `"0.0.0"`.
- FR-3114: All new fields are `total=False`. `.get()` with defaults used everywhere. Old manifests load cleanly.
- FR-3020 (partial): `deleted` and `deleted_at` fields present in schema (population is Task 4).
- FR-3053 (partial): `batch_id` field present (population is Task 3).
- FR-3061 (partial): `validation` field present (population is Task 6).

### Testing Strategy

- Contract test: Load a manifest written by the current (pre-change) pipeline; verify all new fields resolve to defaults.
- Unit test: Round-trip write/read of a manifest entry with all new fields populated.

---

## Task 3: Trace ID Infrastructure (Gap 7)

**Spec requirements:** FR-3050, FR-3051, FR-3052, FR-3053, NFR-3220

**Dependencies:** Task 2 (manifest schema must include `trace_id` and `batch_id` fields)

**Complexity:** Medium

### Description

Generate a UUID v4 trace ID at the start of each document ingestion and propagate it through
both LangGraph phases, all store writes, and all log messages. Add optional batch ID support.

### Files to Modify

| File | Change |
|------|--------|
| `src/ingest/impl.py` | Generate `trace_id = str(uuid4())` at the top of `ingest_file()`. Pass to Phase 1, Phase 2, manifest writes. Accept optional `batch_id` parameter. |
| `src/ingest/doc_processing/state.py` | Add `trace_id: str` to `DocumentProcessingState` TypedDict. |
| `src/ingest/embedding/state.py` | Add `trace_id: str` to `EmbeddingPipelineState` TypedDict. |
| `src/ingest/doc_processing/__init__.py` | Pass `trace_id` through to `run_document_processing()`. |
| `src/ingest/embedding/__init__.py` | Pass `trace_id` through to `run_embedding_pipeline()`. |
| `src/ingest/embedding/nodes/*.py` | Nodes that write to Weaviate (`embedding_storage`) and Neo4j (`knowledge_graph_storage`) must include `trace_id` in their output metadata. |
| `src/ingest/common/types.py` | Add `batch_id: str = ""` to `IngestionConfig` or as a parameter on `ingest_file()`. |

### Trace ID Flow

```
ingest_file(source_path, runtime, ..., batch_id="")
    │
    ├── trace_id = str(uuid4())                     # FR-3050
    │
    ├── run_document_processing(trace_id=trace_id)  # FR-3051
    │     └── DocumentProcessingState.trace_id
    │           └── All Phase 1 nodes: log with trace_id
    │           └── MinIO clean store write: meta includes trace_id
    │
    ├── run_embedding_pipeline(trace_id=trace_id)   # FR-3052
    │     └── EmbeddingPipelineState.trace_id
    │           └── embedding_storage node: Weaviate chunk.trace_id
    │           └── knowledge_graph_storage node: Neo4j triple.trace_id
    │
    └── manifest[source_key].trace_id = trace_id    # FR-3052 AC4
        manifest[source_key].batch_id = batch_id    # FR-3053
```

### Logging Contract (NFR-3220)

All log calls in pipeline nodes MUST include `trace_id` as a structured field:

```python
logger.info(
    "node_name completed",
    extra={"trace_id": state["trace_id"], "source_key": state["source_key"]},
)
```

This applies to every node in both `src/ingest/doc_processing/nodes/` and
`src/ingest/embedding/nodes/`.

### Interface Changes

```python
# src/ingest/impl.py — ingest_file signature extension
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
```

```python
# src/ingest/common/types.py — IngestFileResult extension
@dataclass
class IngestFileResult:
    # ... existing fields ...
    trace_id: str = ""               # NEW: for caller to include in manifest
```

### Acceptance Criteria (from spec)

- FR-3050: UUID v4 generated once per `ingest_file()` call. Immutable for the workflow duration. Retries reuse the same ID.
- FR-3051: `DocumentProcessingState` includes `trace_id`. Set before first node. All Phase 1 logs include it. MinIO metadata includes it.
- FR-3052: `EmbeddingPipelineState` includes `trace_id`. Weaviate chunks, Neo4j triples, and manifest entries include it.
- FR-3053: Optional `batch_id` accepted, stored in manifest and Weaviate metadata. Absence does not affect behavior.
- NFR-3220: Every log message during ingestion includes `trace_id` in structured fields.

### Testing Strategy

- Unit test: Verify `ingest_file()` generates a UUID v4 and passes it to both phases.
- Unit test: Verify Weaviate chunk metadata includes `trace_id` after embedding_storage node.
- Contract test: Verify `DocumentProcessingState` and `EmbeddingPipelineState` TypedDicts include `trace_id`.
- Log assertion test: Capture log output; verify `trace_id` appears in structured fields.

---

## Task 4: GC / Sync Engine (Gap 2)

**Spec requirements:** FR-3000, FR-3001, FR-3002, FR-3010, FR-3011, FR-3012, FR-3020, FR-3021, FR-3022, NFR-3180, NFR-3210, NFR-3221, NFR-3230

**Dependencies:** Task 1 (MinIO clean store — needed for MinIO cleanup), Task 2 (manifest schema — `deleted`/`deleted_at` fields)

**Complexity:** High

### Description

Build the garbage collection and sync engine that reconciles all four stores against the source
directory, supports soft/hard delete modes, and provides manual, scheduled, and on-ingest
trigger modes.

### Files to Create

| File | Purpose |
|------|---------|
| `src/ingest/lifecycle/__init__.py` | Package init; public exports for GC/sync. |
| `src/ingest/lifecycle/sync.py` | Source-to-manifest diff engine (FR-3000). Returns `SyncResult` with added/modified/deleted lists. |
| `src/ingest/lifecycle/gc.py` | Four-store reconciliation engine (FR-3001). Soft delete (FR-3020), hard delete (FR-3021), retention purge (FR-3022). |
| `src/ingest/lifecycle/orphan_report.py` | Orphan detection report (FR-3002). Queries each store for source_keys absent from manifest. |
| `src/ingest/lifecycle/schemas.py` | Typed contracts: `SyncResult`, `GCResult`, `OrphanReport`, `StoreCleanupStatus`. |

### Files to Modify

| File | Change |
|------|--------|
| `src/ingest/impl.py` | Replace inline GC logic in `ingest_directory()` with calls to `sync.diff_sources()` and `gc.reconcile_deleted()`. Pass four-store clients. |
| `src/ingest/common/types.py` | Add GC config fields to `IngestionConfig`: `gc_mode: str = "soft"`, `gc_retention_days: int = 30`. Add `gc_summary` to `IngestionRunSummary`. |
| `config/settings.py` | Add `RAG_GC_MODE`, `RAG_GC_RETENTION_DAYS`, `RAG_GC_SCHEDULE` environment variable mappings. |

### Interface Contracts

```python
# src/ingest/lifecycle/schemas.py

@dataclass
class SyncResult:
    """Result of a source-to-manifest diff (FR-3000)."""
    added: list[str]           # source_keys with no manifest entry
    modified: list[str]        # source_keys with changed content_hash
    deleted: list[str]         # manifest source_keys with no source file
    unchanged: int             # count of unchanged documents

@dataclass
class StoreCleanupStatus:
    """Per-store cleanup result for a single source_key."""
    weaviate: bool             # True if cleanup succeeded or was unnecessary
    minio: bool
    neo4j: bool
    manifest: bool
    errors: list[str]          # Store-level error messages

@dataclass
class GCResult:
    """Aggregate result of a GC run."""
    soft_deleted: int
    hard_deleted: int
    retention_purged: int
    per_document: dict[str, StoreCleanupStatus]
    dry_run: bool

@dataclass
class OrphanReport:
    """Orphan detection report (FR-3002)."""
    weaviate_orphans: list[str]    # source_keys in Weaviate but not manifest
    minio_orphans: list[str]       # source_keys in MinIO clean/ but not manifest
    neo4j_orphans: list[str]       # source_keys in Neo4j but not manifest
```

```python
# src/ingest/lifecycle/sync.py

def diff_sources(
    source_dir: Path,
    manifest: dict[str, ManifestEntry],
    allowed_suffixes: set[str],
) -> SyncResult:
    """Compare source files against manifest entries (FR-3000).

    Runs in O(n) time relative to max(source_count, manifest_count) per NFR-3180.
    """
    ...
```

```python
# src/ingest/lifecycle/gc.py

def reconcile_deleted(
    deleted_keys: list[str],
    manifest: dict[str, ManifestEntry],
    weaviate_client: Any,
    minio_client: Any,
    minio_bucket: str,
    neo4j_client: Any | None,
    mode: str = "soft",              # "soft" | "hard"
    retention_days: int = 30,
    dry_run: bool = False,
) -> GCResult:
    """Remove or soft-delete data for deleted source_keys across all four stores (FR-3001).

    Failures in any single store do not prevent cleanup of remaining stores (NFR-3210).
    """
    ...

def purge_expired(
    manifest: dict[str, ManifestEntry],
    weaviate_client: Any,
    minio_client: Any,
    minio_bucket: str,
    neo4j_client: Any | None,
    retention_days: int = 30,
) -> int:
    """Hard-delete soft-deleted entries past their retention period (FR-3022).

    Returns count of purged entries.
    """
    ...
```

### Four-Store Cleanup Operations

| Store | Soft Delete | Hard Delete | Interface |
|-------|------------|-------------|-----------|
| Weaviate | Set `deleted=true` property on all chunks with matching `source_key` (filter from retrieval) | `delete_by_source_key(client, source_key)` (existing) | `src/vector_db/__init__.py` — needs new `soft_delete_by_source_key()` |
| MinIO | Move objects to `deleted/{source_key}/` prefix with `deleted_at` tag | Delete objects under `clean/{source_key}.*` | `src/ingest/common/minio_clean_store.py` — `delete()` and new `soft_delete()` |
| Neo4j | Set `deleted=true` property on triples with matching `source_key` provenance | Delete triples with matching `source_key` provenance | `src/core/knowledge_graph.py` — needs new `delete_by_source_key()` and `soft_delete_by_source_key()` |
| Manifest | Set `deleted=True`, `deleted_at=<now>` on entry | Remove entry from dict | In-memory dict operation, persisted via `save_manifest()` |

### New Store Interface Methods Required

```python
# src/vector_db/__init__.py — new function
def soft_delete_by_source_key(client: Any, source_key: str) -> int:
    """Mark all chunks for source_key as deleted (set deleted=true property).
    Returns count of affected chunks.
    """
    ...

# src/core/knowledge_graph.py — new methods on KnowledgeGraphBuilder
def delete_by_source_key(self, source_key: str) -> int:
    """Remove all triples with source_key provenance. Returns count."""
    ...

def soft_delete_by_source_key(self, source_key: str) -> int:
    """Mark all triples with source_key provenance as deleted. Returns count."""
    ...
```

### On-Ingest Integration (FR-3012)

The current inline GC in `ingest_directory()` (lines 587-609 of `src/ingest/impl.py`) is
replaced with:

```python
# After all additions/modifications are processed:
if update and selected_sources is None:
    sync_result = diff_sources(documents_dir, manifest, allowed_suffixes)
    if sync_result.deleted:
        gc_result = reconcile_deleted(
            sync_result.deleted, manifest, client, _db_client,
            config.target_bucket, runtime.kg_builder,
            mode="soft", retention_days=config.gc_retention_days,
        )
        # Include gc_result in IngestionRunSummary
```

### Acceptance Criteria (from spec)

- FR-3000: Sync diff returns added/modified/deleted categories in O(n) time.
- FR-3001: Deleted documents cleaned from all four stores. Single-store failures logged, do not block others.
- FR-3002: Orphan report queries each store independently. Report-only, no mutations.
- FR-3010: CLI command with `--dry-run`, `--mode`, `--retention-days` flags.
- FR-3011: Scheduled via `gc.schedule` cron config.
- FR-3012: On-ingest diff runs during `update=True`; uses soft delete; included in summary.
- FR-3020: Soft delete sets `deleted=True`, `deleted_at` timestamp. Data hidden from retrieval.
- FR-3021: Hard delete removes from all stores immediately. Audit logged.
- FR-3022: Retention purge scans for expired soft-deletes and hard-deletes them.
- NFR-3180: Sync diff is O(n), not O(n*m).
- NFR-3210: Store-level failure isolation.
- NFR-3221: Audit log for every GC operation.
- NFR-3230: Hard delete CLI requires `--confirm` or `--force`.

### Testing Strategy

- Unit test: `diff_sources()` with various added/modified/deleted scenarios.
- Unit test: `reconcile_deleted()` with mocked store clients; verify all four stores are called.
- Unit test: Soft delete sets correct fields; hard delete removes entries.
- Unit test: `purge_expired()` only deletes entries past retention window.
- Failure isolation test: One store raises an exception; verify remaining stores still cleaned.
- Integration test: `ingest_directory(update=True)` with deleted source files; verify four-store cleanup.

---

## Task 5: Schema Migration Runner (Gap 11)

**Spec requirements:** FR-3100, FR-3101, FR-3102, FR-3110, FR-3111, FR-3112, FR-3113, NFR-3181, NFR-3211

**Dependencies:** Task 1 (MinIO clean store — needed to read clean markdown for Phase 2 re-runs), Task 2 (manifest schema_version field), Task 3 (trace ID — migration runs generate new trace IDs)

**Complexity:** High

### Description

Build the schema migration system: a version stamp on every artifact, a machine-readable
changelog, and a migration runner that selectively re-processes documents based on their
schema version.

### Files to Create

| File | Purpose |
|------|---------|
| `config/schema_changelog.yaml` | Machine-readable changelog mapping version transitions to migration strategies (FR-3113). |
| `src/ingest/lifecycle/migration.py` | Migration runner: query manifest for stale documents, classify migration strategy, execute minimum-cost re-processing (FR-3110, FR-3111). |
| `src/ingest/lifecycle/changelog.py` | Changelog parser: load and validate `schema_changelog.yaml`, determine migration strategy for a given version gap. |

### Files to Modify

| File | Change |
|------|--------|
| `src/ingest/impl.py` | Include `schema_version` in manifest entries and MinIO metadata. Include `schema_version` in Weaviate chunk metadata via Phase 2 state. |
| `src/ingest/embedding/nodes/embedding_storage.py` | Add `schema_version` to Weaviate chunk metadata properties (FR-3101). |
| `src/ingest/common/schemas.py` | `PIPELINE_SCHEMA_VERSION` constant (FR-3100 AC4). |

### Schema Changelog Format (FR-3113)

```yaml
# config/schema_changelog.yaml
schema_versions:
  - version: "0.0.0"
    date: "2026-01-01"
    description: "Pre-versioning baseline."
    migration_strategy: "none"

  - version: "1.0.0"
    date: "2026-04-15"
    description: >
      Initial versioned schema. Adds schema_version, trace_id, batch_id,
      deleted/deleted_at, validation, clean_hash to manifest. Adds
      schema_version and trace_id to Weaviate chunk metadata.
    migration_strategy: "metadata_only"
```

### Interface Contracts

```python
# src/ingest/lifecycle/changelog.py

@dataclass
class SchemaChange:
    """A single entry in the schema changelog."""
    version: str
    date: str
    description: str
    migration_strategy: str  # "none" | "metadata_only" | "full_phase2" | "kg_reextract"

def load_changelog(path: Path = Path("config/schema_changelog.yaml")) -> list[SchemaChange]:
    """Load and validate the schema changelog."""
    ...

def determine_migration_strategy(
    from_version: str,
    to_version: str,
    changelog: list[SchemaChange],
) -> str:
    """Return the most expensive migration strategy needed for a version jump.

    If any intermediate version requires full_phase2, the overall strategy is full_phase2.
    Strategies are ordered: none < metadata_only < kg_reextract < full_phase2.
    """
    ...
```

```python
# src/ingest/lifecycle/migration.py

@dataclass
class MigrationResult:
    """Summary of a migration run."""
    total_eligible: int
    processed: int
    failed: int
    skipped: int  # already at target version
    strategy_counts: dict[str, int]  # e.g., {"metadata_only": 45, "full_phase2": 3}

def run_migration(
    manifest: dict[str, ManifestEntry],
    target_version: str | None = None,  # None = current PIPELINE_SCHEMA_VERSION
    dry_run: bool = False,
    runtime: Runtime | None = None,     # needed for full_phase2 re-runs
    minio_clean_store: MinioCleanStore | None = None,  # read clean MD for re-embedding
) -> MigrationResult:
    """Execute schema migration for all documents below target version (FR-3110).

    Idempotent: already-migrated documents are skipped (FR-3112).
    Resumable: interrupted migrations can be re-run safely (NFR-3211).

    Migration strategies (FR-3111):
      - metadata_only: Weaviate batch partial-update. No re-embedding.
      - full_phase2: Read clean markdown from MinIO, re-run Embedding Pipeline.
      - kg_reextract: Delete old triples, re-run KG extraction nodes.
    """
    ...
```

### Migration Strategy Execution

| Strategy | Steps | Cost |
|----------|-------|------|
| `metadata_only` | 1. Weaviate batch partial-update (add/update properties). 2. Update manifest `schema_version`. | Cheap. >= 100 docs/sec per NFR-3181. |
| `full_phase2` | 1. Read clean markdown from MinIO. 2. Generate new trace_id. 3. Run full Embedding Pipeline. 4. Update manifest. | Expensive. GPU-bound. |
| `kg_reextract` | 1. Delete existing triples for source_key. 2. Read clean markdown from MinIO. 3. Re-run KG extraction nodes only. 4. Update manifest. | Medium. LLM-bound. |
| `none` | No action. Version transition has no schema impact. | Free. |

### Acceptance Criteria (from spec)

- FR-3100: Every manifest entry has `schema_version`. Missing = `"0.0.0"`.
- FR-3101: Every Weaviate chunk has `schema_version` metadata property.
- FR-3102: MinIO `.meta.json` includes `schema_version`.
- FR-3110: Migration CLI with `--dry-run` and `--target-version`. Summary report.
- FR-3111: Three strategy classifications applied correctly. Minimum-cost path used.
- FR-3112: Idempotent. Re-running is safe. No data duplication.
- FR-3113: YAML changelog exists. Each version has strategy. CI-validateable.
- NFR-3181: Metadata-only migrations >= 100 docs/sec.
- NFR-3211: Interrupted migrations resumable without re-processing completed documents.

### Testing Strategy

- Unit test: `load_changelog()` validates YAML format and required fields.
- Unit test: `determine_migration_strategy()` returns correct strategy for version gaps.
- Unit test: `run_migration(dry_run=True)` reports eligible documents without modifying stores.
- Idempotency test: Run migration twice; verify second run is all skips.
- Resumability test: Simulate interruption at document N; re-run; verify only N+1..end processed.

---

## Task 6: E2E Validation Node (Gap 7)

**Spec requirements:** FR-3060, FR-3061, FR-3062

**Dependencies:** Task 1 (MinIO clean store — validation queries MinIO), Task 2 (manifest `validation` field), Task 3 (trace ID — validation queries by trace_id)

**Complexity:** Medium

### Description

Add a post-Phase 2 validation step that queries all enabled stores to verify they received
data for the document's trace ID. Record the result in the manifest.

### Files to Create

| File | Purpose |
|------|---------|
| `src/ingest/lifecycle/validation.py` | E2E validation logic: query each store, return structured result. |

### Files to Modify

| File | Change |
|------|--------|
| `src/ingest/impl.py` | Call `validate_document()` after Phase 2 succeeds. Record result in manifest entry. |
| `src/ingest/common/types.py` | Add `validation: dict = field(default_factory=dict)` to `IngestFileResult`. |

### Interface Contract

```python
# src/ingest/lifecycle/validation.py

@dataclass
class ValidationResult:
    """Per-document E2E consistency validation result (FR-3061)."""
    validated_at: str          # ISO 8601 timestamp
    weaviate_ok: bool          # At least one chunk with trace_id found
    minio_ok: bool             # Clean markdown object exists for source_key
    neo4j_ok: bool | None      # At least one triple with trace_id, or None if KG disabled
    consistent: bool           # True only if all enabled stores passed

    def to_dict(self) -> dict:
        """Serialize for manifest storage."""
        ...

def validate_document(
    trace_id: str,
    source_key: str,
    weaviate_client: Any,
    minio_client: Any,
    minio_bucket: str,
    neo4j_client: Any | None,
    kg_enabled: bool,
) -> ValidationResult:
    """Query all enabled stores to verify they received data for this trace_id (FR-3060).

    Checks:
    1. Weaviate: >= 1 chunk with trace_id (FR-3060 AC1)
    2. MinIO: clean markdown object exists for source_key (FR-3060 AC2)
    3. Neo4j: >= 1 triple with trace_id, if KG enabled (FR-3060 AC3)
    4. Manifest check is implicit (caller verifies) (FR-3060 AC4)

    Disabled stores are reported as None, not False (FR-3062).
    Failure is logged but does NOT trigger retry (FR-3060 AC6).
    """
    ...
```

### Integration Point in Orchestrator

```python
# src/ingest/impl.py — inside ingest_file(), after Phase 2 succeeds

if not phase2.get("errors"):
    validation = validate_document(
        trace_id=trace_id,
        source_key=source_key,
        weaviate_client=runtime.weaviate_client,
        minio_client=runtime.db_client,
        minio_bucket=runtime.config.target_bucket,
        neo4j_client=None,  # TODO: pass Neo4j client when available on Runtime
        kg_enabled=runtime.config.enable_knowledge_graph_storage,
    )
    if not validation.consistent:
        logger.warning(
            "e2e_validation_inconsistent trace_id=%s source_key=%s weaviate=%s minio=%s neo4j=%s",
            trace_id, source_key,
            validation.weaviate_ok, validation.minio_ok, validation.neo4j_ok,
        )
    # Include in result for manifest recording
```

### Store Query Methods Required

```python
# src/vector_db/__init__.py — new function
def count_by_trace_id(client: Any, trace_id: str) -> int:
    """Return count of chunks with the given trace_id. Used for E2E validation."""
    ...

# MinIO: use MinioCleanStore.exists(source_key) — already defined in Task 1.

# Neo4j: KnowledgeGraphBuilder needs a query method
# src/core/knowledge_graph.py
def count_triples_by_trace_id(self, trace_id: str) -> int:
    """Return count of triples with the given trace_id. Used for E2E validation."""
    ...
```

### Acceptance Criteria (from spec)

- FR-3060: Validation queries all enabled stores by trace_id/source_key after successful ingestion.
- FR-3061: Manifest entry includes `validation` dict with `validated_at`, per-store booleans, and `consistent`.
- FR-3062: Disabled stores reported as `None`. Document is consistent when all enabled stores pass.

### Testing Strategy

- Unit test: `validate_document()` with all stores passing; verify `consistent=True`.
- Unit test: One store failing; verify `consistent=False` and correct store flagged.
- Unit test: KG disabled; verify `neo4j_ok=None` and document still consistent if others pass.
- Integration test: Full `ingest_file()` run; verify manifest entry contains `validation` dict.

---

# Part C: Data Structures and Contracts

## Manifest Entry (Complete Schema After All Tasks)

```python
class ManifestEntry(TypedDict, total=False):
    # Source identity
    source: str                  # Display name
    source_uri: str              # Stable URI
    source_id: str               # OS-level identity (dev:inode)
    source_key: str              # Primary key
    connector: str               # Connector type (e.g., "local_fs")
    source_version: str          # Source version (mtime_ns)
    legacy_name: str             # Pre-migration filename key

    # Processing results
    content_hash: str            # SHA-256 of source file
    clean_hash: str              # SHA-256 of clean markdown (NEW)
    chunk_count: int             # Chunks stored in Weaviate
    summary: str                 # LLM-generated summary
    keywords: list[str]          # LLM-extracted keywords
    processing_log: list[str]    # Last N pipeline stage names
    mirror_stem: str             # Mirror artifact filename stem

    # Lifecycle (NEW)
    schema_version: str          # Pipeline schema version
    trace_id: str                # UUID v4 trace ID
    batch_id: str                # Optional batch grouping ID
    deleted: bool                # Soft-delete flag
    deleted_at: str              # ISO 8601 soft-delete timestamp
    validation: dict             # E2E validation result
```

## MinIO Clean Store Metadata Envelope (FR-3033)

```json
{
  "source_key": "local_fs:65025:12345",
  "source_name": "docs/architecture.pdf",
  "source_uri": "file:///home/user/docs/architecture.pdf",
  "source_id": "65025:12345",
  "connector": "local_fs",
  "source_version": "1712345678000000000",
  "source_hash": "a1b2c3...",
  "clean_hash": "d4e5f6...",
  "schema_version": "1.0.0",
  "trace_id": "550e8400-e29b-41d4-a716-446655440000",
  "created_at": "2026-04-15T10:30:00Z"
}
```

## Weaviate Chunk Metadata (Extended Properties)

The following properties are added to the Weaviate collection schema:

| Property | Type | Source |
|----------|------|--------|
| `trace_id` | string | FR-3052 |
| `schema_version` | string | FR-3101 |
| `batch_id` | string (optional) | FR-3053 |
| `deleted` | boolean | FR-3020 (for soft-delete filtering) |

## GC / Sync Result Types

See Task 4 interface contracts for `SyncResult`, `GCResult`, `StoreCleanupStatus`, and
`OrphanReport` definitions.

## Validation Result Type

See Task 6 interface contract for `ValidationResult` definition.

---

# Part D: Dependency Graph

```
Task 2: Manifest Schema Extension
  │  (no dependencies — schema-only)
  │
  ├──────────────────────────────────────────────┐
  │                                              │
  ▼                                              ▼
Task 1: MinIO Clean Store Migration          Task 3: Trace ID Infrastructure
  │  (depends on Task 2 for meta fields)       │  (depends on Task 2 for manifest fields)
  │                                              │
  ├──────────────┐                               │
  │              │                               │
  ▼              ▼                               │
Task 4: GC/Sync Engine    Task 5: Schema Migration Runner
  │  (depends on T1, T2)    │  (depends on T1, T2, T3)
  │                          │
  └──────────┐               │
             │               │
             ▼               │
         Task 6: E2E Validation Node
           (depends on T1, T2, T3)
```

### Recommended Implementation Order

| Phase | Tasks | Rationale |
|-------|-------|-----------|
| **Phase A** | Task 2 (Manifest Schema) | Zero-risk schema extension. Unblocks everything. |
| **Phase B** | Task 1 (MinIO Clean Store) + Task 3 (Trace ID) — **parallel** | Independent work streams. Task 1 is plumbing; Task 3 is instrumentation. |
| **Phase C** | Task 4 (GC Engine) + Task 6 (E2E Validation) — **parallel** | Both depend on Tasks 1-3. GC is the largest task; validation is self-contained. |
| **Phase D** | Task 5 (Schema Migration Runner) | Depends on everything. Last to build, first to benefit from stable foundation. |

---

# Part E: Migration Path

## From Current Implementation to Target

### Step 1: Manifest Schema Extension (Task 2)

**Risk:** None. All new fields are optional with defaults.

- Add fields to `ManifestEntry` TypedDict.
- Add `PIPELINE_SCHEMA_VERSION` constant.
- Update `_normalize_manifest_entries()` to handle missing fields.
- Existing manifests load without modification. New entries written with all fields.

### Step 2: MinIO Clean Store (Task 1)

**Risk:** Low. Current MinIO integration (`src/db/`) is stable.

- Create `MinioCleanStore` alongside existing `CleanDocumentStore`.
- Add MinIO write to `ingest_file()` main path (after Phase 1 success).
- Keep `CleanDocumentStore` for `export_processed` debug mode only.
- Remove `write_docling()`/`read_docling()` and `persist_docling_document` config flag.
- Remove `.docling.json` from debug export.

**Backward compatibility:** The `CleanDocumentStore` class is retained as a debug-only
facade. Existing code that imports it continues to work. A deprecation warning is emitted
on instantiation.

### Step 3: Trace ID (Task 3)

**Risk:** Low. Additive change to state TypedDicts and log calls.

- Add `trace_id` to both LangGraph state TypedDicts.
- Generate UUID at `ingest_file()` entry.
- Thread through Phase 1 and Phase 2 function signatures.
- Add to Weaviate chunk metadata and Neo4j triple properties.
- Add structured logging fields to all pipeline nodes.

**Backward compatibility:** Nodes that do not yet read `trace_id` from state are unaffected
(it is a `total=False` field). Log format changes are additive.

### Step 4: GC Engine (Task 4)

**Risk:** Medium. Touches all four stores with delete operations.

- Create `src/ingest/lifecycle/` package.
- Implement sync diff, four-store reconciliation, soft/hard delete.
- Replace inline GC in `ingest_directory()` with lifecycle module calls.
- Add `soft_delete_by_source_key()` to vector_db and knowledge_graph interfaces.
- **Safety net:** `--dry-run` flag on all destructive operations. Soft delete by default.

**Backward compatibility:** The inline GC logic in `ingest_directory()` is replaced, not
extended. The behavior is identical for Weaviate and manifest cleanup. MinIO and Neo4j
cleanup is net-new behavior.

### Step 5: Schema Migration (Task 5) and E2E Validation (Task 6)

**Risk:** Low. Both are additive capabilities that do not modify existing behavior.

- Schema migration runner reads manifest, classifies strategy, executes minimum-cost path.
- E2E validation queries stores after Phase 2 and records result in manifest.
- Neither modifies existing ingestion behavior — they add post-processing steps.

---

# Part F: Risk Assessment

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| MinIO write failure during Phase 1 leaves document without durable backup | Medium | Low | Retry with exponential backoff. Log warning but do not fail the pipeline — in-memory handoff still delivers data to Phase 2. Mark validation.minio_ok=false. |
| Soft-delete filtering in Weaviate adds latency to retrieval queries | Medium | Medium | Benchmark with and without `deleted != true` filter. If latency exceeds 10%, switch to physical partition or separate collection for deleted chunks. |
| Schema changelog diverges from actual code changes | High | Medium | CI validation: require changelog entry for any PR that modifies ManifestEntry, Weaviate schema, or KG extraction logic. |
| GC accidentally deletes data for temporarily unmounted source directory | High | Low | Soft delete is the default with 30-day retention. Hard delete requires explicit `--confirm`. Audit log for all deletions (NFR-3221). |
| Migration runner overwhelms stores with concurrent re-processing | Medium | Medium | Rate-limit migration batches. Process sequentially by default; add `--concurrency N` flag for parallel execution. |
| Neo4j unavailable during GC leaves triples orphaned | Low | Medium | Store-level failure isolation (NFR-3210). GC result reports partial failure. Subsequent GC runs retry failed stores. |
| Large manifest (100k+ entries) causes slow GC scans | Low | Low | Manifest is loaded into memory as a dict — O(n) lookup. If manifest size exceeds practical limits, migrate to SQLite (future work, out of scope). |
