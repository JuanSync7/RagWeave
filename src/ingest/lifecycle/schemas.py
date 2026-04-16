# @summary
# Typed contracts for the data lifecycle subsystem: OrphanReport, GCReport,
# StoreInventory, StoreCleanupStatus, SyncResult, LifecycleConfig, MigrationPlan,
# MigrationReport, MigrationTask, ValidationReport, ValidationFinding.
# Exports: OrphanReport, GCReport, StoreInventory, StoreCleanupStatus, SyncResult,
#          LifecycleConfig, MigrationPlan, MigrationReport, MigrationTask,
#          ValidationReport, ValidationFinding
# Deps: dataclasses, typing
# @end-summary
"""Typed contracts for the data lifecycle subsystem.

All public dataclasses are intentionally plain (no Pydantic) to keep this
module import-free of heavy runtime dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


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


# ---------------------------------------------------------------------------
# Schema migration contracts (T5)
# ---------------------------------------------------------------------------


@dataclass
class MigrationTask:
    """A single per-entry migration sub-task inside a :class:`MigrationPlan`.

    Attributes:
        source_key: Stable source identity key for the document.
        trace_id: Current trace_id from the manifest (informational).
        from_version: Schema version the document is currently at.
        to_version: Target schema version.
        strategy: Migration strategy to apply.
    """

    source_key: str
    trace_id: str = ""
    from_version: str = "0.0.0"
    to_version: str = ""
    strategy: str = "none"


@dataclass
class MigrationPlan:
    """Dry-run migration plan produced by :meth:`MigrationEngine.plan`.

    Attributes:
        to_version: Target schema version for this plan.
        tasks: Per-entry sub-tasks to execute.
        skipped_count: Number of entries skipped (already at target, or
            strategy is ``none``).
    """

    to_version: str = ""
    tasks: list[MigrationTask] = field(default_factory=list)
    skipped_count: int = 0


@dataclass
class MigrationReport:
    """Result of a completed migration run from :meth:`MigrationEngine.execute`.

    Attributes:
        to_version: Target schema version that was applied.
        total_eligible: Number of entries included in the plan.
        succeeded: Number of entries successfully migrated.
        failed: Number of entries that failed (errors isolated per entry).
        skipped: Number of entries skipped during execution (idempotency).
        per_entry: Per-source_key outcome dict.  Each value has at minimum
            ``{"status": "ok" | "failed" | "skipped", "strategy": <str>}``.
    """

    to_version: str = ""
    total_eligible: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    per_entry: dict[str, dict[str, Any]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# E2E validation contracts (T6)
# ---------------------------------------------------------------------------


@dataclass
class ValidationFinding:
    """Per-trace_id cross-store consistency finding.

    Attributes:
        trace_id: The trace_id being validated.
        source_key: Resolved source_key (from manifest lookup).
        checked_at: ISO 8601 timestamp of when the check was run.
        consistent: ``True`` when all enabled stores reported data.
        manifest_ok: Whether the manifest has an entry for this trace_id.
        weaviate_ok: Whether Weaviate has >= 1 chunk for this trace_id.
            ``None`` if Weaviate was unavailable.
        weaviate_chunk_count: Raw chunk count from Weaviate.  ``None`` on error.
        minio_ok: Whether MinIO has a clean document for the source_key.
            ``None`` if MinIO is not configured.
        neo4j_ok: Whether the KG has >= 1 triple for this trace_id.
            ``None`` if the KG is disabled (FR-3062).
        kg_triple_count: Raw triple count from the KG.  ``None`` on error or
            when KG is disabled.
        missing_stores: List of store names that are missing data.
    """

    trace_id: str
    source_key: str = ""
    checked_at: str = ""
    consistent: bool = False
    manifest_ok: Optional[bool] = None
    weaviate_ok: Optional[bool] = None
    weaviate_chunk_count: Optional[int] = None
    minio_ok: Optional[bool] = None
    neo4j_ok: Optional[bool] = None
    kg_triple_count: Optional[int] = None
    missing_stores: list[str] = field(default_factory=list)


@dataclass
class ValidationReport:
    """Aggregate E2E validation report from :class:`E2EValidator`.

    Attributes:
        validated_at: ISO 8601 timestamp of when the report was produced.
        findings: Per-trace_id finding list.
        consistent: ``True`` when every finding in *findings* is consistent.
        total_checked: Number of trace_ids checked (equals ``len(findings)``
            for single-trace_id runs).
        inconsistent_count: Number of inconsistent findings.
    """

    validated_at: str = ""
    findings: list[ValidationFinding] = field(default_factory=list)
    consistent: bool = True
    total_checked: int = 0
    inconsistent_count: int = 0
