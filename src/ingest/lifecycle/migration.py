# @summary
# MigrationEngine: per-trace_id schema migration with dry-run plan and confirmed
# execute modes. Supports METADATA_ONLY, FULL_PHASE2_RERUN, KG_REEXTRACT strategies.
# Failures are isolated per entry; re-running is idempotent (already-migrated entries
# are skipped). Exposes run_migration_cli() as a module-level CLI entry point.
# Exports: MigrationEngine, run_migration_cli
# Deps: src.ingest.common.schemas, src.ingest.lifecycle.changelog,
#       src.ingest.lifecycle.schemas, src.vector_db, logging, argparse, json
# @end-summary
"""Schema migration runner (FR-3110, FR-3111, FR-3112, NFR-3181, NFR-3211).

:class:`MigrationEngine` selectively re-processes documents based on their
current ``schema_version``, applying the minimum-cost migration strategy for
each version gap as determined by the schema changelog.

Migration strategies (FR-3111):

* ``metadata_only`` — Weaviate batch partial-update. No re-embedding. Cheap.
* ``full_phase2``   — Read clean markdown from MinIO, re-run Embedding Pipeline.
* ``kg_reextract``  — Delete old triples, re-run KG extraction nodes.
* ``none``          — No action. Entry is skipped.

Idempotency (FR-3112): documents already at the target version are skipped.
Per-trace_id isolation: a failure for one entry never halts the batch.
Resumability (NFR-3211): the manifest is updated incrementally so interrupted
runs can be re-started safely.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from src.ingest.common.schemas import ManifestEntry, PIPELINE_SCHEMA_VERSION
from src.ingest.lifecycle.changelog import (
    SchemaVersion,
    determine_migration_strategy,
    load_changelog,
)
from src.ingest.lifecycle.schemas import MigrationPlan, MigrationReport, MigrationTask

logger = logging.getLogger(__name__)

# Default changelog path (resolved relative to cwd at runtime).
_DEFAULT_CHANGELOG_PATH: Path = Path("config/schema_changelog.yaml")


class MigrationEngine:
    """Per-trace_id schema migration engine.

    Args:
        client: Weaviate client handle (required for metadata_only migrations).
        manifest_path: Path to the manifest JSON file on disk.  Used by the
            CLI helpers; programmatic callers may pass ``None`` and supply
            manifests directly.
        clean_store: :class:`MinioCleanStore` instance (required for
            ``full_phase2`` and ``kg_reextract`` strategies).
        vector_db: Weaviate facade module or object exposing
            ``batch_update_metadata_by_source_key``.  Defaults to importing
            ``src.vector_db`` lazily when needed.
        kg_client: KG backend client (required for ``kg_reextract`` strategy).
        changelog: Pre-loaded changelog entries.  ``None`` triggers
            :func:`load_changelog` on the first call to :meth:`plan`.
        changelog_path: Path to the YAML changelog file. Used only when
            *changelog* is ``None``.
    """

    def __init__(
        self,
        client: Any,
        manifest_path: Optional[str | Path] = None,
        clean_store: Optional[Any] = None,
        vector_db: Optional[Any] = None,
        kg_client: Optional[Any] = None,
        changelog: Optional[list[SchemaVersion]] = None,
        changelog_path: str | Path = _DEFAULT_CHANGELOG_PATH,
    ) -> None:
        self._client = client
        self._manifest_path = Path(manifest_path) if manifest_path else None
        self._clean_store = clean_store
        self._vector_db = vector_db
        self._kg_client = kg_client
        self._changelog = changelog
        self._changelog_path = Path(changelog_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def plan(
        self,
        from_version: str,
        to_version: str,
        manifest: Optional[dict[str, ManifestEntry]] = None,
    ) -> MigrationPlan:
        """Build a dry-run migration plan without executing any store mutations.

        Identifies all non-deleted manifest entries whose ``schema_version``
        differs from *to_version* and whose version gap requires a migration
        strategy that is not ``"none"``.

        Args:
            from_version: Override version to treat as the "current" version for
                all entries.  If ``None`` is passed, each entry's own
                ``schema_version`` field (falling back to ``"0.0.0"``) is used.
                To plan based on each entry's individual version, pass
                ``from_version=""`` and let the engine per-entry.
            to_version: Target schema version.
            manifest: Optional manifest dict.  When ``None``, the engine loads
                the manifest from ``manifest_path``.

        Returns:
            :class:`MigrationPlan` with per-entry tasks and a summary.
        """
        changelog = self._get_changelog()
        if manifest is None:
            manifest = self._load_manifest()

        tasks: list[MigrationTask] = []
        skipped = 0

        for source_key, entry in manifest.items():
            if entry.get("deleted", False):
                skipped += 1
                continue

            doc_version = entry.get("schema_version", "0.0.0") or "0.0.0"
            effective_from = from_version if from_version else doc_version

            if effective_from == to_version:
                skipped += 1
                continue

            try:
                strategy = determine_migration_strategy(
                    effective_from, to_version, changelog
                )
            except ValueError as exc:
                logger.warning(
                    "migration_plan_version_not_found source_key=%s error=%s",
                    source_key,
                    exc,
                )
                strategy = "metadata_only"

            if strategy == "none":
                skipped += 1
                continue

            tasks.append(
                MigrationTask(
                    source_key=source_key,
                    trace_id=entry.get("trace_id", ""),
                    from_version=effective_from,
                    to_version=to_version,
                    strategy=strategy,
                )
            )

        logger.info(
            "migration_plan to_version=%s tasks=%d skipped=%d",
            to_version,
            len(tasks),
            skipped,
        )
        return MigrationPlan(
            to_version=to_version,
            tasks=tasks,
            skipped_count=skipped,
        )

    def execute(
        self,
        plan: MigrationPlan,
        *,
        confirm: bool = False,
        manifest: Optional[dict[str, ManifestEntry]] = None,
    ) -> MigrationReport:
        """Execute the migrations described in *plan*.

        Migrations are refused unless ``confirm=True``.  Each entry's migration
        runs independently — a failure for one entry never halts subsequent
        entries (per-trace_id isolation).  Successfully migrated entries have
        their ``schema_version`` updated immediately so the run is resumable
        (NFR-3211).

        Args:
            plan: Migration plan produced by :meth:`plan`.
            confirm: Must be ``True`` to execute.  A plan without
                ``confirm=True`` raises :class:`PermissionError`.
            manifest: Manifest dict to mutate in-place.  When ``None``, the
                engine loads from ``manifest_path`` and (if ``manifest_path``
                is set) saves back on completion.

        Returns:
            :class:`MigrationReport` with success/fail counts and per-entry
            outcomes.

        Raises:
            PermissionError: If ``confirm=False``.
        """
        if not confirm:
            raise PermissionError(
                "Migration execution requires confirm=True. "
                "Pass --confirm on the CLI or set confirm=True programmatically."
            )

        owns_manifest = manifest is None
        if manifest is None:
            manifest = self._load_manifest()

        changelog = self._get_changelog()
        report = MigrationReport(
            to_version=plan.to_version,
            total_eligible=len(plan.tasks),
        )

        for task in plan.tasks:
            entry = manifest.get(task.source_key)
            if entry is None:
                logger.warning(
                    "migration_execute_entry_missing source_key=%s", task.source_key
                )
                report.failed += 1
                report.per_entry[task.source_key] = {
                    "status": "failed",
                    "error": "entry not found in manifest",
                    "strategy": task.strategy,
                }
                continue

            # Idempotency: skip if already at target (FR-3112).
            current_version = entry.get("schema_version", "0.0.0") or "0.0.0"
            if current_version == task.to_version:
                report.skipped += 1
                report.per_entry[task.source_key] = {
                    "status": "skipped",
                    "reason": "already_at_target",
                    "strategy": task.strategy,
                }
                continue

            try:
                self._run_strategy(task, entry)
                # Update manifest on success (NFR-3211: resumability).
                entry["schema_version"] = task.to_version
                report.succeeded += 1
                report.per_entry[task.source_key] = {
                    "status": "ok",
                    "strategy": task.strategy,
                }
                logger.info(
                    "migration_success source_key=%s strategy=%s to_version=%s",
                    task.source_key,
                    task.strategy,
                    task.to_version,
                )
            except Exception as exc:
                report.failed += 1
                report.per_entry[task.source_key] = {
                    "status": "failed",
                    "error": str(exc),
                    "strategy": task.strategy,
                }
                logger.error(
                    "migration_failed source_key=%s strategy=%s error=%s",
                    task.source_key,
                    task.strategy,
                    exc,
                )

        # Persist manifest if we own it.
        if owns_manifest and self._manifest_path is not None:
            self._save_manifest(manifest)

        logger.info(
            "migration_complete to_version=%s succeeded=%d failed=%d skipped=%d",
            plan.to_version,
            report.succeeded,
            report.failed,
            report.skipped,
        )
        return report

    # ------------------------------------------------------------------
    # Private strategy dispatchers
    # ------------------------------------------------------------------

    def _run_strategy(self, task: MigrationTask, entry: ManifestEntry) -> None:
        """Dispatch to the appropriate strategy handler."""
        if task.strategy == "metadata_only":
            self._migrate_metadata_only(task, entry)
        elif task.strategy == "full_phase2":
            self._migrate_full_phase2(task, entry)
        elif task.strategy == "kg_reextract":
            self._migrate_kg_reextract(task, entry)
        else:
            raise ValueError(f"Unknown migration strategy: {task.strategy!r}")

    def _migrate_metadata_only(
        self, task: MigrationTask, entry: ManifestEntry
    ) -> None:
        """Weaviate batch partial-update: set schema_version on all chunks.

        Target throughput: >= 100 docs/sec (NFR-3181).
        """
        vector_db = self._get_vector_db()
        if not hasattr(vector_db, "batch_update_metadata_by_source_key"):
            logger.warning(
                "migration_metadata_only: batch_update_metadata_by_source_key "
                "not available on vector_db facade; skipping Weaviate update "
                "for source_key=%s",
                task.source_key,
            )
            return

        vector_db.batch_update_metadata_by_source_key(
            self._client,
            task.source_key,
            properties={"schema_version": task.to_version},
        )
        logger.debug(
            "migration_metadata_only_weaviate_updated source_key=%s to_version=%s",
            task.source_key,
            task.to_version,
        )

    def _migrate_full_phase2(
        self, task: MigrationTask, entry: ManifestEntry
    ) -> None:
        """Full Phase 2 re-run using clean markdown from MinIO."""
        if self._clean_store is None:
            raise RuntimeError(
                "full_phase2 migration requires a clean_store (MinioCleanStore). "
                "Pass clean_store= when constructing MigrationEngine."
            )

        text, meta = self._clean_store.read(task.source_key)
        new_trace_id = str(uuid4())

        # Delete existing chunks first.
        vector_db = self._get_vector_db()
        if hasattr(vector_db, "delete_by_source_key"):
            vector_db.delete_by_source_key(self._client, task.source_key)

        # Re-run Phase 2.
        from src.ingest.embedding import run_embedding_pipeline  # type: ignore[attr-defined]

        run_embedding_pipeline(
            runtime=self._client,  # runtime passed as client for now
            source_key=task.source_key,
            source_name=meta.get("source_name", ""),
            source_uri=meta.get("source_uri", ""),
            source_id=meta.get("source_id", ""),
            connector=meta.get("connector", ""),
            source_version=meta.get("source_version", ""),
            clean_text=text,
            clean_hash=meta.get("clean_hash", ""),
            trace_id=new_trace_id,
        )

        entry["trace_id"] = new_trace_id
        logger.debug(
            "migration_full_phase2_complete source_key=%s new_trace_id=%s",
            task.source_key,
            new_trace_id,
        )

    def _migrate_kg_reextract(
        self, task: MigrationTask, entry: ManifestEntry
    ) -> None:
        """Delete old KG triples and re-run KG extraction."""
        if self._clean_store is None or self._kg_client is None:
            raise RuntimeError(
                "kg_reextract migration requires both clean_store and kg_client. "
                "Pass both when constructing MigrationEngine."
            )

        text, meta = self._clean_store.read(task.source_key)

        if hasattr(self._kg_client, "delete_by_source_key"):
            self._kg_client.delete_by_source_key(task.source_key)
        elif hasattr(self._kg_client, "remove_by_source"):
            self._kg_client.remove_by_source(task.source_key)

        new_trace_id = str(uuid4())
        if hasattr(self._kg_client, "extract_from_text"):
            self._kg_client.extract_from_text(
                text=text,
                source_key=task.source_key,
                source_name=meta.get("source_name", ""),
                trace_id=new_trace_id,
            )

        entry["trace_id"] = new_trace_id
        logger.debug(
            "migration_kg_reextract_complete source_key=%s new_trace_id=%s",
            task.source_key,
            new_trace_id,
        )

    # ------------------------------------------------------------------
    # Private infrastructure helpers
    # ------------------------------------------------------------------

    def _get_changelog(self) -> list[SchemaVersion]:
        """Return the loaded changelog, loading lazily on first call."""
        if self._changelog is None:
            self._changelog = load_changelog(self._changelog_path)
        return self._changelog

    def _get_vector_db(self) -> Any:
        """Return the vector_db module/object, importing lazily if needed."""
        if self._vector_db is not None:
            return self._vector_db
        import src.vector_db as _vdb  # type: ignore[attr-defined]

        return _vdb

    def _load_manifest(self) -> dict[str, ManifestEntry]:
        """Load the manifest from disk, or return an empty dict."""
        if self._manifest_path is None:
            return {}
        try:
            import json as _json

            text = self._manifest_path.read_text(encoding="utf-8")
            return _json.loads(text)
        except Exception as exc:
            logger.warning(
                "migration_load_manifest_failed path=%s error=%s",
                self._manifest_path,
                exc,
            )
            return {}

    def _save_manifest(self, manifest: dict) -> None:
        """Persist the manifest back to ``manifest_path``."""
        if self._manifest_path is None:
            return
        try:
            import json as _json

            self._manifest_path.write_text(
                _json.dumps(manifest, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning(
                "migration_save_manifest_failed path=%s error=%s",
                self._manifest_path,
                exc,
            )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def run_migration_cli(argv: list[str] | None = None) -> int:
    """Command-line entry point for the schema migration runner.

    Parses argv (or ``sys.argv[1:]``), plans/executes migrations, and emits a
    JSON or human-readable report to stdout.

    Args:
        argv: Argument list.  Defaults to ``sys.argv[1:]``.

    Returns:
        Exit code: 0 on success, 1 on usage/permission error, 2 on runtime error.

    Usage::

        python -m src.ingest.lifecycle.migration \\
            --from <ver> --to <ver> \\
            [--dry-run] [--confirm] \\
            [--format {json,text}]
    """
    parser = argparse.ArgumentParser(
        prog="ragweave-migrate",
        description="Run schema migration for documents below the target version.",
    )
    parser.add_argument(
        "--from",
        dest="from_version",
        default="",
        metavar="VERSION",
        help=(
            "Treat all documents as being at this version. "
            "Leave empty to use each entry's own schema_version field."
        ),
    )
    parser.add_argument(
        "--to",
        dest="to_version",
        default=PIPELINE_SCHEMA_VERSION,
        metavar="VERSION",
        help=f"Target schema version. Default: {PIPELINE_SCHEMA_VERSION}",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Plan only — report eligible documents without modifying any store.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        default=False,
        help="Required to execute migrations. Refused without this flag.",
    )
    parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        help="Output format. Default: json.",
    )
    parser.add_argument(
        "--changelog",
        default=str(_DEFAULT_CHANGELOG_PATH),
        metavar="PATH",
        help="Path to schema_changelog.yaml. Default: config/schema_changelog.yaml.",
    )

    args = parser.parse_args(argv)

    if not args.dry_run and not args.confirm:
        parser.error(
            "Migration execution requires --confirm. "
            "Use --dry-run to preview changes without --confirm."
        )
        return 1

    try:
        # Load changelog to validate it is readable.
        changelog = load_changelog(Path(args.changelog))

        # Build a lightweight engine with stub clients for the CLI context.
        weaviate_client = _open_weaviate_client()
        minio_client = _open_minio_client()
        minio_bucket = _resolve_minio_bucket()
        manifest = _load_manifest_cli()

        clean_store = None
        if minio_client is not None:
            from src.ingest.common.minio_clean_store import MinioCleanStore  # type: ignore[attr-defined]

            clean_store = MinioCleanStore(minio_client, minio_bucket)

        engine = MigrationEngine(
            client=weaviate_client,
            clean_store=clean_store,
            changelog=changelog,
        )

        plan = engine.plan(
            from_version=args.from_version,
            to_version=args.to_version,
            manifest=manifest,
        )

        if args.dry_run:
            _emit_migration_report_dry(plan, fmt=args.format)
            return 0

        report = engine.execute(plan, confirm=args.confirm, manifest=manifest)
        _save_manifest_cli(manifest)
        _emit_migration_report(plan, report, fmt=args.format)
        return 0

    except PermissionError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 1
    except Exception as exc:
        logger.exception("migration_cli_error: %s", exc)
        sys.stderr.write(f"ERROR: {exc}\n")
        return 2


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def _open_weaviate_client() -> Any:
    try:
        from src.vector_db import create_persistent_client  # type: ignore[attr-defined]

        return create_persistent_client()
    except Exception as exc:
        logger.warning("migration_cli_weaviate_unavailable error=%s", exc)
        return None


def _open_minio_client() -> Optional[Any]:
    try:
        import minio as _minio_lib  # noqa: F401
        from config.settings import (  # type: ignore[attr-defined]
            MINIO_ENDPOINT,
            MINIO_ACCESS_KEY,
            MINIO_SECRET_KEY,
            MINIO_SECURE,
        )
        import minio

        return minio.Minio(
            MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=MINIO_SECURE,
        )
    except Exception as exc:
        logger.warning("migration_cli_minio_unavailable error=%s", exc)
        return None


def _resolve_minio_bucket() -> str:
    try:
        from config.settings import MINIO_BUCKET  # type: ignore[attr-defined]

        return MINIO_BUCKET
    except Exception:
        return ""


def _load_manifest_cli() -> dict:
    try:
        from src.ingest.common.utils import load_manifest  # type: ignore[attr-defined]

        return load_manifest()
    except Exception as exc:
        logger.warning("migration_cli_manifest_load_failed error=%s", exc)
        return {}


def _save_manifest_cli(manifest: dict) -> None:
    try:
        from src.ingest.common.utils import save_manifest  # type: ignore[attr-defined]

        save_manifest(manifest)
    except Exception as exc:
        logger.warning("migration_cli_manifest_save_failed error=%s", exc)


def _emit_migration_report_dry(plan: MigrationPlan, fmt: str = "json") -> None:
    """Emit a dry-run plan report."""
    strategy_counts: dict[str, int] = {}
    for task in plan.tasks:
        strategy_counts[task.strategy] = strategy_counts.get(task.strategy, 0) + 1

    if fmt == "text":
        print("=== Migration Dry Run ===")
        print(f"  Target version  : {plan.to_version}")
        print(f"  Eligible entries: {len(plan.tasks)}")
        print(f"  Skipped         : {plan.skipped_count}")
        print(f"  Strategy counts : {strategy_counts}")
        if plan.tasks:
            print("\nEligible entries:")
            for task in plan.tasks:
                print(f"  [{task.strategy}] {task.source_key}  ({task.from_version} -> {task.to_version})")
    else:
        data = {
            "dry_run": True,
            "to_version": plan.to_version,
            "eligible": len(plan.tasks),
            "skipped": plan.skipped_count,
            "strategy_counts": strategy_counts,
            "tasks": [
                {
                    "source_key": t.source_key,
                    "trace_id": t.trace_id,
                    "from_version": t.from_version,
                    "to_version": t.to_version,
                    "strategy": t.strategy,
                }
                for t in plan.tasks
            ],
        }
        print(json.dumps(data, indent=2))


def _emit_migration_report(
    plan: MigrationPlan, report: MigrationReport, fmt: str = "json"
) -> None:
    """Emit a completed migration report."""
    if fmt == "text":
        print("=== Migration Complete ===")
        print(f"  Target version  : {report.to_version}")
        print(f"  Total eligible  : {report.total_eligible}")
        print(f"  Succeeded       : {report.succeeded}")
        print(f"  Failed          : {report.failed}")
        print(f"  Skipped         : {report.skipped}")
        if report.failed > 0:
            print("\nFailed entries:")
            for key, outcome in report.per_entry.items():
                if outcome.get("status") == "failed":
                    print(f"  [FAILED] {key}: {outcome.get('error', 'unknown error')}")
    else:
        data = {
            "to_version": report.to_version,
            "total_eligible": report.total_eligible,
            "succeeded": report.succeeded,
            "failed": report.failed,
            "skipped": report.skipped,
            "per_entry": report.per_entry,
        }
        print(json.dumps(data, indent=2))


if __name__ == "__main__":
    sys.exit(run_migration_cli())
