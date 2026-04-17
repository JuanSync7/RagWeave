# Data Lifecycle Engineering Guide

| Field | Value |
|-------|-------|
| **Subsystem** | Data Lifecycle |
| **Status** | Authoritative (post-implementation) |
| **Spec** | `DATA_LIFECYCLE_SPEC.md` (FR-3000–FR-3114, NFR-3180–NFR-3230) |
| **Implementation doc** | `DATA_LIFECYCLE_IMPLEMENTATION.md` |
| **Last updated** | 2026-04-17 |

---

## 1. Overview

The Data Lifecycle subsystem provides the complete data-management layer for
the RagWeave ingestion pipeline. It governs how documents are tracked,
reclaimed, versioned, and validated across four storage backends: Weaviate
(vector chunks), MinIO (clean document store), Neo4j (knowledge graph triples),
and the JSON manifest.

### Functional requirements covered

| FR | Title |
|----|-------|
| FR-3000 | Four-store inventory enumeration |
| FR-3001 | Garbage collection |
| FR-3002 | Orphan detection |
| FR-3010 | Soft delete |
| FR-3020 | Soft-delete retention window |
| FR-3022 | Expired-entry purge |
| FR-3030–FR-3034 | MinIO clean document store |
| FR-3050 | Trace ID per ingestion run |
| FR-3053 | Batch ID grouping |
| FR-3060–FR-3062 | E2E cross-store consistency validation |
| FR-3100 | Pipeline schema version constant |
| FR-3110–FR-3114 | Schema migration runner |

### Non-functional requirements covered

| NFR | Title |
|-----|-------|
| NFR-3181 | Migration throughput (≥ 100 docs/sec for `metadata_only`) |
| NFR-3210 | Store-level failure isolation |
| NFR-3211 | Migration resumability (incremental manifest updates) |
| NFR-3221 | Audit log for every GC operation |
| NFR-3230 | Double-confirmation guard for hard delete |

---

## 2. Module Layout

```
src/ingest/lifecycle/
├── __init__.py          # Public API surface — all consumer imports land here
├── schemas.py           # Typed dataclass contracts (no Pydantic)
├── sync.py              # SyncEngine: read-only four-store inventory + diff
├── gc.py                # GCEngine + run_gc_cli()
├── migration.py         # MigrationEngine + run_migration_cli()
├── changelog.py         # Changelog YAML parser + strategy resolver
├── validation.py        # E2EValidator + run_validation_cli()
└── orphan_report.py     # format_text() / format_json() report formatters

src/ingest/common/
├── minio_clean_store.py # MinioCleanStore (write/read/exists/delete/soft_delete/list_keys)
└── schemas.py           # ManifestEntry TypedDict + PIPELINE_SCHEMA_VERSION

config/
└── schema_changelog.yaml  # Machine-readable schema version history
```

### Public exports from `src.ingest.lifecycle`

```python
from src.ingest.lifecycle import (
    # Engines
    GCEngine,
    SyncEngine,
    MigrationEngine,
    E2EValidator,
    # GC / Sync schemas
    GCReport,
    LifecycleConfig,
    OrphanReport,
    StoreCleanupStatus,
    StoreInventory,
    SyncResult,
    # Migration schemas
    MigrationPlan,
    MigrationReport,
    MigrationTask,
    # Validation schemas
    ValidationReport,
    ValidationFinding,
    # Changelog
    SchemaVersion,
    MigrationStrategy,
    load_changelog,
    # Factories
    build_gc_engine,
    build_sync_engine,
)
```

---

## 3. Key Abstractions

### 3.1 `SyncEngine` — four-store inventory and orphan detection

`src/ingest/lifecycle/sync.py`

```python
class SyncEngine:
    def __init__(
        self,
        manifest: dict[str, ManifestEntry],
        weaviate_client: Any,
        minio_client: Optional[Any] = None,
        minio_bucket: str = "",
        neo4j_client: Optional[Any] = None,
        collection: Optional[str] = None,
    ) -> None: ...

    def inventory(self) -> StoreInventory: ...
    # Enumerate all four stores. Errors per store are captured in *_error
    # fields; they never propagate to the caller. The engine never mutates
    # any store.

    def diff(self, inventory: StoreInventory) -> OrphanReport: ...
    # Set-diff the inventory against the manifest:
    #   weaviate_orphans: in Weaviate but not in manifest
    #   minio_orphans:    in MinIO but not in manifest
    #   neo4j_orphans:    in Neo4j but not in manifest
    #   manifest_only:    in manifest but in no live store (GC candidates)
    # All lists are sorted lexicographically.
```

`SyncEngine` is stateless and read-only. Weaviate enumeration calls
`src.vector_db.aggregate_by_source`; MinIO enumeration delegates to
`MinioCleanStore.list_keys()`; Neo4j enumeration calls
`neo4j_client.list_source_keys()` (gracefully skipped if the method is absent).

### 3.2 `GCEngine` — four-store garbage collection

`src/ingest/lifecycle/gc.py`

```python
class GCEngine:
    def __init__(
        self,
        manifest: dict[str, ManifestEntry],
        weaviate_client: Any,
        minio_client: Optional[Any] = None,
        minio_bucket: str = "",
        neo4j_client: Optional[Any] = None,
        retention_days: int = 30,
        collection: Optional[str] = None,
    ) -> None: ...

    def collect(
        self,
        report: OrphanReport,
        mode: str = "soft",
        dry_run: bool = False,
        confirm: bool = False,
        cli_confirmed: bool = False,
    ) -> GCReport: ...
    # Run GC on report.manifest_only keys.
    # Hard delete requires both confirm=True AND cli_confirmed=True (NFR-3230).

    def collect_keys(
        self,
        keys: list[str],
        mode: str = "soft",
        dry_run: bool = False,
        confirm: bool = False,
        cli_confirmed: bool = False,
    ) -> GCReport: ...
    # Lower-level variant — accepts an explicit key list.

    def purge_expired(self, dry_run: bool = False) -> int: ...
    # Hard-delete soft-deleted entries past their retention window (FR-3022).
    # Scans manifest for deleted==True AND deleted_at < now - retention_days.
    # Bypasses the CLI confirmation sentinel (internal scheduled purge).
```

**Delete modes:**

| Mode | Weaviate | MinIO | Neo4j | Manifest |
|------|----------|-------|-------|----------|
| `soft` | `soft_delete_by_source_key()` (skipped if not in facade) | `store.soft_delete()` — moves to `deleted/` prefix | `soft_delete_by_source_key()` (falls back to `remove_by_source`) | `deleted=True`, `deleted_at=<iso>` |
| `hard` | `delete_by_source_key()` | `store.delete()` | `delete_by_source_key()` (falls back to `remove_by_source`) | `manifest.pop(key)` |

**Guard (NFR-3230):** `_require_hard_delete_confirmation(confirm, cli_confirmed)` raises
`PermissionError` unless both flags are `True`.

**Store isolation (NFR-3210):** Each per-store cleanup step is wrapped in its own
`try/except`. A failure in one store is recorded in `StoreCleanupStatus.errors`
but does not prevent cleanup of the remaining stores.

**Audit log (NFR-3221):** Every live GC operation emits a structured `logger.info`
line at the `INFO` level:

```
gc_operation source_key=<key> mode=<mode> weaviate=<bool> minio=<bool>
             neo4j=<bool> manifest=<bool> errors=<count>
```

### 3.3 `MigrationEngine` — per-trace_id schema migration

`src/ingest/lifecycle/migration.py`

```python
class MigrationEngine:
    def __init__(
        self,
        client: Any,                           # Weaviate client
        manifest_path: Optional[str | Path] = None,
        clean_store: Optional[Any] = None,     # MinioCleanStore (full_phase2, kg_reextract)
        vector_db: Optional[Any] = None,       # injected for testing; lazy-imported otherwise
        kg_client: Optional[Any] = None,       # KG backend (kg_reextract)
        changelog: Optional[list[SchemaVersion]] = None,
        changelog_path: str | Path = "config/schema_changelog.yaml",
    ) -> None: ...

    def plan(
        self,
        from_version: str,
        to_version: str,
        manifest: Optional[dict[str, ManifestEntry]] = None,
    ) -> MigrationPlan: ...
    # Dry-run: identify entries that need migration. Does NOT mutate any store.
    # Pass from_version="" to use each entry's own schema_version field.

    def execute(
        self,
        plan: MigrationPlan,
        *,
        confirm: bool = False,
        manifest: Optional[dict[str, ManifestEntry]] = None,
    ) -> MigrationReport: ...
    # Execute migrations. Requires confirm=True (PermissionError otherwise).
    # Per-entry isolation: one failure never halts the batch.
    # Manifest is updated incrementally for resumability (NFR-3211).
```

**Migration strategies (FR-3111):**

| Strategy | What it does | Cost |
|----------|-------------|------|
| `none` | No action; entry skipped | Free |
| `metadata_only` | Weaviate `batch_update_metadata_by_source_key` | Cheap |
| `kg_reextract` | Delete old KG triples + re-run `kg_client.extract_from_text()` | LLM-bound |
| `full_phase2` | Read from MinIO, delete old chunks, re-run embedding pipeline | GPU-bound |

The most expensive strategy in a version range wins (determined by
`determine_migration_strategy(from_version, to_version, changelog)`).

**Idempotency (FR-3112):** Entries already at `to_version` are skipped inside
`execute()` even if the plan includes them (e.g., from a resumed run).

**Resumability (NFR-3211):** On each successful entry, `entry["schema_version"]`
is updated immediately before moving to the next entry. Interrupted runs can be
safely re-started.

### 3.4 `E2EValidator` — cross-store consistency validation

`src/ingest/lifecycle/validation.py`

```python
class E2EValidator:
    def __init__(
        self,
        client: Any,                         # Weaviate client
        minio: Optional[Any] = None,         # MinioCleanStore (None = disabled)
        kg: Optional[Any] = None,            # KG client (None = disabled)
        manifest_path: Optional[str] = None,
        collection: Optional[str] = None,
    ) -> None: ...

    def validate_by_trace_id(
        self,
        trace_id: str,
        manifest: Optional[dict] = None,
    ) -> ValidationReport: ...
    # Validate a single trace_id across all four stores.

    def validate_all(
        self,
        *,
        sample_size: Optional[int] = None,
        manifest: Optional[dict] = None,
    ) -> ValidationReport: ...
    # Validate all (or a random sample of) non-deleted entries
    # that have a non-empty trace_id.
```

Disabled stores (`minio=None`, `kg=None`) are reported as `None` in
`ValidationFinding` (not `False`). This distinguishes "not configured" from
"configured but missing data" (FR-3062). A `None` store is excluded from the
overall consistency check.

### 3.5 `MinioCleanStore` — durable Phase 1 output store

`src/ingest/common/minio_clean_store.py`

```python
class MinioCleanStore:
    def __init__(self, client: Any, bucket: str) -> None: ...

    def write(self, source_key: str, text: str, meta: dict[str, Any]) -> None: ...
    # Write .md (first) then .meta.json (commit marker). FR-3033 AC4.

    def read(self, source_key: str) -> tuple[str, dict[str, Any]]: ...
    # Return (clean_markdown_text, metadata_dict).

    def exists(self, source_key: str) -> bool: ...
    # Check presence of .meta.json commit marker.

    def delete(self, source_key: str) -> None: ...
    # Hard-delete both .md and .meta.json. Tolerates missing objects.

    def soft_delete(self, source_key: str) -> None: ...
    # Copy to deleted/ prefix then remove from clean/. FR-3020.

    def list_keys(self) -> list[str]: ...
    # Enumerate safe_keys from .meta.json objects under clean/.
```

**Object key layout:**

```
clean/{safe_key}.md           — clean markdown (written first)
clean/{safe_key}.meta.json    — metadata envelope, commit marker
deleted/{safe_key}.md         — tombstone after soft_delete()
deleted/{safe_key}.meta.json  — tombstone after soft_delete()
```

`_safe_key(source_key)` replaces the characters `/ \\ : * ? " < > |` with `_`
and `..` with `__`.

### 3.6 Changelog types

`src/ingest/lifecycle/changelog.py`

```python
class MigrationStrategy(str, Enum):
    NONE = "none"
    METADATA_ONLY = "metadata_only"
    KG_REEXTRACT = "kg_reextract"
    FULL_PHASE2 = "full_phase2"

@dataclass(frozen=True)
class SchemaVersion:
    version: str
    date: str
    description: str
    migration_strategy: str
    fields_added: list[str]
    fields_removed: list[str]
    fields_renamed: dict[str, str]

def load_changelog(path: str | Path = "config/schema_changelog.yaml") -> list[SchemaVersion]: ...
def get_required_migrations(from_version, to_version, changelog) -> list[SchemaVersion]: ...
def determine_migration_strategy(from_version, to_version, changelog) -> str: ...
```

Strategy cost ranking (ascending):
`none(0)` < `metadata_only(1)` < `kg_reextract(2)` < `full_phase2(3)`.

`determine_migration_strategy` returns the highest-ranked strategy across all
intermediate versions in the range `(from_version, to_version]`.

### 3.7 Schema contracts

All types in `src/ingest/lifecycle/schemas.py` are plain dataclasses (no Pydantic):

| Dataclass | Purpose |
|-----------|---------|
| `StoreInventory` | Key sets from all four stores plus per-store error fields |
| `OrphanReport` | Per-store orphan lists plus `manifest_only` list |
| `SyncResult` | Source-to-manifest diff (added/modified/deleted/unchanged) |
| `StoreCleanupStatus` | Per-source-key per-store cleanup outcome (bool fields + errors list) |
| `GCReport` | Aggregate GC result (soft_deleted, hard_deleted, retention_purged, per_document, dry_run) |
| `LifecycleConfig` | Lightweight config container |
| `MigrationTask` | Single per-entry migration sub-task |
| `MigrationPlan` | Dry-run plan (to_version, tasks, skipped_count) |
| `MigrationReport` | Execution result (total_eligible, succeeded, failed, skipped, per_entry) |
| `ValidationFinding` | Per-trace_id per-store finding with chunk/triple counts |
| `ValidationReport` | Aggregate validation result |

`src/ingest/common/schemas.py` carries the manifest extension:

```python
PIPELINE_SCHEMA_VERSION: str = "1.0.0"  # single source of truth (FR-3100 AC4)

class ManifestEntry(TypedDict, total=False):
    # ... pre-existing fields (source, source_uri, content_hash, etc.) ...
    schema_version: str     # FR-3100 — e.g. "1.0.0"
    trace_id: str           # FR-3050 — UUID v4 per ingestion run
    batch_id: str           # FR-3053 — optional batch grouping ID
    deleted: bool           # FR-3020 — True if soft-deleted
    deleted_at: str         # FR-3020 — ISO 8601 timestamp
    validation: dict        # FR-3061 — E2E validation result
    clean_hash: str         # SHA-256 of clean markdown output
```

---

## 4. Data Flow

### 4.1 On-ingest path

1. The ingestion pipeline (`impl.py`) generates a UUID v4 `trace_id` per run.
2. Phase 1 writes clean markdown and a metadata envelope to MinIO via
   `MinioCleanStore.write()`. The `.meta.json` commit marker is written last
   (FR-3033 AC4).
3. Phase 2 embeds chunks into Weaviate with `trace_id`, `schema_version`, and
   `batch_id` in chunk metadata.
4. The manifest is updated with all new lifecycle fields.

### 4.2 Orphan detection and GC

```
SyncEngine.inventory()
    ├── manifest: include only entries where deleted != True
    ├── Weaviate: src.vector_db.aggregate_by_source() → set[source_key]
    ├── MinIO: MinioCleanStore.list_keys() → list[safe_key]
    └── Neo4j: neo4j_client.list_source_keys() → list[source_key]
    → StoreInventory  (errors captured, never raised)

SyncEngine.diff(inventory)
    ├── weaviate_keys - manifest_keys → weaviate_orphans
    ├── minio_keys    - manifest_keys → minio_orphans
    ├── neo4j_keys    - manifest_keys → neo4j_orphans
    └── manifest_keys - (all store keys) → manifest_only
    → OrphanReport  (all lists sorted lexicographically)

GCEngine.collect(orphan_report, mode="soft")
    └── for key in orphan_report.manifest_only:
        ├── _cleanup_weaviate(key, mode)   ← isolated try/except
        ├── _cleanup_minio(key, mode)      ← isolated try/except (if minio_client)
        ├── _cleanup_neo4j(key, mode)      ← isolated try/except (if neo4j_client)
        └── _cleanup_manifest(key, mode)   ← sets deleted/deleted_at or pops key
        → StoreCleanupStatus per key
    → GCReport

GCEngine.purge_expired()
    └── scan manifest for deleted==True AND deleted_at < now - retention_days
    └── hard-delete each expired key (same per-store isolation, no CLI sentinel)
    → purged_count (int)
```

### 4.3 Schema migration

```
load_changelog("config/schema_changelog.yaml")
    → list[SchemaVersion]

MigrationEngine.plan(from_version, to_version, manifest)
    └── for each non-deleted entry:
        ├── effective_from = from_version or entry["schema_version"] or "0.0.0"
        ├── determine_migration_strategy(effective_from, to_version, changelog)
        └── skip if strategy=="none" or effective_from==to_version
    → MigrationPlan (tasks list + skipped_count)

MigrationEngine.execute(plan, confirm=True, manifest)
    └── for each MigrationTask:
        ├── skip if entry already at to_version (idempotency, FR-3112)
        ├── _run_strategy(task, entry):
        │   ├── metadata_only  → batch_update_metadata_by_source_key on Weaviate
        │   ├── full_phase2    → read MinIO + delete old chunks + run_embedding_pipeline
        │   └── kg_reextract   → delete old triples + kg_client.extract_from_text()
        ├── on success: entry["schema_version"] = to_version  ← NFR-3211
        └── on failure: record error, continue  ← per-entry isolation
    → MigrationReport
```

### 4.4 E2E validation

```
E2EValidator.validate_by_trace_id(trace_id, manifest)
    ├── find source_key in manifest by trace_id scan
    ├── Weaviate: count_by_trace_id() → int or None on error
    ├── MinIO:    store.exists(source_key) → bool (None if minio disabled)
    ├── Neo4j:    kg.count_triples_by_trace_id() → int (None if kg disabled)
    └── Manifest: presence of source_key
    └── consistent = manifest_ok AND weaviate_ok AND all(enabled store flags)
    → ValidationReport (1 finding)

E2EValidator.validate_all(sample_size=N, manifest)
    ├── collect (trace_id, source_key) for non-deleted entries with trace_id
    ├── optional random.sample(candidates, N)
    └── run _check_single() for each candidate
    → ValidationReport (N findings)
```

---

## 5. Configuration

### Settings (`config/settings.py`)

The CLI entry points read the following settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `RAG_GC_MODE` | `"soft"` | Default delete mode (`"soft"` or `"hard"`) |
| `RAG_GC_RETENTION_DAYS` | `30` | Retention window in days for soft-deleted entries |
| `RAG_GC_SCHEDULE` | `""` | Cron expression for scheduled GC (empty = disabled) |
| `MINIO_ENDPOINT` | — | MinIO server address (host:port) |
| `MINIO_ACCESS_KEY` | — | MinIO access key |
| `MINIO_SECRET_KEY` | — | MinIO secret key |
| `MINIO_SECURE` | `False` | Use HTTPS for MinIO connections |
| `MINIO_BUCKET` | — | Target MinIO bucket name |

### `LifecycleConfig` dataclass

```python
@dataclass
class LifecycleConfig:
    gc_mode: str = "soft"
    gc_retention_days: int = 30
    gc_schedule: str = ""
    minio_bucket: str = ""
```

### Schema changelog (`config/schema_changelog.yaml`)

```yaml
# Required top-level key:
schema_versions:
  - version: "0.0.0"            # must be present as the baseline
    date: "2026-01-01"
    description: "Pre-versioning baseline."
    migration_strategy: "none"
    fields_added: []
    fields_removed: []
    fields_renamed: []

  - version: "1.0.0"
    date: "2026-04-15"
    description: "Initial versioned schema."
    migration_strategy: "metadata_only"
    fields_added: ["trace_id", "batch_id", "schema_version", ...]
    fields_removed: []
    fields_renamed: []
```

Valid `migration_strategy` values: `none`, `metadata_only`, `kg_reextract`,
`full_phase2`. Any other value causes `load_changelog()` to raise `ValueError`.

`PIPELINE_SCHEMA_VERSION` in `src/ingest/common/schemas.py` must always match
the latest `version` entry in this file.

---

## 6. CLI Reference

### 6.1 GC CLI

Entry point: `python -m src.ingest.lifecycle.gc` or `run_gc_cli(argv)`

```
ragweave-gc [--dry-run] [--mode {soft,hard}] [--hard-confirm]
            [--trace-id UUID] [--retention-days N] [--format {json,text}]

Options:
  --dry-run            Report what would be deleted without modifying any store.
  --mode {soft,hard}   Delete mode. Default: soft.
  --hard-confirm       Required alongside --mode hard. IRREVERSIBLE.
  --trace-id UUID      Restrict GC to a single trace_id (informational only).
  --retention-days N   Override retention period for soft deletes. Default: 30.
  --format {json,text} Output format. Default: json.

Exit codes:
  0   Success
  1   Usage error or PermissionError
  2   Runtime error
```

**Examples:**

```bash
# Dry run — inspect what would be cleaned
python -m src.ingest.lifecycle.gc --dry-run --format text

# Soft GC (live)
python -m src.ingest.lifecycle.gc --mode soft --format json

# Hard delete (irreversible — requires both flags)
python -m src.ingest.lifecycle.gc --mode hard --hard-confirm --format json
```

**JSON output structure:**

```json
{
  "orphans": {
    "weaviate": [...],
    "minio": [...],
    "neo4j": [...],
    "manifest_only": [...]
  },
  "gc": {
    "soft_deleted": 0,
    "hard_deleted": 0,
    "retention_purged": 0,
    "dry_run": true,
    "per_document": {}
  }
}
```

### 6.2 Migration CLI

Entry point: `python -m src.ingest.lifecycle.migration` or `run_migration_cli(argv)`

```
ragweave-migrate [--from VERSION] [--to VERSION]
                 [--dry-run | --confirm] [--format {json,text}]
                 [--changelog PATH]

Options:
  --from VERSION       Treat all documents as being at this version.
                       Leave empty to use each entry's own schema_version field.
  --to VERSION         Target schema version. Default: PIPELINE_SCHEMA_VERSION.
  --dry-run            Plan only — no store mutations. Does not require --confirm.
  --confirm            Required to execute. Refused without this flag.
  --format {json,text} Output format. Default: json.
  --changelog PATH     Path to schema_changelog.yaml.
                       Default: config/schema_changelog.yaml.

Exit codes:
  0   Success
  1   Usage/permission error
  2   Runtime error
```

**Examples:**

```bash
# Dry run — see what would be migrated
python -m src.ingest.lifecycle.migration --from 0.0.0 --to 1.0.0 --dry-run

# Execute migration
python -m src.ingest.lifecycle.migration --from 0.0.0 --to 1.0.0 --confirm

# Per-entry schema_version (mixed versions in manifest)
python -m src.ingest.lifecycle.migration --to 1.0.0 --confirm
```

### 6.3 Validation CLI

Entry point: `python -m src.ingest.lifecycle.validation` or `run_validation_cli(argv)`

```
ragweave-validate (--trace-id UUID | --all) [--sample N] [--format {json,text}]

Mutually exclusive required:
  --trace-id UUID     Validate a single trace_id.
  --all               Validate all trace_ids in the manifest.

Options:
  --sample N          Randomly sample N entries (used with --all).
  --format {json,text} Output format. Default: json.

Exit codes:
  0   All validated entries are consistent.
  1   One or more inconsistencies found.
  2   Runtime error.
```

**Examples:**

```bash
# Single trace validation
python -m src.ingest.lifecycle.validation --trace-id <uuid> --format text

# Full manifest validation
python -m src.ingest.lifecycle.validation --all --format json

# Sampled validation (spot-check)
python -m src.ingest.lifecycle.validation --all --sample 50 --format json
```

---

## 7. Extension Guide

### 7.1 Adding a new store to `SyncEngine`

1. Add `new_store_keys: set[str]` and `new_store_error: Optional[str]` to
   `StoreInventory` in `schemas.py`.
2. Add `_enumerate_new_store() -> set[str]` to `SyncEngine`. Wrap in
   `try/except` and populate `inv.new_store_error` on failure.
3. Call it inside `inventory()` conditionally (if the new client is not `None`).
4. Update `diff()` to include the new set in orphan detection and in
   `all_store_keys` for `manifest_only` computation.
5. Update the `logger.info` call in `inventory()` and `diff()`.

### 7.2 Adding a new store to `GCEngine`

1. Add `new_store: bool = True` to `StoreCleanupStatus` in `schemas.py`.
2. Add `_cleanup_new_store(source_key, mode, status) -> bool` to `GCEngine`.
   Guard the body in `try/except`; append to `status.errors` and return `False`
   on failure.
3. Call it inside `collect_keys()` conditionally (same pattern as `minio_client`
   / `neo4j_client`).
4. Update `purge_expired()` to call the new helper.
5. Update the audit log message to include the new store flag.

### 7.3 Adding a new migration strategy

1. Add the strategy name to `_STRATEGY_RANK` in `changelog.py` with an
   appropriate cost integer.
2. Add the corresponding `MigrationStrategy` enum member.
3. Add `_migrate_new_strategy(task, entry) -> None` to `MigrationEngine`.
4. Add a dispatch branch to `_run_strategy()`.
5. Document the strategy in `config/schema_changelog.yaml`'s comment block.

### 7.4 Adding a new schema version to the changelog

1. Append a new entry to `config/schema_changelog.yaml`:
   - Unique `version` string (semantic version; must be after all existing
     entries in the file — `get_required_migrations` uses file order, not
     semver comparison).
   - `migration_strategy` set to the minimum-cost strategy that covers all
     field changes.
   - Populate `fields_added`, `fields_removed`, `fields_renamed` as applicable.
2. Update `PIPELINE_SCHEMA_VERSION` in `src/ingest/common/schemas.py`.
3. Run `python -m src.ingest.lifecycle.migration --dry-run` to verify the
   changelog parses correctly and the plan looks as expected.

---

## 8. Troubleshooting

### `PermissionError: Hard delete requires both confirm=True and cli_confirmed=True`

Hard delete requires passing both `confirm=True` and `cli_confirmed=True`
programmatically, or both `--mode hard` and `--hard-confirm` on the CLI.
This is intentional (NFR-3230). Pass both to proceed.

### `FileNotFoundError: Schema changelog not found: config/schema_changelog.yaml`

`load_changelog()` and the migration CLI resolve the path relative to the
current working directory. Run from the project root, or pass
`--changelog /absolute/path/to/schema_changelog.yaml`.

### `ValueError: from_version '...' not found in changelog`

The version string passed to `plan()` or `get_required_migrations()` is not
present in the changelog. Verify that the changelog contains all versions
referenced in your manifest and that `PIPELINE_SCHEMA_VERSION` matches the
latest entry.

### `ValueError: Duplicate version '...' in changelog`

Each version must appear exactly once. Remove or rename the duplicate entry.

### `ValueError: Unknown migration_strategy '...': Valid values: [...]`

A `schema_changelog.yaml` entry uses an unrecognised strategy string. Valid
values are: `none`, `metadata_only`, `kg_reextract`, `full_phase2`.

### Validation exit code 1 (inconsistency found)

Run `--trace-id <uuid> --format text` for the specific trace_id to see which
stores are missing data. Common causes:

- **Weaviate chunk count = 0:** Embedding pipeline failed or chunks were
  deleted without updating the manifest. Re-ingest the source.
- **MinIO missing:** Phase 1 write failed mid-flight (`.md` written but
  `.meta.json` not committed — partial write). Re-run ingestion for the source.
- **Neo4j missing:** KG extraction failed. Use `--dry-run` with the migration
  CLI to plan a `kg_reextract` migration for the affected document.
- **Manifest missing:** trace_id was generated but the manifest write failed.
  Re-ingest the source.

### MinIO `minio_clean_store_soft_delete_failed` warnings in logs

`MinioCleanStore.soft_delete()` logs a warning (not an error) per object when
a copy or remove step fails. The GC run continues (NFR-3210 store isolation).
Check MinIO connectivity, bucket permissions, and whether the object has
already been moved or deleted.

### `SyncEngine` returns empty `weaviate_keys` with no error

`_enumerate_weaviate()` falls back to an empty set when
`src.vector_db.aggregate_by_source` raises `ImportError` (function not yet
exported from the facade). This is a graceful degradation. To enable Weaviate
enumeration, add `aggregate_by_source` to the `src.vector_db` public API.

### Migration execution interrupted mid-run

Because `execute()` updates `entry["schema_version"]` immediately on each
successful entry (NFR-3211), re-running `plan()` + `execute()` on the same
manifest will skip already-migrated entries. Simply re-run the migration
command; it is safe to repeat.
