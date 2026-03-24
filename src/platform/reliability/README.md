<!-- @summary
Retry provider: local exponential-backoff or Temporal activity retry semantics. Defines RetryPolicy and RetryProvider contracts.
@end-summary -->

# platform/reliability

## Overview

This package provides pluggable retry behavior for external service calls (LLM, vector store, embeddings). The provider is selected at runtime so the same application code works both in local processes and inside Temporal workers.

## Files

| File | Purpose | Key Exports |
| --- | --- | --- |
| `contracts.py` | Abstract `RetryProvider` protocol | `RetryProvider` |
| `providers.py` | Provider factory: selects local or Temporal | `get_retry_provider` |
| `local_retry.py` | Local exponential-backoff retry implementation | `LocalRetryProvider` |
| `temporal_retry.py` | Temporal activity retry semantics (defers to Temporal's retry engine) | `TemporalRetryProvider` |
| `__init__.py` | Package facade | `get_retry_provider` |

## Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `RAG_RETRY_PROVIDER` | `local` | Backend: `local` or `temporal` |

## Retry Policy Defaults

From `schemas/reliability.py` `RetryPolicy`:
- `max_attempts`: 3
- `initial_backoff_seconds`: 0.5
- `max_backoff_seconds`: 5.0
- `backoff_multiplier`: 2.0
