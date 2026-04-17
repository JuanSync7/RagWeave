# @summary
# Priority level constants and trigger-type routing helpers for the dual-queue
# ingestion orchestration layer.
# Exports: PRIORITY_HIGH, PRIORITY_MEDIUM, PRIORITY_LOW,
#          TRIGGER_SINGLE, TRIGGER_BATCH, TRIGGER_BACKGROUND,
#          QUEUE_USER, QUEUE_BACKGROUND,
#          trigger_to_priority, trigger_to_queue
# Deps: os, config.settings (TEMPORAL_TASK_QUEUE for legacy fallback)
# @end-summary
"""Ingestion workflow priority levels and trigger-type routing constants.

Priority is assigned implicitly based on the ingestion trigger type.
Lower numeric values indicate higher scheduling priority.  There is no
user-facing mechanism to set priority directly (FR-3565).

The numeric values below are defaults; they can be overridden via the
environment variables RAG_INGEST_PRIORITY_HIGH, RAG_INGEST_PRIORITY_MEDIUM,
and RAG_INGEST_PRIORITY_LOW (FR-3572).

Queue names are resolved at import time from environment variables.  When
the dual-queue env vars are unset the module falls back to the legacy
``TEMPORAL_TASK_QUEUE`` value from ``config.settings`` (FR-3553).

Trigger-type string constants
------------------------------
These values flow through ``IngestDocumentArgs.trigger_type`` and
``IngestDirectoryArgs.trigger_type``.  They must be used verbatim at
workflow submission call sites (CLI, API, background scheduler).

    TRIGGER_SINGLE      — Single-document, user-initiated upload.
    TRIGGER_BATCH       — Directory / batch ingest (parent and child workflows).
    TRIGGER_BACKGROUND  — System-initiated background work (GC, rehash,
                          schema migration, scheduled re-ingestion).

Queue routing (FR-3550, FR-3551, FR-3552, Table 5.4)
-----------------------------------------------------
    TRIGGER_SINGLE      → QUEUE_USER       / PRIORITY_HIGH
    TRIGGER_BATCH       → QUEUE_USER       / PRIORITY_MEDIUM
    TRIGGER_BACKGROUND  → QUEUE_BACKGROUND / PRIORITY_LOW
"""

from __future__ import annotations

import os

from config.settings import TEMPORAL_TASK_QUEUE as _LEGACY_QUEUE

# ---------------------------------------------------------------------------
# Priority constants (FR-3567, FR-3572)
# ---------------------------------------------------------------------------

PRIORITY_HIGH: int = int(os.environ.get("RAG_INGEST_PRIORITY_HIGH", "1"))
"""Priority 1 (default) — single-document, user-initiated workflows."""

PRIORITY_MEDIUM: int = int(os.environ.get("RAG_INGEST_PRIORITY_MEDIUM", "2"))
"""Priority 2 (default) — batch directory parent/child workflows."""

PRIORITY_LOW: int = int(os.environ.get("RAG_INGEST_PRIORITY_LOW", "3"))
"""Priority 3 (default) — background system-initiated workflows."""

# ---------------------------------------------------------------------------
# Trigger-type string constants (FR-3565, FR-3566)
# ---------------------------------------------------------------------------

TRIGGER_SINGLE: str = "single"
"""Single-document user upload — routed to user queue at high priority."""

TRIGGER_BATCH: str = "batch"
"""Directory / batch ingest — routed to user queue at medium priority."""

TRIGGER_BACKGROUND: str = "background"
"""System-initiated background work — routed to background queue at low priority."""

# ---------------------------------------------------------------------------
# Queue name aliases (FR-3570)
# Resolved from env vars; fall back to the legacy single queue (FR-3553).
# The manager will set these via config/settings.py — until then the env
# vars are read directly here so this module is self-contained.
# ---------------------------------------------------------------------------

_raw_user_queue: str = os.environ.get("RAG_INGEST_USER_TASK_QUEUE", "")
_raw_bg_queue: str = os.environ.get("RAG_INGEST_BACKGROUND_TASK_QUEUE", "")

QUEUE_USER: str = _raw_user_queue if _raw_user_queue else _LEGACY_QUEUE
"""User-queue name string (resolved from RAG_INGEST_USER_TASK_QUEUE,
defaulting to the legacy queue when dual-queue mode is not active)."""

QUEUE_BACKGROUND: str = _raw_bg_queue if _raw_bg_queue else _LEGACY_QUEUE
"""Background-queue name string (resolved from RAG_INGEST_BACKGROUND_TASK_QUEUE,
defaulting to the legacy queue when dual-queue mode is not active)."""

# ---------------------------------------------------------------------------
# Routing helpers (FR-3565, FR-3566, FR-3567)
# ---------------------------------------------------------------------------

_TRIGGER_PRIORITY_MAP: dict[str, int] = {
    TRIGGER_SINGLE: PRIORITY_HIGH,
    TRIGGER_BATCH: PRIORITY_MEDIUM,
    TRIGGER_BACKGROUND: PRIORITY_LOW,
}

_TRIGGER_QUEUE_MAP: dict[str, str] = {
    TRIGGER_SINGLE: QUEUE_USER,
    TRIGGER_BATCH: QUEUE_USER,
    TRIGGER_BACKGROUND: QUEUE_BACKGROUND,
}


def trigger_to_priority(trigger_type: str) -> int:
    """Return the Temporal scheduling priority for *trigger_type*.

    Falls back to ``PRIORITY_LOW`` for unrecognised trigger strings so
    that unknown callers do not accidentally receive elevated priority.

    Args:
        trigger_type: One of ``TRIGGER_SINGLE``, ``TRIGGER_BATCH``, or
            ``TRIGGER_BACKGROUND``.

    Returns:
        Integer priority value (lower = higher scheduling precedence).
    """
    return _TRIGGER_PRIORITY_MAP.get(trigger_type, PRIORITY_LOW)


def trigger_to_queue(trigger_type: str) -> str:
    """Return the Temporal task queue name for *trigger_type*.

    Falls back to ``QUEUE_BACKGROUND`` for unrecognised trigger strings
    so that unknown callers do not pollute the user queue.

    Args:
        trigger_type: One of ``TRIGGER_SINGLE``, ``TRIGGER_BATCH``, or
            ``TRIGGER_BACKGROUND``.

    Returns:
        Task queue name string (e.g. ``"ingest-user"``).
    """
    return _TRIGGER_QUEUE_MAP.get(trigger_type, QUEUE_BACKGROUND)
