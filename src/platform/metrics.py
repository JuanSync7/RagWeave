# @summary
# Prometheus metrics registry for API, pipeline, cache, and memory.
# Exports: REQUESTS_TOTAL, REQUEST_LATENCY_MS, RATE_LIMIT_REJECTS, OVERLOAD_REJECTS,
#          INFLIGHT_REQUESTS, PIPELINE_STAGE_MS, CACHE_HITS, CACHE_MISSES,
#          MEMORY_OP_MS, MEMORY_SUMMARY_TRIGGERS, render_metrics
# Deps: prometheus_client
# @end-summary
"""Prometheus metrics registry for platform services.

This module defines the shared Prometheus metrics used by the API server and
runtime components. Importing this module registers metrics in the default
Prometheus registry.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

REQUESTS_TOTAL = Counter(
    "rag_api_requests_total",
    "Total API requests",
    ["endpoint", "method", "status"],
)

REQUEST_LATENCY_MS = Histogram(
    "rag_api_request_latency_ms",
    "API request latency in milliseconds",
    ["endpoint", "method"],
    buckets=(50, 100, 250, 500, 1000, 2000, 5000, 10000, 30000, 60000),
)

RATE_LIMIT_REJECTS = Counter(
    "rag_rate_limit_rejections_total",
    "Rejected requests due to rate limiting",
    ["endpoint"],
)

OVERLOAD_REJECTS = Counter(
    "rag_api_overload_rejections_total",
    "Rejected requests due to API overload protection",
    ["endpoint"],
)

INFLIGHT_REQUESTS = Gauge(
    "rag_api_inflight_requests",
    "Current number of in-flight API requests within overload guard",
)

PIPELINE_STAGE_MS = Histogram(
    "rag_pipeline_stage_ms",
    "Pipeline stage latency in milliseconds",
    ["stage", "bucket"],
    buckets=(10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000),
)

CACHE_HITS = Counter("rag_cache_hits_total", "Cache hit count", ["layer"])
CACHE_MISSES = Counter("rag_cache_misses_total", "Cache miss count", ["layer"])
MEMORY_OP_MS = Histogram(
    "rag_memory_operation_ms",
    "Conversation memory operation latency in milliseconds",
    ["operation"],
    buckets=(1, 5, 10, 25, 50, 100, 250, 500, 1000, 3000),
)
MEMORY_SUMMARY_TRIGGERS = Counter(
    "rag_memory_summary_triggers_total",
    "Count of rolling-summary trigger events",
    ["reason"],
)


def render_metrics() -> tuple[bytes, str]:
    """Render all registered Prometheus metrics.

    Returns:
        A `(payload, content_type)` tuple suitable for returning from an HTTP
        metrics endpoint.
    """
    payload = generate_latest()
    return payload, CONTENT_TYPE_LATEST

