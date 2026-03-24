<!-- @summary
In-memory fixed-window rate limiter. Thread-safe, keyed by arbitrary string (e.g. tenant ID or IP address).
@end-summary -->

# platform/limits

## Overview

This package provides a simple in-memory fixed-window rate limiter used by the API server to enforce per-principal request limits.

## Files

| File | Purpose | Key Exports |
| --- | --- | --- |
| `provider.py` | Thread-safe fixed-window rate limiter keyed by string | `LimitResult`, `InMemoryRateLimiter` |
| `__init__.py` | Package facade | re-exports from `provider.py` |

## Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `RAG_RATE_LIMIT_ENABLED` | `true` | Enable/disable rate limiting |
| `RAG_RATE_LIMIT_REQUESTS_PER_MINUTE` | `60` | Per-principal fixed-window limit |
| `RAG_RATE_LIMIT_WINDOW_SECONDS` | `60` | Window size in seconds |

## Usage

```python
from src.platform.limits import InMemoryRateLimiter

limiter = InMemoryRateLimiter(limit=60, window_seconds=60)
result = limiter.check(key="tenant:abc")
if not result.allowed:
    raise TooManyRequestsError(retry_after=result.retry_after_seconds)
```
