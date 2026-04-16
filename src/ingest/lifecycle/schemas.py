# @summary
# Typed contracts for the data lifecycle subsystem: OrphanReport, GCReport,
# StoreInventory, StoreCleanupStatus, SyncResult, and LifecycleConfig.
# Exports: OrphanReport, GCReport, StoreInventory, StoreCleanupStatus, SyncResult, LifecycleConfig
# Deps: dataclasses, typing
# @end-summary
"""Typed contracts for the data lifecycle subsystem.

All public dataclasses are intentionally plain (no Pydantic) to keep this
module import-free of heavy runtime dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SyncResult:
    """Result of a source-to-manifest diff (FR-3000).

    Attributes:
        added: Source keys present on disk but absent from the manifest.
        modified: Source keys present in both but with a differing content hash.
        deleted: Source keys in the manifest but no longer on disk.
        unchanged: Count of source keys identical in both.
    """

    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    unchanged: int = 0


@dataclass
class StoreCleanupStatus:
    """Per-store cleanup result for a single source_key.

    Attributes:
        weaviate: True if the Weaviate operation succeeded (or was skipped).
        minio: True if the MinIO operation succeeded (or was skipped).
        neo4j: True if the Neo4j/KG operation succeeded (or was skipped).
        manifest: True if the manifest mutation succeeded.
        errors: Human-readable error messages for any failures.
    """

    weaviate: bool = True
    minio: bool = True
    neo4j: bool = True
    manifest: bool = True
    errors: list[str] = field(default_factory=list)


@dataclass
class GCReport:
    """Aggregate result of a GC run.

    Attributes:
        soft_deleted: Number of source keys soft-deleted in this run.
        hard_deleted: Number of source keys hard-deleted in this run.
        retention_purged: Number of expired soft-deleted entries purged.
        per_document: Per-source-key cleanup status map.
        dry_run: Whether this was a dry-run (no mutations made).
    """

    soft_deleted: int = 0
    hard_deleted: int = 0
    retention_purged: int = 0
    per_document: dict[str, StoreCleanupStatus] = field(default_factory=dict)
    dry_run: bool = False


@dataclass
class StoreInventory:
    """Snapshot of keys present in each store plus the manifest.

    All four sets contain safe/normalised source_key strings.  Callers
    use ``SyncEngine.diff(inventory)`` to derive an :class:`OrphanReport`.

    Attributes:
        manifest_keys: Keys from the active (non-deleted) manifest entries.
        weaviate_keys: Distinct source_keys found in Weaviate (may be empty if
            the store is unavailable).
        minio_keys: Source keys found in the MinIO clean store.
        neo4j_keys: Source keys reported by the KG backend.
        weaviate_error: Error message if Weaviate enumeration failed.
        minio_error: Error message if MinIO enumeration failed.
        neo4j_error: Error message if Neo4j enumeration failed.
    """

    manifest_keys: set[str] = field(default_factory=set)
    weaviate_keys: set[str] = field(default_factory=set)
    minio_keys: set[str] = field(default_factory=set)
    neo4j_keys: set[str] = field(default_factory=set)
    weaviate_error: Optional[str] = None
    minio_error: Optional[str] = None
    neo4j_error: Optional[str] = None


@dataclass
class OrphanReport:
    """Orphan detection report (FR-3002).

    An orphan is an object present in store X but absent from the manifest
    (or vice-versa).  This report is read-only; no cleanup is performed by
    the :class:`SyncEngine`.

    Attributes:
        weaviate_orphans: Source keys in Weaviate but not in the manifest.
        minio_orphans: Source keys in MinIO but not in the manifest.
        neo4j_orphans: Source keys in Neo4j but not in the manifest.
        manifest_only: Source keys in the manifest but in none of the stores.
    """

    weaviate_orphans: list[str] = field(default_factory=list)
    minio_orphans: list[str] = field(default_factory=list)
    neo4j_orphans: list[str] = field(default_factory=list)
    manifest_only: list[str] = field(default_factory=list)


@dataclass
class LifecycleConfig:
    """Configuration for the lifecycle subsystem.

    Intended as a lightweight config container so callers do not need to
    pass individual kwargs through every layer.

    Attributes:
        gc_mode: Default GC delete mode — ``"soft"`` or ``"hard"``.
        gc_retention_days: Days to retain soft-deleted data before purge.
        gc_schedule: Cron expression for scheduled GC. Empty string disables.
        minio_bucket: MinIO bucket for the clean store. Empty uses the
            ``target_bucket`` from :class:`IngestionConfig`.
    """

    gc_mode: str = "soft"
    gc_retention_days: int = 30
    gc_schedule: str = ""
    minio_bucket: str = ""
