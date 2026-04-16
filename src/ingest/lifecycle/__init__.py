# @summary
# Public package init for the data lifecycle subsystem. Stable import surface
# for GCEngine, SyncEngine, OrphanReport, GCReport, StoreInventory, LifecycleConfig,
# MigrationEngine, MigrationPlan, MigrationReport, E2EValidator, ValidationReport,
# SchemaVersion, MigrationStrategy, load_changelog, and factory helpers.
# Exports: GCEngine, SyncEngine, OrphanReport, GCReport, StoreInventory,
#          LifecycleConfig, build_gc_engine, build_sync_engine,
#          MigrationEngine, MigrationPlan, MigrationReport, MigrationTask,
#          E2EValidator, ValidationReport, ValidationFinding,
#          SchemaVersion, MigrationStrategy, load_changelog
# Deps: src.ingest.lifecycle.gc, src.ingest.lifecycle.sync,
#       src.ingest.lifecycle.schemas, src.ingest.lifecycle.changelog,
#       src.ingest.lifecycle.migration, src.ingest.lifecycle.validation
# @end-summary
"""Public API for the data lifecycle subsystem.

All pipeline code should import from this module rather than from the
internal sub-modules, so that internal refactors do not break callers.

Typical usage::

    from src.ingest.lifecycle import (
        SyncEngine, GCEngine, OrphanReport, LifecycleConfig,
        MigrationEngine, E2EValidator, load_changelog,
    )

    # Orphan detection + GC
    engine = SyncEngine(manifest=manifest, weaviate_client=client, ...)
    inventory = engine.inventory()
    orphan_report = engine.diff(inventory)
    gc = GCEngine(manifest=manifest, weaviate_client=client, ...)
    gc_report = gc.collect(orphan_report, mode="soft", dry_run=True)

    # Schema migration
    changelog = load_changelog("config/schema_changelog.yaml")
    migrator = MigrationEngine(client=weaviate_client, changelog=changelog)
    plan = migrator.plan(from_version="0.0.0", to_version="1.0.0")
    report = migrator.execute(plan, confirm=True)

    # E2E validation
    validator = E2EValidator(client=weaviate_client, minio=clean_store)
    vreport = validator.validate_by_trace_id(trace_id)
"""

from src.ingest.lifecycle.changelog import (
    MigrationStrategy,
    SchemaVersion,
    load_changelog,
)
from src.ingest.lifecycle.gc import GCEngine
from src.ingest.lifecycle.migration import MigrationEngine
from src.ingest.lifecycle.schemas import (
    GCReport,
    LifecycleConfig,
    MigrationPlan,
    MigrationReport,
    MigrationTask,
    OrphanReport,
    StoreCleanupStatus,
    StoreInventory,
    SyncResult,
    ValidationFinding,
    ValidationReport,
)
from src.ingest.lifecycle.sync import SyncEngine
from src.ingest.lifecycle.validation import E2EValidator


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def build_sync_engine(
    manifest: dict,
    weaviate_client,
    minio_client=None,
    minio_bucket: str = "",
    neo4j_client=None,
    collection=None,
) -> SyncEngine:
    """Convenience factory for :class:`SyncEngine`.

    Args:
        manifest: Current manifest dict keyed by source_key.
        weaviate_client: Weaviate client handle.
        minio_client: Optional MinIO client.
        minio_bucket: MinIO bucket name.
        neo4j_client: Optional KG backend.
        collection: Weaviate collection name.  ``None`` uses the default.

    Returns:
        A configured :class:`SyncEngine` instance.
    """
    return SyncEngine(
        manifest=manifest,
        weaviate_client=weaviate_client,
        minio_client=minio_client,
        minio_bucket=minio_bucket,
        neo4j_client=neo4j_client,
        collection=collection,
    )


def build_gc_engine(
    manifest: dict,
    weaviate_client,
    minio_client=None,
    minio_bucket: str = "",
    neo4j_client=None,
    retention_days: int = 30,
    collection=None,
) -> GCEngine:
    """Convenience factory for :class:`GCEngine`.

    Args:
        manifest: Current manifest dict keyed by source_key.
        weaviate_client: Weaviate client handle.
        minio_client: Optional MinIO client.
        minio_bucket: MinIO bucket name.
        neo4j_client: Optional KG backend.
        retention_days: Soft-delete retention period in days.
        collection: Weaviate collection name.  ``None`` uses the default.

    Returns:
        A configured :class:`GCEngine` instance.
    """
    return GCEngine(
        manifest=manifest,
        weaviate_client=weaviate_client,
        minio_client=minio_client,
        minio_bucket=minio_bucket,
        neo4j_client=neo4j_client,
        retention_days=retention_days,
        collection=collection,
    )


__all__ = [
    # Engines
    "GCEngine",
    "SyncEngine",
    "MigrationEngine",
    "E2EValidator",
    # Schemas — GC/Sync
    "GCReport",
    "LifecycleConfig",
    "OrphanReport",
    "StoreCleanupStatus",
    "StoreInventory",
    "SyncResult",
    # Schemas — Migration
    "MigrationPlan",
    "MigrationReport",
    "MigrationTask",
    # Schemas — Validation
    "ValidationReport",
    "ValidationFinding",
    # Changelog
    "SchemaVersion",
    "MigrationStrategy",
    "load_changelog",
    # Factories
    "build_gc_engine",
    "build_sync_engine",
]
