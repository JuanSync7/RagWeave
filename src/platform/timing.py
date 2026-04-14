# @summary
# Centralized pipeline timing pool for recording, aggregating, and
# exporting stage-level execution metrics across all pipeline modules.
# Exports: TimingPool
# Deps: time, logging, src.platform.metrics
# @end-summary
"""Centralized timing pool for pipeline stage metrics."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

logger = logging.getLogger("rag.timing")


def measure_ms(started_at: float) -> float:
    """Compute elapsed time in milliseconds.

    Args:
        started_at: A `time.perf_counter()` timestamp captured at start.

    Returns:
        Elapsed milliseconds since `started_at`, rounded to 0.1ms.
    """
    return round((time.perf_counter() - started_at) * 1000, 1)


class TimingPool:
    """Self-expanding timing pool that any pipeline module can record into.

    Usage:
        pool = TimingPool(overall_budget_ms=30000)

        # Record from a start time
        t0 = time.perf_counter()
        do_work()
        pool.record("query_processing", "retrieval", started_at=t0, budget_ms=5000)

        # Or record a known duration
        pool.record("input_rail_intent", "guardrails", ms=42.3)

        # Get totals
        totals = pool.totals()  # {"retrieval_ms": ..., "generation_ms": ..., ...}

        # Check budget
        pool.is_budget_exhausted()  # True if overall elapsed > overall_budget_ms

        # Export for RAGResponse
        pool.entries()   # list[Dict] for stage_timings field
        pool.totals()    # Dict for timing_totals field
    """

    def __init__(
        self,
        overall_budget_ms: float = 30_000,
        stage_budgets: Optional[dict[str, float]] = None,
    ) -> None:
        """Create a timing pool.

        Args:
            overall_budget_ms: Max allowed wall-clock time for the whole request.
            stage_budgets: Optional per-stage budgets (milliseconds) keyed by stage name.
        """
        self._entries: list[dict[str, Any]] = []
        self._overall_budget_ms = overall_budget_ms
        self._stage_budgets = stage_budgets or {}
        self._pipeline_start = time.perf_counter()
        self._budget_exhausted = False
        self._budget_exhausted_stage: Optional[str] = None
        self._prometheus = _get_prometheus_histogram()

    def record(
        self,
        stage: str,
        bucket: str,
        *,
        started_at: Optional[float] = None,
        ms: Optional[float] = None,
        budget_ms: Optional[float] = None,
    ) -> dict[str, Any]:
        """Record a stage timing entry.

        Provide either `started_at` (perf_counter timestamp) or `ms` (duration).
        `budget_ms` overrides the stage budget from __init__ for this entry.

        Args:
            stage: Stage name (e.g. "query_processing").
            bucket: High-level bucket (e.g. "retrieval", "generation").
            started_at: Optional `time.perf_counter()` timestamp captured at start.
            ms: Optional duration in milliseconds (if `started_at` not provided).
            budget_ms: Optional override for the stage budget for this entry.

        Returns:
            The recorded entry dictionary.

        Raises:
            ValueError: If neither `started_at` nor `ms` is provided.
        """
        if ms is None:
            if started_at is None:
                raise ValueError("Provide either 'started_at' or 'ms'")
            ms = measure_ms(started_at)
        else:
            ms = round(ms, 1)

        effective_budget = budget_ms if budget_ms is not None else self._stage_budgets.get(stage)
        within_budget = ms <= float(effective_budget) if effective_budget is not None else True

        entry: dict[str, Any] = {
            "stage": stage,
            "bucket": bucket,
            "ms": ms,
            "budget_ms": effective_budget,
            "within_budget": within_budget,
        }
        self._entries.append(entry)

        # Observe on Prometheus histogram
        if self._prometheus is not None:
            self._prometheus.labels(stage=stage, bucket=bucket).observe(ms)

        return entry

    def totals(self) -> dict[str, float]:
        """Aggregate milliseconds by bucket, plus overall total.

        Returns:
            A mapping like `{"retrieval_ms": 12.3, "generation_ms": 45.6, "total_ms": 57.9}`.
        """
        buckets: dict[str, float] = {}
        for entry in self._entries:
            bkt = entry["bucket"]
            buckets[bkt] = buckets.get(bkt, 0.0) + float(entry["ms"])

        result: dict[str, float] = {}
        total = 0.0
        for bkt, val in sorted(buckets.items()):
            key = f"{bkt}_ms"
            result[key] = round(val, 1)
            total += val
        result["total_ms"] = round(total, 1)
        return result

    def entries(self) -> list[dict[str, Any]]:
        """Return all recorded timing entries.

        Returns:
            A list of entry dictionaries for response payloads.
        """
        return list(self._entries)

    def elapsed_ms(self) -> float:
        """Return wall-clock milliseconds since pool creation."""
        return measure_ms(self._pipeline_start)

    def is_overall_budget_exhausted(self) -> bool:
        """Check if total elapsed time exceeds the overall budget."""
        return self.elapsed_ms() > self._overall_budget_ms

    def mark_budget_exhausted(self, stage: str) -> None:
        """Mark that budget was exhausted at the given stage.

        Args:
            stage: Stage name where the budget was determined to be exhausted.
        """
        self._budget_exhausted = True
        self._budget_exhausted_stage = stage

    @property
    def pipeline_start(self) -> float:
        """The perf_counter timestamp when the pool was created."""
        return self._pipeline_start

    @property
    def budget_exhausted(self) -> bool:
        """Whether a budget exhaustion flag was set."""
        return self._budget_exhausted

    @property
    def budget_exhausted_stage(self) -> Optional[str]:
        """The stage name that triggered budget exhaustion, if any."""
        return self._budget_exhausted_stage

    def check_stage_budget(self, stage: str) -> bool:
        """Check if the last entry for `stage` exceeded its budget.

        Args:
            stage: Stage name to check.

        Returns:
            True if the last entry exceeded its budget or the overall budget is exhausted.
        """
        for entry in reversed(self._entries):
            if entry["stage"] == stage:
                return not entry["within_budget"] or self.is_overall_budget_exhausted()
        return False

    def log_summary(self) -> None:
        """Log a one-line summary of all timings."""
        if not self._entries:
            return
        parts = " | ".join(
            f"{e['bucket']}.{e['stage']}: {float(e['ms']):.0f}ms"
            for e in self._entries
        )
        totals = self.totals()
        bucket_parts = " | ".join(
            f"{k}: {v:.0f}ms" for k, v in totals.items()
        )
        logger.info("Pipeline timings — %s | %s", parts, bucket_parts)


def _get_prometheus_histogram():
    """Lazy-import to avoid import errors when prometheus_client isn't available."""
    try:
        from src.platform.metrics import PIPELINE_STAGE_MS
        return PIPELINE_STAGE_MS
    except Exception:
        return None
