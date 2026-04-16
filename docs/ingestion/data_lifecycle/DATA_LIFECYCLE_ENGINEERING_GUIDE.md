> **⚠ DRAFT — PRE-IMPLEMENTATION DESIGN RATIONALE**
>
> This document was authored **before** source code existed and has not been validated against a running implementation. File paths, CLI syntax, error messages, and troubleshooting sections are **speculative**. Sections that claim post-implementation knowledge (Operations, Troubleshooting, exact module paths, performance numbers) are provisional until the code lands.
>
> To be **fully rewritten post-implementation** using `/write-engineering-guide` (which now enforces a non-skippable existence check). For authoritative content prior to rewrite, consult the companion `DATA_LIFECYCLE_SPEC.md`, `DATA_LIFECYCLE_DESIGN.md`, and `DATA_LIFECYCLE_IMPLEMENTATION.md`.
>
> **Salvage audit:** Architecture Overview (§1), Data Flow (§2), and Extension Guide (§4) capture design intent and survive rewrite. Operations (§3) and Troubleshooting (§5) will be regenerated from real code.

---

> **Document type:** Engineering guide (Layer 5)
> **Upstream:** DATA_LIFECYCLE_IMPLEMENTATION.md
> **Last updated:** 2026-04-15
> **Status:** DRAFT (pre-implementation)

# Data Lifecycle -- Engineering Guide (v1.0.0-draft)

## 1. Architecture Overview

### 1.1 System Context (where data lifecycle fits in the pipeline)

The Data Lifecycle subsystem is a cross-cutting layer that sits alongside the two-phase
ingestion pipeline. It does not own any pipeline stage. Instead, it governs what happens
to data **after** it has been written to the four storage backends, and it extends the
pipeline orchestrator with trace propagation, validation, and durable storage concerns.

```
Source Directory (ground truth)
       |
       v
+-- Ingestion Orchestrator (src/ingest/impl.py) ---------------------+
|                                                                     |
|  1. trace_id = uuid4()    <-- lifecycle injects trace identity      |
|  2. Phase 1: Document Processing                                    |
|  3. MinIO durable write   <-- lifecycle adds clean store persistence|
|  4. Phase 2: Embedding Pipeline                                     |
|  5. E2E Validation        <-- lifecycle validates cross-store state |
|  6. Manifest write        <-- lifecycle extends schema              |
|                                                                     |
+----+---------------------------+-----------------------------------+
     |                           |
     v                           v
  On-ingest GC                Schema Migration
  (src/ingest/lifecycle/)     (src/ingest/lifecycle/migration.py)
     |                           |
     +-- diff_sources()          +-- run_migration()
     +-- reconcile_deleted()     +-- determine_migration_strategy()
     +-- purge_expired()         +-- schema_changelog.yaml
```

The four stores that lifecycle manages:

| Store | What it holds | Lifecycle operations |
|-------|--------------|---------------------|
| **Weaviate** | Vector chunks + embeddings + metadata | Soft/hard delete, metadata-only migration, schema_version stamp |
| **MinIO** | Clean markdown blobs + `.meta.json` envelopes | Durable clean store write, soft delete (move to `deleted/` prefix), orphan scan |
| **Neo4j** | KG triples + entity nodes | Soft/hard delete by source_key provenance, KG re-extraction migration |
| **Manifest** (JSON) | Idempotency ledger per source_key | Extended with 7 new fields, soft-delete flags, validation results |

### 1.2 Key Architecture Decisions (and why)

**Decision 1: In-memory inter-phase handoff, MinIO as durable backup (not boundary).**
Phase 1 returns `clean_text` to the orchestrator in memory. The orchestrator passes it
directly to Phase 2. MinIO receives a write after Phase 1 succeeds, but Phase 2 never
reads from MinIO during normal operation. This was chosen because (a) the in-memory path
was already the reality in the codebase -- `CleanDocumentStore` was only used for debug
export, and (b) making MinIO the inter-phase boundary would add latency on every document
with no benefit until multi-node Temporal workers are deployed. MinIO is used as the
recovery/migration data source (the migration runner reads clean markdown from MinIO for
`full_phase2` re-runs).

**Decision 2: Soft delete by default, hard delete opt-in.**
Source files can be temporarily moved, renamed, or on an unmounted drive. A 30-day
retention window prevents irreversible data loss from transient filesystem changes.
Hard delete requires explicit `--mode hard --confirm` at the CLI to prevent accidents.

**Decision 3: Schema version as a string constant, not computed from code.**
`PIPELINE_SCHEMA_VERSION` is a single constant in `src/ingest/common/schemas.py`. It is
bumped manually when a schema-impacting change ships. The alternative -- deriving the
version from code structure or hashing -- was rejected because migration strategy
classification needs a human-authored changelog entry for each version bump (you cannot
automatically determine whether a change is metadata-only or requires re-embedding).

**Decision 4: O(n) sync diff via set operations.**
The sync engine uses Python set intersection/difference on `source_key` sets, not nested
loops. This keeps GC fast enough to run on every incremental ingestion without adding
meaningful latency. The manifest is the reference -- individual stores are not scanned
during the diff (orphan detection is a separate, heavier operation).

**Decision 5: Store-level failure isolation in GC.**
A Neo4j timeout during GC must not prevent Weaviate cleanup from proceeding. Each store
cleanup is wrapped in its own try/except, and `StoreCleanupStatus` records per-store
success/failure. This is enforced by NFR-3210.

### 1.3 Component Map

```
src/ingest/
+-- common/
|   +-- schemas.py              # ManifestEntry (7 new fields), PIPELINE_SCHEMA_VERSION
|   +-- minio_clean_store.py    # MinioCleanStore: write/read/delete/soft_delete/list_keys
|   +-- clean_store.py          # CleanDocumentStore (deprecated, debug-only)
|   +-- types.py                # IngestionConfig (GC fields), IngestFileResult (trace_id, validation)
|   +-- __init__.py             # Exports MinioCleanStore + backward-compat alias
+-- lifecycle/
|   +-- __init__.py             # Public exports: diff_sources, reconcile_deleted, purge_expired, ...
|   +-- schemas.py              # SyncResult, GCResult, StoreCleanupStatus, OrphanReport
|   +-- sync.py                 # diff_sources() -- source-to-manifest O(n) diff
|   +-- gc.py                   # reconcile_deleted(), purge_expired() -- four-store GC
|   +-- orphan_report.py        # detect_orphans() -- report-only, no mutations
|   +-- migration.py            # run_migration() -- schema migration runner
|   +-- changelog.py            # load_changelog(), determine_migration_strategy()
|   +-- validation.py           # validate_document() -- per-document E2E consistency

config/
+-- schema_changelog.yaml       # Machine-readable changelog (version -> migration strategy)
+-- settings.py                 # RAG_GC_MODE, RAG_GC_RETENTION_DAYS, RAG_GC_SCHEDULE

src/vector_db/__init__.py       # New: soft_delete_by_source_key, count_by_trace_id,
                                #       list_source_keys, batch_update_metadata_by_source_key
src/core/knowledge_graph.py     # New: delete_by_source_key, soft_delete_by_source_key,
                                #       count_triples_by_trace_id, list_source_keys
```

---

## 2. Data Flow

### 2.1 Document Ingestion Flow (MinIO clean store)

This is the happy path for a single document through `ingest_file()`:

```
ingest_file(source_path, runtime, ..., batch_id="batch-42")
  |
  +-- trace_id = "a1b2c3d4-..."           # Step 1: Generate UUID v4
  |
  +-- phase1 = run_document_processing(    # Step 2: Phase 1
  |       ..., trace_id=trace_id           #   trace_id injected into LangGraph state
  |   )
  |   returns: {clean_text: "# Doc Title\n...", source_hash: "abc123", ...}
  |
  +-- clean_hash = sha256(clean_text)      # Step 3: Compute clean_hash
  |
  +-- minio_store.write(                   # Step 4: Durable MinIO write
  |       source_key,
  |       clean_text,
  |       meta={
  |           source_key, source_name, source_uri, source_id,
  |           connector, source_version, source_hash, clean_hash,
  |           schema_version: "1.0.0", trace_id: "a1b2c3d4-..."
  |       }
  |   )
  |   writes:
  |     clean/my_document_pdf.md          (text/markdown)
  |     clean/my_document_pdf.meta.json   (application/json, written LAST = commit marker)
  |
  +-- _debug_store.write(...)              # Step 4b: Optional local debug export
  |   (only if config.export_processed=True)
  |
  +-- phase2 = run_embedding_pipeline(     # Step 5: Phase 2
  |       ..., clean_text=clean_text,
  |       trace_id=trace_id, batch_id="batch-42"
  |   )
  |   writes to Weaviate:  chunk.trace_id = "a1b2c3d4-..."
  |                         chunk.schema_version = "1.0.0"
  |                         chunk.batch_id = "batch-42"
  |                         chunk.deleted = False
  |   writes to Neo4j:     triple.trace_id = "a1b2c3d4-..."
  |
  +-- validate_document(trace_id, ...)     # Step 6: E2E validation
  |   queries: Weaviate (count_by_trace_id), MinIO (exists), Neo4j (count_triples)
  |   returns: ValidationResult(consistent=True, weaviate_ok=True, minio_ok=True, neo4j_ok=True)
  |
  +-- return IngestFileResult(             # Step 7: Return to orchestrator
          trace_id="a1b2c3d4-...",
          validation={validated_at: "...", consistent: true, ...},
          clean_hash="def456", ...
      )
```

The orchestrator then writes the manifest entry with all lifecycle fields:

```python
manifest[source_key] = {
    # ... existing fields (source, source_uri, content_hash, etc.) ...
    "schema_version": "1.0.0",
    "trace_id": "a1b2c3d4-...",
    "batch_id": "batch-42",
    "deleted": False,
    "deleted_at": "",
    "validation": {"validated_at": "...", "consistent": true, ...},
    "clean_hash": "def456",
}
```

### 2.2 GC/Sync Flow (with concrete examples)

**Scenario:** You have 100 documents in the manifest. You delete 3 source files from the
source directory and run `ingest_directory(update=True)`.

```
ingest_directory(documents_dir, update=True)
  |
  +-- ... process new/modified documents first ...
  |
  +-- diff_sources(documents_dir, manifest, allowed_suffixes)
  |   |
  |   +-- Scan source_dir: finds 97 files
  |   +-- Load manifest: 100 entries (excluding deleted)
  |   +-- Set diff:
  |       source_keys = {97 keys}
  |       manifest_keys = {100 keys}
  |       deleted = manifest_keys - source_keys = {doc_a, doc_b, doc_c}
  |       added = source_keys - manifest_keys = {}
  |       modified = [key for key in common if hash_changed(key)] = {}
  |   +-- Returns SyncResult(added=[], modified=[], deleted=[doc_a, doc_b, doc_c], unchanged=97)
  |
  +-- reconcile_deleted(
  |       deleted_keys=[doc_a, doc_b, doc_c],
  |       manifest=manifest,
  |       weaviate_client=client,
  |       minio_client=_db_client,
  |       minio_bucket="my-bucket",
  |       neo4j_client=runtime.kg_builder,
  |       mode="soft",               # default
  |       retention_days=30,
  |   )
  |   |
  |   For each deleted key (e.g., doc_a):
  |   |  +-- Weaviate: soft_delete_by_source_key(client, "doc_a")
  |   |  |     sets deleted=true on all chunks matching source_key
  |   |  +-- MinIO: store.soft_delete("doc_a")
  |   |  |     copies clean/doc_a.md -> deleted/doc_a.md
  |   |  |     copies clean/doc_a.meta.json -> deleted/doc_a.meta.json
  |   |  |     removes originals under clean/
  |   |  +-- Neo4j: kg_builder.soft_delete_by_source_key("doc_a")
  |   |  |     sets deleted=true on triples with source_key provenance
  |   |  +-- Manifest: manifest["doc_a"]["deleted"] = True
  |   |  |              manifest["doc_a"]["deleted_at"] = "2026-04-15T10:30:00+00:00"
  |   |  +-- Audit log: gc_operation source_key=doc_a mode=soft weaviate=True minio=True ...
  |   |
  |   Returns GCResult(soft_deleted=3, hard_deleted=0, ...)
  |
  +-- purge_expired(manifest, ..., retention_days=30)
      |
      +-- Scans manifest for entries where deleted=True AND deleted_at < (now - 30 days)
      +-- Suppose doc_x was soft-deleted 45 days ago:
          +-- reconcile_deleted([doc_x], ..., mode="hard")
              removes doc_x from all 4 stores permanently
```

**Retention purge timeline:**

```
Day 0:    doc_x soft-deleted. deleted=True, deleted_at="2026-03-01T..."
Day 1-29: doc_x hidden from retrieval, but data preserved in all stores.
          Operator can restore by setting deleted=False and deleted_at="".
Day 30+:  Next GC run calls purge_expired(). doc_x is past retention window.
          Hard-deleted from Weaviate, MinIO, Neo4j. Manifest entry removed.
```

### 2.3 Schema Migration Flow

**Scenario:** You upgrade the pipeline from schema 1.0.0 to 1.1.0. The changelog says
1.1.0 is a `metadata_only` migration. You have 500 documents at 1.0.0 and 50 legacy
documents at 0.0.0.

```
run_migration(manifest, target_version="1.1.0", dry_run=False, ...)
  |
  +-- changelog = load_changelog("config/schema_changelog.yaml")
  |
  +-- For each manifest entry (550 total):
  |   +-- doc at "1.1.0" -> skipped (already current)
  |   +-- doc at "1.0.0" -> determine_migration_strategy("1.0.0", "1.1.0", changelog)
  |   |   -> examines versions between 1.0.0 (exclusive) and 1.1.0 (inclusive)
  |   |   -> returns "metadata_only"
  |   +-- doc at "0.0.0" -> determine_migration_strategy("0.0.0", "1.1.0", changelog)
  |       -> examines 1.0.0 (metadata_only) and 1.1.0 (metadata_only)
  |       -> max rank = metadata_only -> returns "metadata_only"
  |
  +-- eligible = 550 documents, all strategy="metadata_only"
  |
  +-- For each eligible document:
  |   +-- _migrate_metadata_only(source_key, entry, "1.1.0", weaviate_client)
  |   |   calls batch_update_metadata_by_source_key(client, source_key,
  |   |       properties={"schema_version": "1.1.0"})
  |   +-- entry["schema_version"] = "1.1.0"   # manifest updated in-memory
  |
  +-- Returns MigrationResult(total_eligible=550, processed=550, failed=0, skipped=0,
          strategy_counts={"metadata_only": 550})
```

**Strategy escalation example:** If version 1.2.0 introduces `full_phase2` (embedding
model changed), then `determine_migration_strategy("0.0.0", "1.2.0", changelog)` walks
through 1.0.0 (metadata_only, rank 1), 1.1.0 (metadata_only, rank 1), 1.2.0
(full_phase2, rank 3) and returns `full_phase2` because rank 3 > rank 1. The migration
runner reads clean markdown from MinIO and re-runs the full embedding pipeline.

### 2.4 Trace ID Propagation

The trace ID flows through every layer of the system:

```
Orchestrator         Phase 1 State           Phase 2 State           Stores
+-----------+        +---------------+        +---------------+       +-----------+
| trace_id  | -----> | trace_id      | -----> | trace_id      | ----> | Weaviate  |
| = uuid4() |        | (in TypedDict)|        | (in TypedDict)|       |  .trace_id|
+-----------+        +-------+-------+        +-------+-------+       +-----------+
      |                      |                        |               | MinIO     |
      |                      v                        v               |  .meta    |
      |              All Phase 1 logs         All Phase 2 logs        |  .trace_id|
      |              include trace_id         include trace_id        +-----------+
      |              in extra= field          in extra= field         | Neo4j     |
      |                      |                        |               |  .trace_id|
      |                      v                        v               +-----------+
      |              MinIO meta.json           Weaviate chunks        | Manifest  |
      +------------> .trace_id                 .trace_id              |  .trace_id|
                                               Neo4j triples          +-----------+
                                               .trace_id
```

Structured logging pattern used in every pipeline node:

```python
logger.info(
    "text_cleaning_complete chars=%d",
    len(cleaned_text),
    extra={
        "trace_id": state.get("trace_id", ""),
        "source_key": state.get("source_key", ""),
    },
)
```

This enables filtering all log lines for a single document ingestion:

```bash
# Find all logs for a specific trace
grep "trace_id=a1b2c3d4" logs/ingest.log
```

---

## 3. Operations Guide

### 3.1 Running Manual GC

**Dry run** (see what would be deleted without touching any store):

```bash
aion ingest gc --dry-run
```

Output:

```
Sync result: added=0 modified=2 deleted=5 unchanged=193
Dry-run GC: 5 documents would be soft-deleted
  - local_fs:reports/Q1_2025.pdf
  - local_fs:reports/Q2_2025.pdf
  - local_fs:drafts/old_proposal.docx
  - local_fs:notes/meeting_2025-01-15.md
  - local_fs:notes/meeting_2025-02-01.md
```

**Soft delete** (default, 30-day retention):

```bash
aion ingest gc
# equivalent to: aion ingest gc --mode soft --retention-days 30
```

**Hard delete** (irreversible, requires confirmation):

```bash
aion ingest gc --mode hard --confirm
```

**Override retention period:**

```bash
aion ingest gc --retention-days 7
```

**Programmatic API:**

```python
from src.ingest.lifecycle.sync import diff_sources
from src.ingest.lifecycle.gc import reconcile_deleted, purge_expired

sync_result = diff_sources(source_dir, manifest, allowed_suffixes)
if sync_result.deleted:
    gc_result = reconcile_deleted(
        deleted_keys=sync_result.deleted,
        manifest=manifest,
        weaviate_client=client,
        minio_client=db_client,
        minio_bucket="my-bucket",
        neo4j_client=kg_builder,
        mode="soft",
        retention_days=30,
        dry_run=False,
    )
    print(f"Soft-deleted: {gc_result.soft_deleted}")

# Purge expired soft-deletes
purged = purge_expired(manifest, client, db_client, "my-bucket", kg_builder, retention_days=30)
print(f"Purged: {purged}")
```

### 3.2 Running Schema Migrations

**Check what needs migration** (dry run):

```bash
aion ingest migrate --dry-run
```

Output:

```
Migration dry run: target=1.1.0
  Eligible: 550 documents
  Strategies: metadata_only=548, full_phase2=2
  Skipped: 0 (already at target)
```

**Run the migration:**

```bash
aion ingest migrate
```

**Migrate to a specific version** (not necessarily latest):

```bash
aion ingest migrate --target-version 1.0.0
```

**After a migration**, verify with:

```bash
# Check for documents still below target version
python -c "
from src.ingest.common.utils import load_manifest
m = load_manifest('processed/manifest.json')
stale = [k for k, v in m.items() if v.get('schema_version', '0.0.0') != '1.1.0']
print(f'Documents still below target: {len(stale)}')
for k in stale[:10]:
    print(f'  {k}: {m[k].get(\"schema_version\", \"0.0.0\")}')
"
```

**Adding a new schema version:**

1. Bump `PIPELINE_SCHEMA_VERSION` in `src/ingest/common/schemas.py`.
2. Add an entry to `config/schema_changelog.yaml`:

```yaml
  - version: "1.1.0"
    date: "2026-05-01"
    description: "Added document_type metadata property to Weaviate chunks."
    migration_strategy: "metadata_only"
```

3. The migration runner reads the changelog and applies the correct strategy.

### 3.3 Checking E2E Validation Results

**Find inconsistent documents:**

```python
from src.ingest.common.utils import load_manifest

manifest = load_manifest("processed/manifest.json")
inconsistent = [
    (k, v.get("validation", {}))
    for k, v in manifest.items()
    if v.get("validation", {}).get("consistent") is False
]
print(f"Inconsistent documents: {len(inconsistent)}")
for key, val in inconsistent:
    print(f"  {key}: weaviate={val.get('weaviate_ok')} "
          f"minio={val.get('minio_ok')} neo4j={val.get('neo4j_ok')}")
```

**Re-ingest inconsistent documents:**

```python
# Collect source keys of inconsistent documents
keys_to_reingest = [k for k, v in inconsistent]
# Pass them to ingest_directory with selected_sources filter
```

**Documents with no validation** (pre-lifecycle, schema_version 0.0.0):

```python
no_validation = [k for k, v in manifest.items() if not v.get("validation")]
print(f"Documents without validation: {len(no_validation)}")
```

### 3.4 Monitoring and Alerts

**Key log patterns to monitor:**

| Pattern | Meaning | Action |
|---------|---------|--------|
| `e2e_validation_inconsistent` | A document finished Phase 2 but a store is missing data | Investigate the failing store; re-ingest the document |
| `gc_weaviate_failed` | GC could not clean Weaviate for a source_key | Check Weaviate connectivity; the document is partially cleaned |
| `gc_minio_failed` | GC could not clean MinIO for a source_key | Check MinIO connectivity; orphan blobs may remain |
| `gc_neo4j_failed` | GC could not clean Neo4j for a source_key | Check Neo4j connectivity; orphan triples may remain |
| `minio_clean_store_write_failed` | MinIO durable write failed after Phase 1 | In-memory handoff still works; migration/recovery reads will fail for this doc |
| `migration_failed` | A document failed during schema migration | Check error details; re-run migration (idempotent) |
| `gc_purge_invalid_deleted_at` | A soft-deleted entry has a malformed timestamp | Manual fix needed on the manifest entry |

**Environment variables for configuration:**

```bash
RAG_GC_MODE=soft              # "soft" or "hard"
RAG_GC_RETENTION_DAYS=30      # days before soft-deleted data is purged
RAG_GC_SCHEDULE=""            # cron expression, e.g. "0 3 * * 0" for weekly at 3 AM
```

**Orphan detection** (run periodically to detect data drift):

```python
from src.ingest.lifecycle.orphan_report import detect_orphans

report = detect_orphans(manifest, weaviate_client, minio_client, "my-bucket", kg_builder)
print(f"Weaviate orphans: {len(report.weaviate_orphans)}")
print(f"MinIO orphans: {len(report.minio_orphans)}")
print(f"Neo4j orphans: {len(report.neo4j_orphans)}")
```

Orphan detection is read-only and safe to run at any time. If orphans are found, run a
manual GC with `--mode hard --confirm` after confirming the orphans are not from
in-flight ingestions.

---

## 4. Extension Guide

### 4.1 Adding a New Store to GC

Suppose you add a fifth storage backend (e.g., an Elasticsearch index). Here is how to
integrate it into GC:

**Step 1:** Add a cleanup method to the new store's module:

```python
# src/search/elasticsearch.py (example)

def soft_delete_by_source_key(client, source_key: str) -> int:
    """Mark documents as deleted in Elasticsearch."""
    ...

def delete_by_source_key(client, source_key: str) -> int:
    """Hard-delete documents from Elasticsearch."""
    ...

def list_source_keys(client) -> list[str]:
    """List all distinct source_keys in the index."""
    ...
```

**Step 2:** Extend `StoreCleanupStatus` in `src/ingest/lifecycle/schemas.py`:

```python
@dataclass
class StoreCleanupStatus:
    weaviate: bool = True
    minio: bool = True
    neo4j: bool = True
    manifest: bool = True
    elasticsearch: bool = True    # NEW
    errors: list[str] = field(default_factory=list)
```

**Step 3:** Add a cleanup block in `reconcile_deleted()` in `src/ingest/lifecycle/gc.py`,
following the same try/except pattern as the existing stores:

```python
# -- Elasticsearch cleanup --
if elasticsearch_client is not None:
    try:
        if mode == "soft":
            soft_delete_by_source_key(elasticsearch_client, source_key)
        else:
            delete_by_source_key(elasticsearch_client, source_key)
        status.elasticsearch = True
    except Exception as exc:
        status.elasticsearch = False
        status.errors.append(f"elasticsearch: {exc}")
        logger.error("gc_elasticsearch_failed source_key=%s mode=%s error=%s",
                      source_key, mode, exc)
```

**Step 4:** Add an orphan detection block in `detect_orphans()` in
`src/ingest/lifecycle/orphan_report.py`:

```python
# Extend OrphanReport with elasticsearch_orphans: list[str]
if elasticsearch_client is not None:
    try:
        es_keys = set(list_source_keys(elasticsearch_client))
        report.elasticsearch_orphans = sorted(es_keys - manifest_keys)
    except Exception as exc:
        logger.warning("orphan_detect_elasticsearch_failed error=%s", exc)
```

**Step 5:** Add a validation check in `validate_document()` in
`src/ingest/lifecycle/validation.py` if the new store should participate in E2E
validation.

### 4.2 Adding a New Migration Strategy

The migration runner currently supports four strategies: `none`, `metadata_only`,
`full_phase2`, and `kg_reextract`. To add a new one (e.g., `reindex_search`):

**Step 1:** Add the strategy to `_STRATEGY_ORDER` in `src/ingest/lifecycle/changelog.py`:

```python
_STRATEGY_ORDER = {
    "none": 0,
    "metadata_only": 1,
    "kg_reextract": 2,
    "reindex_search": 3,       # NEW -- between kg_reextract and full_phase2
    "full_phase2": 4,          # bump rank if new strategy is less expensive
}
```

The rank determines strategy escalation: when a version jump crosses multiple changelog
entries, `determine_migration_strategy()` returns the strategy with the highest rank.
Position the new strategy correctly relative to cost.

**Step 2:** Add a handler in `run_migration()` in `src/ingest/lifecycle/migration.py`:

```python
elif strategy == "reindex_search":
    _migrate_reindex_search(key, entry, target, runtime, minio_clean_store)
```

**Step 3:** Implement the handler function:

```python
def _migrate_reindex_search(
    source_key: str,
    entry: ManifestEntry,
    target_version: str,
    runtime: Any,
    minio_clean_store: Any,
) -> None:
    """Re-index clean markdown into search backend without re-embedding."""
    text, meta = minio_clean_store.read(source_key)
    # ... your re-indexing logic ...
```

**Step 4:** Use the new strategy in `config/schema_changelog.yaml`:

```yaml
  - version: "1.3.0"
    date: "2026-06-15"
    description: "Added Elasticsearch search index."
    migration_strategy: "reindex_search"
```

### 4.3 Adding New Manifest Fields

The manifest schema is designed for forward-compatible evolution. All fields are
`total=False` (optional) in the `ManifestEntry` TypedDict.

**Step 1:** Add the field to `ManifestEntry` in `src/ingest/common/schemas.py`:

```python
class ManifestEntry(TypedDict, total=False):
    # ... existing fields ...
    my_new_field: str     # Brief description and FR reference
```

**Step 2:** Add a `.setdefault()` in `_normalize_manifest_entries()` in
`src/ingest/impl.py` so that old manifests load cleanly:

```python
entry.setdefault("my_new_field", "")
```

**Step 3:** Populate the field in the manifest write block in `ingest_directory()`:

```python
manifest[source_key] = {
    # ... existing fields ...
    "my_new_field": result.my_new_field,
}
```

**Step 4:** If the field is relevant to migration, bump `PIPELINE_SCHEMA_VERSION` and add
a changelog entry.

**Critical rule:** All code that reads manifest entries MUST use `.get()` with explicit
defaults for new fields. Never assume a field is present.

---

## 5. Troubleshooting

### 5.1 Common Failure Modes

**Problem: MinIO clean store write fails but ingestion succeeds.**
The orchestrator catches MinIO write failures and logs
`minio_clean_store_write_failed`. The in-memory handoff to Phase 2 still works, so
the document is ingested correctly. However, this document will not be available for
`full_phase2` migration later (the migration runner reads from MinIO).
**Fix:** Check MinIO connectivity/credentials. Re-ingest the document when MinIO is
healthy -- the MinIO write will succeed on the next run.

**Problem: E2E validation reports inconsistency for Neo4j but KG is enabled.**
This means Phase 2 completed but `count_triples_by_trace_id` returned 0.
**Common causes:** (a) The KG extraction node silently failed (check logs for
the trace_id). (b) Neo4j was temporarily unreachable during Phase 2 write.
(c) The document had no extractable entities (valid -- check if this is expected
for the document type).
**Fix:** Re-ingest the document. If the problem persists, check Neo4j connectivity
and the KG extraction node logs.

**Problem: GC reports store-level failures (e.g., `gc_neo4j_failed`).**
GC isolates store failures. The other three stores were still cleaned.
**Fix:** Check the failing store's connectivity. Run GC again -- it will retry
the failed cleanup. For Neo4j failures, orphaned triples remain until the next
successful GC run.

**Problem: Migration runner fails on `full_phase2` with "clean markdown not found in MinIO."**
The document was ingested before the MinIO clean store was deployed, or the MinIO
write failed during original ingestion.
**Fix:** Re-ingest the document from source. This will write to MinIO and update
the schema version in one pass.

**Problem: Manifest has entries with `deleted_at` but `deleted=False`.**
This is an inconsistent state, likely from a manual manifest edit or a bug.
**Fix:** If the document should be deleted, set `deleted=True`. If it should be
active, clear `deleted_at` to `""`.

### 5.2 Diagnostic Commands

**Check manifest health:**

```python
from src.ingest.common.utils import load_manifest

m = load_manifest("processed/manifest.json")
total = len(m)
deleted = sum(1 for v in m.values() if v.get("deleted", False))
no_version = sum(1 for v in m.values() if v.get("schema_version", "0.0.0") == "0.0.0")
no_trace = sum(1 for v in m.values() if not v.get("trace_id"))
inconsistent = sum(1 for v in m.values()
                   if v.get("validation", {}).get("consistent") is False)

print(f"Total entries:        {total}")
print(f"Active:               {total - deleted}")
print(f"Soft-deleted:         {deleted}")
print(f"Pre-versioned (0.0.0):{no_version}")
print(f"Missing trace_id:     {no_trace}")
print(f"Inconsistent (E2E):   {inconsistent}")
```

**Inspect a single document across all stores:**

```python
source_key = "local_fs:reports/Q1_2025.pdf"
trace_id = m[source_key].get("trace_id", "")

# Manifest
print(f"Manifest: schema={m[source_key].get('schema_version')} "
      f"deleted={m[source_key].get('deleted')} trace={trace_id}")

# Weaviate
from src.vector_db import count_by_trace_id
print(f"Weaviate chunks: {count_by_trace_id(client, trace_id)}")

# MinIO
from src.ingest.common.minio_clean_store import MinioCleanStore
store = MinioCleanStore(db_client, "my-bucket")
print(f"MinIO exists: {store.exists(source_key)}")

# Neo4j
if kg_builder:
    print(f"Neo4j triples: {kg_builder.count_triples_by_trace_id(trace_id)}")
```

**List all orphans:**

```python
from src.ingest.lifecycle.orphan_report import detect_orphans

report = detect_orphans(m, client, db_client, "my-bucket", kg_builder)
for store, orphans in [
    ("Weaviate", report.weaviate_orphans),
    ("MinIO", report.minio_orphans),
    ("Neo4j", report.neo4j_orphans),
]:
    if orphans:
        print(f"\n{store} orphans ({len(orphans)}):")
        for key in orphans[:20]:
            print(f"  {key}")
```

### 5.3 Recovery Procedures

**Recovering a soft-deleted document** (within the retention window):

```python
# 1. Set deleted=False and clear deleted_at
manifest[source_key]["deleted"] = False
manifest[source_key]["deleted_at"] = ""

# 2. Restore MinIO objects (move from deleted/ back to clean/)
# This is the reverse of soft_delete -- currently manual:
from minio.commonconfig import CopySource
safe = source_key.replace("/", "_")  # simplified; use _safe_key() in practice
for suffix in (".md", ".meta.json"):
    db_client.copy_object("my-bucket", f"clean/{safe}{suffix}",
                          CopySource("my-bucket", f"deleted/{safe}{suffix}"))
    db_client.remove_object("my-bucket", f"deleted/{safe}{suffix}")

# 3. Restore Weaviate chunks (un-set deleted flag)
from src.vector_db import batch_update_metadata_by_source_key
batch_update_metadata_by_source_key(client, source_key, {"deleted": False})

# 4. Restore Neo4j triples (un-set deleted flag)
if kg_builder:
    # Neo4j restore depends on your soft-delete implementation
    pass

# 5. Save manifest
from src.ingest.common.utils import save_manifest
save_manifest("processed/manifest.json", manifest)
```

**Full re-ingestion of a single document:**

```python
from src.ingest.impl import ingest_file

result = ingest_file(
    source_path=Path("documents/my_doc.pdf"),
    runtime=runtime,
    source_name="my_doc.pdf",
    source_uri="file:///documents/my_doc.pdf",
    source_key="local_fs:my_doc.pdf",
    source_id="abc123",
    connector="local_fs",
    source_version="1",
)
print(f"Trace ID: {result.trace_id}")
print(f"Consistent: {result.validation.get('consistent')}")
```

---

## 6. Testing Guide

### 6.1 Critical Test Scenarios (12)

These are the tests that must pass before shipping any change to the lifecycle subsystem.

| # | Scenario | Module | What it verifies |
|---|----------|--------|-----------------|
| 1 | **MinIO clean store round-trip** | `minio_clean_store.py` | `write()` then `read()` returns identical text and metadata. Content types are `text/markdown` and `application/json`. `.meta.json` is the commit marker (written last). |
| 2 | **Manifest backward compatibility** | `schemas.py`, `impl.py` | Load a manifest written by the pre-lifecycle pipeline (no `schema_version`, `trace_id`, etc.). All new fields resolve to safe defaults. No errors. |
| 3 | **Trace ID propagation end-to-end** | `impl.py`, state files | `ingest_file()` generates a UUID v4, passes it to Phase 1 state, Phase 2 state, MinIO metadata, Weaviate chunk metadata, Neo4j triple metadata, and manifest entry. All locations contain the same trace_id. |
| 4 | **Sync diff correctness** | `sync.py` | Given a source directory with 3 new files, 2 modified files, and 1 deleted file relative to the manifest, `diff_sources()` returns correct `SyncResult` counts and lists. |
| 5 | **Four-store soft delete** | `gc.py` | `reconcile_deleted()` in soft mode: Weaviate `soft_delete_by_source_key` called, MinIO `soft_delete` called, Neo4j `soft_delete_by_source_key` called, manifest entry has `deleted=True` and `deleted_at` set. |
| 6 | **Four-store hard delete** | `gc.py` | `reconcile_deleted()` in hard mode: Weaviate `delete_by_source_key` called, MinIO `delete` called, Neo4j `delete_by_source_key` called, manifest entry removed. |
| 7 | **GC store failure isolation** | `gc.py` | Weaviate raises an exception during soft delete. Verify: MinIO, Neo4j, and manifest are still cleaned. `StoreCleanupStatus.weaviate=False`, others `True`. Error is logged. |
| 8 | **Retention purge window** | `gc.py` | Soft-delete a document with `deleted_at` = 45 days ago. Call `purge_expired(retention_days=30)`. Verify hard-deleted. Soft-delete another document with `deleted_at` = 10 days ago. Verify NOT purged. |
| 9 | **E2E validation -- all stores pass** | `validation.py` | Mock all store queries to return positive results. `validate_document()` returns `consistent=True` with all `*_ok=True`. |
| 10 | **E2E validation -- KG disabled** | `validation.py` | Call `validate_document()` with `kg_enabled=False`. Verify `neo4j_ok=None` (not False). Document is still `consistent=True` if Weaviate and MinIO pass. |
| 11 | **Migration strategy determination** | `changelog.py` | Load a changelog with entries at 0.0.0 (none), 1.0.0 (metadata_only), 1.1.0 (kg_reextract), 1.2.0 (full_phase2). Verify: `determine_migration_strategy("0.0.0", "1.2.0")` returns `full_phase2` (highest rank in range). `determine_migration_strategy("1.0.0", "1.1.0")` returns `kg_reextract`. |
| 12 | **Migration idempotency** | `migration.py` | Run `run_migration()` on a manifest where all documents are already at the target version. Verify: `MigrationResult.processed=0`, `skipped=N`, no store writes. Run again on a partially migrated manifest. Verify: only unmigrated documents are processed. |

### 6.2 Test Fixtures and Helpers

**Mock MinIO client:**

```python
class MockMinioClient:
    """In-memory MinIO client for unit tests."""

    def __init__(self):
        self._objects: dict[str, tuple[bytes, str]] = {}  # key -> (data, content_type)

    def put_object(self, bucket, key, data, length, content_type=""):
        self._objects[key] = (data.read(), content_type)

    def get_object(self, bucket, key):
        if key not in self._objects:
            raise Exception(f"NoSuchKey: {key}")
        return MockResponse(self._objects[key][0])

    def stat_object(self, bucket, key):
        if key not in self._objects:
            raise Exception(f"NoSuchKey: {key}")

    def remove_object(self, bucket, key):
        self._objects.pop(key, None)

    def list_objects(self, bucket, prefix="", recursive=False):
        return [MockObject(k) for k in self._objects if k.startswith(prefix)]

    def copy_object(self, bucket, dest_key, source):
        src_key = source._source_key  # depends on CopySource mock
        if src_key in self._objects:
            self._objects[dest_key] = self._objects[src_key]


class MockResponse:
    def __init__(self, data: bytes):
        self._data = data
    def read(self):
        return self._data
    def close(self):
        pass
    def release_conn(self):
        pass


class MockObject:
    def __init__(self, name: str):
        self.object_name = name
```

**Sample manifest fixture:**

```python
import pytest

@pytest.fixture
def sample_manifest():
    """Manifest with a mix of versioned, pre-versioned, and deleted entries."""
    return {
        "local_fs:doc_a.pdf": {
            "source": "doc_a.pdf",
            "source_key": "local_fs:doc_a.pdf",
            "content_hash": "aaa111",
            "schema_version": "1.0.0",
            "trace_id": "aaaa-bbbb-cccc-dddd",
            "deleted": False,
            "deleted_at": "",
            "validation": {"consistent": True},
            "clean_hash": "ccc333",
        },
        "local_fs:doc_b.pdf": {
            "source": "doc_b.pdf",
            "source_key": "local_fs:doc_b.pdf",
            "content_hash": "bbb222",
            # No schema_version -- pre-lifecycle document
        },
        "local_fs:doc_deleted.pdf": {
            "source": "doc_deleted.pdf",
            "source_key": "local_fs:doc_deleted.pdf",
            "content_hash": "ddd444",
            "schema_version": "1.0.0",
            "deleted": True,
            "deleted_at": "2026-03-01T00:00:00+00:00",
        },
    }
```

**Schema changelog fixture:**

```python
@pytest.fixture
def sample_changelog(tmp_path):
    """Write a test changelog and return its path."""
    content = """
schema_versions:
  - version: "0.0.0"
    date: "2026-01-01"
    description: "Pre-versioning baseline."
    migration_strategy: "none"
  - version: "1.0.0"
    date: "2026-04-15"
    description: "Initial versioned schema."
    migration_strategy: "metadata_only"
  - version: "1.1.0"
    date: "2026-05-01"
    description: "KG extraction logic changed."
    migration_strategy: "kg_reextract"
"""
    path = tmp_path / "schema_changelog.yaml"
    path.write_text(content)
    return path
```

### 6.3 Integration Test Setup

Integration tests require running instances of Weaviate, MinIO, and optionally Neo4j.
Use docker-compose for the test environment:

```yaml
# docker-compose.test.yaml (relevant services)
services:
  weaviate:
    image: semitechnologies/weaviate:1.24.0
    ports: ["8080:8080"]
    environment:
      QUERY_DEFAULTS_LIMIT: 25
      AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED: "true"

  minio:
    image: minio/minio:latest
    ports: ["9000:9000"]
    command: server /data
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin

  neo4j:
    image: neo4j:5.18
    ports: ["7474:7474", "7687:7687"]
    environment:
      NEO4J_AUTH: "neo4j/testpassword"
```

**Integration test structure:**

```python
# tests/ingest/lifecycle/test_gc_integration.py

@pytest.mark.integration
class TestGCIntegration:
    """Integration tests requiring live Weaviate + MinIO."""

    def test_on_ingest_gc_four_store_cleanup(
        self, weaviate_client, minio_client, sample_docs
    ):
        """Ingest 3 docs, delete 1 from source dir, run update=True.
        Verify all 4 stores are cleaned for the deleted doc."""
        # 1. Ingest all 3 documents
        # 2. Delete source file for doc_c
        # 3. Run ingest_directory(update=True)
        # 4. Assert: Weaviate has no chunks for doc_c
        # 5. Assert: MinIO has no clean/ objects for doc_c
        # 6. Assert: Manifest entry for doc_c has deleted=True
        ...

    def test_migration_metadata_only_does_not_reembed(
        self, weaviate_client, minio_client
    ):
        """Ingest a doc at schema 1.0.0. Run metadata_only migration to 1.1.0.
        Verify: Weaviate chunk embeddings are unchanged; only metadata updated."""
        # 1. Ingest document
        # 2. Record original embedding vectors
        # 3. Run migration to 1.1.0 (metadata_only)
        # 4. Assert: embeddings are byte-identical
        # 5. Assert: schema_version metadata is "1.1.0"
        ...
```

**Running integration tests:**

```bash
# Start test infrastructure
docker-compose -f docker-compose.test.yaml up -d

# Run lifecycle integration tests
pytest tests/ingest/lifecycle/ -m integration -v

# Teardown
docker-compose -f docker-compose.test.yaml down
```
