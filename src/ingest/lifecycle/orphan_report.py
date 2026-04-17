# @summary
# Human-readable and JSON formatting for OrphanReport and GCReport.
# Provides format_text() and format_json() as the stable formatting surface.
# Exports: format_text, format_json
# Deps: src.ingest.lifecycle.schemas, dataclasses, json, datetime
# @end-summary
"""Orphan report formatting — plain text and JSON (FR-3002).

Both formatters are pure functions (no side effects) and accept the same
two positional arguments:

* :class:`OrphanReport` — the orphan detection result from :class:`SyncEngine`.
* :class:`GCReport` — the GC result (optional; pass ``None`` if GC has not
  run yet).

The text format is human-readable and suitable for CLI ``--format text``.
The JSON format is machine-readable and suitable for piping or structured
logging.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional

from src.ingest.lifecycle.schemas import GCReport, OrphanReport


# ---------------------------------------------------------------------------
# Public formatters
# ---------------------------------------------------------------------------


def format_text(
    orphan_report: OrphanReport,
    gc_report: Optional[GCReport] = None,
) -> str:
    """Render *orphan_report* (and optional *gc_report*) as human-readable text.

    Args:
        orphan_report: Orphan detection report produced by :class:`SyncEngine`.
        gc_report: Optional GC execution report.  When ``None``, the GC
            summary section is omitted.

    Returns:
        A multi-line string ready for ``print()`` or file output.
    """
    lines: list[str] = []
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines.append(f"=== RagWeave Orphan Report  [{ts}] ===")
    lines.append("")

    # Orphan summary
    total_orphans = (
        len(orphan_report.weaviate_orphans)
        + len(orphan_report.minio_orphans)
        + len(orphan_report.neo4j_orphans)
    )
    lines.append(f"Total orphaned keys: {total_orphans}")
    lines.append(
        f"  Weaviate orphans : {len(orphan_report.weaviate_orphans)}"
    )
    lines.append(
        f"  MinIO orphans    : {len(orphan_report.minio_orphans)}"
    )
    lines.append(
        f"  Neo4j orphans    : {len(orphan_report.neo4j_orphans)}"
    )
    lines.append(
        f"  Manifest-only    : {len(orphan_report.manifest_only)}"
    )
    lines.append("")

    if orphan_report.weaviate_orphans:
        lines.append("Weaviate orphans:")
        for key in orphan_report.weaviate_orphans:
            lines.append(f"  - {key}")
        lines.append("")

    if orphan_report.minio_orphans:
        lines.append("MinIO orphans:")
        for key in orphan_report.minio_orphans:
            lines.append(f"  - {key}")
        lines.append("")

    if orphan_report.neo4j_orphans:
        lines.append("Neo4j orphans:")
        for key in orphan_report.neo4j_orphans:
            lines.append(f"  - {key}")
        lines.append("")

    if orphan_report.manifest_only:
        lines.append("Manifest-only keys (no live store data):")
        for key in orphan_report.manifest_only:
            lines.append(f"  - {key}")
        lines.append("")

    # GC summary (optional)
    if gc_report is not None:
        lines.append("=== GC Summary ===")
        lines.append(f"  Mode       : {'dry-run' if gc_report.dry_run else 'live'}")
        lines.append(f"  Soft-deleted    : {gc_report.soft_deleted}")
        lines.append(f"  Hard-deleted    : {gc_report.hard_deleted}")
        lines.append(f"  Retention purged: {gc_report.retention_purged}")
        lines.append("")

        if gc_report.per_document:
            lines.append("Per-document status:")
            for key, status in gc_report.per_document.items():
                ok = all(
                    [status.weaviate, status.minio, status.neo4j, status.manifest]
                )
                marker = "OK" if ok else "PARTIAL"
                lines.append(
                    f"  [{marker}] {key}"
                    f"  weaviate={status.weaviate}"
                    f" minio={status.minio}"
                    f" neo4j={status.neo4j}"
                    f" manifest={status.manifest}"
                )
                for err in status.errors:
                    lines.append(f"    ERROR: {err}")
            lines.append("")

    return "\n".join(lines)


def format_json(
    orphan_report: OrphanReport,
    gc_report: Optional[GCReport] = None,
    *,
    indent: int = 2,
) -> str:
    """Render *orphan_report* (and optional *gc_report*) as a JSON string.

    The JSON is deterministic: keys are sorted and the timestamp is included at
    the top level for reproducibility in tests.

    Args:
        orphan_report: Orphan detection report.
        gc_report: Optional GC execution report.
        indent: JSON indentation level (default 2).

    Returns:
        A JSON-serialised string.
    """
    ts = datetime.now(timezone.utc).isoformat()
    payload: dict = {
        "generated_at": ts,
        "orphans": {
            "weaviate": orphan_report.weaviate_orphans,
            "minio": orphan_report.minio_orphans,
            "neo4j": orphan_report.neo4j_orphans,
            "manifest_only": orphan_report.manifest_only,
        },
    }
    if gc_report is not None:
        payload["gc"] = {
            "dry_run": gc_report.dry_run,
            "soft_deleted": gc_report.soft_deleted,
            "hard_deleted": gc_report.hard_deleted,
            "retention_purged": gc_report.retention_purged,
            "per_document": {
                k: asdict(v) for k, v in gc_report.per_document.items()
            },
        }
    return json.dumps(payload, indent=indent, sort_keys=True)
