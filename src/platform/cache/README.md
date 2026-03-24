<!-- @summary
Response cache provider: in-memory TTL backend and optional Redis backend. Singleton factory pattern via get_cache().
@end-summary -->

# platform/cache

## Overview

This package provides a pluggable response cache for RAG query results, used by the retrieval pipeline to avoid re-running expensive queries.

## Files

| File | Purpose | Key Exports |
| --- | --- | --- |
| `provider.py` | Cache backend factory with singleton `get_cache()`. Backends: in-memory TTL, Redis, no-op. | `CacheProvider`, `InMemoryTTLCache`, `RedisCache`, `NoopCache`, `get_cache` |
| `__init__.py` | Package facade | re-exports from `provider.py` |

## Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `RAG_CACHE_ENABLED` | `true` | Enable/disable caching |
| `RAG_CACHE_PROVIDER` | `redis` | Backend: `memory` or `redis` |
| `RAG_CACHE_TTL_SECONDS` | `120` | Cache TTL in seconds |
| `RAG_CACHE_REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |

## Usage

```python
from src.platform.cache import get_cache

cache = get_cache()
cached = cache.get(key)
if cached is None:
    result = run_query(...)
    cache.set(key, result)
```
