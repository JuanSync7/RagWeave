"""Prometheus metrics helpers."""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

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

PIPELINE_STAGE_MS = Histogram(
    "rag_pipeline_stage_ms",
    "Pipeline stage latency in milliseconds",
    ["stage", "bucket"],
    buckets=(10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000),
)

CACHE_HITS = Counter("rag_cache_hits_total", "Cache hit count", ["layer"])
CACHE_MISSES = Counter("rag_cache_misses_total", "Cache miss count", ["layer"])


def render_metrics() -> tuple[bytes, str]:
    payload = generate_latest()
    return payload, CONTENT_TYPE_LATEST

