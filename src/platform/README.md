<!-- @summary
Cross-cutting platform services: security/auth, rate limits, cache, conversation memory, observability, reliability, Prometheus metrics, pipeline timing, CLI helpers, and slash-command contracts.
@end-summary -->

# src/platform

## Overview

This package provides all cross-cutting services consumed by the API server, retrieval runtime, and ingestion pipeline. Platform services are intentionally dependency-free toward feature packages — they can be imported by any layer without creating circular dependencies.

## Package-Level Files

| File | Purpose | Key Exports |
| --- | --- | --- |
| `metrics.py` | Prometheus metrics registry (API, pipeline, cache, memory counters/histograms) | `REQUESTS_TOTAL`, `REQUEST_LATENCY_MS`, `PIPELINE_STAGE_MS`, `CACHE_HITS`, `render_metrics` |
| `timing.py` | Centralized pipeline stage timing pool | `TimingPool` |
| `validation.py` | Small boundary validation helpers | `validate_alpha`, `validate_positive_int`, `validate_filter_value`, `validate_documents_dir` |
| `command_catalog.py` | Slash-command catalog — single source of truth for CLI and web console commands | `CommandSpec`, `list_command_specs`, `get_command_spec`, `build_registry` |
| `command_runtime.py` | Server-side command intent dispatch for console endpoints | `dispatch_command` |
| `cli_interactive.py` | Terminal interactive slash-command selection with live-filtering dropdown and tab completion | `interactive_command_select`, `get_input_with_menu`, `setup_tab_completion` |
| `cli_log_formatting.py` | Terminal log output formatting helpers | (formatting functions) |

## Subdirectories

| Directory | Purpose |
| --- | --- |
| `cache/` | Response cache (in-memory TTL or Redis backend) |
| `limits/` | Fixed-window rate limiter |
| `llm/` | Unified LLM provider backed by LiteLLM Router |
| `memory/` | Tenant-aware conversation memory (Redis canonical backend) |
| `observability/` | Tracing provider (Langfuse or no-op) |
| `reliability/` | Retry provider (local exponential-backoff or Temporal) |
| `schemas/` | Shared typed contracts for observability and reliability |
| `security/` | Auth, API keys, quotas, RBAC, tenancy, and secrets |
| `token_budget/` | Token counting and context window budget calculation |

## Dependency Notes

- Platform modules are imported by `server/`, `src/retrieval/`, and `src/ingest/`.
- Platform modules do **not** import from `src/ingest/` or `src/retrieval/` to avoid circular dependencies.
- `metrics.py` and `timing.py` are imported by retrieval, server, and ingestion stage modules.
- `command_catalog.py` is the shared contract between `cli.py`, `server/cli_client.py`, and the web console.
